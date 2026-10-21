"""Scaffold helpers for ``minix add <component> --module=...`` on an existing module.

Writes the component file, exports it from its subpackage ``__init__.py`` and
wires it into the module's ``BusinessModule`` chain in ``module.py``. Existing
code is never rewritten; only new lines / tokens are inserted.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from minix.core.cli.commands.add_module_scaffold import (
    _DEFAULT_COMPONENT,
    ModuleSpec,
    _tpl_consumer,
    _tpl_controller,
    _tpl_entity,
    _tpl_helper,
    _tpl_periodic,
    _tpl_pkg_init,
    _tpl_repository,
    _tpl_service,
    _tpl_task,
    _write,
    build_spec,
    to_pascal,
    validate_module_name,
)


@dataclass(frozen=True)
class _Piece:
    """One generated class: where it lives and how it is rendered."""

    class_attr: str  # ModuleSpec attribute holding the class name
    file_attr: str  # ModuleSpec attribute holding the file stem
    subpackage: str
    template: Callable[[ModuleSpec], str]


@dataclass(frozen=True)
class _Component:
    pieces: tuple[_Piece, ...]
    add_method: str  # BusinessModule method used for wiring


_ENTITY = _Piece("entity_class", "entity_file", "entities", _tpl_entity)
_REPOSITORY = _Piece("repository_class", "repository_file", "repositories", _tpl_repository)
_SERVICE = _Piece("service_class", "service_file", "services", _tpl_service)

COMPONENTS: dict[str, _Component] = {
    "controller": _Component(
        (_Piece("controller_class", "controller_file", "controllers", _tpl_controller),),
        "add_controller",
    ),
    "task": _Component(
        (_Piece("task_class", "task_file", "tasks", _tpl_task),),
        "add_task",
    ),
    "periodic": _Component(
        (_Piece("periodic_class", "periodic_file", "tasks", _tpl_periodic),),
        "add_periodic_task",
    ),
    "helper": _Component(
        (_Piece("helper_class", "helper_file", "services", _tpl_helper),),
        "add_helper_service",
    ),
    "consumer": _Component(
        (_Piece("consumer_class", "consumer_file", "consumers", _tpl_consumer),),
        "add_consumer",
    ),
    "binding": _Component((_ENTITY, _REPOSITORY, _SERVICE), "add_binding"),
}


@dataclass
class _ExistingModule:
    export: str  # e.g. OrdersModule
    bindings: list[tuple[str, ...]]  # every add_binding(E, R, S) in the module


def _parse(path: Path) -> tuple[str, ast.Module]:
    text = path.read_text()
    try:
        return text, ast.parse(text)
    except SyntaxError as exc:
        raise ValueError(f"Cannot parse {path}: {exc}") from exc


def _is_business_module_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "BusinessModule"
    )


def _find_export_assign(tree: ast.Module) -> ast.Assign | ast.AnnAssign | None:
    """Top-level ``<Name> = ... BusinessModule(...) ...`` assignment."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if isinstance(target, ast.Name) and any(
            _is_business_module_call(n) for n in ast.walk(value)
        ):
            return node
    return None


def _wired_calls(tree: ast.Module, method: str) -> list[tuple[str, ...]]:
    """Positional ``Name`` args of every ``.<method>(...)`` call in the file."""
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method
        ):
            found.append(
                tuple(a.id for a in node.args if isinstance(a, ast.Name))
            )
    return found


def _read_existing(module_py: Path) -> _ExistingModule:
    _, tree = _parse(module_py)
    assign = _find_export_assign(tree)
    if assign is None:
        raise ValueError(
            f"No `<Name> = BusinessModule(...)` assignment found in {module_py}; "
            "wire the component manually."
        )
    target = assign.targets[0] if isinstance(assign, ast.Assign) else assign.target
    return _ExistingModule(
        export=target.id,
        bindings=[b for b in _wired_calls(tree, "add_binding") if len(b) == 3],
    )


def _offset(lines: list[str], lineno: int, col: int) -> int:
    """Absolute string index for an ast (1-based line, UTF-8 byte col) position."""
    before = sum(len(line) for line in lines[: lineno - 1])
    return before + len(lines[lineno - 1].encode()[:col].decode())


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(a.asname or a.name.split(".")[0] for a in node.names)
    return names


def _insert_import(text: str, tree: ast.Module, line: str) -> str:
    """Insert ``line`` after the last top-level import (or the docstring)."""
    lines = text.splitlines(keepends=True)
    anchor = 0
    for i, node in enumerate(tree.body):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            anchor = node.end_lineno
        elif (
            i == 0
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            anchor = node.end_lineno
    if anchor and not lines[anchor - 1].endswith("\n"):
        lines[anchor - 1] += "\n"
    lines.insert(anchor, line + "\n")
    return "".join(lines)


def _ensure_import(text: str, package: str, symbol: str) -> str:
    tree = ast.parse(text)
    if symbol in _imported_names(tree):
        return text
    return _insert_import(text, tree, f"from {package} import {symbol}")


def _append_to_all(text: str, symbol: str) -> str:
    """Add ``symbol`` to a literal ``__all__`` list/tuple when present."""
    tree = ast.parse(text)
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            continue
        seq = node.value
        if any(isinstance(e, ast.Constant) and e.value == symbol for e in seq.elts):
            return text
        lines = text.splitlines(keepends=True)
        entry = f'"{symbol}"'
        if not seq.elts:
            at = _offset(lines, seq.end_lineno, seq.end_col_offset) - 1
            return text[:at] + entry + text[at:]
        last = seq.elts[-1]
        if seq.lineno != seq.end_lineno:
            # Multi-line: new entry on its own line, matching the last entry.
            last_line = lines[last.lineno - 1]
            indent = last_line[: len(last_line) - len(last_line.lstrip())]
            at = _offset(lines, seq.end_lineno, 0)
            close_line = lines[seq.end_lineno - 1]
            if close_line[: seq.end_col_offset - 1].strip():
                # Closing bracket shares a line with the last entry.
                at = _offset(lines, last.end_lineno, last.end_col_offset)
                return text[:at] + f",\n{indent}{entry}" + text[at:]
            # Ensure the previous entry has a trailing comma.
            after_last = _offset(lines, last.end_lineno, last.end_col_offset)
            between = text[after_last:at]
            if "," not in between:
                text = text[:after_last] + "," + text[after_last:]
                at += 1
            return text[:at] + f"{indent}{entry},\n" + text[at:]
        at = _offset(lines, last.end_lineno, last.end_col_offset)
        return text[:at] + f", {entry}" + text[at:]
    return text


def _ensure_export(init_path: Path, symbol: str, submodule: str, spec: ModuleSpec) -> None:
    """Export ``symbol`` from a subpackage ``__init__.py`` (create if missing)."""
    package_import = submodule.rsplit(".", 1)[0]
    stem = submodule.rsplit(".", 1)[1]
    if not init_path.exists():
        _write(init_path, _tpl_pkg_init({symbol: stem}, package_import), spec)
        return
    text = init_path.read_text()
    try:
        updated = _append_to_all(_ensure_import(text, submodule, symbol), symbol)
    except SyntaxError as exc:
        raise ValueError(f"Cannot parse {init_path}: {exc}") from exc
    if updated != text:
        init_path.write_text(updated)
        spec.created.append(f"{init_path} (updated)")


def _wire(module_py: Path, export: str, method: str, classes: list[str], imports: list[tuple[str, str]]) -> str:
    """Add imports and ``.<method>(<classes>)`` to the module chain."""
    text, tree = _parse(module_py)
    if tuple(classes) in _wired_calls(tree, method):
        return f"already wired: .{method}({', '.join(classes)})"

    for package, symbol in imports:
        text = _ensure_import(text, package, symbol)

    tree = ast.parse(text)
    assign = _find_export_assign(tree)
    assert assign is not None  # checked by _read_existing
    value = assign.value
    lines = text.splitlines(keepends=True)
    value_end = _offset(lines, value.end_lineno, value.end_col_offset)
    stmt_end = _offset(lines, assign.end_lineno, assign.end_col_offset)
    call = f".{method}({', '.join(classes)})"

    if text[value_end:stmt_end].strip().startswith(")"):
        # Parenthesised chain: continue on a new line, matching its indent.
        end_line = lines[value.end_lineno - 1]
        indent = end_line[: len(end_line) - len(end_line.lstrip())]
        if value.end_lineno == assign.lineno or not indent:
            indent = "    "
        text = text[:value_end] + f"\n{indent}{call}" + text[value_end:]
    else:
        text = text[:value_end] + call + text[value_end:]

    module_py.write_text(text)
    return f"wired in {module_py.name}: {call}"


def add_component(
    kind: str,
    *,
    module_name: str,
    path: str | None,
    names: dict[str, str | None],
    force: bool,
) -> tuple[ModuleSpec, str]:
    """Generate ``kind`` inside an existing module and wire it into ``module.py``.

    ``names`` maps ``build_spec`` keyword (``controller``, ``entity``, …) to an
    optional custom class name. Returns the spec (created/skipped files) and a
    wiring status message.
    """
    component = COMPONENTS[kind]
    name = validate_module_name(module_name)
    package = Path(path) if path else Path("src") / "modules" / name
    module_py = package / "module.py"
    if not module_py.exists():
        raise ValueError(
            f"{module_py} not found. Create the module first: minix add module {name}"
        )
    existing = _read_existing(module_py)

    is_binding = kind == "binding"
    options = {k: None for k in ("entity", "repository", "service", "controller",
                                 "task", "helper", "consumer", "periodic")}
    if is_binding:
        options.update({k: names.get(k) for k in ("entity", "repository", "service")})
        entity = names.get("entity")
        if entity:
            # Name the repository / service after a custom entity so a second
            # binding does not reuse the module's default OrderSql* classes.
            base = to_pascal(entity)
            options["repository"] = options["repository"] or f"{base}SqlRepository"
            options["service"] = options["service"] or f"{base}SqlService"
    else:
        options[kind] = names.get(kind) or _DEFAULT_COMPONENT

    spec = build_spec(
        module_name=name,
        path=path,
        **options,
        all_components=False,
        no_binding=not is_binding,
        no_controller=kind != "controller",
        force=force,
        register=False,
    )
    spec.module_export = existing.export
    if kind == "controller" and existing.bindings:
        # Let the controller template use the module's existing service.
        spec.service_class = existing.bindings[0][2]
    if is_binding:
        new = (spec.entity_class, spec.repository_class, spec.service_class)
        for wired_binding in existing.bindings:
            if wired_binding != new and set(wired_binding) & set(new):
                raise ValueError(
                    f"Binding {', '.join(new)} shares classes with the existing "
                    f".add_binding({', '.join(wired_binding)}). Pass distinct "
                    "--entity / --repository / --service names."
                )

    classes: list[str] = []
    imports: list[tuple[str, str]] = []
    for piece in component.pieces:
        cls = getattr(spec, piece.class_attr)
        stem = getattr(spec, piece.file_attr)
        sub_import = f"{spec.import_root}.{piece.subpackage}"
        _write(package / piece.subpackage / f"{stem}.py", piece.template(spec), spec)
        _ensure_export(
            package / piece.subpackage / "__init__.py",
            cls,
            f"{sub_import}.{stem}",
            spec,
        )
        classes.append(cls)
        imports.append((sub_import, cls))

    wired = _wire(module_py, spec.module_export, component.add_method, classes, imports)
    return spec, wired
