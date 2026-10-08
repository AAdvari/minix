from typing import Any, Self, Type, TypeVar, cast

from minix.core.utils.singleton import SingletonMeta

T = TypeVar("T")


class Registry(metaclass=SingletonMeta):

    def __init__(self):
        self.registry: dict[Any, Any] = {}

    def register(
        self,
        key: Any,
        value: Any,
        salt: str | None = None,
    ) -> Self:
        if salt is not None:
            self.registry[f"{key}_{salt}"] = value
        else:
            self.registry[key] = value
        return self

    def get(self, key: Type[T], salt: str | None = None) -> T:
        if salt is not None:
            return cast(T, self.registry.get(f"{key}_{salt}"))
        return cast(T, self.registry.get(key))
