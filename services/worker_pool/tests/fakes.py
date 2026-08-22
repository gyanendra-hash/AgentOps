"""In-memory stand-in for SchedulerClient (duck-typed: Worker only calls
get_job/update_status), so worker retry/DLQ logic is testable without a real
HTTP server."""

import uuid
from datetime import datetime, timezone

from agentops_common.models import JobResponse, JobStatus


class FakeSchedulerClient:
    def __init__(self) -> None:
        self.jobs: dict[str, JobResponse] = {}
        self.status_history: list[tuple[str, JobStatus]] = []

    def seed(self, job_id: str | None = None, **overrides) -> str:
        job_id = job_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        defaults = dict(
            id=job_id,
            name="job",
            status=JobStatus.DISPATCHED,
            priority=0,
            attempt=0,
            max_retries=3,
            payload={},
            depends_on=[],
            error=None,
            created_at=now,
            updated_at=now,
        )
        defaults.update(overrides)
        self.jobs[job_id] = JobResponse(**defaults)
        return job_id

    async def get_job(self, job_id: str) -> JobResponse | None:
        return self.jobs.get(job_id)

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        increment_attempt: bool = False,
    ) -> JobResponse | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        self.status_history.append((job_id, status))
        updated = job.model_copy(
            update={
                "status": status,
                "error": error,
                "attempt": job.attempt + (1 if increment_attempt else 0),
            }
        )
        self.jobs[job_id] = updated
        return updated
