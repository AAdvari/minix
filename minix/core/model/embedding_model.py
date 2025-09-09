from abc import ABC, abstractmethod
import numpy as np
from minix.core.model import Model


class EmbeddingModel(Model, ABC):

    def predict(self, text: str):
        """Predict using the model"""
        return self.embed(text)


    @abstractmethod
    def embed(self, text: str) -> np.ndarray:
        raise NotImplementedError("The embed method must be implemented by subclasses.")

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Embed a batch of texts"""
        raise NotImplementedError("The embed_batch method must be implemented by subclasses.")
