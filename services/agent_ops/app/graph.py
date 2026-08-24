"""ROADMAP 3.5: a single LangGraph node -- question -> retrieve -> rerank ->
grounded answer. Deliberately kept to one node: SRS 6.5.1's full agent graph
(classify_intent -> route -> {scheduler_agent | debug_agent | monitor_agent}
-> clarify -> respond) has no branching to justify yet -- that arrives with
intent classification in Milestone 5. This node *is* the debug_agent's core
logic, ready to be dropped into the bigger graph later.

ROADMAP 6.2: the graph is compiled once at startup and reused across every
request, so a `Tracer` can't be baked into the node closure -- that would
share one mutable trace list across every concurrent request forever. Each
caller instead puts a fresh `Tracer()` in the *state* it invokes with
(`tracer` key); nodes read/write `state["tracer"]`, which is per-invocation.
"""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.embeddings import EmbeddingProvider
from app.llm import AnswerGenerator
from app.reranker import Reranker
from app.repository import EmbeddingRepository
from app.retrieval import retrieve
from app.tracing import Tracer


class DebugState(TypedDict):
    question: str
    retrieved_context: list[str]
    sources: list[str]
    answer: str
    tracer: Any  # Tracer, per-invocation -- see module docstring


def build_graph(
    embedding_provider: EmbeddingProvider,
    repository: EmbeddingRepository,
    reranker: Reranker,
    answer_generator: AnswerGenerator,
    *,
    top_k: int = 5,
    min_score: float = 0.0,
):
    async def answer_question(state: DebugState) -> dict:
        tracer: Tracer = state.get("tracer") or Tracer()

        with tracer.span("retrieve"):
            candidates = await retrieve(
                state["question"], embedding_provider, repository, k=top_k, min_score=min_score
            )
        with tracer.span("rerank"):
            reranked = await reranker.rerank(state["question"], candidates)

        context_texts = [c.chunk.text for c in reranked]
        with tracer.span("generate"):
            answer = await answer_generator.generate(state["question"], context_texts)
        tracer.record_usage("generate", getattr(answer_generator, "last_usage", None))

        return {
            "retrieved_context": context_texts,
            "sources": [c.chunk.source for c in reranked],
            "answer": answer,
        }

    builder = StateGraph(DebugState)
    builder.add_node("answer_question", answer_question)
    builder.add_edge(START, "answer_question")
    builder.add_edge("answer_question", END)
    return builder.compile()
