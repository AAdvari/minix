"""Build connector / module configs from the active settings object."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from minix.core.conf import ImproperlyConfigured

if TYPE_CHECKING:
    from minix.core.connectors.sql_connector import SqlConnectorConfig
    from minix.core.object_storage.config import ObjectStorageConfig
    from minix.core.scheduler import SchedulerConfig

DEFAULT_CONNECTION = "default"


def _pick(raw: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first present key in ``raw`` (supports UPPER and lower names)."""
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return default


def _settings(settings=None):
    from minix.core.conf import settings as default_settings

    return settings or default_settings


def get_connection(settings, map_attr: str, key: str) -> dict[str, Any]:
    """Return ``settings.<map_attr>[key]`` or raise with a clear hint."""
    s = _settings(settings)
    connections = getattr(s, map_attr, None)
    if not isinstance(connections, dict) or not connections:
        raise ImproperlyConfigured(
            f"settings.{map_attr} is missing or empty. "
            f"Define it in config.py, e.g. "
            f"{map_attr} = {{'default': {{...}}}}"
        )
    if key not in connections:
        available = ", ".join(repr(k) for k in connections) or "(none)"
        raise ImproperlyConfigured(
            f"Unknown {map_attr} key {key!r}. Available: {available}. "
            f"Add {map_attr}[{key!r}] = {{...}} in your config."
        )
    cfg = connections[key]
    if not isinstance(cfg, dict):
        raise ImproperlyConfigured(
            f"settings.{map_attr}[{key!r}] must be a dict of connection options, "
            f"got {type(cfg).__name__}."
        )
    return cfg


def sql_connector_config(
    settings=None,
    connection: str = DEFAULT_CONNECTION,
) -> "SqlConnectorConfig":
    from minix.core.connectors.sql_connector import SqlConnectorConfig

    raw = get_connection(settings, "DATABASES", connection)
    port = _pick(raw, "PORT", "port")
    return SqlConnectorConfig(
        username=_pick(raw, "USER", "username", "user"),
        password=_pick(raw, "PASSWORD", "password"),
        host=_pick(raw, "HOST", "host"),
        port=int(port) if port is not None else None,
        database=_pick(raw, "NAME", "DATABASE", "database", "name"),
        driver=_pick(raw, "DRIVER", "driver"),
    )


def object_storage_config(
    settings=None,
    connection: str = DEFAULT_CONNECTION,
) -> "ObjectStorageConfig":
    from minix.core.object_storage.config import ObjectStorageConfig

    raw = get_connection(settings, "OBJECT_STORAGES", connection)
    return ObjectStorageConfig(
        endpoint_url=_pick(raw, "ENDPOINT_URL", "endpoint_url"),
        access_key=_pick(raw, "ACCESS_KEY", "access_key"),
        secret_key=_pick(raw, "SECRET_KEY", "secret_key"),
        bucket_name=_pick(raw, "BUCKET_NAME", "bucket_name"),
        use_ssl=bool(_pick(raw, "USE_SSL", "use_ssl", default=False)),
        verify_ssl=bool(_pick(raw, "VERIFY_SSL", "verify_ssl", default=False)),
    )


def qdrant_connection_config(
    settings=None,
    connection: str = DEFAULT_CONNECTION,
) -> dict:
    return get_connection(settings, "QDRANT_CONNECTIONS", connection)


def redis_connection_url(
    settings=None,
    connection: str = DEFAULT_CONNECTION,
) -> str:
    raw = get_connection(settings, "REDIS_CONNECTIONS", connection)
    url = _pick(raw, "URL", "url")
    if not url:
        raise ImproperlyConfigured(
            f"settings.REDIS_CONNECTIONS[{connection!r}] must include 'URL' or 'url'."
        )
    return url


def scheduler_config(
    settings=None,
    connection: str = DEFAULT_CONNECTION,
) -> "SchedulerConfig":
    from minix.core.scheduler import SchedulerConfig

    raw = get_connection(settings, "CELERY_CONNECTIONS", connection)
    accept = _pick(raw, "ACCEPT_CONTENT", "accept_content", default=["json"])
    if isinstance(accept, str):
        accept = [part.strip() for part in accept.split(",") if part.strip()]
    return (
        SchedulerConfig()
        .set_broker_url(_pick(raw, "BROKER_URL", "broker_url"))
        .set_result_backend(_pick(raw, "RESULT_BACKEND", "result_backend"))
        .set_task_serializer(
            _pick(raw, "TASK_SERIALIZER", "task_serializer", default="json")
        )
        .set_result_serializer(
            _pick(raw, "RESULT_SERIALIZER", "result_serializer", default="json")
        )
        .set_accept_content(accept)
        .set_timezone(_pick(raw, "TIMEZONE", "timezone", default="GMT"))
    )


def kafka_bootstrap_servers(
    settings=None,
    connection: str = DEFAULT_CONNECTION,
) -> list[str]:
    cluster = get_connection(settings, "KAFKA_CLUSTERS", connection)
    raw = _pick(cluster, "BOOTSTRAP_SERVERS", "bootstrap_servers")

    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def connectors_from_settings(settings=None) -> list:
    """Build connector instances for every named connection in settings maps.

    Maps wired automatically:
    - ``DATABASES`` → ``SqlConnector``
    - ``OBJECT_STORAGES`` → ``ObjectStorageConnector``
    - ``QDRANT_CONNECTIONS`` → ``QdrantConnector``
    - ``REDIS_CONNECTIONS`` → ``RedisConnector``

    Celery stays on ``CELERY_CONNECTIONS`` via ``scheduler_config`` / module install.
    """
    s = _settings(settings)
    connectors: list = []

    databases = getattr(s, "DATABASES", None) or {}
    if isinstance(databases, dict):
        from minix.core.connectors import SqlConnector

        for name in databases:
            connectors.append(SqlConnector(connection=name, settings=s))

    storages = getattr(s, "OBJECT_STORAGES", None) or {}
    if isinstance(storages, dict):
        from minix.core.object_storage import ObjectStorageConnector

        for name in storages:
            connectors.append(ObjectStorageConnector(connection=name, settings=s))

    qdrant = getattr(s, "QDRANT_CONNECTIONS", None) or {}
    if isinstance(qdrant, dict):
        from minix.core.connectors.qdrant_connector import QdrantConnector

        for name in qdrant:
            connectors.append(QdrantConnector(connection=name, settings=s))

    redis = getattr(s, "REDIS_CONNECTIONS", None) or {}
    if isinstance(redis, dict):
        from minix.core.connectors.redis_connector import RedisConnector

        for name in redis:
            connectors.append(RedisConnector(connection=name, settings=s))

    return connectors


def import_string(path: str):
    """Import ``pkg.mod.attr`` and return the attribute."""
    import importlib

    module_path, sep, attr = path.rpartition(".")
    if not sep or not module_path or not attr:
        raise ImproperlyConfigured(
            f"Invalid import path {path!r}. Expected 'package.module.Attribute'."
        )
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImproperlyConfigured(
            f"Could not import module {module_path!r} for INSTALLED_MODULES "
            f"entry {path!r}: {exc}"
        ) from exc
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise ImproperlyConfigured(
            f"Module {module_path!r} has no attribute {attr!r} "
            f"(INSTALLED_MODULES entry {path!r})."
        ) from exc


def modules_from_settings(settings=None) -> list:
    """Resolve ``settings.INSTALLED_MODULES`` to Module instances.

    Each entry is a dotted path to a ``Module`` instance or subclass.
    Subclasses are instantiated with no arguments.
    """
    from minix.core.module import Module

    s = _settings(settings)
    paths = getattr(s, "INSTALLED_MODULES", None)
    if paths is None:
        return []
    if not isinstance(paths, (list, tuple)):
        raise ImproperlyConfigured(
            "settings.INSTALLED_MODULES must be a list of dotted paths, "
            f"got {type(paths).__name__}."
        )

    modules: list = []
    for path in paths:
        if not isinstance(path, str) or not path.strip():
            raise ImproperlyConfigured(
                f"INSTALLED_MODULES entries must be non-empty strings, got {path!r}."
            )
        obj = import_string(path.strip())
        if isinstance(obj, type) and issubclass(obj, Module):
            obj = obj()
        if not isinstance(obj, Module):
            raise ImproperlyConfigured(
                f"INSTALLED_MODULES entry {path!r} resolved to "
                f"{type(obj).__name__}, expected a Module instance or subclass."
            )
        modules.append(obj)
    return modules
