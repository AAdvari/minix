# RAG module service exports. Lazy so pure service tests can import one
# service without importing optional RAG runtime dependencies.

__all__ = [
    "RagCollectionService",
    "RagDocumentService",
    "RagChunkService",
    "RagJobService",
    "RagSearchRequestService",
    "RagQueryRequestService",
]

_EXPORTS = {
    "RagCollectionService": "minix.core.modules.rag.services.collection_service",
    "RagDocumentService": "minix.core.modules.rag.services.document_service",
    "RagChunkService": "minix.core.modules.rag.services.chunk_service",
    "RagJobService": "minix.core.modules.rag.services.job_service",
    "RagSearchRequestService": "minix.core.modules.rag.services.search_request_service",
    "RagQueryRequestService": "minix.core.modules.rag.services.query_request_service",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = __import__(module_name, fromlist=[name])
    value = getattr(module, name)
    globals()[name] = value
    return value
