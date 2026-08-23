"""Thin wrapper over the Rate Limiter's read-only status endpoint (ROADMAP
5.3), same shape/retry behavior as scheduler_client.py."""

import httpx


class RateLimiterUnavailableError(Exception):
    pass


class RateLimiterClient:
    def __init__(self, client: httpx.AsyncClient, base_url: str, *, max_attempts: int = 2) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._max_attempts = max_attempts

    async def _get(self, path: str, **kwargs) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await self._client.get(f"{self._base_url}{path}", **kwargs)
            except httpx.TransportError as exc:
                last_error = exc
                if attempt == self._max_attempts:
                    break
        raise RateLimiterUnavailableError(str(last_error)) from last_error

    async def status(self, client_id: str, tier: str = "default") -> dict:
        response = await self._get(
            "/v1/rate-limit/status", params={"client_id": client_id, "tier": tier}
        )
        response.raise_for_status()
        return response.json()
