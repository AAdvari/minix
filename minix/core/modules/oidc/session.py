import time


def encode_session(secret: str, payload: dict, ttl_seconds: int) -> str:
    """Sign a short-lived session payload as an HS256 JWT."""
    from authlib.jose import jwt

    if not secret:
        raise RuntimeError("OIDC_SESSION_SECRET is required to issue minix sessions.")
    data = {**payload, "exp": int(time.time()) + ttl_seconds}
    return jwt.encode({"alg": "HS256"}, data, secret).decode("utf-8")


def decode_session(secret: str, token: str) -> dict:
    """Validate a session JWT and return its claims (raises on tamper/expiry)."""
    from authlib.jose import jwt

    if not secret:
        raise RuntimeError("OIDC_SESSION_SECRET is required to read minix sessions.")
    claims = jwt.decode(token, secret)
    claims.validate()  # enforces exp
    return dict(claims)
