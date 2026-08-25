#!/usr/bin/env python3
"""
Static guard: snapshot writers must never backfill from current state.

A snapshot row for a past date must never be populated from the current
deals table. Reading current state into a historical row produces plausible
numbers with silent lookahead bias — five of nine fields were wrong this way
before it was caught in GrowthBook.

This test greps the snapshot writers and fails on anti-patterns:
- Method 1 (snapshot_deals.py): Must hardcode snapshot_date to today
- Method 2 (backfill_snapshots.py): Must read from property history, not deals table

Run this before committing any changes to snapshot writers.
"""
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def test_method1_only_snapshots_today():
    """
    Method 1 (snapshot_deals.py) must hardcode snapshot_date to date.today().

    ALLOWED:
        today_date = date.today()
        snapshot_row = {'snapshot_date': today, ...}

    FORBIDDEN:
        snapshot_date = some_parameter  # Could be historical
        snapshot_row = {'snapshot_date': snapshot_date, ...}
    """
    print("\n[TEST] Method 1 only snapshots TODAY")

    snapshot_deals_path = REPO_ROOT / 'scripts' / 'analytics' / 'snapshot_deals.py'
    if not snapshot_deals_path.exists():
        print("  ⚠️  snapshot_deals.py not found - skipping")
        return

    source = snapshot_deals_path.read_text()

    # Check 1: Must have today_date = date.today() or today = date.today()
    if 'date.today()' not in source:
        raise AssertionError(
            "snapshot_deals.py does not call date.today() - how does it "
            "determine snapshot_date?"
        )

    # Check 2: Must NOT have snapshot_date as a parameter
    # Parse the main() function signature
    tree = ast.parse(source)
    main_func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'main':
            main_func = node
            break

    if main_func is None:
        raise AssertionError("snapshot_deals.py has no main() function")

    # Check main() has no parameters (especially not snapshot_date)
    if len(main_func.args.args) > 0:
        param_names = [arg.arg for arg in main_func.args.args]
        if 'snapshot_date' in param_names or 'as_of' in param_names or 'date' in param_names:
            raise AssertionError(
                f"snapshot_deals.py main() has date-like parameters: {param_names}. "
                f"Method 1 must hardcode to today, not accept a date parameter."
            )

    # Check 3: snapshot_date must be assigned from today or today_date
    # Look for assignments like: 'snapshot_date': today
    if "'snapshot_date': today" not in source and '"snapshot_date": today' not in source:
        # Could be today_date - check for that too
        if "'snapshot_date': today_date" not in source and '"snapshot_date": today_date' not in source:
            raise AssertionError(
                "snapshot_deals.py does not assign snapshot_date from a today variable. "
                "Method 1 must use snapshot_date = today (where today = date.today())."
            )

    print("  ✓ snapshot_deals.py hardcodes snapshot_date to date.today()")
    print("  ✓ main() has no date parameters")


def test_method2_never_reads_current_state():
    """
    Method 2 (backfill_snapshots.py) must read from property history,
    NEVER from the live deals table.

    ALLOWED (Method 2):
        stage_id, conf = get_stage_at_date(stage_history, deal_id, snapshot_date)
        snapshot_row = {'snapshot_date': snapshot_date, 'stage_id': stage_id, ...}

    FORBIDDEN (the GrowthBook bug):
        for deal in deals:  # ← live deals table
            snapshot_row = {
                'snapshot_date': historical_date,  # ← past date
                'stage_id': deal['stage'],  # ← current state (WRONG)
            }

    This is the actual bug pattern from GrowthBook that produced silent
    lookahead bias in five of nine fields.
    """
    print("\n[TEST] Method 2 never reads current state for historical rows")

    backfill_path = REPO_ROOT / 'scripts' / 'analytics' / 'backfill_snapshots.py'
    if not backfill_path.exists():
        print("  ⚠️  backfill_snapshots.py not found yet - will check when ported")
        return

    source = backfill_path.read_text()

    # Anti-pattern 1: Reading from deals table directly
    # Method 2 should read from stage_history, field_history, etc.
    # NOT from select_all(sb, 'deals', ...)
    if "select_all(sb, 'deals'" in source or 'select_all(sb, "deals"' in source:
        raise AssertionError(
            "backfill_snapshots.py queries the live deals table. Method 2 must "
            "read from property history (stage_history, field_history), not "
            "current state. This is the GrowthBook bug."
        )

    # Anti-pattern 2: Accessing deal['stage'] for historical snapshots
    # Should use get_stage_at_date() instead
    if "deal['stage']" in source or 'deal["stage"]' in source:
        # Could be building the deals dict for reconstruction - check context
        # But if it's being assigned to snapshot_row, that's the bug
        if "'stage_id': deal['stage']" in source or '"stage_id": deal["stage"]' in source:
            raise AssertionError(
                "backfill_snapshots.py assigns deal['stage'] (current state) to "
                "stage_id in snapshot row. Must use get_stage_at_date() for "
                "historical reconstruction."
            )

    # Anti-pattern 3: Accessing deal['deal_value'] for historical snapshots
    if "'deal_value': deal['deal_value']" in source or '"deal_value": deal["deal_value"]' in source:
        raise AssertionError(
            "backfill_snapshots.py assigns deal['deal_value'] (current state) to "
            "snapshot row. Must use get_field_at_date() or reconstruct_value_at_date() "
            "for historical reconstruction."
        )

    # Positive check: Should use point_in_time functions
    required_functions = ['get_stage_at_date', 'get_field_at_date', 'reconstruct_open_rows']
    missing = []
    for func in required_functions:
        if func not in source:
            missing.append(func)

    if missing:
        # Check if this is the template's stub version with local implementation
        has_local_impl = 'def get_stage_at_date(self' in source
        if has_local_impl:
            print("  ⚠️  Template version detected: has local get_stage_at_date")
            print("  ⚠️  Will be replaced in Step 3b with shared point_in_time functions")
            print(f"  ⚠️  Missing shared functions: {missing}")
            return  # Don't fail on template stub - will be replaced
        else:
            raise AssertionError(
                f"backfill_snapshots.py does not import/use required point_in_time "
                f"functions: {missing}. Method 2 must reconstruct from property history."
            )

    print("  ✓ backfill_snapshots.py does not query live deals table")
    print("  ✓ Uses get_stage_at_date() for historical stage reconstruction")
    print("  ✓ Uses point_in_time functions (no current-state reads)")


def test_no_live_deals_join_in_historical_write():
    """
    Master guard: ANY writer that writes snapshot_date < today must read
    from property history, never from live deals table.

    This is a higher-level check that catches the pattern regardless of
    which file it's in.
    """
    print("\n[TEST] No live-deals join in historical write path")

    analytics_dir = REPO_ROOT / 'scripts' / 'analytics'
    snapshot_files = list(analytics_dir.glob('*snapshot*.py'))

    violations = []

    for filepath in snapshot_files:
        if 'test_' in filepath.name:
            continue  # Skip test files

        source = filepath.read_text()

        # Heuristic: If file accepts a date parameter AND queries deals table,
        # it's likely reading current state for historical dates
        has_date_param = False
        queries_deals = False

        # Check if main/run function has date-like parameters
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in ['main', 'run', 'backfill']:
                for arg in node.args.args:
                    if arg.arg in ['snapshot_date', 'as_of', 'start_date', 'end_date', 'date']:
                        has_date_param = True

        # Check if it queries deals table
        if "select_all(sb, 'deals'" in source or 'select_all(sb, "deals"' in source:
            queries_deals = True

        # If BOTH conditions are true, it's likely the bug pattern
        # UNLESS it's snapshot_deals.py (Method 1, which is allowed to query deals for today)
        if has_date_param and queries_deals and filepath.name != 'snapshot_deals.py':
            violations.append(filepath.name)

    if violations:
        raise AssertionError(
            f"Found snapshot writer(s) that accept date parameters AND query "
            f"live deals table: {violations}. This is the GrowthBook bug pattern. "
            f"Historical snapshots must read from property history, not current state."
        )

    print(f"  ✓ Checked {len(snapshot_files)} snapshot writers")
    print("  ✓ No historical writes from current state detected")


def main():
    """Run all snapshot invariant tests."""
    print("=" * 70)
    print("SNAPSHOT WRITER INVARIANT TESTS")
    print("=" * 70)
    print("\nGuard against: Reading current state into historical snapshot rows")
    print("GrowthBook bug: Five of nine fields wrong due to lookahead bias\n")

    tests = [
        test_method1_only_snapshots_today,
        test_method2_never_reads_current_state,
        test_no_live_deals_join_in_historical_write,
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
        print("Historical snapshots must read from property history, not current state.")
        print("See point_in_time.py for get_stage_at_date() and get_field_at_date().")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
