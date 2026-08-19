import httpx

from agentops_common.models import RateLimitCheckResponse
from app.config import get_settings


class RateLimiterUnavailableError(Exception):
    pass


async def check_rate_limit(client: httpx.AsyncClient, client_id: str, tier: str) -> RateLimitCheckResponse:
    settings = get_settings()
    try:
        response = await client.post(
            f"{settings.rate_limiter_url}/v1/rate-limit/check",
            json={"client_id": client_id, "tier": tier},
            timeout=1.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RateLimiterUnavailableError(str(exc)) from exc

    return RateLimitCheckResponse.model_validate(response.json())
