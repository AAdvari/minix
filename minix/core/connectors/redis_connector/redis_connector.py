import os
from redis import Redis
from minix.core.connectors.connector import Connector


class RedisConnector(Connector):
    def __init__(self, url: str | None = None):
        _url = url or os.getenv("CELERY_BROKER_URL", "redis://localhost:6379")
        self.client: Redis = Redis.from_url(_url, decode_responses=True)

    def get_client(self) -> Redis:
        return self.client
