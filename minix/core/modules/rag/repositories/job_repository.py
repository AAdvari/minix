# Repository for async RAG ingestion job tracking.
from datetime import datetime, timezone
import uuid

from minix.core.repository import SqlRepository
from minix.core.modules.rag.entities.job_entity import RagJobEntity


class RagJobRepository(SqlRepository[RagJobEntity]):

    def create_job(self, job_type: str, collection_name: str,
                   requester_user_id: str | None = None) -> RagJobEntity:
        entity = RagJobEntity()
        entity.job_uuid = uuid.uuid4()
        entity.type = job_type
        entity.status = "pending"
        entity.collection_name = collection_name
        entity.requester_user_id = requester_user_id
        return self.save(entity)

    def get_by_uuid(self, job_uuid: uuid.UUID) -> RagJobEntity | None:
        with self.get_session() as session:
            return session.query(self.entity).filter(
                self.entity.job_uuid == job_uuid
            ).first()

    def mark_processing(self, job_id: int) -> None:
        with self.get_session() as session:
            row = session.query(self.entity).filter(self.entity.id == job_id).first()
            if row:
                row.status = "processing"
                row.started_at = datetime.now(timezone.utc)
                session.commit()

    def complete_job(self, job_id: int, document_id: int, result: dict) -> None:
        with self.get_session() as session:
            row = session.query(self.entity).filter(self.entity.id == job_id).first()
            if row:
                row.status = "completed"
                row.document_id = document_id
                row.result = result
                row.completed_at = datetime.now(timezone.utc)
                session.commit()

    def fail_job(self, job_id: int, error: str) -> None:
        with self.get_session() as session:
            row = session.query(self.entity).filter(self.entity.id == job_id).first()
            if row:
                row.status = "failed"
                row.error_message = error
                row.completed_at = datetime.now(timezone.utc)
                session.commit()

    def cancel_job(self, job_id: int) -> None:
        """Operator corrective maintenance: mark a stuck/queued
        job as cancelled. No document contents are touched."""
        with self.get_session() as session:
            row = session.query(self.entity).filter(self.entity.id == job_id).first()
            if row:
                row.status = "cancelled"
                row.completed_at = datetime.now(timezone.utc)
                session.commit()

    def requeue_job(self, job_id: int) -> None:
        """Operator corrective maintenance: reset a failed/stuck
        job back to pending so it can be re-run. Clears the prior error."""
        with self.get_session() as session:
            row = session.query(self.entity).filter(self.entity.id == job_id).first()
            if row:
                row.status = "pending"
                row.error_message = None
                row.started_at = None
                row.completed_at = None
                session.commit()
