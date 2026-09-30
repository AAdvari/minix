"""The RAG module stands alone and is extensible without being edited.

Pins the framework contract the RAG module relies on:

* `RagController` builds its routes and OpenAPI schema with no database, and
  mounts only the core RAG surface;
* the default access policy is role-only and never filters retrieval;
* `provides=` registers an installed instance under a base type too, so a
  subclass stands in for a framework class everywhere it is resolved;
* a subclass of a mapped entity that names no table extends the parent's table
  (single-table inheritance) instead of defining a second one.
"""
import pytest
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String

pytest.importorskip("langchain_core")
pytest.importorskip("qdrant_client")

from fastapi import FastAPI  # noqa: E402

from minix.core.modules.auth.dependencies import AuthContext  # noqa: E402
from minix.core.modules.auth.entities import UserRole  # noqa: E402
from minix.core.modules.rag.controllers import RagController  # noqa: E402
from minix.core.modules.rag.entities import RagCollectionEntity  # noqa: E402
from minix.core.modules.rag.services.access_policy import RoleAccessPolicy  # noqa: E402

_CORE_ROUTES = {
    "GET /rag/chunking/strategies",
    "POST /rag/collections", "GET /rag/collections",
    "GET /rag/collections/{name}", "PATCH /rag/collections/{name}",
    "DELETE /rag/collections/{name}",
    "GET /rag/collections/{name}/documents",
    "GET /rag/collections/{name}/documents/{doc_id}",
    "DELETE /rag/collections/{name}/documents/{doc_id}",
    "GET /rag/collections/{name}/documents/{doc_id}/chunks",
    "POST /rag/ingest/upload", "POST /rag/ingest/text", "POST /rag/match",
    "GET /rag/jobs/{job_id}",
    "POST /rag/search", "GET /rag/search/{search_id}",
    "POST /rag/query", "GET /rag/query/{query_id}",
    "GET /rag/health", "GET /rag/me",
}


def test_controller_builds_the_core_routes():
    app = FastAPI()
    app.include_router(RagController().get_router)
    spec = app.openapi()
    routes = {f"{m.upper()} {p}" for p, ops in spec["paths"].items() for m in ops}
    assert routes == _CORE_ROUTES


class _Policy(RoleAccessPolicy):
    def __init__(self, enabled: bool):
        self._enabled = enabled

    def _flag(self):
        return self._enabled


def test_access_policy_is_role_only():
    reader = AuthContext(user_id="r", role=UserRole.READONLY, api_key_id=1)
    user = AuthContext(user_id="u", role=UserRole.USER, api_key_id=2)
    admin = AuthContext(user_id="a", role=UserRole.ADMIN, api_key_id=3)
    on = _Policy(True)
    assert on.check_collection_permission(reader, "c", "query")
    assert not on.check_collection_permission(reader, "c", "ingest")
    assert on.check_collection_permission(user, "c", "ingest")
    assert not on.check_collection_permission(user, "c", "delete_collection")
    assert on.check_collection_permission(admin, "c", "delete_collection")
    assert on.allowed_document_ids(reader, "c") is None
    # Flag off: the anonymous-admin developer flow, everything passes.
    assert _Policy(False).check_collection_permission(reader, "c", "delete_collection")
    with pytest.raises(ValueError):
        on.check_collection_permission(admin, "c", "no_such_action")


def test_provides_registers_the_instance_under_the_base_type():
    from minix.core.module.business_module import BusinessModule
    from minix.core.registry.registry import Registry
    from minix.core.service import Service

    class _Repo:
        pass

    class _BaseService(Service):
        def __init__(self, repository):
            self.repository = repository

    class _SubService(_BaseService):
        pass

    Registry().register(_Repo, _Repo())
    module = BusinessModule("provides_probe")
    module.repositories = [(_Repo, None, None)]
    module.services = [(_SubService, _BaseService)]
    module.install_services(module.services)
    assert isinstance(Registry().get(_BaseService), _SubService)
    assert Registry().get(_BaseService) is Registry().get(_SubService)


def test_module_follows_the_binding_convention():
    """Like `AuthModule` / `OidcModule`: one `add_binding` per entity, so the
    entity / repository / service lists cannot drift out of step."""
    from minix.core.modules.rag.module import RagModule

    assert len(RagModule.entities) == len(RagModule.repositories) == len(RagModule.services) == 6
    assert [c for c, _ in RagModule.controllers] == [RagController]
    assert RagModule.name == "rag_module"


def test_qdrant_client_uses_a_registered_connector():
    from minix.core.connectors import QdrantConnector
    from minix.core.modules.rag import qdrant_ops
    from minix.core.registry.registry import Registry

    seen = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    real = qdrant_ops.QdrantClient
    qdrant_ops.QdrantClient = _FakeClient
    Registry().register(QdrantConnector, QdrantConnector("http://qdrant.internal:6333", "secret"))
    qdrant_ops.get_qdrant_client.cache_clear()
    try:
        qdrant_ops.get_qdrant_client()
        assert seen["url"] == "http://qdrant.internal:6333"
        assert seen["api_key"] == "secret"
    finally:
        qdrant_ops.QdrantClient = real
        Registry().registry.pop(QdrantConnector, None)
        qdrant_ops.get_qdrant_client.cache_clear()


def test_entity_subclass_extends_the_parent_table():
    class ExtendedCollectionEntity(RagCollectionEntity):
        probe_label: Mapped[str | None] = mapped_column(String(32), nullable=True)

    assert ExtendedCollectionEntity.__table__ is RagCollectionEntity.__table__
    assert "probe_label" in RagCollectionEntity.__table__.columns
    assert RagCollectionEntity.__tablename__ == "rag_collections"
