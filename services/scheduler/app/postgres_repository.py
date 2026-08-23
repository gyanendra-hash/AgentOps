from __future__ import annotations

import asyncio
import uuid

import asyncpg

from agentops_common.models import JobStatus
from app.repository import CANCELLABLE_STATUSES, JobNotCancellableError, JobRecord

_GET_QUERY = """
    SELECT j.id, j.name, j.status, j.priority, j.attempt, j.max_retries,
           j.payload, j.error, j.created_at, j.updated_at,
           COALESCE(
               array_agg(jd.depends_on_id) FILTER (WHERE jd.depends_on_id IS NOT NULL),
               '{}'
           ) AS depends_on
    FROM jobs j
    LEFT JOIN job_dependencies jd ON jd.job_id = j.id
    WHERE j.id = $1::uuid
    GROUP BY j.id
"""

_READY_CANDIDATES_QUERY = """
    SELECT j.id FROM jobs j
    WHERE j.status = 'PENDING'
    AND NOT EXISTS (
        SELECT 1 FROM job_dependencies jd
        JOIN jobs dep ON dep.id = jd.depends_on_id
        WHERE jd.job_id = j.id AND dep.status != 'SUCCEEDED'
    )
"""


def _row_to_record(row: asyncpg.Record) -> JobRecord:
    return JobRecord(
        id=str(row["id"]),
        name=row["name"],
        status=JobStatus(row["status"]),
        priority=row["priority"],
        attempt=row["attempt"],
        max_retries=row["max_retries"],
        payload=row["payload"],
        depends_on=[str(d) for d in row["depends_on"]],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class PostgresJobRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_batch(
        self, jobs: list[dict], depends_on_by_ref: dict[str, list[str]]
    ) -> dict[str, JobRecord]:
        ref_to_id = {job["ref"]: str(uuid.uuid4()) for job in jobs}

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for job in jobs:
                    await conn.execute(
                        """
                        INSERT INTO jobs (id, name, priority, payload, max_retries, status)
                        VALUES ($1::uuid, $2, $3, $4::jsonb, $5, 'PENDING')
                        """,
                        ref_to_id[job["ref"]],
                        job["name"],
                        job["priority"],
                        job["payload"],
                        job["max_retries"],
                    )
                for ref, dep_refs in depends_on_by_ref.items():
                    for dep_ref in dep_refs:
                        await conn.execute(
                            """
                            INSERT INTO job_dependencies (job_id, depends_on_id)
                            VALUES ($1::uuid, $2::uuid)
                            """,
                            ref_to_id[ref],
                            ref_to_id[dep_ref],
                        )

        records = await asyncio.gather(*(self.get(job_id) for job_id in ref_to_id.values()))
        return dict(zip(ref_to_id.keys(), records))

    async def get(self, job_id: str) -> JobRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(_GET_QUERY, job_id)
        return _row_to_record(row) if row else None

    async def find_ready_candidates(self) -> list[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_READY_CANDIDATES_QUERY)
        return [str(row["id"]) for row in rows]

    async def mark_ready(self, job_ids: list[str]) -> list[JobRecord]:
        query = """
            UPDATE jobs SET status = 'READY', updated_at = now()
            WHERE id = ANY($1::uuid[]) AND status = 'PENDING'
            RETURNING id
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, job_ids)
        updated_ids = [str(row["id"]) for row in rows]
        records = await asyncio.gather(*(self.get(job_id) for job_id in updated_ids))
        return [record for record in records if record is not None]

    async def mark_dispatched(self, job_id: str) -> bool:
        query = """
            UPDATE jobs SET status = 'DISPATCHED', updated_at = now()
            WHERE id = $1::uuid AND status = 'READY'
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(query, job_id)
        return result.endswith(" 1")

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        increment_attempt: bool = False,
    ) -> JobRecord | None:
        increment = 1 if increment_attempt else 0
        query = """
            UPDATE jobs
            SET status = $2, error = $3, attempt = attempt + $4, updated_at = now()
            WHERE id = $1::uuid
        """
        async with self._pool.acquire() as conn:
            await conn.execute(query, job_id, status.value, error, increment)
        return await self.get(job_id)

    async def list_by_status(self, status: JobStatus | None) -> list[JobRecord]:
        if status is None:
            query = "SELECT id FROM jobs ORDER BY created_at DESC"
            args: tuple = ()
        else:
            query = "SELECT id FROM jobs WHERE status = $1 ORDER BY created_at DESC"
            args = (status.value,)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
        records = await asyncio.gather(*(self.get(str(row["id"])) for row in rows))
        return [record for record in records if record is not None]

    async def cancel(self, job_id: str) -> JobRecord | None:
        record = await self.get(job_id)
        if record is None:
            return None
        if record.status not in CANCELLABLE_STATUSES:
            raise JobNotCancellableError(job_id, record.status)

        query = """
            UPDATE jobs SET status = 'CANCELLED', updated_at = now()
            WHERE id = $1::uuid AND status = ANY($2::text[])
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                query, job_id, [s.value for s in CANCELLABLE_STATUSES]
            )
        if not result.endswith(" 1"):
            # lost a race with another cancel/dispatch between the read above
            # and this write -- re-fetch and report the status honestly
            record = await self.get(job_id)
            raise JobNotCancellableError(job_id, record.status if record else JobStatus.CANCELLED)
        return await self.get(job_id)
