from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from celery import chain, chord, group
from celery.canvas import Signature

from src.core.scheduler.task import Task


class WorkflowError(Exception):
    pass


class CycleError(WorkflowError):
    pass


@dataclass(frozen=True)
class WorkflowNode:
    node_id: str
    task: Task
    depends_on: Tuple[str, ...] = ()
    consume_dependency_results: bool = True


class Workflow:
    """
    DAG of Task invocations compiled to Celery Canvas.

    Celery canvas primitives are tree-shaped; naive recursion over a DAG duplicates
    shared ancestors => "task executed multiple times".

    This compiler avoids the common overlap case by factoring joins around the
    Lowest Common Ancestor (LCA) and using IdentityTask to re-emit prefix results
    into the chord header without re-execution.
    """

    def __init__(self, name: str):
        self.name = name
        self._nodes: Dict[str, WorkflowNode] = {}
        self._ancestors_cache: Dict[str, Set[str]] = {}
        self._depth_cache: Dict[str, int] = {}

    def add(
        self,
        task: Task,
        *,
        node_id: str,
        depends_on: Iterable[str] = (),
        consume_dependency_results: bool = True,
    ) -> str:
        if node_id in self._nodes:
            raise WorkflowError(f"Duplicate node_id: {node_id}")
        self._nodes[node_id] = WorkflowNode(
            node_id=node_id,
            task=task,
            depends_on=tuple(depends_on),
            consume_dependency_results=consume_dependency_results,
        )
        self._ancestors_cache.clear()
        self._depth_cache.clear()
        return node_id

    def _dependents_map(self) -> Dict[str, List[str]]:
        dep_map: Dict[str, List[str]] = {nid: [] for nid in self._nodes}
        for n in self._nodes.values():
            for dep in n.depends_on:
                dep_map[dep].append(n.node_id)
        return dep_map

    def sinks(self) -> List[str]:
        dep_map = self._dependents_map()
        return [nid for nid, ds in dep_map.items() if not ds]

    def uses_join(self) -> bool:
        return any(len(n.depends_on) > 1 for n in self._nodes.values())

    def validate_dag(self) -> None:
        node_ids = set(self._nodes.keys())
        for n in self._nodes.values():
            for dep in n.depends_on:
                if dep not in node_ids:
                    raise WorkflowError(f"Node '{n.node_id}' depends on missing node '{dep}'")
                if dep == n.node_id:
                    raise WorkflowError(f"Node '{n.node_id}' cannot depend on itself")

        # Kahn cycle detection
        indeg: Dict[str, int] = {nid: 0 for nid in self._nodes}
        children: Dict[str, List[str]] = {nid: [] for nid in self._nodes}
        for n in self._nodes.values():
            for dep in n.depends_on:
                children[dep].append(n.node_id)
                indeg[n.node_id] += 1

        ready = [nid for nid, d in indeg.items() if d == 0]
        visited = 0
        while ready:
            nid = ready.pop()
            visited += 1
            for ch in children[nid]:
                indeg[ch] -= 1
                if indeg[ch] == 0:
                    ready.append(ch)

        if visited != len(self._nodes):
            raise CycleError("Workflow contains a cycle (not a DAG).")

    # --- Graph helpers ---

    def _ancestors(self, node_id: str) -> Set[str]:
        if node_id in self._ancestors_cache:
            return self._ancestors_cache[node_id]
        n = self._nodes[node_id]
        acc: Set[str] = set()
        for dep in n.depends_on:
            acc.add(dep)
            acc |= self._ancestors(dep)
        self._ancestors_cache[node_id] = acc
        return acc

    def _depth(self, node_id: str) -> int:
        if node_id in self._depth_cache:
            return self._depth_cache[node_id]
        n = self._nodes[node_id]
        if not n.depends_on:
            self._depth_cache[node_id] = 0
            return 0
        d = 1 + max(self._depth(dep) for dep in n.depends_on)
        self._depth_cache[node_id] = d
        return d

    def _lca(self, node_ids: List[str]) -> Optional[str]:
        if not node_ids:
            return None
        common: Optional[Set[str]] = None
        for nid in node_ids:
            s = self._ancestors(nid) | {nid}
            common = s if common is None else (common & s)
        if not common:
            return None
        return max(common, key=self._depth)

    # --- Celery signature helpers ---

    @staticmethod
    def _task_signature(*, app, task: Task, consume_upstream: bool) -> Signature:
        return app.signature(
            task.get_name(),
            args=task.get_args(),
            kwargs=task.get_kwargs(),
            immutable=not consume_upstream,
        )

    @staticmethod
    def _identity_signature(*, app) -> Signature:
        return app.signature("workflow.identity", immutable=False)

    # --- Public API ---

    def to_canvas(self, *, app, target_node_id: Optional[str] = None) -> Signature:
        self.validate_dag()

        if target_node_id is None:
            sinks = self.sinks()
            if not sinks:
                raise WorkflowError("Workflow has no nodes.")
            if len(sinks) != 1:
                raise WorkflowError(
                    f"Workflow has multiple sinks {sinks}. Pass target_node_id explicitly."
                )
            target_node_id = sinks[0]

        if target_node_id not in self._nodes:
            raise WorkflowError(f"Unknown target_node_id: {target_node_id}")

        return self._compile_abs(app=app, node_id=target_node_id)

    # --- Compilation internals ---

    def _compile_abs(self, *, app, node_id: str) -> Signature:
        node = self._nodes[node_id]
        deps = list(node.depends_on)

        consume = node.consume_dependency_results and len(deps) > 0
        node_sig = self._task_signature(app=app, task=node.task, consume_upstream=consume)

        if not deps:
            return node_sig

        if len(deps) == 1:
            return chain(self._compile_abs(app=app, node_id=deps[0]), node_sig)

        # Join: factor around LCA to avoid duplicating shared ancestors.
        lca = self._lca(deps)
        if lca is None:
            header = group([self._compile_abs(app=app, node_id=d) for d in deps])
            return chord(header, node_sig)

        prefix = self._compile_abs(app=app, node_id=lca)
        header_items = [self._compile_rel(app=app, prefix_id=lca, node_id=d) for d in deps]
        return chain(prefix, group(header_items), node_sig)

    def _compile_rel(self, *, app, prefix_id: str, node_id: str) -> Signature:
        """
        Compile a node assuming prefix_id already executed.
        The prefix result will be injected as arg0 into this relative canvas.
        """
        if node_id == prefix_id:
            return self._identity_signature(app=app)

        node = self._nodes[node_id]
        deps = list(node.depends_on)

        if not deps:
            raise WorkflowError(
                f"Cannot compile '{node_id}' relative to '{prefix_id}': node has no deps and is not the prefix."
            )

        consume = node.consume_dependency_results
        node_sig = self._task_signature(app=app, task=node.task, consume_upstream=consume)

        if len(deps) == 1:
            return chain(self._compile_rel(app=app, prefix_id=prefix_id, node_id=deps[0]), node_sig)

        # Relative join: only supported when prefix is the LCA of deps.
        lca = self._lca(deps)
        if lca != prefix_id:
            raise WorkflowError(
                f"Cannot compile join '{node_id}' relative to '{prefix_id}'. "
                f"Dependencies={deps}, computed_lca={lca}."
            )

        header = group([self._compile_rel(app=app, prefix_id=prefix_id, node_id=d) for d in deps])
        return chain(header, node_sig)
