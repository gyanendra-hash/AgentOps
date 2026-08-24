"""Per-node latency and token-cost tracking (ROADMAP 6.2), with an optional
Langfuse export (ROADMAP 6.1). Tracing is always-on and always local --
every graph node's latency (and, for LLM-calling nodes, token usage) is
collected into `Tracer.traces` and returned to the caller in the API
response, whether or not Langfuse is configured. Langfuse is an *additional*
export destination for production observability, not a requirement for the
tracking itself -- consistent with the rest of the app, nothing here needs
an API key to produce useful, testable output."""

import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field


@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class NodeTrace:
    node: str
    latency_ms: float
    usage: TokenUsage | None = None


class Tracer:
    def __init__(self) -> None:
        self.traces: list[NodeTrace] = []

    @contextmanager
    def span(self, node: str):
        start = time.perf_counter()
        trace = NodeTrace(node=node, latency_ms=0.0)
        try:
            yield trace
        finally:
            trace.latency_ms = (time.perf_counter() - start) * 1000
            self.traces.append(trace)

    def record_usage(self, node: str, usage: TokenUsage | None) -> None:
        """Attaches usage to the most recent trace for `node` (the one the
        enclosing `span(node)` just recorded)."""
        if usage is None:
            return
        for trace in reversed(self.traces):
            if trace.node == node:
                trace.usage = usage
                return

    @property
    def total_latency_ms(self) -> float:
        return sum(t.latency_ms for t in self.traces)

    @property
    def total_tokens(self) -> int:
        return sum(t.usage.total_tokens for t in self.traces if t.usage)

    def as_dicts(self) -> list[dict]:
        return [
            {
                "node": t.node,
                "latency_ms": round(t.latency_ms, 2),
                "usage": asdict(t.usage) if t.usage else None,
            }
            for t in self.traces
        ]


class LangfuseExporter:
    """No-ops (logs at debug level) unless LANGFUSE_PUBLIC_KEY/SECRET_KEY are
    set -- a missing/unconfigured Langfuse should never break a request."""

    def __init__(self, public_key: str | None, secret_key: str | None, host: str | None = None) -> None:
        self._client = None
        if public_key and secret_key:
            from langfuse import Langfuse

            self._client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def export(self, name: str, question: str, tracer: Tracer, response: str) -> None:
        if self._client is None:
            return

        trace = self._client.trace(name=name, input={"question": question}, output={"response": response})
        for node_trace in tracer.traces:
            trace.span(
                name=node_trace.node,
                start_time=None,
                end_time=None,
                metadata={"latency_ms": node_trace.latency_ms},
                usage=(
                    {
                        "input": node_trace.usage.prompt_tokens,
                        "output": node_trace.usage.completion_tokens,
                        "unit": "TOKENS",
                    }
                    if node_trace.usage
                    else None
                ),
            )
        self._client.flush()
