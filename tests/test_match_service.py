"""MatchService + MultiQueryBlender tests.

These exercise the new multi-query weighted retrieval over regular documents.
No DB or Qdrant — both retrieval and blending math are injected.
"""
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from minix.core.modules.rag.controllers.schemas import MatchRequest, MatchQuery
from minix.core.modules.rag.services.match_service import MatchService
from minix.core.modules.rag.retrieval.multi_query_blender import (
    MultiQueryBlender, _aggregate_chunks_to_docs, _normalize,
)


# Stable UUIDs for repeatable assertions. The label suffix is what we read in
# assertions; the UUID body is just a valid v4 prefix.
DOC_A = "11111111-1111-4111-8111-111111111111"
DOC_B = "22222222-2222-4222-8222-222222222222"
DOC_C = "33333333-3333-4333-8333-333333333333"
DOC_X = "44444444-4444-4444-8444-444444444444"
DOC_Y = "55555555-5555-4555-8555-555555555555"


def _chunk(doc_id: str, score: float, collection: str = "c", source: str = "doc.pdf") -> Document:
    return Document(
        page_content="ignored",
        metadata={
            "document_id": doc_id,
            "collection_name": collection,
            "source": source,
            "relevance_score": score,
        },
    )


# ── MatchService ──────────────────────────────────────────────────────────────

def _service(known_for_collection: dict, blender_hits=None, doc_metadata=None):
    col_svc = MagicMock()
    col_svc.get_by_name = lambda name: object() if name in known_for_collection else None

    doc_svc = MagicMock()
    doc_svc.get_metadata_bulk = lambda ids: doc_metadata or {}

    # Inject a retrieve_fn factory that the service will pass into the blender.
    # We bypass real hybrid retrieval by handing the blender a function whose
    # output we control end-to-end.
    chunks_by_query: dict[str, list[Document]] = blender_hits or {}

    def factory(_allowed):
        def retrieve(query_text: str, collection: str):
            return chunks_by_query.get(query_text, [])
        return retrieve

    return MatchService(
        retrieve_fn_factory=factory,
        collection_service=col_svc,
        document_service=doc_svc,
    )


def test_unknown_collection_raises_lookup_error():
    svc = _service(known_for_collection={})
    req = MatchRequest(
        collection="missing",
        queries=[MatchQuery(text="q", weight=1.0)],
    )
    with pytest.raises(LookupError):
        svc.match(req)


def test_happy_path_empty_response():
    svc = _service(known_for_collection={"c": []}, blender_hits={})
    req = MatchRequest(
        collection="c",
        queries=[MatchQuery(text="q", weight=1.0)],
    )
    res = svc.match(req)
    assert res.results == []


def test_single_query_orders_by_chunk_score():
    svc = _service(
        known_for_collection={"c": []},
        blender_hits={
            "skills": [
                _chunk(DOC_A, 0.9),
                _chunk(DOC_B, 0.4),
                _chunk(DOC_C, 0.1),
            ],
        },
    )
    req = MatchRequest(
        collection="c",
        queries=[MatchQuery(text="skills", weight=1.0, name="skills")],
        score_normalization="rank_rrf",
    )
    res = svc.match(req)
    assert [str(r.document_id) for r in res.results[:3]] == [DOC_A, DOC_B, DOC_C]


def test_two_queries_weight_zero_suppresses_second():
    svc = _service(
        known_for_collection={"c": []},
        blender_hits={
            "alpha": [_chunk(DOC_A, 0.9)],
            # beta would rank doc_B first if it had weight, but weight=0 zeroes it.
            "beta":  [_chunk(DOC_B, 0.99)],
        },
    )
    req = MatchRequest(
        collection="c",
        queries=[
            MatchQuery(text="alpha", weight=1.0, name="alpha"),
            MatchQuery(text="beta",  weight=0.0, name="beta"),
        ],
    )
    res = svc.match(req)
    # doc_A wins because beta contributes 0.
    assert str(res.results[0].document_id) == DOC_A
    # doc_B still appears (it's a candidate) but with zero contribution from beta.
    by_id = {str(r.document_id): r for r in res.results}
    assert by_id[DOC_B].query_scores["beta"].contribution == 0.0


def test_anonymous_queries_get_synthesized_labels():
    svc = _service(
        known_for_collection={"c": []},
        blender_hits={
            "first":  [_chunk(DOC_A, 0.9)],
            "second": [_chunk(DOC_A, 0.5)],
        },
    )
    req = MatchRequest(
        collection="c",
        queries=[
            MatchQuery(text="first", weight=1.0),
            MatchQuery(text="second", weight=1.0),
        ],
    )
    res = svc.match(req)
    assert set(res.results[0].query_scores.keys()) == {"q1", "q2"}


def test_matched_chunks_counts_distinct_contributions():
    svc = _service(
        known_for_collection={"c": []},
        blender_hits={
            "alpha": [
                _chunk(DOC_A, 0.8),
                _chunk(DOC_A, 0.5),
                _chunk(DOC_A, 0.3),
            ],
        },
    )
    req = MatchRequest(
        collection="c",
        queries=[MatchQuery(text="alpha", weight=1.0)],
    )
    res = svc.match(req)
    assert res.results[0].matched_chunks == 3


# ── Aggregation / normalization unit tests ───────────────────────────────────

def test_aggregate_takes_top_3_chunks_per_doc():
    chunks = [
        _chunk(DOC_X, 0.9),
        _chunk(DOC_X, 0.8),
        _chunk(DOC_X, 0.7),
        _chunk(DOC_X, 0.1),  # outside top-3, should be excluded
        _chunk(DOC_Y, 0.5),
    ]
    scores, counts, _, _ = _aggregate_chunks_to_docs(chunks)
    assert scores[DOC_X] == pytest.approx(0.9 + 0.8 + 0.7)
    assert scores[DOC_Y] == pytest.approx(0.5)
    assert counts[DOC_X] == 4  # all four chunks counted as "matched"
    assert counts[DOC_Y] == 1


def test_aggregate_drops_zero_or_negative_chunks():
    chunks = [_chunk(DOC_X, 0.0), _chunk(DOC_X, -0.1), _chunk(DOC_Y, 0.5)]
    scores, _, _, _ = _aggregate_chunks_to_docs(chunks)
    assert DOC_X not in scores
    assert scores[DOC_Y] == 0.5


def test_normalize_minmax_collapses_to_zero_one():
    out = _normalize({"a": 0.2, "b": 1.0, "c": 0.6}, "minmax")
    assert out["a"] == pytest.approx(0.0)
    assert out["b"] == pytest.approx(1.0)
    assert out["c"] == pytest.approx(0.5)


def test_normalize_minmax_handles_all_equal():
    out = _normalize({"a": 0.4, "b": 0.4}, "minmax")
    assert out == {"a": 1.0, "b": 1.0}


def test_normalize_rrf_uses_rank_not_magnitude():
    # Even though c has a much larger score, RRF only cares about rank.
    out = _normalize({"a": 0.99, "b": 0.98, "c": 100.0}, "rank_rrf")
    # c ranks 1, then a, then b → c > a > b.
    assert out["c"] > out["a"] > out["b"]


# ── MultiQueryBlender end-to-end via injected retrieve_fn ─────────────────────

def test_blender_combines_queries_with_weights():
    chunks_by_query = {
        "alpha": [_chunk(DOC_A, 0.9), _chunk(DOC_B, 0.2)],
        "beta":  [_chunk(DOC_B, 0.9), _chunk(DOC_C, 0.5)],
    }
    blender = MultiQueryBlender(
        retrieve_fn=lambda q, _col: chunks_by_query.get(q, []),
    )
    qs = [
        MatchQuery(text="alpha", weight=1.0, name="alpha"),
        MatchQuery(text="beta",  weight=1.0, name="beta"),
    ]
    hits = blender.blend(
        queries=qs, collections=["c"], top_k=10, score_normalization="rank_rrf",
    )
    by_id = {h.document_id: h for h in hits}
    # doc_B shows up in both queries; doc_A and doc_C only in one.
    assert by_id[DOC_B].final_score > by_id[DOC_A].final_score
    assert by_id[DOC_B].final_score > by_id[DOC_C].final_score
