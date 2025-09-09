import importlib.util
from .model import Model
from .model_registry import ModelRegistry

if importlib.util.find_spec('mlflow') and importlib.util.find_spec('torch'): # Check if mlflow is installed
     from .mlflow_model import MlflowModel
if importlib.util.find_spec('numpy'):
     from .embedding_model import EmbeddingModel

