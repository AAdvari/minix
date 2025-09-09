from typing import TypeVar

from src.minix.core.entity import RedisEntity
from src.minix.core.service import Service


T = TypeVar('T', bound=RedisEntity)
class RedisService(Service[T]):
    pass