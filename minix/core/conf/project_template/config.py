from __future__ import annotations

from typing import Any

from minix.core.conf import BaseSettings, Field, SettingsConfigDict
from minix.core.conf.env import env, env_optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    debug: bool = False
    app_name: str = "my_project"
    app_host: str = "0.0.0.0"
    # Placeholder __APP_PORT__ is replaced by `minix init` (quoted so the template is valid Python).
    app_port: int = int("__APP_PORT__")
    secret_key: str | None = None

    # Modules installed when bootstrap_from_settings(modules=...) is omitted
    installed_modules: list[str] = Field(
        default_factory=lambda: [
            "minix.core.modules.auth.AuthModule",
            # "src.modules.example.ExampleModule",
        ]
    )

    # SQL — add another key to register a second database automatically
    databases: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: {
            "default": {
                "user": env("DB_USER", "root"),
                "password": env("DB_PASS", ""),
                "host": env("DB_HOST", "localhost"),
                "port": env("DB_PORT", int("__DB_PORT__")),
                "name": env("DB_DATABASE", "minix"),
                "driver": env("DB_DRIVER", "mysql"),
            },
# __BEGIN_CLICKHOUSE__
            "clickhouse": {
                "user": env("CLICKHOUSE_USER", "default"),
                "password": env("CLICKHOUSE_PASS", ""),
                "host": env("CLICKHOUSE_HOST", "localhost"),
                "port": env("CLICKHOUSE_PORT", 9000),
                "name": env("CLICKHOUSE_DATABASE", "default"),
                "driver": "clickhouse",
            },
# __END_CLICKHOUSE__
            # "analytics": {
            #     "user": env("ANALYTICS_DB_USER", "root"),
            #     "password": env("ANALYTICS_DB_PASS", ""),
            #     "host": env("ANALYTICS_DB_HOST", "localhost"),
            #     "port": env("ANALYTICS_DB_PORT", 3306),
            #     "name": env("ANALYTICS_DB_DATABASE", "analytics"),
            #     "driver": env("ANALYTICS_DB_DRIVER", "mysql"),
            # },
        }
    )

    # Celery
    celery_connections: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: {
            "default": {
                "broker_url": env(
                    "CELERY_BROKER_URL", "redis://localhost:__REDIS_PORT__/0"
                ),
                "result_backend": env(
                    "CELERY_RESULT_BACKEND", "redis://localhost:__REDIS_PORT__/1"
                ),
                "task_serializer": env("CELERY_TASK_SERIALIZER", "json"),
                "result_serializer": env("CELERY_RESULT_SERIALIZER", "json"),
                "accept_content": ["json"],
                "timezone": env("CELERY_TIMEZONE", "GMT"),
            },
            # "priority": {
            #     "broker_url": env("PRIORITY_CELERY_BROKER_URL", "redis://localhost:6379/2"),
            #     "result_backend": env(
            #         "PRIORITY_CELERY_RESULT_BACKEND", "redis://localhost:6379/3"
            #     ),
            #     "task_serializer": "json",
            #     "result_serializer": "json",
            #     "accept_content": ["json"],
            #     "timezone": env("CELERY_TIMEZONE", "GMT"),
            # },
        }
    )

    # Redis
    redis_connections: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: {
            "default": {
                "url": env(
                    "REDIS_URL",
                    env("CELERY_BROKER_URL", "redis://localhost:__REDIS_PORT__/0"),
                ),
            },
        }
    )

    # Kafka
    kafka_clusters: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: {
            "default": {
                "bootstrap_servers": env("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            },
        }
    )

# __BEGIN_VDB__
    # Qdrant (minix[vdb])
    qdrant_connections: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: {
            "default": {
                "url": env("QDRANT_URL", "http://localhost:__QDRANT_PORT__"),
                "api_key": env_optional("QDRANT_API_KEY"),
            },
        }
    )

# __END_VDB__
# __BEGIN_NO_VDB__
    qdrant_connections: dict[str, dict[str, Any]] = Field(default_factory=dict)

# __END_NO_VDB__
    # Object storage (S3 / MinIO)
    object_storages: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: {
            "default": {
                "endpoint_url": env(
                    "OBJECT_STORAGE_ENDPOINT_URL",
                    "http://localhost:__OBJECT_STORAGE_PORT__",
                ),
                "access_key": env("OBJECT_STORAGE_ACCESS_KEY", "minioadmin"),
                "secret_key": env("OBJECT_STORAGE_SECRET_KEY", "minioadmin"),
                "bucket_name": env("OBJECT_STORAGE_BUCKET_NAME", "minix"),
                "use_ssl": env("OBJECT_STORAGE_USE_SSL", False),
                "verify_ssl": env("OBJECT_STORAGE_VERIFY_SSL", False),
            },
        }
    )

    # Optional
# __BEGIN_AI__
    mlflow_tracking_url: str = env(
        "MLFLOW_TRACKING_URL", "http://localhost:__MLFLOW_PORT__"
    )
# __END_AI__
# __BEGIN_NO_AI__
    mlflow_tracking_url: str = "http://localhost:5000"
# __END_NO_AI__
    python_version: str = "3.11"

    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str | None = None
    oidc_audience: str | None = None
    oidc_redirect_uri: str | None = None
    oidc_post_login_redirect: str = "/"
    oidc_scopes: str = "openid profile email"
    oidc_role_claim: str = "realm_access.roles"
    oidc_role_map: str | None = None
    oidc_default_role: str = "user"
    oidc_jwks_ttl: int = 3600
    oidc_session_secret: str | None = None
    oidc_session_cookie: str = "minix_session"
    oidc_session_ttl: int = 28800
    oidc_cookie_secure: bool = True


config = Settings()
