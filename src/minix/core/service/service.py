from typing import Generic, TypeVar

from src.minix.core.entity import Entity
from src.minix.core.repository import Repository


T = TypeVar('T', bound=Entity)
class Service(Generic[T]):
    def __init__(self, repository: Repository[T]):
        self.repository = repository

    def get_repository(self)-> Repository[T]:
        return self.repository







