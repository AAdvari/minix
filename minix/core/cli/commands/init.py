"""``minix init`` — scaffold a project in the current directory."""

from __future__ import annotations

from pathlib import Path

import typer

from minix.core.cli.commands.init_scaffold import (
    apply_feature_blocks,
    minix_pip_install_spec,
    resolve_minix_extras,
)

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "conf" / "project_template"
_SETTINGS_MODULE_LINE = "MINIX_SETTINGS_MODULE=config"

_DEFAULT_PORTS = {
    "APP_PORT": 8000,
    "DB_PORT": 3306,
    "REDIS_PORT": 6379,
    "QDRANT_PORT": 6333,
    "QDRANT_GRPC_PORT": 6334,
    "OBJECT_STORAGE_PORT": 9000,
    "OBJECT_STORAGE_CONSOLE_PORT": 9001,
    "MLFLOW_PORT": 5000,
}

# Relative paths under the template dir → destination under the project root.
_OPTIONAL_FILES = (
    ".env.example",
    ".gitignore",
    "Dockerfile",
    "docker-compose.yml",
    ".dockerignore",
    "entries/__init__.py",
    "entries/api.py",
    "entries/worker.py",
    "entries/beat.py",
)


_ENV_EXAMPLE_HEADER = (
    "# Copy to `.env` and adjust. Values fall back to defaults in config.py.\n\n"
)


def _port_option(name: str, default: int, help_text: str):
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
    # Fallback: drop a leading "# Copy to..." line if present.
    lines = example_content.splitlines(keepends=True)
    if lines and lines[0].lstrip().startswith("# Copy to"):
        # Also drop the blank line that usually follows the header.
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


def _render(
    content: str,
    *,
    app_name: str,
    ports: dict[str, int],
    extras: set[str],
) -> str:
    rendered = apply_feature_blocks(content, extras)
    rendered = rendered.replace("my_project", app_name)
    rendered = rendered.replace("__MINIX_PIP_SPEC__", minix_pip_install_spec(extras))
    for key, value in ports.items():
        rendered = rendered.replace(f"__{key}__", str(value))
    # Dockerfile uses a literal EXPOSE 8000 so IDE validators accept the
    # template; bake the chosen APP_PORT when scaffolding.
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
    db_port: int = _port_option(
        "DB_PORT",
        _DEFAULT_PORTS["DB_PORT"],
        "Host port mapped to MySQL (container stays on 3306).",
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
            "(vdb, clickhouse, ai). Default: infer from packages installed "
            "in this environment."
        ),
    ),
    no_extras: bool = typer.Option(
        False,
        "--no-extras",
        help="Minimal scaffold: base minix only, no optional compose services.",
    ),
):
    """
    Scaffold a Minix project in the current directory.

    Usage::

        minix init APP_NAME

    Creates ``config.py`` (pydantic settings), ``.env``, ``.env.example``,
    ``.gitignore``, ``Dockerfile``, ``docker-compose.yml``, ``.dockerignore``,
    and ``entries/`` process entrypoints. Optional ``--*-port`` flags bake
    defaults into Docker / env files. Docker install spec and optional services
    follow detected or explicit Minix extras (``[vdb]``, ``[clickhouse]``,
    ``[ai]``). Existing optional files are left intact (``.env`` only gains
    ``MINIX_SETTINGS_MODULE`` when missing).
    Does nothing if ``config.py`` or ``settings.py`` already exists.
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

    ports = {
        "APP_PORT": app_port,
        "DB_PORT": db_port,
        "REDIS_PORT": redis_port,
        "QDRANT_PORT": qdrant_port,
        "QDRANT_GRPC_PORT": qdrant_grpc_port,
        "OBJECT_STORAGE_PORT": object_storage_port,
        "OBJECT_STORAGE_CONSOLE_PORT": object_storage_console_port,
        "MLFLOW_PORT": _DEFAULT_PORTS["MLFLOW_PORT"],
    }

    render_kw = dict(app_name=app_name, ports=ports, extras=minix_extras)

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
    extras_label = minix_pip_install_spec(minix_extras)
    typer.echo(
        f"Initialized (APP_NAME={app_name}; pip={extras_label}; {port_summary}); "
        f"wrote: {', '.join(created)}"
    )
