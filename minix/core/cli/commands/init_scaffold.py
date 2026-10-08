"""Feature detection and template rendering for ``minix init``."""

from __future__ import annotations

import importlib.util
import re
from typing import Iterable

VALID_MINIX_EXTRAS = frozenset({"postgresql", "mysql", "vdb", "clickhouse", "ai"})
_EXTRA_ORDER = ("postgresql", "mysql", "vdb", "clickhouse", "ai")
# Template feature blocks may use shorter aliases (e.g. BEGIN_POSTGRES).
_FEATURE_TO_PIP_EXTRA = {
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "mysql": "mysql",
    "vdb": "vdb",
    "clickhouse": "clickhouse",
    "ai": "ai",
}

_FEATURE_BLOCK = re.compile(
    r"^# __BEGIN_(?P<name>[A-Z0-9_]+)__\r?\n(.*?)^# __END_(?P=name)__\r?\n",
    re.MULTILINE | re.DOTALL,
)


def detect_installed_minix_extras() -> set[str]:
    """Infer optional Minix extras from packages in the current environment."""
    extras: set[str] = set()
    if importlib.util.find_spec("psycopg") is not None:
        extras.add("postgresql")
    if importlib.util.find_spec("pymysql") is not None:
        extras.add("mysql")
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


# First PyPI release that exports ``bootstrap_from_settings`` for the Docker template.
_MIN_DOCKER_MINIX = "0.2.2"


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in value.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or (0,)


def _normalize_version_parts(parts: list[int] | tuple[int, ...]) -> list[int]:
    out = list(parts)
    while len(out) < 3:
        out.append(0)
    return out[:3]


def _compatible_release_constraint(version: str) -> str:
    """``~=X.Y.Z`` → latest patch on the same minor (e.g. 0.2.2 → any 0.2.x ≥ 0.2.2)."""
    major, minor, patch = _normalize_version_parts(_version_tuple(version))
    return f"~={major}.{minor}.{patch}"


def _latest_pypi_minix_on_minor(major: int, minor: int) -> tuple[int, int, int] | None:
    """Return the newest published Minix version on ``major.minor``, or None."""
    try:
        import json
        import urllib.request

        with urllib.request.urlopen(
            "https://pypi.org/pypi/minix/json",
            timeout=3,
        ) as resp:
            data = json.load(resp)
    except Exception:
        return None

    best: tuple[int, int, int] | None = None
    for ver in data.get("releases", {}):
        parts = _normalize_version_parts(_version_tuple(ver))
        if parts[0] != major or parts[1] != minor:
            continue
        # Skip empty/yanked-only releases when files are absent.
        files = data["releases"].get(ver) or []
        if not files:
            continue
        candidate = (parts[0], parts[1], parts[2])
        if best is None or candidate > best:
            best = candidate
    return best


def _minix_version_constraint() -> str:
    """Pin Docker to a PyPI-installable release on the installed minor line.

    Uses the installed Minix version as the preferred floor, but never pins
    above the latest published patch on that minor (local unreleased builds
    like ``0.2.4`` must not break ``pip install`` in Docker).
    """
    floor = _normalize_version_parts(_version_tuple(_MIN_DOCKER_MINIX))
    target = list(floor)

    try:
        from importlib.metadata import version

        installed = _normalize_version_parts(_version_tuple(version("minix")))
        if tuple(installed) >= tuple(floor):
            target = installed
        elif installed[:2] == floor[:2]:
            target = [floor[0], floor[1], max(installed[2], floor[2])]
    except Exception:
        pass

    published = _latest_pypi_minix_on_minor(target[0], target[1])
    if published is not None and published < tuple(target):
        target = list(published)

    if tuple(target) < tuple(floor):
        return _compatible_release_constraint(_MIN_DOCKER_MINIX)
    return _compatible_release_constraint(f"{target[0]}.{target[1]}.{target[2]}")


def minix_pip_install_spec(extras: Iterable[str]) -> str:
    normalized = {
        _FEATURE_TO_PIP_EXTRA.get(e, e) for e in extras if e in _FEATURE_TO_PIP_EXTRA or e in VALID_MINIX_EXTRAS
    }
    chosen = [e for e in _EXTRA_ORDER if e in normalized]
    constraint = _minix_version_constraint()
    if not chosen:
        return f"minix{constraint}"
    return f'minix[{",".join(chosen)}]{constraint}'


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
