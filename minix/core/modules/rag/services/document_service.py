# Service layer for RAG document lifecycle: register, index, fail, query, delete.
from typing import List
import uuid

from minix.core.service import SqlService
from minix.core.modules.rag.entities.document_entity import RagDocumentEntity
from minix.core.modules.rag.repositories.document_repository import RagDocumentRepository


class RagDocumentService(SqlService[RagDocumentEntity]):

    def __init__(self, repository: RagDocumentRepository):
        super().__init__(repository)
        self.repository: RagDocumentRepository = repository

    def register(self, collection_name: str, source_file: str,
                 document_type: str, extracted_metadata: dict) -> RagDocumentEntity:
        return self.repository.register_document(
            collection_name, source_file, document_type, extracted_metadata,
        )

    def mark_indexed(self, doc_id: int, chunks_count: int,
                     document_type: str | None = None,
                     extracted_metadata: dict | None = None,
                     caller_metadata: dict | None = None) -> None:
        self.repository.mark_indexed(doc_id, chunks_count,
                                     document_type=document_type,
                                     extracted_metadata=extracted_metadata,
                                     caller_metadata=caller_metadata)

    def mark_failed(self, doc_id: int, error: str) -> None:
        self.repository.mark_failed(doc_id, error)

    def get_by_doc_uuid(self, doc_uuid: uuid.UUID) -> RagDocumentEntity | None:
        return self.repository.get_by_doc_uuid(doc_uuid)

    def find_by_hash(self, collection: str, file_hash: str) -> RagDocumentEntity | None:
        return self.repository.find_by_hash(collection, file_hash)

    def update_file_info(self, doc_id: int, file_hash: str, storage_path: str) -> None:
        self.repository.update_file_info(doc_id, file_hash, storage_path)

    def list_by_collection(self, collection_name: str, page: int = 1,
                            page_size: int = 20, status: str | None = None,
                            document_type: str | None = None,
                            allowed_doc_uuids: set[str] | list[str] | None = None) -> tuple[List[RagDocumentEntity], int]:
        return self.repository.list_by_collection(
            collection_name, page, page_size, status, document_type,
            allowed_doc_uuids=allowed_doc_uuids,
        )

    def get_metadata_bulk(self, doc_ids: list[int]) -> dict[str, dict]:
        return self.repository.get_metadata_bulk(doc_ids)

    def count_by_collection(self, collection_name: str) -> int:
        return self.repository.count_by_collection(collection_name)

    def delete_by_uuid(self, doc_uuid: uuid.UUID | str) -> None:
        """Delete the document row and its chunk rows."""
        self.repository.delete_by_uuid(doc_uuid)
