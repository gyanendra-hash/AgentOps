#!/usr/bin/env python
"""ROADMAP 6.4: run the 20-query eval set against a REAL, configured
classify_intent (needs OPENAI_API_KEY or ANTHROPIC_API_KEY -- everything
else in this repo up to now has been verified against fakes; this is the
one script meant to make a real LLM call).

Usage (from services/agent_ops, with requirements installed and .env sourced
or the env vars set another way):

    python scripts/run_eval.py

Only measures routing accuracy (ROADMAP 6.4) -- it doesn't need Postgres,
Redis, the Scheduler, or the Rate Limiter running, since it calls
classify_intent directly rather than executing whichever specialist it
routes to.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.eval import format_report, run_eval  # noqa: E402
from app.main import build_intent_classifier  # noqa: E402
from eval.eval_set import EVAL_SET  # noqa: E402


async def main() -> None:
    settings = get_settings()
    intent_classifier = build_intent_classifier(settings)

    report = await run_eval(intent_classifier, EVAL_SET)
    print(format_report(report))


if __name__ == "__main__":
    asyncio.run(main())
