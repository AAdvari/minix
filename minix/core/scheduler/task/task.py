from __future__ import annotations

import inspect
from abc import abstractmethod, ABC
from functools import lru_cache
from typing import Any, Tuple

from celery import Task as CeleryTask
from celery.schedules import crontab


class _RunArity:
    __slots__ = ("min_positional", "max_positional", "has_varargs")

    def __init__(self, min_positional: int, max_positional: int, has_varargs: bool):
        self.min_positional = min_positional
        self.max_positional = max_positional
        self.has_varargs = has_varargs


@lru_cache(maxsize=2048)
def _get_run_arity(task_cls: type) -> _RunArity:
    """Inspect and cache run() signature per Task class."""
    run_fn = getattr(task_cls, "run", None)
    if run_fn is None:
        return _RunArity(0, 0, False)

    sig = inspect.signature(run_fn)
    params = list(sig.parameters.values())

    # Exclude `self`
    if params and params[0].name == "self":
        params = params[1:]

    positional = [
        p
        for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)

    min_pos = sum(1 for p in positional if p.default is inspect._empty)
    max_pos = len(positional)
    return _RunArity(min_pos, max_pos, has_varargs)


def _flatten_one_level(seq: Tuple[Any, ...]) -> Tuple[Any, ...]:
    out = []
    for v in seq:
        if isinstance(v, (list, tuple)):
            out.extend(v)
        else:
            out.append(v)
    return tuple(out)


class Task(CeleryTask, ABC):
    """
    Base task with "flatten/unpack" support:

    - If Celery delivers a single list/tuple argument (common with chords/groups and
      also when an upstream returns a tuple), and run() can accept multiple positional
      args, we automatically unpack that container into positional args.

    This lets user tasks keep signatures like:
        run(self, a, b)
    instead of:
        run(self, results: list)
    """

    # Unpack a single incoming list/tuple into positional args when run() can take >=2 args.
    minix_auto_unpack: bool = True

    # If direct unpack doesn't fit run() arity, try flattening one level and re-check.
    minix_auto_flatten: bool = True

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        super().__init__()

    def get_args(self):
        return self.args

    def get_kwargs(self):
        return self.kwargs

    @property
    def name(self):
        return self.get_name()

    def __call__(self, *args, **kwargs):
        """
        Normalize incoming args before Celery calls run().
        """
        if self.minix_auto_unpack and args:
            first = args[0]
            if isinstance(first, (list, tuple)):
                arity = _get_run_arity(self.__class__)

                # Don't unpack if run() is effectively "single-arg" (max_positional < 2 and no *args)
                can_accept_multiple = arity.has_varargs or arity.max_positional >= 2
                if can_accept_multiple:
                    seq = tuple(first)

                    # Try direct unpack first
                    candidate = seq + tuple(args[1:])

                    def fits(a: Tuple[Any, ...]) -> bool:
                        if arity.has_varargs:
                            return len(a) >= arity.min_positional
                        return arity.min_positional <= len(a) <= arity.max_positional

                    if fits(candidate):
                        args = candidate
                    elif self.minix_auto_flatten:
                        seq2 = _flatten_one_level(seq)
                        candidate2 = seq2 + tuple(args[1:])
                        if fits(candidate2):
                            args = candidate2
                        else:
                            raise TypeError(
                                f"{self.__class__.__name__}.run arity mismatch after unpack/flatten. "
                                f"incoming_len={len(seq)}, flattened_len={len(seq2)}, "
                                f"expected={arity.min_positional}..{arity.max_positional}"
                            )

        return super().__call__(*args, **kwargs)

    @abstractmethod
    def get_name(self) -> str:
        pass

    @abstractmethod
    def run(self, *args, **kwargs):
        pass


class PeriodicTask(Task, ABC):
    @abstractmethod
    def get_schedule(self) -> crontab:
        pass
