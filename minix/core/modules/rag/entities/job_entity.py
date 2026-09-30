# SQLAlchemy entity for async RAG ingestion jobs.
from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
import uuid as _uuid

from minix.core.entity import SqlEntity


class RagJobEntity(SqlEntity):
    __tablename__ = "rag_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_uuid: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), default=_uuid.uuid4, unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", nullable=False)
    collection_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_id: Mapped[int | None] = mapped_column(nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), server_default=func.now(), onupdate=func.now(), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The authenticated requester, so polling can re-check it against the
    # caller and the current permissions.
    requester_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_rag_jobs_status", "status"),
        Index("idx_rag_jobs_collection", "collection_name"),
        Index("idx_rag_jobs_requester_user_id", "requester_user_id"),
    )
