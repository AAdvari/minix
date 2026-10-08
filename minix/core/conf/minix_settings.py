"""Build Minix uppercase settings from a project pydantic config instance."""

from __future__ import annotations

from typing import Any


def _get(cfg: Any, name: str, default: Any = None) -> Any:
    return getattr(cfg, name, default)


def _connection_map(
    cfg: Any,
    dict_attr: str,
    *,
    flat_default: dict[str, Any] | None = None,
    extra_attr: str | None = None,
) -> dict[str, Any]:
    """Prefer an explicit dict field; fall back to flat fields + extra_* maps."""
    raw = _get(cfg, dict_attr, None)
    if isinstance(raw, dict) and raw:
        return dict(raw)

    result: dict[str, Any] = {}
    if flat_default:
        result["default"] = flat_default
    if extra_attr:
        result.update(dict(_get(cfg, extra_attr, {}) or {}))
    return result


def exports_from_config(cfg: Any) -> dict[str, Any]:
    """Map a pydantic ``Settings`` instance to names used by Minix bootstrap.

    Prefers dict-style fields (``databases``, ``celery_connections``, …).
    Flat ``db_*`` / ``extra_*`` fields on the pydantic model remain supported
    as a convenience for ``config.py`` (not legacy ``settings.py``).
    """
    celery_broker = _get(cfg, "celery_broker_url", "redis://localhost:6379/0")
    redis_url = _get(cfg, "redis_url", None)

    databases = _connection_map(
        cfg,
        "databases",
        flat_default={
            "user": _get(cfg, "db_user", "minix"),
            "password": _get(cfg, "db_pass", "minix"),
            "host": _get(cfg, "db_host", "localhost"),
            "port": _get(cfg, "db_port", 5432),
            "name": _get(cfg, "db_database", "minix"),
            "driver": _get(cfg, "db_driver", "postgresql"),
        },
        extra_attr="extra_databases",
    )
    celery_connections = _connection_map(
        cfg,
        "celery_connections",
        flat_default={
            "broker_url": celery_broker,
            "result_backend": _get(
                cfg, "celery_result_backend", "redis://localhost:6379/1"
            ),
            "task_serializer": _get(cfg, "celery_task_serializer", "json"),
            "result_serializer": _get(cfg, "celery_result_serializer", "json"),
            "accept_content": ["json"],
            "timezone": _get(cfg, "celery_timezone", "GMT"),
        },
        extra_attr="extra_celery_connections",
    )
    redis_connections = _connection_map(
        cfg,
        "redis_connections",
        flat_default={"url": redis_url or celery_broker},
        extra_attr="extra_redis_connections",
    )
    kafka_clusters = _connection_map(
        cfg,
        "kafka_clusters",
        flat_default={
            "bootstrap_servers": _get(
                cfg, "kafka_bootstrap_servers", "localhost:9092"
            ),
        },
        extra_attr="extra_kafka_clusters",
    )
    qdrant_connections = _connection_map(
        cfg,
        "qdrant_connections",
        flat_default={
            "url": _get(cfg, "qdrant_url", "http://localhost:6333"),
            "api_key": _get(cfg, "qdrant_api_key", None),
        },
        extra_attr="extra_qdrant_connections",
    )
    object_storages = _connection_map(
        cfg,
        "object_storages",
        flat_default={
            "endpoint_url": _get(
                cfg, "object_storage_endpoint_url", "http://localhost:9000"
            ),
            "access_key": _get(cfg, "object_storage_access_key", "minioadmin"),
            "secret_key": _get(cfg, "object_storage_secret_key", "minioadmin"),
            "bucket_name": _get(cfg, "object_storage_bucket_name", "minix"),
            "use_ssl": _get(cfg, "object_storage_use_ssl", False),
            "verify_ssl": _get(cfg, "object_storage_verify_ssl", False),
        },
        extra_attr="extra_object_storages",
    )

    return {
        "DEBUG": _get(cfg, "debug", False),
        "APP_NAME": _get(cfg, "app_name", "minix"),
        "APP_HOST": _get(cfg, "app_host", "0.0.0.0"),
        "APP_PORT": _get(cfg, "app_port", 8000),
        "SECRET_KEY": _get(cfg, "secret_key", None),
        "INSTALLED_MODULES": list(_get(cfg, "installed_modules", []) or []),
        "DATABASES": databases,
        "CELERY_CONNECTIONS": celery_connections,
        "REDIS_CONNECTIONS": redis_connections,
        "KAFKA_CLUSTERS": kafka_clusters,
        "QDRANT_CONNECTIONS": qdrant_connections,
        "OBJECT_STORAGES": object_storages,
        "MLFLOW_TRACKING_URL": _get(cfg, "mlflow_tracking_url", "http://localhost:5000"),
        "PYTHON_VERSION": _get(cfg, "python_version", "3.11"),
        "OIDC_ISSUER": _get(cfg, "oidc_issuer", ""),
        "OIDC_CLIENT_ID": _get(cfg, "oidc_client_id", ""),
        "OIDC_CLIENT_SECRET": _get(cfg, "oidc_client_secret", None),
        "OIDC_AUDIENCE": _get(cfg, "oidc_audience", None),
        "OIDC_REDIRECT_URI": _get(cfg, "oidc_redirect_uri", None),
        "OIDC_POST_LOGIN_REDIRECT": _get(cfg, "oidc_post_login_redirect", "/"),
        "OIDC_SCOPES": _get(cfg, "oidc_scopes", "openid profile email"),
        "OIDC_ROLE_CLAIM": _get(cfg, "oidc_role_claim", "realm_access.roles"),
        "OIDC_ROLE_MAP": _get(cfg, "oidc_role_map", None),
        "OIDC_DEFAULT_ROLE": _get(cfg, "oidc_default_role", "user"),
        "OIDC_JWKS_TTL": _get(cfg, "oidc_jwks_ttl", 3600),
        "OIDC_SESSION_SECRET": _get(cfg, "oidc_session_secret", None),
        "OIDC_SESSION_COOKIE": _get(cfg, "oidc_session_cookie", "minix_session"),
        "OIDC_SESSION_TTL": _get(cfg, "oidc_session_ttl", 28800),
        "OIDC_COOKIE_SECURE": _get(cfg, "oidc_cookie_secure", True),
    }
