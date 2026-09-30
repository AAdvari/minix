import hashlib
from datetime import datetime
from typing import List
from minix.core.repository import SqlRepository
from minix.core.modules.auth.entities import ApiKeyEntity, UserRole


class ApiKeyRepository(SqlRepository[ApiKeyEntity]):

    def get_by_key(self, api_key: str) -> ApiKeyEntity | None:
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        results = self.get_by(key_hash=key_hash, is_active=True)
        if not results:
            return None
        key_entity = results[0]
        if key_entity.expires_at and key_entity.expires_at < datetime.utcnow():
            return None
        return key_entity

    def create_key(
            self,
            user_id: str,
            role: UserRole = UserRole.USER,
            name: str | None = None,
            expires_at: datetime | None = None,
    ) -> tuple[ApiKeyEntity, str]:
        # Construct via self.entity (not the imported class) so a mounted
        # subclass (e.g. one carrying a scope column) takes effect; a consuming
        # layer overrides create_key to stamp its extra fields.
        full_key, prefix, key_hash = self.entity.generate_key()
        entity = self.entity(
            key_hash=key_hash,
            key_prefix=prefix,
            user_id=user_id,
            role=role,
            name=name,
            expires_at=expires_at,
        )
        saved = self.save(entity)
        return saved, full_key

    def revoke_key(self, key_id: int) -> bool:
        entity = self.get_by_id(key_id)
        if not entity:
            return False
        entity.is_active = False
        self.save(entity)
        return True

    def update_last_used(self, key_id: int) -> None:
        entity = self.get_by_id(key_id)
        if entity:
            entity.last_used_at = datetime.utcnow()
            self.save(entity)

    def get_keys_for_user(self, user_id: str) -> List[ApiKeyEntity]:
        return self.get_by(user_id=user_id, is_active=True)

    def list_keys(self, user_id: str | None = None) -> List[ApiKeyEntity]:
        """List keys including revoked ones, for admin views and the user's
        own key-management UI. Filters by user_id when provided."""
        with self.get_session() as session:
            q = session.query(self.entity)
            if user_id is not None:
                q = q.filter(self.entity.user_id == user_id)
            return q.order_by(self.entity.created_at.desc()).all()
