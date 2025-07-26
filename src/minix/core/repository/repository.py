from typing import Type, Generic, TypeVar
from minix.core.entity import Entity

T = TypeVar('T', bound=Entity)

class Repository(Generic[T]):
    def __init__(self, entity: Type[T]):
        self.entity = entity