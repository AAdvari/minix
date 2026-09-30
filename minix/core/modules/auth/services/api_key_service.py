from datetime import datetime
from typing import List
from minix.core.service import SqlService
from minix.core.modules.auth.entities import ApiKeyEntity, UserRole
from minix.core.modules.auth.repositories import ApiKeyRepository


class ApiKeyService(SqlService[ApiKeyEntity]):
    def __init__(self, repository: ApiKeyRepository):
        super().__init__(repository)
        self.repository: ApiKeyRepository = repository

    def get_repository(self) -> ApiKeyRepository:
        return self.repository

    def validate_key(self, api_key: str) -> ApiKeyEntity | None:
        entity = self.repository.get_by_key(api_key)
        if entity:
            self.repository.update_last_used(entity.id)
        return entity

    def create_key(
        self,
        user_id: str,
        role: UserRole = UserRole.USER,
        name: str | None = None,
        expires_at: datetime | None = None,
    ) -> tuple[ApiKeyEntity, str]:
        return self.repository.create_key(
            user_id=user_id,
            role=role,
            name=name,
            expires_at=expires_at,
        )

    def revoke_key(self, key_id: int) -> bool:
        return self.repository.revoke_key(key_id)

    def get_user_keys(self, user_id: str) -> List[ApiKeyEntity]:
        return self.repository.get_keys_for_user(user_id)

    def list_keys(self, user_id: str | None = None) -> List[ApiKeyEntity]:
        """Admin + self key listing: includes revoked keys so callers can
        distinguish active from revoked in the UI. Filters by user_id when
        provided. `get_user_keys` (above) stays active-only for places that
        do live key lookups."""
        return self.repository.list_keys(user_id)

    def get_by_id(self, key_id: int) -> ApiKeyEntity | None:
        return self.repository.get_by_id(key_id)
