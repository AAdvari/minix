"""``minix add module`` — scaffold a feature module."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from minix.core.cli.commands.add_module_scaffold import (
    _DEFAULT_COMPONENT,
    build_spec,
    register_in_config,
    write_module,
)

_FLAG = _DEFAULT_COMPONENT


def _long_name_option(*flags: str, help_text: str):
    """Long option with optional ``=value`` (e.g. ``--controller[=name]``).

    Use ``--controller`` or ``--controller=OrderController``.
    Do **not** pass a following separate token as the value (Click may steal
    the next flag). Short flags are separate booleans (``-c``, ``-t``, …).
    """
    return typer.Option(
        None,
        *flags,
        help=help_text,
        flag_value=_FLAG,
        show_default=False,
    )


def _merge(long_opt: str | None, short_flag: bool) -> str | None:
    """Combine ``--foo`` / ``--foo=Name`` with short ``-f`` presence."""
    if long_opt is not None:
        return long_opt
    if short_flag:
        return _FLAG
    return None


def module(
    name: str = typer.Argument(
        ...,
        help="Module name in snake_case (package under src/modules/<name>/).",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        help="Package directory (default: src/modules/<name>).",
    ),
    # Long form: --entity / --entity=Order
    entity: Optional[str] = _long_name_option(
        "--entity",
        help_text=(
            "SQL binding entity class (on by default with repository + service). "
            "Optional: --entity=Order."
        ),
    ),
    repository: Optional[str] = _long_name_option(
        "--repository",
        help_text=(
            "SQL binding repository class (on by default with entity + service). "
            "Optional: --repository=OrderSqlRepository."
        ),
    ),
    service: Optional[str] = _long_name_option(
        "--service",
        help_text=(
            "SQL binding service class (on by default with entity + repository). "
            "Optional: --service=OrderSqlService."
        ),
    ),
    controller: Optional[str] = _long_name_option(
        "--controller",
        help_text=(
            "Include controller (on by default). Optional: --controller=OrderController."
        ),
    ),
    task: Optional[str] = _long_name_option(
        "--task",
        help_text="Also scaffold an async Celery Task. Optional: --task=ProcessOrder.",
    ),
    helper: Optional[str] = _long_name_option(
        "--helper",
        help_text="Also scaffold a HelperService. Optional: --helper=OrderHelper.",
    ),
    consumer: Optional[str] = _long_name_option(
        "--consumer",
        help_text="Also scaffold a Kafka AsyncConsumer. Optional: --consumer=OrderConsumer.",
    ),
    periodic: Optional[str] = _long_name_option(
        "--periodic",
        help_text="Also scaffold a PeriodicTask. Optional: --periodic=HourlySync.",
    ),
    # Short flags — presence only (never steal the next token)
    entity_short: bool = typer.Option(
        False,
        "-e",
        help="Include the SQL binding entity (same as --entity; implies full binding).",
    ),
    repository_short: bool = typer.Option(
        False,
        "-r",
        help="Include the SQL binding repository (same as --repository; implies full binding).",
    ),
    service_short: bool = typer.Option(
        False,
        "-s",
        help="Include the SQL binding service (same as --service; implies full binding).",
    ),
    controller_short: bool = typer.Option(
        False, "-c", help="Include controller (same as --controller)."
    ),
    task_short: bool = typer.Option(
        False, "-t", help="Also scaffold a Task (same as --task)."
    ),
    helper_short: bool = typer.Option(
        False, "-H", help="Also scaffold a HelperService (same as --helper)."
    ),
    periodic_short: bool = typer.Option(
        False, "-p", help="Also scaffold a PeriodicTask (same as --periodic)."
    ),
    all_components: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Scaffold everything: default stack + task, helper, consumer, periodic.",
    ),
    no_binding: bool = typer.Option(
        False,
        "--no-binding",
        help=(
            "Skip the SQL binding entirely (entity + repository + service). "
            "These three are always generated together or not at all."
        ),
    ),
    no_controller: bool = typer.Option(
        False, "--no-controller", help="Skip controller."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing files.",
    ),
    register: bool = typer.Option(
        True,
        "--register/--no-register",
        help="Append the module to installed_modules in config.py when present.",
    ),
):
    """
    Scaffold a Minix feature module.

    **Default stack** (most common): entity + repository + service + controller.
    Entity / repository / service are one ``add_binding`` unit — all present or
    none (``--no-binding``).

    **Optional add-ons:** ``-t/--task``, ``-H/--helper``, ``--consumer``,
    ``-p/--periodic``, or ``-a/--all``.

    **Naming:** use ``=`` for optional custom class names on long flags.
    Short flags (``-c``, ``-t``, …) are presence-only and safe next to other flags::

        minix add module orders
        minix add module orders -c
        minix add module orders --controller
        minix add module orders --controller=OrderController
        minix add module orders -t --no-register
        minix add module orders --task=ShipOrder -a
        minix add module orders --no-controller -t
        minix add module orders --no-binding -t
    """
    try:
        spec = build_spec(
            module_name=name,
            path=path,
            entity=_merge(entity, entity_short),
            repository=_merge(repository, repository_short),
            service=_merge(service, service_short),
            controller=_merge(controller, controller_short),
            task=_merge(task, task_short),
            helper=_merge(helper, helper_short),
            consumer=consumer,
            periodic=_merge(periodic, periodic_short),
            all_components=all_components,
            no_binding=no_binding,
            no_controller=no_controller,
            force=force,
            register=register,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if spec.package_path.exists() and any(spec.package_path.iterdir()) and not force:
        typer.echo(
            f"note: {spec.package_path} already exists "
            "(existing files kept; use --force to overwrite)"
        )

    write_module(spec)

    dotted = f"{spec.import_root}.{spec.module_export}"
    reg_msg = None
    if register:
        reg_msg = register_in_config(
            Path.cwd() / "config.py",
            module_import=dotted,
        )

    _print_summary(spec, reg_msg, dotted)


def _print_summary(spec, reg_msg: str | None, dotted: str) -> None:
    parts = []
    if spec.entity_class:
        parts.append(f"entity={spec.entity_class}")
    if spec.repository_class:
        parts.append(f"repository={spec.repository_class}")
    if spec.service_class:
        parts.append(f"service={spec.service_class}")
    if spec.controller_class:
        parts.append(f"controller={spec.controller_class}")
    if spec.task_class:
        parts.append(f"task={spec.task_class}")
    if spec.helper_class:
        parts.append(f"helper={spec.helper_class}")
    if spec.consumer_class:
        parts.append(f"consumer={spec.consumer_class}")
    if spec.periodic_class:
        parts.append(f"periodic={spec.periodic_class}")

    typer.echo(
        f"Module `{spec.module_name}` → {spec.package_path}/ "
        f"({', '.join(parts) or 'empty'})"
    )
    if spec.created:
        typer.echo(f"  wrote: {', '.join(spec.created)}")
    if spec.skipped:
        typer.echo(f"  skipped (exists): {', '.join(spec.skipped)}")

    if reg_msg:
        typer.echo(f"  {reg_msg}")
    elif register:
        typer.echo(
            "  register in config.py installed_modules:\n"
            f'    "{dotted}",'
        )
    else:
        typer.echo(
            f'  skipped config registration; add manually:\n    "{dotted}",'
        )
    typer.echo(f"  import: from {spec.import_root} import {spec.module_export}")


def register(add_app: typer.Typer) -> None:
    add_app.command("module")(module)
