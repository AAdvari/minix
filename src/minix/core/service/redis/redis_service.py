from typing import TypeVar

from minix.core.entity import RedisEntity
from minix.core.service import Service


T = TypeVar('T', bound=RedisEntity)
class RedisService(Service[T]):
    pass