import os
from typing import TypeVar, Type, List, Dict, Any, Coroutine
import numpy as np
from qdrant_client.models import PointStruct
from src.core.entity import QdrantEntity
from src.core.qdrant_connector import QdrantConnector
from src.core.repository import Repository

T = TypeVar('T', bound=QdrantEntity)


class QdrantRepository(Repository[T]):

    def __init__(self, entity: Type[T], qdrant_connector: QdrantConnector):
        super().__init__(entity)
        self.entity = entity
        self.connector = qdrant_connector
        self.client = self.connector.client
        ## check if collection exists, if not create it
        collections = self.client.get_collections().collections
        collection_names = [collection.name for collection in collections]
        if not self.entity.collection() in collection_names:
            self.client.create_collection(
                collection_name=self.entity.collection(),
                vectors_config={
                    "size": int(os.getenv("VECTOR_SIZE", 1536)),
                    "distance": "Cosine"
                }
            )

    async def insert(self, entities: List[T]) -> None:
        points = [
            PointStruct(
                id=entity.id,
                vector=entity.vector,
                payload=entity.payload
            ) for entity in entities
        ]
        self.client.upsert(collection_name=self.entity.collection(), points=points)

    async def search(
            self,
            vector: List[float] | np.ndarray,
            top_k: int = 10,
            with_vector: bool = False,
            threshold: float | None = None
    ) -> List[T]:
        results = self.client.search(
            collection_name=self.entity.collection(),
            query_vector=vector,
            limit=top_k,
            with_vectors=with_vector,
            score_threshold=threshold
        )
        print(results)
        return [self.entity(content=result.payload['content'], id=result.id, vector=None,
                            created_at=result.payload['created_at']) for result in results]

    async def delete(self, entity_ids: List[str]) -> None:
        self.client.delete(collection_name=self.entity.collection(), points_selector=[entity_ids])

    async def update_payload(self, point_id: str, payload: Dict[str, Any]) -> None:
        self.client.set_payload(
            collection_name=self.entity.collection(),
            payload=payload,
            points=[point_id],
        )
