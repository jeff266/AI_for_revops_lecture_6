#!/usr/bin/env python3
"""
Routing smoke tests — verify questions route to the correct handlers.

These tests require live Haiku calls (classification), so they're gated behind
ANTHROPIC_API_KEY presence. Run only when deploying routing changes.

Usage:
  # Skip if no API key set:
  python scripts/test_routing_smoke.py

  # Run with API key:
  ANTHROPIC_API_KEY=... python scripts/test_routing_smoke.py

Critical test: "score Bestseller on MEDDICC" must route to query_rubric_scores_bulk,
NOT query_deal_health (the production misroute that this disambiguation prevents).
"""

import os
import sys
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Gate: skip if no API key (makes test suite runnable offline)
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("SKIP: test_routing_smoke requires ANTHROPIC_API_KEY (live Haiku calls)")
    print("Set ANTHROPIC_API_KEY to run routing verification tests")
    sys.exit(0)

import anthropic
from api.router import build_intent_prompt, _extract_json
from datetime import date


def current_quarter_label() -> str:
    """Minimal FY quarter label for testing."""
    month = date.today().month
    year = date.today().year
    # FY starts Feb: Feb-Apr=Q1, May-Jul=Q2, Aug-Oct=Q3, Nov-Jan=Q4
    if 2 <= month <= 4:
        return f"FY{year+1} Q1"
    elif 5 <= month <= 7:
        return f"FY{year+1} Q2"
    elif 8 <= month <= 10:
        return f"FY{year+1} Q3"
    else:  # Nov, Dec, Jan
        fy = year + 1 if month <= 1 else year + 2
        return f"FY{fy} Q4"


def classify_question(question: str, client, roster_text: str = "") -> dict:
    """Call Haiku to classify a question and return parsed intent."""
    today = date.today().isoformat()
    cq = current_quarter_label()

    prompt = build_intent_prompt(
        today=today,
        current_quarter=cq,
        history="[]",
        question=question,
        roster_text=roster_text,
    )

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system="Respond with valid JSON only. No markdown, no backticks, no explanation.",
        messages=[{"role": "user", "content": prompt}]
    )

    return _extract_json(resp.content[0].text)


# Smoke tests: (question, expected_handler, min_confidence)
# One representative question per handler
SMOKE_TESTS = [
    # Batch 1: Deal-level handlers
    ("which deals are at risk?", "query_deal_health", 0.7),
    ("which deals haven't moved in 30 days?", "query_stale_deals", 0.7),
    ("prep me for my Skyscanner call", "query_pre_call_brief", 0.7),
    ("how did the last Skyscanner call go?", "query_call_quality", 0.6),

    # Batch 2: Rep/team handlers
    ("show me Christian's pipeline", "query_rep_pipeline", 0.7),
    ("who is on track to hit quota?", "query_rep_attainment", 0.7),
    ("show me the team leaderboard", "query_team_leaderboard", 0.7),
    ("which reps need coaching this week?", "query_coaching_priorities", 0.6),

    # Batch 3: SDR/pipeline handlers
    ("how is Jake tracking this month", "query_sdr_metrics", 0.7),
    ("show me SDR team activity", "query_sdr_leaderboard", 0.6),
    ("show me pipeline sourced by SDRs", "query_sdr_pipeline_sourced", 0.6),
    ("which deals moved stage last week?", "query_pipeline_movement", 0.6),

    # CRITICAL: The Bestseller misroute case
    # This MUST route to query_rubric_scores_bulk, NOT query_deal_health
    # Catches the live bug this disambiguation fixes
    ("score Bestseller on MEDDICC, highlight weaknesses and next steps", "query_rubric_scores_bulk", 0.7),
]


def run_smoke_tests():
    """Run all smoke tests and report results."""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    # Optional: load roster for name resolution tests
    # For this smoke test, we'll use a minimal roster for Christian/Jake examples
    roster_text = """- Christian Liebenow — christian@example.com (AE)
- Jake Smith — jake@example.com (SDR)"""

    print("=" * 72)
    print("ROUTING SMOKE TESTS — 12 handlers + critical disambiguation")
    print("=" * 72)
    print()

    passed = 0
    failed = 0
    failures = []

    for question, expected_handler, min_confidence in SMOKE_TESTS:
        try:
            result = classify_question(question, client, roster_text)
            actual_handler = result.get("handler", "unknown")
            confidence = result.get("confidence", 0.0)

            # Check: correct handler AND reasonable confidence
            handler_match = actual_handler == expected_handler
            confidence_ok = confidence >= min_confidence

            if handler_match and confidence_ok:
                passed += 1
                print(f"✓ {expected_handler:30s} (conf={confidence:.2f})")
                print(f"  Q: {question[:60]}")
            else:
                failed += 1
                failures.append({
                    "question": question,
                    "expected": expected_handler,
                    "actual": actual_handler,
                    "confidence": confidence,
                    "min_confidence": min_confidence,
                })
                print(f"❌ {expected_handler:30s}")
                print(f"  Q: {question[:60]}")
                if not handler_match:
                    print(f"  Expected: {expected_handler}")
                    print(f"  Got:      {actual_handler}")
                if not confidence_ok:
                    print(f"  Confidence: {confidence:.2f} < {min_confidence:.2f} (too low)")

        except Exception as e:
            failed += 1
            failures.append({
                "question": question,
                "expected": expected_handler,
                "error": str(e),
            })
            print(f"❌ {expected_handler:30s}")
            print(f"  Q: {question[:60]}")
            print(f"  Error: {e}")

    print()
    print("=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 72)

    if failures:
        print()
        print("FAILURES:")
        for f in failures:
            print(f"\n  Question: {f['question']}")
            print(f"  Expected: {f['expected']}")
            if "actual" in f:
                print(f"  Got:      {f['actual']} (conf={f['confidence']:.2f}, min={f['min_confidence']:.2f})")
            if "error" in f:
                print(f"  Error:    {f['error']}")
        print()
        return 1

    print()
    print("All routing smoke tests passed ✓")
    return 0


if __name__ == "__main__":
    sys.exit(run_smoke_tests())
