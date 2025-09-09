from typing import Self, Type, TypeVar
from minix.core.utils.singleton import SingletonMeta

T = TypeVar('T')


class Registry(metaclass=SingletonMeta):

    def __init__(self):
        self.registry = {}

    def register(
            self,
            key: T,
            value,
            salt = None
    ) -> Self:
        if salt is not None:
            self.registry[f'{key}_{salt}'] = value
        else:
            self.registry[key] = value
        return self

    def get(self, key: Type[T], salt = None)-> T:
        if salt is not None:
            return self.registry.get(f'{key}_{salt}')
        else:
            return self.registry.get(key)
