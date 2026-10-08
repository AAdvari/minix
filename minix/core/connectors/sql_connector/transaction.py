"""Shared SQL session / cross-module transaction support."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Iterator

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from minix.core.connectors.sql_connector.sql_connector import SqlConnector

# connector id → (session, nesting depth)
_tx_sessions: ContextVar[dict[int, tuple[Session, int]] | None] = ContextVar(
    "minix_sql_tx_sessions",
    default=None,
)


class TransactionalSessionProxy:
    """Session stand-in while an outer ``SqlConnector.transaction()`` owns the unit.

    Repository code that calls ``commit()`` / ``close()`` (or uses ``with session``)
    joins the outer transaction: ``commit`` flushes, ``close`` is a no-op.
    """

    __slots__ = ("_session",)

    def __init__(self, session: Session):
        object.__setattr__(self, "_session", session)

    def commit(self) -> None:
        self._session.flush()

    def rollback(self) -> None:
        # Outer ``transaction()`` rolls back the whole unit if the block fails.
        return None

    def close(self) -> None:
        return None

    def __enter__(self) -> TransactionalSessionProxy:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def __getattr__(self, name: str):
        return getattr(self._session, name)


def _connector_key(connector: SqlConnector) -> int:
    return id(connector)


def in_transaction(connector: SqlConnector) -> bool:
    state = _tx_sessions.get()
    return bool(state and _connector_key(connector) in state)


def active_session(connector: SqlConnector) -> Session | None:
    state = _tx_sessions.get()
    if not state:
        return None
    entry = state.get(_connector_key(connector))
    return entry[0] if entry else None


@contextmanager
def transaction_scope(connector: SqlConnector) -> Iterator[Session]:
    """Run *connector* work in one session; nested calls use SAVEPOINTs."""
    state = _tx_sessions.get()
    token: Token | None = None
    if state is None:
        state = {}
        token = _tx_sessions.set(state)

    key = _connector_key(connector)
    if key in state:
        session, depth = state[key]
        state[key] = (session, depth + 1)
        nested = session.begin_nested()
        try:
            yield session
            nested.commit()
        except Exception:
            nested.rollback()
            raise
        finally:
            session, depth = state[key]
            state[key] = (session, depth - 1)
        return

    session = connector.open_session()
    state[key] = (session, 1)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        state.pop(key, None)
        session.close()
        if token is not None and not state:
            _tx_sessions.reset(token)


def _resolve_sql_connector(connection: str = "default") -> SqlConnector:
    from minix.core.connectors.sql_connector.sql_connector import SqlConnector
    from minix.core.registry import Registry

    salt = None if connection == "default" else connection
    connector = (
        Registry().get(SqlConnector, salt=salt)
        if salt is not None
        else Registry().get(SqlConnector)
    )
    if connector is None:
        label = connection if salt else "default"
        raise RuntimeError(
            f"SqlConnector {label!r} is not registered. "
            "Call bootstrap_from_settings() (or register connectors) first."
        )
    return connector


@contextmanager
def sql_transaction(connection: str = "default") -> Iterator[Session]:
    """Shorthand for ``Registry().get(SqlConnector).transaction()``.

    Example::

        from minix.core.connectors import sql_transaction

        with sql_transaction():
            order_repo.save(order)
            payment_repo.save(payment)

        with sql_transaction("mysql"):
            ...
    """
    with transaction_scope(_resolve_sql_connector(connection)) as session:
        yield session
