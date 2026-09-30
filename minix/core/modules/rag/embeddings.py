# Provider-neutral embeddings: a LangChain `Embeddings` backed by LiteLLM, so the
# embedding model can come from any supported provider (OpenAI, Azure, Cohere,
# Voyage, Bedrock, Ollama, …) by changing EMBEDDING_MODEL.
from __future__ import annotations

from typing import Any

import litellm
from langchain_core.embeddings import Embeddings

# Same request bounds the OpenAI SDK applied by default.
_TIMEOUT_SECONDS = 600
_MAX_RETRIES = 2


def _field(item: Any, key: str):
    return item[key] if isinstance(item, dict) else getattr(item, key)


class LiteLLMEmbeddings(Embeddings):
    """Embeds texts through ``litellm.embedding``.

    ``dimensions`` is sent as the request parameter of the same name (it
    shortens the vector for models that support it, e.g. OpenAI
    ``text-embedding-3-*``); leave it ``None`` for models with a fixed size.
    Texts are sent in batches of ``batch_size``.
    """

    def __init__(self, model: str, dimensions: int | None = None, batch_size: int = 100):
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            kwargs: dict[str, Any] = {
                "model": self.model,
                "input": texts[start:start + self.batch_size],
                "timeout": _TIMEOUT_SECONDS,
                "num_retries": _MAX_RETRIES,
            }
            if self.dimensions:
                kwargs["dimensions"] = self.dimensions
            try:
                response = litellm.embedding(**kwargs)
            except litellm.UnsupportedParamsError as exc:
                if "dimensions" not in kwargs:
                    raise
                raise ValueError(
                    f"The embedding model {self.model!r} does not accept the "
                    "`dimensions` parameter. Set RAG_EMBEDDING_SEND_DIMENSIONS=false "
                    "and make EMBEDDING_DIMENSION equal to the size the model returns."
                ) from exc
            data = sorted(response.data, key=lambda d: _field(d, "index"))
            vectors.extend(list(_field(d, "embedding")) for d in data)
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(list(texts))

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]
