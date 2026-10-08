"""``minix init`` — scaffold a project in the current directory."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from minix.core.cli.commands.init_prompts import (
    primary_sql_driver,
    prompt_sql_drivers,
    sql_driver_defaults,
)
from minix.core.cli.commands.init_scaffold import (
    apply_feature_blocks,
    minix_pip_install_spec,
    resolve_minix_extras,
)

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "conf" / "project_template"
_SETTINGS_MODULE_LINE = "MINIX_SETTINGS_MODULE=config"

_DEFAULT_PORTS = {
    "APP_PORT": 8000,
    "REDIS_PORT": 6379,
    "QDRANT_PORT": 6333,
    "QDRANT_GRPC_PORT": 6334,
    "OBJECT_STORAGE_PORT": 9000,
    "OBJECT_STORAGE_CONSOLE_PORT": 9001,
    "MLFLOW_PORT": 5000,
}

_OPTIONAL_FILES = (
    ".env.example",
    ".gitignore",
    "Dockerfile",
    "docker-compose.yml",
    ".dockerignore",
    "AGENTS.md",
    "entries/__init__.py",
    "entries/api.py",
    "entries/worker.py",
    "entries/beat.py",
)

_ENV_EXAMPLE_HEADER = (
    "# Copy to `.env` and adjust. Values fall back to defaults in config.py.\n\n"
)


def _port_option(name: str, default: int | None, help_text: str):
    return typer.Option(
        default,
        f"--{name.replace('_', '-').lower()}",
        min=1,
        max=65535,
        help=help_text,
    )


def _ensure_settings_module(env_path: Path) -> bool:
    """Append MINIX_SETTINGS_MODULE if missing. Returns True when modified."""
    text = env_path.read_text()
    if "MINIX_SETTINGS_MODULE=" in text:
        return False
    suffix = "" if text.endswith("\n") or not text else "\n"
    env_path.write_text(f"{text}{suffix}\n# Minix config module\n{_SETTINGS_MODULE_LINE}\n")
    return True


def _env_file_content(example_content: str) -> str:
    """``.env`` is the example without the copy-instruction header."""
    if example_content.startswith(_ENV_EXAMPLE_HEADER):
        return example_content[len(_ENV_EXAMPLE_HEADER) :]
    lines = example_content.splitlines(keepends=True)
    if lines and lines[0].lstrip().startswith("# Copy to"):
        rest = lines[1:]
        if rest and rest[0].strip() == "":
            rest = rest[1:]
        return "".join(rest)
    return example_content


def _write_if_missing(root: Path, relative: str, content: str, created: list[str]) -> None:
    dest = root / relative
    if dest.exists():
        typer.echo(f"kept existing {relative}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)
    created.append(relative)


def _sql_features(drivers: list[str]) -> set[str]:
    """Template feature flags for selected SQL engines (+ secondary connection)."""
    features = set(drivers)
    primary = primary_sql_driver(drivers)
    for driver in drivers:
        if driver != primary:
            features.add(f"{driver}_secondary")
    return features


def _render(
    content: str,
    *,
    app_name: str,
    ports: dict[str, int],
    features: set[str],
    placeholders: dict[str, str],
) -> str:
    rendered = apply_feature_blocks(content, features)
    rendered = rendered.replace("my_project", app_name)
    rendered = rendered.replace("__MINIX_PIP_SPEC__", minix_pip_install_spec(features))
    for key, value in placeholders.items():
        rendered = rendered.replace(f"__{key}__", value)
    for key, value in ports.items():
        rendered = rendered.replace(f"__{key}__", str(value))
    app_port = ports.get("APP_PORT")
    if app_port is not None and "\nEXPOSE 8000\n" in rendered:
        rendered = rendered.replace("\nEXPOSE 8000\n", f"\nEXPOSE {app_port}\n", 1)
    return rendered


def init(
    app_name: str = typer.Argument(
        ...,
        help="Application name written to APP_NAME in config and .env.",
    ),
    app_port: int = _port_option(
        "APP_PORT",
        _DEFAULT_PORTS["APP_PORT"],
        "Host/container port for the API (Dockerfile EXPOSE, compose app service).",
    ),
    db_driver: Optional[str] = typer.Option(
        None,
        "--db-driver",
        help=(
            "SQL database(s), comma-separated: postgresql (recommended) and/or mysql. "
            "Prompted interactively if omitted."
        ),
    ),
    db_port: Optional[int] = _port_option(
        "DB_PORT",
        None,
        "Host port for the primary SQL database "
        "(default: 5432 for PostgreSQL, 3306 for MySQL).",
    ),
    redis_port: int = _port_option(
        "REDIS_PORT",
        _DEFAULT_PORTS["REDIS_PORT"],
        "Host port mapped to Redis (container stays on 6379).",
    ),
    qdrant_port: int = _port_option(
        "QDRANT_PORT",
        _DEFAULT_PORTS["QDRANT_PORT"],
        "Host port mapped to Qdrant HTTP (container stays on 6333).",
    ),
    qdrant_grpc_port: int = _port_option(
        "QDRANT_GRPC_PORT",
        _DEFAULT_PORTS["QDRANT_GRPC_PORT"],
        "Host port mapped to Qdrant gRPC (container stays on 6334).",
    ),
    object_storage_port: int = _port_option(
        "OBJECT_STORAGE_PORT",
        _DEFAULT_PORTS["OBJECT_STORAGE_PORT"],
        "Host port mapped to MinIO API (container stays on 9000).",
    ),
    object_storage_console_port: int = _port_option(
        "OBJECT_STORAGE_CONSOLE_PORT",
        _DEFAULT_PORTS["OBJECT_STORAGE_CONSOLE_PORT"],
        "Host port mapped to MinIO console (container stays on 9001).",
    ),
    extras: str | None = typer.Option(
        None,
        "--extras",
        help=(
            "Comma-separated Minix PyPI extras for Docker and compose "
            "(postgresql, mysql, vdb, clickhouse, ai). "
            "SQL extras are also set from --db-driver / the SQL prompt. "
            "Default for non-SQL extras: infer from this environment."
        ),
    ),
    no_extras: bool = typer.Option(
        False,
        "--no-extras",
        help="Skip auto-detected non-SQL extras (SQL extras from --db-driver still apply).",
    ),
):
    """
    Scaffold a Minix project in the current directory.

    Usage::

        minix init APP_NAME

    Asks which SQL database(s) to use (PostgreSQL recommended/default; multi-select
    allowed), then creates ``config.py``, ``.env``, Docker files, and ``entries/``.
    Only the selected SQL driver extras are installed in Docker
    (``minix[postgresql]``, ``minix[mysql]``, or both).
    """
    root = Path.cwd()
    if (root / "config.py").exists() or (root / "settings.py").exists():
        typer.echo("config.py or settings.py already exists", err=True)
        raise typer.Exit(code=1)

    try:
        minix_extras = resolve_minix_extras(no_extras=no_extras, extras_option=extras)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    # SQL engines come from the prompt / --db-driver, not from ambient installs.
    minix_extras -= {"postgresql", "mysql"}

    drivers = prompt_sql_drivers(explicit=db_driver)
    primary = primary_sql_driver(drivers)
    primary_meta = sql_driver_defaults(primary)
    resolved_db_port = int(db_port if db_port is not None else primary_meta["port"])

    sql_features = _sql_features(drivers)
    features = set(minix_extras) | sql_features

    ports = {
        "APP_PORT": app_port,
        "DB_PORT": resolved_db_port,
        "REDIS_PORT": redis_port,
        "QDRANT_PORT": qdrant_port,
        "QDRANT_GRPC_PORT": qdrant_grpc_port,
        "OBJECT_STORAGE_PORT": object_storage_port,
        "OBJECT_STORAGE_CONSOLE_PORT": object_storage_console_port,
        "MLFLOW_PORT": _DEFAULT_PORTS["MLFLOW_PORT"],
    }

    placeholders = {
        "DB_DRIVER": primary,
        "DB_USER": str(primary_meta["user"]),
        "DB_SERVICE": str(primary_meta["service"]),
        "POSTGRES_PORT": str(
            resolved_db_port if primary == "postgresql" else sql_driver_defaults("postgresql")["port"]
        ),
        "POSTGRES_USER": "minix",
        "MYSQL_PORT": str(
            resolved_db_port if primary == "mysql" else sql_driver_defaults("mysql")["port"]
        ),
        "MYSQL_USER": "minix",
    }

    render_kw = dict(
        app_name=app_name,
        ports=ports,
        features=features,
        placeholders=placeholders,
    )

    config = _render((_TEMPLATE_DIR / "config.py").read_text(), **render_kw)
    env_example = _render((_TEMPLATE_DIR / ".env.example").read_text(), **render_kw)
    env = _env_file_content(env_example)

    (root / "config.py").write_text(config)
    created = ["config.py"]

    env_path = root / ".env"
    if env_path.exists():
        if _ensure_settings_module(env_path):
            typer.echo("kept existing .env (added MINIX_SETTINGS_MODULE)")
        else:
            typer.echo("kept existing .env")
    else:
        env_path.write_text(env)
        created.append(".env")

    for relative in _OPTIONAL_FILES:
        content = _render(
            (_TEMPLATE_DIR / relative).read_text(),
            **render_kw,
        )
        _write_if_missing(root, relative, content, created)

    port_summary = ", ".join(f"{k}={v}" for k, v in ports.items())
    extras_label = minix_pip_install_spec(features)
    db_label = "+".join(drivers)
    typer.echo(
        f"Initialized (APP_NAME={app_name}; db={db_label}; primary={primary}; "
        f"pip={extras_label}; {port_summary}); wrote: {', '.join(created)}"
    )
