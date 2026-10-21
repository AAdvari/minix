"""Multi-query weighted document blender.

Runs N hybrid-retrieval queries against the standard chunked corpus, aggregates
chunk-level scores to document level (sum of the top-N chunk scores per doc),
normalizes per query, and blends with per-query weights into a final ranking.

This is the engine behind `POST /rag/match`. It assumes nothing about the
ingest path — works on any documents indexed via the regular pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

# Sum of the best N chunk scores per document, per query. Caps the "evidence
# bonus" that very long documents get from having many tangentially-relevant
# chunks while still rewarding docs that match on multiple chunks.
CHUNK_AGGREGATION_TOP_N = 3

# Reciprocal-rank-fusion constant (paper default).
RRF_K = 60


@dataclass
class QueryScoreData:
    raw: float
    normalized: float
    weight: float
    contribution: float


@dataclass
class BlendedHit:
    document_id: str
    collection: str
    source: str | None
    metadata: dict[str, Any]
    final_score: float
    matched_chunks: int
    query_scores: dict[str, QueryScoreData] = field(default_factory=dict)


def _aggregate_chunks_to_docs(
    chunks: list[Any],
) -> tuple[dict[str, float], dict[str, int], dict[str, str], dict[str, dict[str, Any]]]:
    """Group chunks by document_id and return:
        per_doc_score: doc_id → sum of top-N chunk relevance scores
        per_doc_chunk_count: doc_id → distinct chunks that contributed
        doc_collection: doc_id → collection_name (first-seen)
        doc_metadata: doc_id → metadata dict (first-seen)
    """
    scores_by_doc: dict[str, list[float]] = {}
    collection_by_doc: dict[str, str] = {}
    metadata_by_doc: dict[str, dict[str, Any]] = {}
    for ch in chunks:
        meta = dict(ch.metadata or {})
        doc_id = meta.get("document_id")
        if not doc_id:
            continue
        doc_id = str(doc_id)
        score = float(meta.get("relevance_score") or 0.0)
        if score <= 0.0:
            continue
        scores_by_doc.setdefault(doc_id, []).append(score)
        collection_by_doc.setdefault(doc_id, str(meta.get("collection_name") or ""))
        if doc_id not in metadata_by_doc:
            metadata_by_doc[doc_id] = meta

    per_doc_score: dict[str, float] = {}
    per_doc_chunk_count: dict[str, int] = {}
    for doc_id, scores in scores_by_doc.items():
        top = sorted(scores, reverse=True)[:CHUNK_AGGREGATION_TOP_N]
        per_doc_score[doc_id] = sum(top)
        per_doc_chunk_count[doc_id] = len(scores)
    return per_doc_score, per_doc_chunk_count, collection_by_doc, metadata_by_doc


def _normalize(
    scores_by_doc: dict[str, float],
    method: Literal["minmax", "rank_rrf"],
) -> dict[str, float]:
    if not scores_by_doc:
        return {}
    if method == "minmax":
        values = list(scores_by_doc.values())
        lo, hi = min(values), max(values)
        if hi - lo < 1e-12:
            return {d: 1.0 for d in scores_by_doc}
        return {d: (s - lo) / (hi - lo) for d, s in scores_by_doc.items()}
    # rank_rrf
    ranked = sorted(scores_by_doc.items(), key=lambda kv: kv[1], reverse=True)
    return {doc_id: 1.0 / (RRF_K + rank) for rank, (doc_id, _) in enumerate(ranked, start=1)}


class MultiQueryBlender:
    """Pure orchestrator. The per-query retrieval function is injected so the
    blending math can be unit-tested in isolation.

    `retrieve_fn(query_text, collection) -> list[Document]`: one call per
    (query, collection) pair. Returned chunks must carry `document_id` and
    `relevance_score` in their `.metadata`.
    """

    def __init__(self, retrieve_fn: Callable[[str, str], list[Any]]):
        self._retrieve_fn = retrieve_fn

    def blend(
        self,
        queries: Iterable[Any],
        collections: list[str],
        top_k: int,
        score_normalization: Literal["minmax", "rank_rrf"] = "rank_rrf",
    ) -> list[BlendedHit]:
        queries_list = list(queries)

        # Per-query: aggregate chunks → docs, then per-query normalization.
        raw_by_query: dict[str, dict[str, float]] = {}
        normalized_by_query: dict[str, dict[str, float]] = {}
        chunks_by_doc: dict[str, int] = {}
        collection_by_doc: dict[str, str] = {}
        metadata_by_doc: dict[str, dict[str, Any]] = {}
        query_labels: list[str] = []

        for idx, q in enumerate(queries_list):
            label = self._label_for(q, idx)
            query_labels.append(label)
            all_chunks: list[Any] = []
            for col in collections:
                all_chunks.extend(self._retrieve_fn(q.text, col))
            per_doc_score, per_doc_count, col_by_doc, meta_by_doc = _aggregate_chunks_to_docs(all_chunks)
            raw_by_query[label] = per_doc_score
            normalized_by_query[label] = _normalize(per_doc_score, score_normalization)
            for doc_id, cnt in per_doc_count.items():
                # Track max chunk hit count across queries.
                chunks_by_doc[doc_id] = max(chunks_by_doc.get(doc_id, 0), cnt)
            for doc_id, col in col_by_doc.items():
                collection_by_doc.setdefault(doc_id, col)
            for doc_id, meta in meta_by_doc.items():
                metadata_by_doc.setdefault(doc_id, meta)

        candidate_doc_ids: set[str] = set()
        for per_doc in raw_by_query.values():
            candidate_doc_ids.update(per_doc)

        weights: list[float] = [float(q.weight) for q in queries_list]

        results: list[BlendedHit] = []
        for doc_id in candidate_doc_ids:
            per_query: dict[str, QueryScoreData] = {}
            final = 0.0
            for label, q, weight in zip(query_labels, queries_list, weights):
                raw = raw_by_query[label].get(doc_id, 0.0)
                normalized = normalized_by_query[label].get(doc_id, 0.0)
                contribution = normalized * weight
                final += contribution
                per_query[label] = QueryScoreData(
                    raw=raw,
                    normalized=normalized,
                    weight=weight,
                    contribution=contribution,
                )
            results.append(BlendedHit(
                document_id=doc_id,
                collection=collection_by_doc.get(doc_id, collections[0] if collections else ""),
                source=metadata_by_doc.get(doc_id, {}).get("source"),
                metadata=metadata_by_doc.get(doc_id, {}),
                final_score=final,
                matched_chunks=chunks_by_doc.get(doc_id, 0),
                query_scores=per_query,
            ))

        results.sort(key=lambda r: r.final_score, reverse=True)
        return results[:top_k]

    @staticmethod
    def _label_for(query: Any, idx: int) -> str:
        name = getattr(query, "name", None)
        return name if name else f"q{idx + 1}"
