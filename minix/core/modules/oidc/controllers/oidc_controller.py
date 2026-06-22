import base64
import hashlib
import logging
import secrets
from urllib.parse import urlencode

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from minix.core.controller import Controller
from minix.core.registry import Registry
from minix.core.modules.oidc.dependencies import extract_roles
from minix.core.modules.oidc.session import encode_session, decode_session
from minix.core.modules.oidc.services.oidc_discovery_service import OidcDiscovery
from minix.core.modules.oidc.services.oidc_user_service import OidcUserService

logger = logging.getLogger(__name__)

FLOW_COOKIE = "minix_oidc_flow"
FLOW_TTL_SECONDS = 600


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class OidcController(Controller):
    """Browser-facing OIDC Authorization Code + PKCE endpoints.

    These routes are intentionally unprotected (no ``@protected`` marker) so the
    login round-trip can complete before a session exists.
    """

    def get_prefix(self):
        return ""

    def define_routes(self):
        self.router.add_api_route(path="/auth/oidc/login", endpoint=self.login, methods=["GET"], tags=["Auth OIDC"], description="Start the OIDC login flow (redirects to the IdP).")
        self.router.add_api_route(path="/auth/oidc/callback", endpoint=self.callback, methods=["GET"], tags=["Auth OIDC"], description="OIDC redirect URI: exchange the code and issue a session.")
        self.router.add_api_route(path="/auth/oidc/userinfo", endpoint=self.userinfo, methods=["GET"], tags=["Auth OIDC"], description="Return the current authenticated identity.")
        self.router.add_api_route(path="/auth/oidc/logout", endpoint=self.logout, methods=["GET"], tags=["Auth OIDC"], description="Clear the session and optionally sign out at the IdP.")

    def _discovery(self) -> OidcDiscovery:
        discovery = Registry().get(OidcDiscovery)
        if discovery is None:
            raise HTTPException(status_code=500, detail="OIDC is not configured.")
        return discovery

    def _redirect_uri(self, request: Request, config) -> str:
        return config.redirect_uri or str(request.url_for("callback"))

    def login(self, request: Request, redirect: str | None = None):
        discovery = self._discovery()
        config = discovery.config
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(24)

        params = {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": self._redirect_uri(request, config),
            "scope": config.scopes,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        url = f"{discovery.authorization_endpoint}?{urlencode(params)}"

        resp = RedirectResponse(url, status_code=302)
        flow = encode_session(
            config.session_secret,
            {"cv": verifier, "st": state, "rd": redirect or config.post_login_redirect},
            ttl_seconds=FLOW_TTL_SECONDS,
        )
        resp.set_cookie(
            FLOW_COOKIE, flow, httponly=True, max_age=FLOW_TTL_SECONDS,
            samesite="lax", secure=config.cookie_secure,
        )
        return resp

    def callback(self, request: Request, code: str | None = None, state: str | None = None):
        discovery = self._discovery()
        config = discovery.config

        flow_cookie = request.cookies.get(FLOW_COOKIE)
        if not code or not flow_cookie:
            raise HTTPException(status_code=400, detail="Missing OIDC authorization code or flow state.")
        try:
            flow = decode_session(config.session_secret, flow_cookie)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid or expired OIDC flow state.")
        if state != flow.get("st"):
            raise HTTPException(status_code=400, detail="OIDC state mismatch.")

        token_resp = discovery.exchange_code(code, self._redirect_uri(request, config), flow.get("cv"))
        id_token = token_resp.get("id_token")
        if not id_token:
            raise HTTPException(status_code=400, detail="IdP did not return an id_token.")
        claims = discovery.verify_jwt(id_token)

        sub = claims.get("sub")
        email = claims.get("email")
        name = claims.get("name") or claims.get("preferred_username")
        role = config.map_roles(extract_roles(claims, config.role_claim))

        user_service = Registry().get(OidcUserService)
        if user_service is not None:
            user_service.upsert(sub=sub, email=email, name=name, role=role, touch_login=True)

        session = encode_session(
            config.session_secret,
            {"sub": sub, "email": email, "name": name, "minix_role": role.value},
            ttl_seconds=config.session_ttl_seconds,
        )
        resp = RedirectResponse(flow.get("rd") or config.post_login_redirect, status_code=302)
        resp.set_cookie(
            config.session_cookie_name, session, httponly=True,
            max_age=config.session_ttl_seconds, samesite="lax", secure=config.cookie_secure,
        )
        resp.delete_cookie(FLOW_COOKIE)
        return resp

    def userinfo(self, request: Request):
        config = self._discovery().config
        cookie = request.cookies.get(config.session_cookie_name)
        if not cookie:
            raise HTTPException(status_code=401, detail="Not authenticated.")
        try:
            claims = decode_session(config.session_secret, cookie)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired session.")
        return JSONResponse({
            "user_id": claims.get("sub"),
            "email": claims.get("email"),
            "name": claims.get("name"),
            "role": claims.get("minix_role"),
        })

    def logout(self, request: Request, redirect: str | None = None):
        config = self._discovery().config
        end_session = self._discovery().end_session_endpoint
        target = redirect or config.post_login_redirect
        if end_session:
            params = {"client_id": config.client_id, "post_logout_redirect_uri": target}
            target = f"{end_session}?{urlencode(params)}"
        resp = RedirectResponse(target, status_code=302)
        resp.delete_cookie(config.session_cookie_name)
        return resp
