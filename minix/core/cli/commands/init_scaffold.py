"""Feature detection and template rendering for ``minix init``."""

from __future__ import annotations

import importlib.util
import re
from typing import Iterable

VALID_MINIX_EXTRAS = frozenset({"vdb", "clickhouse", "ai"})
_EXTRA_ORDER = ("vdb", "clickhouse", "ai")

_FEATURE_BLOCK = re.compile(
    r"^# __BEGIN_(?P<name>[A-Z0-9_]+)__\r?\n(.*?)^# __END_(?P=name)__\r?\n",
    re.MULTILINE | re.DOTALL,
)


def detect_installed_minix_extras() -> set[str]:
    """Infer optional Minix extras from packages in the current environment."""
    extras: set[str] = set()
    if importlib.util.find_spec("qdrant_client") is not None:
        extras.add("vdb")
    if importlib.util.find_spec("clickhouse_driver") is not None:
        extras.add("clickhouse")
    if (
        importlib.util.find_spec("mlflow") is not None
        and importlib.util.find_spec("torch") is not None
    ):
        extras.add("ai")
    return extras


def parse_extras_option(value: str) -> set[str]:
    """Parse ``--extras vdb,clickhouse``."""
    parts = {p.strip().lower() for p in value.split(",") if p.strip()}
    unknown = parts - VALID_MINIX_EXTRAS
    if unknown:
        raise ValueError(
            f"Unknown minix extra(s): {', '.join(sorted(unknown))}. "
            f"Choose from: {', '.join(_EXTRA_ORDER)}."
        )
    return parts


def resolve_minix_extras(
    *,
    no_extras: bool,
    extras_option: str | None,
) -> set[str]:
    if no_extras:
        return set()
    if extras_option is not None:
        return parse_extras_option(extras_option)
    return detect_installed_minix_extras()


def minix_pip_install_spec(extras: Iterable[str]) -> str:
    chosen = [e for e in _EXTRA_ORDER if e in extras]
    if not chosen:
        return "minix"
    return f'minix[{",".join(chosen)}]'


def apply_feature_blocks(text: str, extras: set[str]) -> str:
    """Keep or drop ``# __BEGIN_*__`` / ``# __END_*__`` template regions."""

    def _repl(match: re.Match[str]) -> str:
        name = match.group("name")
        body = match.group(2)
        if name.startswith("NO_"):
            feature = name[3:].lower()
            include = feature not in extras
        else:
            feature = name.lower()
            include = feature in extras
        return body if include else ""

    return _FEATURE_BLOCK.sub(_repl, text)
