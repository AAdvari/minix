# Centralized RAG configuration loaded from environment variables.
import os
from dotenv import load_dotenv

load_dotenv()


class RagConfig:
    # Every model call goes through LiteLLM, so each *_MODEL below is any model
    # name LiteLLM supports ("gpt-4o", "anthropic/claude-...", "azure/<deployment>",
    # "ollama/llama3", ...). API keys come from the provider's standard
    # environment variable (OPENAI_API_KEY, ANTHROPIC_API_KEY, AZURE_API_KEY, ...),
    # which LiteLLM reads itself.
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")
    # None = don't pass temperature to the API at all (required for models
    # that reject the parameter, e.g. o1, o3, o4-mini, gpt-4.5).
    # Set LLM_TEMPERATURE=0 in .env to pin deterministic output on models
    # that do support it (gpt-4o, gpt-4-turbo, etc.).
    _temp_env = os.getenv("LLM_TEMPERATURE")
    LLM_TEMPERATURE: float | None = float(_temp_env) if _temp_env is not None else None

    # F-3: neither ChatLiteLLM construction set a timeout, a token ceiling or a
    # retry bound, so a provider that accepted the connection and then stalled
    # hung the request thread indefinitely. B-2 made this load-bearing — the LLM
    # judge now runs on every guarded query, so an un-timed call sits on the hot
    # path of the primary groundedness gate. Applied in
    # `minix/core/modules/rag/llm_factory.py`, the single construction point.
    #
    # None means "leave the provider default alone" rather than imposing one.
    LLM_TIMEOUT_SECONDS: float | None = (
        float(os.getenv("RAG_LLM_TIMEOUT_SECONDS"))
        if os.getenv("RAG_LLM_TIMEOUT_SECONDS") else 60.0
    )
    LLM_MAX_TOKENS: int | None = (
        int(os.getenv("RAG_LLM_MAX_TOKENS"))
        if os.getenv("RAG_LLM_MAX_TOKENS") else 2048
    )
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    # Vector size of the Qdrant collections — it must equal what the embedding
    # model returns.
    EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "1536"))
    # Also send EMBEDDING_DIMENSION to the provider as the `dimensions` request
    # parameter (OpenAI text-embedding-3-* shortens the vector to that size).
    # Set RAG_EMBEDDING_SEND_DIMENSIONS=false for models with a fixed output
    # size that reject the parameter.
    EMBEDDING_SEND_DIMENSIONS: bool = os.getenv(
        "RAG_EMBEDDING_SEND_DIMENSIONS", "true"
    ).lower() in ("1", "true", "yes", "on")

    QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    QDRANT_API_KEY: str | None = os.getenv("QDRANT_API_KEY")

    # Vision / extraction model: PDF and image transcription, document metadata
    # extraction and the LLM chunking strategy.
    DOCUMENT_PROCESSOR_MODEL: str = os.getenv("DOCUMENT_PROCESSOR_MODEL", "gpt-4o")

    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "800"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "100"))
    LLM_CHUNK_SEGMENT_PREVIEW_CHARS: int = int(
        os.getenv("RAG_LLM_CHUNK_SEGMENT_PREVIEW_CHARS", "800")
    )
    LLM_CHUNK_WINDOW_OVERLAP: int = int(
        os.getenv("RAG_LLM_CHUNK_WINDOW_OVERLAP", "4")
    )
    LLM_CHUNK_REPAIR_ENABLED: bool = os.getenv(
        "RAG_LLM_CHUNK_REPAIR_ENABLED", "false"
    ).lower() in ("1", "true", "yes", "on")

    TOP_K: int = int(os.getenv("TOP_K", "5"))
    BM25_WEIGHT: float = float(os.getenv("BM25_WEIGHT", "0.3"))
    VECTOR_WEIGHT: float = float(os.getenv("VECTOR_WEIGHT", "0.7"))

    # LLM reranker (minix/core/modules/rag/retrieval/llm_reranker.py) that re-orders the
    # retrieved chunks before they reach the answer prompt. The env name is kept
    # from the older "selector" it replaced, so existing deployments keep their
    # setting. Disabling it eliminates a source of non-determinism (LLM scoring
    # varies between runs for the same input); the fusion order is then used as-is.
    LLM_SELECTOR_ENABLED: bool = os.getenv("LLM_SELECTOR_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    # Number of chunks handed to the answer prompt on /query, whether the
    # reranker is on (best N after reranking) or off (top N by fusion score), so
    # a multi-collection query doesn't drown the LLM in irrelevant context.
    SELECTOR_FALLBACK_TOP_N: int = int(os.getenv("SELECTOR_FALLBACK_TOP_N", "5"))
    # Model used for reranking. Empty = use LLM_MODEL. A smaller, cheaper model
    # is usually enough for relevance scoring.
    RERANKER_MODEL: str = os.getenv("RAG_RERANKER_MODEL", "")
    # /query only: chunks the reranker scores below this (0-10 scale) are dropped
    # before the answer prompt, as the old selector did at 5. If that drops
    # everything, the best 3 are kept. 0 = pure re-order, nothing dropped.
    # /search never drops — it returns the same top_k, re-ordered.
    RERANKER_MIN_SCORE: float = float(os.getenv("RAG_RERANKER_MIN_SCORE", "5"))
    # Characters of each chunk shown to the reranker (the old selector saw 500).
    RERANKER_MAX_CHARS: int = int(os.getenv("RAG_RERANKER_MAX_CHARS", "1200"))

    # Minimum relevance score for a retrieved chunk to survive the pre-LLM filter.
    # Applied as `max(vector_score, bm25_score_normalized) >= MIN_RELEVANCE_SCORE`.
    # 0.3 is conservative — cosine similarities below this on text-embedding-3-small
    # are almost always unrelated. Tune via env var MIN_RELEVANCE_SCORE.
    MIN_RELEVANCE_SCORE: float = float(os.getenv("MIN_RELEVANCE_SCORE", "0.3"))

    # Keyword (ts_query) construction mode for the BM25/keyword retrieval leg.
    #   plainto — plainto_tsquery: ANDs every content token (legacy default).
    #             A long, multi-term natural-language query then requires one
    #             chunk to contain *every* token, so it matches almost nothing.
    #   or      — OR-join sanitized lexemes via to_tsquery, so any term can
    #             match and ts_rank orders the candidates. Recommended for
    #             natural-language / long queries.
    BM25_QUERY_MODE: str = os.getenv("RAG_BM25_QUERY_MODE", "plainto").lower()

    # Candidate pool size fetched from each retrieval leg before fusion and
    # truncation: fetch_k = max(top_k * FETCH_MULTIPLIER, CANDIDATE_FLOOR).
    # A larger pool lets fusion/ranking surface deeper matches (recall keeps
    # climbing with k); the previous hard-coded top_k*2 starved recall.
    RETRIEVAL_FETCH_MULTIPLIER: int = int(os.getenv("RAG_RETRIEVAL_FETCH_MULTIPLIER", "6"))
    RETRIEVAL_CANDIDATE_FLOOR: int = int(os.getenv("RAG_RETRIEVAL_CANDIDATE_FLOOR", "50"))

    # Ingest-time document-identity enrichment. When true, a compact header with
    # the document's title / parties / source name is prepended to every chunk
    # before embedding + keyword indexing, so a query that names the document
    # (e.g. "the NDA between DoiT and ICN") can match the right one among many
    # near-identical contracts — the discriminating tokens otherwise live only
    # in the filename and are invisible to retrieval. Off by default (changes
    # stored chunk text + snippets); enable per deployment + re-ingest.
    INGEST_IDENTITY_ENRICHMENT: bool = os.getenv(
        "RAG_INGEST_IDENTITY_ENRICHMENT", "false"
    ).lower() in ("1", "true", "yes", "on")

    DEFAULT_COLLECTION: str = os.getenv("DEFAULT_COLLECTION", "default")

    # Master switch for authentication + role enforcement on the RAG routes.
    # While false, a request without an API key runs as an anonymous admin
    # (single-user developer flow). While true, every RAG route requires a
    # valid key and the caller's global role (admin / user / readonly) is
    # enforced. A consuming layer may add finer-grained (per-collection)
    # access control on top of the same flag.
    ACCESS_CONTROL_ENABLED: bool = os.getenv("RAG_ACCESS_CONTROL_ENABLED", "false").lower() in ("1", "true", "yes", "on")
