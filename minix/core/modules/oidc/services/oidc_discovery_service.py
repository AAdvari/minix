import time
from typing import Any

from minix.core.service import HelperService
from minix.core.modules.oidc.config import OidcConfig


class OidcDiscovery(HelperService):
    """Resolves OpenID Connect metadata and validates tokens.

    Fetches and caches the IdP's ``/.well-known/openid-configuration`` document
    and its JWKS, and verifies bearer/ID tokens (signature, issuer, audience,
    expiry). Built on ``authlib`` + ``httpx``, both imported lazily so the rest
    of the module stays importable when OIDC is not in use.
    """

    def __init__(self) -> None:
        self._config: OidcConfig | None = None
        self._metadata: dict[str, Any] | None = None
        self._jwks: Any = None
        self._jwks_fetched_at: float = 0.0

    # --- config / metadata ------------------------------------------------

    @property
    def config(self) -> OidcConfig:
        if self._config is None:
            self._config = OidcConfig.from_env()
        return self._config

    def set_config(self, config: OidcConfig) -> None:
        """Override the env-derived config (used in tests)."""
        self._config = config
        self._metadata = None
        self._jwks = None

    def _http_get(self, url: str) -> dict:
        import httpx

        resp = httpx.get(url, timeout=10.0)
        resp.raise_for_status()
        return resp.json()

    @property
    def metadata(self) -> dict[str, Any]:
        if self._metadata is None:
            well_known = f"{self.config.issuer}/.well-known/openid-configuration"
            self._metadata = self._http_get(well_known)
        return self._metadata

    @property
    def authorization_endpoint(self) -> str:
        return self.metadata["authorization_endpoint"]

    @property
    def token_endpoint(self) -> str:
        return self.metadata["token_endpoint"]

    @property
    def userinfo_endpoint(self) -> str | None:
        return self.metadata.get("userinfo_endpoint")

    @property
    def end_session_endpoint(self) -> str | None:
        return self.metadata.get("end_session_endpoint")

    # --- JWKS / verification ---------------------------------------------

    def _get_jwks(self):
        from authlib.jose import JsonWebKey

        ttl = self.config.jwks_ttl_seconds
        if self._jwks is None or (time.time() - self._jwks_fetched_at) > ttl:
            raw = self._http_get(self.metadata["jwks_uri"])
            self._jwks = JsonWebKey.import_key_set(raw)
            self._jwks_fetched_at = time.time()
        return self._jwks

    def set_jwks(self, jwks) -> None:
        """Inject a key set directly (used in tests to avoid network)."""
        self._jwks = jwks
        self._jwks_fetched_at = time.time()

    def verify_jwt(self, token: str) -> dict:
        """Validate a JWT and return its claims, raising on any failure."""
        from authlib.jose import jwt
        from authlib.jose.errors import JoseError

        claims_options = {
            "iss": {"essential": True, "value": self.config.issuer},
            "exp": {"essential": True},
        }
        if self.config.audience:
            claims_options["aud"] = {"essential": True, "value": self.config.audience}

        try:
            claims = jwt.decode(token, self._get_jwks(), claims_options=claims_options)
            claims.validate()
        except JoseError as exc:
            raise ValueError(f"Invalid OIDC token: {exc}") from exc
        return dict(claims)

    # --- authorization-code flow -----------------------------------------

    def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None) -> dict:
        import httpx

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.config.client_id,
        }
        if self.config.client_secret:
            data["client_secret"] = self.config.client_secret
        if code_verifier:
            data["code_verifier"] = code_verifier

        resp = httpx.post(self.token_endpoint, data=data, timeout=10.0)
        resp.raise_for_status()
        return resp.json()
