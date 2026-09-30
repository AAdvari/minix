# Qdrant vector store operations: create/delete collections, search, manage vectors.
from __future__ import annotations

from functools import lru_cache

from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from minix.core.connectors import QdrantConnector
from minix.core.modules.rag.config import RagConfig
from minix.core.modules.rag.embeddings import LiteLLMEmbeddings
from minix.core.registry import Registry


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    """Synchronous Qdrant client for the RAG module.

    The connection details come from a `QdrantConnector` registered at bootstrap
    when there is one — the same way every other connector is wired — and
    otherwise from QDRANT_URL / QDRANT_API_KEY. (The framework connector wraps
    the *async* client; LangChain's vector store needs the sync one, so only the
    url and api key are shared.)
    """
    connector = Registry().get(QdrantConnector)
    if connector is not None:
        url, api_key = connector.url, connector.api_key
    else:
        url, api_key = RagConfig.QDRANT_URL, RagConfig.QDRANT_API_KEY
    return QdrantClient(url=url, api_key=api_key, timeout=30)


@lru_cache(maxsize=1)
def get_embeddings() -> LiteLLMEmbeddings:
    return LiteLLMEmbeddings(
        model=RagConfig.EMBEDDING_MODEL,
        dimensions=(
            RagConfig.EMBEDDING_DIMENSION if RagConfig.EMBEDDING_SEND_DIMENSIONS else None
        ),
    )


# Payload fields that retrieval filters on. Indexed at collection-creation
# time so retrieval filters never trigger a full payload scan.
_REQUIRED_PAYLOAD_INDEXES: dict[str, qmodels.PayloadSchemaType] = {
    "metadata.document_id": qmodels.PayloadSchemaType.KEYWORD,
    "metadata.collection_name": qmodels.PayloadSchemaType.KEYWORD,
    # Fields a consuming layer filters on (access levels, scope/tenancy keys)
    # are registered via register_payload_index() — the generic framework has
    # none of its own.
}


def register_payload_index(field: str, schema: qmodels.PayloadSchemaType) -> None:
    """Register a payload field to index at collection-creation time.

    Lets a consuming module (e.g. an access-control or tenancy layer) add its
    own hard-filter field to the built-in index set without editing the
    framework. Idempotent:
    re-registering the same field just overwrites the schema. Call at import
    time, before any collection is created.
    """
    _REQUIRED_PAYLOAD_INDEXES[field] = schema


def ensure_payload_indexes(name: str) -> dict[str, str]:
    """Create the required payload indexes on a Qdrant collection. Idempotent:
    re-creating an existing index is a no-op (Qdrant returns the existing one).
    Returns {field: 'created' | 'exists' | 'error: ...'}."""
    client = get_qdrant_client()
    results: dict[str, str] = {}
    for field, schema in _REQUIRED_PAYLOAD_INDEXES.items():
        try:
            client.create_payload_index(
                collection_name=name,
                field_name=field,
                field_schema=schema,
            )
            results[field] = "created"
        except Exception as e:
            msg = str(e).lower()
            if "already exists" in msg or "exists" in msg:
                results[field] = "exists"
            else:
                results[field] = f"error: {e}"
    return results


def create_qdrant_collection(name: str) -> None:
    client = get_qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if name in existing:
        raise ValueError(f"Qdrant collection '{name}' already exists.")
    client.create_collection(
        collection_name=name,
        vectors_config=qmodels.VectorParams(
            size=RagConfig.EMBEDDING_DIMENSION,
            distance=qmodels.Distance.COSINE,
            hnsw_config=qmodels.HnswConfigDiff(m=16, ef_construct=100),
        ),
        on_disk_payload=False,
    )
    # Ship payload indexes with the column, not later — full-scan filtering
    # on access_level is the documented perf cliff.
    ensure_payload_indexes(name)


def delete_qdrant_collection(name: str) -> bool:
    client = get_qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        return False
    client.delete_collection(name)
    return True


def get_qdrant_collection_info(name: str) -> dict | None:
    client = get_qdrant_client()
    try:
        info = client.get_collection(name)
        return {
            "vectors_count": info.points_count or 0,
            "index_status": str(info.status),
            "vector_size": info.config.params.vectors.size,
            "distance": str(info.config.params.vectors.distance),
        }
    except Exception:
        return None


def list_qdrant_collections() -> list[str]:
    return [c.name for c in get_qdrant_client().get_collections().collections]


def get_vectorstore(collection_name: str) -> QdrantVectorStore:
    return QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=collection_name,
        embedding=get_embeddings(),
    )


def delete_document_vectors(collection_name: str, document_id: str) -> None:
    client = get_qdrant_client()
    client.delete(
        collection_name=collection_name,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="metadata.document_id",
                        match=qmodels.MatchValue(value=document_id),
                    )
                ]
            )
        ),
    )


def vector_search(query: str, collection_name: str, k: int = 10,
                   filters: dict | None = None,
                   allowed_document_ids: set[str] | list[str] | None = None,
                   hard_filters: dict[str, int | str] | None = None) -> list:
    """
    Dense-vector similarity search with scores.

    Returns a list of langchain Documents whose metadata carries a
    `vector_score` key in the range [0, 1] (cosine similarity, higher = better).

    Access control:
        `allowed_document_ids=None`   → no access filter is applied (caller is
                                        admin or feature flag is off).
        `allowed_document_ids=set()`  → empty set → return [] without hitting
                                        Qdrant; caller may see no documents.
        `allowed_document_ids={...}`  → server-side AND filter on
                                        `metadata.document_id`. Caller-supplied
                                        `filters` cannot widen this.

    Both legs of hybrid retrieval must derive from one allowed-doc-id call.
    """
    if allowed_document_ids is not None and len(allowed_document_ids) == 0:
        return []
    store = get_vectorstore(collection_name)
    must_conditions: list = []
    if filters:
        for key, val in filters.items():
            must_conditions.append(
                qmodels.FieldCondition(
                    key=f"metadata.{key}",
                    match=qmodels.MatchValue(value=str(val)),
                )
            )
    if allowed_document_ids is not None:
        must_conditions.append(
            qmodels.FieldCondition(
                key="metadata.document_id",
                match=qmodels.MatchAny(any=list(allowed_document_ids)),
            )
        )
    # Generic hard filters — the framework's scope injection point. Each entry
    # ANDs into `must` PRESERVING the Python value type, so an int scope
    # renders MatchValue(value=<int>) (unlike the caller-supplied `filters`
    # dict, which stringifies).
    if hard_filters:
        for key, val in hard_filters.items():
            must_conditions.append(
                qmodels.FieldCondition(
                    key=f"metadata.{key}",
                    match=qmodels.MatchValue(value=val),
                )
            )
    qdrant_filter = qmodels.Filter(must=must_conditions) if must_conditions else None
    results = store.similarity_search_with_score(query, k=k, filter=qdrant_filter)
    docs = []
    for doc, score in results:
        # Stamp the cosine-similarity score so the retriever can threshold on it.
        doc.metadata = {**doc.metadata, "vector_score": float(score)}
        docs.append(doc)
    return docs
