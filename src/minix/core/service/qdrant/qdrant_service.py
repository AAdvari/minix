from typing import TypeVar, List

from minix.core.entity import QdrantEntity
from minix.core.repository.qdrant.qdrant_repository import QdrantRepository
from minix.core.service import Service

T = TypeVar('T', bound=QdrantEntity)

class QdrantService(Service[T]):
    def __init__(self, repository: QdrantRepository[QdrantEntity]):
        super().__init__(repository)
        self.repository = repository

    def get_repository(self) -> QdrantRepository[QdrantEntity]:
        return self.repository


    async def get_knn(self, entity: T, top_k: int = 10) -> List[QdrantEntity]:
        result = await self.get_repository().query(entity, top_k)
        return result

    async def insert(self, entities: List[T]) -> None:
        await self.get_repository().insert(entities)

    async def delete(self, ids: List[str]) -> None:
        await self.get_repository().delete(entity_ids=ids)