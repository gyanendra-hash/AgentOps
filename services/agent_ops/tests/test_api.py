"""Sets `app.state.graph` / `app.state.scheduler_agent_graph` directly,
bypassing the real lifespan (which opens a Postgres pool and instantiates
real embedding/LLM providers), the same pattern
services/scheduler/tests/test_api.py uses -- ASGITransport doesn't drive
lifespan events, so no Docker, Postgres, or API key is needed here."""

import httpx
import pytest
import respx

from app.graph import build_graph
from app.ingest import ingest_text
from app.main import app
from app.scheduler_agent import build_scheduler_agent_graph
from app.tool_llm import ToolDecision
from tests.conftest import SCHEDULER_BASE_URL
from tests.fakes import FakeToolCallingLLM


@pytest.fixture(autouse=True)
async def _graph(embedding_provider, repository, reranker, answer_generator):
    await ingest_text(
        "## Scenario: Test\n\nThe gateway returns 503 when the rate limiter is unreachable.",
        "runbook",
        embedding_provider,
        repository,
    )
    app.state.graph = build_graph(embedding_provider, repository, reranker, answer_generator, top_k=3)


@pytest.fixture(autouse=True)
async def _scheduler_agent(scheduler_client, pending_actions):
    app.state.scheduler_client = scheduler_client
    app.state.pending_actions = pending_actions
    tool_llm = FakeToolCallingLLM(
        decisions={
            "cancel job job-1": ToolDecision(tool_name="cancel_job", args={"job_id": "job-1"}),
        }
    )
    app.state.scheduler_agent_graph = build_scheduler_agent_graph(
        scheduler_client, tool_llm, pending_actions
    )


async def _client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


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


@respx.mock
async def test_agent_schedule_requires_confirmation_for_cancel():
    async with await _client() as client:
        response = await client.post("/v1/agent/schedule", json={"question": "cancel job job-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["needs_confirmation"] is True
    assert body["confirmation_token"]


@respx.mock
async def test_agent_confirm_executes_the_pending_cancel():
    respx.post(f"{SCHEDULER_BASE_URL}/v1/jobs/job-1/cancel").mock(
        return_value=httpx.Response(200, json={"id": "job-1", "status": "CANCELLED"})
    )

    async with await _client() as client:
        schedule_response = await client.post("/v1/agent/schedule", json={"question": "cancel job job-1"})
        token = schedule_response.json()["confirmation_token"]

        confirm_response = await client.post(
            "/v1/agent/confirm", json={"confirmation_token": token, "confirmed": True}
        )

    assert confirm_response.status_code == 200
    assert confirm_response.json()["result"]["status"] == "CANCELLED"


async def test_agent_confirm_declining_takes_no_action():
    async with await _client() as client:
        schedule_response = await client.post("/v1/agent/schedule", json={"question": "cancel job job-1"})
        token = schedule_response.json()["confirmation_token"]

        confirm_response = await client.post(
            "/v1/agent/confirm", json={"confirmation_token": token, "confirmed": False}
        )

    assert confirm_response.status_code == 200
    assert "Cancelled" in confirm_response.json()["response"]


async def test_agent_confirm_unknown_token_is_handled_gracefully():
    async with await _client() as client:
        response = await client.post(
            "/v1/agent/confirm", json={"confirmation_token": "never-existed", "confirmed": True}
        )

    assert response.status_code == 200
    assert "expired" in response.json()["response"] or "already used" in response.json()["response"]
