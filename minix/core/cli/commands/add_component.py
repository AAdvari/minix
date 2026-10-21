"""``minix add <component> [NAME] --module=MODULE`` — add a piece to an existing module.

    minix add controller --module=orders
    minix add task ShipOrder -m orders
    minix add binding -m orders --entity=ShopOrder
"""

from __future__ import annotations

from typing import Optional

import typer

from minix.core.cli.commands.add_component_scaffold import add_component

_MODULE_HELP = "Existing module name in snake_case (src/modules/<name>/)."
_PATH_HELP = "Module package directory (default: src/modules/<name>)."
_FORCE_HELP = "Overwrite the component file if it already exists."


def _run(kind: str, module_name: str, path: str | None, names: dict, force: bool) -> None:
    try:
        spec, wired = add_component(
            kind,
            module_name=module_name,
            path=path,
            names=names,
            force=force,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Module `{spec.module_name}` → {spec.package_path}/ (added {kind})")
    if spec.created:
        typer.echo(f"  wrote: {', '.join(spec.created)}")
    if spec.skipped:
        typer.echo(f"  skipped (exists): {', '.join(spec.skipped)}")
    typer.echo(f"  {wired}")


def _single(
    kind: str, label: str, add_method: str, default_example: str, custom_example: str
):
    def command(
        name: Optional[str] = typer.Argument(
            None,
            metavar="[NAME]",
            help=f"Custom class name (default: {default_example}).",
            show_default=False,
        ),
        module_name: str = typer.Option(..., "--module", "-m", help=_MODULE_HELP),
        path: Optional[str] = typer.Option(None, "--path", help=_PATH_HELP),
        force: bool = typer.Option(False, "--force", "-f", help=_FORCE_HELP),
    ):
        _run(kind, module_name, path, {kind: name}, force)

    command.__doc__ = (
        f"Add a {label} to an existing module (wired via `.{add_method}(...)`).\n\n"
        f"    minix add {kind} --module=orders\n\n"
        f"    minix add {kind} {custom_example} -m orders"
    )
    return command


def binding(
    module_name: str = typer.Option(..., "--module", "-m", help=_MODULE_HELP),
    entity: Optional[str] = typer.Option(
        None, "--entity", "-e", help="Entity class name (default: Order for orders)."
    ),
    repository: Optional[str] = typer.Option(
        None,
        "--repository",
        "-r",
        help="Repository class name (default: OrderSqlRepository).",
    ),
    service: Optional[str] = typer.Option(
        None, "--service", "-s", help="Service class name (default: OrderSqlService)."
    ),
    path: Optional[str] = typer.Option(None, "--path", help=_PATH_HELP),
    force: bool = typer.Option(False, "--force", "-f", help=_FORCE_HELP),
):
    """
    Add a SQL binding (entity + repository + service) to an existing module.

    Wired via `.add_binding(Entity, Repository, Service)`.

        minix add binding --module=orders

        minix add binding -m orders --entity=ShopOrder
    """
    _run(
        "binding",
        module_name,
        path,
        {"entity": entity, "repository": repository, "service": service},
        force,
    )


def register(add_app: typer.Typer) -> None:
    add_app.command("controller")(
        _single("controller", "controller", "add_controller", "OrderController", "OrderAdminController")
    )
    add_app.command("task")(_single("task", "Celery task", "add_task", "OrderTask", "ShipOrder"))
    add_app.command("periodic")(
        _single("periodic", "periodic task", "add_periodic_task", "OrderPeriodicTask", "HourlySync")
    )
    add_app.command("helper")(
        _single("helper", "helper service", "add_helper_service", "OrderHelperService", "PricingHelper")
    )
    add_app.command("consumer")(
        _single("consumer", "Kafka consumer", "add_consumer", "OrderConsumer", "OrderEventsConsumer")
    )
    add_app.command("binding")(binding)
