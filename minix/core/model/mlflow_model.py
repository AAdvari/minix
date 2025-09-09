import pickle
import tempfile
import time
from abc import abstractmethod
from typing import List, Dict
import mlflow.pyfunc
from mlflow.tracking import MlflowClient
from mlflow.exceptions import RestException
import torch
from loguru import logger
import os

from minix.core.model import Model


class MlflowModel(mlflow.pyfunc.PythonModel):

    def __init__(
            self,
            name: str,
            packages: list = None,
            device: str = "cuda" if torch.cuda.is_available() else "cpu",
            version: int = 1
    ):
        self.device = device
        self.packages = packages
        self.version = version
        logger.info('MLFLOW_TRACKING_URL', os.getenv("MLFLOW_TRACKING_URL"))
        mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URL"))
        logger.info("connected")
        if packages is None:
            self.packages = [
                'torch',
                'numpy',
                'Pillow',
                'mlflow',
            ]


        self.name = name


    @abstractmethod
    def get_model(self) -> Model:
        pass

    def get_model_uri(self) -> str:
        return f"models:/{self.name}/{self.version}"



    def log_model(self, artifact_path = 'model')-> str:
        logger.info(f"Logging model {self.name} to MLflow.")

        with mlflow.start_run() as run:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pkl') as tmp_file:
                pickle.dump(self, tmp_file)
                tmp_path = tmp_file.name

            mlflow.pyfunc.log_model(
                artifact_path=artifact_path,
                python_model=self,
                artifacts={
                    "model_name": tmp_path,
                },
                conda_env={
                    'name': 'model_env',
                    'channels': ['defaults'],
                    'dependencies': [
                        f"python={os.getenv('PYTHON_VERSION')}",
                        'pip',
                        {
                            'pip': self.packages
                        }
                    ]
                }
            )
            os.remove(tmp_path)
            return f"runs:/{run.info.run_id}/{artifact_path}"


    def is_model_registered(self)-> bool:
        """Check if the model exists"""
        client = MlflowClient()
        try:
            client.get_model_version(self.name, str(self.version))
            return True
        except Exception as e:
            print("Exception", e)
            if isinstance(e, RestException) and e.error_code == "RESOURCE_DOES_NOT_EXIST":
                return False
            else:
                logger.error(f"Error checking model existence: {str(e)}")
                raise e


    def register_model(self):
        logger.info(f"Registering model {self.name}.")
        model_uri = self.log_model()
        mlflow.register_model(model_uri=model_uri, name=self.name)
        logger.info(f"Model {self.name} registered successfully.")


    def get_next_model_version(self, model_name: str) -> int:
        client = MlflowClient()
        versions = client.search_model_versions(f"name='{model_name}'")
        return max((int(v.version) for v in versions), default=0) + 1


    def generate_prediction_run_name(self):
        return f"prediction-{self.name}-{self.version}-{time.strftime('%Y-%m-%d-%H-%M-%S')}"


    def load_model(self):
        if not self.is_model_registered():
            logger.info(f"Model {self.name}/{self.version} is not registered. Registering model.")
            next_version = self.get_next_model_version(self.name)
            if self.version == int(next_version):
                self.register_model()
            else:
                raise Exception(f'Next valid version is {next_version} you provided {self.version}')
        try:
            model = mlflow.pyfunc.load_model(self.get_model_uri())
            logger.info(f"Model loaded from {self.get_model_uri()}")
            return model
        except Exception as e:
            logger.error(f"Error loading model from {self.get_model_uri()}: {str(e)}")
            raise


    @abstractmethod
    def predict(self, model_input: List[Dict[str, str]]):
        pass

