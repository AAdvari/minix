# LCEL RAG chain with hybrid retrieval, LLM reranking, citations, and confidence scoring.
from langchain_litellm import ChatLiteLLM
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnableLambda, RunnableParallel, RunnablePassthrough
from langchain_core.documents import Document

from minix.core.modules.rag.hybrid_retriever import HybridRetriever
from minix.core.modules.rag.llm_factory import make_chat_llm
from minix.core.modules.rag.config import RagConfig
from minix.core.modules.rag.prompts import (
    RAG_PROMPT, _FENCE, _IDENTITY_KEYS, neutralise_fence,
)
from minix.core.modules.rag.retrieval.llm_reranker import RerankResult, rerank as _llm_rerank


def _make_llm() -> ChatLiteLLM:
    # F-3: construction moved to llm_factory so the timeout and token ceiling
    # cannot be applied here and silently missed in groundedness.py, which used
    # to duplicate this function to avoid a circular import.
    return make_chat_llm()


def _rerank_or_truncate(question: str, docs: list[Document],
                        rerank: bool | None = None) -> RerankResult:
    """The one post-retrieval step every query path shares.

    `rerank=None` follows the server setting (LLM_SELECTOR_ENABLED); a bool is a
    per-request override. Either way at most SELECTOR_FALLBACK_TOP_N chunks go
    on to the answer prompt. Every answer path calls this one step, so the
    setting applies uniformly.
    """
    enabled = RagConfig.LLM_SELECTOR_ENABLED if rerank is None else rerank
    keep_n = RagConfig.SELECTOR_FALLBACK_TOP_N
    if not enabled:
        return RerankResult(docs=list(docs[:keep_n]), skipped=True)
    return _llm_rerank(
        question, docs, keep_n=keep_n, min_score=RagConfig.RERANKER_MIN_SCORE,
    )


# `_IDENTITY_KEYS` (chunk-header metadata fields) and `neutralise_fence` live in
# prompts.py — the reranker needs both — and are re-exported here for existing
# importers.


def _format_docs(docs: list[Document]) -> str:
    parts = []
    for i, doc in enumerate(docs, 1):
        m = doc.metadata
        # Neutralise the attacker-controlled *inputs* before assembly, not the
        # finished header — the header deliberately contains the sentinel, so
        # neutralising it afterwards would strip the very marker being added.
        identity_parts = [
            f"{k.replace('_', ' ').title()}: {neutralise_fence(str(m[k]))}"
            for k in _IDENTITY_KEYS if m.get(k)
        ]
        source = neutralise_fence(str(m.get("source", "unknown")))
        heading = neutralise_fence(str(m.get("parent_heading", "") or ""))
        section = neutralise_fence(str(m.get("section_type", "") or ""))
        # The chunk marker carries the sentinel so a document cannot forge a
        # chunk boundary or a source attribution. The bare `[{i}] source: ...`
        # it replaces was trivially reproducible in document text.
        header = f"[[{_FENCE} CHUNK {i}]] source: {source}"
        if identity_parts:
            header += "  |  " + "  |  ".join(identity_parts)
        if heading:
            header += f"  |  section: {heading}"
        if section and section != "paragraph":
            header += f"  |  type: {section}"
        parts.append(f"{header}\n{neutralise_fence(doc.page_content)}")
    # Separator also carries the sentinel — the previous "\n\n---\n\n" was a
    # markdown rule any document could contain.
    return f"\n\n[[{_FENCE} BOUNDARY]]\n\n".join(parts)


def build_rag_chain(retriever: HybridRetriever) -> Runnable:
    llm = _make_llm()

    def _retrieve_select_format(question: str) -> str:
        docs = retriever.invoke(question)
        return _format_docs(_rerank_or_truncate(question, docs).docs)

    chain: Runnable = (
        RunnableParallel({
            "context": RunnableLambda(_retrieve_select_format),
            "question": RunnablePassthrough(),
        })
        | RAG_PROMPT
        | llm
        | StrOutputParser()
    )
    return chain


def query_with_debug(
    question: str,
    retriever: HybridRetriever,
    *,
    rerank: bool | None = None,
) -> dict:
    llm = _make_llm()
    all_docs: list[Document] = retriever.invoke(question)

    # Short-circuit when the relevance filter wiped everything: don't burn an
    # LLM call. Return a canonical refusal so the downstream classifier can
    # tag it `out_of_corpus`.
    if not all_docs:
        return {
            "answer": "I don't have enough information to answer that.",
            "retrieved_chunks": [],
            "selected_chunks": [],
            "selection_scores": [],
            "skipped_selection": True,
            "retrieval_mode": "hybrid",
        }

    reranked = _rerank_or_truncate(question, all_docs, rerank)
    selected_docs = reranked.docs

    context = _format_docs(selected_docs)
    answer = (RAG_PROMPT | llm | StrOutputParser()).invoke({
        "context": context,
        "question": question,
    })

    def _doc_to_dict(doc: Document) -> dict:
        return {"content": doc.page_content, "metadata": doc.metadata}

    return {
        "answer": answer,
        "retrieved_chunks": [_doc_to_dict(d) for d in all_docs],
        "selected_chunks": [_doc_to_dict(d) for d in selected_docs],
        "selection_scores": reranked.scores,
        "skipped_selection": reranked.skipped,
        "rerank_fallback_reason": reranked.fallback_reason,
        "retrieval_mode": "hybrid",
    }


def query_with_debug_multi(
    question: str,
    retrievers: dict[str, HybridRetriever],
    top_k: int = RagConfig.TOP_K,
    *,
    rerank: bool | None = None,
) -> dict:
    if not retrievers:
        return {
            "answer": "No collections found. Please ingest some documents first.",
            "retrieved_chunks": [],
            "selected_chunks": [],
            "selection_scores": [],
            "skipped_selection": True,
            "retrieval_mode": "hybrid",
            "collections_queried": [],
        }

    llm = _make_llm()

    per_collection: dict[str, list[Document]] = {}
    for col, retriever in retrievers.items():
        try:
            docs = retriever.invoke(question)
        except Exception:
            docs = []
        for d in docs:
            d.metadata["_collection"] = col
        per_collection[col] = docs

    # Short-circuit: every retriever came back empty (e.g. threshold filtered
    # everything out across all collections).
    if not any(per_collection.values()):
        return {
            "answer": "I don't have enough information to answer that.",
            "retrieved_chunks": [],
            "selected_chunks": [],
            "selection_scores": [],
            "skipped_selection": True,
            "retrieval_mode": "hybrid",
            "collections_queried": list(retrievers.keys()),
        }

    max_pool = top_k * 4
    all_docs: list[Document] = []
    iters = [iter(v) for v in per_collection.values() if v]
    while len(all_docs) < max_pool and iters:
        exhausted = []
        for it in iters:
            try:
                all_docs.append(next(it))
                if len(all_docs) >= max_pool:
                    break
            except StopIteration:
                exhausted.append(it)
        for ex in exhausted:
            iters.remove(ex)

    reranked = _rerank_or_truncate(question, all_docs, rerank)
    selected_docs = reranked.docs

    context = _format_docs(selected_docs)
    answer = (RAG_PROMPT | llm | StrOutputParser()).invoke({
        "context": context,
        "question": question,
    })

    def _doc_to_dict(doc: Document) -> dict:
        return {"content": doc.page_content, "metadata": doc.metadata}

    return {
        "answer": answer,
        "retrieved_chunks": [_doc_to_dict(d) for d in all_docs],
        "selected_chunks": [_doc_to_dict(d) for d in selected_docs],
        "selection_scores": reranked.scores,
        "skipped_selection": reranked.skipped,
        "rerank_fallback_reason": reranked.fallback_reason,
        "retrieval_mode": "hybrid",
        "collections_queried": list(retrievers.keys()),
    }
