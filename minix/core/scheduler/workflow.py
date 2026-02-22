from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from celery import chain
from celery.canvas import Signature

from minix.core.scheduler.task import Task


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
    DAG of Task invocations compiled to a Celery *chain* that carries a context dict.

    This avoids the core limitation of Celery canvas for general DAGs:
    canvas chaining only forwards the *last* task result, so joins that require
    outputs from multiple "earlier" ancestors can’t be expressed without reruns.

    With a context dict:
      - Each node runs exactly once.
      - Multiple sinks are supported.
      - Tasks not on the path to a particular sink still run when executing the whole workflow.
      - Dependency outputs are passed as arg0 (value or list), matching previous behavior.
    """

    def __init__(self, name: str):
        self.name = name
        self._nodes: Dict[str, WorkflowNode] = {}

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
        # Still “true” for multi-dep nodes, but we no longer require chord/result_backend.
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

        ready = [nid for nid in self._nodes.keys() if indeg[nid] == 0]  # stable order
        visited = 0

        while ready:
            nid = ready.pop(0)
            visited += 1
            for ch in children[nid]:
                indeg[ch] -= 1
                if indeg[ch] == 0:
                    ready.append(ch)

        if visited != len(self._nodes):
            raise CycleError("Workflow contains a cycle (not a DAG).")

    def _ancestor_closure(self, node_id: str) -> Set[str]:
        """
        Return {node_id} U all ancestors(node_id).
        """
        if node_id not in self._nodes:
            raise WorkflowError(f"Unknown node_id: {node_id}")

        closure: Set[str] = set()

        def dfs(nid: str) -> None:
            if nid in closure:
                return
            closure.add(nid)
            for dep in self._nodes[nid].depends_on:
                dfs(dep)

        dfs(node_id)
        return closure

    def _topological_order(self, selected: Set[str]) -> List[str]:
        """
        Stable Kahn topological sort over `selected` nodes.
        """
        indeg: Dict[str, int] = {nid: 0 for nid in selected}
        children: Dict[str, List[str]] = {nid: [] for nid in selected}

        for nid in selected:
            for dep in self._nodes[nid].depends_on:
                if dep in selected:
                    indeg[nid] += 1
                    children[dep].append(nid)

        ready = [nid for nid in self._nodes.keys() if nid in selected and indeg[nid] == 0]
        out: List[str] = []

        while ready:
            nid = ready.pop(0)
            out.append(nid)
            for ch in children[nid]:
                indeg[ch] -= 1
                if indeg[ch] == 0:
                    ready.append(ch)

        if len(out) != len(selected):
            raise CycleError("Selected subgraph contains a cycle (not a DAG).")

        return out

    def to_canvas(self, *, app, target_node_id: Optional[str] = None) -> Signature:
        """
        Compile to a Celery chain that carries a context dict.

        - If target_node_id is provided: run only the subgraph needed for that node,
          and return the *target node result* (old behavior).
        - If target_node_id is None: run the *entire workflow* and return sink outputs.
        """
        self.validate_dag()

        if not self._nodes:
            raise WorkflowError("Workflow has no nodes.")

        if target_node_id is not None:
            selected = self._ancestor_closure(target_node_id)
            topo = self._topological_order(selected)

            init = app.signature("workflow.init_context", immutable=True)

            steps: List[Signature] = []
            for nid in topo:
                n = self._nodes[nid]
                steps.append(
                    app.signature(
                        "workflow.execute_node",
                        kwargs={
                            "node_id": nid,
                            "task_name": n.task.get_name(),
                            "task_args": list(n.task.get_args()),
                            "task_kwargs": dict(n.task.get_kwargs()),
                            "depends_on": list(n.depends_on),
                            "consume_dependency_results": n.consume_dependency_results,
                        },
                        immutable=False,
                    )
                )

            extract = app.signature(
                "workflow.extract_one",
                kwargs={"node_id": target_node_id},
                immutable=False,
            )

            return chain(init, *steps, extract)

        # Run whole workflow
        selected = set(self._nodes.keys())
        topo = self._topological_order(selected)

        init = app.signature("workflow.init_context", immutable=True)

        steps = []
        for nid in topo:
            n = self._nodes[nid]
            steps.append(
                app.signature(
                    "workflow.execute_node",
                    kwargs={
                        "node_id": nid,
                        "task_name": n.task.get_name(),
                        "task_args": list(n.task.get_args()),
                        "task_kwargs": dict(n.task.get_kwargs()),
                        "depends_on": list(n.depends_on),
                        "consume_dependency_results": n.consume_dependency_results,
                    },
                    immutable=False,
                )
            )

        sink_ids = self.sinks()
        extract = app.signature(
            "workflow.extract_sinks",
            kwargs={"sink_node_ids": sink_ids},
            immutable=False,
        )

        return chain(init, *steps, extract)
