# SQLAlchemy entity for RAG documents (one row per ingested file).
from datetime import datetime

from sqlalchemy import (
    String, Integer, Text, DateTime, ForeignKey, Index, func,
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
import uuid as _uuid

from minix.core.entity import SqlEntity


class RagDocumentEntity(SqlEntity):
    __tablename__ = "rag_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_uuid: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), default=_uuid.uuid4, unique=True, nullable=False)
    collection_name: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("rag_collections.name", ondelete="CASCADE"),
        nullable=False,
    )
    source_file: Mapped[str | None] = mapped_column(String(500))
    document_type: Mapped[str] = mapped_column(String(50), default="general", server_default="general", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", nullable=False)
    extracted_metadata: Mapped[dict | None] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    # Metadata the CALLER supplied at ingest, kept separate from
    # `extracted_metadata` above (which only the LLM extractor writes), so the
    # caller's own keys survive verbatim and stay distinguishable from values a
    # model inferred.
    caller_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    chunks_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), server_default=func.now(), onupdate=func.now(), index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_rag_documents_collection", "collection_name"),
        Index("idx_rag_documents_status", "status"),
        Index("idx_rag_documents_file_hash", "collection_name", "file_hash"),
    )
