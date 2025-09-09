from abc import ABC, abstractmethod
from typing import Dict


class Model(ABC):

    @abstractmethod
    def get_model_name(self):
        """Get model name"""
        pass

    @abstractmethod
    def predict(self, model_input: Dict):
        """Predict using the model"""
        pass


    @abstractmethod
    def set_device(self, device: str):
        """Set device for the model"""
        pass
