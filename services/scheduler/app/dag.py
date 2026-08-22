"""Dependency-graph validation for a batch of jobs, using Kahn's algorithm.

Used at *submission* time only: once a batch is accepted, dispatch-time
readiness is decided with a plain SQL "all my dependencies succeeded" check
(see app/repository.py), so this module never has to run against the live
job table.
"""

from collections import deque


class CycleDetectedError(Exception):
    def __init__(self, remaining: set[str]) -> None:
        self.remaining = remaining
        super().__init__(f"dependency cycle detected among: {sorted(remaining)}")


def topological_order(dependencies: dict[str, set[str]]) -> list[str]:
    """`dependencies` maps each node to the set of nodes it depends on (must
    run before it). Returns one valid topological order. Raises
    CycleDetectedError if the graph isn't a DAG."""

    nodes = set(dependencies) | {dep for deps in dependencies.values() for dep in deps}
    in_degree = {node: 0 for node in nodes}
    dependents: dict[str, list[str]] = {node: [] for node in nodes}

    for node, deps in dependencies.items():
        in_degree[node] = len(deps)
        for dep in deps:
            dependents[dep].append(node)

    queue = deque(sorted(node for node, degree in in_degree.items() if degree == 0))
    order: list[str] = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for dependent in sorted(dependents[node]):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(order) != len(nodes):
        remaining = nodes - set(order)
        raise CycleDetectedError(remaining)

    return order
