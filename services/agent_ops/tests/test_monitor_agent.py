import httpx
import respx

from app.monitor_agent import run_monitor
from tests.conftest import RATE_LIMITER_BASE_URL, SCHEDULER_BASE_URL


@respx.mock
async def test_reports_queue_depth_without_client_id(scheduler_client, rate_limiter_client):
    respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs/stats").mock(
        return_value=httpx.Response(200, json={"counts": {"PENDING": 3, "DLQ": 1}})
    )

    response_text, data = await run_monitor(scheduler_client, rate_limiter_client)

    assert data["queue_depth"] == {"PENDING": 3, "DLQ": 1}
    assert "rate_limit" not in data
    assert "Queue depth" in response_text


@respx.mock
async def test_reports_rate_limit_when_client_id_given(scheduler_client, rate_limiter_client):
    respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs/stats").mock(
        return_value=httpx.Response(200, json={"counts": {}})
    )
    respx.get(f"{RATE_LIMITER_BASE_URL}/v1/rate-limit/status").mock(
        return_value=httpx.Response(
            200, json={"algorithm": "token_bucket", "remaining": 15.0, "limit": 20.0}
        )
    )

    response_text, data = await run_monitor(scheduler_client, rate_limiter_client, client_id="acme")

    assert data["rate_limit"]["remaining"] == 15.0
    assert "acme" in response_text


@respx.mock
async def test_scheduler_unavailable_does_not_crash():
    async with httpx.AsyncClient() as http:
        from app.rate_limiter_client import RateLimiterClient
        from app.scheduler_client import SchedulerClient

        scheduler_client = SchedulerClient(http, SCHEDULER_BASE_URL)
        rate_limiter_client = RateLimiterClient(http, RATE_LIMITER_BASE_URL)

        respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs/stats").mock(side_effect=httpx.ConnectError("down"))

        response_text, data = await run_monitor(scheduler_client, rate_limiter_client)

    assert "queue_depth" not in data
    assert "unavailable" in response_text
