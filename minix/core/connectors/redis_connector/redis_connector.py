from redis import Redis
from minix.core.connectors.connector import Connector
from minix.core.conf import settings


class RedisConnector(Connector):
    def __init__(self, url: str | None = None):
        _url = url or settings.REDIS_URL or settings.CELERY_BROKER_URL
        self.client: Redis = Redis.from_url(_url, decode_responses=True)

    def get_client(self) -> Redis:
        return self.client
