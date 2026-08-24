"""ROADMAP 6.1/6.2: per-node latency/token tracking, and specifically a
regression test for the bug caught while building this -- a graph is
compiled once at startup and reused across every request, so a Tracer must
never be baked into a node closure at build time (it would accumulate every
request's traces into one shared, ever-growing list). Every graph instead
reads `state["tracer"]`, set fresh per `ainvoke()` call."""

import asyncio

from app.graph import build_graph
from app.tracing import LangfuseExporter, Tracer, TokenUsage


def test_span_records_latency():
    tracer = Tracer()
    with tracer.span("step"):
        pass

    assert len(tracer.traces) == 1
    assert tracer.traces[0].node == "step"
    assert tracer.traces[0].latency_ms >= 0


def test_record_usage_attaches_to_matching_span():
    tracer = Tracer()
    with tracer.span("generate"):
        pass
    tracer.record_usage("generate", TokenUsage(prompt_tokens=10, completion_tokens=5))

    assert tracer.traces[0].usage.total_tokens == 15


def test_record_usage_with_none_is_a_noop():
    tracer = Tracer()
    with tracer.span("generate"):
        pass
    tracer.record_usage("generate", None)

    assert tracer.traces[0].usage is None


def test_totals_sum_across_spans():
    tracer = Tracer()
    with tracer.span("a"):
        pass
    with tracer.span("b"):
        pass
    tracer.record_usage("a", TokenUsage(prompt_tokens=10, completion_tokens=5))
    tracer.record_usage("b", TokenUsage(prompt_tokens=3, completion_tokens=2))

    assert tracer.total_tokens == 20
    assert tracer.total_latency_ms >= 0


def test_as_dicts_shape():
    tracer = Tracer()
    with tracer.span("step"):
        pass
    tracer.record_usage("step", TokenUsage(prompt_tokens=1, completion_tokens=1))

    [entry] = tracer.as_dicts()
    assert entry["node"] == "step"
    assert "latency_ms" in entry
    assert entry["usage"] == {"prompt_tokens": 1, "completion_tokens": 1}


def test_langfuse_exporter_disabled_when_unconfigured():
    exporter = LangfuseExporter(None, None)
    assert exporter.enabled is False


def test_langfuse_exporter_export_is_a_noop_when_disabled():
    exporter = LangfuseExporter(None, None)
    tracer = Tracer()
    with tracer.span("step"):
        pass

    exporter.export("test", "question", tracer, "response")  # must not raise


async def test_concurrent_graph_invocations_get_isolated_traces(
    embedding_provider, repository, reranker, answer_generator
):
    """The regression test: build_graph() compiles ONE graph (as it would at
    startup), then two concurrent requests each pass their own Tracer via
    state. Neither tracer should see the other's spans."""
    graph = build_graph(embedding_provider, repository, reranker, answer_generator, top_k=3)

    tracer_a = Tracer()
    tracer_b = Tracer()

    async def invoke(question: str, tracer: Tracer) -> None:
        await graph.ainvoke(
            {"question": question, "tracer": tracer, "retrieved_context": [], "sources": [], "answer": ""}
        )

    await asyncio.gather(invoke("question A", tracer_a), invoke("question B", tracer_b))

    assert len(tracer_a.traces) == 3  # retrieve, rerank, generate
    assert len(tracer_b.traces) == 3
    assert tracer_a.traces is not tracer_b.traces


async def test_graph_works_without_a_tracer_in_state(
    embedding_provider, repository, reranker, answer_generator
):
    """Backwards compatible: callers that don't care about tracing (or
    predate it) can omit "tracer" entirely."""
    graph = build_graph(embedding_provider, repository, reranker, answer_generator, top_k=3)

    result = await graph.ainvoke(
        {"question": "why is the gateway returning 503", "retrieved_context": [], "sources": [], "answer": ""}
    )

    assert result["answer"]
