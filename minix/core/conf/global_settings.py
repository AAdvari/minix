"""
Default Minix settings.

These are used when no project settings module is available.
Project ``settings.py`` files (from ``minix init``) overlay these values
automatically.

Every setting is read from the environment with a sensible default so apps
work without a hand-written ``.env``.
"""

from __future__ import annotations

import dotenv

dotenv.load_dotenv()

from minix.core.conf.env import env, env_optional

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
DEBUG = env("DEBUG", False)
APP_NAME = env("APP_NAME", "minix")
APP_HOST = env("APP_HOST", "0.0.0.0")
APP_PORT = env("APP_PORT", 8000)
SECRET_KEY = env_optional("SECRET_KEY")

# ---------------------------------------------------------------------------
# SQL database
# ---------------------------------------------------------------------------
DB_USER = env("DB_USER", "root")
DB_PASS = env("DB_PASS", "")
DB_HOST = env("DB_HOST", "localhost")
DB_PORT = env("DB_PORT", 3306)
DB_DATABASE = env("DB_DATABASE", "minix")
DB_DRIVER = env("DB_DRIVER", "mysql")

# ---------------------------------------------------------------------------
# Celery / Redis scheduler
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env(
    "CELERY_RESULT_BACKEND",
    "redis://localhost:6379/1",
)
CELERY_TASK_SERIALIZER = env("CELERY_TASK_SERIALIZER", "json")
CELERY_RESULT_SERIALIZER = env("CELERY_RESULT_SERIALIZER", "json")
CELERY_TIMEZONE = env("CELERY_TIMEZONE", "GMT")
REDIS_URL = env("REDIS_URL", CELERY_BROKER_URL)

# ---------------------------------------------------------------------------
# Kafka
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP_SERVERS = env("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------
QDRANT_URL = env("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = env_optional("QDRANT_API_KEY")

# ---------------------------------------------------------------------------
# Object storage (S3-compatible)
# ---------------------------------------------------------------------------
OBJECT_STORAGE_ENDPOINT_URL = env(
    "OBJECT_STORAGE_ENDPOINT_URL",
    "http://localhost:9000",
)
OBJECT_STORAGE_ACCESS_KEY = env("OBJECT_STORAGE_ACCESS_KEY", "minioadmin")
OBJECT_STORAGE_SECRET_KEY = env("OBJECT_STORAGE_SECRET_KEY", "minioadmin")
OBJECT_STORAGE_BUCKET_NAME = env("OBJECT_STORAGE_BUCKET_NAME", "minix")
OBJECT_STORAGE_USE_SSL = env("OBJECT_STORAGE_USE_SSL", False)
OBJECT_STORAGE_VERIFY_SSL = env("OBJECT_STORAGE_VERIFY_SSL", False)

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
