from minix.core.service import SqlService
from minix.core.modules.rag.entities.query_request_entity import RagQueryRequestEntity
from minix.core.modules.rag.repositories.query_request_repository import RagQueryRequestRepository


class RagQueryRequestService(SqlService[RagQueryRequestEntity]):

    def __init__(self, repository: RagQueryRequestRepository):
        super().__init__(repository)
        self.repository: RagQueryRequestRepository = repository

    def create(self, question: str, collection: str | None, top_k: int, debug: bool,
               requester_user_id: str | None = None,
               search_collections: list[str] | None = None) -> RagQueryRequestEntity:
        return self.repository.create(
            question, collection, top_k, debug,
            requester_user_id=requester_user_id,
            search_collections=search_collections,
        )

    def get_by_id(self, request_id: int) -> RagQueryRequestEntity | None:
        return self.repository.get_by_id(request_id)

    def mark_processing(self, request_id: int) -> None:
        self.repository.mark_processing(request_id)

    def complete(self, request_id: int, result: dict, duration_ms: int) -> None:
        self.repository.complete(request_id, result, duration_ms)

    def fail(self, request_id: int, error: str, duration_ms: int) -> None:
        self.repository.fail(request_id, error, duration_ms)
