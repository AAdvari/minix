# Service layer for RAG collection management: create, list, delete, stats.
from typing import List

from minix.core.service import SqlService
from minix.core.modules.rag.entities.collection_entity import RagCollectionEntity
from minix.core.modules.rag.repositories.collection_repository import RagCollectionRepository
from minix.core.modules.rag.qdrant_ops import (
    create_qdrant_collection,
    delete_qdrant_collection,
    get_qdrant_collection_info,
    list_qdrant_collections,
)


class RagCollectionService(SqlService[RagCollectionEntity]):

    def __init__(self, repository: RagCollectionRepository):
        super().__init__(repository)
        self.repository: RagCollectionRepository = repository

    def create_collection(self, name: str, description: str | None = None,
                          chunking_config: dict | None = None) -> RagCollectionEntity:
        if self.repository.get_by_name(name):
            raise ValueError(f"Collection '{name}' already exists.")
        create_qdrant_collection(name)
        # Construct via the repository's mounted entity so a consuming layer's
        # entity subclass (extra columns) takes effect.
        entity = self.repository.entity()
        entity.name = name
        entity.description = description
        entity.chunking_config = chunking_config or {
            "strategy": "smart", "chunk_size": 800,
            "chunk_overlap": 100, "min_chunk_size": 100,
        }
        return self.repository.save(entity)

    def get_by_name(self, name: str) -> RagCollectionEntity | None:
        return self.repository.get_by_name(name)

    def list_all(self) -> List[RagCollectionEntity]:
        return self.repository.list_all()

    def delete_collection(self, name: str) -> bool:
        delete_qdrant_collection(name)
        return self.repository.delete_by_name(name)

    def get_chunking_config(self, name: str) -> dict:
        return self.repository.get_chunking_config(name)

    def update_chunking_config(self, name: str, partial: dict) -> RagCollectionEntity | None:
        """Shallow-merge `partial` over the stored chunking_config and persist.
        Validation of merged values happens at the controller boundary via the
        ChunkingConfig Pydantic model — this method assumes the payload is
        already trusted. Returns the refreshed entity, or None when the
        collection doesn't exist. Re-indexing is intentionally NOT triggered:
        the new config applies only to subsequent ingests (chunking_config is
        read at ingest time in rag_controller.py)."""
        current = self.repository.get_chunking_config(name)
        merged = {**current, **{k: v for k, v in partial.items() if v is not None}}
        return self.repository.update_chunking_config(name, merged)

    def get_stats(self, name: str, doc_count: int, chunk_count: int) -> dict:
        qdrant_info = get_qdrant_collection_info(name) or {}
        return {
            "documents": doc_count,
            "chunks": chunk_count,
            "vectors": qdrant_info.get("vectors_count", 0),
            "index_status": qdrant_info.get("index_status"),
        }

    def list_qdrant_collections(self) -> list[str]:
        return list_qdrant_collections()
