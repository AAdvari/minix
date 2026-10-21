import threading
from typing import Any, Callable, Self, Type, TypeVar, cast

from minix.core.utils.singleton import SingletonMeta

T = TypeVar("T")


class Registry(metaclass=SingletonMeta):

    def __init__(self):
        self.registry: dict[Any, Any] = {}
        self._factories: dict[Any, Callable[[], Any]] = {}
        self._factory_lock = threading.Lock()

    def register(
        self,
        key: Any,
        value: Any,
        salt: str | None = None,
    ) -> Self:
        storage_key = self._storage_key(key, salt)
        self._factories.pop(storage_key, None)
        self.registry[storage_key] = value
        return self

    def get(self, key: Type[T], salt: str | None = None) -> T:
        storage_key = self._storage_key(key, salt)
        if storage_key not in self.registry and storage_key in self._factories:
            self._build(storage_key)
        return cast(T, self.registry.get(storage_key))

    def _register_factory(
        self,
        key: Any,
        factory: Callable[[], Any],
        salt: str | None = None,
    ) -> Self:
        """Register ``factory`` to build the value on the first ``get()``."""
        storage_key = self._storage_key(key, salt)
        self.registry.pop(storage_key, None)
        self._factories[storage_key] = factory
        return self

    def _build(self, storage_key: Any) -> None:
        with self._factory_lock:
            factory = self._factories.get(storage_key)
            if factory is None or storage_key in self.registry:
                return
            self.registry[storage_key] = factory()
            del self._factories[storage_key]

    @staticmethod
    def _storage_key(key: Any, salt: str | None) -> Any:
        return f"{key}_{salt}" if salt is not None else key
