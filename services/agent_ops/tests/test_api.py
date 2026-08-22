"""Sets `app.state.graph` directly, bypassing the real lifespan (which opens
a Postgres pool and instantiates real embedding/LLM providers), the same
pattern services/scheduler/tests/test_api.py uses -- ASGITransport doesn't
drive lifespan events, so no Docker, Postgres, or API key is needed here."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.graph import build_graph
from app.ingest import ingest_text
from app.main import app


@pytest.fixture(autouse=True)
async def _graph(embedding_provider, repository, reranker, answer_generator):
    await ingest_text(
        "## Scenario: Test\n\nThe gateway returns 503 when the rate limiter is unreachable.",
        "runbook",
        embedding_provider,
        repository,
    )
    app.state.graph = build_graph(embedding_provider, repository, reranker, answer_generator, top_k=3)


async def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_health_endpoint():
    async with await _client() as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ask_returns_grounded_answer():
    async with await _client() as client:
        response = await client.post("/v1/debug/ask", json={"question": "why is the gateway returning 503"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"]
    assert body["sources"] == ["runbook"]


async def test_ask_with_unrelated_question_still_returns_200():
    async with await _client() as client:
        response = await client.post("/v1/debug/ask", json={"question": "what's the weather today"})

    assert response.status_code == 200
