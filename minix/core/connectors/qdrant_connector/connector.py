from __future__ import annotations

import warnings

from minix.core.connectors.connector import Connector


class QdrantConnector(Connector):
    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        *,
        connection: str = "default",
        settings=None,
    ):
        """Create a Qdrant connector.

        Prefer ``QdrantConnector(connection=...)`` with
        ``settings.QDRANT_CONNECTIONS``. Passing ``url`` / ``api_key`` is
        deprecated but still supported for backward compatibility.
        Registry identity remains the bootstrap **salt**.
        """
        self.connection_name = connection

        if url is not None:
            warnings.warn(
                "Passing url/api_key to QdrantConnector is deprecated; "
                "use QdrantConnector(connection=...) with settings.QDRANT_CONNECTIONS instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            self.url = url
            self.api_key = api_key
        else:
            from minix.core.conf.builders import qdrant_connection_config

            cfg = qdrant_connection_config(settings=settings, connection=connection)
            self.url = cfg.get("URL", cfg.get("url"))
            self.api_key = (
                api_key if api_key is not None else cfg.get("API_KEY", cfg.get("api_key"))
            )
        self.client = None

    def connect(self) -> None:
        try:
            from qdrant_client import AsyncQdrantClient  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "qdrant-client is required for QdrantConnector. "
                "Install with: pip install 'minix[vdb]'"
            ) from exc

        self.client = AsyncQdrantClient(url=self.url, api_key=self.api_key)

    def disconnect(self) -> None:
        self.client = None

    def is_connected(self) -> bool:
        return self.client is not None
