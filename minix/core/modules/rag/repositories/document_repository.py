# Repository for RAG document CRUD, status tracking, and metadata queries.
from datetime import datetime, timezone
from typing import List
import uuid

from sqlalchemy import desc

from minix.core.repository import SqlRepository
from minix.core.modules.rag.entities.document_entity import RagDocumentEntity
from minix.core.modules.rag.entities.chunk_entity import RagChunkEntity


def _as_uuid(doc_uuid: uuid.UUID | str) -> uuid.UUID:
    """Coerce the string form callers pass (e.g. ``str(doc.doc_uuid)``) to a
    real UUID so the query binds correctly."""
    return doc_uuid if isinstance(doc_uuid, uuid.UUID) else uuid.UUID(str(doc_uuid))


class RagDocumentRepository(SqlRepository[RagDocumentEntity]):

    def register_document(self, collection_name: str, source_file: str,
                          document_type: str, extracted_metadata: dict) -> RagDocumentEntity:
        # Construct via self.entity (not the imported class) so a mounted
        # entity subclass takes effect without editing this method.
        entity = self.entity()
        entity.doc_uuid = uuid.uuid4()
        entity.collection_name = collection_name
        entity.source_file = source_file
        entity.document_type = document_type
        entity.extracted_metadata = extracted_metadata
        entity.status = "pending"
        return self.save(entity)

    def mark_indexed(self, doc_id: int, chunks_count: int,
                     document_type: str | None = None,
                     extracted_metadata: dict | None = None,
                     caller_metadata: dict | None = None) -> None:
        with self.get_session() as session:
            row = session.query(self.entity).filter(self.entity.id == doc_id).first()
            if row:
                row.status = "indexed"
                row.chunks_count = chunks_count
                row.indexed_at = datetime.now(timezone.utc)
                if document_type:
                    row.document_type = document_type
                if extracted_metadata is not None:
                    row.extracted_metadata = extracted_metadata
                # H-1: only overwrite when something was supplied, so a caller
                # that sends no metadata does not blank an earlier value.
                if caller_metadata:
                    row.caller_metadata = caller_metadata
                session.commit()

    def mark_failed(self, doc_id: int, error: str) -> None:
        with self.get_session() as session:
            row = session.query(self.entity).filter(self.entity.id == doc_id).first()
            if row:
                row.status = "failed"
                row.error_message = error
                session.commit()

    def get_by_doc_uuid(self, doc_uuid: uuid.UUID) -> RagDocumentEntity | None:
        with self.get_session() as session:
            return session.query(self.entity).filter(
                self.entity.doc_uuid == doc_uuid
            ).first()

    def find_by_hash(self, collection: str, file_hash: str) -> RagDocumentEntity | None:
        with self.get_session() as session:
            return session.query(self.entity).filter(
                self.entity.collection_name == collection,
                self.entity.file_hash == file_hash,
                self.entity.status == "indexed",
            ).first()

    def update_file_info(self, doc_id: int, file_hash: str, storage_path: str) -> None:
        with self.get_session() as session:
            row = session.query(self.entity).filter(self.entity.id == doc_id).first()
            if row:
                row.file_hash = file_hash
                row.storage_path = storage_path
                session.commit()

    def list_by_collection(self, collection_name: str, page: int = 1,
                            page_size: int = 20, status: str | None = None,
                            document_type: str | None = None,
                            allowed_doc_uuids: set[str] | list[str] | None = None) -> tuple[List[RagDocumentEntity], int]:
        if allowed_doc_uuids is not None and len(allowed_doc_uuids) == 0:
            return [], 0
        with self.get_session() as session:
            q = session.query(self.entity).filter(
                self.entity.collection_name == collection_name
            )
            if allowed_doc_uuids is not None:
                allowed = []
                for raw in allowed_doc_uuids:
                    try:
                        allowed.append(uuid.UUID(str(raw)))
                    except ValueError:
                        continue
                if not allowed:
                    return [], 0
                q = q.filter(self.entity.doc_uuid.in_(allowed))
            if status:
                q = q.filter(self.entity.status == status)
            if document_type:
                q = q.filter(self.entity.document_type == document_type)
            total = q.count()
            rows = q.order_by(desc(self.entity.created_at)).offset(
                (page - 1) * page_size
            ).limit(page_size).all()
            return rows, total

    def get_metadata_bulk(self, doc_ids: list) -> dict[str, dict]:
        if not doc_ids:
            return {}
        str_ids = [str(d) for d in doc_ids]
        with self.get_session() as session:
            rows = session.query(self.entity).filter(
                self.entity.doc_uuid.in_(str_ids)
            ).all()
            return {
                str(row.doc_uuid): {
                    **(row.extracted_metadata or {}),
                    "source": row.source_file,
                    "document_type": row.document_type,
                    "document_id": str(row.doc_uuid),
                }
                for row in rows
            }

    def count_by_collection(self, collection_name: str) -> int:
        with self.get_session() as session:
            return session.query(self.entity).filter(
                self.entity.collection_name == collection_name
            ).count()

    def delete_by_uuid(self, doc_uuid: uuid.UUID | str) -> None:
        """Delete the document row and its chunk rows.

        Chunk rows are deleted explicitly in the same transaction rather
        than left to `rag_chunks.document_id`'s DB-level `ON DELETE CASCADE`
        (initial_schema.py:80) so a caller gets one atomic outcome and the
        method's own docstring is not dependent on inspecting the schema.
        Raises `ValueError` if the document does not exist, so a missing row
        surfaces as an error rather than a silent no-op.
        """
        doc_uuid = _as_uuid(doc_uuid)
        with self.get_session() as session:
            row = session.query(self.entity).filter(
                self.entity.doc_uuid == doc_uuid
            ).first()
            if row is None:
                raise ValueError(f"Document {doc_uuid} not found")
            session.query(RagChunkEntity).filter(
                RagChunkEntity.document_id == row.id
            ).delete(synchronize_session=False)
            session.delete(row)
            session.commit()
