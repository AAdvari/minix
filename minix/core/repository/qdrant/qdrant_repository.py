from typing import TypeVar, Type, List
from qdrant_client.grpc import PointStruct
from minix.core.entity import QdrantEntity
from minix.core.connectors.qdrant_connector import QdrantConnector
from minix.core.repository import Repository

T = TypeVar('T', bound=QdrantEntity)
class QdrantRepository(Repository[T]):

    def __init__(self, entity: Type[T], qdrant_connector: QdrantConnector):
        super().__init__(entity)
        self.entity = entity
        self.connector = qdrant_connector
        if not self.connector.is_connected():
            raise RuntimeError("QdrantConnector is not connected. Please connect before using the repository.")
        self.client = self.connector.client

    async def insert(self, entities: List[T]) -> None:
        points = [
            PointStruct(
                id=entity.id,
                vector=entity.vector,
                payload=entity.payload
            ) for entity in entities
        ]
        await self.client.upsert(collection_name=self.entity.collection, points=points)


    async def query(self, entity: T,  top_k: int = 10) -> List[T]:
        results = await self.client.search(
            collection_name=self.entity,
            query_vector=entity.vector,
            limit=top_k
        )
        return [r.dict() for r in results]


    async def delete(self, entity_ids: List[str]) -> None:
        await self.client.delete(collection_name=self.entity.collection, points=[entity_ids])
