"""Service-layer entry for POST /rag/match.

Runs multi-query weighted retrieval over regular ingested documents — no
named-representation ingest required. Per-query hybrid retrieval results are
aggregated chunk → document and blended by weight.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from langchain_core.documents import Document

from minix.core.registry import Registry
from minix.core.modules.rag.controllers.schemas import (
    MatchRequest, MatchResponse, MatchResultItem, QueryScore,
)
from minix.core.modules.rag.retrieval.multi_query_blender import MultiQueryBlender

if TYPE_CHECKING:
    from minix.core.modules.rag.services.collection_service import RagCollectionService
    from minix.core.modules.rag.services.document_service import RagDocumentService


class MatchService:
    def __init__(
        self,
        retrieve_fn_factory: Callable[[dict[str, set[str] | None] | None], Callable[[str, str], list[Document]]] | None = None,
        collection_service: "RagCollectionService | None" = None,
        document_service: "RagDocumentService | None" = None,
    ):
        # `retrieve_fn_factory(allowed_by_collection) -> retrieve_fn`
        # where `retrieve_fn(query_text, collection) -> list[Document]`.
        # When None, defaults to the project's HybridRetriever.
        self._retrieve_fn_factory = retrieve_fn_factory
        self._collection_service = collection_service
        self._document_service = document_service

    def _svc_collection(self) -> "RagCollectionService":
        if self._collection_service is not None:
            return self._collection_service
        from minix.core.modules.rag.services.collection_service import RagCollectionService
        return Registry().get(RagCollectionService)

    def _svc_document(self) -> "RagDocumentService":
        if self._document_service is not None:
            return self._document_service
        from minix.core.modules.rag.services.document_service import RagDocumentService
        return Registry().get(RagDocumentService)

    def _default_retrieve_fn(
        self,
        allowed_document_ids_by_collection: dict[str, set[str] | None] | None,
        metadata_filters: dict | None,
        top_k: int,
        scope_filters: dict | None = None,
    ) -> Callable[[str, str], list[Document]]:
        # Per-(query, collection) hybrid retrieval. We oversize fetch_k and
        # drop the min-score floor so the blender has plenty of candidates;
        # filtering by relevance happens at the doc-level after blending.
        # Chunk fetch size is scaled to top_k so a caller requesting 100 docs
        # gets enough distinct document candidates from the retriever.
        chunk_fetch_k = max(top_k * 5, 50)
        from minix.core.modules.rag.hybrid_retriever import HybridRetriever
        from minix.core.modules.rag.qdrant_ops import vector_search
        from minix.core.modules.rag.services.chunk_service import RagChunkService

        svc_chunk = Registry().get(RagChunkService)

        def _retrieve(query_text: str, collection: str) -> list[Document]:
            allowed = (
                allowed_document_ids_by_collection.get(collection)
                if allowed_document_ids_by_collection is not None
                else None
            )
            if allowed is not None and len(allowed) == 0:
                return []

            # Scope passthrough: the caller's scope filters (the controller's
            # `_scope_filters` hook) become a hard vector filter and a
            # whitelisted BM25 filter. None = unscoped.

            def _vector_fn(q: str, col: str, k: int):
                return vector_search(q, col, k=k, allowed_document_ids=allowed, filters=metadata_filters, hard_filters=scope_filters)

            def _bm25_fn(q: str, col: str, k: int):
                return svc_chunk.bm25_search_with_filter(q, col, k=k, metadata_filters=metadata_filters, allowed_doc_uuids=allowed, extra_filters=scope_filters)

            retriever = HybridRetriever(
                collection_name=collection,
                top_k=chunk_fetch_k,
                # Don't pre-filter at chunk level; blending handles noise.
                min_score=0.0,
                vector_search_fn=_vector_fn,
                bm25_search_fn=_bm25_fn,
                metadata_bulk_fn=None,
            )
            return retriever.invoke(query_text)

        return _retrieve

    def match(
        self,
        req: MatchRequest,
        *,
        allowed_document_ids_by_collection: dict[str, set[str] | list[str] | None] | None = None,
        scope_filters: dict | None = None,
    ) -> MatchResponse:
        collections = (
            [req.collection] if req.collection is not None
            else list(req.search_collections or [])
        )

        # Verify collections exist (raise LookupError → 404 in controller).
        col_svc = self._svc_collection()
        for col in collections:
            if not col_svc.get_by_name(col):
                raise LookupError(f"Collection '{col}' not found.")

        normalized_allowed: dict[str, set[str] | None] | None = None
        if allowed_document_ids_by_collection is not None:
            normalized_allowed = {
                k: (set(map(str, v)) if v is not None else None)
                for k, v in allowed_document_ids_by_collection.items()
            }

        retrieve_fn = (
            self._retrieve_fn_factory(normalized_allowed)
            if self._retrieve_fn_factory is not None
            else self._default_retrieve_fn(normalized_allowed, req.filters, req.top_k, scope_filters=scope_filters)
        )
        blender = MultiQueryBlender(retrieve_fn)
        hits = blender.blend(
            queries=req.queries,
            collections=collections,
            top_k=req.top_k,
            score_normalization=req.score_normalization,
        )

        # Enrich with PG-stored document metadata (source filename etc.).
        doc_ids = [h.document_id for h in hits]
        meta_by_id = self._svc_document().get_metadata_bulk(doc_ids) if doc_ids else {}

        items: list[MatchResultItem] = []
        for h in hits:
            doc_meta = meta_by_id.get(str(h.document_id), {})
            merged_meta = {**h.metadata, **doc_meta}
            items.append(MatchResultItem(
                document_id=h.document_id,
                collection=h.collection,
                source=h.source or doc_meta.get("source"),
                metadata=merged_meta,
                final_score=h.final_score,
                matched_chunks=h.matched_chunks,
                query_scores={
                    name: QueryScore(
                        raw=s.raw,
                        normalized=s.normalized,
                        weight=s.weight,
                        contribution=s.contribution,
                    )
                    for name, s in h.query_scores.items()
                },
            ))
        return MatchResponse(results=items)
