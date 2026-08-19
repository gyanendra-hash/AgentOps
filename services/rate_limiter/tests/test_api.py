import fakeredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch):
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr("app.main.get_redis", lambda: fake)
    monkeypatch.setattr("app.redis_client.get_redis", lambda: fake)


async def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_health_endpoint():
    async with await _client() as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_check_allows_first_request():
    async with await _client() as client:
        response = await client.post(
            "/v1/rate-limit/check", json={"client_id": "acme", "tier": "default"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is True
    assert body["algorithm"] == "token_bucket"


async def test_check_denies_after_capacity_exhausted():
    async with await _client() as client:
        for _ in range(20):
            await client.post(
                "/v1/rate-limit/check", json={"client_id": "burst", "tier": "default"}
            )
        response = await client.post(
            "/v1/rate-limit/check", json={"client_id": "burst", "tier": "default"}
        )

    body = response.json()
    assert body["allowed"] is False
    assert body["retry_after"] is not None


async def test_unknown_tier_returns_404():
    async with await _client() as client:
        response = await client.post(
            "/v1/rate-limit/check", json={"client_id": "acme", "tier": "nope"}
        )

    assert response.status_code == 404
