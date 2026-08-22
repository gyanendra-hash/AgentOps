"""ROADMAP 3.6: "manual test with 10 sample debugging questions" -- made
automated and repeatable instead of a one-off manual check. Each question
maps to a distinct runbook scenario; the assertion is that the retrieved
context for that question actually contains the expected scenario's content,
i.e. retrieval is grounding the answer in the *right* section of the
runbook, not just returning something."""

from pathlib import Path

import pytest

from app.graph import build_graph
from app.ingest import ingest_file

RUNBOOK_PATH = Path(__file__).resolve().parent.parent / "runbook" / "runbook.md"

QUESTIONS = [
    ("Why is the gateway returning 503 for every single request?", "fail_open"),
    ("The rate limiter is letting through more requests than the configured limit, why?", "flushed"),
    ("A job has been stuck in PENDING for a long time and never moves, what's wrong?", "leader"),
    ("Jobs reach DISPATCHED but never move to RUNNING, what should I check?", "worker pool"),
    ("The dead letter queue is growing very fast, what should I look at?", "dead-letter"),
    ("Scheduler leadership keeps flapping between replicas, how do I fix it?", "leader_ttl_seconds"),
    ("We're seeing Postgres connection pool exhausted errors under load, why?", "max_size"),
    ("The same job id appears to have run twice, what happened?", "duplicate"),
    ("Redis was restarted and now rate limits reset, is that expected?", "redis"),
    ("Job dispatch latency is very high under load, what should I tune?", "dispatch_poll_interval_seconds"),
]


@pytest.fixture
async def graph(embedding_provider, repository, reranker, answer_generator):
    await ingest_file(RUNBOOK_PATH, "runbook", embedding_provider, repository)
    return build_graph(embedding_provider, repository, reranker, answer_generator, top_k=3, min_score=0.0)


@pytest.mark.parametrize("question,expected_keyword", QUESTIONS)
async def test_question_retrieves_grounded_context(graph, question, expected_keyword):
    result = await graph.ainvoke(
        {"question": question, "retrieved_context": [], "sources": [], "answer": ""}
    )

    assert result["retrieved_context"], f"no context retrieved for: {question}"
    combined = " ".join(result["retrieved_context"]).lower()
    assert expected_keyword in combined, (
        f"expected '{expected_keyword}' in retrieved context for: {question}\n"
        f"got: {result['retrieved_context']}"
    )
    assert result["answer"]
    assert result["sources"] == ["runbook"] * len(result["retrieved_context"])


async def test_answer_generator_receives_the_retrieved_context(graph, answer_generator):
    await graph.ainvoke(
        {"question": "why is the DLQ growing", "retrieved_context": [], "sources": [], "answer": ""}
    )

    assert len(answer_generator.calls) == 1
    question, context_chunks = answer_generator.calls[0]
    assert question == "why is the DLQ growing"
    assert context_chunks  # not empty -- generator was actually grounded


async def test_min_score_filters_out_irrelevant_context(embedding_provider, repository, reranker, answer_generator):
    await ingest_file(RUNBOOK_PATH, "runbook", embedding_provider, repository)
    strict_graph = build_graph(
        embedding_provider, repository, reranker, answer_generator, top_k=5, min_score=1.1
    )

    result = await strict_graph.ainvoke(
        {"question": "gateway 503", "retrieved_context": [], "sources": [], "answer": ""}
    )

    assert result["retrieved_context"] == []
    assert "don't have enough information" in result["answer"]
