import asyncio
import logging

from redis.asyncio import Redis

from agentops_common.models import JobStatus, NewJob
from agentops_common.queue import push_job
from app.dag import topological_order
from app.leader_election import LeaderElection
from app.heap import PriorityQueue
from app.repository import JobRecord, JobRepository

logger = logging.getLogger(__name__)


class DuplicateRefError(Exception):
    pass


class UnknownDependencyError(Exception):
    pass


class Scheduler:
    """Owns the ready-queue heap and drives the dispatch loop. Only the
    replica holding leadership (see LeaderElection) refreshes/dispatches;
    the others just keep polling to try to take over if it dies."""

    def __init__(self, repository: JobRepository, redis: Redis, leader: LeaderElection) -> None:
        self.repository = repository
        self._redis = redis
        self._leader = leader
        self._queue = PriorityQueue()
        self._dispatch_lock = asyncio.Lock()

    async def submit_batch(self, jobs: list[NewJob]) -> dict[str, JobRecord]:
        refs = [job.ref for job in jobs]
        if len(refs) != len(set(refs)):
            raise DuplicateRefError("duplicate `ref` values in batch")

        ref_set = set(refs)
        dependencies = {job.ref: set(job.depends_on) for job in jobs}
        for ref, deps in dependencies.items():
            unknown = deps - ref_set
            if unknown:
                raise UnknownDependencyError(
                    f"{ref} depends on unknown ref(s): {sorted(unknown)}"
                )

        topological_order(dependencies)  # raises CycleDetectedError if invalid

        job_dicts = [job.model_dump() for job in jobs]
        depends_on_by_ref = {job.ref: job.depends_on for job in jobs}
        return await self.repository.create_batch(job_dicts, depends_on_by_ref)

    async def get_job(self, job_id: str) -> JobRecord | None:
        return await self.repository.get(job_id)

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        increment_attempt: bool = False,
    ) -> JobRecord | None:
        return await self.repository.update_status(
            job_id, status, error=error, increment_attempt=increment_attempt
        )

    async def refresh_ready_jobs(self) -> int:
        candidate_ids = await self.repository.find_ready_candidates()
        if not candidate_ids:
            return 0
        records = await self.repository.mark_ready(candidate_ids)
        for record in records:
            self._queue.push(record.id, record.priority)
        return len(records)

    async def dispatch_next(self) -> str | None:
        """Pop the highest-priority READY job and hand it to the worker
        pool via Redis. Guarded by a lock so two concurrent dispatch calls
        within this process can't both pop-and-claim the same heap entry;
        mark_dispatched is also a conditional UPDATE for defense in depth."""
        async with self._dispatch_lock:
            job_id = self._queue.pop()
            if job_id is None:
                return None
            claimed = await self.repository.mark_dispatched(job_id)
            if not claimed:
                return None
            record = await self.repository.get(job_id)
            await push_job(self._redis, job_id, record.payload if record else {})
            return job_id

    async def run_once(self) -> None:
        if not await self._leader.try_acquire():
            return
        await self.refresh_ready_jobs()
        while self._queue:
            if await self.dispatch_next() is None:
                break

    async def run_forever(self, stop_event: asyncio.Event, poll_interval: float) -> None:
        while not stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("scheduler dispatch loop iteration failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass
