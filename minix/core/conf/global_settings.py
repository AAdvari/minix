"""
Default Minix settings.

Used when no project ``config.py`` is available.
``minix init`` scaffolds a ``config.py`` (pydantic-settings)
that overlays these defaults.

``bootstrap_from_settings()`` auto-registers connectors from connection maps and installs
``INSTALLED_MODULES`` unless explicit lists are passed.
"""

from __future__ import annotations

import os

import dotenv

dotenv.load_dotenv(os.environ.get("MINIX_DOTENV_PATH", ".env"))

from minix.core.conf.env import env, env_optional

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
DEBUG = env("DEBUG", False)
APP_NAME = env("APP_NAME", "minix")
APP_HOST = env("APP_HOST", "0.0.0.0")
APP_PORT = env("APP_PORT", 8000)
SECRET_KEY = env_optional("SECRET_KEY")

# Dotted paths to Module instances (or Module subclasses).
# bootstrap_from_settings() installs these when modules= is omitted.
INSTALLED_MODULES = [
    # "minix.core.modules.auth.AuthModule",
    # "src.modules.example.ExampleModule",
]

# ---------------------------------------------------------------------------
# SQL databases
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "USER": env("DB_USER", "minix"),
        "PASSWORD": env("DB_PASS", "minix"),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", 5432),
        "NAME": env("DB_DATABASE", "minix"),
        "DRIVER": env("DB_DRIVER", "postgresql"),
    },
    # "analytics": {
    #     "USER": env("ANALYTICS_DB_USER", "minix"),
    #     "PASSWORD": env("ANALYTICS_DB_PASS", "minix"),
    #     "HOST": env("ANALYTICS_DB_HOST", "localhost"),
    #     "PORT": env("ANALYTICS_DB_PORT", 5432),
    #     "NAME": env("ANALYTICS_DB_DATABASE", "analytics"),
    #     "DRIVER": env("ANALYTICS_DB_DRIVER", "postgresql"),
    # },
}

# ---------------------------------------------------------------------------
# Celery / Redis
# ---------------------------------------------------------------------------
CELERY_CONNECTIONS = {
    "default": {
        "BROKER_URL": env("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        "RESULT_BACKEND": env("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
        "TASK_SERIALIZER": env("CELERY_TASK_SERIALIZER", "json"),
        "RESULT_SERIALIZER": env("CELERY_RESULT_SERIALIZER", "json"),
        "ACCEPT_CONTENT": ["json"],
        "TIMEZONE": env("CELERY_TIMEZONE", "GMT"),
    },
    # "priority": {
    #     "BROKER_URL": env("PRIORITY_CELERY_BROKER_URL", "redis://localhost:6379/2"),
    #     "RESULT_BACKEND": env("PRIORITY_CELERY_RESULT_BACKEND", "redis://localhost:6379/3"),
    #     "TASK_SERIALIZER": "json",
    #     "RESULT_SERIALIZER": "json",
    #     "ACCEPT_CONTENT": ["json"],
    #     "TIMEZONE": env("CELERY_TIMEZONE", "GMT"),
    # },
}

REDIS_CONNECTIONS = {
    "default": {
        "URL": env("REDIS_URL", CELERY_CONNECTIONS["default"]["BROKER_URL"]),
    },
}

# ---------------------------------------------------------------------------
# Kafka
# ---------------------------------------------------------------------------
KAFKA_CLUSTERS = {
    "default": {
        "BOOTSTRAP_SERVERS": env("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
    },
}

# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------
QDRANT_CONNECTIONS = {
    "default": {
        "URL": env("QDRANT_URL", "http://localhost:6333"),
        "API_KEY": env_optional("QDRANT_API_KEY"),
    },
}

# ---------------------------------------------------------------------------
# Object storage (S3-compatible)
# ---------------------------------------------------------------------------
OBJECT_STORAGES = {
    "default": {
        "ENDPOINT_URL": env("OBJECT_STORAGE_ENDPOINT_URL", "http://localhost:9000"),
        "ACCESS_KEY": env("OBJECT_STORAGE_ACCESS_KEY", "minioadmin"),
        "SECRET_KEY": env("OBJECT_STORAGE_SECRET_KEY", "minioadmin"),
        "BUCKET_NAME": env("OBJECT_STORAGE_BUCKET_NAME", "minix"),
        "USE_SSL": env("OBJECT_STORAGE_USE_SSL", False),
        "VERIFY_SSL": env("OBJECT_STORAGE_VERIFY_SSL", False),
    },
}

# ---------------------------------------------------------------------------
# MLflow (optional AI extra)
# ---------------------------------------------------------------------------
MLFLOW_TRACKING_URL = env("MLFLOW_TRACKING_URL", "http://localhost:5000")
PYTHON_VERSION = env("PYTHON_VERSION", "3.11")

# ---------------------------------------------------------------------------
# OIDC (optional auth module)
# ---------------------------------------------------------------------------
OIDC_ISSUER = env("OIDC_ISSUER", "")
OIDC_CLIENT_ID = env("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = env_optional("OIDC_CLIENT_SECRET")
OIDC_AUDIENCE = env_optional("OIDC_AUDIENCE")
OIDC_REDIRECT_URI = env_optional("OIDC_REDIRECT_URI")
OIDC_POST_LOGIN_REDIRECT = env("OIDC_POST_LOGIN_REDIRECT", "/")
OIDC_SCOPES = env("OIDC_SCOPES", "openid profile email")
OIDC_ROLE_CLAIM = env("OIDC_ROLE_CLAIM", "realm_access.roles")
OIDC_ROLE_MAP = env_optional("OIDC_ROLE_MAP")  # JSON string
OIDC_DEFAULT_ROLE = env("OIDC_DEFAULT_ROLE", "user")
OIDC_JWKS_TTL = env("OIDC_JWKS_TTL", 3600)
OIDC_SESSION_SECRET = env_optional("OIDC_SESSION_SECRET")
OIDC_SESSION_COOKIE = env("OIDC_SESSION_COOKIE", "minix_session")
OIDC_SESSION_TTL = env("OIDC_SESSION_TTL", 28800)
OIDC_COOKIE_SECURE = env("OIDC_COOKIE_SECURE", True)
