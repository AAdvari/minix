"""Which tables belong to which ``settings.DATABASES`` connection."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import Table

# Alembic has no ClickHouse dialect support; those connections are skipped.
MIGRATABLE_DRIVERS = frozenset({"postgresql", "mysql"})


def _connection_name(salt: str | None) -> str:
    # add_binding maps "default" / None to no salt; the deprecated
    # connector_salt="default" keeps the literal name.
    return "default" if salt in (None, "default") else salt


def connection_tables(connection: str = "default", modules: Iterable | None = None) -> dict[str, Table]:
    """Tables of the SQL entities that ``modules`` bind to ``connection``.

    ``modules`` defaults to ``settings.INSTALLED_MODULES``. Modules are only
    built, not installed, so nothing connects to a database or vector store.
    Pairing follows ``BusinessModule.install_repositories``: the n-th entity
    goes with the n-th repository.
    """
    from minix.core.repository import SqlRepository

    if modules is None:
        from minix.core.conf.builders import modules_from_settings

        modules = modules_from_settings()

    tables: dict[str, Table] = {}
    for module in modules:
        for entity, (repository, salt, _provides) in zip(module.entities, module.repositories):
            if not (isinstance(repository, type) and issubclass(repository, SqlRepository)):
                continue
            # Single-table-inheritance extensions resolve to the parent's table.
            table = getattr(entity, "__table__", None)
            if table is not None and _connection_name(salt) == connection:
                tables[table.name] = table
    return tables


def version_table(connection: str) -> str:
    """Alembic's revision table; distinct per connection in case two share a database."""
    return "alembic_version" if connection == "default" else f"alembic_version_{connection}"
