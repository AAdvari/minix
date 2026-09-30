from datetime import datetime

from sqlalchemy import String, Integer, Text, DateTime, Boolean, func, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from minix.core.entity import SqlEntity


class RagSearchRequestEntity(SqlEntity):
    __tablename__ = "rag_search_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Nullable so a consumer can scrub the text in place while keeping the row.
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    collection: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="hybrid", server_default="hybrid")
    top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    filters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requester_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_rag_search_requests_status", "status"),
        Index("idx_rag_search_requests_collection", "collection"),
        Index("idx_rag_search_requests_created_at", "created_at"),
        Index("idx_rag_search_requests_requester_user_id", "requester_user_id"),
    )
