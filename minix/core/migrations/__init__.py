"""Alembic migrations for the SQL entities of the installed modules.

``minix db init`` writes ``migrations/<connection>/`` with an ``env.py`` that
calls :func:`run_migrations`; ``minix db makemigrations`` and ``minix db migrate``
drive Alembic through it. Each ``settings.DATABASES`` connection gets its own
directory and manages only the tables of the entities bound to it.
"""

from minix.core.migrations.env import run_migrations
from minix.core.migrations.targets import (
    MIGRATABLE_DRIVERS,
    connection_tables,
    version_table,
)

__all__ = [
    "MIGRATABLE_DRIVERS",
    "connection_tables",
    "run_migrations",
    "version_table",
]
