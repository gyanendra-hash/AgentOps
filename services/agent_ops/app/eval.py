"""ROADMAP 6.4: run the eval set through classify_intent, measure routing
accuracy, log failures. Deliberately calls `IntentClassifier.classify()`
directly rather than the full orchestrator graph: ROADMAP 6.4 asks for
*routing* accuracy, which is entirely decided by this one call -- going
through the full graph would also require live Scheduler/Rate-Limiter
services just to reach a routing verdict (the downstream specialist nodes
would still run and could fail for unrelated reasons). `scripts/run_eval.py`
drives this against a real, configured classifier (needs an LLM API key).
`tests/test_eval.py` runs it against `FakeIntentClassifier` to verify the
harness's own logic (accuracy math, failure capture), not an LLM's
judgment."""

from dataclasses import dataclass

from app.intent import IntentClassifier
from eval.eval_set import EvalCase


@dataclass
class EvalResult:
    question: str
    expected_intent: str
    actual_intent: str
    correct: bool


@dataclass
class EvalReport:
    results: list[EvalResult]

    @property
    def accuracy(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.correct) / len(self.results)

    @property
    def failures(self) -> list[EvalResult]:
        return [r for r in self.results if not r.correct]


async def run_eval(intent_classifier: IntentClassifier, eval_set: list[EvalCase]) -> EvalReport:
    results = []
    for case in eval_set:
        classification = await intent_classifier.classify(case.question)
        results.append(
            EvalResult(
                question=case.question,
                expected_intent=case.expected_intent,
                actual_intent=classification.intent,
                correct=classification.intent == case.expected_intent,
            )
        )
    return EvalReport(results=results)


def format_report(report: EvalReport) -> str:
    lines = [f"Accuracy: {report.accuracy:.0%} ({len(report.results) - len(report.failures)}/{len(report.results)})"]
    if report.failures:
        lines.append("")
        lines.append("Failures:")
        for failure in report.failures:
            lines.append(
                f"  - {failure.question!r}: expected {failure.expected_intent!r}, "
                f"got {failure.actual_intent!r}"
            )
    return "\n".join(lines)
