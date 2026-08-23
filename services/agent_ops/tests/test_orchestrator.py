"""ROADMAP 5.5: end-to-end test with 15 mixed queries, routing accuracy
measured. As with every other LLM boundary in this repo, the classification
decision itself is preprogrammed via FakeIntentClassifier (see its
docstring) -- what's actually under test is whether the orchestrator routes
each declared intent to the right specialist and that specialist actually
runs, which is the part ROADMAP 5.1/5.2 specify."""

import httpx
import pytest
import respx

from app.intent import IntentClassification
from app.orchestrator import INITIAL_ORCHESTRATOR_STATE, build_orchestrator_graph
from tests.conftest import RATE_LIMITER_BASE_URL, SCHEDULER_BASE_URL

QUERIES = [
    ("create a job called nightly-etl", IntentClassification(intent="schedule"), "schedule"),
    ("cancel job job-1", IntentClassification(intent="schedule"), "schedule"),
    ("what's the status of job job-1", IntentClassification(intent="schedule"), "schedule"),
    ("list failed jobs", IntentClassification(intent="schedule"), "schedule"),
    ("create a job called backup with priority 3", IntentClassification(intent="schedule"), "schedule"),
    ("why is the gateway returning 503", IntentClassification(intent="debug"), "debug"),
    ("how do I fix jobs stuck in pending", IntentClassification(intent="debug"), "debug"),
    ("the dead letter queue is growing, what should I check", IntentClassification(intent="debug"), "debug"),
    ("why do jobs keep retrying forever", IntentClassification(intent="debug"), "debug"),
    ("how's the queue looking right now", IntentClassification(intent="monitor"), "monitor"),
    (
        "what's client acme's rate limit usage",
        IntentClassification(intent="monitor", client_id="acme"),
        "monitor",
    ),
    (
        "check rate limit status for client bravo tier premium",
        IntentClassification(intent="monitor", client_id="bravo", tier="premium"),
        "monitor",
    ),
    ("is everything ok", IntentClassification(intent="ambiguous"), "ambiguous"),
    ("help", IntentClassification(intent="ambiguous"), "ambiguous"),
    ("hello", IntentClassification(intent="ambiguous"), "ambiguous"),
]

# tool_name each schedule-intent query above should route to inside the
# Scheduler Agent sub-graph
_SCHEDULE_TOOL_DECISIONS = {
    "create a job called nightly-etl": ("create_job", {"name": "nightly-etl", "priority": 0}),
    "cancel job job-1": ("cancel_job", {"job_id": "job-1"}),
    "what's the status of job job-1": ("get_job_status", {"job_id": "job-1"}),
    "list failed jobs": ("list_failed_jobs", {}),
    "create a job called backup with priority 3": ("create_job", {"name": "backup", "priority": 3}),
}


@pytest.fixture
def orchestrator(scheduler_client, rate_limiter_client, pending_actions, embedding_provider, repository, reranker, answer_generator):
    from app.scheduler_agent import build_scheduler_agent_graph
    from app.graph import build_graph
    from app.tool_llm import ToolDecision
    from tests.fakes import FakeIntentClassifier, FakeToolCallingLLM

    tool_llm = FakeToolCallingLLM(
        decisions={
            question: ToolDecision(tool_name=tool_name, args=args)
            for question, (tool_name, args) in _SCHEDULE_TOOL_DECISIONS.items()
        }
    )
    scheduler_agent_graph = build_scheduler_agent_graph(scheduler_client, tool_llm, pending_actions)
    debug_graph = build_graph(embedding_provider, repository, reranker, answer_generator, top_k=3)
    intent_classifier = FakeIntentClassifier(
        decisions={question: classification for question, classification, _ in QUERIES}
    )

    return build_orchestrator_graph(
        intent_classifier,
        scheduler_agent_graph,
        debug_graph,
        scheduler_client,
        rate_limiter_client,
        pending_actions,
    ), tool_llm, answer_generator


@respx.mock
async def test_15_mixed_queries_route_to_the_correct_specialist(orchestrator):
    graph, tool_llm, answer_generator = orchestrator

    respx.post(f"{SCHEDULER_BASE_URL}/v1/jobs").mock(
        return_value=httpx.Response(201, json={"jobs": [{"id": "job-x", "name": "x"}]})
    )
    respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs/job-1").mock(
        return_value=httpx.Response(200, json={"id": "job-1", "status": "RUNNING"})
    )
    respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": []})
    )
    respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs/stats").mock(
        return_value=httpx.Response(200, json={"counts": {"PENDING": 2}})
    )
    respx.get(f"{RATE_LIMITER_BASE_URL}/v1/rate-limit/status").mock(
        return_value=httpx.Response(200, json={"algorithm": "token_bucket", "remaining": 10.0, "limit": 20.0})
    )

    correct = 0
    for question, _classification, expected_route in QUERIES:
        result = await graph.ainvoke({"question": question, **INITIAL_ORCHESTRATOR_STATE})

        if expected_route == "schedule":
            routed_correctly = question in tool_llm.calls
        elif expected_route == "debug":
            routed_correctly = any(q == question for q, _ctx in answer_generator.calls)
        elif expected_route == "monitor":
            routed_correctly = result["response"].startswith("Queue depth")
        else:  # ambiguous
            routed_correctly = "clarify" in result["response"].lower() or "not sure" in result["response"].lower()

        if routed_correctly:
            correct += 1

    accuracy = correct / len(QUERIES)
    assert accuracy == 1.0, f"routing accuracy {accuracy:.0%} ({correct}/{len(QUERIES)})"


@respx.mock
async def test_schedule_intent_reaches_scheduler_agent(orchestrator):
    graph, tool_llm, _answer_generator = orchestrator
    respx.post(f"{SCHEDULER_BASE_URL}/v1/jobs").mock(
        return_value=httpx.Response(201, json={"jobs": [{"id": "job-x", "name": "nightly-etl"}]})
    )

    result = await graph.ainvoke(
        {"question": "create a job called nightly-etl", **INITIAL_ORCHESTRATOR_STATE}
    )

    assert result["intent"] == "schedule"
    assert result["result"]["id"] == "job-x"


async def test_debug_intent_reaches_rag_graph(orchestrator):
    graph, _tool_llm, answer_generator = orchestrator

    result = await graph.ainvoke(
        {"question": "why is the gateway returning 503", **INITIAL_ORCHESTRATOR_STATE}
    )

    assert result["intent"] == "debug"
    assert len(answer_generator.calls) == 1


@respx.mock
async def test_monitor_intent_with_client_id_reaches_rate_limiter(orchestrator):
    graph, _tool_llm, _answer_generator = orchestrator
    respx.get(f"{SCHEDULER_BASE_URL}/v1/jobs/stats").mock(
        return_value=httpx.Response(200, json={"counts": {}})
    )
    respx.get(f"{RATE_LIMITER_BASE_URL}/v1/rate-limit/status").mock(
        return_value=httpx.Response(200, json={"algorithm": "token_bucket", "remaining": 5.0, "limit": 20.0})
    )

    result = await graph.ainvoke(
        {"question": "what's client acme's rate limit usage", **INITIAL_ORCHESTRATOR_STATE}
    )

    assert result["intent"] == "monitor"
    assert result["result"]["rate_limit"]["remaining"] == 5.0


async def test_ambiguous_intent_asks_for_clarification(orchestrator):
    graph, _tool_llm, _answer_generator = orchestrator

    result = await graph.ainvoke({"question": "is everything ok", **INITIAL_ORCHESTRATOR_STATE})

    assert result["intent"] == "ambiguous"
    assert "clarify" in result["response"].lower()
