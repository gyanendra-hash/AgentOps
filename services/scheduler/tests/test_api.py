"""API tests set `app.state.scheduler` directly (bypassing the real
lifespan's Postgres pool creation, which never runs here since ASGITransport
doesn't drive lifespan events) so the test suite stays fully in-process, same
as rate_limiter's tests/test_api.py."""

import fakeredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.dispatcher import Scheduler
from app.leader_election import LeaderElection
from app.main import app
from tests.fakes import InMemoryJobRepository


@pytest.fixture(autouse=True)
def _scheduler():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    leader = LeaderElection(redis, "test:leader", ttl_seconds=5.0)
    app.state.scheduler = Scheduler(InMemoryJobRepository(), redis, leader)


async def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_health_endpoint():
    async with await _client() as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_submit_single_job():
    async with await _client() as client:
        response = await client.post(
            "/v1/jobs", json={"jobs": [{"ref": "a", "name": "do-thing", "priority": 5}]}
        )

    assert response.status_code == 201
    body = response.json()
    assert len(body["jobs"]) == 1
    assert body["jobs"][0]["status"] == "PENDING"
    assert body["jobs"][0]["priority"] == 5


async def test_submit_batch_preserves_request_order_in_response():
    async with await _client() as client:
        response = await client.post(
            "/v1/jobs",
            json={
                "jobs": [
                    {"ref": "b", "name": "b"},
                    {"ref": "a", "name": "a", "depends_on": []},
                ]
            },
        )

    assert response.status_code == 201
    names = [job["name"] for job in response.json()["jobs"]]
    assert names == ["b", "a"]


async def test_submit_batch_with_cycle_returns_422():
    async with await _client() as client:
        response = await client.post(
            "/v1/jobs",
            json={
                "jobs": [
                    {"ref": "a", "name": "a", "depends_on": ["b"]},
                    {"ref": "b", "name": "b", "depends_on": ["a"]},
                ]
            },
        )

    assert response.status_code == 422


async def test_get_job_roundtrip():
    async with await _client() as client:
        submit_response = await client.post(
            "/v1/jobs", json={"jobs": [{"ref": "a", "name": "a"}]}
        )
        job_id = submit_response.json()["jobs"][0]["id"]

        get_response = await client.get(f"/v1/jobs/{job_id}")

    assert get_response.status_code == 200
    assert get_response.json()["id"] == job_id


async def test_get_unknown_job_returns_404():
    async with await _client() as client:
        response = await client.get("/v1/jobs/does-not-exist")

    assert response.status_code == 404


async def test_patch_job_status_updates_and_returns_job():
    async with await _client() as client:
        submit_response = await client.post(
            "/v1/jobs", json={"jobs": [{"ref": "a", "name": "a"}]}
        )
        job_id = submit_response.json()["jobs"][0]["id"]

        patch_response = await client.patch(
            f"/v1/jobs/{job_id}/status",
            json={"status": "RUNNING", "increment_attempt": True},
        )

    assert patch_response.status_code == 200
    body = patch_response.json()
    assert body["status"] == "RUNNING"
    assert body["attempt"] == 1


async def test_patch_unknown_job_returns_404():
    async with await _client() as client:
        response = await client.patch(
            "/v1/jobs/does-not-exist/status", json={"status": "RUNNING"}
        )

    assert response.status_code == 404
