from typing import TypeVar, List, Tuple

from minix.core.entity import PGVectorEntity
from minix.core.repository.pgvector.pgvector_repository import PGVectorRepository
from minix.core.service import SqlService

T = TypeVar('T', bound=PGVectorEntity)


class PGVectorService(SqlService[T]):
    def __init__(self, repository: PGVectorRepository[T]):
        super().__init__(repository)
        self.repository = repository

    def get_repository(self) -> PGVectorRepository[T]:
        return self.repository

    def get_knn(self, entity: T, top_k: int = 10) -> List[T]:
        return self.get_repository().search(entity.vector, top_k)

    def search(
            self,
            vector: List[float],
            top_k: int = 10,
            max_distance: float | None = None,
            **kwargs
    ) -> List[T]:
        return self.get_repository().search(vector, top_k, max_distance, **kwargs)

    def search_with_distance(
            self,
            vector: List[float],
            top_k: int = 10,
            max_distance: float | None = None,
            **kwargs
    ) -> List[Tuple[T, float]]:
        return self.get_repository().search_with_distance(vector, top_k, max_distance, **kwargs)
