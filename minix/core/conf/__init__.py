"""
Settings loader for Minix.

Usage::

    from minix.core.conf import settings

    print(settings.DB_HOST)

By default Minix loads a project ``settings`` module when it is importable
(created by ``minix init``). Override with ``MINIX_SETTINGS_MODULE``, or leave
that unset and rely on ``global_settings`` when no project settings exist.

Programmatic configuration (tests)::

    settings.configure(DEBUG=True, DB_HOST="127.0.0.1")
"""

from __future__ import annotations

import importlib
import os
from types import ModuleType
from typing import Any

import dotenv

# Resolve .env before global_settings evaluates env() defaults.
dotenv.load_dotenv()

from . import global_settings as default_settings  # noqa: E402

ENVIRONMENT_VARIABLE = "MINIX_SETTINGS_MODULE"
DEFAULT_SETTINGS_MODULE = "settings"


class ImproperlyConfigured(Exception):
    """Raised when settings are used incorrectly."""


class Settings:
    """Hold uppercase settings from global defaults plus an optional module."""

    def __init__(self, settings_module: str | None = None):
        for name in dir(default_settings):
            if name.isupper():
                setattr(self, name, getattr(default_settings, name))

        self.SETTINGS_MODULE = settings_module
        if settings_module:
            mod = importlib.import_module(settings_module)
            self._explicit_settings: set[str] = set()
            for name in dir(mod):
                if name.isupper():
                    setattr(self, name, getattr(mod, name))
                    self._explicit_settings.add(name)
        else:
            self._explicit_settings = set()

    def __repr__(self) -> str:
        mod = self.SETTINGS_MODULE or "minix.core.conf.global_settings"
        return f"<Settings '{mod}'>"


class UserSettingsHolder:
    """Settings object populated via ``settings.configure(**options)``."""

    def __init__(self, default_settings_obj: ModuleType | Settings):
        self.__dict__["_deleted"] = set()
        self.default_settings = default_settings_obj

    def __getattr__(self, name: str) -> Any:
        if name in self._deleted:
            raise AttributeError(name)
        return getattr(self.default_settings, name)

    def __setattr__(self, name: str, value: Any) -> None:
        self._deleted.discard(name)
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        self._deleted.add(name)
        if hasattr(self, name):
            super().__delattr__(name)

    def __repr__(self) -> str:
        return "<UserSettingsHolder>"


def _resolve_settings_module() -> str | None:
    """Load ``.env``, then pick the settings module (default: ``settings``)."""
    dotenv.load_dotenv()
    explicit = os.environ.get(ENVIRONMENT_VARIABLE)
    if explicit:
        return explicit
    return DEFAULT_SETTINGS_MODULE


class LazySettings:
    """Proxy that loads settings on first access."""

    def __init__(self) -> None:
        self._wrapped: Settings | UserSettingsHolder | None = None

    def _setup(self, name: str | None = None) -> None:
        settings_module = _resolve_settings_module()
        explicit = ENVIRONMENT_VARIABLE in os.environ
        try:
            self._wrapped = Settings(settings_module)
        except ModuleNotFoundError:
            if explicit:
                raise
            # No project settings.py yet — framework defaults only.
            self._wrapped = Settings(None)

    def __getattr__(self, name: str) -> Any:
        if self._wrapped is None:
            self._setup(name)
        val = getattr(self._wrapped, name)
        self.__dict__[name] = val
        return val

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_wrapped":
            self.__dict__.clear()
            self.__dict__["_wrapped"] = value
            return
        if self._wrapped is None:
            self._setup()
        setattr(self._wrapped, name, value)
        self.__dict__[name] = value

    def __delattr__(self, name: str) -> None:
        if name == "_wrapped":
            raise TypeError("cannot delete _wrapped.")
        if self._wrapped is None:
            self._setup()
        delattr(self._wrapped, name)
        self.__dict__.pop(name, None)

    def configure(self, default_settings_obj: ModuleType | None = None, **options: Any) -> None:
        """Configure settings manually (useful in tests). Must be called before access."""
        if self._wrapped is not None:
            raise ImproperlyConfigured("Settings already configured.")
        holder = UserSettingsHolder(default_settings_obj or default_settings)
        for name, value in options.items():
            if not name.isupper():
                raise TypeError(f"Setting {name!r} must be uppercase.")
            setattr(holder, name, value)
        self._wrapped = holder

    @property
    def configured(self) -> bool:
        return self._wrapped is not None


settings = LazySettings()
