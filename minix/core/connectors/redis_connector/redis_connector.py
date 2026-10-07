from redis import Redis


class RedisConnector:
    def __init__(
        self,
        url: str | None = None,
        *,
        connection: str = "default",
        settings=None,
    ):
        """Create a Redis connector.

        Pass ``url`` explicitly, or omit it to read
        ``settings.REDIS_CONNECTIONS[connection]``.
        """
        self.connection_name = connection
        if url is None:
            from minix.core.conf.builders import redis_connection_url

            url = redis_connection_url(settings=settings, connection=connection)
        self.client: Redis = Redis.from_url(url, decode_responses=True)

    def get_client(self) -> Redis:
        return self.client
