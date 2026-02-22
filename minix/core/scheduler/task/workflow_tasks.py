from __future__ import annotations

from typing import Any, Dict, List, Optional

from celery import Task as CeleryTask


class InitContextTask(CeleryTask):
    """
    Starts the workflow execution with an empty context dict.
    """
    name = "workflow.init_context"

    def run(self) -> Dict[str, Any]:
        return {}


class ExecuteNodeTask(CeleryTask):
    """
    Executes one workflow node, updates and returns the context.

    Parameters are passed via kwargs from the compiled canvas.
    The upstream 'context' arrives as the first positional argument via Celery chaining.
    """
    name = "workflow.execute_node"

    def run(
            self,
            context: Optional[Dict[str, Any]],
            node_id: str,
            task_name: str,
            task_args: Optional[List[Any]] = None,
            task_kwargs: Optional[Dict[str, Any]] = None,
            depends_on: Optional[List[str]] = None,
            consume_dependency_results: bool = True,
    ) -> Dict[str, Any]:
        if context is None:
            context = {}
        if task_args is None:
            task_args = []
        if task_kwargs is None:
            task_kwargs = {}
        if depends_on is None:
            depends_on = []

        # If we've already produced this node (should not happen with topo order),
        # do not execute again.
        if node_id in context:
            return dict(context)

        call_args = list(task_args)

        # Match previous behavior: only pass upstream results if:
        # - consume_dependency_results is True
        # - and there is at least 1 dependency
        if consume_dependency_results and depends_on:
            missing = [d for d in depends_on if d not in context]
            if missing:
                raise KeyError(
                    f"Node '{node_id}' cannot run: missing dependency results for {missing}. "
                    f"Available keys: {sorted(context.keys())}"
                )

            if len(depends_on) == 1:
                dep_payload = context[depends_on[0]]
            else:
                dep_payload = [context[d] for d in depends_on]

            call_args = [dep_payload] + call_args

        # Lookup the actual Celery task by name and execute it synchronously inside this worker process.
        t = self.app.tasks.get(task_name)
        if t is None:
            raise KeyError(
                f"Task '{task_name}' is not registered in this Celery app. "
                f"Register it via Scheduler.register_async_task(...) during module install."
            )

        # Important: calling the task object runs its __call__/run in-process.
        result = t(*call_args, **task_kwargs)

        new_ctx = dict(context)
        new_ctx[node_id] = result
        return new_ctx


class ExtractOneTask(CeleryTask):
    """
    For target workflows: return only the target node output (old behavior).
    """
    name = "workflow.extract_one"

    def run(self, context: Dict[str, Any], node_id: str) -> Any:
        return context[node_id]


class ExtractSinksTask(CeleryTask):
    """
    For full workflows: return sink outputs.
    - If there is only one sink, return its value (backward-friendly).
    - If multiple sinks, return a dict {sink_id: value}.
    """
    name = "workflow.extract_sinks"

    def run(self, context: Dict[str, Any], sink_node_ids: List[str]) -> Any:
        if not sink_node_ids:
            return {}

        if len(sink_node_ids) == 1:
            return context[sink_node_ids[0]]

        return {nid: context[nid] for nid in sink_node_ids}
