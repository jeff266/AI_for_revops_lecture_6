#!/usr/bin/env python3
"""
Tests for router.py production fixes.

These test failures that shipped to production:
1. Deal ID string char-iterated to in.(6,0,1,4,...)
2. Cached deal_id hijacked follow-ups with explicit IDs
3. Synthesis invented causes instead of stating facts
4. Two-deal response truncated mid-sentence
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / 'scripts'))
sys.path.insert(0, str(_REPO_ROOT / 'api'))

from supabase_client import _coerce_in_values
from router import (
    extract_explicit_deal_ids,
    _result_summary,
    _below_floor,
    _honest_miss,
    _looks_truncated
)


def test_single_deal_id_not_char_iterated():
    """A deal_id string must never expand to characters. Produced
    in.(6,0,1,4,...) — a query on nonsense ids.

    Production fix #1: _coerce_in_values in supabase_client.py"""
    print("\n[TEST] Deal ID string not char-iterated")

    # Single deal ID as string (the bug case)
    result = _coerce_in_values("60785721693")
    assert result == ["60785721693"], \
        f"Single ID string should become ['60785721693'], got {result}"
    print("  ✓ Single ID string → ['60785721693']")

    # Comma-joined IDs
    result = _coerce_in_values("60785,60786,60787")
    assert result == ["60785", "60786", "60787"], \
        f"Comma-joined should split, got {result}"
    print("  ✓ Comma-joined IDs split correctly")

    # Already a list (should pass through)
    result = _coerce_in_values(["60785", "60786"])
    assert result == ["60785", "60786"], \
        f"List should pass through, got {result}"
    print("  ✓ List passes through unchanged")

    # Quoted values should be de-quoted
    result = _coerce_in_values(['"60785"', "'60786'"])
    assert result == ["60785", "60786"], \
        f"Quotes should be stripped, got {result}"
    print("  ✓ Quotes stripped from values")

    print("  ✓ PASS: _coerce_in_values prevents character iteration")


def test_explicit_ids_override_thread_context():
    """IDs in the current message win over cached entities. A stale
    deal_id hijacked every follow-up in the thread.

    Production fix #2: extract_explicit_deal_ids() and entity override logic."""
    print("\n[TEST] Explicit IDs override thread context")

    # Question with explicit deal ID
    question1 = "What's the status of deal 60785?"
    ids = extract_explicit_deal_ids(question1)
    assert ids == ["60785"], \
        f"Should extract 60785, got {ids}"
    print("  ✓ Extracted deal 60785 from question")

    # Question with multiple IDs
    question2 = "Compare deals 12345 and 67890"
    ids = extract_explicit_deal_ids(question2)
    assert set(ids) == {"12345", "67890"}, \
        f"Should extract both IDs, got {ids}"
    print("  ✓ Extracted multiple IDs")

    # Question with no IDs (pronoun reference)
    question3 = "What about those deals?"
    ids = extract_explicit_deal_ids(question3)
    assert ids == [], \
        f"Should find no IDs in pronoun question, got {ids}"
    print("  ✓ No IDs extracted from pronoun reference")

    # Question with 5-digit minimum (not phone numbers)
    question4 = "Call me at 555-1234 about deal 123456"
    ids = extract_explicit_deal_ids(question4)
    assert ids == ["123456"], \
        f"Should only extract 6-digit deal ID, got {ids}"
    print("  ✓ 5+ digit minimum prevents phone number extraction")

    print("  ✓ PASS: Explicit IDs correctly extracted from current message")


def test_below_floor_returns_honest_miss_not_speculation():
    """Below the confidence floor, state what was queried and what came
    back. Never invent causes — that's the bug this replaces.

    Production fixes #4 and #5: _result_summary(), _honest_miss(), _below_floor()."""
    print("\n[TEST] Below-floor honest miss (no speculation)")

    # Test _result_summary: factual count-only
    tool_results_empty = {"rows": []}
    summary = _result_summary(tool_results_empty)
    assert "no matching rows came back" in summary, \
        f"Empty result should say 'no matching rows', got: {summary}"
    print(f"  ✓ Empty result: '{summary}'")

    tool_results_with_data = {"rows": [{"deal_id": "123"}, {"deal_id": "456"}]}
    summary = _result_summary(tool_results_with_data)
    assert "2 rows came back" in summary, \
        f"Should say '2 rows came back', got: {summary}"
    print(f"  ✓ Non-empty result: '{summary}'")

    # Test _below_floor: blocks low scores
    assessment_low = {"score": 0.20}
    assert _below_floor(assessment_low, floor=0.30), \
        "Score 0.20 should be below floor 0.30"
    print("  ✓ Score 0.20 blocked at floor 0.30")

    assessment_ok = {"score": 0.40}
    assert not _below_floor(assessment_ok, floor=0.30), \
        "Score 0.40 should pass floor 0.30"
    print("  ✓ Score 0.40 passes floor 0.30")

    # Test exemptions
    assessment_skipped = {"skipped": True, "score": 0.10}
    assert not _below_floor(assessment_skipped), \
        "Skipped assessment should not be blocked"
    print("  ✓ Skipped assessment exempt from floor")

    assessment_data_gap = {"issue": "data_gap", "score": 0.10}
    assert not _below_floor(assessment_data_gap), \
        "data_gap issue should not be blocked"
    print("  ✓ data_gap acknowledged, exempt from floor")

    # Test _honest_miss: no speculation about causes
    miss_msg = _honest_miss("query_deals_at_risk", tool_results_empty)

    # Should contain facts: handler name, what came back
    assert "query_deals_at_risk" in miss_msg, \
        "Message should name the handler"
    assert "no matching rows came back" in miss_msg, \
        "Message should state what came back"

    # Should NOT contain speculation
    speculation_words = ["might not exist", "might be", "could be",
                        "possibly", "perhaps", "maybe"]
    for word in speculation_words:
        assert word not in miss_msg.lower(), \
            f"Message should not speculate with '{word}'"

    print(f"  ✓ Honest miss message: facts only, no speculation")
    print("  ✓ PASS: Below-floor path returns honest miss")


def test_multi_deal_synthesis_not_truncated():
    """A two-deal response must complete. 1670 chars of tool_results
    produced a mid-sentence cutoff at the old ceiling.

    Production fix #7: SYNTH_MAX_TOKENS increased, _looks_truncated() detector."""
    print("\n[TEST] Multi-deal synthesis not truncated")

    # Complete answer (ends with period)
    complete = "Here are the two deals with their MEDDICC scores."
    assert not _looks_truncated(complete), \
        "Complete sentence should not be flagged as truncated"
    print("  ✓ Complete answer not flagged")

    # Truncated mid-sentence (ends without punctuation)
    truncated = "Here are the two deals with their"
    assert _looks_truncated(truncated), \
        "Mid-word cutoff should be detected as truncated"
    print("  ✓ Mid-sentence cutoff detected")

    # Trailing markdown emphasis should be handled
    complete_with_md = "**Deal 60785** has strong scores."
    assert not _looks_truncated(complete_with_md), \
        "Markdown emphasis before period should not trigger"
    print("  ✓ Markdown emphasis handled correctly")

    # Empty/whitespace not truncated (different failure mode)
    assert not _looks_truncated(""), \
        "Empty string is not truncation, it's a different failure"
    assert not _looks_truncated("   "), \
        "Whitespace is not truncation"
    print("  ✓ Empty result not confused with truncation")

    # Unfinished list item
    unfinished_list = "The deals are:\n- Deal 60785 with strong"
    assert _looks_truncated(unfinished_list), \
        "Unfinished list item should be detected"
    print("  ✓ Unfinished list item detected")

    # Complete list item
    complete_list = "The deals are:\n- Deal 60785 with strong scores."
    assert not _looks_truncated(complete_list), \
        "Complete list item should not trigger"
    print("  ✓ Complete list item passes")

    print("  ✓ PASS: Truncation detector works correctly")


def main():
    """Run all router production fix tests."""
    print("=" * 70)
    print("ROUTER PRODUCTION FIXES TESTS")
    print("=" * 70)
    print("\nGuards against failures that shipped to production")

    tests = [
        test_single_deal_id_not_char_iterated,
        test_explicit_ids_override_thread_context,
        test_below_floor_returns_honest_miss_not_speculation,
        test_multi_deal_synthesis_not_truncated,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"\n❌ FAILED: {test.__name__}")
            print(f"   {e}")
        except Exception as e:
            failed += 1
            print(f"\n❌ ERROR in {test.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    if failed > 0:
        print("\n⚠️  PRODUCTION FIX REGRESSION DETECTED")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
