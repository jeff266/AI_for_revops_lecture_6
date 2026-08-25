#!/usr/bin/env python3
"""
Fixture tests for point_in_time.py - prove the reconstruction invariants.

These fixtures demonstrate that point_in_time reconstruction:
1. Handles deals moving backward (stage regression) correctly
2. Returns null when no history exists (never defaults/guesses)
3. Never looks ahead (strictly backward-looking)
4. Distinguishes cleared vs pre_history

Run: python3 scripts/analytics/test_point_in_time.py
"""
import sys
from pathlib import Path
from datetime import datetime, date

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from point_in_time import (
    get_stage_at_date,
    get_field_at_date,
    is_deal_open_at_date,
    is_terminal_stage,
    UnclassifiableStageError,
)


def test_deal_moving_backward():
    """
    Fixture: Deal regresses from Scoping back to Discovery.

    Timeline:
    - 2024-01-01: Created in Discovery
    - 2024-01-15: Moved to Scoping (progress)
    - 2024-02-01: Moved back to Discovery (regression)
    - 2024-02-15: Moved to Proposal (recovered)

    Point-in-time reads must handle backward movement correctly.
    """
    print("\n[FIXTURE] Deal moving backward (regression)")

    property_history = {
        'deal_123': {
            'history': [
                {'timestamp': '2024-01-01T00:00:00', 'value': 'appointmentscheduled'},  # Discovery
                {'timestamp': '2024-01-15T00:00:00', 'value': 'qualifiedtobuy'},        # Scoping
                {'timestamp': '2024-02-01T00:00:00', 'value': 'appointmentscheduled'},  # Back to Discovery
                {'timestamp': '2024-02-15T00:00:00', 'value': 'presentationscheduled'}, # Proposal
            ]
        }
    }

    # Test 1: Before regression (should be Scoping)
    stage, conf, _ = get_stage_at_date(
        property_history, 'deal_123',
        datetime(2024, 1, 20)
    )
    assert stage == 'qualifiedtobuy', f"Expected Scoping on 2024-01-20, got {stage}"
    assert conf == 'exact'
    print("  ✓ 2024-01-20: qualifiedtobuy (Scoping) - before regression")

    # Test 2: After regression (should be Discovery again)
    stage, conf, _ = get_stage_at_date(
        property_history, 'deal_123',
        datetime(2024, 2, 5)
    )
    assert stage == 'appointmentscheduled', f"Expected Discovery on 2024-02-05, got {stage}"
    assert conf == 'exact'
    print("  ✓ 2024-02-05: appointmentscheduled (Discovery) - after regression")

    # Test 3: After recovery (should be Proposal)
    stage, conf, _ = get_stage_at_date(
        property_history, 'deal_123',
        datetime(2024, 2, 20)
    )
    assert stage == 'presentationscheduled', f"Expected Proposal on 2024-02-20, got {stage}"
    assert conf == 'exact'
    print("  ✓ 2024-02-20: presentationscheduled (Proposal) - after recovery")

    print("  ✓ Backward movement handled correctly (no assumptions about monotonicity)")


def test_no_history_returns_null():
    """
    Fixture: Deal exists but has no stage history at snapshot date.

    Must return null, never guess, never default, never forward-fill.

    Timeline:
    - 2024-01-01: Deal created (no stage set)
    - 2024-01-15: First stage set (Discovery)

    Snapshots before 2024-01-15 must see null, not Discovery.
    """
    print("\n[FIXTURE] No history returns null (never defaults)")

    property_history = {
        'deal_456': {
            'history': [
                {'timestamp': '2024-01-15T00:00:00', 'value': 'appointmentscheduled'},
            ]
        }
    }

    # Test 1: Before first history entry (should be None with pre_history confidence)
    stage, conf, _ = get_stage_at_date(
        property_history, 'deal_456',
        datetime(2024, 1, 10)
    )
    assert stage is None, f"Expected None on 2024-01-10 (before history), got {stage}"
    assert conf == 'pre_history', f"Expected pre_history confidence, got {conf}"
    print("  ✓ 2024-01-10: None (pre_history) - deal existed, history doesn't reach")

    # Test 2: On the day stage was set (should have value)
    stage, conf, _ = get_stage_at_date(
        property_history, 'deal_456',
        datetime(2024, 1, 15)
    )
    assert stage == 'appointmentscheduled', f"Expected Discovery on 2024-01-15, got {stage}"
    assert conf == 'exact'
    print("  ✓ 2024-01-15: appointmentscheduled (exact) - history covers")

    # Test 3: No history at all (should be None with no_history confidence)
    stage, conf, _ = get_stage_at_date(
        property_history, 'deal_999',  # Deal doesn't exist
        datetime(2024, 1, 10)
    )
    assert stage is None, f"Expected None for missing deal, got {stage}"
    assert conf == 'no_history', f"Expected no_history confidence, got {conf}"
    print("  ✓ deal_999: None (no_history) - no property history available")

    print("  ✓ No defaults, no guesses, no forward-fill")


def test_no_lookahead():
    """
    Fixture: Strictly backward-looking - entries after snapshot date never selected.

    Timeline:
    - 2024-01-01: Discovery
    - 2024-02-01: Scoping
    - 2024-03-01: Closed Won

    Snapshot on 2024-01-20 must see Discovery, NOT Scoping (even though Scoping
    is the "next" stage). This is the lookahead bias that broke GrowthBook.
    """
    print("\n[FIXTURE] No lookahead (strictly backward-looking)")

    property_history = {
        'deal_789': {
            'history': [
                {'timestamp': '2024-01-01T00:00:00', 'value': 'appointmentscheduled'},
                {'timestamp': '2024-02-01T00:00:00', 'value': 'qualifiedtobuy'},
                {'timestamp': '2024-03-01T00:00:00', 'value': 'closedwon'},
            ]
        }
    }

    # Test 1: Between first and second entry (must NOT see second entry)
    stage, conf, _ = get_stage_at_date(
        property_history, 'deal_789',
        datetime(2024, 1, 20)
    )
    assert stage == 'appointmentscheduled', \
        f"Lookahead detected! Expected Discovery on 2024-01-20, got {stage}"
    assert conf == 'exact'
    print("  ✓ 2024-01-20: appointmentscheduled (Discovery) - not Scoping")

    # Test 2: Between second and third entry (must NOT see Closed Won)
    stage, conf, _ = get_stage_at_date(
        property_history, 'deal_789',
        datetime(2024, 2, 15)
    )
    assert stage == 'qualifiedtobuy', \
        f"Lookahead detected! Expected Scoping on 2024-02-15, got {stage}"
    assert conf == 'exact'
    print("  ✓ 2024-02-15: qualifiedtobuy (Scoping) - not Closed Won")

    # Test 3: Exact boundary (on the day of change, should see NEW value)
    stage, conf, _ = get_stage_at_date(
        property_history, 'deal_789',
        datetime(2024, 2, 1)
    )
    assert stage == 'qualifiedtobuy', \
        f"Expected Scoping on 2024-02-01 (change date), got {stage}"
    print("  ✓ 2024-02-01: qualifiedtobuy (Scoping) - boundary case correct")

    print("  ✓ No lookahead - strictly backward-looking at all dates")


def test_cleared_vs_pre_history():
    """
    Fixture: Distinguish 'cleared' (actively unstaged) from 'pre_history' (never staged).

    Timeline:
    - Deal A: Never had a stage set → pre_history
    - Deal B: Had stage, then cleared → cleared

    Both read as None/open, but they're different facts and should be labelled differently.
    """
    print("\n[FIXTURE] Cleared vs pre_history distinction")

    # Deal A: History starts after snapshot date
    property_history_pre = {
        'deal_A': {
            'history': [
                {'timestamp': '2024-02-01T00:00:00', 'value': 'appointmentscheduled'},
            ]
        }
    }

    # Deal B: Stage was set, then cleared (set to null)
    property_history_cleared = {
        'deal_B': {
            'history': [
                {'timestamp': '2024-01-01T00:00:00', 'value': 'appointmentscheduled'},
                {'timestamp': '2024-01-15T00:00:00', 'value': None},  # Actively cleared
            ]
        }
    }

    # Test 1: pre_history (deal existed, never staged at this date)
    stage, conf, _ = get_stage_at_date(
        property_history_pre, 'deal_A',
        datetime(2024, 1, 20)
    )
    assert stage is None
    assert conf == 'pre_history', f"Expected pre_history, got {conf}"
    print("  ✓ Deal A: None (pre_history) - history doesn't reach this date")

    # Test 2: cleared (deal was staged, then actively unstaged)
    stage, conf, _ = get_stage_at_date(
        property_history_cleared, 'deal_B',
        datetime(2024, 1, 20)
    )
    assert stage is None
    assert conf == 'cleared', f"Expected cleared, got {conf}"
    print("  ✓ Deal B: None (cleared) - stage was actively cleared")

    # Both are open, but the facts are different
    print("  ✓ Both read as open, but labelled differently (different facts)")


def test_inclusion_rule_with_fixtures():
    """
    Fixture: is_deal_open_at_date with edge cases.

    Tests:
    - Deal created after snapshot date → excluded
    - Deal in terminal stage → excluded
    - Deal with no stage (pre_history) → included (open)
    - Deal with cleared stage → included (open)
    """
    print("\n[FIXTURE] Inclusion rule edge cases")

    # Test 1: Created after snapshot date → excluded
    create_date = datetime(2024, 2, 1)
    snapshot_date = datetime(2024, 1, 15)
    result = is_deal_open_at_date(create_date, 'appointmentscheduled', snapshot_date)
    assert result is False, "Deal created after snapshot should be excluded"
    print("  ✓ Created after snapshot → excluded")

    # Test 2: Terminal stage → excluded
    create_date = datetime(2024, 1, 1)
    snapshot_date = datetime(2024, 2, 1)
    result = is_deal_open_at_date(create_date, 'closedwon', snapshot_date)
    assert result is False, "Closed Won deal should be excluded"
    print("  ✓ Terminal stage (Closed Won) → excluded")

    # Test 3: No stage (None) → included (open by default)
    result = is_deal_open_at_date(create_date, None, snapshot_date)
    assert result is True, "Deal with no stage should be open"
    print("  ✓ No stage (None) → included (open)")

    # Test 4: Open stage → included
    result = is_deal_open_at_date(create_date, 'appointmentscheduled', snapshot_date)
    assert result is True, "Discovery stage should be open"
    print("  ✓ Open stage (Discovery) → included")

    print("  ✓ Inclusion rule handles all edge cases correctly")


def test_field_reconstruction():
    """
    Fixture: get_field_at_date for deal_value reconstruction.

    Tests same backward-looking logic for non-stage fields.
    """
    print("\n[FIXTURE] Field reconstruction (deal_value)")

    field_history = {
        'deal_123': {
            'history': [
                {'timestamp': '2024-01-01T00:00:00', 'value': 50000},
                {'timestamp': '2024-02-01T00:00:00', 'value': 75000},
                {'timestamp': '2024-03-01T00:00:00', 'value': 100000},
            ]
        }
    }

    # Test 1: Before first change
    value, conf = get_field_at_date(
        field_history, 'deal_123',
        datetime(2023, 12, 15)
    )
    assert value is None, f"Expected None before history, got {value}"
    assert conf == 'pre_history'
    print("  ✓ 2023-12-15: None (pre_history) - before first value")

    # Test 2: Between first and second
    value, conf = get_field_at_date(
        field_history, 'deal_123',
        datetime(2024, 1, 15)
    )
    assert value == 50000, f"Expected 50000 on 2024-01-15, got {value}"
    assert conf == 'exact'
    print("  ✓ 2024-01-15: 50000 (exact) - first value")

    # Test 3: Between second and third (no lookahead)
    value, conf = get_field_at_date(
        field_history, 'deal_123',
        datetime(2024, 2, 15)
    )
    assert value == 75000, f"Expected 75000 on 2024-02-15, got {value}"
    assert conf == 'exact'
    print("  ✓ 2024-02-15: 75000 (exact) - second value, not 100000")

    print("  ✓ Field reconstruction uses same backward-looking logic")


def main():
    """Run all fixture tests."""
    print("=" * 70)
    print("POINT-IN-TIME FIXTURE TESTS")
    print("=" * 70)
    print("\nProving reconstruction invariants:")
    print("1. Handles backward movement (stage regression)")
    print("2. Returns null when no history (never defaults)")
    print("3. No lookahead (strictly backward-looking)")
    print("4. Distinguishes cleared vs pre_history")

    tests = [
        test_deal_moving_backward,
        test_no_history_returns_null,
        test_no_lookahead,
        test_cleared_vs_pre_history,
        test_inclusion_rule_with_fixtures,
        test_field_reconstruction,
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

    if failed == 0:
        print("\n✅ All invariants proven by fixtures")
        print("point_in_time reconstruction is correct:")
        print("  - Handles stage regression")
        print("  - Never defaults/guesses")
        print("  - Strictly backward-looking")
        print("  - Distinguishes cleared vs pre_history")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
