import pytest

pytest.importorskip("pgvector")

from sqlalchemy import Text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, Session, mapped_column

from minix.core.connectors import SqlConnector
from minix.core.entity import PGVectorEntity
from minix.core.module.business_module import BusinessModule
from minix.core.registry import Registry
from minix.core.repository import PGVectorRepository, SqlRepository
from minix.core.service import PGVectorService, SqlService


class EmbeddingEntity(PGVectorEntity):
    vector_size = 3

    content: Mapped[str] = mapped_column(Text, nullable=False)


class EmbeddingRepository(PGVectorRepository[EmbeddingEntity]):
    pass


class EuclidEmbeddingRepository(PGVectorRepository[EmbeddingEntity]):
    def get_distance(self) -> str:
        return 'Euclid'


class EmbeddingService(PGVectorService[EmbeddingEntity]):
    pass


class _RecordingQuery:
    """Wraps an unbound Query; records the SQL instead of executing it."""

    def __init__(self, query, session):
        self._query = query
        self._session = session

    def __getattr__(self, name):
        attr = getattr(self._query, name)

        def chain(*args, **kwargs):
            return _RecordingQuery(attr(*args, **kwargs), self._session)

        return chain

    def all(self):
        self._session.statements.append(self._query.statement)
        return self._session.rows


class _RecordingSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.statements = []
        self.executed = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, *entities):
        return _RecordingQuery(Session().query(*entities), self)

    def execute(self, statement):
        self.executed.append(str(statement))

    def commit(self):
        self.committed = True


class _FakeConnector:
    def __init__(self, session):
        self.session = session

    def get_session(self):
        return self.session


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_entity_has_sql_columns_and_sized_vector():
    columns = EmbeddingEntity.__table__.columns
    assert {'id', 'created_at', 'updated_at', 'content', 'vector'} <= set(columns.keys())
    assert columns['vector'].type.compile(dialect=postgresql.dialect()) == 'VECTOR(3)'
    assert columns['vector'].nullable is False


def test_repository_and_service_extend_sql_layer():
    assert issubclass(PGVectorRepository, SqlRepository)
    assert issubclass(PGVectorService, SqlService)


def test_search_orders_by_cosine_distance_and_limits():
    entity = EmbeddingEntity(content='a', vector=[1.0, 0.0, 0.0])
    session = _RecordingSession(rows=[(entity, 0.0)])
    repository = EmbeddingRepository(EmbeddingEntity, _FakeConnector(session))

    assert repository.search([1.0, 0.0, 0.0], top_k=5) == [entity]

    sql = _sql(session.statements[0])
    assert '<=>' in sql
    assert 'ORDER BY' in sql and 'LIMIT 5' in sql


def test_search_with_distance_applies_filters_and_max_distance():
    entity = EmbeddingEntity(content='a', vector=[1.0, 0.0, 0.0])
    session = _RecordingSession(rows=[(entity, 0.25)])
    repository = EuclidEmbeddingRepository(EmbeddingEntity, _FakeConnector(session))

    result = repository.search_with_distance([1.0, 0.0, 0.0], top_k=2, max_distance=0.5, content='a')

    assert result == [(entity, 0.25)]
    sql = _sql(session.statements[0])
    assert '<->' in sql
    assert "content = 'a'" in sql
    assert '<= 0.5' in sql


def test_unsupported_distance_raises():
    class BadRepository(PGVectorRepository[EmbeddingEntity]):
        def get_distance(self) -> str:
            return 'Hamming'

    repository = BadRepository(EmbeddingEntity, _FakeConnector(_RecordingSession()))
    with pytest.raises(ValueError):
        repository.search([1.0, 0.0, 0.0])


def test_create_extension():
    session = _RecordingSession()
    EmbeddingRepository(EmbeddingEntity, _FakeConnector(session)).create_extension()

    assert session.executed == ['CREATE EXTENSION IF NOT EXISTS vector']
    assert session.committed


def test_service_get_knn_searches_by_entity_vector():
    entity = EmbeddingEntity(content='a', vector=[0.0, 1.0, 0.0])
    session = _RecordingSession(rows=[(entity, 0.0)])
    service = EmbeddingService(EmbeddingRepository(EmbeddingEntity, _FakeConnector(session)))

    assert service.get_knn(entity, top_k=3) == [entity]
    assert 'LIMIT 3' in _sql(session.statements[0])


def test_business_module_installs_binding_with_sql_connector():
    connector = _FakeConnector(_RecordingSession())
    Registry().register(SqlConnector, connector)

    BusinessModule('pgvector_test').add_binding(
        EmbeddingEntity, EmbeddingRepository, EmbeddingService
    ).install()

    repository = Registry().get(EmbeddingRepository)
    assert repository.sql_connector is connector
    assert Registry().get(EmbeddingService).get_repository() is repository
