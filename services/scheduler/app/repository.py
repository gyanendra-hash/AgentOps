from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agentops_common.models import JobStatus


#: Statuses a job can still be cancelled from -- once DISPATCHED, a worker
#: may already be executing it, so cancellation is refused rather than
#: racing the Worker Pool.
CANCELLABLE_STATUSES = {JobStatus.PENDING, JobStatus.READY, JobStatus.RETRY}


class JobNotCancellableError(Exception):
    def __init__(self, job_id: str, status: JobStatus) -> None:
        self.job_id = job_id
        self.status = status
        super().__init__(f"job {job_id} cannot be cancelled from status {status.value}")


@dataclass
class JobRecord:
    id: str
    name: str
    status: JobStatus
    priority: int
    attempt: int
    max_retries: int
    payload: dict
    depends_on: list[str]
    error: str | None
    created_at: datetime
    updated_at: datetime


class JobRepository(Protocol):
    """Storage boundary for job state. `PostgresJobRepository` is the real
    implementation; tests use an in-memory fake behind the same interface
    (tests/fakes.py) the same way the rest of the codebase swaps fakeredis in
    for real Redis, so the scheduler's dispatch logic is fully unit-testable
    without Docker or a live database."""

    async def create_batch(
        self, jobs: list[dict], depends_on_by_ref: dict[str, list[str]]
    ) -> dict[str, JobRecord]: ...

    async def get(self, job_id: str) -> JobRecord | None: ...

    async def find_ready_candidates(self) -> list[str]:
        """PENDING jobs whose dependencies (if any) have all SUCCEEDED."""
        ...

    async def mark_ready(self, job_ids: list[str]) -> list[JobRecord]:
        """PENDING -> READY for the given ids; returns the ones actually
        transitioned (already-moved ids are silently skipped)."""
        ...

    async def mark_dispatched(self, job_id: str) -> bool:
        """READY -> DISPATCHED. Returns False if the job wasn't READY
        (e.g. already claimed by a concurrent dispatch)."""
        ...

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        increment_attempt: bool = False,
    ) -> JobRecord | None: ...

    async def list_by_status(self, status: JobStatus | None) -> list[JobRecord]:
        """All jobs, or all jobs in `status` if given. Newest first."""
        ...

    async def cancel(self, job_id: str) -> JobRecord | None:
        """None if `job_id` doesn't exist. Raises JobNotCancellableError if
        it exists but isn't in a cancellable status (see
        CANCELLABLE_STATUSES) -- otherwise transitions it to CANCELLED."""
        ...
