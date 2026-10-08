"""CLI command modules. Add new commands here and register them in ``register``."""

from __future__ import annotations

import typer

from minix.core.cli.commands import add_module as add_module_cmd
from minix.core.cli.commands import init as init_cmd


def register(app: typer.Typer) -> None:
    app.command("init")(init_cmd.init)

    add_app = typer.Typer(
        help="Scaffold feature modules.\n\n  minix add module MODULE_NAME [options]",
        no_args_is_help=True,
    )
    add_module_cmd.register(add_app)
    app.add_typer(add_app, name="add")
