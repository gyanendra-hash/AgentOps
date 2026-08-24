"""ROADMAP 4.3: the Scheduler Agent as a LangGraph -- the first branching
graph in the codebase (Milestone 3's RAG graph was a single node). Per SRS
6.5.1/6.5.4 and FR-9: destructive tools route through a `clarify` node
instead of executing immediately.

The graph is invoked fresh per HTTP request, so "wait for confirmation"
can't mean pausing mid-graph -- `clarify` parks the decision in
PendingActionStore and ends the graph; a *separate* request
(POST /v1/agent/confirm) redeems the token via `execute_confirmed_action`,
reusing the same tool-execution/response-formatting logic as the graph's own
`execute_tool` node.

ROADMAP 6.2: the graph is compiled once at startup and reused across every
request, so (as in app/graph.py) a `Tracer` can't be baked into the node
closures -- callers put a fresh `Tracer()` in the state they invoke with."""

from typing import Any, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph

from app.pending_actions import PendingActionStore
from app.scheduler_client import SchedulerClient, SchedulerUnavailableError
from app.tool_llm import ToolCallingLLM
from app.tools import TOOLS, InvalidToolArgsError, UnknownToolError, execute_tool
from app.tracing import Tracer


class SchedulerAgentState(TypedDict):
    question: str
    tool_name: str | None
    tool_args: dict
    rationale: str
    needs_confirmation: bool
    confirmation_token: str | None
    result: Any
    error: str | None
    response: str
    tracer: Any  # Tracer, per-invocation -- see module docstring


def _describe_tool_call(tool_name: str, args: dict) -> str:
    spec = TOOLS.get(tool_name)
    description = spec.description if spec else tool_name
    return f"About to run `{tool_name}` ({description}) with arguments {args}. Confirm?"


async def _run_tool(client: SchedulerClient, tool_name: str, args: dict) -> tuple[Any, str | None]:
    """Shared by the graph's execute_tool node and the confirm endpoint.
    Never raises -- tool/argument/network failures become an `error` string
    instead (ROADMAP 4.6: malformed args, API timeouts)."""
    try:
        result = await execute_tool(client, tool_name, args)
        return result, None
    except InvalidToolArgsError as exc:
        return None, f"invalid arguments: {exc}"
    except UnknownToolError as exc:
        return None, f"unknown tool: {exc}"
    except SchedulerUnavailableError as exc:
        return None, f"scheduler unavailable: {exc}"
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None, "job not found"
        if exc.response.status_code == 409:
            return None, "job can't be cancelled anymore (already dispatched or finished)"
        return None, f"scheduler returned {exc.response.status_code}"
    except ValueError as exc:
        return None, str(exc)


def _format_response(tool_name: str | None, result: Any, error: str | None) -> str:
    if tool_name is None:
        return "I couldn't find a matching action for that request."
    if error is not None:
        return f"Couldn't run `{tool_name}`: {error}"
    return f"Ran `{tool_name}` successfully. Result: {result}"


def build_scheduler_agent_graph(
    scheduler_client: SchedulerClient,
    tool_llm: ToolCallingLLM,
    pending_actions: PendingActionStore,
):
    async def decide_tool(state: SchedulerAgentState) -> dict:
        tracer: Tracer = state.get("tracer") or Tracer()
        with tracer.span("decide_tool"):
            decision = await tool_llm.decide(state["question"], list(TOOLS.values()))
        tracer.record_usage("decide_tool", getattr(tool_llm, "last_usage", None))
        return {
            "tool_name": decision.tool_name,
            "tool_args": decision.args,
            "rationale": decision.rationale,
        }

    def route_after_decision(state: SchedulerAgentState) -> str:
        if state["tool_name"] is None:
            return "respond_no_tool"
        spec = TOOLS.get(state["tool_name"])
        if spec is not None and spec.destructive:
            return "clarify"
        return "execute_tool"

    async def clarify(state: SchedulerAgentState) -> dict:
        token = await pending_actions.create(state["tool_name"], state["tool_args"], state["question"])
        return {
            "needs_confirmation": True,
            "confirmation_token": token,
            "response": _describe_tool_call(state["tool_name"], state["tool_args"]),
        }

    async def execute_tool_node(state: SchedulerAgentState) -> dict:
        tracer: Tracer = state.get("tracer") or Tracer()
        with tracer.span("execute_tool"):
            result, error = await _run_tool(scheduler_client, state["tool_name"], state["tool_args"])
        return {"result": result, "error": error}

    async def respond(state: SchedulerAgentState) -> dict:
        return {"response": _format_response(state["tool_name"], state.get("result"), state.get("error"))}

    async def respond_no_tool(state: SchedulerAgentState) -> dict:
        text = state["rationale"] or "I couldn't find a matching action for that request."
        return {"response": text}

    builder = StateGraph(SchedulerAgentState)
    builder.add_node("decide_tool", decide_tool)
    builder.add_node("clarify", clarify)
    builder.add_node("execute_tool", execute_tool_node)
    builder.add_node("respond", respond)
    builder.add_node("respond_no_tool", respond_no_tool)

    builder.add_edge(START, "decide_tool")
    builder.add_conditional_edges(
        "decide_tool",
        route_after_decision,
        {"clarify": "clarify", "execute_tool": "execute_tool", "respond_no_tool": "respond_no_tool"},
    )
    builder.add_edge("clarify", END)
    builder.add_edge("execute_tool", "respond")
    builder.add_edge("respond", END)
    builder.add_edge("respond_no_tool", END)

    return builder.compile()


async def execute_confirmed_action(
    scheduler_client: SchedulerClient,
    pending_actions: PendingActionStore,
    token: str,
) -> tuple[str, Any, str | None]:
    """Returns (response_text, result, error). `response_text` explains an
    expired/unknown token; the graph never reaches this path itself."""
    pending = await pending_actions.get(token)
    if pending is None:
        return "That confirmation has expired or was already used.", None, None

    await pending_actions.delete(token)
    result, error = await _run_tool(scheduler_client, pending["tool_name"], pending["args"])
    return _format_response(pending["tool_name"], result, error), result, error
