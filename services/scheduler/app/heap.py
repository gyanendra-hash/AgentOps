"""In-memory min-heap priority queue for READY jobs, local to whichever
scheduler replica currently holds leadership (see app/leader_election.py) —
it's rebuilt from Postgres on every dispatch cycle via
Scheduler.refresh_ready_jobs, so it never needs to survive a restart itself.
"""

import heapq
import itertools
from dataclasses import dataclass, field


@dataclass(order=True)
class _HeapEntry:
    sort_key: tuple = field(compare=True)
    job_id: str = field(compare=False)


class PriorityQueue:
    """Min-heap over (-priority, sequence) so higher `priority` values pop
    first, and jobs with equal priority pop in submission order (FIFO) rather
    than being starved by newer high-priority arrivals of the same tier."""

    def __init__(self) -> None:
        self._heap: list[_HeapEntry] = []
        self._counter = itertools.count()

    def push(self, job_id: str, priority: int) -> None:
        seq = next(self._counter)
        heapq.heappush(self._heap, _HeapEntry((-priority, seq), job_id))

    def pop(self) -> str | None:
        if not self._heap:
            return None
        return heapq.heappop(self._heap).job_id

    def peek(self) -> str | None:
        if not self._heap:
            return None
        return self._heap[0].job_id

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)
