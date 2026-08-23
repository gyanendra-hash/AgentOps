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


async def test_list_jobs_filters_by_status_query_param():
    async with await _client() as client:
        await client.post("/v1/jobs", json={"jobs": [{"ref": "a", "name": "a"}]})
        submit_response = await client.post("/v1/jobs", json={"jobs": [{"ref": "b", "name": "b"}]})
        job_id = submit_response.json()["jobs"][0]["id"]
        await client.patch(f"/v1/jobs/{job_id}/status", json={"status": "DLQ", "error": "boom"})

        all_response = await client.get("/v1/jobs")
        dlq_response = await client.get("/v1/jobs", params={"status": "DLQ"})

    assert len(all_response.json()["jobs"]) == 2
    dlq_jobs = dlq_response.json()["jobs"]
    assert len(dlq_jobs) == 1
    assert dlq_jobs[0]["id"] == job_id


async def test_cancel_job_endpoint_succeeds_for_pending_job():
    async with await _client() as client:
        submit_response = await client.post("/v1/jobs", json={"jobs": [{"ref": "a", "name": "a"}]})
        job_id = submit_response.json()["jobs"][0]["id"]

        cancel_response = await client.post(f"/v1/jobs/{job_id}/cancel")

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "CANCELLED"


async def test_cancel_job_endpoint_returns_409_when_already_dispatched():
    async with await _client() as client:
        submit_response = await client.post("/v1/jobs", json={"jobs": [{"ref": "a", "name": "a"}]})
        job_id = submit_response.json()["jobs"][0]["id"]
        await client.patch(f"/v1/jobs/{job_id}/status", json={"status": "DISPATCHED"})

        cancel_response = await client.post(f"/v1/jobs/{job_id}/cancel")

    assert cancel_response.status_code == 409


async def test_cancel_job_endpoint_returns_404_for_unknown_job():
    async with await _client() as client:
        response = await client.post("/v1/jobs/does-not-exist/cancel")

    assert response.status_code == 404


async def test_job_stats_endpoint_returns_counts_by_status():
    async with await _client() as client:
        await client.post("/v1/jobs", json={"jobs": [{"ref": "a", "name": "a"}]})
        submit_response = await client.post("/v1/jobs", json={"jobs": [{"ref": "b", "name": "b"}]})
        job_id = submit_response.json()["jobs"][0]["id"]
        await client.patch(f"/v1/jobs/{job_id}/status", json={"status": "DLQ", "error": "boom"})

        stats_response = await client.get("/v1/jobs/stats")

    assert stats_response.status_code == 200
    counts = stats_response.json()["counts"]
    assert counts["DLQ"] == 1
    assert counts["PENDING"] == 1


async def test_job_stats_route_does_not_collide_with_job_id_route():
    # regression: /v1/jobs/stats must resolve to the stats route, not
    # GET /v1/jobs/{job_id} with job_id="stats"
    async with await _client() as client:
        response = await client.get("/v1/jobs/stats")

    assert response.status_code == 200
    assert "counts" in response.json()
