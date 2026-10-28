"""CLI command modules. Add new commands here and register them in ``register``."""

from __future__ import annotations

import typer

from minix.core.cli.commands import add_component as add_component_cmd
from minix.core.cli.commands import add_module as add_module_cmd
from minix.core.cli.commands import add_rag as add_rag_cmd
from minix.core.cli.commands import db as db_cmd
from minix.core.cli.commands import init as init_cmd


def register(app: typer.Typer) -> None:
    app.command("init")(init_cmd.init)
    db_cmd.register(app)

    add_app = typer.Typer(
        help=(
            "Enable built-in RAG, scaffold feature modules, or add pieces to an existing one.\n\n"
            "  minix add rag\n\n"
            "  minix add module MODULE_NAME [options]\n\n"
            "  minix add controller|task|periodic|helper|consumer|binding [NAME] --module=MODULE"
        ),
        no_args_is_help=True,
    )
    add_module_cmd.register(add_app)
    add_app.command("rag")(add_rag_cmd.rag)
    add_component_cmd.register(add_app)
    app.add_typer(add_app, name="add")
