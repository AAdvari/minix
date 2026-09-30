# Service layer for RAG chunk operations: bulk insert, BM25 search, FTS index.
from typing import List

from minix.core.service import SqlService
from minix.core.modules.rag.entities.chunk_entity import RagChunkEntity
from minix.core.modules.rag.repositories.chunk_repository import RagChunkRepository


class RagChunkService(SqlService[RagChunkEntity]):

    def __init__(self, repository: RagChunkRepository):
        super().__init__(repository)
        self.repository: RagChunkRepository = repository

    def add_chunks(self, document_id: int, collection_name: str,
                   chunks: list[dict]) -> None:
        self.repository.add_chunks(document_id, collection_name, chunks)

    def bm25_search(self, query: str, collection_name: str,
                    k: int = 10,
                    allowed_doc_uuids: set[str] | list[str] | None = None,
                    extra_filters: dict[str, int | str] | None = None) -> List[dict]:
        # `extra_filters` is the generic scope passthrough — a consuming layer
        # supplies e.g. {"tenant_id": n}; the framework itself is unscoped.
        return self.repository.bm25_search(
            query, collection_name, k, allowed_doc_uuids=allowed_doc_uuids,
            extra_filters=extra_filters,
        )

    def bm25_search_with_filter(self, query: str, collection_name: str,
                                 k: int = 10, metadata_filters: dict | None = None,
                                 allowed_doc_uuids: set[str] | list[str] | None = None,
                                 extra_filters: dict[str, int | str] | None = None) -> List[dict]:
        return self.repository.bm25_search_with_filter(
            query, collection_name, k, metadata_filters,
            allowed_doc_uuids=allowed_doc_uuids,
            extra_filters=extra_filters,
        )

    def count_by_collection(self, collection_name: str) -> int:
        return self.repository.count_by_collection(collection_name)

    def list_by_document_uuid(self, doc_uuid: str, limit: int = 50,
                              offset: int = 0) -> tuple[list[dict], int]:
        return self.repository.list_by_document_uuid(doc_uuid, limit, offset)

    def create_fts_index(self) -> None:
        self.repository.create_fts_index()
