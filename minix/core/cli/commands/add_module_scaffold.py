"""Scaffold helpers for ``minix add module``."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


_DEFAULT_COMPONENT = "__DEFAULT__"
_SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class ModuleSpec:
    """Resolved names and which pieces to generate."""

    module_name: str  # snake_case package name
    package_path: Path  # e.g. src/modules/orders
    import_root: str  # e.g. src.modules.orders

    entity_class: str | None = None
    entity_file: str | None = None
    table_name: str | None = None

    repository_class: str | None = None
    repository_file: str | None = None

    service_class: str | None = None
    service_file: str | None = None

    controller_class: str | None = None
    controller_file: str | None = None
    route_prefix: str | None = None

    task_class: str | None = None
    task_file: str | None = None
    task_name: str | None = None

    helper_class: str | None = None
    helper_file: str | None = None

    consumer_class: str | None = None
    consumer_file: str | None = None

    periodic_class: str | None = None
    periodic_file: str | None = None
    periodic_task_name: str | None = None

    module_export: str = ""
    force: bool = False
    register: bool = True
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def to_snake(value: str) -> str:
    """Normalize a module or class-ish name to snake_case."""
    value = value.strip().replace("-", "_").replace(" ", "_")
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"__+", "_", value).lower().strip("_")
    return value


def to_pascal(value: str) -> str:
    snake = to_snake(value)
    return "".join(part.capitalize() for part in snake.split("_") if part)


def singularize(snake: str) -> str:
    """Best-effort English singular for resource class names (orders → order)."""
    if snake.endswith("ies") and len(snake) > 3:
        return snake[:-3] + "y"
    if snake.endswith(("sses", "ss", "us", "is")):
        return snake
    if snake.endswith("s") and len(snake) > 1:
        return snake[:-1]
    return snake


def validate_module_name(name: str) -> str:
    snake = to_snake(name)
    if not snake or not _SNAKE_RE.match(snake):
        raise ValueError(
            f"Invalid module name {name!r}. Use snake_case "
            f"(letters, digits, underscores), e.g. orders or job_posts."
        )
    return snake


def resolve_class_name(raw: str | None, default_pascal: str, suffix: str = "") -> str | None:
    """Turn option value into a PascalCase class name.

    ``None`` → omit component.
    ``_DEFAULT_COMPONENT`` / empty → ``default_pascal`` (+ suffix if missing).
    Custom string → PascalCase; append ``suffix`` when not already present.
    """
    if raw is None:
        return None
    if raw in (_DEFAULT_COMPONENT, ""):
        name = default_pascal
    else:
        name = to_pascal(raw)
    if suffix and not name.endswith(suffix):
        name = f"{name}{suffix}"
    if not _IDENT_RE.match(name):
        raise ValueError(f"Invalid class name: {name!r}")
    return name


def file_stem_for_class(class_name: str, strip_suffix: str, file_suffix: str) -> str:
    """``OrderController`` + strip Controller + ``_controller`` → ``order_controller``."""
    base = class_name
    if strip_suffix and base.endswith(strip_suffix):
        base = base[: -len(strip_suffix)]
    return f"{to_snake(base)}{file_suffix}"


def build_spec(
    *,
    module_name: str,
    path: str | None,
    entity: str | None,
    repository: str | None,
    service: str | None,
    controller: str | None,
    task: str | None,
    helper: str | None,
    consumer: str | None,
    periodic: str | None,
    all_components: bool,
    no_binding: bool,
    no_controller: bool,
    force: bool,
    register: bool,
) -> ModuleSpec:
    name = validate_module_name(module_name)
    # Package / Module export keep the given name; entity stack uses singular.
    base = to_pascal(singularize(name))
    module_pascal = to_pascal(name)
    package = Path(path) if path else Path("src") / "modules" / name
    import_root = ".".join(package.parts)

    # Entity + repository + service are one binding (add_binding): all or none.
    binding_requested = any(v is not None for v in (entity, repository, service))
    if no_binding and binding_requested:
        raise ValueError(
            "Cannot combine --no-binding with --entity / --repository / --service "
            "(or -e / -r / -s). The SQL binding is all-or-none."
        )
    if no_binding:
        entity = repository = service = None
    else:
        # Defaults fill any missing piece so the binding stays complete.
        if entity is None:
            entity = _DEFAULT_COMPONENT
        if repository is None:
            repository = _DEFAULT_COMPONENT
        if service is None:
            service = _DEFAULT_COMPONENT

    if controller is None and not no_controller:
        controller = _DEFAULT_COMPONENT

    if all_components:
        if task is None:
            task = _DEFAULT_COMPONENT
        if helper is None:
            helper = _DEFAULT_COMPONENT
        if consumer is None:
            consumer = _DEFAULT_COMPONENT
        if periodic is None:
            periodic = _DEFAULT_COMPONENT

    if no_controller:
        controller = None

    entity_class = resolve_class_name(entity, base, "")
    repository_class = _resolve_suffixed(
        repository, default=f"{base}SqlRepository", preferred_suffix="SqlRepository"
    )
    service_class = _resolve_suffixed(
        service, default=f"{base}SqlService", preferred_suffix="SqlService"
    )
    binding = (entity_class, repository_class, service_class)
    if any(binding) and not all(binding):
        raise ValueError(
            "Entity, repository, and service must be generated together "
            "(required by add_binding). Omit --no-binding for the full SQL stack, "
            "or pass --no-binding to skip all three."
        )
    controller_class = resolve_class_name(controller, f"{base}Controller", "Controller")
    task_class = resolve_class_name(task, f"{base}Task", "Task")
    helper_class = _resolve_suffixed(
        helper, default=f"{base}HelperService", preferred_suffix="HelperService"
    )
    consumer_class = resolve_class_name(consumer, f"{base}Consumer", "Consumer")
    periodic_class = resolve_class_name(
        periodic, f"{base}PeriodicTask", "PeriodicTask"
    )

    table = f"{name}s" if not name.endswith("s") else name
    route = f"/{name.replace('_', '-')}"

    def _task_celery_name(cls: str, kind: str) -> str:
        stem = cls
        for suf in ("PeriodicTask", "Task"):
            if stem.endswith(suf):
                stem = stem[: -len(suf)]
                break
        return f"{name}.{to_snake(stem or kind)}"

    return ModuleSpec(
        module_name=name,
        package_path=package,
        import_root=import_root,
        entity_class=entity_class,
        entity_file=(
            file_stem_for_class(entity_class, "Entity", "_entity")
            if entity_class
            else None
        ),
        table_name=table if entity_class else None,
        repository_class=repository_class,
        repository_file=(
            file_stem_for_class(repository_class, "SqlRepository", "_sql_repository")
            if repository_class
            else None
        ),
        service_class=service_class,
        service_file=(
            file_stem_for_class(service_class, "SqlService", "_sql_service")
            if service_class
            else None
        ),
        controller_class=controller_class,
        controller_file=(
            file_stem_for_class(controller_class, "Controller", "_controller")
            if controller_class
            else None
        ),
        route_prefix=route if controller_class else None,
        task_class=task_class,
        task_file=(
            file_stem_for_class(task_class, "Task", "_task") if task_class else None
        ),
        task_name=_task_celery_name(task_class, "task") if task_class else None,
        helper_class=helper_class,
        helper_file=(
            file_stem_for_class(helper_class, "HelperService", "_helper_service")
            if helper_class
            else None
        ),
        consumer_class=consumer_class,
        consumer_file=(
            file_stem_for_class(consumer_class, "Consumer", "_consumer")
            if consumer_class
            else None
        ),
        periodic_class=periodic_class,
        periodic_file=(
            file_stem_for_class(periodic_class, "PeriodicTask", "_periodic_task")
            if periodic_class
            else None
        ),
        periodic_task_name=(
            _task_celery_name(periodic_class, "periodic") if periodic_class else None
        ),
        module_export=f"{module_pascal}Module",
        force=force,
        register=register,
    )


def _resolve_suffixed(
    raw: str | None,
    *,
    default: str,
    preferred_suffix: str,
) -> str | None:
    """Resolve optional class option to a class ending with ``preferred_suffix``."""
    if raw is None:
        return None
    if raw in (_DEFAULT_COMPONENT, ""):
        return default
    name = to_pascal(raw)
    if name.endswith(preferred_suffix):
        return name
    # Accept FooRepository when preferred is SqlRepository, etc.
    short = preferred_suffix.replace("Sql", "").replace("Helper", "")
    if short and name.endswith(short) and not name.endswith(preferred_suffix):
        # e.g. OrderRepository → keep as-is (user was explicit)
        return name
    if name.endswith("Service") or name.endswith("Repository"):
        return name
    return f"{name}{preferred_suffix}"


def _write(path: Path, content: str, spec: ModuleSpec) -> None:
    rel = str(path)
    if path.exists() and not spec.force:
        spec.skipped.append(rel)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if content.endswith("\n") else content + "\n")
    spec.created.append(rel)


def _tpl_entity(spec: ModuleSpec) -> str:
    return f'''from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from minix.core.entity import SqlEntity


class {spec.entity_class}(SqlEntity):
    """SQL entity for the ``{spec.module_name}`` module."""

    __tablename__ = "{spec.table_name}"

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return f"<{spec.entity_class} {{self.id}}>"
'''


def _tpl_repository(spec: ModuleSpec) -> str:
    return f'''from minix.core.repository import SqlRepository

from {spec.import_root}.entities import {spec.entity_class}


class {spec.repository_class}(SqlRepository[{spec.entity_class}]):
    """Data access for :class:`{spec.entity_class}`."""

    pass
'''


def _tpl_service(spec: ModuleSpec) -> str:
    return f'''from minix.core.service import SqlService

from {spec.import_root}.entities import {spec.entity_class}
from {spec.import_root}.repositories import {spec.repository_class}


class {spec.service_class}(SqlService[{spec.entity_class}]):
    """Business logic for :class:`{spec.entity_class}`."""

    def __init__(self, repository: {spec.repository_class}):
        super().__init__(repository)
        self.repository = repository

    def get_repository(self) -> {spec.repository_class}:
        return self.repository
'''


def _tpl_controller(spec: ModuleSpec) -> str:
    if spec.service_class:
        imports = (
            "from minix.core.controller import Controller\n"
            "from minix.core.registry import Registry\n\n"
            f"from {spec.import_root}.services import {spec.service_class}\n"
        )
        list_body = (
            f"        service = Registry().get({spec.service_class})\n"
            f"        return service.get_all()\n"
        )
    else:
        imports = "from minix.core.controller import Controller\n"
        list_body = (
            f'        return {{"module": "{spec.module_name}", "items": []}}\n'
        )
    tag = to_pascal(spec.module_name)
    return f'''{imports}
class {spec.controller_class}(Controller):
    """HTTP API for the ``{spec.module_name}`` module."""

    def get_prefix(self) -> str:
        return "{spec.route_prefix}"

    def list_items(self):
{list_body}
    def define_routes(self):
        self.add_api_route("/", self.list_items, methods=["GET"], tags=["{tag}"])
'''


def _tpl_task(spec: ModuleSpec) -> str:
    return f'''from minix.core.scheduler.task import Task


class {spec.task_class}(Task):
    """Async Celery task for the ``{spec.module_name}`` module."""

    def get_name(self) -> str:
        return "{spec.task_name}"

    def run(self, item_id: int):
        # Resolve services via Registry().get(...) and do work.
        pass
'''


def _tpl_helper(spec: ModuleSpec) -> str:
    return f'''from minix.core.service import HelperService


class {spec.helper_class}(HelperService):
    """Stateless / cross-cutting helper for the ``{spec.module_name}`` module."""

    def run(self):
        pass
'''


def _tpl_consumer(spec: ModuleSpec) -> str:
    return f'''from minix.core.consumer import AsyncConsumer, AsyncConsumerConfig


class {spec.consumer_class}(AsyncConsumer):
    """Kafka consumer for the ``{spec.module_name}`` module."""

    def get_config(self) -> AsyncConsumerConfig:
        return AsyncConsumerConfig(
            name="{spec.module_name}_consumer",
            topics=["{spec.module_name}"],
            group_id="{spec.module_name}_service",
            bootstrap_servers=None,  # falls back to KAFKA_BOOTSTRAP_SERVERS
        )

    async def run(self, message: dict):
        pass
'''


def _tpl_periodic(spec: ModuleSpec) -> str:
    return f'''from celery.schedules import crontab

from minix.core.scheduler.task import PeriodicTask


class {spec.periodic_class}(PeriodicTask):
    """Scheduled Celery task for the ``{spec.module_name}`` module."""

    def get_name(self) -> str:
        return "{spec.periodic_task_name}"

    def get_schedule(self) -> crontab:
        return crontab(minute=0, hour="*")  # hourly — adjust as needed

    def run(self):
        pass
'''


def _tpl_module_py(spec: ModuleSpec) -> str:
    imports: list[str] = ["from minix.core.module import BusinessModule", ""]
    chain = [f'BusinessModule("{spec.module_name}")']

    if spec.entity_class and spec.repository_class and spec.service_class:
        imports.append(f"from {spec.import_root}.entities import {spec.entity_class}")
        imports.append(
            f"from {spec.import_root}.repositories import {spec.repository_class}"
        )
        imports.append(f"from {spec.import_root}.services import {spec.service_class}")
        chain.append(
            f"    .add_binding({spec.entity_class}, {spec.repository_class}, {spec.service_class})"
        )

    if spec.helper_class:
        imports.append(f"from {spec.import_root}.services import {spec.helper_class}")
        chain.append(f"    .add_helper_service({spec.helper_class})")

    if spec.controller_class:
        imports.append(
            f"from {spec.import_root}.controllers import {spec.controller_class}"
        )
        chain.append(f"    .add_controller({spec.controller_class})")

    if spec.task_class:
        imports.append(f"from {spec.import_root}.tasks import {spec.task_class}")
        chain.append(f"    .add_task({spec.task_class})")

    if spec.periodic_class:
        imports.append(f"from {spec.import_root}.tasks import {spec.periodic_class}")
        chain.append(f"    .add_periodic_task({spec.periodic_class})")

    if spec.consumer_class:
        imports.append(f"from {spec.import_root}.consumers import {spec.consumer_class}")
        chain.append(f"    .add_consumer({spec.consumer_class})")

    imports.append("")
    body = "\n".join(imports)
    # First chain line is BusinessModule(...); rest already indented.
    head, *rest = chain
    wired_lines = [f"    {head}"] + list(rest)
    wired = "\n".join(wired_lines)
    return f"""{body}
{spec.module_export} = (
{wired}
)
"""


def _tpl_pkg_init(exports: dict[str, str], package_import: str) -> str:
    """exports: symbol → submodule file stem."""
    lines = [
        f"from {package_import}.{stem} import {symbol}"
        for symbol, stem in exports.items()
    ]
    all_list = ", ".join(f'"{s}"' for s in exports)
    return "\n".join(lines) + f"\n\n__all__ = [{all_list}]\n"


def _tpl_root_init(spec: ModuleSpec) -> str:
    return f'''from {spec.import_root}.module import {spec.module_export}

__all__ = ["{spec.module_export}"]
'''


def write_module(spec: ModuleSpec) -> ModuleSpec:
    root = spec.package_path
    root.mkdir(parents=True, exist_ok=True)

    # entities
    entity_exports: dict[str, str] = {}
    if spec.entity_class and spec.entity_file:
        _write(root / "entities" / f"{spec.entity_file}.py", _tpl_entity(spec), spec)
        entity_exports[spec.entity_class] = spec.entity_file
        _write(
            root / "entities" / "__init__.py",
            _tpl_pkg_init(entity_exports, f"{spec.import_root}.entities"),
            spec,
        )

    # repositories
    if spec.repository_class and spec.repository_file:
        _write(
            root / "repositories" / f"{spec.repository_file}.py",
            _tpl_repository(spec),
            spec,
        )
        _write(
            root / "repositories" / "__init__.py",
            _tpl_pkg_init(
                {spec.repository_class: spec.repository_file},
                f"{spec.import_root}.repositories",
            ),
            spec,
        )

    # services (+ helper)
    service_exports: dict[str, str] = {}
    if spec.service_class and spec.service_file:
        _write(root / "services" / f"{spec.service_file}.py", _tpl_service(spec), spec)
        service_exports[spec.service_class] = spec.service_file
    if spec.helper_class and spec.helper_file:
        _write(root / "services" / f"{spec.helper_file}.py", _tpl_helper(spec), spec)
        service_exports[spec.helper_class] = spec.helper_file
    if service_exports:
        _write(
            root / "services" / "__init__.py",
            _tpl_pkg_init(service_exports, f"{spec.import_root}.services"),
            spec,
        )

    # controllers
    if spec.controller_class and spec.controller_file:
        _write(
            root / "controllers" / f"{spec.controller_file}.py",
            _tpl_controller(spec),
            spec,
        )
        _write(
            root / "controllers" / "__init__.py",
            _tpl_pkg_init(
                {spec.controller_class: spec.controller_file},
                f"{spec.import_root}.controllers",
            ),
            spec,
        )

    # tasks (+ periodic)
    task_exports: dict[str, str] = {}
    if spec.task_class and spec.task_file:
        _write(root / "tasks" / f"{spec.task_file}.py", _tpl_task(spec), spec)
        task_exports[spec.task_class] = spec.task_file
    if spec.periodic_class and spec.periodic_file:
        _write(root / "tasks" / f"{spec.periodic_file}.py", _tpl_periodic(spec), spec)
        task_exports[spec.periodic_class] = spec.periodic_file
    if task_exports:
        _write(
            root / "tasks" / "__init__.py",
            _tpl_pkg_init(task_exports, f"{spec.import_root}.tasks"),
            spec,
        )

    # consumers
    if spec.consumer_class and spec.consumer_file:
        _write(
            root / "consumers" / f"{spec.consumer_file}.py",
            _tpl_consumer(spec),
            spec,
        )
        _write(
            root / "consumers" / "__init__.py",
            _tpl_pkg_init(
                {spec.consumer_class: spec.consumer_file},
                f"{spec.import_root}.consumers",
            ),
            spec,
        )

    _write(root / "module.py", _tpl_module_py(spec), spec)
    _write(root / "__init__.py", _tpl_root_init(spec), spec)
    return spec


_INSTALLED_MODULES_NAME_RE = re.compile(
    r"\binstalled_modules\b",
    re.IGNORECASE,
)
_LIST_STRING_RE = re.compile(r"""["']([^"']+)["']""")


def _skip_string(text: str, i: int) -> int:
    """Return index just past a quoted string starting at ``i``."""
    quote = text[i]
    i += 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        i += 1
    return i


def _find_installed_modules_list_open(text: str, name_end: int) -> int | None:
    """Find ``[`` that opens the installed_modules value list (not ``list[str]``)."""
    i = name_end
    while i < len(text) and text[i] in " \t":
        i += 1

    # Skip optional PEP-604 / generic type annotation: ``: list[str]``
    if i < len(text) and text[i] == ":":
        i += 1
        depth = 0
        while i < len(text):
            ch = text[i]
            if ch in ("'", '"'):
                i = _skip_string(text, i)
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
            elif ch == "=" and depth == 0:
                break
            i += 1

    while i < len(text) and text[i] != "=":
        i += 1
    if i >= len(text) or text[i] != "=":
        return None
    i += 1

    while i < len(text):
        ch = text[i]
        if ch in ("'", '"'):
            i = _skip_string(text, i)
            continue
        if ch == "[":
            return i
        i += 1
    return None


def _matching_close_bracket(text: str, open_idx: int) -> int | None:
    depth = 0
    i = open_idx
    while i < len(text):
        ch = text[i]
        if ch in ("'", '"'):
            i = _skip_string(text, i)
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _find_installed_modules_list(text: str) -> tuple[int, int, int] | None:
    """Locate the ``installed_modules`` / ``INSTALLED_MODULES`` list body.

    Returns ``(open_bracket_index, close_bracket_index, entry_indent)`` or
    ``None`` when the list cannot be found safely.
    """
    name_match = _INSTALLED_MODULES_NAME_RE.search(text)
    if not name_match:
        return None

    open_idx = _find_installed_modules_list_open(text, name_match.end())
    if open_idx is None:
        return None
    close_idx = _matching_close_bracket(text, open_idx)
    if close_idx is None:
        return None

    body = text[open_idx + 1 : close_idx]
    entry_indent = 12  # matches project template default
    for line in body.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        entry_indent = len(line) - len(stripped)
        break
    else:
        # Empty list: indent one level deeper than the line that contains '['.
        line_start = text.rfind("\n", 0, open_idx) + 1
        open_line = text[line_start:open_idx]
        entry_indent = len(open_line) - len(open_line.lstrip()) + 4

    return open_idx, close_idx, entry_indent


def _listed_module_paths(list_body: str) -> set[str]:
    """Active (non-comment) string entries inside an ``installed_modules`` list."""
    found: set[str] = set()
    for line in list_body.splitlines():
        code = line.split("#", 1)[0]
        for match in _LIST_STRING_RE.finditer(code):
            found.add(match.group(1))
    return found


def register_in_config(
    config_path: Path,
    *,
    module_import: str,
    force_duplicate: bool = False,
) -> str | None:
    """Append ``module_import`` to ``installed_modules`` without rewriting peers.

    Existing entries (and comments) are left untouched. Only a new line is
    inserted immediately before the list's closing ``]`` (or before the
    template's commented example entry when present).

    Returns a short status message, or ``None`` if ``config.py`` / the list
    cannot be found.
    """
    if not config_path.exists():
        return None

    text = config_path.read_text()
    located = _find_installed_modules_list(text)
    if located is None:
        return None

    open_idx, close_idx, entry_indent = located
    list_body = text[open_idx + 1 : close_idx]
    if module_import in _listed_module_paths(list_body) and not force_duplicate:
        return f"already listed in {config_path.name}"

    indent = " " * entry_indent
    entry_line = f'{indent}"{module_import}",\n'

    # Keep a trailing commented example below new entries when present.
    marker = '# "src.modules.example.ExampleModule"'
    marker_at = list_body.find(marker)
    if marker_at >= 0:
        line_start = list_body.rfind("\n", 0, marker_at) + 1
        absolute = open_idx + 1 + line_start
        updated = text[:absolute] + entry_line + text[absolute:]
    else:
        # Insert on its own line before the closing ']' line so we never
        # steal the bracket's indentation (…,\n        ]).
        close_line_start = text.rfind("\n", 0, close_idx) + 1
        updated = text[:close_line_start] + entry_line + text[close_line_start:]

    config_path.write_text(updated)
    return f"registered in {config_path.name}"
