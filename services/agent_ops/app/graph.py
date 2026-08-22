"""ROADMAP 3.5: a single LangGraph node -- question -> retrieve -> rerank ->
grounded answer. Deliberately kept to one node: SRS 6.5.1's full agent graph
(classify_intent -> route -> {scheduler_agent | debug_agent | monitor_agent}
-> clarify -> respond) has no branching to justify yet -- that arrives with
intent classification in Milestone 5. This node *is* the debug_agent's core
logic, ready to be dropped into the bigger graph later."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.embeddings import EmbeddingProvider
from app.llm import AnswerGenerator
from app.reranker import Reranker
from app.repository import EmbeddingRepository
from app.retrieval import retrieve


class DebugState(TypedDict):
    question: str
    retrieved_context: list[str]
    sources: list[str]
    answer: str


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
        candidates = await retrieve(
            state["question"], embedding_provider, repository, k=top_k, min_score=min_score
        )
        reranked = await reranker.rerank(state["question"], candidates)
        context_texts = [c.chunk.text for c in reranked]
        answer = await answer_generator.generate(state["question"], context_texts)
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
