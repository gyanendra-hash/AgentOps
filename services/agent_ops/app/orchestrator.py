"""ROADMAP 5.1/5.2: the top-level routing graph, per SRS 6.5.1 --
`classify_intent -> route -> {scheduler_agent | debug_agent | monitor_agent}
-> clarify (if ambiguous) -> respond`. The three specialist branches are the
graphs/functions already built in Milestones 3 and 4
(app/graph.py::build_graph, app/scheduler_agent.py::build_scheduler_agent_graph)
and the new Monitor Agent (app/monitor_agent.py) -- this module's only new
logic is classification and routing between them.

ROADMAP 6.2: one `Tracer` per invocation, put in the state passed to
`ainvoke()` (never baked into the compiled graph, which is built once at
startup and shared across every request/concurrent user) -- forwarded into
whichever sub-graph gets invoked so a single trace covers the whole request,
not just the orchestrator's own `classify` node."""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.intent import IntentClassifier
from app.monitor_agent import run_monitor
from app.pending_actions import PendingActionStore
from app.rate_limiter_client import RateLimiterClient
from app.scheduler_client import SchedulerClient
from app.tracing import Tracer

#: `tracer` deliberately excluded here -- every call site sets it explicitly
#: (ordered *after* this spread) to the current request's Tracer instance.
_SCHEDULER_AGENT_INITIAL_STATE = {
    "tool_name": None,
    "tool_args": {},
    "rationale": "",
    "needs_confirmation": False,
    "confirmation_token": None,
    "result": None,
    "error": None,
    "response": "",
}


class OrchestratorState(TypedDict):
    question: str
    intent: str | None
    client_id: str | None
    tier: str
    response: str
    needs_confirmation: bool
    confirmation_token: str | None
    result: Any
    sources: list[str]
    tracer: Any  # Tracer, per-invocation -- see module docstring


def build_orchestrator_graph(
    intent_classifier: IntentClassifier,
    scheduler_agent_graph,
    debug_graph,
    scheduler_client: SchedulerClient,
    rate_limiter_client: RateLimiterClient,
    pending_actions: PendingActionStore,
):
    async def classify(state: OrchestratorState) -> dict:
        tracer: Tracer = state.get("tracer") or Tracer()
        with tracer.span("classify_intent"):
            classification = await intent_classifier.classify(state["question"])
        tracer.record_usage("classify_intent", getattr(intent_classifier, "last_usage", None))
        return {
            "intent": classification.intent,
            "client_id": classification.client_id,
            "tier": classification.tier,
        }

    def route_after_classify(state: OrchestratorState) -> str:
        return {
            "schedule": "run_scheduler_agent",
            "debug": "run_debug_agent",
            "monitor": "run_monitor_agent",
        }.get(state["intent"], "clarify_intent")

    async def run_scheduler_agent(state: OrchestratorState) -> dict:
        result = await scheduler_agent_graph.ainvoke(
            {
                "question": state["question"],
                "tracer": state.get("tracer"),
                **_SCHEDULER_AGENT_INITIAL_STATE,
            }
        )
        return {
            "response": result["response"],
            "needs_confirmation": result["needs_confirmation"],
            "confirmation_token": result["confirmation_token"],
            "result": result.get("result"),
        }

    async def run_debug_agent(state: OrchestratorState) -> dict:
        result = await debug_graph.ainvoke(
            {
                "question": state["question"],
                "tracer": state.get("tracer"),
                "retrieved_context": [],
                "sources": [],
                "answer": "",
            }
        )
        return {"response": result["answer"], "sources": result["sources"]}

    async def run_monitor_agent(state: OrchestratorState) -> dict:
        tracer: Tracer = state.get("tracer") or Tracer()
        with tracer.span("monitor"):
            response, data = await run_monitor(
                scheduler_client,
                rate_limiter_client,
                client_id=state.get("client_id"),
                tier=state.get("tier") or "default",
            )
        return {"response": response, "result": data}

    async def clarify_intent(state: OrchestratorState) -> dict:
        return {
            "response": (
                "I'm not sure whether you want to schedule something, debug an "
                "issue, or check system status -- could you clarify?"
            )
        }

    builder = StateGraph(OrchestratorState)
    builder.add_node("classify", classify)
    builder.add_node("run_scheduler_agent", run_scheduler_agent)
    builder.add_node("run_debug_agent", run_debug_agent)
    builder.add_node("run_monitor_agent", run_monitor_agent)
    builder.add_node("clarify_intent", clarify_intent)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges(
        "classify",
        route_after_classify,
        {
            "run_scheduler_agent": "run_scheduler_agent",
            "run_debug_agent": "run_debug_agent",
            "run_monitor_agent": "run_monitor_agent",
            "clarify_intent": "clarify_intent",
        },
    )
    builder.add_edge("run_scheduler_agent", END)
    builder.add_edge("run_debug_agent", END)
    builder.add_edge("run_monitor_agent", END)
    builder.add_edge("clarify_intent", END)

    return builder.compile()


#: `tracer` deliberately excluded here -- the caller sets it explicitly
#: (ordered *after* this spread) to the current request's Tracer instance.
INITIAL_ORCHESTRATOR_STATE = {
    "intent": None,
    "client_id": None,
    "tier": "default",
    "response": "",
    "needs_confirmation": False,
    "confirmation_token": None,
    "result": None,
    "sources": [],
}
