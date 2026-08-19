import json

import httpx
import respx
from starlette.testclient import TestClient

from app.config import get_settings
from app.main import app

RATE_LIMITER_URL = "http://rate-limiter.test"
BACKEND_URL = "http://backend.test"


def _client(monkeypatch, fail_open: bool = True) -> TestClient:
    monkeypatch.setenv("RATE_LIMITER_URL", RATE_LIMITER_URL)
    monkeypatch.setenv(
        "ROUTING_TABLE", json.dumps({"backend": [BACKEND_URL]})
    )
    monkeypatch.setenv("FAIL_OPEN", "true" if fail_open else "false")
    get_settings.cache_clear()
    return TestClient(app)


def test_health_endpoint(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@respx.mock
def test_allowed_request_is_forwarded_to_backend(monkeypatch):
    respx.post(f"{RATE_LIMITER_URL}/v1/rate-limit/check").mock(
        return_value=httpx.Response(
            200,
            json={
                "allowed": True,
                "algorithm": "token_bucket",
                "remaining": 5,
                "limit": 10,
                "retry_after": None,
            },
        )
    )
    respx.get(f"{BACKEND_URL}/ping").mock(
        return_value=httpx.Response(200, json={"pong": True})
    )

    with _client(monkeypatch) as client:
        response = client.get("/api/ping", headers={"X-Client-Id": "acme"})

    assert response.status_code == 200
    assert response.json() == {"pong": True}


@respx.mock
def test_denied_request_returns_429_with_retry_after(monkeypatch):
    respx.post(f"{RATE_LIMITER_URL}/v1/rate-limit/check").mock(
        return_value=httpx.Response(
            200,
            json={
                "allowed": False,
                "algorithm": "token_bucket",
                "remaining": 0,
                "limit": 10,
                "retry_after": 2.5,
            },
        )
    )

    with _client(monkeypatch) as client:
        response = client.get("/api/ping", headers={"X-Client-Id": "acme"})

    assert response.status_code == 429
    assert response.headers["retry-after"] == "3"


@respx.mock
def test_fails_open_when_rate_limiter_unreachable(monkeypatch):
    respx.post(f"{RATE_LIMITER_URL}/v1/rate-limit/check").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    respx.get(f"{BACKEND_URL}/ping").mock(
        return_value=httpx.Response(200, json={"pong": True})
    )

    with _client(monkeypatch, fail_open=True) as client:
        response = client.get("/api/ping", headers={"X-Client-Id": "acme"})

    assert response.status_code == 200
    assert response.json() == {"pong": True}


@respx.mock
def test_fails_closed_when_rate_limiter_unreachable(monkeypatch):
    respx.post(f"{RATE_LIMITER_URL}/v1/rate-limit/check").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    with _client(monkeypatch, fail_open=False) as client:
        response = client.get("/api/ping", headers={"X-Client-Id": "acme"})

    assert response.status_code == 503


@respx.mock
def test_no_healthy_backend_returns_503(monkeypatch):
    respx.post(f"{RATE_LIMITER_URL}/v1/rate-limit/check").mock(
        return_value=httpx.Response(
            200,
            json={
                "allowed": True,
                "algorithm": "token_bucket",
                "remaining": 5,
                "limit": 10,
                "retry_after": None,
            },
        )
    )
    monkeypatch.setenv("RATE_LIMITER_URL", RATE_LIMITER_URL)
    monkeypatch.setenv("ROUTING_TABLE", json.dumps({"backend": []}))
    monkeypatch.setenv("FAIL_OPEN", "true")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get("/api/ping", headers={"X-Client-Id": "acme"})

    assert response.status_code == 503
