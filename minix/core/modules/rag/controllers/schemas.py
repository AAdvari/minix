# Pydantic request/response schemas for the RAG API endpoints.
import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field, model_validator

from minix.core.modules.rag.config import RagConfig


# Shared name pattern for representation labels — lowercase identifiers,
# matches the collection-name pattern used elsewhere in the API.
_QUERY_NAME_PATTERN = r"^[a-z0-9_-]+$"
_METADATA_FILTER_KEY = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


# Valid chunking strategies — kept in sync with SmartChunker._STRATEGIES.
# Using Literal so Pydantic rejects unknown values with a clear 422 error
# (fixes the silent override where e.g. "recursive" was accepted at create
# time but then quietly downgraded to "smart" during ingest).
ChunkingStrategy = Literal[
    "smart", "fixed", "by_heading", "by_clause", "qa", "sentence", "llm",
]


class ChunkingConfig(BaseModel):
    strategy: ChunkingStrategy = Field(
        default="smart",
        description=(
            "One of: smart | fixed | by_heading | by_clause | qa | sentence | llm. "
            "Any other value is rejected with HTTP 422 — no silent fallback."
        ),
    )
    chunk_size: int = Field(default=800, ge=100, le=8000)
    chunk_overlap: int = Field(default=100, ge=0, le=500)
    min_chunk_size: int = Field(default=100, ge=0, le=500)
    instruction: str | None = Field(
        default=None,
        description="Natural-language chunking instruction for strategy='llm'.",
    )


class ChunkingStrategyInfo(BaseModel):
    """API-owned UI metadata for one selectable chunking strategy.

    Returned by GET /rag/chunking/strategies so the UI renders labels and
    descriptions from the backend instead of duplicating the enum. Sourced from
    chunking.STRATEGY_METADATA, which is asserted to match the executable
    strategy registry."""

    value: ChunkingStrategy
    label: str
    option_label: str
    description: str
    requires_instruction: bool


class CreateCollectionRequest(BaseModel):
    name: str = Field(..., pattern=r"^[a-z0-9_-]{1,64}$")
    description: str | None = None
    chunking_config: ChunkingConfig = Field(default_factory=ChunkingConfig)


class CollectionInfo(BaseModel):
    name: str
    description: str | None
    chunking_config: dict
    created_at: datetime
    documents: int
    chunks: int
    vectors: int
    index_status: str | None


# PATCH body — chunking_config is mutable post-create (description stays
# create-time only). Partial: any subset of ChunkingConfig
# fields is allowed; missing fields keep their current value.
class UpdateChunkingConfig(BaseModel):
    strategy: ChunkingStrategy | None = None
    chunk_size: int | None = Field(default=None, ge=100, le=8000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=500)
    min_chunk_size: int | None = Field(default=None, ge=0, le=500)
    instruction: str | None = None


class UpdateCollectionRequest(BaseModel):
    chunking_config: UpdateChunkingConfig | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "UpdateCollectionRequest":
        if self.chunking_config is None:
            raise ValueError("PATCH body must include `chunking_config`.")
        return self


class JobAccepted(BaseModel):
    job_id: str
    status: str = "pending"
    message: str = "Job accepted. Poll GET /rag/jobs/{job_id} for status."


class JobStatus(BaseModel):
    job_id: str
    type: str
    status: str
    collection_name: str | None
    document_id: str | None
    result: dict | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class DocumentDetail(BaseModel):
    document_id: str
    collection_name: str
    source_file: str | None
    document_type: str
    status: str
    extracted_metadata: dict
    chunks_count: int
    error_message: str | None
    created_at: datetime
    indexed_at: datetime | None


class DocumentListResponse(BaseModel):
    documents: list[DocumentDetail]
    total: int
    page: int
    page_size: int
    pages: int


class ChunkDetail(BaseModel):
    chunk_id: str
    chunk_index: int | None
    section_type: str | None
    parent_heading: str | None
    collection_name: str
    char_count: int
    content: str


class ChunkListResponse(BaseModel):
    chunks: list[ChunkDetail]
    total: int
    page: int
    page_size: int
    pages: int
    document_id: str
    collection_name: str


# ── Search ────────────────────────────────────────────────────────────────────

# F-3: input bounds on the inference path, chosen from the observed distribution
# in this deployment rather than round numbers.
#
# Query/search text is tiny in practice — `rag_query_requests.question` measured
# p50=79, p95=181, p99=222 chars, and the only rows above 8 KB were 320 KB abuse
# probes. 4000 is ~18x p99: generous enough for a question with a
# pasted paragraph, small enough that the probe is rejected at the schema
# boundary.
#
# Ingest text is deliberately NOT bounded tightly, because real documents here
# are large: per-document text measured p50=130 KB, p95=206 KB, max=3.7 MB. A
# tight limit would reject legitimate ingests. The 10 MB ceiling is a sanity bound
# against a pathological payload (~2.7x the largest real document); the actual
# controls on ingest volume are the rate limit and the `documents_ingested` quota
# gate added with this change.
_MAX_QUERY_CHARS = 4000
_MAX_INGEST_TEXT_CHARS = 10_000_000


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=_MAX_QUERY_CHARS)
    collection: str = RagConfig.DEFAULT_COLLECTION
    top_k: int = Field(default=5, ge=1, le=50)
    mode: Literal["hybrid", "vector", "keyword"] = Field(
        default="hybrid", description="hybrid | vector | keyword"
    )
    filters: dict = Field(default={})
    rerank: bool = Field(
        default=False,
        description=(
            "Re-order the top_k results with the LLM reranker. Same results, new "
            "order; each result gets a `rerank_score` (0-10). Adds one LLM call."
        ),
    )

    @model_validator(mode="after")
    def _validate_filter_keys(self) -> "SearchRequest":
        for key in self.filters:
            if not _METADATA_FILTER_KEY.fullmatch(str(key)):
                raise ValueError(
                    f"Invalid metadata filter key {key!r}. "
                    "Keys must match ^[A-Za-z0-9_.-]{{1,128}}$."
                )
        return self


class SearchAccepted(BaseModel):
    search_id: int
    status: str = "pending"
    message: str = "Search accepted. Poll GET /rag/search/{search_id} for results."


class SearchResult(BaseModel):
    rank: int
    content: str
    document_id: str
    score: float | None
    metadata: dict
    search_type: str
    # LLM reranker score (0-10). Present only when the request set rerank=true
    # and reranking succeeded; `score` stays the retrieval relevance score.
    rerank_score: float | None = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
    total: int
    query: str
    collection: str
    mode: str
    # True when the results were re-ordered by the LLM reranker. False when it
    # was not requested or failed (then `rerank_fallback_reason` says why).
    reranked: bool | None = None
    rerank_fallback_reason: str | None = None


class SearchStatusResponse(BaseModel):
    search_id: int
    status: str                     # pending | processing | completed | failed
    success: bool | None
    # Optional so a consumer that scrubs request text in place can still serve
    # the row.
    query: str | None = None
    collection: str
    mode: str
    top_k: int
    result: SearchResponse | None
    error_message: str | None
    duration_ms: int | None
    created_at: datetime
    completed_at: datetime | None


# ── Query ─────────────────────────────────────────────────────────────────────

RefusalReason = Literal[
    "out_of_corpus",       # no relevant chunks anywhere in the corpus
    "out_of_scope",        # chunks exist but don't match the question
    "policy_violation",    # prompt injection / disallowed request
    "ambiguous",           # multiple senses; clarification needed
]


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=_MAX_QUERY_CHARS)
    collection: str | None = Field(
        default=None,
        description="Single collection to query. Mutually exclusive with search_collections.",
    )
    # Fix 1 — explicit allowlist for multi-collection queries. `collection: null`
    # used to silently fan out to EVERY collection on the server (data-boundary leak).
    # Callers must now opt-in with an explicit list, or specify a single `collection`.
    search_collections: list[str] | None = Field(
        default=None,
        description=(
            "Explicit allowlist of collections to fan out across. Required when "
            "`collection` is null. Use this instead of the old implicit-all behavior."
        ),
    )
    top_k: int = Field(default=RagConfig.TOP_K, ge=1, le=20)
    # Minimum relevance score a chunk must reach to pass the retrieval filter.
    # Applied as `max(vector_score, bm25_score_normalized) >= min_score`.
    # When omitted, falls back to RagConfig.MIN_RELEVANCE_SCORE (env-configurable).
    min_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Override the retrieval relevance threshold for this query. "
            "Range 0.0–1.0. Defaults to server's MIN_RELEVANCE_SCORE (0.3)."
        ),
    )
    debug: bool = Field(
        default=False,
        description=(
            "Deprecated — retrieved_chunks / selected_chunks / selection_scores "
            "are now always returned. Kept for backward compatibility."
        ),
    )
    rerank: bool | None = Field(
        default=None,
        description=(
            "Override the server's LLM-reranker setting for this query. "
            "null = use the server default (admin config llm_selector_enabled)."
        ),
    )

    @model_validator(mode="after")
    def _collection_xor_allowlist(self) -> "QueryRequest":
        if self.collection is not None and self.search_collections is not None:
            raise ValueError(
                "Pass either `collection` (single) or `search_collections` (multi), not both."
            )
        if self.collection is None and (
            self.search_collections is None or len(self.search_collections) == 0
        ):
            raise ValueError(
                "A collection scope is required: set `collection` for a single "
                "collection, or `search_collections` to an explicit list of names. "
                "The old `collection: null` fan-out-to-all behavior has been removed "
                "to prevent cross-collection data leakage."
            )
        return self


class QueryAccepted(BaseModel):
    query_id: int
    status: str = "pending"
    message: str = "Query accepted. Poll GET /rag/query/{query_id} for results."


class QueryResponse(BaseModel):
    answer: str
    # Fix 3 — `collection` kept for backward compat (single-collection mode only).
    # For multi-collection responses use `collections` (the list of collections
    # that actually contributed chunks). The old literal string "__all__" is gone.
    collection: str | None = None
    collections: list[str] | None = Field(
        default=None,
        description="Collections that actually contributed to the answer.",
    )
    # Fix 2 — always populated. Each chunk dict now includes its source collection.
    retrieved_chunks: list[dict] | None = None
    selected_chunks: list[dict] | None = None
    # `{index, score}` per chunk from the LLM reranker (0-10). Indices refer to
    # `retrieved_chunks` (minus any chunks dropped before reranking).
    # Empty when reranking was skipped. Each selected chunk's metadata also
    # carries its `rerank_score`.
    selection_scores: list[dict] | None = None
    # True when no reranker call was made (reranker off, or <= 1 chunk).
    skipped_selection: bool | None = None
    # Set when the reranker call failed and retrieval order was kept.
    rerank_fallback_reason: str | None = None
    # Fix 4 — machine-readable refusal classifier. `null` on successful answers.
    refusal_reason: RefusalReason | None = None


class QueryStatusResponse(BaseModel):
    query_id: int
    status: str                     # pending | processing | completed | failed
    success: bool | None
    # Optional so a consumer that scrubs request text in place can still serve
    # the row.
    question: str | None = None
    collection: str | None
    top_k: int
    debug: bool
    result: QueryResponse | None
    error_message: str | None
    duration_ms: int | None
    created_at: datetime
    completed_at: datetime | None


# ── Ingest ────────────────────────────────────────────────────────────────────

class IngestTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=_MAX_INGEST_TEXT_CHARS)
    collection: str = RagConfig.DEFAULT_COLLECTION
    # `rag_documents.source_file` is varchar(500) — an unbounded value would
    # reach the database and surface as a 500 (`StringDataRightTruncation`)
    # rather than a 422. Bounded just under the
    # column so the schema rejects it at the boundary, which is where every other
    # input limit lives.
    source: str = Field(default="text_input", max_length=480)
    metadata: dict = {}


# ── Match (multi-query weighted retrieval over regular documents) ────────────

class MatchQuery(BaseModel):
    text: str = Field(min_length=1, max_length=_MAX_QUERY_CHARS)
    weight: float = Field(default=1.0, ge=0.0)
    # `name` is a cosmetic label used only for the per-query score breakdown
    # in the response. Server-side, queries are addressed by their index. If
    # omitted, the response uses synthesized labels (`q1`, `q2`, …).
    name: str | None = Field(default=None, max_length=64)


class MatchRequest(BaseModel):
    collection: str | None = Field(
        default=None,
        description="Single collection to match against. Mutually exclusive with search_collections.",
    )
    search_collections: list[str] | None = Field(
        default=None,
        description="Explicit allowlist of collections to fan out across.",
    )
    queries: list[MatchQuery] = Field(min_length=1, max_length=8)
    filters: dict[str, Any] | None = Field(
        default=None,
        description="Optional metadata filter applied at the Qdrant search level.",
    )
    top_k: int = Field(default=10, ge=1, le=100)
    score_normalization: Literal["minmax", "rank_rrf"] = "rank_rrf"

    @model_validator(mode="after")
    def _collection_xor_allowlist(self) -> "MatchRequest":
        if self.collection is not None and self.search_collections is not None:
            raise ValueError(
                "Pass either `collection` (single) or `search_collections` (multi), not both."
            )
        if self.collection is None and (
            self.search_collections is None or len(self.search_collections) == 0
        ):
            raise ValueError(
                "A collection scope is required: set `collection` or `search_collections`."
            )
        # Require at least one query with a positive weight, otherwise the
        # whole blend collapses to zero.
        if not any(q.weight > 0 for q in self.queries):
            raise ValueError("At least one query must have weight > 0.")
        names = [q.name for q in self.queries if q.name is not None]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate query names are not allowed.")
        for key in (self.filters or {}):
            if not _METADATA_FILTER_KEY.fullmatch(str(key)):
                raise ValueError(
                    f"Invalid metadata filter key {key!r}. "
                    "Keys must match ^[A-Za-z0-9_.-]{{1,128}}$."
                )
        return self


class QueryScore(BaseModel):
    raw: float                  # raw aggregated chunk score for this query
    normalized: float           # after score_normalization across the candidate set
    weight: float
    contribution: float         # normalized * weight


class MatchResultItem(BaseModel):
    document_id: UUID
    collection: str
    source: str | None = None
    metadata: dict[str, Any] = {}
    final_score: float
    matched_chunks: int = Field(
        default=0,
        description=(
            "Total number of positively-scored chunks retrieved for this document "
            "across all queries. Note: only the top-3 chunk scores per query "
            "contribute to the final score; this count reflects all retrieved "
            "chunks and indicates how thoroughly the document appears in results."
        ),
    )
    query_scores: dict[str, QueryScore]


class MatchResponse(BaseModel):
    results: list[MatchResultItem]
