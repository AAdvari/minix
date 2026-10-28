"""Files ``minix db init`` writes for one connection."""

from __future__ import annotations

from pathlib import Path

MIGRATIONS_DIR = "migrations"

_ALEMBIC_INI = """\
# Alembic settings for the "{connection}" connection; `minix db` reads this file.
# Plain Alembic works too: alembic -c migrations/{connection}/alembic.ini history
[alembic]
script_location = %(here)s

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
"""

_ENV_PY = """\
from pathlib import Path

from minix.core.migrations import run_migrations

run_migrations({connection!r}, project_root=Path(__file__).resolve().parents[2])
"""

_SCRIPT_MAKO = '''\
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
'''


def connection_dir(root: Path, connection: str) -> Path:
    return root / MIGRATIONS_DIR / connection


def initialized_connections(root: Path) -> list[str]:
    base = root / MIGRATIONS_DIR
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "alembic.ini").is_file())


def scaffold_connection(root: Path, connection: str) -> list[str]:
    """Write the migration files for ``connection``; keeps files that exist.

    Returns the paths written, relative to ``root``.
    """
    directory = connection_dir(root, connection)
    files = {
        directory / "alembic.ini": _ALEMBIC_INI.format(connection=connection),
        directory / "env.py": _ENV_PY.format(connection=connection),
        directory / "script.py.mako": _SCRIPT_MAKO,
        directory / "versions" / ".gitkeep": "",
    }
    written = []
    for path, content in files.items():
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        written.append(str(path.relative_to(root)))
    return written
