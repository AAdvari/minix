from dataclasses import dataclass

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPBearer

from minix.core.registry import Registry

# Shown in the OpenAPI "Authorize" dialog. The guard reads the credential off
# the request itself, so this is optional (auto_error=False).
BEARER_SCHEME = HTTPBearer(scheme_name="OidcBearer", auto_error=False)


@dataclass
class OidcContext:
    """Identity resolved from an OIDC token or session cookie.

    Self-contained (no dependency on the core auth module): ``role`` is a plain
    string mapped from the IdP claims via :class:`OidcConfig`.
    """

    user_id: str  # OIDC subject (`sub`)
    email: str | None
    role: str
    claims: dict

    def has_role(self, *roles: str) -> bool:
        return self.role in roles

    def is_admin(self) -> bool:
        return self.role == "admin"


def extract_roles(claims: dict, dotted_path: str) -> list[str]:
    """Walk a dotted claim path (e.g. ``realm_access.roles``) to the role list."""
    node = claims
    for part in dotted_path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            node = None
            break
    if node is None:
        return []
    if isinstance(node, str):
        return [node]
    if isinstance(node, (list, tuple)):
        return [str(r) for r in node]
    return []


def _discovery():
    from minix.core.modules.oidc.services.oidc_discovery_service import OidcDiscovery

    return Registry().get(OidcDiscovery)


def _user_service():
    from minix.core.modules.oidc.services.oidc_user_service import OidcUserService

    return Registry().get(OidcUserService)


def _context_from_claims(claims: dict, config) -> OidcContext | None:
    sub = claims.get("sub")
    if not sub:
        return None
    email = claims.get("email")
    name = claims.get("name") or claims.get("preferred_username")

    # Session cookies carry the already-mapped app role; bearer tokens carry the
    # IdP roles under the configured claim path.
    if claims.get("minix_role"):
        role = claims["minix_role"]
    else:
        role = config.map_roles(extract_roles(claims, config.role_claim))

    service = _user_service()
    if service is not None:
        service.upsert(sub=sub, email=email, name=name, role=role, touch_login=False)

    return OidcContext(user_id=sub, email=email, role=role, claims=claims)


async def resolve_oidc_context(request: Request) -> OidcContext | None:
    """Return the OIDC identity on the request, or ``None`` if unauthenticated.

    Accepts an ``Authorization: Bearer <jwt>`` token (validated via the IdP
    JWKS) or the session cookie issued by :class:`OidcController`.
    """
    discovery = _discovery()
    if discovery is None:
        return None
    config = discovery.config

    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        try:
            claims = discovery.verify_jwt(token)
        except ValueError:
            return None
        return _context_from_claims(claims, config)

    cookie = request.cookies.get(config.session_cookie_name)
    if cookie and config.session_secret:
        from minix.core.modules.oidc.session import decode_session

        try:
            claims = decode_session(config.session_secret, cookie)
        except Exception:
            return None
        return _context_from_claims(claims, config)

    return None


async def get_oidc_user(request: Request, _bearer=Security(BEARER_SCHEME)) -> OidcContext:
    """FastAPI dependency: require any authenticated OIDC identity."""
    context = await resolve_oidc_context(request)
    if context is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return context


class RequireOidcRole:
    """FastAPI dependency factory: require one of the given app roles."""

    def __init__(self, *roles: str):
        self.roles = roles

    async def __call__(self, request: Request, _bearer=Security(BEARER_SCHEME)) -> OidcContext:
        context = await resolve_oidc_context(request)
        if context is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if self.roles and context.role not in self.roles:
            raise HTTPException(status_code=403, detail="Access denied.")
        return context
