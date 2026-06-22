import json
import os
from dataclasses import dataclass, field

# Roles are plain strings here so the OIDC module stays fully independent of the
# core `auth` module. An application can map these onto its own role system.
DEFAULT_ROLES = ("admin", "user", "service", "readonly")


def _default_role_map() -> dict:
    return {r: r for r in DEFAULT_ROLES}


@dataclass
class OidcConfig:
    """OIDC settings, populated from environment variables.

    The minix OIDC integration is provider-agnostic: point ``issuer`` at any
    spec-compliant IdP (Keycloak, Auth0, Okta, Entra, …) and the OpenID
    discovery document supplies the concrete endpoints and JWKS.
    """

    issuer: str
    client_id: str
    client_secret: str | None = None
    audience: str | None = None
    redirect_uri: str | None = None
    post_login_redirect: str = "/"
    scopes: str = "openid profile email"
    # Dotted path into the token claims that holds the user's roles,
    # e.g. "realm_access.roles" for Keycloak or "roles" for a flat claim.
    role_claim: str = "realm_access.roles"
    role_map: dict = field(default_factory=_default_role_map)
    default_role: str = "user"
    jwks_ttl_seconds: int = 3600
    session_secret: str | None = None
    session_cookie_name: str = "minix_session"
    session_ttl_seconds: int = 28800  # 8h
    cookie_secure: bool = True

    @classmethod
    def from_env(cls) -> "OidcConfig":
        issuer = os.getenv("OIDC_ISSUER", "").rstrip("/")
        if not issuer:
            raise RuntimeError(
                "OIDC_ISSUER is required to use the OIDC module. Set it to your "
                "IdP's issuer URL (e.g. https://keycloak/realms/kinetix)."
            )

        role_map = _default_role_map()
        raw_map = os.getenv("OIDC_ROLE_MAP")
        if raw_map:
            # JSON object mapping IdP role name -> app role name, e.g.
            # {"kinetix-admin": "admin", "kinetix-user": "user"}
            for idp_role, app_role in json.loads(raw_map).items():
                role_map[idp_role] = str(app_role).lower()

        return cls(
            issuer=issuer,
            client_id=os.getenv("OIDC_CLIENT_ID", ""),
            client_secret=os.getenv("OIDC_CLIENT_SECRET") or None,
            audience=os.getenv("OIDC_AUDIENCE") or os.getenv("OIDC_CLIENT_ID") or None,
            redirect_uri=os.getenv("OIDC_REDIRECT_URI") or None,
            post_login_redirect=os.getenv("OIDC_POST_LOGIN_REDIRECT", "/"),
            scopes=os.getenv("OIDC_SCOPES", "openid profile email"),
            role_claim=os.getenv("OIDC_ROLE_CLAIM", "realm_access.roles"),
            role_map=role_map,
            default_role=os.getenv("OIDC_DEFAULT_ROLE", "user").lower(),
            jwks_ttl_seconds=int(os.getenv("OIDC_JWKS_TTL", "3600")),
            session_secret=os.getenv("OIDC_SESSION_SECRET") or None,
            session_cookie_name=os.getenv("OIDC_SESSION_COOKIE", "minix_session"),
            session_ttl_seconds=int(os.getenv("OIDC_SESSION_TTL", "28800")),
            cookie_secure=os.getenv("OIDC_COOKIE_SECURE", "true").lower() == "true",
        )

    def map_roles(self, roles: list[str]) -> str:
        """Resolve the highest-privilege app role from the IdP role list."""
        precedence = ["admin", "service", "user", "readonly"]
        mapped = {self.role_map[r] for r in roles if r in self.role_map}
        for role in precedence:
            if role in mapped:
                return role
        return self.default_role
