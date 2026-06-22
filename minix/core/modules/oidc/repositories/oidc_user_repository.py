from minix.core.repository import SqlRepository
from minix.core.modules.oidc.entities import OidcUserEntity


class OidcUserRepository(SqlRepository[OidcUserEntity]):

    def get_by_sub(self, sub: str) -> OidcUserEntity | None:
        results = self.get_by(sub=sub)
        return results[0] if results else None
