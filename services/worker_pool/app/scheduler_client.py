import httpx

from agentops_common.models import JobResponse, JobStatus


class SchedulerUnavailableError(Exception):
    pass


class SchedulerClient:
    """Thin wrapper over the Scheduler's REST API. The worker pool never
    touches Postgres directly -- the Scheduler owns job state, so status
    transitions go through here (mirrors gateway/rate_limit_client.py)."""

    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def get_job(self, job_id: str) -> JobResponse | None:
        try:
            response = await self._client.get(f"{self._base_url}/v1/jobs/{job_id}")
        except httpx.HTTPError as exc:
            raise SchedulerUnavailableError(str(exc)) from exc

        if response.status_code == 404:
            return None
        response.raise_for_status()
        return JobResponse.model_validate(response.json())

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        increment_attempt: bool = False,
    ) -> JobResponse | None:
        try:
            response = await self._client.patch(
                f"{self._base_url}/v1/jobs/{job_id}/status",
                json={
                    "status": status.value,
                    "error": error,
                    "increment_attempt": increment_attempt,
                },
            )
        except httpx.HTTPError as exc:
            raise SchedulerUnavailableError(str(exc)) from exc

        if response.status_code == 404:
            return None
        response.raise_for_status()
        return JobResponse.model_validate(response.json())
