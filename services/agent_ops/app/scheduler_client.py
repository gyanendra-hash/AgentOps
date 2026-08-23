"""Thin wrapper over the Scheduler's REST API (ROADMAP 4.2) -- tool
functions call these instead of touching Postgres or re-implementing
scheduling logic, per SRS 6.5.4: "the agent never re-implements scheduling
logic." One retry on transient connection/timeout errors (ROADMAP 4.6)."""

import uuid

import httpx


class SchedulerUnavailableError(Exception):
    pass


class SchedulerClient:
    def __init__(self, client: httpx.AsyncClient, base_url: str, *, max_attempts: int = 2) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._max_attempts = max_attempts

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await self._client.request(method, f"{self._base_url}{path}", **kwargs)
            except httpx.TransportError as exc:
                last_error = exc
                if attempt == self._max_attempts:
                    break
        raise SchedulerUnavailableError(str(last_error)) from last_error

    async def create_job(self, name: str, *, priority: int = 0, payload: dict | None = None) -> dict:
        response = await self._request(
            "POST",
            "/v1/jobs",
            json={
                "jobs": [
                    {
                        "ref": str(uuid.uuid4()),
                        "name": name,
                        "priority": priority,
                        "payload": payload or {},
                    }
                ]
            },
        )
        response.raise_for_status()
        return response.json()["jobs"][0]

    async def get_job(self, job_id: str) -> dict | None:
        response = await self._request("GET", f"/v1/jobs/{job_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def cancel_job(self, job_id: str) -> dict:
        response = await self._request("POST", f"/v1/jobs/{job_id}/cancel")
        response.raise_for_status()
        return response.json()

    async def list_jobs(self, status: str | None = None) -> list[dict]:
        params = {"status": status} if status else {}
        response = await self._request("GET", "/v1/jobs", params=params)
        response.raise_for_status()
        return response.json()["jobs"]
