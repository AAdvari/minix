# SQLAlchemy entity for RAG chunks (one row per chunk, BM25 FTS index).
from datetime import datetime

from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Index, func, text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
import uuid as _uuid

from minix.core.entity import SqlEntity


class RagChunkEntity(SqlEntity):
    __tablename__ = "rag_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    chunk_uuid: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), default=_uuid.uuid4, unique=True, nullable=False)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    collection_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int | None] = mapped_column(Integer)
    section_type: Mapped[str | None] = mapped_column(String(50))
    parent_heading: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), server_default=func.now(), onupdate=func.now(), index=True)

    __table_args__ = (
        Index("idx_rag_chunks_document_id", "document_id"),
        Index("idx_rag_chunks_collection", "collection_name"),
        # PostgreSQL GIN index for BM25 full-text search.
        # Defined here so Alembic's initial autogenerate picks it up.
        Index(
            "idx_rag_chunks_fts",
            func.to_tsvector(sa_text("'english'"), sa_text("content")),
            postgresql_using="gin",
        ),
    )
