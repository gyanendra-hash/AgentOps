"""Verifies the eval harness itself (app/eval.py) -- accuracy computation
and failure capture -- using FakeIntentClassifier, not a real LLM's
classification judgment (that's scripts/run_eval.py's job, once a real API
key is available)."""

from app.eval import run_eval
from eval.eval_set import EVAL_SET, EvalCase
from tests.fakes import FakeIntentClassifier


async def test_perfect_classifier_scores_100_percent():
    from app.intent import IntentClassification

    classifier = FakeIntentClassifier(
        decisions={case.question: IntentClassification(intent=case.expected_intent) for case in EVAL_SET}
    )

    report = await run_eval(classifier, EVAL_SET)

    assert report.accuracy == 1.0
    assert report.failures == []


async def test_misclassifications_are_captured_as_failures():
    from app.intent import IntentClassification

    eval_set = [
        EvalCase("create a job", "schedule"),
        EvalCase("why is it broken", "debug"),
    ]
    # classifier gets the second one wrong
    classifier = FakeIntentClassifier(
        decisions={
            "create a job": IntentClassification(intent="schedule"),
            "why is it broken": IntentClassification(intent="monitor"),
        }
    )

    report = await run_eval(classifier, eval_set)

    assert report.accuracy == 0.5
    assert len(report.failures) == 1
    assert report.failures[0].question == "why is it broken"
    assert report.failures[0].expected_intent == "debug"
    assert report.failures[0].actual_intent == "monitor"


async def test_empty_eval_set_has_zero_accuracy_not_a_crash():
    classifier = FakeIntentClassifier()

    report = await run_eval(classifier, [])

    assert report.accuracy == 0.0
    assert report.results == []


def test_eval_set_has_20_cases_covering_all_intents():
    assert len(EVAL_SET) == 20
    intents = {case.expected_intent for case in EVAL_SET}
    assert intents == {"schedule", "debug", "monitor", "ambiguous"}
