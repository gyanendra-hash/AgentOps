"""ROADMAP 6.3: 20-query evaluation set for the orchestrator's
classify_intent step, covering all four intents plus a few deliberately
ambiguous/tricky cases. `expected_intent` is what a correctly-tuned
classifier *should* return -- run against a real LLM (`scripts/run_eval.py`)
to measure actual accuracy; `tests/test_eval.py` runs the same set through
`FakeIntentClassifier` to verify the eval harness itself (accuracy
computation, failure logging) rather than the LLM's judgment."""

from dataclasses import dataclass


@dataclass
class EvalCase:
    question: str
    expected_intent: str  # "schedule" | "debug" | "monitor" | "ambiguous"
    notes: str = ""


EVAL_SET: list[EvalCase] = [
    EvalCase("create a job called nightly-etl", "schedule"),
    EvalCase("create a job called backup with priority 3", "schedule"),
    EvalCase("cancel job job-1", "schedule"),
    EvalCase("what's the status of job job-1", "schedule"),
    EvalCase("list failed jobs", "schedule"),
    EvalCase("show me everything in the dead letter queue", "schedule", notes="paraphrase of list_failed_jobs"),
    EvalCase("why is the gateway returning 503", "debug"),
    EvalCase("how do I fix jobs stuck in pending", "debug"),
    EvalCase("the dead letter queue is growing, what should I check", "debug"),
    EvalCase("why do jobs keep retrying forever", "debug"),
    EvalCase("scheduler leadership keeps flapping between replicas, how do I fix it", "debug"),
    EvalCase("we're seeing postgres connection pool exhausted errors, why", "debug"),
    EvalCase("how's the queue looking right now", "monitor"),
    EvalCase("what's client acme's rate limit usage", "monitor"),
    EvalCase("check rate limit status for client bravo tier premium", "monitor"),
    EvalCase("how many jobs are pending right now", "monitor", notes="paraphrase of queue depth"),
    EvalCase("is everything ok", "ambiguous"),
    EvalCase("help", "ambiguous"),
    EvalCase("hello", "ambiguous"),
    EvalCase(
        "what happened to job-1 yesterday",
        "ambiguous",
        notes="could be schedule (get_job_status) or debug (postmortem) -- genuinely ambiguous without more context",
    ),
]

assert len(EVAL_SET) == 20
