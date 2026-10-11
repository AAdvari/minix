import os

from redis import Redis

from minix.core.connectors.connector import Connector


class RedisConnector(Connector):
    def __init__(
        self,
        url: str | None = None,
        *,
        connection: str | None = None,
        settings=None,
    ):
        """Create a Redis connector.

        Pass ``url`` explicitly, or pass ``connection`` / ``settings`` to read
        ``settings.REDIS_CONNECTIONS[connection]``. With no arguments at all,
        ``CELERY_BROKER_URL`` is used (default ``redis://localhost:6379``).
        """
        self.connection_name = connection or "default"
        if url is None:
            if connection is None and settings is None:
                url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379")
            else:
                from minix.core.conf.builders import redis_connection_url

                url = redis_connection_url(settings=settings, connection=self.connection_name)
        self.client: Redis = Redis.from_url(url, decode_responses=True)

    def get_client(self) -> Redis:
        return self.client
