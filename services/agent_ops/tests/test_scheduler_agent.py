"""ROADMAP 4.3-4.6: the Scheduler Agent graph. The LLM decision is
preprogrammed via FakeToolCallingLLM (see its docstring for why) -- these
tests verify the routing/execution/confirmation plumbing around that
decision, which is what 4.3-4.5 actually specify."""

import httpx
import respx

from app.pending_actions import PendingActionStore
from app.scheduler_agent import build_scheduler_agent_graph, execute_confirmed_action
from app.tool_llm import ToolDecision
from tests.conftest import SCHEDULER_BASE_URL

INITIAL_STATE = {
    "tool_name": None,
    "tool_args": {},
    "rationale": "",
    "needs_confirmation": False,
    "confirmation_token": None,
    "result": None,
    "error": None,
    "response": "",
}


def _state(question: str) -> dict:
    return {"question": question, **INITIAL_STATE}


@respx.mock
async def test_nl_request_calls_create_job_with_right_arguments(scheduler_client, pending_actions):
    respx.post(f"{SCHEDULER_BASE_URL}/v1/jobs").mock(
        return_value=httpx.Response(201, json={"jobs": [{"id": "job-1", "name": "nightly-etl"}]})
    )
    tool_llm = _fake_llm(
        {
            "please create a job called nightly-etl with priority 5": ToolDecision(
                tool_name="create_job", args={"name": "nightly-etl", "priority": 5}
            )
        }
    )
    graph = build_scheduler_agent_graph(scheduler_client, tool_llm, pending_actions)

    result = await graph.ainvoke(_state("please create a job called nightly-etl with priority 5"))

    assert result["needs_confirmation"] is False
    assert result["result"]["id"] == "job-1"
    assert "create_job" in result["response"]


@respx.mock
async def test_destructive_tool_requires_confirmation_and_does_not_execute(
    scheduler_client, pending_actions
):
    cancel_route = respx.post(f"{SCHEDULER_BASE_URL}/v1/jobs/job-1/cancel")
    tool_llm = _fake_llm(
        {"cancel job job-1": ToolDecision(tool_name="cancel_job", args={"job_id": "job-1"})}
    )
    graph = build_scheduler_agent_graph(scheduler_client, tool_llm, pending_actions)

    result = await graph.ainvoke(_state("cancel job job-1"))

    assert result["needs_confirmation"] is True
    assert result["confirmation_token"] is not None
    assert not cancel_route.called  # not executed yet -- waiting on confirmation


@respx.mock
async def test_confirming_a_pending_cancel_executes_it(scheduler_client, pending_actions):
    respx.post(f"{SCHEDULER_BASE_URL}/v1/jobs/job-1/cancel").mock(
        return_value=httpx.Response(200, json={"id": "job-1", "status": "CANCELLED"})
    )
    tool_llm = _fake_llm(
        {"cancel job job-1": ToolDecision(tool_name="cancel_job", args={"job_id": "job-1"})}
    )
    graph = build_scheduler_agent_graph(scheduler_client, tool_llm, pending_actions)
    pending = await graph.ainvoke(_state("cancel job job-1"))

    response_text, result, error = await execute_confirmed_action(
        scheduler_client, pending_actions, pending["confirmation_token"]
    )

    assert error is None
    assert result["status"] == "CANCELLED"
    assert await pending_actions.get(pending["confirmation_token"]) is None  # consumed


async def test_declining_never_calls_execute_confirmed_action(scheduler_client, pending_actions):
    # Declining is handled at the API layer (deletes the token without ever
    # calling execute_confirmed_action) -- covered in tests/test_api.py.
    # This test just documents that redeeming an already-deleted/unknown
    # token is a safe no-op, not an error that crashes the request.
    response_text, result, error = await execute_confirmed_action(
        scheduler_client, pending_actions, "never-existed"
    )

    assert result is None
    assert error is None
    assert "expired" in response_text or "already used" in response_text


@respx.mock
async def test_no_matching_tool_responds_gracefully(scheduler_client, pending_actions):
    tool_llm = _fake_llm(default=ToolDecision(tool_name=None, rationale="that's not something I can help with"))
    graph = build_scheduler_agent_graph(scheduler_client, tool_llm, pending_actions)

    result = await graph.ainvoke(_state("what's the weather today"))

    assert result["needs_confirmation"] is False
    assert result["response"] == "that's not something I can help with"


@respx.mock
async def test_malformed_tool_args_produce_friendly_error_not_a_crash(scheduler_client, pending_actions):
    tool_llm = _fake_llm(
        {"get status of nothing": ToolDecision(tool_name="get_job_status", args={})}  # missing job_id
    )
    graph = build_scheduler_agent_graph(scheduler_client, tool_llm, pending_actions)

    result = await graph.ainvoke(_state("get status of nothing"))

    assert result["error"] is not None
    assert "invalid arguments" in result["response"]


@respx.mock
async def test_scheduler_timeout_produces_friendly_error_not_a_crash(scheduler_client, pending_actions):
    respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs/job-1").mock(side_effect=httpx.ConnectTimeout("timed out"))
    tool_llm = _fake_llm(
        {"status of job-1": ToolDecision(tool_name="get_job_status", args={"job_id": "job-1"})}
    )
    graph = build_scheduler_agent_graph(scheduler_client, tool_llm, pending_actions)

    result = await graph.ainvoke(_state("status of job-1"))

    assert result["error"] is not None
    assert "scheduler unavailable" in result["response"]


def _fake_llm(decisions: dict | None = None, default: ToolDecision | None = None):
    from tests.fakes import FakeToolCallingLLM

    return FakeToolCallingLLM(decisions=decisions, default=default)
