"""LLM reranker: re-orders retrieved chunks by LLM-judged relevance.

Runs on the retriever's *final* output (the chunks that would otherwise go to
the answer prompt, or be returned by /search), not on the wider fusion pool.
One LLM call scores every chunk 0-10 pointwise; chunks are then sorted by that
score, with the retrieval `fusion_score` breaking ties.

Replaces the older "selector", which scored chunks the same way but only
*dropped* the low scorers and kept the survivors in retrieval order — so the
chunk numbered [1] in the answer context was not the best one. It also parsed
the reply with a bare `json.loads` (a ```json fence silently disabled it) and
put chunk text into the prompt unfenced.

The reranker never fails a request: any LLM or parse failure returns the input
order, truncated, with `fallback_reason` set.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import unquote

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from pydantic import BaseModel, Field

from minix.core.modules.rag.config import RagConfig
from minix.core.modules.rag.llm_factory import make_chat_llm
from minix.core.modules.rag.prompts import (
    FENCE_BEGIN, FENCE_END, RERANK_PROMPT, _FENCE, _IDENTITY_KEYS, neutralise_fence,
)

logger = logging.getLogger(__name__)

HEADING_MAX_CHARS = 150

# When the min-score cutoff would drop every chunk, keep this many of the best
# instead — the old selector's behaviour, so a harsh judge doesn't turn every
# borderline question into an empty context.
CUTOFF_FALLBACK_KEEP = 3


class ChunkScore(BaseModel):
    index: int
    score: float = Field(ge=0, le=10)


class RerankScores(BaseModel):
    scores: list[ChunkScore]


@dataclass
class RerankResult:
    docs: list[Document]
    # `{index, score}` per scored chunk, indices into the *input* list — the
    # same shape the selector returned as `selection_scores`.
    scores: list[dict] = field(default_factory=list)
    # True when no LLM call was made (nothing to re-order).
    skipped: bool = False
    # Set when the LLM call or its parsing failed and the input order was kept.
    fallback_reason: str | None = None


def make_reranker_llm():
    return make_chat_llm(model=RagConfig.RERANKER_MODEL or RagConfig.LLM_MODEL)


def _document_name(m: dict) -> str:
    # URL-decoded so "Model%20NDA%20(recommended%20by%20SWA).txt" reads as the
    # name it is — the encoded form hid the party the question named.
    raw = str(m.get("source") or m.get("source_file") or m.get("filename") or "unknown")
    return unquote(raw)


def _format_chunks(docs: list[Document], max_chars: int) -> str:
    """Each chunk gets a header naming its document (plus the same identity
    fields the answer prompt shows), because the prompt's document-scope rule
    needs it: without it the judge scored text only, and on a corpus of
    near-identical documents promoted matching passages from the wrong one."""
    parts = []
    for i, doc in enumerate(docs):
        m = doc.metadata or {}
        header = f"[[{_FENCE} CHUNK {i}]] document: {neutralise_fence(_document_name(m))}"
        for k in _IDENTITY_KEYS:
            if m.get(k):
                header += f"  |  {k.replace('_', ' ').title()}: {neutralise_fence(str(m[k]))}"
        # Some chunkers store a whole clause as the heading; cap it so the
        # header stays a label rather than a second copy of the chunk.
        heading = neutralise_fence(str(m.get("parent_heading") or "")[:HEADING_MAX_CHARS])
        if heading:
            header += f"  |  section: {heading}"
        parts.append(f"{header}\n{neutralise_fence(doc.page_content[:max_chars])}")
    return f"{FENCE_BEGIN}\n" + "\n\n".join(parts) + f"\n{FENCE_END}"


_CODE_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def _parse_scores(raw: str) -> list[ChunkScore]:
    """Parse a plain-text reply: a JSON object `{"scores": [...]}` or a bare
    array, optionally wrapped in a markdown code fence. Invalid entries are
    skipped rather than failing the whole reply."""
    text = _CODE_FENCE.sub("", raw.strip())
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("scores")
    if not isinstance(data, list):
        raise ValueError("reranker reply is not a list of scores")
    parsed = []
    for item in data:
        try:
            parsed.append(ChunkScore(**item))
        except (TypeError, ValueError):
            continue
    return parsed


def _score(llm, question: str, chunks_text: str) -> list[ChunkScore]:
    inputs = {"question": question, "chunks_text": chunks_text}
    try:
        result = (RERANK_PROMPT | llm.with_structured_output(RerankScores)).invoke(inputs)
        if isinstance(result, RerankScores):
            return result.scores
        if isinstance(result, dict):
            return RerankScores(**result).scores
    except Exception:
        pass
    # Fallback for providers without json_schema support, as in
    # rag_chain._structured_llm_invoke.
    return _parse_scores((RERANK_PROMPT | llm | StrOutputParser()).invoke(inputs))


def rerank(
    question: str,
    docs: list[Document],
    *,
    keep_n: int,
    min_score: float = 0.0,
    llm=None,
    max_chars: int | None = None,
) -> RerankResult:
    """Re-order `docs` by LLM relevance and keep the best `keep_n`.

    `min_score` > 0 also drops chunks scored below it (falling back to the best
    CUTOFF_FALLBACK_KEEP if that drops everything). Each returned Document is a
    copy carrying `rerank_score` in its metadata.
    """
    if len(docs) <= 1:
        return RerankResult(docs=list(docs[:keep_n]), skipped=True)

    max_chars = max_chars or RagConfig.RERANKER_MAX_CHARS
    try:
        llm = llm or make_reranker_llm()
        raw_scores = _score(llm, question, _format_chunks(docs, max_chars))
    except Exception as e:
        logger.warning("reranker failed, keeping retrieval order: %s", type(e).__name__)
        return RerankResult(docs=list(docs[:keep_n]), fallback_reason=f"llm_error:{type(e).__name__}")

    # First score per in-range index wins; the model occasionally repeats or
    # invents indices.
    by_index: dict[int, float] = {}
    for s in raw_scores:
        if 0 <= s.index < len(docs) and s.index not in by_index:
            by_index[s.index] = float(s.score)
    if not by_index:
        logger.warning("reranker returned no usable scores, keeping retrieval order")
        return RerankResult(docs=list(docs[:keep_n]), fallback_reason="no_valid_scores")

    # Chunks the model skipped rank as 0. `sorted` is stable, so equal
    # (score, fusion) pairs keep their retrieval order.
    order = sorted(
        range(len(docs)),
        key=lambda i: (
            by_index.get(i, 0.0),
            float((docs[i].metadata or {}).get("fusion_score") or 0.0),
        ),
        reverse=True,
    )
    ranked = [
        Document(
            page_content=docs[i].page_content,
            metadata={**(docs[i].metadata or {}), "rerank_score": by_index.get(i, 0.0)},
        )
        for i in order
    ]
    if min_score > 0:
        kept = [d for d in ranked if d.metadata["rerank_score"] >= min_score]
        ranked = kept or ranked[:CUTOFF_FALLBACK_KEEP]

    return RerankResult(
        docs=ranked[:keep_n],
        scores=[{"index": i, "score": by_index[i]} for i in sorted(by_index)],
    )
