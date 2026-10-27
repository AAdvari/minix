from typing import TypeVar, Type, List, Tuple

from sqlalchemy import text
from sqlalchemy.sql.elements import ColumnElement

from minix.core.entity import PGVectorEntity
from minix.core.connectors.sql_connector import SqlConnector
from minix.core.repository import SqlRepository

T = TypeVar('T', bound=PGVectorEntity)


class PGVectorRepository(SqlRepository[T]):
    # Distance names follow Qdrant's, mapped to pgvector's comparator methods.
    DISTANCES = {
        'Cosine': 'cosine_distance',
        'Euclid': 'l2_distance',
        'Dot': 'max_inner_product',
        'Manhattan': 'l1_distance',
    }

    def __init__(self, entity: Type[T], sql_connector: SqlConnector):
        super().__init__(entity, sql_connector)
        self.entity = entity

    def create_extension(self) -> None:
        with self.get_session() as session:
            session.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
            session.commit()

    def get_distance(self) -> str:
        return 'Cosine'

    def distance_to(self, vector: List[float]) -> ColumnElement[float]:
        distance = self.get_distance()
        if distance not in self.DISTANCES:
            raise ValueError(f'Distance not supported: {distance!r}')
        return getattr(self.entity.vector, self.DISTANCES[distance])(vector)

    def search_with_distance(
            self,
            vector: List[float],
            top_k: int = 10,
            max_distance: float | None = None,
            **kwargs
    ) -> List[Tuple[T, float]]:
        # `max_distance` bounds the pgvector distance; for 'Dot' that is the
        # negative inner product.
        distance = self.distance_to(vector)
        with self.get_session() as session:
            query = session.query(self.entity, distance.label('distance')).filter_by(**kwargs)
            if max_distance is not None:
                query = query.filter(distance <= max_distance)
            rows = query.order_by(distance).limit(top_k).all()
        return [(entity, value) for entity, value in rows]

    def search(
            self,
            vector: List[float],
            top_k: int = 10,
            max_distance: float | None = None,
            **kwargs
    ) -> List[T]:
        return [entity for entity, _ in self.search_with_distance(vector, top_k, max_distance, **kwargs)]
