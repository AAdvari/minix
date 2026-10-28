"""The body of a generated ``migrations/<connection>/env.py``."""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv

from minix.core.migrations.targets import MIGRATABLE_DRIVERS, connection_tables, version_table


def _drop_enum_types(downgrade_ops) -> None:
    """Drop the PostgreSQL enum types of the tables a downgrade drops.

    Autogenerate creates them with the table but never drops them, so a
    downgrade followed by an upgrade fails with "type ... already exists".
    The drops go last because one enum type may back columns of several tables.
    """
    from alembic.operations import ops
    from sqlalchemy import Enum

    names: list[str] = []
    for op in downgrade_ops.ops:
        if not isinstance(op, ops.DropTableOp):
            continue
        for column in op.to_table().columns:
            name = getattr(column.type, "name", None)
            if isinstance(column.type, Enum) and name and name not in names:
                names.append(name)
    downgrade_ops.ops.extend(ops.ExecuteSQLOp(f'DROP TYPE IF EXISTS "{name}"') for name in names)


def run_migrations(connection: str = "default", project_root: str | Path | None = None) -> None:
    """Run Alembic for one connection; call it from ``env.py``.

    Loads the project's ``.env`` and ``config.py`` from ``project_root`` so plain
    ``alembic -c migrations/<connection>/alembic.ini ...`` works too. Only tables
    of entities bound to ``connection`` are compared, so autogenerate never
    proposes dropping tables it does not own.
    """
    from alembic import context

    if project_root is not None:
        root = str(Path(project_root).resolve())
        if root not in sys.path:
            sys.path.insert(0, root)
        load_dotenv(Path(root) / ".env")

    from minix.core.connectors import SqlConnector
    from minix.core.entity.sql_entity import Base

    connector = SqlConnector(connection=connection)
    if connector.driver not in MIGRATABLE_DRIVERS:
        raise RuntimeError(
            f"Connection {connection!r} uses {connector.driver}; migrations support "
            f"{', '.join(sorted(MIGRATABLE_DRIVERS))} only."
        )
    tables = connection_tables(connection)
    engine = connector.get_engine()

    config = context.config
    # After the modules are imported: some of their dependencies reset logging.
    if config.config_file_name is not None:
        fileConfig(config.config_file_name, disable_existing_loggers=False)

    def include_object(obj, name, type_, reflected, compare_to):
        if type_ == "table":
            return name in tables
        return True

    def process_revision_directives(migration_context, revision, directives):
        script = directives[0]
        # `minix db makemigrations` writes nothing when there is nothing to do.
        if config.attributes.get("minix_skip_empty") and script.upgrade_ops.is_empty():
            directives[:] = []
            return
        if migration_context.dialect.name == "postgresql":
            _drop_enum_types(script.downgrade_ops)

    options = dict(
        target_metadata=Base.metadata,
        include_object=include_object,
        process_revision_directives=process_revision_directives,
        version_table=version_table(connection),
        compare_type=True,
    )
    if context.is_offline_mode():
        context.configure(
            url=engine.url.render_as_string(hide_password=False),
            literal_binds=True,
            **options,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    with engine.connect() as conn:
        context.configure(connection=conn, **options)
        with context.begin_transaction():
            context.run_migrations()
