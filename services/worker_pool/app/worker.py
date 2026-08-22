import asyncio
import logging
import time

from redis.asyncio import Redis

from agentops_common.models import JobStatus
from agentops_common.queue import pop_job, promote_due_retries, push_dlq, schedule_retry
from app.retry import next_backoff_seconds, should_retry
from app.scheduler_client import SchedulerClient

logger = logging.getLogger(__name__)


class Worker:
    def __init__(
        self,
        redis: Redis,
        scheduler_client: SchedulerClient,
        *,
        max_retries: int = 3,
        base_backoff_seconds: float = 1.0,
        poll_timeout_seconds: float = 2.0,
        simulate_failure_key: str = "simulate_failure",
    ) -> None:
        self._redis = redis
        self._scheduler = scheduler_client
        self._max_retries = max_retries
        self._base_backoff_seconds = base_backoff_seconds
        self._poll_timeout_seconds = poll_timeout_seconds
        self._simulate_failure_key = simulate_failure_key

    async def execute_mock_task(self, payload: dict) -> None:
        """Placeholder task execution (ROADMAP 2.5: "execute mock task").
        A real task handler/dispatch table is out of scope for Milestone 2;
        this just simulates success/failure so retry+DLQ logic is
        exercisable end-to-end. `payload["simulate_failure"]: true` forces a
        failure, which is what the tests use."""
        await asyncio.sleep(0)
        if payload.get(self._simulate_failure_key):
            raise RuntimeError(payload.get("failure_reason", "simulated failure"))

    async def process_one(self, job_id: str, payload: dict) -> None:
        try:
            await self._scheduler.update_status(job_id, JobStatus.RUNNING)
            await self.execute_mock_task(payload)
        except Exception as exc:
            await self._handle_failure(job_id, payload, str(exc))
            return
        await self._scheduler.update_status(job_id, JobStatus.SUCCEEDED)

    async def _handle_failure(self, job_id: str, payload: dict, error: str) -> None:
        job = await self._scheduler.get_job(job_id)
        attempt_before = job.attempt if job is not None else 0
        attempt_after = attempt_before + 1

        if should_retry(attempt_after, self._max_retries):
            await self._scheduler.update_status(
                job_id, JobStatus.RETRY, error=error, increment_attempt=True
            )
            delay = next_backoff_seconds(attempt_after, self._base_backoff_seconds)
            await schedule_retry(self._redis, job_id, payload, time.time() + delay)
            logger.info("job %s failed (attempt %d), retrying in %.1fs", job_id, attempt_after, delay)
        else:
            await self._scheduler.update_status(
                job_id, JobStatus.DLQ, error=error, increment_attempt=True
            )
            await push_dlq(self._redis, job_id, payload, error)
            logger.warning("job %s exhausted retries, moved to DLQ", job_id)

    async def run_once(self) -> bool:
        await promote_due_retries(self._redis, time.time())
        job = await pop_job(self._redis, timeout=self._poll_timeout_seconds)
        if job is None:
            return False
        await self.process_one(job["job_id"], job["payload"])
        return True

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("worker loop iteration failed")
