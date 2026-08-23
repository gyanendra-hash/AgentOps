"""app/intent.py's `_coerce` is the defensive fallback ROADMAP 5.6 calls for
("bug-fix pass: misclassified cases") -- a real LLM occasionally returns a
value outside the schema (typo, missing field, refusal); these tests verify
that degrades to "ambiguous" instead of raising and failing the request."""

from app.intent import IntentClassification, _coerce


def test_coerce_valid_intent_passes_through():
    result = _coerce({"intent": "schedule", "client_id": None, "tier": "default"})
    assert result.intent == "schedule"


def test_coerce_unknown_intent_falls_back_to_ambiguous():
    result = _coerce({"intent": "delete_everything"})
    assert result.intent == "ambiguous"


def test_coerce_missing_intent_falls_back_to_ambiguous():
    result = _coerce({"client_id": "acme"})
    assert result.intent == "ambiguous"


def test_coerce_extracts_client_id_and_tier():
    result = _coerce({"intent": "monitor", "client_id": "acme", "tier": "premium"})
    assert result.client_id == "acme"
    assert result.tier == "premium"


def test_coerce_defaults_tier_when_omitted():
    result = _coerce({"intent": "monitor"})
    assert result.tier == "default"


def test_intent_classification_model_defaults():
    classification = IntentClassification(intent="debug")
    assert classification.client_id is None
    assert classification.tier == "default"
