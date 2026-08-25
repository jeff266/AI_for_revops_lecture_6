#!/usr/bin/env python3
"""
Tests for transcript_store module.

Guards against failure modes that cost real time in GrowthBook:
1. GraphQL body-error rate-limit detection (1,920 of 2,189 Fireflies calls failed)
2. Transient vs terminal classification (resume must re-attempt transients)
3. Apollo metrics use real timestamps (not utterance count)
4. Null transcript never empty string (CHECK constraint enforces NOT NULL or NULL)
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent))

from transcript_store import (
    _is_rate_limit,
    _classify_empty_transcript,
    compute_metrics,
    build_transcript_row
)


def test_graphql_body_error_triggers_rate_limit():
    """
    GraphQL body-level errors must trigger rate-limit backoff.

    GrowthBook failure: Fireflies returned 200 OK with {"errors": [...]}
    containing rate-limit messages, but code only checked HTTP 429.
    Result: 1,920 of 2,189 calls failed with no backoff.

    This test proves _is_rate_limit() catches body-level rate limits.
    """
    print("\n[TEST] GraphQL body-error triggers rate-limit backoff")

    # Real Fireflies rate-limit messages from GrowthBook logs
    fireflies_patterns = [
        "Rate limit exceeded. Please try again later.",
        "Too many requests. Please slow down.",
        "API quota exceeded",
        "You have been throttled",
    ]

    for msg in fireflies_patterns:
        assert _is_rate_limit(msg), f"Failed to detect rate limit in: {msg}"

    # Non-rate-limit errors should NOT trigger
    other_errors = [
        "Transcript not found",
        "Invalid transcript ID",
        "Authentication failed",
        "Internal server error",
    ]

    for msg in other_errors:
        assert not _is_rate_limit(msg), f"False positive rate limit on: {msg}"

    print("  ✓ Rate-limit detection works for GraphQL body errors")
    print("  ✓ Non-rate-limit errors don't trigger false backoff")


def test_transient_failure_is_retryable_not_terminal():
    """
    Transient failures (recent calls, still processing) must be retryable.

    GrowthBook issue: Empty transcripts were always marked 'unavailable'
    (TERMINAL), so resume never re-attempted them. Corrected logic uses
    unavailable_reason with TERMINAL/RETRY prefix to distinguish.

    The STILL_PROCESSING_DAYS threshold (default 3 days) means:
    - Call from 1 day ago: unavailable_reason='retry: ...' (might still be processing)
    - Call from 4 days ago: unavailable_reason='terminal: ...' (should exist by now)
    """
    from transcript_store import RETRY, TERMINAL, STILL_PROCESSING_DAYS

    print(f"\n[TEST] Transient failure is retryable, not terminal (threshold={STILL_PROCESSING_DAYS}d)")

    now = datetime.utcnow()

    # Recent call (within threshold) - should be RETRY
    recent_call = now - timedelta(days=1)
    reason = _classify_empty_transcript(recent_call)
    assert reason.startswith(RETRY), \
        f"Recent call (<{STILL_PROCESSING_DAYS}d) should start with '{RETRY}', got '{reason}'"

    # Old call (beyond threshold) - should be TERMINAL
    old_call = now - timedelta(days=STILL_PROCESSING_DAYS + 1)
    reason = _classify_empty_transcript(old_call)
    assert reason.startswith(TERMINAL), \
        f"Old call (>{STILL_PROCESSING_DAYS}d) should start with '{TERMINAL}', got '{reason}'"

    # Edge case: exactly at threshold boundary (STILL_PROCESSING_DAYS uses .days which truncates)
    # To cross the threshold, need full days > threshold
    edge_call = now - timedelta(days=STILL_PROCESSING_DAYS, hours=12)
    reason = _classify_empty_transcript(edge_call)
    # This is still <= threshold in whole days, so should be RETRY
    assert reason.startswith(RETRY), \
        f"Call at {STILL_PROCESSING_DAYS}d+12h (still {STILL_PROCESSING_DAYS} whole days) should be '{RETRY}', got '{reason}'"

    # Just past threshold
    past_threshold_call = now - timedelta(days=STILL_PROCESSING_DAYS + 1, hours=0)
    reason = _classify_empty_transcript(past_threshold_call)
    assert reason.startswith(TERMINAL), \
        f"Call at {STILL_PROCESSING_DAYS + 1}d should start with '{TERMINAL}', got '{reason}'"

    print(f"  ✓ Recent calls (<{STILL_PROCESSING_DAYS}d) are retryable (retry:)")
    print(f"  ✓ Old calls (>{STILL_PROCESSING_DAYS}d) are terminal (terminal:)")
    print("  ✓ Resume will re-attempt retryables, skip terminals")


def test_apollo_metrics_use_real_timestamps_and_sum_correctly():
    """
    Apollo metrics must use real timestamps (milliseconds), not utterance count.

    GrowthBook spot-check: Call had 919.0 + 1170.9 = 2089.9 total_speech_seconds
    exactly matching per-speaker talk time sum. This only works with real durations.

    The bug: sequential index as timestamps (0, 1, 2, 3...) makes talk_time
    equal utterance_count, not actual speaking time.
    """
    print("\n[TEST] Apollo metrics use real timestamps and sum correctly")

    # Apollo fragments with real millisecond timestamps (from GrowthBook field probe)
    apollo_utterances = [
        # Speaker A: 3 utterances totaling 919 seconds
        {'speaker': 'participant_1', 'display_name': 'Alice',
         'text': 'First point', 'start_seconds': 0.0, 'end_seconds': 300.0},  # 300s
        {'speaker': 'participant_1', 'display_name': 'Alice',
         'text': 'Second point', 'start_seconds': 350.0, 'end_seconds': 650.0},  # 300s
        {'speaker': 'participant_1', 'display_name': 'Alice',
         'text': 'Third point', 'start_seconds': 700.0, 'end_seconds': 1019.0},  # 319s

        # Speaker B: 2 utterances totaling 1170.9 seconds
        {'speaker': 'participant_2', 'display_name': 'Bob',
         'text': 'Response one', 'start_seconds': 1019.0, 'end_seconds': 1600.0},  # 581s
        {'speaker': 'participant_2', 'display_name': 'Bob',
         'text': 'Response two', 'start_seconds': 1650.0, 'end_seconds': 2239.9},  # 589.9s
    ]

    metrics = compute_metrics(apollo_utterances)

    # Talk time must use real durations, not utterance count
    talk_time = metrics['talk_time_seconds']
    assert 'participant_1' in talk_time, "Speaker A missing from talk_time"
    assert 'participant_2' in talk_time, "Speaker B missing from talk_time"

    # Expected: 300 + 300 + 319 = 919.0
    alice_time = talk_time['participant_1']
    assert abs(alice_time - 919.0) < 0.1, \
        f"Alice talk_time should be ~919.0s, got {alice_time:.1f}s"

    # Expected: 581 + 589.9 = 1170.9
    bob_time = talk_time['participant_2']
    assert abs(bob_time - 1170.9) < 0.1, \
        f"Bob talk_time should be ~1170.9s, got {bob_time:.1f}s"

    # Total should sum to ~2089.9
    total_speech = alice_time + bob_time
    assert abs(total_speech - 2089.9) < 0.1, \
        f"Total speech should be ~2089.9s, got {total_speech:.1f}s"

    print(f"  ✓ Alice: {alice_time:.1f}s (expected 919.0s)")
    print(f"  ✓ Bob: {bob_time:.1f}s (expected 1170.9s)")
    print(f"  ✓ Total: {total_speech:.1f}s (expected 2089.9s)")
    print("  ✓ Metrics use real timestamps, not utterance count")


def test_null_transcript_never_empty_string():
    """
    Null transcript must be NULL, never empty string.

    The CHECK constraint enforces (transcript_text IS NULL OR
    length(transcript_text) > 0). An empty string '' would violate this.

    build_transcript_row() must set transcript_text to None (NULL) for
    empty/failed transcripts, not ''.
    """
    print("\n[TEST] Null transcript never empty string (CHECK enforces it)")

    # Empty utterances - should produce NULL transcript
    row = build_transcript_row(
        source='fireflies',
        call_id='test-001',
        utterances=[],
        error=None,
        call_date=datetime.utcnow()
    )

    assert row['transcript_text'] is None, \
        f"Empty utterances should produce NULL transcript_text, got '{row['transcript_text']}'"
    assert row['transcript_quality'] == 'unavailable', \
        f"Recent empty should be 'unavailable', got '{row['transcript_quality']}'"
    assert row.get('unavailable_reason', '').startswith('retry:'), \
        f"Recent empty should have 'retry:' reason, got '{row.get('unavailable_reason')}'"

    # Fetch error - should produce NULL transcript with retry: prefix
    row = build_transcript_row(
        source='fireflies',
        call_id='test-002',
        utterances=None,
        error='Rate limit exceeded',
        call_date=datetime.utcnow()
    )

    assert row['transcript_text'] is None, \
        f"Error should produce NULL transcript_text, got '{row['transcript_text']}'"
    assert row['transcript_quality'] == 'unavailable', \
        f"Error should be 'unavailable', got '{row['transcript_quality']}'"
    assert row.get('unavailable_reason', '').startswith('retry:'), \
        f"Transient error should have 'retry:' reason, got '{row.get('unavailable_reason')}'"

    # Valid utterances - should produce non-empty string
    row = build_transcript_row(
        source='fireflies',
        call_id='test-003',
        utterances=[
            {'speaker': 'Alice', 'text': 'Hello', 'start_seconds': 0, 'end_seconds': 1}
        ],
        error=None,
        call_date=datetime.utcnow()
    )

    assert row['transcript_text'] is not None, \
        "Valid utterances should produce non-NULL transcript_text"
    assert len(row['transcript_text']) > 0, \
        "Valid utterances should produce non-empty transcript_text"
    assert 'Alice: Hello' in row['transcript_text'], \
        f"Transcript should contain utterance, got: {row['transcript_text']}"
    assert row.get('unavailable_reason') is None, \
        f"Valid transcript should have NULL unavailable_reason, got '{row.get('unavailable_reason')}'"

    print("  ✓ Empty utterances → NULL (not '') + retry: reason")
    print("  ✓ Fetch error → NULL (not '') + retry: reason")
    print("  ✓ Valid utterances → non-empty string + NULL reason")
    print("  ✓ CHECK(transcript_text IS NULL OR length > 0) will pass")


def test_is_done_single_authority_for_resume():
    """
    is_done() is the single authority for resume logic.

    A row is DONE (skip on resume) when:
    - Has text (quality != 'unavailable'), OR
    - Is a terminal empty (unavailable_reason starts with 'terminal:')

    A row is NOT DONE (retry on resume) when:
    - Is a retryable empty (unavailable_reason starts with 'retry:'), OR
    - Row is absent from table

    This prevents the two scale failures:
    1. Transient failures (rate limits) not skipped forever
    2. Old calls without transcripts not re-attempted every pass
    """
    from transcript_store import is_done, UNAVAILABLE, TERMINAL, RETRY

    print("\n[TEST] is_done() single authority for resume logic")

    # Has text - DONE
    assert is_done('full', None) == True, \
        "Row with text (quality='full') should be DONE"
    assert is_done('partial', None) == True, \
        "Row with text (quality='partial') should be DONE"
    assert is_done('fragments_only', None) == True, \
        "Row with text (quality='fragments_only') should be DONE"

    # Terminal empty - DONE
    assert is_done(UNAVAILABLE, f'{TERMINAL} no transcript (7d-old call, none will appear)') == True, \
        "Terminal empty should be DONE (skip on resume)"

    # Retryable empty - NOT DONE
    assert is_done(UNAVAILABLE, f'{RETRY} no transcript yet (recent call, may still be processing)') == False, \
        "Retryable empty should NOT be DONE (retry on resume)"
    assert is_done(UNAVAILABLE, f'{RETRY} Rate limit exceeded') == False, \
        "Transient failure should NOT be DONE (retry on resume)"

    # Edge cases
    assert is_done(UNAVAILABLE, None) == False, \
        "UNAVAILABLE with NULL reason should NOT be DONE (missing data)"
    assert is_done(UNAVAILABLE, '') == False, \
        "UNAVAILABLE with empty reason should NOT be DONE (missing data)"
    assert is_done(UNAVAILABLE, 'something else') == False, \
        "UNAVAILABLE without terminal: prefix should NOT be DONE"

    print("  ✓ Has text → DONE (skip)")
    print("  ✓ Terminal empty → DONE (skip)")
    print("  ✓ Retryable empty → NOT DONE (retry)")
    print("  ✓ Single authority prevents rate-limit casualties skipped forever")


def test_backchannel_rule_preserves_monologues():
    """
    Backchannel rule: A run isn't broken by other-speaker interjections
    totaling under 3 seconds.

    Without it, an eight-minute monologue reads as twelve short runs every
    time the other party says "mm-hmm."

    GrowthBook example: Sales rep speaks 5min (300s), prospect says "got it"
    (1s), rep continues 3min (180s) → should be one 480s monologue, not two
    separate 300s and 180s runs.
    """
    print("\n[TEST] Backchannel rule preserves monologues")

    # Scenario: Rep speaks 5min, prospect says "mm-hmm" (1s), rep continues 3min
    utterances = [
        {'speaker': 'rep', 'text': 'Let me explain our pricing model...',
         'start_seconds': 0.0, 'end_seconds': 300.0},  # 5 min

        {'speaker': 'prospect', 'text': 'mm-hmm',
         'start_seconds': 300.0, 'end_seconds': 301.0},  # 1s backchannel

        {'speaker': 'rep', 'text': 'And here are the key benefits...',
         'start_seconds': 301.0, 'end_seconds': 481.0},  # 3 min
    ]

    metrics = compute_metrics(utterances)
    monologues = metrics['longest_monologue_seconds']

    # Rep's longest monologue should be 480s (5min + 3min, ignoring 1s backchannel)
    rep_monologue = monologues.get('rep', 0.0)
    assert rep_monologue == 480.0, \
        f"Rep monologue should be 480s (backchannel ignored), got {rep_monologue}s"

    # Prospect's "mm-hmm" should NOT count as a monologue
    prospect_monologue = monologues.get('prospect', 0.0)
    assert prospect_monologue == 1.0, \
        f"Prospect backchannel should be 1s, got {prospect_monologue}s"

    print("  ✓ 5min + 3min with 1s backchannel = 480s monologue")
    print("  ✓ Backchannel not credited to monologue duration")

    # Scenario 2: Real speaker change (>3s interruption breaks the run)
    utterances2 = [
        {'speaker': 'rep', 'text': 'First point...',
         'start_seconds': 0.0, 'end_seconds': 300.0},  # 5 min

        {'speaker': 'prospect', 'text': 'Wait, let me clarify something...',
         'start_seconds': 300.0, 'end_seconds': 305.0},  # 5s (>3s threshold)

        {'speaker': 'rep', 'text': 'Sure, go ahead...',
         'start_seconds': 305.0, 'end_seconds': 485.0},  # 3 min
    ]

    metrics2 = compute_metrics(utterances2)
    monologues2 = metrics2['longest_monologue_seconds']

    # Rep's longest should be 300s (first run), not 480s (runs are broken)
    rep_monologue2 = monologues2.get('rep', 0.0)
    assert rep_monologue2 == 300.0, \
        f"Rep monologue should be 300s (real interruption breaks run), got {rep_monologue2}s"

    print("  ✓ 5s interruption (>3s threshold) breaks the run")
    print("  ✓ Longest monologue = 300s (first run), not 480s")


def main():
    """Run all transcript_store tests."""
    print("=" * 70)
    print("TRANSCRIPT_STORE TESTS")
    print("=" * 70)
    print("\nGuarding against GrowthBook failure modes:")
    print("- 1,920 of 2,189 Fireflies calls failed (no body-error detection)")
    print("- Transient empties marked terminal (resume skipped them)")
    print("- Apollo talk_time was utterance_count (no real timestamps)")
    print("- Empty string violated CHECK constraint\n")

    tests = [
        test_graphql_body_error_triggers_rate_limit,
        test_transient_failure_is_retryable_not_terminal,
        test_apollo_metrics_use_real_timestamps_and_sum_correctly,
        test_null_transcript_never_empty_string,
        test_backchannel_rule_preserves_monologues,
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
        print("\n⚠️  FIX BEFORE COMMITTING")
        print("These failures indicate production bugs that cost real time in GrowthBook.")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
