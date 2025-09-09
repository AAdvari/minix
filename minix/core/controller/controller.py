from abc import abstractmethod
from typing import List
from fastapi import APIRouter


class Controller:
    def __init__(self, tags: List[str] = None):
        self.router = APIRouter(prefix= self.get_prefix(), tags=tags)
        self.define_routes()


    @property
    def get_router(self):
        return self.router


    @abstractmethod
    def get_prefix(self):
        """
        Returns the prefix for the controller's routes.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement this method.")


    @abstractmethod
    def define_routes(self):
        """
        Defines the routes for the controller.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement this method.")