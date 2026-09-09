"""``minix init`` — scaffold a project in the current directory."""

from pathlib import Path

import typer

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "conf" / "project_template"


def init(
    app_name: str = typer.Argument(
        "my_project",
        help="Application name written to APP_NAME in settings and .env.",
    ),
):
    """
    Scaffold a Minix project in the current directory.

    Creates settings.py, .env, .env.example, and .gitignore.
    Does nothing if settings.py already exists.
    """
    root = Path.cwd()
    if (root / "settings.py").exists():
        typer.echo("settings.py already exists", err=True)
        raise typer.Exit(code=1)

    settings = (_TEMPLATE_DIR / "settings.py").read_text().replace("my_project", app_name)
    env = (_TEMPLATE_DIR / ".env.example").read_text().replace("my_project", app_name)

    (root / "settings.py").write_text(settings)
    (root / ".env.example").write_text(env)
    (root / ".env").write_text(env)
    (root / ".gitignore").write_text((_TEMPLATE_DIR / ".gitignore").read_text())

    typer.echo(f"Initialized (APP_NAME={app_name})")
