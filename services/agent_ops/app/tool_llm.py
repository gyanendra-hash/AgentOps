"""LLM tool-calling (ROADMAP 4.3/4.4): given a natural-language operator
request, decide which Scheduler tool (if any) to call and with what
arguments. Mirrors app/llm.py's dual-provider, lazy-import pattern; tests
use tests/fakes.py::FakeToolCallingLLM instead, so the routing/execution
plumbing is verifiable without a real LLM call."""

import json
from dataclasses import dataclass, field
from typing import Protocol

from app.tools import ToolSpec

SYSTEM_PROMPT = (
    "You are the Scheduler Agent for the AgentOps platform. Given an "
    "operator's request, decide whether one of the available tools applies "
    "and with what arguments. If no tool clearly applies, don't call one -- "
    "say so instead of guessing at a job id or job name that wasn't given."
)


@dataclass
class ToolDecision:
    tool_name: str | None
    args: dict = field(default_factory=dict)
    rationale: str = ""


class ToolCallingLLM(Protocol):
    async def decide(self, question: str, tools: list[ToolSpec]) -> ToolDecision: ...


def _tool_schema(spec: ToolSpec) -> dict:
    return {
        "name": spec.name,
        "description": spec.description,
        "parameters": spec.args_model.model_json_schema(),
    }


class OpenAIToolCallingLLM:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def decide(self, question: str, tools: list[ToolSpec]) -> ToolDecision:
        tool_defs = [{"type": "function", "function": _tool_schema(spec)} for spec in tools]
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            tools=tool_defs,
        )
        message = response.choices[0].message
        if not message.tool_calls:
            return ToolDecision(tool_name=None, rationale=message.content or "")

        call = message.tool_calls[0]
        return ToolDecision(tool_name=call.function.name, args=json.loads(call.function.arguments))


class AnthropicToolCallingLLM:
    def __init__(self, api_key: str, model: str = "claude-sonnet-5") -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def decide(self, question: str, tools: list[ToolSpec]) -> ToolDecision:
        tool_defs = [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.args_model.model_json_schema(),
            }
            for spec in tools
        ]
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": question}],
            tools=tool_defs,
        )
        for block in response.content:
            if block.type == "tool_use":
                return ToolDecision(tool_name=block.name, args=block.input)

        text = "".join(block.text for block in response.content if block.type == "text")
        return ToolDecision(tool_name=None, rationale=text)
