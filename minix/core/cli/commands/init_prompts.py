"""Interactive prompts for ``minix init``."""

from __future__ import annotations

import sys

import typer

# Canonical driver → compose/pip feature name / defaults.
SQL_DRIVERS: dict[str, dict[str, object]] = {
    "postgresql": {
        "label": "postgresql",
        "feature": "postgresql",
        "service": "postgres",
        "port": 5432,
        "user": "minix",
        "recommended": True,
        "pip_extra": "postgresql",
    },
    "mysql": {
        "label": "mysql",
        "feature": "mysql",
        "service": "mysql",
        "port": 3306,
        "user": "minix",
        "recommended": False,
        "pip_extra": "mysql",
    },
}

_DEFAULT_SQL_DRIVERS = ("postgresql",)


def normalize_sql_driver(value: str) -> str:
    key = value.strip().lower()
    aliases = {
        "postgresql": "postgresql",
        "postgres": "postgresql",
        "pgsql": "postgresql",
        "1": "postgresql",
        "mysql": "mysql",
        "2": "mysql",
    }
    if key not in aliases:
        allowed = ", ".join(SQL_DRIVERS)
        raise ValueError(f"Unknown SQL database {value!r}. Choose from: {allowed}.")
    return aliases[key]


def parse_sql_drivers(value: str) -> list[str]:
    """Parse ``postgresql``, ``1,2``, or ``postgresql,mysql`` into unique drivers."""
    parts = [p.strip() for p in value.replace(" ", ",").split(",") if p.strip()]
    if not parts:
        raise ValueError("Select at least one SQL database.")
    drivers: list[str] = []
    for part in parts:
        driver = normalize_sql_driver(part)
        if driver not in drivers:
            drivers.append(driver)
    return drivers


def prompt_sql_drivers(*, explicit: str | None = None) -> list[str]:
    """Ask which SQL database(s) to use; PostgreSQL is recommended/default.

    Multi-select via comma-separated choices (e.g. ``1`` or ``1,2``).
    """
    if explicit is not None:
        try:
            return parse_sql_drivers(explicit)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

    if not sys.stdin.isatty():
        return list(_DEFAULT_SQL_DRIVERS)

    typer.echo("")
    typer.echo("Which SQL database(s) do you want? (comma-separated for multiple)")
    typer.echo("  1) postgresql  (recommended) [default]")
    typer.echo("  2) mysql")
    typer.echo("Examples: 1   |   2   |   1,2")
    raw = typer.prompt("Choice", default="1")
    try:
        return parse_sql_drivers(raw)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def sql_driver_defaults(driver: str) -> dict[str, object]:
    return dict(SQL_DRIVERS[normalize_sql_driver(driver)])


def primary_sql_driver(drivers: list[str]) -> str:
    """Prefer postgresql when selected; otherwise the first choice."""
    if "postgresql" in drivers:
        return "postgresql"
    return drivers[0]
