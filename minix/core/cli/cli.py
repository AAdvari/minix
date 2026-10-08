"""Minix CLI entrypoint."""

import typer

from minix.core.cli.commands import register
from minix.core.cli.options import version_option

app = typer.Typer(
    name="minix",
    help="Minix framework CLI.",
    no_args_is_help=True,
)


@app.callback()
def main(
    version: bool = version_option,
):
    """Minix framework CLI."""


register(app)


if __name__ == "__main__":
    app()
