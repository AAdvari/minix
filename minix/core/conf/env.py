"""Helpers for reading configuration from the environment."""

from __future__ import annotations

import os
from typing import Callable, TypeVar, overload

T = TypeVar("T")

_TRUE = {"1", "true", "yes", "on", "y"}
_FALSE = {"0", "false", "no", "off", "n", ""}


def _cast_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ValueError(f"Cannot cast {value!r} to bool")


def _cast_list(value: str) -> list[str]:
    if not value or not value.strip():
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


@overload
def env(key: str, default: str = "") -> str: ...


@overload
def env(key: str, default: T, *, cast: Callable[[str], T]) -> T: ...


def env(key: str, default: T = "", *, cast: Callable[[str], T] | None = None) -> T:
    """Read ``key`` from the environment, falling back to ``default``.

    When ``cast`` is omitted, the cast is inferred from ``default``'s type for
    ``bool``, ``int``, ``float``, and ``list``. Otherwise the raw string (or
    default) is returned.
    """
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default  # type: ignore[return-value]

    if cast is not None:
        return cast(raw)

    if isinstance(default, bool):
        return _cast_bool(raw)  # type: ignore[return-value]
    if isinstance(default, int) and not isinstance(default, bool):
        return int(raw)  # type: ignore[return-value]
    if isinstance(default, float):
        return float(raw)  # type: ignore[return-value]
    if isinstance(default, list):
        return _cast_list(raw)  # type: ignore[return-value]
    return raw  # type: ignore[return-value]


def env_optional(key: str, default: str | None = None) -> str | None:
    """Like ``env`` but treats empty strings as missing (returns ``default``)."""
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    return raw
