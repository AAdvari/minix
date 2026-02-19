from __future__ import annotations

from celery import Task as CeleryTask


class IdentityTask(CeleryTask):
    """
    Internal helper: returns its single input unchanged.

    Used when compiling DAG joins so we can include an already-produced ancestor result
    in a chord header without re-running that ancestor task.
    """
    name = "workflow.identity"

    def run(self, x):
        return x
