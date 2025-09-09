from qdrant_client import AsyncQdrantClient

from minix.core.connectors import Connector


class QdrantConnector(Connector):
    def __init__(self, url: str, api_key: str = None):
        self.url = url
        self.api_key = api_key
        self.client = None

    async def connect(self) -> None:
        self.client = AsyncQdrantClient(url=self.url, api_key=self.api_key)

    async def disconnect(self) -> None:
        # qdrant-client doesn't need explicit disconnect, but close can be added for compatibility
        self.client = None

    async def is_connected(self) -> bool:
        return self.client is not None