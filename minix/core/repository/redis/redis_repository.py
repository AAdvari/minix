from typing import TypeVar, Type

from minix.core.entity import RedisEntity
from minix.core.repository import Repository
from redis import Redis

T = TypeVar('T', bound=RedisEntity)
class RedisRepository(Repository[T]):
    def __init__(self, entity: Type[T], redis_client: Redis):
        super().__init__(entity)
        self.redis_client = redis_client


