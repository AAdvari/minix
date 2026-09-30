# RagModule definition: wires the RAG entity/repository/service bindings and the
# controller into MINIX.
from minix.core.module import BusinessModule
from minix.core.modules.rag.entities import (
    RagCollectionEntity, RagDocumentEntity, RagChunkEntity,
    RagJobEntity,
    RagSearchRequestEntity, RagQueryRequestEntity,
)
from minix.core.modules.rag.repositories import (
    RagCollectionRepository, RagDocumentRepository, RagChunkRepository,
    RagJobRepository,
    RagSearchRequestRepository, RagQueryRequestRepository,
)
from minix.core.modules.rag.services import (
    RagCollectionService, RagDocumentService, RagChunkService,
    RagJobService,
    RagSearchRequestService, RagQueryRequestService,
)
from minix.core.modules.rag.controllers import RagController

# Retrieval-augmented generation module. Needs the `rag` extra
# (pip install "minix[rag]"), a PostgreSQL SqlConnector and a Qdrant instance
# (QDRANT_URL, or a QdrantConnector registered at bootstrap). Include alongside
# the core `auth` module: its API keys authenticate the RAG routes.
RagModule = (
    BusinessModule('rag_module')
        .add_binding(RagCollectionEntity, RagCollectionRepository, RagCollectionService)
        .add_binding(RagDocumentEntity, RagDocumentRepository, RagDocumentService)
        .add_binding(RagChunkEntity, RagChunkRepository, RagChunkService)
        .add_binding(RagJobEntity, RagJobRepository, RagJobService)
        .add_binding(RagSearchRequestEntity, RagSearchRequestRepository, RagSearchRequestService)
        .add_binding(RagQueryRequestEntity, RagQueryRequestRepository, RagQueryRequestService)
        .add_controller(RagController)
    )
