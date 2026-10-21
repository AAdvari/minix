# FastAPI controller exposing all RAG endpoints using MINIX Controller pattern.
import hashlib
import io
import json
import re
import tempfile
import shutil
import time
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, File, Form, BackgroundTasks, Query, Depends, Security, Request
from pydantic import ValidationError

from minix.core.controller import Controller
from minix.core.registry import Registry
from minix.core.modules.rag.config import RagConfig
from minix.core.modules.rag.chunking import SmartChunker, STRATEGY_METADATA
from minix.core.modules.rag.metadata_extractor import MetadataExtractor
from minix.core.modules.rag.document_processor import get_processor
from minix.core.modules.rag.qdrant_ops import (
    get_vectorstore,
    delete_document_vectors,
    vector_search,
    get_qdrant_collection_info,
    list_qdrant_collections,
)
from minix.core.modules.rag.hybrid_retriever import HybridRetriever, fuse_and_rank
from minix.core.modules.rag.rag_chain import query_with_debug, query_with_debug_multi
from minix.core.modules.rag.refusal import infer_refusal_reason
from minix.core.modules.rag.retrieval.llm_reranker import rerank as llm_rerank
from minix.core.modules.rag.services import (
    RagCollectionService,
    RagDocumentService,
    RagChunkService,
    RagJobService,
    RagSearchRequestService,
    RagQueryRequestService,
)
from minix.core.modules.rag.services.match_service import MatchService
from minix.core.modules.rag.services.access_policy import RoleAccessPolicy, not_found
from minix.core.modules.auth.dependencies import AuthContext, API_KEY_HEADER
from minix.core.modules.auth.entities import UserRole
from minix.core.modules.auth.services import ApiKeyService
from minix.core.modules.rag.controllers.schemas import (
    CreateCollectionRequest, CollectionInfo, JobAccepted, JobStatus,
    DocumentDetail, DocumentListResponse,
    ChunkDetail, ChunkListResponse,
    SearchRequest, SearchAccepted, SearchResult, SearchResponse, SearchStatusResponse,
    QueryRequest, QueryAccepted, QueryResponse, QueryStatusResponse,
    IngestTextRequest, ChunkingConfig, ChunkingStrategyInfo,
    MatchRequest, MatchResponse,
    UpdateCollectionRequest,
)
from langchain_core.documents import Document


def _identity_header(filename: str, meta: dict | None) -> str:
    """Build a compact document-identity line to prepend to each chunk.

    Surfaces the discriminating signal (title / parties / source name) that
    otherwise lives only in the filename, so a query naming a document can match
    the right one among many near-identical documents. Kept short so it does not
    dominate the chunk.
    """
    meta = meta or {}
    # Humanize the filename: drop extension, turn separators into spaces. The
    # filename usually carries the party names (e.g. "DoiT-ICN-NonDisclosure").
    base = re.sub(r"\.[^.]+$", "", filename or "")
    base = re.sub(r"[-_%]+", " ", base).strip()
    title = str(meta.get("title") or "").strip()
    parts: list[str] = []
    if title:
        parts.append(f"Document: {title}")
        if base and base.lower() not in title.lower():
            parts.append(base)
    elif base:
        parts.append(f"Document: {base}")
    parties = meta.get("parties")
    if parties:
        parties_str = parties if isinstance(parties, str) else ", ".join(map(str, parties))
        if parties_str.strip():
            parts.append(f"Parties: {parties_str.strip()}")
    return (". ".join(parts) + ".") if parts else ""

# The auth module's `API_KEY_HEADER` is the per-request API-key extractor
# (auto_error=False), so what a missing key means is decided here from
# RAG_ACCESS_CONTROL_ENABLED — see `get_optional_auth_context`.


async def get_optional_auth_context(
    request: Request,
    api_key: str | None = Security(API_KEY_HEADER),
) -> AuthContext:
    """Auth dependency for every RAG route — generic framework: API-key only.

    With `RAG_ACCESS_CONTROL_ENABLED=false` and no key, returns the
    anonymous-admin context (single-user developer flow). With the flag on,
    missing credentials are a 401. A *present but invalid* key is always a 401.

    A consuming layer overrides `get_auth_dependency()` to add other
    credential types (e.g. JWT sessions) or request scoping.
    """
    flag_on = RagConfig.ACCESS_CONTROL_ENABLED
    if api_key:
        service = Registry().get(ApiKeyService)
        key_entity = service.validate_key(api_key)
        if not key_entity:
            raise HTTPException(401, {"error": "unauthorized", "message": "Invalid or expired API key."})
        return AuthContext(
            user_id=key_entity.user_id,
            role=key_entity.role,
            api_key_id=key_entity.id,
        )
    if flag_on:
        raise HTTPException(401, {"error": "unauthorized", "message": "Authentication required."})
    return AuthContext(user_id="anonymous", role=UserRole.ADMIN, api_key_id=0)


async def get_health_auth_context(api_key: str | None = Security(API_KEY_HEADER)) -> AuthContext | None:
    """Best-effort identity for liveness.

    Health remains public, but collection names are returned only to admins
    when access control is on. Missing or invalid keys therefore become
    anonymous health probes instead of 401s.
    """
    if not api_key:
        return None
    try:
        service = Registry().get(ApiKeyService)
        key_entity = service.validate_key(api_key)
    except Exception:
        return None
    if not key_entity:
        return None
    return AuthContext(
        user_id=key_entity.user_id,
        role=key_entity.role,
        api_key_id=key_entity.id,
    )


async def _no_ingest_options() -> dict:
    """Default `/ingest/upload` options dependency: the framework reads no extra
    form fields. See `RagController.get_ingest_options_dependency`."""
    return {}


class RagController(Controller):

    # ── Response / request models ─────────────────────────────────────────────
    # Class attributes so a consuming layer can swap in subclasses that carry
    # extra fields (e.g. an access-control or compliance layer) without
    # redefining the routes. Routes read them when `define_routes()` runs.
    CREATE_COLLECTION_REQUEST_MODEL = CreateCollectionRequest
    UPDATE_COLLECTION_REQUEST_MODEL = UpdateCollectionRequest
    COLLECTION_INFO_MODEL = CollectionInfo
    DOCUMENT_DETAIL_MODEL = DocumentDetail
    DOCUMENT_LIST_RESPONSE_MODEL = DocumentListResponse
    INGEST_TEXT_REQUEST_MODEL = IngestTextRequest
    SEARCH_STATUS_RESPONSE_MODEL = SearchStatusResponse
    QUERY_RESPONSE_MODEL = QueryResponse
    QUERY_STATUS_RESPONSE_MODEL = QueryStatusResponse

    # Route name -> OpenAPI description, overriding the route's docstring. Lets
    # a consuming layer document behavior it adds to a framework route.
    ROUTE_DESCRIPTIONS: dict[str, str] = {}

    def _route_description(self, route: str) -> str | None:
        # None makes FastAPI fall back to the endpoint docstring.
        return self.ROUTE_DESCRIPTIONS.get(route)

    def get_prefix(self):
        return "/rag"

    def define_routes(self):
        self._define_collection_routes()
        self._define_document_routes()
        self._define_ingestion_routes()
        self._define_job_routes()
        self._define_search_routes()
        self._define_query_routes()
        self._define_health_routes()
        self._define_identity_routes()

    # ── Service accessors ─────────────────────────────────────────────────────

    def _svc_collection(self) -> RagCollectionService:
        return Registry().get(RagCollectionService)

    def _svc_document(self) -> RagDocumentService:
        return Registry().get(RagDocumentService)

    def _svc_chunk(self) -> RagChunkService:
        return Registry().get(RagChunkService)

    def _svc_job(self) -> RagJobService:
        return Registry().get(RagJobService)

    def _svc_search(self) -> RagSearchRequestService:
        return Registry().get(RagSearchRequestService)

    def _svc_query(self) -> RagQueryRequestService:
        return Registry().get(RagQueryRequestService)

    def _svc_access(self):
        """The permission service every route asks. The framework answers from
        global roles only (`RoleAccessPolicy`); a consuming layer returns an
        object with the same methods that adds per-collection grants and
        per-document visibility."""
        return RoleAccessPolicy()

    # ── Extension hooks ───────────────────────────────────────────────────────
    # Every default below is the generic single-scope behavior, so the RAG
    # module stands alone. A consuming layer overrides them to add request
    # scoping (tenancy), gating and usage metering, access control, audit,
    # guardrails, compliance and cost tracking — without redefining routes.

    def get_auth_dependency(self):
        """The FastAPI auth dependency used by every RAG route."""
        return get_optional_auth_context

    def get_health_auth_dependency(self):
        """The best-effort auth dependency used by the public health route."""
        return get_health_auth_context

    def get_ingest_options_dependency(self):
        """Dependency that reads extra `/ingest/upload` form fields into an
        options dict, passed to the ingest hooks below. None in the framework."""
        return _no_ingest_options

    # Request scope (tenancy) ─────────────────────────────────────────────────

    def _request_scope(self, auth: "AuthContext") -> int | None:
        """Opaque scope discriminator for the request. None (unscoped) in the
        generic framework; a scope provider overrides it."""
        return None

    def _scope_kwargs(self, auth: "AuthContext") -> dict:
        """Scope kwargs splatted into row-creating service calls. Empty in the
        generic framework."""
        return {}

    def _scope_filters(self, scope_id: int | None) -> dict | None:
        """Hard retrieval filters for the scope — fed to
        `vector_search(hard_filters=...)` and `bm25_search*(extra_filters=...)`.
        None (no scope filter) in the generic framework."""
        return None

    def _row_scope(self, row) -> int | None:
        """The scope a stored row belongs to, for background work that has no
        `auth` (ingest tasks). None in the generic framework."""
        return None

    def _assert_row_scope(self, auth: "AuthContext", row,
                          allow_none: bool = False) -> None:
        """Enforce a scope boundary on a fetched row. No-op in the generic
        framework (no tenancy); a scope provider overrides it."""
        return

    def _ingest_scope_meta(self, doc_row) -> dict:
        """Scope keys stamped into every Qdrant point payload at ingest. Empty
        in the generic framework."""
        return {}

    # Gating + usage ──────────────────────────────────────────────────────────

    def _gate_request(self, auth: "AuthContext") -> None:
        """Pre-flight gate for write ops (e.g. rate limiting). No-op in the
        generic framework."""
        return

    def _gate_metered(self, auth: "AuthContext", metric: str,
                      quantity: float = 1.0) -> None:
        """Quota pre-flight for a metered action. No-op in the generic framework."""
        return

    def _record_usage(self, scope_id: int | None, metric: str,
                      quantity: float = 1.0, ref: str | None = None,
                      user_id: str | None = None) -> None:
        """Record a usage event. No-op in the generic framework."""
        return

    def _cost_tracker(self, scope_id: int | None):
        """LLM cost tracker handed to the chunker (see SmartChunker). None —
        no cost tracking — in the generic framework."""
        return None

    def _record_llm_cost(self, operation: str, collection: str | None,
                         description: str, input_text: str, output_text: str,
                         model: str, *, extra_calls: int = 0,
                         scope_id: int | None = None) -> None:
        """Record the cost of an LLM call made on a request path. No-op in the
        generic framework."""
        return

    # Audit ───────────────────────────────────────────────────────────────────

    def _audit(self, auth: "AuthContext | None", action: str, *,
               collection: str | None = None, target: str | None = None,
               reason: str | None = None) -> None:
        """Record a management action (collection/document create, update,
        delete). No-op in the generic framework."""
        return

    def _audit_disclosure(self, *, action: str, actor_id: str | None,
                          scope_id: int | None, collection: str | None,
                          target: str | None = None,
                          document_ids=None) -> None:
        """Record that document content was returned to a caller (search
        results, query context, chunk listing). No-op in the generic framework."""
        return

    # Collections ─────────────────────────────────────────────────────────────

    def _collection_create_kwargs(self, req) -> dict:
        """Extra kwargs for `create_collection` taken from the create request."""
        return {}

    def _on_collection_created(self, auth: "AuthContext", req, row) -> None:
        """Runs after a collection row is created (e.g. seed policies, grant
        the creator ownership). No-op in the generic framework."""
        return

    def _apply_collection_update(self, name: str, req, row,
                                 reasons: list[str]):
        """Apply update-request fields beyond `chunking_config`, appending the
        name of each applied field to `reasons`. Returns the refreshed row
        (or the one passed in when nothing changed)."""
        return row

    def _collection_info_extras(self, auth: "AuthContext", row) -> dict:
        """Extra `COLLECTION_INFO_MODEL` fields for a collection row."""
        return {}

    # Documents ───────────────────────────────────────────────────────────────

    def _document_detail_extras(self, row, *, full: bool = False) -> dict:
        """Extra `DOCUMENT_DETAIL_MODEL` fields for a document row. `full` is
        True on the single-document route, False in listings."""
        return {}

    # Ingestion ───────────────────────────────────────────────────────────────

    def _ingest_text_options(self, req, request_metadata: dict) -> dict:
        """Ingest options for `/ingest/text` (the counterpart of the upload
        options dependency). May consume keys from `request_metadata`."""
        return {}

    def _document_register_kwargs(self, options: dict) -> dict:
        """Extra kwargs for `RagDocumentService.register` from ingest options."""
        return {}

    def _ingest_payload_meta(self, options: dict) -> dict:
        """Extra keys stamped into every Qdrant point payload at ingest."""
        return {}

    def _validate_upload(self, collection: str, filename: str, size: int,
                         metadata: dict) -> None:
        """Pre-flight check on an upload before any processing (raise
        HTTPException to reject). No-op in the generic framework."""
        return

    def _validate_ingest_text(self, collection: str, text: str,
                              metadata: dict) -> None:
        """Pre-flight check on `/ingest/text` input (raise HTTPException to
        reject). No-op in the generic framework."""
        return

    def _metadata_extraction_mode(self, collection: str) -> str:
        """"standard" | "minimal" | "off" — how much LLM metadata extraction
        runs at ingest."""
        return "standard"

    def _validate_extracted_text(self, collection: str, text: str,
                                 metadata: dict) -> None:
        """Post-extraction check on a file's text (raise to fail the job).
        No-op in the generic framework."""
        return

    def _ingest_file_job_extras(self, collection: str) -> dict:
        """Extra keys for a completed file-ingest job's result."""
        return {}

    def _record_provider_event(self, operation: str, provider: str, *,
                               doc_id: int | None = None, **kwargs) -> None:
        """Called at each point data is sent to an external model provider
        (extraction, embedding, reranking, answering). No-op in the generic
        framework."""
        return

    # Search + query ──────────────────────────────────────────────────────────

    def _redact_input(self, auth: "AuthContext", text: str):
        """Rewrite search/query text before it is stored or used. Returns
        `(text, context)`; `context` is handed to `_audit_input_redaction`.
        Pass-through in the generic framework."""
        return text, None

    def _audit_input_redaction(self, context, *, query_id: int,
                               user_id: str | None,
                               collection_name: str | None) -> None:
        """Record what `_redact_input` changed, once the request row exists."""
        return

    def _shape_search_results(self, results: list[dict], collection: str,
                              search_id: int) -> list[dict]:
        """Post-process `/search` results before they are stored."""
        return results

    def _answer_single(self, question: str, retriever: HybridRetriever, *,
                       collection: str, query_id: int,
                       raw_question: str | None, user_id: str | None,
                       rerank: bool | None, scope_id: int | None) -> dict:
        """Answer a single-collection query."""
        return query_with_debug(question, retriever, rerank=rerank)

    def _answer_multi(self, question: str, retrievers: dict, *,
                      collections: list[str], top_k: int, query_id: int,
                      raw_question: str | None, user_id: str | None,
                      rerank: bool | None, scope_id: int | None) -> dict:
        """Answer a query fanned out across several collections."""
        return query_with_debug_multi(
            question=question, retrievers=retrievers, top_k=top_k, rerank=rerank,
        )

    def _query_payload_extras(self, result: dict, refusal: str | None) -> dict:
        """Extra keys for the stored `/query` result payload."""
        return {}

    def _redact_query_chunks(self, collection: str, retrieved: list[dict],
                             selected: list[dict],
                             result: dict) -> tuple[list[dict], list[dict]]:
        """Post-process a single-collection answer's chunks before they are
        returned and stored. `result` is what `_answer_single` returned."""
        return retrieved, selected

    def _shape_query_payload(self, payload: dict, collection: str,
                             query_id: int) -> dict:
        """Post-process a single-collection `/query` payload before storage."""
        return payload

    def _request_row_extras(self, row) -> dict:
        """Extra fields for the search/query status responses."""
        return {}

    # Health ──────────────────────────────────────────────────────────────────

    def _health_extras(self) -> dict:
        """Extra keys for the `/health` payload."""
        return {}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _require_collection(self, name: str):
        if not self._svc_collection().get_by_name(name):
            raise not_found()

    def _check_perm(self, auth: AuthContext, collection: str, action: str,
                    *, force: bool = False) -> None:
        """Raise 403 if `auth` cannot perform `action` on `collection`.

        The scope boundary is checked FIRST — a collection outside the caller's
        scope must look like it does not exist (404), never a 403, so the
        permission error never discloses existence. `allow_none` leaves
        genuinely-missing collections to the route's own 404.

        `force=True` threads through to `require_collection_permission`,
        enforcing the role check even when `RAG_ACCESS_CONTROL_ENABLED` is off,
        for the specific callers that opt in."""
        svc_access = self._svc_access()
        col = self._svc_collection().get_by_name(collection)
        self._assert_row_scope(auth, col, allow_none=True)
        svc_access.require_collection_permission(auth, collection, action, force=force)

    def _check_polling_access(self, auth: AuthContext, requester_user_id: str | None,
                              collection: str | None, action: str = "read") -> None:
        """Polling endpoints: re-check requester match + current permission on
        the collection. On any mismatch, raise 404 to avoid leaking id
        existence."""
        if not RagConfig.ACCESS_CONTROL_ENABLED or auth.role == UserRole.ADMIN:
            return
        if requester_user_id and requester_user_id != auth.user_id:
            raise not_found()
        if collection and not self._svc_access().check_collection_permission(
            auth, collection, action,
        ):
            raise not_found()

    def _chunk_dicts(self, chunks: list[Document]) -> list[dict]:
        return [
            {
                "content": c.page_content,
                "chunk_index": c.metadata.get("chunk_index"),
                "section_type": c.metadata.get("section_type"),
                "parent_heading": c.metadata.get("parent_heading"),
            }
            for c in chunks
        ]

    def _chunking_job_result(self, chunking_config: dict, chunks: list[Document]) -> dict:
        requested = chunking_config.get("strategy", "smart")
        meta = chunks[0].metadata if chunks else {}
        return {
            "chunking_strategy_requested": meta.get(
                "chunking_strategy_requested", requested,
            ),
            "chunking_strategy_effective": meta.get(
                "chunking_strategy_effective", requested,
            ),
            "llm_chunking_fallback": bool(meta.get("llm_chunking_fallback", False)),
            "llm_chunking_warnings": meta.get("llm_chunking_warnings", []),
        }

    def _build_retriever(
        self,
        collection_name: str,
        top_k: int | None = None,
        min_score: float | None = None,
        allowed_doc_ids: set[str] | None = None,
        scope_id: int | None = None,
    ) -> HybridRetriever:
        svc_chunk = self._svc_chunk()
        svc_doc = self._svc_document()

        # Wrap the search functions so both legs of hybrid retrieval consume
        # the same allowed-doc-id set — both legs MUST derive from one
        # `allowed_document_ids(...)` call. Both legs also carry the caller's
        # scope filter (the `_scope_filters` hook), so neither vector nor
        # keyword retrieval can cross a scope boundary.
        scope_filters = self._scope_filters(scope_id)

        def _vector_fn(query: str, collection: str, k: int):
            return vector_search(
                query, collection, k=k,
                allowed_document_ids=allowed_doc_ids,
                hard_filters=scope_filters,
            )

        def _bm25_fn(query: str, collection: str, k: int):
            return svc_chunk.bm25_search(
                query, collection, k=k,
                allowed_doc_uuids=allowed_doc_ids,
                extra_filters=scope_filters,
            )

        return HybridRetriever(
            collection_name=collection_name,
            bm25_weight=RagConfig.BM25_WEIGHT,
            vector_weight=RagConfig.VECTOR_WEIGHT,
            top_k=(top_k or RagConfig.TOP_K) * 2,
            min_score=(
                RagConfig.MIN_RELEVANCE_SCORE if min_score is None else float(min_score)
            ),
            vector_search_fn=_vector_fn,
            bm25_search_fn=_bm25_fn,
            metadata_bulk_fn=svc_doc.get_metadata_bulk,
        )

    # ── Background tasks ──────────────────────────────────────────────────────

    def _run_ingest_file(self, job_id: int, doc_id: int, content: bytes,
                         filename: str, collection: str, provider: str,
                         chunking_config: dict, file_hash: str,
                         storage_path: str,
                         requester_user_id: str | None = None,
                         extra_metadata: dict | None = None,
                         options: dict | None = None) -> None:
        # `extra_metadata` is the upload's `metadata` form field: it reaches
        # both Postgres (`caller_metadata`) and every Qdrant payload.
        # `options` come from `get_ingest_options_dependency()`.
        extra_metadata = extra_metadata or {}
        options = options or {}
        svc_job = self._svc_job()
        svc_doc = self._svc_document()
        svc_chunk = self._svc_chunk()
        svc_job.mark_processing(job_id)
        tmp_dir = tempfile.mkdtemp()
        try:
            tmp_path = Path(tmp_dir) / filename
            tmp_path.write_bytes(content)
            text = get_processor(provider).process(str(tmp_path))
            if not text.strip():
                raise ValueError("No text could be extracted from the file.")
            self._record_provider_event(
                "ingest_extract",
                "openai" if provider == "gpt" else provider,
                doc_id=doc_id,
                model_or_service=RagConfig.DOCUMENT_PROCESSOR_MODEL if provider == "gpt" else None,
                collection_name=collection,
                job_id=job_id,
                metadata={"filename": filename, "file_hash": file_hash},
            )
            # Metadata extraction mode (off / minimal / standard).
            extraction_mode = self._metadata_extraction_mode(collection)
            if extraction_mode == "off":
                entity_meta: dict = {}
                document_type = "general"
            else:
                extractor = MetadataExtractor()
                entity_meta = extractor.extract(text)
                document_type = entity_meta.pop("_detected_type", "general")
                if extraction_mode == "minimal":
                    _MINIMAL_KEYS = {"title", "date", "author", "language", "document_type"}
                    entity_meta = {k: v for k, v in entity_meta.items() if k in _MINIMAL_KEYS}
            # Post-extraction gate (raises to fail the job with a clear message).
            self._validate_extracted_text(collection, text, entity_meta)
            _doc_row = svc_doc.get_by_id(doc_id)
            # The doc row is the earliest point in this background task where
            # the ingest scope is known (background tasks have no `auth`).
            _ingest_scope = self._row_scope(_doc_row)
            base_meta = {
                "source": filename,
                "document_id": str(_doc_row.doc_uuid),
                "collection_name": collection,
                "document_type": document_type,
                **self._ingest_payload_meta(options),
                # Scope keys go into every point payload so the vector leg can
                # hard-filter by scope (the `_ingest_scope_meta` hook).
                **self._ingest_scope_meta(_doc_row),
                # Same precedence as the text path — caller keys first, so
                # extractor output wins a collision (its keys are the documented
                # ones retrieval filters on).
                **extra_metadata,
                **entity_meta,
            }
            doc = Document(page_content=text, metadata=base_meta)
            chunker = SmartChunker(cost_tracker=self._cost_tracker(_ingest_scope))
            chunks = chunker.chunk(doc, config=chunking_config)
            # Document-identity enrichment: prepend a short title/parties/source
            # header to every chunk so retrieval (vector + keyword) can tell
            # near-identical documents apart. Done before embedding + keyword
            # indexing so both legs see it.
            if RagConfig.INGEST_IDENTITY_ENRICHMENT:
                identity = _identity_header(base_meta.get("source", ""), entity_meta)
                if identity:
                    for ch in chunks:
                        ch.page_content = f"{identity}\n\n{ch.page_content}"
            get_vectorstore(collection).add_documents(chunks)
            svc_chunk.add_chunks(doc_id, collection, self._chunk_dicts(chunks))
            svc_doc.mark_indexed(doc_id, len(chunks), document_type=document_type,
                                 extracted_metadata=entity_meta,
                                 caller_metadata=extra_metadata)
            svc_doc.update_file_info(doc_id, file_hash, storage_path)
            self._record_provider_event(
                "embed", "openai",
                doc_id=doc_id,
                model_or_service=RagConfig.EMBEDDING_MODEL,
                collection_name=collection,
                job_id=job_id,
                metadata={"chunks_stored": len(chunks)},
            )
            svc_job.complete_job(job_id, doc_id, {
                "document_id": str(svc_doc.get_by_id(doc_id).doc_uuid),
                "collection": collection,
                "document_type": document_type,
                "chunking_strategy": chunking_config.get("strategy", "smart"),
                **self._chunking_job_result(chunking_config, chunks),
                "extracted_metadata": entity_meta,
                "chunks_stored": len(chunks),
                "file_hash": file_hash,
                "storage_path": storage_path,
                **self._ingest_file_job_extras(collection),
            })
            self._record_usage(_ingest_scope, "documents_ingested", 1.0, ref=str(job_id), user_id=requester_user_id)
            self._record_usage(_ingest_scope, "pages_processed", float(len(chunks)), ref=str(job_id), user_id=requester_user_id)
        except Exception as e:
            svc_doc.mark_failed(doc_id, str(e))
            svc_job.fail_job(job_id, str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _run_ingest_text(self, job_id: int, doc_id: int, text: str,
                         source: str, collection: str, extra_metadata: dict,
                         chunking_config: dict,
                         requester_user_id: str | None = None,
                         options: dict | None = None) -> None:
        options = options or {}
        svc_job = self._svc_job()
        svc_doc = self._svc_document()
        svc_chunk = self._svc_chunk()
        svc_job.mark_processing(job_id)
        try:
            # Metadata extraction mode (off / minimal / standard).
            extraction_mode = self._metadata_extraction_mode(collection)
            if extraction_mode == "off":
                entity_meta: dict = {}
                document_type = "general"
            else:
                extractor = MetadataExtractor()
                entity_meta = extractor.extract(text)
                document_type = entity_meta.pop("_detected_type", "general")
                if extraction_mode == "minimal":
                    _MINIMAL_KEYS = {"title", "date", "author", "language", "document_type"}
                    entity_meta = {k: v for k, v in entity_meta.items() if k in _MINIMAL_KEYS}
            _doc_row = svc_doc.get_by_id(doc_id)
            # See `_run_ingest_file` — same reasoning for the scope tag.
            _ingest_scope = self._row_scope(_doc_row)
            base_meta = {
                "source": source,
                "document_id": str(_doc_row.doc_uuid),
                "collection_name": collection,
                "document_type": document_type,
                **self._ingest_payload_meta(options),
                # Scope keys on every point payload (see above).
                **self._ingest_scope_meta(_doc_row),
                **extra_metadata,
                **entity_meta,
            }
            doc = Document(page_content=text, metadata=base_meta)
            chunker = SmartChunker(cost_tracker=self._cost_tracker(_ingest_scope))
            chunks = chunker.chunk(doc, config=chunking_config)
            # Document-identity enrichment: prepend a short title/parties/source
            # header to every chunk so retrieval (vector + keyword) can tell
            # near-identical documents apart. Done before embedding + keyword
            # indexing so both legs see it.
            if RagConfig.INGEST_IDENTITY_ENRICHMENT:
                identity = _identity_header(base_meta.get("source", ""), entity_meta)
                if identity:
                    for ch in chunks:
                        ch.page_content = f"{identity}\n\n{ch.page_content}"
            get_vectorstore(collection).add_documents(chunks)
            svc_chunk.add_chunks(doc_id, collection, self._chunk_dicts(chunks))
            # `caller_metadata` persists what the CALLER supplied, in Postgres
            # as well as in the Qdrant payload.
            svc_doc.mark_indexed(doc_id, len(chunks), document_type=document_type,
                                 extracted_metadata=entity_meta,
                                 caller_metadata=extra_metadata)
            if extraction_mode != "off":
                self._record_provider_event(
                    "ingest_extract", "openai",
                    doc_id=doc_id,
                    model_or_service=RagConfig.LLM_MODEL,
                    collection_name=collection, job_id=job_id,
                )
            self._record_provider_event(
                "embed", "openai",
                doc_id=doc_id,
                model_or_service=RagConfig.EMBEDDING_MODEL,
                collection_name=collection, job_id=job_id,
                metadata={"chunks_stored": len(chunks)},
            )
            svc_job.complete_job(job_id, doc_id, {
                "document_id": str(svc_doc.get_by_id(doc_id).doc_uuid),
                "collection": collection,
                "document_type": document_type,
                "chunking_strategy": chunking_config.get("strategy", "smart"),
                **self._chunking_job_result(chunking_config, chunks),
                "extracted_metadata": entity_meta,
                "chunks_stored": len(chunks),
            })
            self._record_usage(_ingest_scope, "documents_ingested", 1.0, ref=str(job_id), user_id=requester_user_id)
            self._record_usage(_ingest_scope, "pages_processed", float(len(chunks)), ref=str(job_id), user_id=requester_user_id)
        except Exception as e:
            svc_doc.mark_failed(doc_id, str(e))
            svc_job.fail_job(job_id, str(e))

    def _run_search(self, search_id: int, query: str, collection: str,
                    mode: str, top_k: int, filters: dict,
                    allowed_doc_ids: set[str] | None = None,
                    scope_id: int | None = None,
                    requester_user_id: str | None = None,
                    rerank: bool = False) -> None:
        svc_search = self._svc_search()
        svc_search.mark_processing(search_id)
        started = time.monotonic()
        scope_filters = self._scope_filters(scope_id)
        try:
            fetch_k = max(
                top_k * RagConfig.RETRIEVAL_FETCH_MULTIPLIER,
                RagConfig.RETRIEVAL_CANDIDATE_FLOOR,
            )
            vector_docs = []
            bm25_rows = []
            if mode in ("hybrid", "vector"):
                vector_docs = vector_search(
                    query, collection, k=fetch_k,
                    filters=filters if filters else None,
                    allowed_document_ids=allowed_doc_ids,
                    hard_filters=scope_filters,
                )
            if mode in ("hybrid", "keyword"):
                bm25_rows = self._svc_chunk().bm25_search_with_filter(
                    query, collection, k=fetch_k,
                    metadata_filters=filters if filters else None,
                    allowed_doc_uuids=allowed_doc_ids,
                    extra_filters=scope_filters,
                )
            # Build keyword rows into Documents, then fuse + rank with the same
            # helper the /query path uses, so /search returns a properly ranked,
            # scored list. (It previously concatenated all keyword rows ahead of
            # all vector rows, unscored.) min_score=0.0 because /search is raw
            # retrieval — it returns what it found, just ranked; thresholding and
            # refusal belong to the answer path.
            bm25_docs = [
                Document(
                    page_content=row["content"],
                    metadata={
                        "document_id": row["document_id"],
                        "section_type": row.get("section_type"),
                        "parent_heading": row.get("parent_heading"),
                        "bm25_score": float(row.get("score") or 0.0),
                    },
                )
                for row in bm25_rows
            ]
            stype = {"keyword": "bm25", "vector": "vector"}.get(mode, "hybrid")
            candidates = fuse_and_rank(
                bm25_docs, vector_docs,
                bm25_weight=RagConfig.BM25_WEIGHT,
                vector_weight=RagConfig.VECTOR_WEIGHT,
                top_k=top_k,
                min_score=0.0,
            )
            doc_ids = [d.metadata.get("document_id") for d in candidates if d.metadata.get("document_id")]
            meta_by_id = self._svc_document().get_metadata_bulk(doc_ids)
            rerank_fallback_reason = None
            if rerank and candidates:
                candidates, rerank_fallback_reason = self._rerank_search_candidates(
                    query, collection, candidates, meta_by_id, top_k,
                    search_id=search_id, scope_id=scope_id,
                )
            results = []
            for rank, doc in enumerate(candidates, 1):
                doc_id = doc.metadata.get("document_id", "")
                doc_meta = meta_by_id.get(str(doc_id), {})
                results.append({
                    "rank": rank,
                    "content": doc.page_content,
                    "document_id": str(doc_id),
                    "score": round(float(doc.metadata.get("relevance_score") or 0.0), 6),
                    "metadata": {"document_id": doc_id,
                                 "section_type": doc.metadata.get("section_type"),
                                 "parent_heading": doc.metadata.get("parent_heading"), **doc_meta},
                    "search_type": stype,
                    "rerank_score": doc.metadata.get("rerank_score"),
                })
            duration_ms = int((time.monotonic() - started) * 1000)
            results = self._shape_search_results(results, collection, search_id)
            result_payload = {
                "results": results,
                "total": len(results),
                "query": query,
                "collection": collection,
                "mode": mode,
                "reranked": bool(rerank) and rerank_fallback_reason is None,
                "rerank_fallback_reason": rerank_fallback_reason,
            }
            svc_search.complete(search_id, result_payload, duration_ms)
            # Who received which documents. Content-free: document uuids and a
            # count, never the query text.
            self._audit_disclosure(
                action="search.disclose",
                actor_id=requester_user_id,
                scope_id=scope_id,
                collection=collection,
                target=str(search_id),
                document_ids=[r.get("document_id") for r in results],
            )
            self._record_usage(scope_id, "searches", 1.0, ref=str(search_id), user_id=requester_user_id)
        except Exception as e:
            duration_ms = int((time.monotonic() - started) * 1000)
            svc_search.fail(search_id, str(e), duration_ms)

    def _rerank_search_candidates(self, query: str, collection: str,
                                  candidates: list[Document], meta_by_id: dict,
                                  top_k: int, *, search_id: int,
                                  scope_id: int | None) -> tuple[list[Document], str | None]:
        """Re-order /search results with the LLM reranker (same results, new
        order). The reranker sees each chunk's document metadata (source name,
        heading) as well as its text. Its LLM call goes through the cost and
        provider-event hooks, because /search otherwise sends nothing to a model
        provider."""
        docs = [
            Document(
                page_content=d.page_content,
                metadata={**meta_by_id.get(str(d.metadata.get("document_id")), {}), **d.metadata},
            )
            for d in candidates
        ]
        result = llm_rerank(query, docs, keep_n=top_k, min_score=0.0)
        if result.skipped:
            return candidates, None
        model = RagConfig.RERANKER_MODEL or RagConfig.LLM_MODEL
        self._record_llm_cost(
            "Search rerank", collection, f"query: {query}",
            query + " ".join(d.page_content[:RagConfig.RERANKER_MAX_CHARS] for d in docs),
            json.dumps(result.scores), model,
            scope_id=scope_id,
        )
        self._record_provider_event(
            "search_rerank_llm", "openai",
            model_or_service=model,
            collection_name=collection,
            search_id=search_id,
            status="failed" if result.fallback_reason else "completed",
            metadata={"chunks": len(docs)},
        )
        return result.docs, result.fallback_reason

    def _run_query(
        self,
        query_id: int,
        question: str,
        collection: str | None,
        top_k: int,
        debug: bool,
        search_collections: list[str] | None = None,
        min_score: float | None = None,
        allowed_doc_ids_per_collection: dict[str, set[str] | None] | None = None,
        raw_question: str | None = None,
        scope_id: int | None = None,
        requester_user_id: str | None = None,
        rerank: bool | None = None,
    ) -> None:
        """
        Applied fixes (vs. the pre-hardening version):
          1. `collection: null` no longer fans out to every collection on the server.
             Callers must set `collection` OR `search_collections` (see request schema).
          2. `retrieved_chunks`, `selected_chunks`, `selection_scores`,
             `skipped_selection` are ALWAYS populated — no more debug gating.
          3. Multi-collection responses return a `collections` list of the collections
             that actually contributed chunks, instead of the opaque string "__all__".
          4. `refusal_reason` is inferred from the LLM answer + retrieval state and
             included in every response.
          5. Chunking `strategy` is validated by the Pydantic schema (rejected if
             unknown) — see `ChunkingConfig` / `ChunkingStrategy`.
        """
        svc_query = self._svc_query()
        svc_query.mark_processing(query_id)
        started = time.monotonic()
        try:
            is_multi = collection is None
            if is_multi:
                # Fix 1 — explicit allowlist. Schema already rejected the case where
                # both are null, so `search_collections` is guaranteed non-empty here.
                requested = list(search_collections or [])
                # Enforce that every requested collection exists; fail on first missing
                # so a typo isn't silently dropped.
                known = {c.name for c in self._svc_collection().list_all()}
                missing = [c for c in requested if c not in known]
                if missing:
                    raise ValueError(
                        f"Unknown collection(s) in search_collections: {missing}. "
                        f"Known: {sorted(known)}"
                    )
                # Per-collection allowed_doc_ids snapshot taken at request time.
                # Caller-supplied filters cannot widen this; revocations are
                # caught by the polling re-check, not retroactively here.
                doc_ids_map = allowed_doc_ids_per_collection or {}
                retrievers = {
                    name: self._build_retriever(
                        name, top_k, min_score=min_score,
                        allowed_doc_ids=doc_ids_map.get(name),
                        scope_id=scope_id,
                    )
                    for name in requested
                }
                result = self._answer_multi(
                    question, retrievers,
                    collections=requested, top_k=top_k, query_id=query_id,
                    raw_question=raw_question, user_id=requester_user_id,
                    rerank=rerank, scope_id=scope_id,
                )
                # Fix 3 — compute the collections that *actually* contributed chunks
                # to the answer (not just those that were searched).
                contributing = self._collections_from_chunks(
                    result.get("selected_chunks") or []
                )
                if not contributing:
                    # fall back to retrieved-chunk sources if nothing selected
                    contributing = self._collections_from_chunks(
                        result.get("retrieved_chunks") or []
                    )
                input_text = question + " ".join(
                    c.get("content", "") for c in (result.get("selected_chunks") or [])
                )
                self._record_llm_cost(
                    "Query (multi-collection)", ",".join(requested),
                    f"question: {question}",
                    input_text, result["answer"], RagConfig.LLM_MODEL,
                    extra_calls=0 if result["skipped_selection"] else 1,
                    scope_id=scope_id,
                )
                self._record_usage(scope_id, "queries", 1.0, ref=str(query_id), user_id=requester_user_id)
                # Fix 4 — refusal classifier. A typed verdict from the answer
                # path (`result["refusal_reason"]`) takes precedence over the
                # heuristic.
                refusal = result.get("refusal_reason") or infer_refusal_reason(
                    question,
                    result["answer"],
                    result.get("selected_chunks") or [],
                    result.get("retrieved_chunks") or [],
                )
                # Fix 2 — chunks always populated (no `if debug else None`).
                result_payload = {
                    "answer": result["answer"],
                    "collection": None,  # multi-collection → use `collections`
                    "collections": contributing or requested,
                    "_searched_collections": requested,
                    "retrieved_chunks": result["retrieved_chunks"],
                    "selected_chunks": result["selected_chunks"],
                    "selection_scores": result["selection_scores"],
                    "skipped_selection": result["skipped_selection"],
                    "rerank_fallback_reason": result.get("rerank_fallback_reason"),
                    "refusal_reason": refusal,
                    **self._query_payload_extras(result, refusal),
                }
            else:
                # Single-collection path. We always use `query_with_debug` so the
                # provenance data is available; the `debug` request flag is a no-op.
                doc_ids_map = allowed_doc_ids_per_collection or {}
                retriever = self._build_retriever(
                    collection, top_k, min_score=min_score,
                    allowed_doc_ids=doc_ids_map.get(collection),
                    scope_id=scope_id,
                )
                result = self._answer_single(
                    question, retriever,
                    collection=collection, query_id=query_id,
                    raw_question=raw_question, user_id=requester_user_id,
                    rerank=rerank, scope_id=scope_id,
                )
                input_text = question + " ".join(
                    c.get("content", "") for c in (result.get("selected_chunks") or [])
                )
                self._record_llm_cost(
                    "Query", collection,
                    f"question: {question}",
                    input_text, result["answer"], RagConfig.LLM_MODEL,
                    extra_calls=0 if result["skipped_selection"] else 1,
                    scope_id=scope_id,
                )
                self._record_usage(scope_id, "queries", 1.0, ref=str(query_id), user_id=requester_user_id)
                refusal = result.get("refusal_reason") or infer_refusal_reason(
                    question,
                    result["answer"],
                    result.get("selected_chunks") or [],
                    result.get("retrieved_chunks") or [],
                )
                # Done here, at the single assembly point, so what is returned
                # and what is stored agree.
                _retrieved, _selected = self._redact_query_chunks(
                    collection, result["retrieved_chunks"], result["selected_chunks"],
                    result,
                )
                result_payload = {
                    "answer": result["answer"],
                    "collection": collection,
                    "collections": [collection],
                    "retrieved_chunks": _retrieved,
                    "selected_chunks": _selected,
                    "selection_scores": result["selection_scores"],
                    "skipped_selection": result["skipped_selection"],
                    "rerank_fallback_reason": result.get("rerank_fallback_reason"),
                    "refusal_reason": refusal,
                    **self._query_payload_extras(result, refusal),
                }
                result_payload = self._shape_query_payload(result_payload, collection, query_id)
            duration_ms = int((time.monotonic() - started) * 1000)
            svc_query.complete(query_id, result_payload, duration_ms)
            # Disclosure: `retrieved_chunks` is the set the answer was built
            # from; a refusal carries an empty list, so a refused query records a
            # disclosure of zero documents rather than nothing at all.
            self._audit_disclosure(
                action="query.disclose",
                actor_id=requester_user_id,
                scope_id=scope_id,
                collection=collection,
                target=str(query_id),
                document_ids=[
                    (c.get("metadata") or {}).get("document_id")
                    for c in (result_payload.get("retrieved_chunks") or [])
                ],
            )
            self._record_provider_event(
                "query_llm", "openai",
                model_or_service=RagConfig.LLM_MODEL,
                collection_name=collection,
                query_id=query_id,
                metadata={
                    "is_multi": collection is None,
                    "duration_ms": duration_ms,
                    "skipped_selection": bool(result_payload.get("skipped_selection")),
                },
            )
        except Exception as e:
            duration_ms = int((time.monotonic() - started) * 1000)
            svc_query.fail(query_id, str(e), duration_ms)
            self._record_provider_event(
                "query_llm", "openai",
                model_or_service=RagConfig.LLM_MODEL,
                collection_name=collection,
                query_id=query_id,
                status="failed",
                metadata={"error": str(e)[:200]},
            )

    @staticmethod
    def _collections_from_chunks(chunks: list[dict]) -> list[str]:
        """Return the unique collection names the given chunks came from,
        preserving first-seen order. Used to populate the `collections`
        response field after multi-collection retrieval."""
        seen: list[str] = []
        for c in chunks:
            meta = c.get("metadata") or {}
            col = meta.get("_collection") or meta.get("collection_name")
            if col and col not in seen:
                seen.append(col)
        return seen

    # ── Routes ────────────────────────────────────────────────────────────────

    def _define_collection_routes(self):
        CreateCollectionModel = self.CREATE_COLLECTION_REQUEST_MODEL
        UpdateCollectionModel = self.UPDATE_COLLECTION_REQUEST_MODEL
        CollectionInfoModel = self.COLLECTION_INFO_MODEL

        @self._actual_router.get(
            "/chunking/strategies", response_model=list[ChunkingStrategyInfo],
            description=self._route_description("list_chunking_strategies"),
        )
        def list_chunking_strategies():
            """Selectable chunking strategies with UI labels/descriptions.
            Static metadata sourced from the chunking module so the UI never
            duplicates the strategy enum."""
            return [ChunkingStrategyInfo(**m) for m in STRATEGY_METADATA]

        @self._actual_router.post("/collections", response_model=CollectionInfoModel, status_code=201)
        def create_collection(
            req: CreateCollectionModel,
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            if RagConfig.ACCESS_CONTROL_ENABLED and auth.role == UserRole.READONLY:
                raise HTTPException(403, {"error": "forbidden", "required_role": "user"})
            # Gate only (no usage metric): an unbounded create loop is a cheap
            # way to exhaust the database and the Qdrant collection count.
            self._gate_request(auth)
            svc = self._svc_collection()
            try:
                row = svc.create_collection(
                    req.name, req.description, req.chunking_config.model_dump(),
                    **self._collection_create_kwargs(req),
                    **self._scope_kwargs(auth),
                )
            except ValueError as e:
                raise HTTPException(409, str(e))
            self._on_collection_created(auth, req, row)
            stats = svc.get_stats(req.name, 0, 0)
            return CollectionInfoModel(
                name=row.name, description=row.description,
                chunking_config=row.chunking_config,
                created_at=row.created_at, documents=0, chunks=0,
                vectors=stats["vectors"], index_status=stats["index_status"],
                **self._collection_info_extras(auth, row),
            )

        @self._actual_router.get("/collections", response_model=list[CollectionInfoModel])
        def list_collections(auth: AuthContext = Depends(self.get_auth_dependency())):
            svc_col = self._svc_collection()
            svc_doc = self._svc_document()
            svc_chunk = self._svc_chunk()
            rows = svc_col.list_all()
            visible = set(self._svc_access().allowed_collections(auth, "read", None))
            result = []
            for row in rows:
                if row.name not in visible:
                    continue
                dc = svc_doc.count_by_collection(row.name)
                cc = svc_chunk.count_by_collection(row.name)
                stats = svc_col.get_stats(row.name, dc, cc)
                result.append(CollectionInfoModel(
                    name=row.name, description=row.description,
                    chunking_config=row.chunking_config or {},
                    created_at=row.created_at,
                    documents=stats["documents"], chunks=stats["chunks"],
                    vectors=stats["vectors"], index_status=stats["index_status"],
                    **self._collection_info_extras(auth, row),
                ))
            return result

        @self._actual_router.get("/collections/{name}", response_model=CollectionInfoModel)
        def get_collection(
            name: str,
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            svc_col = self._svc_collection()
            row = svc_col.get_by_name(name)
            if not row:
                raise not_found()
            self._check_perm(auth, name, "read")
            dc = self._svc_document().count_by_collection(name)
            cc = self._svc_chunk().count_by_collection(name)
            stats = svc_col.get_stats(name, dc, cc)
            return CollectionInfoModel(
                name=row.name, description=row.description,
                chunking_config=row.chunking_config or {},
                created_at=row.created_at,
                documents=stats["documents"], chunks=stats["chunks"],
                vectors=stats["vectors"], index_status=stats["index_status"],
                **self._collection_info_extras(auth, row),
            )

        @self._actual_router.delete("/collections/{name}", status_code=204)
        def delete_collection(
            name: str,
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            if name == RagConfig.DEFAULT_COLLECTION:
                raise HTTPException(400, "The default collection cannot be deleted.")
            self._require_collection(name)
            self._check_perm(auth, name, "delete_collection")
            self._audit(auth, "collection.delete", collection=name, target=name)
            self._svc_collection().delete_collection(name)

        @self._actual_router.patch(
            "/collections/{name}", response_model=CollectionInfoModel,
            description=self._route_description("update_collection"),
        )
        def update_collection(
            name: str,
            req: UpdateCollectionModel,
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            """Edit a collection's chunking_config. Changes apply to NEW ingests
            only — existing documents keep their chunks until re-ingested.
            Requires the `update_collection` permission."""
            self._require_collection(name)
            self._check_perm(auth, name, "update_collection")
            svc = self._svc_collection()
            row = None
            reasons: list[str] = []
            if req.chunking_config is not None:
                # Shallow-merge the partial onto the current config, then
                # re-validate through the full ChunkingConfig model so bounds +
                # literal strategy are enforced (e.g. chunk_size=99 → 422).
                current = svc.get_chunking_config(name)
                patch_dict = req.chunking_config.model_dump(exclude_none=True)
                merged = {**current, **patch_dict}
                try:
                    validated = ChunkingConfig(**merged).model_dump()
                except ValidationError as e:
                    raise HTTPException(422, {"error": "invalid_chunking_config", "details": e.errors()})
                row = svc.update_chunking_config(name, validated)
                reasons.append("chunking_config")
            row = self._apply_collection_update(name, req, row, reasons)
            if row is None:
                raise not_found()
            self._audit(
                auth, "collection.update", collection=name, target=name,
                reason=",".join(reasons),
            )
            dc = self._svc_document().count_by_collection(name)
            cc = self._svc_chunk().count_by_collection(name)
            stats = svc.get_stats(name, dc, cc)
            return CollectionInfoModel(
                name=row.name, description=row.description,
                chunking_config=row.chunking_config or {},
                created_at=row.created_at,
                documents=stats["documents"], chunks=stats["chunks"],
                vectors=stats["vectors"], index_status=stats["index_status"],
                **self._collection_info_extras(auth, row),
            )

    def _define_document_routes(self):
        DocumentDetailModel = self.DOCUMENT_DETAIL_MODEL
        DocumentListModel = self.DOCUMENT_LIST_RESPONSE_MODEL

        @self._actual_router.get("/collections/{name}/documents", response_model=DocumentListModel)
        def list_documents(
            name: str,
            page: int = Query(default=1, ge=1),
            page_size: int = Query(default=20, ge=1, le=100),
            status: str | None = Query(default=None),
            document_type: str | None = Query(default=None),
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            self._require_collection(name)
            self._check_perm(auth, name, "list_documents")
            # Management path: `include_restricted=True` lists documents whose
            # content the policy withholds from retrieval, so they stay
            # administrable (see list_document_chunks below).
            allowed_doc_ids = self._svc_access().allowed_document_ids(
                auth, name, include_restricted=True,
            )
            rows, total = self._svc_document().list_by_collection(
                name, page, page_size, status, document_type,
                allowed_doc_uuids=allowed_doc_ids,
            )
            pages = max(1, -(-total // page_size))
            return DocumentListModel(
                documents=[
                    DocumentDetailModel(
                        document_id=str(r.doc_uuid),
                        collection_name=r.collection_name,
                        source_file=r.source_file,
                        document_type=r.document_type,
                        status=r.status,
                        extracted_metadata=r.extracted_metadata or {},
                        chunks_count=r.chunks_count or 0,
                        error_message=r.error_message,
                        created_at=r.created_at,
                        indexed_at=r.indexed_at,
                        **self._document_detail_extras(r),
                    )
                    for r in rows
                ],
                total=total, page=page, page_size=page_size, pages=pages,
            )

        @self._actual_router.get("/collections/{name}/documents/{doc_id}", response_model=DocumentDetailModel)
        def get_document(
            name: str, doc_id: str,
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            self._require_collection(name)
            self._check_perm(auth, name, "read")
            try:
                doc_uuid = uuid.UUID(doc_id)
            except ValueError:
                raise HTTPException(400, "Invalid document ID format.")
            row = self._svc_document().get_by_doc_uuid(doc_uuid)
            if not row or row.collection_name != name:
                raise not_found()
            # Management path: `include_restricted=True` (see list_documents).
            allowed_doc_ids = self._svc_access().allowed_document_ids(
                auth, name, include_restricted=True,
            )
            if allowed_doc_ids is not None and str(row.doc_uuid) not in allowed_doc_ids:
                raise not_found()
            return DocumentDetailModel(
                document_id=str(row.doc_uuid),
                collection_name=row.collection_name,
                source_file=row.source_file,
                document_type=row.document_type,
                status=row.status,
                extracted_metadata=row.extracted_metadata or {},
                chunks_count=row.chunks_count or 0,
                error_message=row.error_message,
                created_at=row.created_at,
                indexed_at=row.indexed_at,
                **self._document_detail_extras(row, full=True),
            )

        @self._actual_router.get(
            "/collections/{name}/documents/{doc_id}/chunks",
            response_model=ChunkListResponse,
        )
        def list_document_chunks(
            name: str,
            doc_id: str,
            page: int = Query(default=1, ge=1),
            page_size: int = Query(default=50, ge=1, le=200),
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            self._require_collection(name)
            self._check_perm(auth, name, "read")
            try:
                doc_uuid = uuid.UUID(doc_id)
            except ValueError:
                raise HTTPException(400, "Invalid document ID format.")
            row = self._svc_document().get_by_doc_uuid(doc_uuid)
            if not row or row.collection_name != name:
                raise not_found()
            allowed_doc_ids = self._svc_access().allowed_document_ids(auth, name)
            if allowed_doc_ids is not None and str(row.doc_uuid) not in allowed_doc_ids:
                raise not_found()
            offset = (page - 1) * page_size
            chunks, total = self._svc_chunk().list_by_document_uuid(
                str(doc_uuid), limit=page_size, offset=offset
            )
            pages = max(1, -(-total // page_size))
            # This route returns raw chunk text — the most direct disclosure of
            # document content in the API.
            self._audit_disclosure(
                action="chunks.disclose",
                actor_id=None if auth.user_id == "anonymous" else auth.user_id,
                scope_id=self._request_scope(auth),
                collection=name,
                target=str(row.doc_uuid),
                document_ids=[str(row.doc_uuid)],
            )
            return ChunkListResponse(
                chunks=[
                    ChunkDetail(
                        chunk_id=c["chunk_id"],
                        chunk_index=c["chunk_index"],
                        section_type=c["section_type"],
                        parent_heading=c["parent_heading"],
                        collection_name=c["collection_name"],
                        char_count=c["char_count"],
                        content=c["content"],
                    )
                    for c in chunks
                ],
                total=total, page=page, page_size=page_size, pages=pages,
                document_id=str(doc_uuid), collection_name=name,
            )

        @self._actual_router.delete("/collections/{name}/documents/{doc_id}", status_code=204)
        def delete_document(
            name: str, doc_id: str,
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            self._require_collection(name)
            self._check_perm(auth, name, "delete_document")
            try:
                doc_uuid = uuid.UUID(doc_id)
            except ValueError:
                raise HTTPException(400, "Invalid document ID format.")
            row = self._svc_document().get_by_doc_uuid(doc_uuid)
            if not row or row.collection_name != name:
                raise not_found()
            self._audit(
                auth, "document.delete", collection=name, target=doc_id,
            )
            delete_document_vectors(name, doc_id)
            self._svc_document().delete(row)

    def _define_ingestion_routes(self):
        IngestTextModel = self.INGEST_TEXT_REQUEST_MODEL

        @self._actual_router.post("/ingest/upload", response_model=JobAccepted, status_code=202)
        async def ingest_upload(
            background_tasks: BackgroundTasks,
            file: UploadFile = File(...),
            collection: str = Form(default=RagConfig.DEFAULT_COLLECTION),
            provider: str = Form(default="gpt"),
            source: str = Form(default="upload"),
            metadata: str | None = Form(default=None),
            # `auth` is declared before `options` on purpose: FastAPI resolves
            # dependencies in declaration order, so an invalid option is only
            # reported after authentication has run.
            auth: AuthContext = Depends(self.get_auth_dependency()),
            options: dict = Depends(self.get_ingest_options_dependency()),
        ):
            self._gate_request(auth)
            self._check_perm(auth, collection, "ingest")
            self._gate_metered(auth, "documents_ingested")
            requester = None if auth.user_id == "anonymous" else auth.user_id
            self._require_collection(collection)
            _upload_meta: dict = {}
            if metadata:
                try:
                    _upload_meta = json.loads(metadata)
                    if not isinstance(_upload_meta, dict):
                        raise ValueError("metadata must be a JSON object")
                except (json.JSONDecodeError, ValueError) as e:
                    raise HTTPException(400, f"Invalid metadata form field: {e}")
            content = await file.read()
            if not content:
                raise HTTPException(400, "Uploaded file is empty.")
            filename = Path(file.filename or "upload").name
            # Pre-flight check before heavy processing.
            self._validate_upload(collection, filename, len(content), _upload_meta)
            file_hash = hashlib.sha256(content).hexdigest()
            existing = self._svc_document().find_by_hash(collection, file_hash)
            if existing:
                raise HTTPException(409, {
                    "error": "duplicate_file",
                    "message": f"This file has already been indexed in collection '{collection}'.",
                    "document_id": str(existing.doc_uuid),
                    "file_hash": file_hash,
                })
            chunking_config = self._svc_collection().get_chunking_config(collection)
            chunking_config["_collection_name"] = collection
            doc_entity = self._svc_document().register(
                collection, filename, "pending_detection", {},
                **self._document_register_kwargs(options),
            )
            job_entity = self._svc_job().create_job(
                "ingest_upload", collection, requester_user_id=requester,
                **self._scope_kwargs(auth),
            )
            background_tasks.add_task(
                self._run_ingest_file,
                job_entity.id, doc_entity.id, content, filename,
                collection, provider, chunking_config, file_hash, "",
                requester,
                _upload_meta,
                options,
            )
            return JobAccepted(job_id=str(job_entity.job_uuid))

        @self._actual_router.post("/ingest/text", response_model=JobAccepted, status_code=202)
        async def ingest_text(
            req: IngestTextModel,
            background_tasks: BackgroundTasks,
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            # Same gates and metric as `/ingest/upload`: the job records
            # "documents_ingested" usage, so it needs the same pre-flight check.
            self._gate_request(auth)
            self._require_collection(req.collection)
            self._check_perm(auth, req.collection, "ingest")
            self._gate_metered(auth, "documents_ingested")
            requester = None if auth.user_id == "anonymous" else auth.user_id
            request_metadata = dict(req.metadata or {})
            options = self._ingest_text_options(req, request_metadata)
            # Pre-flight check on the input.
            self._validate_ingest_text(req.collection, req.text, request_metadata)
            chunking_config = self._svc_collection().get_chunking_config(req.collection)
            chunking_config["_collection_name"] = req.collection
            doc_entity = self._svc_document().register(
                req.collection, req.source, "pending_detection", {},
                **self._document_register_kwargs(options),
            )
            job_entity = self._svc_job().create_job(
                "ingest_text", req.collection, requester_user_id=requester,
                **self._scope_kwargs(auth),
            )
            background_tasks.add_task(
                self._run_ingest_text,
                job_entity.id, doc_entity.id, req.text, req.source,
                req.collection, request_metadata, chunking_config,
                requester,
                options,
            )
            return JobAccepted(job_id=str(job_entity.job_uuid))

        @self._actual_router.post("/match", response_model=MatchResponse)
        def match(
            req: MatchRequest,
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            # Unlike /query and /search this route is SYNCHRONOUS (`def`, running
            # MatchService inline on the request thread) and takes up to 8 query
            # texts, so it is gated, and metered as "searches" — a weighted
            # multi-query retrieval.
            self._gate_request(auth)
            self._gate_metered(auth, "searches")
            # Schema validator already checked collection XOR + weight sum.
            collections = (
                [req.collection] if req.collection is not None
                else list(req.search_collections or [])
            )
            for c in collections:
                self._check_perm(auth, c, "match")
            allowed_per_col = {
                c: self._svc_access().allowed_document_ids(auth, c)
                for c in collections
            }
            try:
                svc = MatchService()
                return svc.match(
                    req,
                    allowed_document_ids_by_collection=allowed_per_col,
                    scope_filters=self._scope_filters(self._request_scope(auth)),
                )
            except LookupError:
                # The uniform 404 body: `_check_perm` 404s an out-of-scope
                # collection with `not_found()`, so an absent one must get the
                # same body, or the difference becomes an existence oracle.
                raise not_found()
            except ValueError as e:
                # 400, not 404: a malformed request discloses nothing about what
                # exists, and the message is about the caller's own input.
                raise HTTPException(400, str(e))

    def _define_job_routes(self):
        @self._actual_router.get("/jobs/{job_id}", response_model=JobStatus)
        def get_job_status(
            job_id: str,
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            try:
                job_uuid = uuid.UUID(job_id)
            except ValueError:
                raise HTTPException(400, "Invalid job ID format.")
            row = self._svc_job().get_by_uuid(job_uuid)
            if not row:
                raise not_found()
            # A job outside the caller's scope is 404, not 403 — polling cannot
            # confirm the id exists.
            self._assert_row_scope(auth, row)
            # Polling re-check: requester match AND current permission on the
            # job's collection. Mismatch → 404 (not 403).
            self._check_polling_access(auth, row.requester_user_id, row.collection_name, "read")
            return JobStatus(
                job_id=str(row.job_uuid),
                type=row.type,
                status=row.status,
                collection_name=row.collection_name,
                document_id=str(row.document_id) if row.document_id else None,
                result=row.result,
                error_message=row.error_message,
                created_at=row.created_at,
                started_at=row.started_at,
                completed_at=row.completed_at,
            )

    def _define_search_routes(self):
        SearchStatusModel = self.SEARCH_STATUS_RESPONSE_MODEL

        @self._actual_router.post("/search", response_model=SearchAccepted, status_code=202)
        def search(
            req: SearchRequest, background_tasks: BackgroundTasks,
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            self._gate_request(auth)
            self._require_collection(req.collection)
            self._check_perm(auth, req.collection, "search")
            self._gate_metered(auth, "searches")
            requester = None if auth.user_id == "anonymous" else auth.user_id
            allowed = self._svc_access().allowed_document_ids(auth, req.collection)
            # Input rewrite before the query touches the DB, retrieval, or the
            # LLM (the `_redact_input` hook).
            redacted_query, redaction = self._redact_input(auth, req.query)
            entity = self._svc_search().create(
                redacted_query, req.collection, req.mode, req.top_k, req.filters,
                requester_user_id=requester,
                **self._scope_kwargs(auth),
            )
            self._audit_input_redaction(
                redaction, query_id=entity.id,
                user_id=requester, collection_name=req.collection,
            )
            background_tasks.add_task(
                self._run_search,
                entity.id, redacted_query, req.collection, req.mode, req.top_k, req.filters,
                allowed,
                self._request_scope(auth),
                requester,
                rerank=req.rerank,
            )
            return SearchAccepted(search_id=entity.id)

        @self._actual_router.get("/search/{search_id}", response_model=SearchStatusModel)
        def get_search_result(
            search_id: int,
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            row = self._svc_search().get_by_id(search_id)
            if not row:
                raise not_found()
            # Scope boundary first, unconditional on ACCESS_CONTROL_ENABLED and
            # on role (same `_assert_row_scope` every scoped route shares).
            self._assert_row_scope(auth, row)
            # Polling re-check: requester match AND current permission on the
            # request's collection. Mismatch → 404 to avoid an id-existence
            # oracle.
            self._check_polling_access(auth, row.requester_user_id, row.collection, "search")
            result_obj = None
            if row.result and row.status == "completed":
                result_obj = SearchResponse(**row.result)
            return SearchStatusModel(
                search_id=row.id,
                status=row.status,
                success=row.success,
                query=row.query,
                **self._request_row_extras(row),
                collection=row.collection,
                mode=row.mode,
                top_k=row.top_k,
                result=result_obj,
                error_message=row.error_message,
                duration_ms=row.duration_ms,
                created_at=row.created_at,
                completed_at=row.completed_at,
            )

    def _define_query_routes(self):
        QueryResponseModel = self.QUERY_RESPONSE_MODEL
        QueryStatusModel = self.QUERY_STATUS_RESPONSE_MODEL

        @self._actual_router.post("/query", response_model=QueryAccepted, status_code=202)
        def query(
            req: QueryRequest, background_tasks: BackgroundTasks,
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            # Schema-level validator (`_collection_xor_allowlist`) has already
            # guaranteed exactly one of `collection` / `search_collections` is set.
            collections = (
                [req.collection] if req.collection is not None
                else list(req.search_collections or [])
            )
            self._gate_request(auth)
            for name in collections:
                self._require_collection(name)
                self._check_perm(auth, name, "query")
            self._gate_metered(auth, "queries")
            requester = None if auth.user_id == "anonymous" else auth.user_id
            # Snapshot allowed doc ids per collection at request time.
            allowed_per_col = {
                name: self._svc_access().allowed_document_ids(auth, name)
                for name in collections
            }
            # Input rewrite before the question touches the DB, retrieval, or
            # the LLM (the `_redact_input` hook).
            redacted_question, redaction = self._redact_input(auth, req.question)
            entity = self._svc_query().create(
                redacted_question, req.collection, req.top_k, req.debug,
                requester_user_id=requester,
                search_collections=req.search_collections,
                **self._scope_kwargs(auth),
            )
            self._audit_input_redaction(
                redaction, query_id=entity.id,
                user_id=requester, collection_name=req.collection,
            )
            background_tasks.add_task(
                self._run_query,
                entity.id, redacted_question, req.collection, req.top_k, req.debug,
                req.search_collections, req.min_score, allowed_per_col,
                req.question,  # raw_question: the unredacted text, never stored
                self._request_scope(auth),
                requester,
                rerank=req.rerank,
            )
            return QueryAccepted(query_id=entity.id)

        @self._actual_router.get("/query/{query_id}", response_model=QueryStatusModel)
        def get_query_result(
            query_id: int,
            auth: AuthContext = Depends(self.get_auth_dependency()),
        ):
            row = self._svc_query().get_by_id(query_id)
            if not row:
                raise not_found()
            # Scope boundary first, unconditional on ACCESS_CONTROL_ENABLED and
            # on role (mirrors the job-status route).
            self._assert_row_scope(auth, row)
            self._check_polling_access(auth, row.requester_user_id, row.collection, "query")
            if RagConfig.ACCESS_CONTROL_ENABLED and row.collection is None:
                # Re-check the caller against every collection that was in scope
                # at request time, using the persisted list. This catches grants
                # revoked between submit and poll.
                stored = list(row.search_collections or [])
                if not stored and row.result:
                    stored = row.result.get("_searched_collections") or row.result.get("collections") or []
                for collection_name in stored:
                    if not self._svc_access().check_collection_permission(
                        auth, collection_name, "query",
                    ):
                        raise not_found()
            result_obj = None
            if row.result and row.status == "completed":
                result_obj = QueryResponseModel(**row.result)
            return QueryStatusModel(
                query_id=row.id,
                status=row.status,
                success=row.success,
                question=row.question,
                **self._request_row_extras(row),
                collection=row.collection,
                top_k=row.top_k,
                debug=row.debug,
                result=result_obj,
                error_message=row.error_message,
                duration_ms=row.duration_ms,
                created_at=row.created_at,
                completed_at=row.completed_at,
            )

    def _define_health_routes(self):
        @self._actual_router.get("/health")
        def health(auth: AuthContext | None = Depends(self.get_health_auth_dependency())):
            svc_col = self._svc_collection()
            qdrant_cols = set(svc_col.list_qdrant_collections())
            pg_cols = [r.name for r in svc_col.list_all()]
            can_show_collection_names = (
                not RagConfig.ACCESS_CONTROL_ENABLED
                or (auth is not None and auth.role == UserRole.ADMIN)
            )
            return {
                "status": "healthy",
                "version": "1.0.0",
                "llm_model": RagConfig.LLM_MODEL,
                "qdrant_url": RagConfig.QDRANT_URL,
                "collections": pg_cols if can_show_collection_names else [],
                "default_collection": RagConfig.DEFAULT_COLLECTION,
                "stores_in_sync": set(pg_cols) == qdrant_cols,
                "hybrid_weights": {"bm25": RagConfig.BM25_WEIGHT, "vector": RagConfig.VECTOR_WEIGHT},
                "features": [
                    "async_ingestion", "async_search", "async_query",
                    "job_tracking", "document_management",
                    "search_without_llm", "multi_collection",
                    "layout_aware_chunking", "llm_metadata_extraction",
                    "hybrid_bm25_vector_retrieval", "llm_auto_selection",
                    "citation_tracking", "confidence_scoring",
                ],
                "access_control_enabled": RagConfig.ACCESS_CONTROL_ENABLED,
                **self._health_extras(),
            }

    def _define_identity_routes(self):
        @self._actual_router.get("/me", description=self._route_description("whoami"))
        def whoami(auth: AuthContext = Depends(self.get_auth_dependency())):
            """Identity probe used by a UI to drive role-based hiding.
            With the access-control flag off and no key, returns the
            synthesized anonymous-admin context."""
            return {
                "user_id": auth.user_id,
                "role": auth.role.value if hasattr(auth.role, "value") else str(auth.role),
                "access_control_enabled": RagConfig.ACCESS_CONTROL_ENABLED,
            }
