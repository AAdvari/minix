from datetime import datetime

from minix.core.service import SqlService
from minix.core.modules.oidc.entities import OidcUserEntity
from minix.core.modules.oidc.repositories import OidcUserRepository


class OidcUserService(SqlService[OidcUserEntity]):
    def __init__(self, repository: OidcUserRepository):
        super().__init__(repository)
        self.repository: OidcUserRepository = repository

    def get_repository(self) -> OidcUserRepository:
        return self.repository

    def _ensure_schema_ready(self) -> None:
        # minix does not auto-create tables; create on first use (idempotent).
        with self.repository.get_session() as session:
            OidcUserEntity.__table__.create(bind=session.get_bind(), checkfirst=True)

    def get_by_sub(self, sub: str) -> OidcUserEntity | None:
        self._ensure_schema_ready()
        return self.repository.get_by_sub(sub)

    def upsert(
        self,
        *,
        sub: str,
        email: str | None = None,
        name: str | None = None,
        role: str = "user",
        touch_login: bool = True,
    ) -> OidcUserEntity:
        """Create or update the local profile for an OIDC subject.

        Writes only when something changed (or ``touch_login`` is set), so the
        per-request authentication path stays read-mostly.
        """
        self._ensure_schema_ready()
        entity = self.repository.get_by_sub(sub)
        if entity is None:
            entity = OidcUserEntity(
                sub=sub,
                email=email,
                name=name,
                role=role,
                last_login_at=datetime.utcnow() if touch_login else None,
            )
            return self.repository.save(entity)

        changed = False
        if email and entity.email != email:
            entity.email = email
            changed = True
        if name and entity.name != name:
            entity.name = name
            changed = True
        if role and entity.role != role:
            entity.role = role
            changed = True
        if touch_login:
            entity.last_login_at = datetime.utcnow()
            changed = True

        if changed:
            return self.repository.save(entity)
        return entity
