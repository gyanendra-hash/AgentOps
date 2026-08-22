import fakeredis
import pytest
from httpx import ASGITransport, AsyncClient

from agentops_common.queue import push_dlq
from app.main import app


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch):
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr("app.main.get_redis", lambda: fake)
    monkeypatch.setattr("app.redis_client.get_redis", lambda: fake)
    return fake


async def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_health_endpoint():
    async with await _client() as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_dlq_empty_by_default():
    async with await _client() as client:
        response = await client.get("/v1/dlq")

    assert response.status_code == 200
    assert response.json() == {"jobs": []}


async def test_dlq_lists_pushed_jobs(_patch_redis):
    await push_dlq(_patch_redis, "job-1", {"x": 1}, "boom")

    async with await _client() as client:
        response = await client.get("/v1/dlq")

    body = response.json()
    assert len(body["jobs"]) == 1
    assert body["jobs"][0]["job_id"] == "job-1"
    assert body["jobs"][0]["error"] == "boom"
