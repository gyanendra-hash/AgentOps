"""Grounded answer generation (ROADMAP 3.5), per SRS 9: "OpenAI gpt-4o-mini
or Claude API (swappable)". Both providers implement the same `AnswerGenerator`
protocol so `app/graph.py` doesn't know or care which one is in use. Real LLM
calls need an API key (OPENAI_API_KEY or ANTHROPIC_API_KEY) -- tests use
tests/fakes.py::FakeAnswerGenerator instead, so the whole retrieve->rerank
pipeline is verifiable without one."""

from typing import Protocol

SYSTEM_PROMPT = (
    "You are an on-call assistant for the AgentOps platform. Answer the "
    "operator's question using ONLY the provided runbook context below. "
    "If the context doesn't contain the answer, say you don't have enough "
    "information instead of guessing."
)


class AnswerGenerator(Protocol):
    async def generate(self, question: str, context_chunks: list[str]) -> str: ...


def _build_user_prompt(question: str, context_chunks: list[str]) -> str:
    context = "\n\n---\n\n".join(context_chunks) if context_chunks else "(no relevant context found)"
    return f"Context:\n{context}\n\nQuestion: {question}"


class OpenAIAnswerGenerator:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def generate(self, question: str, context_chunks: list[str]) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(question, context_chunks)},
            ],
        )
        return response.choices[0].message.content or ""


class AnthropicAnswerGenerator:
    def __init__(self, api_key: str, model: str = "claude-sonnet-5") -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def generate(self, question: str, context_chunks: list[str]) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_prompt(question, context_chunks)}],
        )
        return "".join(block.text for block in response.content if block.type == "text")
