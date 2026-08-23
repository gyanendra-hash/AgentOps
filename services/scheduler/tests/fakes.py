"""In-memory stand-in for PostgresJobRepository, implementing the same
JobRepository protocol, so scheduler logic can be unit-tested without a real
Postgres instance -- the same trade-off the rest of the codebase makes by
testing against fakeredis instead of real Redis."""

import uuid
from datetime import datetime, timezone

from agentops_common.models import JobStatus
from app.repository import CANCELLABLE_STATUSES, JobNotCancellableError, JobRecord


class InMemoryJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._depends_on: dict[str, list[str]] = {}

    async def create_batch(self, jobs, depends_on_by_ref):
        ref_to_id = {job["ref"]: str(uuid.uuid4()) for job in jobs}

        for job in jobs:
            job_id = ref_to_id[job["ref"]]
            depends_on_ids = [ref_to_id[ref] for ref in depends_on_by_ref.get(job["ref"], [])]
            now = datetime.now(timezone.utc)
            self._jobs[job_id] = JobRecord(
                id=job_id,
                name=job["name"],
                status=JobStatus.PENDING,
                priority=job["priority"],
                attempt=0,
                max_retries=job["max_retries"],
                payload=job["payload"],
                depends_on=depends_on_ids,
                error=None,
                created_at=now,
                updated_at=now,
            )
            self._depends_on[job_id] = depends_on_ids

        return {ref: self._jobs[job_id] for ref, job_id in ref_to_id.items()}

    async def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    async def find_ready_candidates(self) -> list[str]:
        candidates = []
        for job_id, record in self._jobs.items():
            if record.status != JobStatus.PENDING:
                continue
            deps = self._depends_on.get(job_id, [])
            if all(self._jobs[dep_id].status == JobStatus.SUCCEEDED for dep_id in deps):
                candidates.append(job_id)
        return candidates

    async def mark_ready(self, job_ids: list[str]) -> list[JobRecord]:
        updated = []
        for job_id in job_ids:
            record = self._jobs.get(job_id)
            if record is not None and record.status == JobStatus.PENDING:
                record.status = JobStatus.READY
                record.updated_at = datetime.now(timezone.utc)
                updated.append(record)
        return updated

    async def mark_dispatched(self, job_id: str) -> bool:
        record = self._jobs.get(job_id)
        if record is None or record.status != JobStatus.READY:
            return False
        record.status = JobStatus.DISPATCHED
        record.updated_at = datetime.now(timezone.utc)
        return True

    async def update_status(
        self, job_id: str, status: JobStatus, *, error: str | None = None, increment_attempt: bool = False
    ) -> JobRecord | None:
        record = self._jobs.get(job_id)
        if record is None:
            return None
        record.status = status
        record.error = error
        if increment_attempt:
            record.attempt += 1
        record.updated_at = datetime.now(timezone.utc)
        return record

    async def list_by_status(self, status: JobStatus | None) -> list[JobRecord]:
        records = list(self._jobs.values())
        if status is not None:
            records = [r for r in records if r.status == status]
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    async def cancel(self, job_id: str) -> JobRecord | None:
        record = self._jobs.get(job_id)
        if record is None:
            return None
        if record.status not in CANCELLABLE_STATUSES:
            raise JobNotCancellableError(job_id, record.status)
        record.status = JobStatus.CANCELLED
        record.updated_at = datetime.now(timezone.utc)
        return record
