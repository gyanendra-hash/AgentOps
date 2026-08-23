"""Intent classification (ROADMAP 5.1): the entry point of the orchestrator
graph (app/orchestrator.py). One structured-output LLM call returns the
intent plus (for monitor requests) whatever client_id/tier it could pull out
of the question, so the Monitor Agent doesn't need a second LLM round-trip.

Same dual-provider, lazy-import, Protocol-with-a-fake pattern as
app/llm.py and app/tool_llm.py."""

import json
from typing import Literal, Protocol

from pydantic import BaseModel

Intent = Literal["schedule", "debug", "monitor", "ambiguous"]

# ROADMAP 5.6: few-shot examples, added after misclassification during
# testing showed bare category names weren't enough signal -- "how's the
# queue looking" was initially classified as "debug" (it *sounds* like a
# question) instead of "monitor".
SYSTEM_PROMPT = """You are the intent router for the AgentOps platform. Classify the \
operator's request into exactly one of: schedule, debug, monitor, ambiguous.

- schedule: create, cancel, or check the status of a specific job.
- debug: "why is X happening" / "how do I fix Y" questions about system behavior, \
answered from the runbook.
- monitor: asking about current system state -- queue depth, rate-limit usage \
-- not a specific past failure.
- ambiguous: could plausibly be more than one of the above, or none of them.

Examples:
- "create a job called nightly-etl" -> schedule
- "cancel job abc-123" -> schedule
- "what's the status of job abc-123" -> schedule
- "why does the gateway keep returning 503" -> debug
- "how do I fix jobs stuck in PENDING" -> debug
- "how's the queue looking right now" -> monitor
- "what's client acme's current rate limit usage" -> monitor
- "is everything OK" -> ambiguous
- "help" -> ambiguous

If the request is about rate-limit usage for a specific client, extract that \
client's id as client_id (and tier if mentioned, default "default")."""


class IntentClassification(BaseModel):
    intent: Intent
    client_id: str | None = None
    tier: str = "default"


class IntentClassifier(Protocol):
    async def classify(self, question: str) -> IntentClassification: ...


_VALID_INTENTS = {"schedule", "debug", "monitor", "ambiguous"}


def _coerce(raw: dict) -> IntentClassification:
    """ROADMAP 5.6 bug-fix: a model can return a value outside the schema
    (typo'd intent name, missing field). Treat that as ambiguous instead of
    raising and failing the whole request."""
    intent = raw.get("intent")
    if intent not in _VALID_INTENTS:
        return IntentClassification(intent="ambiguous")
    try:
        return IntentClassification.model_validate(raw)
    except Exception:
        return IntentClassification(intent="ambiguous")


class OpenAIIntentClassifier:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def classify(self, question: str) -> IntentClassification:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "classify_intent",
                        "description": "Record the classified intent.",
                        "parameters": IntentClassification.model_json_schema(),
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "classify_intent"}},
        )
        message = response.choices[0].message
        if not message.tool_calls:
            return IntentClassification(intent="ambiguous")
        return _coerce(json.loads(message.tool_calls[0].function.arguments))


class AnthropicIntentClassifier:
    def __init__(self, api_key: str, model: str = "claude-sonnet-5") -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def classify(self, question: str) -> IntentClassification:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": question}],
            tools=[
                {
                    "name": "classify_intent",
                    "description": "Record the classified intent.",
                    "input_schema": IntentClassification.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": "classify_intent"},
        )
        for block in response.content:
            if block.type == "tool_use":
                return _coerce(block.input)
        return IntentClassification(intent="ambiguous")
