# Hybrid retriever: Qdrant dense vector + PostgreSQL keyword (ts_rank) + RRF fusion.
#
# Hardening changes (vs. earlier version):
#   - Each candidate now carries `vector_score` (cosine sim 0-1) and / or
#     `bm25_score` (ts_rank, ~0-1) in its metadata.
#   - A `relevance_score = max(vector_score, bm25_score_norm)` is computed and
#     stamped onto every returned Document.
#   - Chunks with `relevance_score < min_score` are DROPPED before the LLM ever
#     sees them, addressing the issue where "totally different words" could
#     still pass through rank-based RRF fusion.
#   - `min_score` defaults to RagConfig.MIN_RELEVANCE_SCORE (0.3) and can be
#     overridden per-query.
#
# Naming note: the project calls the keyword side "BM25" but the SQL uses
# `ts_rank` (not Okapi BM25). Score thresholds are calibrated for that.
from __future__ import annotations

import uuid
from typing import Callable

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from minix.core.modules.rag.config import RagConfig


def _rrf(
    ranked_lists: list[list[Document]],
    weights: list[float],
    k: int = 60,
) -> list[Document]:
    """Reciprocal-Rank Fusion — rank-based; score magnitudes ignored."""
    scores: dict[str, float] = {}
    doc_map: dict[str, Document] = {}
    for ranked_list, weight in zip(ranked_lists, weights):
        for rank, doc in enumerate(ranked_list):
            key = str(hash(doc.page_content[:200]))
            doc_map[key] = doc
            scores[key] = scores.get(key, 0.0) + weight / (k + rank + 1)
    return [doc_map[k] for k in sorted(scores, key=scores.__getitem__, reverse=True)]


def _normalize_bm25(score: float | None) -> float:
    """`ts_rank` produces values that typically max out around 0.3–0.4 for
    strong matches. Scale them into an approximate 0–1 range so they can be
    compared against cosine similarity on the same threshold.

    This is a rough calibration, not a rigorous transform. Clamped to [0, 1].
    """
    if not score:
        return 0.0
    # A ts_rank of ~0.1 is a decent keyword hit; multiplying by 3 brings that
    # to ~0.3, the default MIN_RELEVANCE_SCORE threshold.
    return max(0.0, min(1.0, score * 3.0))


def fuse_and_rank(
    bm25_docs: list[Document],
    vector_docs: list[Document],
    *,
    bm25_weight: float,
    vector_weight: float,
    top_k: int,
    min_score: float,
) -> list[Document]:
    """Fuse keyword + vector candidates into one ranked, scored list.

    Dedups the two legs (via RRF as a union/dedup pass), recovers each leg's
    raw score, then **orders by a weighted blend**
    ``vector_weight*vector + bm25_weight*normalized_bm25`` so a confident vector
    hit outranks a noisy keyword-only match while dual-signal chunks rise.
    Stamps ``relevance_score = max(vector_score, normalized_bm25)`` (used only
    for the ``min_score`` gate, to preserve the answer-path refusal behavior),
    drops chunks below ``min_score``, and returns the top_k. Shared by
    HybridRetriever (the ``/query`` path) and the controller's ``_run_search``
    (the ``/search`` path) so both rank identically — previously ``/search``
    did an unranked concatenation of all keyword rows before all vector rows.

    Pass ``min_score=0.0`` for a raw-retrieval endpoint that should return
    whatever it found (just ranked), versus the configured threshold for the
    answer path where an empty result intentionally drives a refusal.
    """
    if bm25_docs and vector_docs:
        fused = _rrf([bm25_docs, vector_docs], weights=[bm25_weight, vector_weight])
    else:
        # One leg empty (e.g. keyword-only / vector-only mode, or the keyword
        # query matched nothing): rank the non-empty leg as-is.
        fused = vector_docs or bm25_docs

    vec_lookup = {
        str(hash(d.page_content[:200])): d.metadata.get("vector_score", 0.0)
        for d in vector_docs
    }
    bm25_lookup = {
        str(hash(d.page_content[:200])): d.metadata.get("bm25_score", 0.0)
        for d in bm25_docs
    }

    scored: list[Document] = []
    for doc in fused:
        key = str(hash(doc.page_content[:200]))
        v = float(vec_lookup.get(key, doc.metadata.get("vector_score") or 0.0))
        b = float(bm25_lookup.get(key, doc.metadata.get("bm25_score") or 0.0))
        b_norm = _normalize_bm25(b)
        relevance = max(v, b_norm)
        # Ordering score: a weighted blend of the two normalized signals. This
        # is what fixes "OR-keyword floods the results": a confident vector hit
        # (high v) outranks a noisy keyword-only hit (a wrong-document chunk
        # that merely shares common legal words), while a chunk carrying *both*
        # signals rises above either alone. `relevance_score` stays = max(...)
        # so the min-score gate / refusal behavior on the answer path is
        # unchanged; only the ordering uses the blend.
        fusion = vector_weight * v + bm25_weight * b_norm
        scored.append(Document(
            page_content=doc.page_content,
            metadata={
                **doc.metadata,
                "vector_score": v,
                "bm25_score": b,
                "bm25_score_normalized": b_norm,
                "relevance_score": relevance,
                "fusion_score": fusion,
            },
        ))

    scored.sort(key=lambda d: d.metadata["fusion_score"], reverse=True)
    filtered = [d for d in scored if d.metadata["relevance_score"] >= min_score]
    return filtered[:top_k]


class HybridRetriever(BaseRetriever):
    collection_name: str
    bm25_weight: float = RagConfig.BM25_WEIGHT
    vector_weight: float = RagConfig.VECTOR_WEIGHT
    top_k: int = RagConfig.TOP_K
    min_score: float = RagConfig.MIN_RELEVANCE_SCORE
    vector_search_fn: Callable | None = None
    bm25_search_fn: Callable | None = None
    metadata_bulk_fn: Callable | None = None

    class Config:
        arbitrary_types_allowed = True

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        fetch_k = max(
            self.top_k * RagConfig.RETRIEVAL_FETCH_MULTIPLIER,
            RagConfig.RETRIEVAL_CANDIDATE_FLOOR,
        )

        # ── 1. Dense vector search ──────────────────────────────────────────
        # vector_search stamps `vector_score` (cosine sim 0-1) into each doc's
        # metadata.
        vector_docs: list[Document] = []
        if self.vector_search_fn:
            vector_docs = self.vector_search_fn(query, self.collection_name, k=fetch_k)

        # ── 2. Keyword search (ts_rank, named "bm25" for legacy reasons) ────
        bm25_rows: list[dict] = []
        if self.bm25_search_fn:
            bm25_rows = self.bm25_search_fn(query, self.collection_name, k=fetch_k)

        bm25_docs = [
            Document(
                page_content=row["content"],
                metadata={
                    "document_id": row["document_id"],
                    "chunk_index": row["chunk_index"],
                    "section_type": row["section_type"],
                    "parent_heading": row["parent_heading"],
                    "collection_name": self.collection_name,
                    "bm25_score": float(row.get("score") or 0.0),
                },
            )
            for row in bm25_rows
        ]

        # ── 3. Fuse + recover scores + threshold ───────────────────────────
        # Delegated to the shared helper so the /search path ranks identically.
        # An empty result here still yields an empty `selected_chunks`
        # downstream, which drives the refusal classifier to `out_of_corpus`.
        candidates = fuse_and_rank(
            bm25_docs,
            vector_docs,
            bm25_weight=self.bm25_weight,
            vector_weight=self.vector_weight,
            top_k=self.top_k,
            min_score=self.min_score,
        )

        # ── 6. Enrich with per-document metadata ───────────────────────────
        doc_ids: list[uuid.UUID] = []
        for doc in candidates:
            raw = doc.metadata.get("document_id") or doc.metadata.get("source")
            try:
                doc_ids.append(uuid.UUID(str(raw)))
            except (ValueError, AttributeError):
                pass

        meta_by_id = {}
        if self.metadata_bulk_fn and doc_ids:
            meta_by_id = self.metadata_bulk_fn(doc_ids)

        enriched: list[Document] = []
        for doc in candidates:
            raw = doc.metadata.get("document_id") or doc.metadata.get("source")
            doc_meta = meta_by_id.get(str(raw), {})
            # Note: doc.metadata goes LAST so our scores (added above) are
            # not overwritten by whatever the bulk-metadata fetcher returns.
            merged_meta = {**doc_meta, **doc.metadata}
            enriched.append(Document(page_content=doc.page_content, metadata=merged_meta))

        return enriched
