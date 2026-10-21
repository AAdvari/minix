from datetime import datetime, timezone

from minix.core.repository import SqlRepository
from minix.core.modules.rag.entities.search_request_entity import RagSearchRequestEntity


class RagSearchRequestRepository(SqlRepository[RagSearchRequestEntity]):

    def create(self, query: str, collection: str, mode: str, top_k: int, filters: dict,
               requester_user_id: str | None = None) -> RagSearchRequestEntity:
        entity = RagSearchRequestEntity()
        entity.query = query
        entity.collection = collection
        entity.mode = mode
        entity.top_k = top_k
        entity.filters = filters or {}
        entity.status = "pending"
        entity.requester_user_id = requester_user_id
        return self.save(entity)

    def mark_processing(self, request_id: int) -> None:
        with self.get_session() as session:
            row = session.query(self.entity).filter(self.entity.id == request_id).first()
            if row:
                row.status = "processing"
                session.commit()

    def complete(self, request_id: int, result: dict, duration_ms: int) -> None:
        with self.get_session() as session:
            row = session.query(self.entity).filter(self.entity.id == request_id).first()
            if row:
                row.status = "completed"
                row.success = True
                row.result = result
                row.duration_ms = duration_ms
                row.completed_at = datetime.now(timezone.utc)
                session.commit()

    def fail(self, request_id: int, error: str, duration_ms: int) -> None:
        with self.get_session() as session:
            row = session.query(self.entity).filter(self.entity.id == request_id).first()
            if row:
                row.status = "failed"
                row.success = False
                row.error_message = error
                row.duration_ms = duration_ms
                row.completed_at = datetime.now(timezone.utc)
                session.commit()
