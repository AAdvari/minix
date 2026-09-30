# SQLAlchemy entity for RAG collections (project namespaces).
from datetime import datetime

from sqlalchemy import String, Text, DateTime, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from minix.core.entity import SqlEntity


_DEFAULT_CHUNKING_CONFIG = {
    "strategy": "smart",
    "chunk_size": 800,
    "chunk_overlap": 100,
    "min_chunk_size": 100,
}


class RagCollectionEntity(SqlEntity):
    __tablename__ = "rag_collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # Ownership / access-control / tenancy columns are added by consuming
    # layers through single-table-inheritance subclasses. The framework entity
    # stays single-tenant.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_document_type: Mapped[str] = mapped_column(String(50), default="general", server_default="general", nullable=False)
    chunking_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=lambda: dict(_DEFAULT_CHUNKING_CONFIG), server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=func.now(), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=func.now(), server_default=func.now(), onupdate=func.now(), index=True
    )
