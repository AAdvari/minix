from minix.core.service import SqlService
from minix.core.modules.rag.entities.search_request_entity import RagSearchRequestEntity
from minix.core.modules.rag.repositories.search_request_repository import RagSearchRequestRepository


class RagSearchRequestService(SqlService[RagSearchRequestEntity]):

    def __init__(self, repository: RagSearchRequestRepository):
        super().__init__(repository)
        self.repository: RagSearchRequestRepository = repository

    def create(self, query: str, collection: str, mode: str, top_k: int, filters: dict,
               requester_user_id: str | None = None) -> RagSearchRequestEntity:
        return self.repository.create(
            query, collection, mode, top_k, filters,
            requester_user_id=requester_user_id,
        )

    def get_by_id(self, request_id: int) -> RagSearchRequestEntity | None:
        return self.repository.get_by_id(request_id)

    def mark_processing(self, request_id: int) -> None:
        self.repository.mark_processing(request_id)

    def complete(self, request_id: int, result: dict, duration_ms: int) -> None:
        self.repository.complete(request_id, result, duration_ms)

    def fail(self, request_id: int, error: str, duration_ms: int) -> None:
        self.repository.fail(request_id, error, duration_ms)
