"""Shared CLI options."""

import typer


def version_callback(value: bool) -> None:
    if not value:
        return
    try:
        from importlib.metadata import version as pkg_version

        typer.echo(f"Minix version: {pkg_version('minix')}")
    except Exception:
        typer.echo("Minix version: unknown")
    raise typer.Exit()


version_option = typer.Option(
    False,
    "--version",
    "-v",
    help="Show the framework version and exit.",
    callback=version_callback,
    is_eager=True,
)
