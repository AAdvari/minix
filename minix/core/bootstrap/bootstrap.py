from __future__ import annotations

import os
import warnings
from typing import Sequence, Tuple

import dotenv

from minix.core.connectors import Connector
from minix.core.module import Module
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from minix.core.registry import Registry
from minix.core.scheduler import Scheduler, SchedulerConfig
from minix.core.conf import settings
from minix.core.conf.builders import (
    connectors_from_settings,
    modules_from_settings,
    scheduler_config,
)

try:
    import pymysql

    pymysql.install_as_MySQLdb()
except ImportError:
    pass

dotenv.load_dotenv()

_SENTINEL = object()
LegacyConnectorEntry = tuple[Connector | object, str | None]
ConnectorEntry = object | LegacyConnectorEntry


def _registry_salt(connector: object, salt=_SENTINEL) -> str | None:
    """Map connection name to Registry salt; explicit tuple salt wins when given."""
    if salt is not _SENTINEL:
        return salt  # type: ignore[return-value]
    name = getattr(connector, "connection_name", None) or "default"
    return None if name == "default" else name


def _is_legacy_connector_tuple_list(connectors: Sequence[ConnectorEntry]) -> bool:
    """True when every entry is a ``(connector, salt)`` pair (legacy shape)."""
    return bool(connectors) and all(
        isinstance(entry, tuple) and len(entry) == 2 for entry in connectors
    )


def _register_connectors_legacy(connectors: Sequence[LegacyConnectorEntry]) -> None:
    """Register ``(connector, salt)`` pairs without emitting a deprecation warning."""
    for connector, salt in connectors:
        if salt is not None:
            Registry().register(connector.__class__, connector, salt=salt)
        else:
            Registry().register(connector.__class__, connector)


def register_connectors(connectors: list[Tuple[Connector, str | None]] | Sequence[LegacyConnectorEntry]):
    """Register ``(connector, salt)`` pairs.

    .. deprecated::
        Kept for backward compatibility. Prefer :func:`bootstrap_from_settings`
        or :func:`register_connector_entries`.
    """
    warnings.warn(
        "register_connectors() is deprecated; prefer bootstrap_from_settings() "
        "or register_connector_entries().",
        DeprecationWarning,
        stacklevel=2,
    )
    _register_connectors_legacy(connectors)


def register_connector_entries(connectors: Sequence[ConnectorEntry]):
    """Register connectors from bare instances and/or ``(connector, salt)`` tuples.

    Bare instances derive Registry salt from ``connection_name`` (``default`` →
    unsalted). Explicit tuple salts win, including ``None`` for the default slot.
    Duplicate ``(type, salt)`` pairs raise ``ImproperlyConfigured``.
    """
    from minix.core.conf import ImproperlyConfigured

    seen: set[tuple[type, str | None]] = set()
    for entry in connectors:
        if isinstance(entry, tuple):
            connector, salt = entry
        else:
            connector, salt = entry, _SENTINEL
        salt = _registry_salt(connector, salt)
        key = (connector.__class__, salt)
        if key in seen:
            label = salt if salt is not None else "default"
            raise ImproperlyConfigured(
                f"Duplicate connector registration for {connector.__class__.__name__} "
                f"with salt {label!r}. Each (connector type, salt) pair must be unique."
            )
        seen.add(key)
        if salt is not None:
            Registry().register(connector.__class__, connector, salt=salt)
        else:
            Registry().register(connector.__class__, connector)


def register_scheduler():
    """Register Celery scheduler.

    Uses ``CELERY_BROKER_URL`` / ``CELERY_RESULT_BACKEND`` from the environment
    when set (legacy); otherwise ``settings.CELERY_CONNECTIONS``.
    """
    broker = os.getenv("CELERY_BROKER_URL")
    backend = os.getenv("CELERY_RESULT_BACKEND")
    if broker is not None or backend is not None:
        cfg = (
            SchedulerConfig()
            .set_broker_url(broker)
            .set_result_backend(backend)
            .set_task_serializer("json")
            .set_result_serializer("json")
            .set_accept_content(["json"])
            .set_timezone("GMT")
        )
    else:
        cfg = scheduler_config(settings)
    Registry().register(Scheduler, Scheduler(cfg))


def register_fast_api(default_cors: bool = True):
    app = FastAPI(title=getattr(settings, "APP_NAME", "minix"))
    if not default_cors:
        # The application installs its own CORS policy.
        Registry().register(FastAPI, app)
        return
    # Allow CORS for localhost-related origins and local network IPs.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=(
            r"^https?://("
            r"localhost|"
            r"127(?:\.\d{1,3}){3}|"
            r"10(?:\.\d{1,3}){3}|"
            r"192\.168(?:\.\d{1,3}){2}|"
            r"172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}|"
            r"\[::1\]"
            r")(?::\d+)?$"
        ),
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    Registry().register(FastAPI, app)


def register_modules(modules: list[Module], default_cors: bool = True):
    fast_api = False
    scheduler = False
    for module in modules:
        if module.controllers is not None and len(module.controllers) > 0:
            fast_api = True
        if module.periodic_tasks is not None and len(module.periodic_tasks) > 0:
            scheduler = True
        if module.tasks is not None and len(module.tasks) > 0:
            scheduler = True

    if fast_api:
        register_fast_api(default_cors)
    if scheduler:
        register_scheduler()
    for module in modules:
        module.install()


def bootstrap(
        modules: list[Module] | None = None,
        connectors: Sequence[ConnectorEntry] | None = None,
        default_cors: bool = True,
):
    """Register explicit connector and module lists.

    .. deprecated::
        Kept for backward compatibility. Prefer :func:`bootstrap_from_settings`
        with ``config.py`` connection maps and ``INSTALLED_MODULES``.

    Only non-empty ``connectors`` / ``modules`` are registered — omitted or
    ``None`` means skip.

    ``default_cors=False`` skips the built-in localhost / private-network CORS
    policy, for an application that installs its own ``CORSMiddleware``.
    """
    warnings.warn(
        "bootstrap() with explicit connector/module lists is deprecated; "
        "prefer bootstrap_from_settings().",
        DeprecationWarning,
        stacklevel=2,
    )
    if connectors:
        if _is_legacy_connector_tuple_list(connectors):
            _register_connectors_legacy(connectors)  # type: ignore[arg-type]
        else:
            register_connector_entries(connectors)
    if modules:
        register_modules(modules, default_cors)


def bootstrap_from_settings(
        modules: list[Module] | None = None,
        connectors: Sequence[ConnectorEntry] | None = None,
        default_cors: bool = True,
):
    """Register connectors and modules from settings when lists are omitted.

    ``connectors``:
    - omitted / ``None`` — auto-wire from settings connection maps
      (``DATABASES``, ``OBJECT_STORAGES``, ``QDRANT_CONNECTIONS``,
      ``REDIS_CONNECTIONS``)
    - explicit sequence — register that list
    - empty sequence — register nothing

    ``modules``:
    - omitted / ``None`` — install ``settings.INSTALLED_MODULES``
    - explicit sequence — install that list
    - empty sequence — install nothing

    ``default_cors=False`` skips the built-in localhost / private-network CORS
    policy, for an application that installs its own ``CORSMiddleware``.
    """
    if connectors is None:
        connectors = connectors_from_settings(settings)
    if connectors:
        register_connector_entries(connectors)

    if modules is None:
        modules = modules_from_settings(settings)
    if modules:
        register_modules(modules, default_cors)
