"""``minix db`` — Alembic migrations for the installed modules' SQL tables.

    minix db init
    minix db makemigrations -m "add orders"
    minix db migrate
    minix db downgrade -1
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

from minix.core.migrations.scaffold import (
    connection_dir,
    initialized_connections,
    scaffold_connection,
)
from minix.core.migrations.targets import MIGRATABLE_DRIVERS

_DATABASE_HELP = (
    "settings.DATABASES connection name; repeat for several. "
    "Default: every connection set up with `minix db init`."
)
_INSTALL_HINT = 'Alembic is not installed. Install it with: pip install "minix[postgresql]" (or "minix[mysql]").'


def _fail(message: str) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code=1)


def _project_root() -> Path:
    """The current directory, set up so the project's settings resolve."""
    root = Path.cwd()
    if not (root / "config.py").is_file():
        _fail("No config.py found. Run this command in a Minix project root.")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    load_dotenv(root / ".env")
    return root


def _migratable_connections() -> dict[str, str]:
    """``settings.DATABASES`` names mapped to their normalized driver."""
    from minix.core.conf import settings
    from minix.core.connectors import SqlConnector

    databases = getattr(settings, "DATABASES", None) or {}
    drivers = {}
    for name, cfg in databases.items():
        try:
            drivers[name] = SqlConnector.normalize_driver(cfg.get("driver"))
        except Exception:
            drivers[name] = str(cfg.get("driver"))
    return drivers


def _alembic():
    """Alembic's ``command`` module and ``CommandError``, imported on first use."""
    try:
        from alembic import command
        from alembic.util import CommandError
    except ImportError:
        _fail(_INSTALL_HINT)
    return command, CommandError


def _alembic_config(root: Path, connection: str):
    from alembic.config import Config

    ini = connection_dir(root, connection) / "alembic.ini"
    if not ini.is_file():
        _fail(f"No migrations for {connection!r}. Run: minix db init --database {connection}")
    return Config(str(ini))


def _targets(root: Path, database: list[str] | None) -> list[str]:
    if database:
        return list(dict.fromkeys(database))
    connections = initialized_connections(root)
    if not connections:
        _fail("No migrations set up. Run: minix db init")
    return connections


def init(
    database: Optional[list[str]] = typer.Option(None, "--database", "-d", help=(
        "settings.DATABASES connection name; repeat for several. "
        "Default: every PostgreSQL / MySQL connection."
    )),
):
    """Create migrations/<connection>/ for each SQL connection."""
    root = _project_root()
    drivers = _migratable_connections()
    if database:
        unknown = [name for name in database if name not in drivers]
        if unknown:
            _fail(f"Not in settings.DATABASES: {', '.join(unknown)}")
        targets = list(dict.fromkeys(database))
    else:
        targets = list(drivers)

    written: list[str] = []
    for name in targets:
        if drivers[name] not in MIGRATABLE_DRIVERS:
            typer.echo(f"skipped {name!r} ({drivers[name]}): migrations support PostgreSQL and MySQL only")
            continue
        written += scaffold_connection(root, name)

    if written:
        typer.echo("wrote: " + ", ".join(written))
    else:
        typer.echo("Migrations are already set up.")
    typer.echo('Next: minix db makemigrations -m "initial" && minix db migrate')


def makemigrations(
    message: str = typer.Option("auto", "--message", "-m", help="Revision message."),
    database: Optional[list[str]] = typer.Option(None, "--database", "-d", help=_DATABASE_HELP),
    empty: bool = typer.Option(False, "--empty", help="Write an empty revision to fill in by hand."),
):
    """Generate a revision from changes to the installed modules' SQL entities.

    Compares the entities with the live database, so the database must be
    running and up to date (minix db migrate).
    """
    root = _project_root()
    command, CommandError = _alembic()
    for name in _targets(root, database):
        config = _alembic_config(root, name)
        config.attributes["minix_skip_empty"] = not empty
        try:
            script = command.revision(config, message=message, autogenerate=not empty)
        except CommandError as exc:
            hint = " Run: minix db migrate" if "not up to date" in str(exc) else ""
            _fail(f"{name}: {exc}.{hint}")
        if not script:
            typer.echo(f"{name}: no changes detected")
        else:
            typer.echo(f"{name}: wrote {Path(script.path).relative_to(root)}")


def migrate(
    revision: str = typer.Argument("head", help="Target revision (default: head)."),
    database: Optional[list[str]] = typer.Option(None, "--database", "-d", help=_DATABASE_HELP),
):
    """Apply migrations up to REVISION; use `minix db downgrade` to go back."""
    root = _project_root()
    command, CommandError = _alembic()
    for name in _targets(root, database):
        config = _alembic_config(root, name)
        try:
            command.upgrade(config, revision)
        except CommandError as exc:
            _fail(f"{name}: {exc}")
        typer.echo(f"{name}: migrated to {revision}")


def downgrade(
    revision: str = typer.Argument(..., help="Target revision: an id, -1 for one step, or base for none."),
    database: Optional[list[str]] = typer.Option(None, "--database", "-d", help=_DATABASE_HELP),
):
    """Revert migrations down to REVISION."""
    root = _project_root()
    command, CommandError = _alembic()
    for name in _targets(root, database):
        config = _alembic_config(root, name)
        try:
            command.downgrade(config, revision)
        except CommandError as exc:
            _fail(f"{name}: {exc}")
        typer.echo(f"{name}: downgraded to {revision}")


# Alembic commands `minix db` forwards as-is; init/revision/upgrade/downgrade have
# their own commands above.
_PASSTHROUGH = {
    "current": "Show the revision the database is at.",
    "history": "List the migrations.",
    "heads": "Show the latest revision(s).",
    "branches": "Show where migration history splits.",
    "show": "Show one revision.",
    "check": "Fail if the entities have changes without a migration.",
    "stamp": "Set the database revision without running migrations.",
    "merge": "Merge two heads into one revision.",
    "edit": "Open a revision in $EDITOR.",
}


def _passthrough(name: str):
    def command(
        ctx: typer.Context,
        database: Optional[list[str]] = typer.Option(None, "--database", "-d", help=_DATABASE_HELP),
    ):
        root = _project_root()
        _alembic()
        from alembic.config import CommandLine, Config

        cli = CommandLine(prog="minix db")
        options = cli.parser.parse_args([name, *ctx.args])
        targets = _targets(root, database)
        for connection in targets:
            ini = _alembic_config(root, connection).config_file_name
            if len(targets) > 1:
                typer.echo(f"== {connection} ==")
            # Config's default stdout is bound when Alembic is imported; pass the live one.
            cli.run_cmd(Config(ini, cmd_opts=options, stdout=sys.stdout), options)

    command.__doc__ = (
        f"{_PASSTHROUGH[name]}\n\nRuns `alembic {name}`; other options go to Alembic "
        f"(minix db {name} --help)."
    )
    return command


def register(app: typer.Typer) -> None:
    db_app = typer.Typer(
        help=(
            "Database migrations (Alembic) for the installed modules' SQL tables.\n\n"
            "  minix db init\n\n"
            '  minix db makemigrations -m "message"\n\n'
            "  minix db migrate [REVISION]\n\n"
            "  minix db downgrade REVISION\n\n"
            "Alembic's current, history, heads, branches, show, check, stamp, "
            "merge and edit run as minix db <command>."
        ),
        no_args_is_help=True,
    )
    db_app.command("init")(init)
    db_app.command("makemigrations")(makemigrations)
    db_app.command("migrate")(migrate)
    # Lets `minix db downgrade -1` read -1 as the revision, not an option.
    db_app.command("downgrade", context_settings={"ignore_unknown_options": True})(downgrade)
    for name in _PASSTHROUGH:
        db_app.command(
            name,
            # --help and every unknown option reach Alembic untouched.
            add_help_option=False,
            context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
        )(_passthrough(name))
    app.add_typer(db_app, name="db")
