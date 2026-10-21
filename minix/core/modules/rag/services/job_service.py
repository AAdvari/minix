# Service layer for async RAG ingestion job lifecycle.
import uuid

from minix.core.service import SqlService
from minix.core.modules.rag.entities.job_entity import RagJobEntity
from minix.core.modules.rag.repositories.job_repository import RagJobRepository


class RagJobService(SqlService[RagJobEntity]):

    def __init__(self, repository: RagJobRepository):
        super().__init__(repository)
        self.repository: RagJobRepository = repository

    def create_job(self, job_type: str, collection_name: str,
                   requester_user_id: str | None = None) -> RagJobEntity:
        return self.repository.create_job(
            job_type, collection_name, requester_user_id=requester_user_id,
        )

    def get_by_uuid(self, job_uuid: uuid.UUID) -> RagJobEntity | None:
        return self.repository.get_by_uuid(job_uuid)

    def mark_processing(self, job_id: int) -> None:
        self.repository.mark_processing(job_id)

    def complete_job(self, job_id: int, document_id: int, result: dict) -> None:
        self.repository.complete_job(job_id, document_id, result)

    def fail_job(self, job_id: int, error: str) -> None:
        self.repository.fail_job(job_id, error)

    def cancel_job(self, job_id: int) -> None:
        self.repository.cancel_job(job_id)

    def requeue_job(self, job_id: int) -> None:
        self.repository.requeue_job(job_id)
