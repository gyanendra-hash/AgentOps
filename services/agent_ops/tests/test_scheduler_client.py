"""Mocks at the HTTP boundary with respx (same style as gateway's
tests/test_proxy.py) rather than faking SchedulerClient itself, so its
retry-on-transient-failure logic (ROADMAP 4.6) is exercised for real."""

import httpx
import pytest
import respx

from app.scheduler_client import SchedulerUnavailableError
from tests.conftest import SCHEDULER_BASE_URL


@respx.mock
async def test_create_job(scheduler_client):
    respx.post(f"{SCHEDULER_BASE_URL}/v1/jobs").mock(
        return_value=httpx.Response(
            201,
            json={"jobs": [{"id": "job-1", "name": "extract", "status": "PENDING"}]},
        )
    )

    job = await scheduler_client.create_job("extract", priority=5)

    assert job["id"] == "job-1"


@respx.mock
async def test_get_job_found(scheduler_client):
    respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs/job-1").mock(
        return_value=httpx.Response(200, json={"id": "job-1", "status": "RUNNING"})
    )

    job = await scheduler_client.get_job("job-1")

    assert job["status"] == "RUNNING"


@respx.mock
async def test_get_job_not_found_returns_none(scheduler_client):
    respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs/ghost").mock(return_value=httpx.Response(404))

    assert await scheduler_client.get_job("ghost") is None


@respx.mock
async def test_cancel_job_raises_on_409(scheduler_client):
    respx.post(f"{SCHEDULER_BASE_URL}/v1/jobs/job-1/cancel").mock(
        return_value=httpx.Response(409, json={"detail": "already dispatched"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await scheduler_client.cancel_job("job-1")


@respx.mock
async def test_list_jobs_with_status_filter(scheduler_client):
    route = respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": [{"id": "job-1", "status": "DLQ"}]})
    )

    jobs = await scheduler_client.list_jobs(status="DLQ")

    assert route.calls.last.request.url.params["status"] == "DLQ"
    assert len(jobs) == 1


@respx.mock
async def test_transient_failure_is_retried_once(scheduler_client):
    route = respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs/job-1").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={"id": "job-1"})]
    )

    job = await scheduler_client.get_job("job-1")

    assert job["id"] == "job-1"
    assert route.call_count == 2


@respx.mock
async def test_persistent_failure_raises_scheduler_unavailable(scheduler_client):
    respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs/job-1").mock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(SchedulerUnavailableError):
        await scheduler_client.get_job("job-1")
