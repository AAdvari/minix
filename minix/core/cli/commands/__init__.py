"""CLI command modules. Add new commands here and register them in ``register``."""

from __future__ import annotations

import typer

from minix.core.cli.commands import init as init_cmd


def register(app: typer.Typer) -> None:
    app.command()(init_cmd.init)
