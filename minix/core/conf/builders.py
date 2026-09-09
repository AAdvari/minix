"""Build connector / module configs from the active settings object."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from minix.core.connectors.sql_connector import SqlConnectorConfig
    from minix.core.object_storage.config import ObjectStorageConfig
    from minix.core.scheduler import SchedulerConfig


def sql_connector_config(settings=None) -> "SqlConnectorConfig":
    from minix.core.conf import settings as default_settings
    from minix.core.connectors.sql_connector import SqlConnectorConfig

    s = settings or default_settings
    return SqlConnectorConfig(
        username=s.DB_USER,
        password=s.DB_PASS,
        host=s.DB_HOST,
        port=int(s.DB_PORT) if s.DB_PORT is not None else None,
        database=s.DB_DATABASE,
        driver=s.DB_DRIVER,
    )


def object_storage_config(settings=None) -> "ObjectStorageConfig":
    from minix.core.conf import settings as default_settings
    from minix.core.object_storage.config import ObjectStorageConfig

    s = settings or default_settings
    return ObjectStorageConfig(
        endpoint_url=s.OBJECT_STORAGE_ENDPOINT_URL,
        access_key=s.OBJECT_STORAGE_ACCESS_KEY,
        secret_key=s.OBJECT_STORAGE_SECRET_KEY,
        bucket_name=s.OBJECT_STORAGE_BUCKET_NAME,
        use_ssl=bool(s.OBJECT_STORAGE_USE_SSL),
        verify_ssl=bool(s.OBJECT_STORAGE_VERIFY_SSL),
    )


def scheduler_config(settings=None) -> "SchedulerConfig":
    from minix.core.conf import settings as default_settings
    from minix.core.scheduler import SchedulerConfig

    s = settings or default_settings
    return (
        SchedulerConfig()
        .set_broker_url(s.CELERY_BROKER_URL)
        .set_result_backend(s.CELERY_RESULT_BACKEND)
        .set_task_serializer(s.CELERY_TASK_SERIALIZER)
        .set_result_serializer(s.CELERY_RESULT_SERIALIZER)
        .set_accept_content(["json"])
        .set_timezone(s.CELERY_TIMEZONE)
    )


def kafka_bootstrap_servers(settings=None) -> list[str]:
    from minix.core.conf import settings as default_settings

    s = settings or default_settings
    raw = s.KAFKA_BOOTSTRAP_SERVERS
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]
