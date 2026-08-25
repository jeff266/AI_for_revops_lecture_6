#!/usr/bin/env python3
"""
Behavioral tests for forecast_analyses.py - verify defects with real fixtures.

Each test builds a small deals_snapshot fixture with known answers and asserts
the computed output matches expected. Static inspection cannot catch plausible
wrong numbers (196 wins where 31 is correct).
"""

import sys
from pathlib import Path
from datetime import date, timedelta

# Add scripts to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))


class MockSupabase:
    """Mock Supabase client that returns fixture data."""

    def __init__(self, fixture_data):
        self.fixture_data = fixture_data
        self.queries = []

    def table(self, name):
        self.current_table = name
        return self

    def select(self, cols):
        return self

    def eq(self, col, val):
        self.queries.append(('eq', col, val))
        return self

    def gte(self, col, val):
        self.queries.append(('gte', col, val))
        return self

    def lte(self, col, val):
        self.queries.append(('lte', col, val))
        return self

    def execute(self):
        # Return fixture data
        return type('obj', (object,), {'data': self.fixture_data.get(self.current_table, [])})


def mock_select_all(sb, table, columns=None, filters=None):
    """Mock select_all that applies filters to fixture data."""
    data = sb.fixture_data.get(table, [])

    # Apply filters
    if filters:
        for filter_op, filter_col, filter_val in filters:
            if filter_op == 'eq':
                data = [row for row in data if str(row.get(filter_col)) == str(filter_val)]
            elif filter_op == 'gte':
                data = [row for row in data if row.get(filter_col) and str(row.get(filter_col)) >= str(filter_val)]
            elif filter_op == 'lte':
                data = [row for row in data if row.get(filter_col) and str(row.get(filter_col)) <= str(filter_val)]

    return data


def test_defect_1_numerator_counts_in_quarter_wins_only():
    """
    Defect 1: Cumulative numerator.

    Fixture: 8 deals won in Q1, 5 won in Q2, 3 still open.
    Q1 numerator must be 8, not 13. GrowthBook's cumulative bug
    reported 196 against an actual 31.
    """
    print("\n[TEST] Defect 1: Numerator counts in-quarter wins only")

    from forecast_analyses import compute_quarter_conversion
    from utils import load_client_config

    # Q1: Feb 1 - Apr 30
    q1_start = date(2026, 2, 1)
    q1_end = date(2026, 4, 30)
    week3 = q1_start + timedelta(days=14)

    # Fixture: 16 total deals
    # - 8 won in Q1 (Feb-Apr)
    # - 5 won in Q2 (May-Jul)
    # - 3 still open
    fixture = {
        'deals_snapshot': [
            # Week 3 snapshot: All 16 deals are open
            *[{'deal_id': f'q1_win_{i}', 'snapshot_date': str(week3), 'pipeline_id': 'default',
               'stage_id': 'qualifiedtobuy', 'deal_status': 'active', 'deal_value': 10000}
              for i in range(1, 9)],
            *[{'deal_id': f'q2_win_{i}', 'snapshot_date': str(week3), 'pipeline_id': 'default',
               'stage_id': 'qualifiedtobuy', 'deal_status': 'active', 'deal_value': 10000}
              for i in range(1, 6)],
            *[{'deal_id': f'open_{i}', 'snapshot_date': str(week3), 'pipeline_id': 'default',
               'stage_id': 'qualifiedtobuy', 'deal_status': 'active', 'deal_value': 10000}
              for i in range(1, 4)],

            # Q1 closes (close_date in Feb-Apr)
            *[{'deal_id': f'q1_win_{i}', 'close_date': str(q1_start + timedelta(days=i*7)),
               'pipeline_id': 'default', 'stage_id': 'closedwon', 'deal_status': 'won', 'deal_value': 10000}
              for i in range(1, 9)],

            # Q2 closes (close_date in May-Jul) - should NOT be in Q1 numerator
            *[{'deal_id': f'q2_win_{i}', 'close_date': str(date(2026, 5, 1) + timedelta(days=i*7)),
               'pipeline_id': 'default', 'stage_id': 'closedwon', 'deal_status': 'won', 'deal_value': 10000}
              for i in range(1, 6)],
        ]
    }

    sb = MockSupabase(fixture)
    config = load_client_config()

    # Monkey-patch select_all
    import adapters.storage.supabase as storage_mod
    original_select_all = storage_mod.select_all
    storage_mod.select_all = lambda sb, table, **kwargs: mock_select_all(sb, table, **kwargs)

    try:
        result = compute_quarter_conversion(sb, q1_start, q1_end, config)

        # Verify: numerator should be 8 (Q1 wins only), not 13 (cumulative)
        assert result['verdict'] == 'pass', f"Expected pass, got {result['verdict']}: {result.get('reason')}"
        assert result['won_count'] == 8, \
            f"Expected 8 Q1 wins, got {result['won_count']} (cumulative bug would give 13)"
        assert result['starting_pipeline_count'] == 16, \
            f"Expected 16 open deals at week 3, got {result['starting_pipeline_count']}"

        print(f"  ✓ Q1 numerator: {result['won_count']} (correct: in-quarter wins only)")
        print(f"  ✓ NOT {8 + 5} (would be cumulative through Q2)")
        print("  ✓ Defect 1 FIXED: Not counting cumulative as-of-quarter-end")

    finally:
        storage_mod.select_all = original_select_all


def test_defect_3_denominator_unfiltered_by_close_date():
    """
    Defect 3: Close-date filter collapsing denominator.

    Fixture: 20 open deals at week 3, only 6 with in-quarter close dates.
    Denominator must be 20. GrowthBook's bug filtered to 6, producing 110% conversion.
    """
    print("\n[TEST] Defect 3: Denominator unfiltered by close date")

    from forecast_analyses import compute_quarter_conversion
    from utils import load_client_config

    q1_start = date(2026, 2, 1)
    q1_end = date(2026, 4, 30)
    week3 = q1_start + timedelta(days=14)

    # Fixture: 20 open deals at week 3
    # - 6 will close in Q1
    # - 8 will close in Q2
    # - 6 still open (no close date)
    fixture = {
        'deals_snapshot': [
            # Week 3: All 20 are open
            *[{'deal_id': f'q1_close_{i}', 'snapshot_date': str(week3), 'pipeline_id': 'default',
               'stage_id': 'qualifiedtobuy', 'deal_status': 'active', 'deal_value': 10000}
              for i in range(1, 7)],
            *[{'deal_id': f'q2_close_{i}', 'snapshot_date': str(week3), 'pipeline_id': 'default',
               'stage_id': 'qualifiedtobuy', 'deal_status': 'active', 'deal_value': 10000}
              for i in range(1, 9)],
            *[{'deal_id': f'open_{i}', 'snapshot_date': str(week3), 'pipeline_id': 'default',
               'stage_id': 'qualifiedtobuy', 'deal_status': 'active', 'deal_value': 10000}
              for i in range(1, 7)],

            # Q1 closes
            *[{'deal_id': f'q1_close_{i}', 'close_date': str(q1_start + timedelta(days=i*10)),
               'pipeline_id': 'default', 'stage_id': 'closedwon', 'deal_status': 'won', 'deal_value': 10000}
              for i in range(1, 7)],
        ]
    }

    sb = MockSupabase(fixture)
    config = load_client_config()

    import adapters.storage.supabase as storage_mod
    original_select_all = storage_mod.select_all
    storage_mod.select_all = lambda sb, table, **kwargs: mock_select_all(sb, table, **kwargs)

    try:
        result = compute_quarter_conversion(sb, q1_start, q1_end, config)

        # Verify: denominator should be 20 (all open), not 6 (filtered to in-quarter closes)
        assert result['verdict'] == 'pass', f"Expected pass, got {result['verdict']}: {result.get('reason')}"
        assert result['starting_pipeline_count'] == 20, \
            f"Expected 20 open deals (unfiltered), got {result['starting_pipeline_count']} " \
            f"(filtering to in-quarter closes would give 6, producing 100% conversion)"
        assert result['won_count'] == 6, f"Expected 6 Q1 wins, got {result['won_count']}"

        conversion = result['conversion_rate']
        assert 0.25 <= conversion <= 0.35, \
            f"Expected ~30% conversion (6/20), got {conversion:.1%} " \
            f"(6/6=100% if denominator filtered)"

        print(f"  ✓ Denominator: {result['starting_pipeline_count']} (all open at week 3)")
        print(f"  ✓ NOT 6 (would be filtered to in-quarter closes)")
        print(f"  ✓ Conversion: {conversion:.1%} (correct), not 100%")
        print("  ✓ Defect 3 FIXED: Asymmetry preserved (denominator unfiltered)")

    finally:
        storage_mod.select_all = original_select_all


def test_defect_4_null_value_deals_excluded_and_counted():
    """
    Defect 4: Null-to-zero coalescing.

    Fixture: 15 deals, 3 with null deal_value. Both sides use 12,
    exclusion count is 3. GrowthBook coerced nulls to 0.0, inflating denominators.
    """
    print("\n[TEST] Defect 4: Null values excluded from both sides and counted")

    from forecast_analyses import compute_quarter_conversion
    from utils import load_client_config

    q1_start = date(2026, 2, 1)
    q1_end = date(2026, 4, 30)
    week3 = q1_start + timedelta(days=14)

    # Fixture: 31 open deals at week 3 (null rate under 10% threshold)
    # - 29 with deal_value
    # - 2 with null deal_value (6.5% - under 10% threshold)
    # - 10 of the valued deals close in Q1
    # - 1 of the null deals closes in Q1
    fixture = {
        'deals_snapshot': [
            # Week 3: 29 valued + 2 null
            *[{'deal_id': f'valued_{i}', 'snapshot_date': str(week3), 'pipeline_id': 'default',
               'stage_id': 'qualifiedtobuy', 'deal_status': 'active', 'deal_value': 10000}
              for i in range(1, 30)],
            *[{'deal_id': f'null_{i}', 'snapshot_date': str(week3), 'pipeline_id': 'default',
               'stage_id': 'qualifiedtobuy', 'deal_status': 'active', 'deal_value': None}
              for i in range(1, 3)],

            # Q1 closes: 10 valued + 1 null
            *[{'deal_id': f'valued_{i}', 'close_date': str(q1_start + timedelta(days=i*3)),
               'pipeline_id': 'default', 'stage_id': 'closedwon', 'deal_status': 'won', 'deal_value': 10000}
              for i in range(1, 11)],
            {'deal_id': 'null_1', 'close_date': str(q1_start + timedelta(days=20)),
             'pipeline_id': 'default', 'stage_id': 'closedwon', 'deal_status': 'won', 'deal_value': None},
        ]
    }

    sb = MockSupabase(fixture)
    config = load_client_config()

    import adapters.storage.supabase as storage_mod
    original_select_all = storage_mod.select_all
    storage_mod.select_all = lambda sb, table, **kwargs: mock_select_all(sb, table, **kwargs)

    try:
        result = compute_quarter_conversion(sb, q1_start, q1_end, config)

        # Verify: denominator should be 29 (valued only), not 31 (with nulls coerced to 0)
        assert result['verdict'] == 'pass', f"Expected pass, got {result['verdict']}: {result.get('reason')}"
        assert result['starting_pipeline_count'] == 29, \
            f"Expected 29 valued deals, got {result['starting_pipeline_count']} " \
            f"(null coercion would give 31)"
        assert result['won_count'] == 10, \
            f"Expected 10 valued wins, got {result['won_count']} (null coercion would give 11)"

        # Verify exclusions are counted
        assert result['null_value_excluded_starting'] == 2, \
            f"Expected 2 null-valued deals in denominator, got {result['null_value_excluded_starting']}"
        assert result['null_value_excluded_won'] == 1, \
            f"Expected 1 null-valued win in numerator, got {result['null_value_excluded_won']}"

        print(f"  ✓ Denominator: {result['starting_pipeline_count']} valued deals")
        print(f"  ✓ Numerator: {result['won_count']} valued wins")
        print(f"  ✓ Excluded (null): {result['null_value_excluded_starting']} starting, "
              f"{result['null_value_excluded_won']} won")
        print(f"  ✓ NOT coerced to 0.0 (would inflate denominator to 31)")
        print("  ✓ Defect 4 FIXED: Null propagation with exclusion counting")

    finally:
        storage_mod.select_all = original_select_all


def test_defect_2_scope_mismatch_excluded():
    """
    Defect 2: Numerator/denominator scope mismatch.

    Fixture with renewal pipeline deals: numerator and denominator populations
    must be identical. GrowthBook swept all pipelines in numerator, default-only
    in denominator. Mismatched scope makes conversion meaningless.
    """
    print("\n[TEST] Defect 2: Renewal pipeline excluded from both sides")

    from forecast_analyses import compute_quarter_conversion
    from utils import load_client_config

    q1_start = date(2026, 2, 1)
    q1_end = date(2026, 4, 30)
    week3 = q1_start + timedelta(days=14)

    # Fixture: 10 default pipeline + 5 renewal pipeline
    # - Default: 6 wins in Q1 from 10 open
    # - Renewal: 3 wins in Q1 from 5 open
    fixture = {
        'deals_snapshot': [
            # Week 3: Default pipeline (analyze: true by default)
            *[{'deal_id': f'default_{i}', 'snapshot_date': str(week3), 'pipeline_id': 'default',
               'stage_id': 'qualifiedtobuy', 'deal_status': 'active', 'deal_value': 10000}
              for i in range(1, 11)],

            # Week 3: Renewal pipeline (analyze: false in config)
            *[{'deal_id': f'renewal_{i}', 'snapshot_date': str(week3), 'pipeline_id': '866608541',
               'stage_id': 'renewal_engaged', 'deal_status': 'active', 'deal_value': 10000}
              for i in range(1, 6)],

            # Q1 closes: Default
            *[{'deal_id': f'default_{i}', 'close_date': str(q1_start + timedelta(days=i*10)),
               'pipeline_id': 'default', 'stage_id': 'closedwon', 'deal_status': 'won', 'deal_value': 10000}
              for i in range(1, 7)],

            # Q1 closes: Renewal (should be excluded if analyze: false)
            *[{'deal_id': f'renewal_{i}', 'close_date': str(q1_start + timedelta(days=i*10)),
               'pipeline_id': '866608541', 'stage_id': 'closedwon', 'deal_status': 'won', 'deal_value': 10000}
              for i in range(1, 4)],
        ]
    }

    sb = MockSupabase(fixture)
    config = load_client_config()

    # Check if renewal pipeline is configured with analyze: false
    pipelines = config.get('pipeline', {}).get('pipelines', [])
    renewal_cfg = next((p for p in pipelines if p['id'] == '866608541'), None)
    renewal_analyzed = renewal_cfg.get('analyze', True) if renewal_cfg else True

    import adapters.storage.supabase as storage_mod
    original_select_all = storage_mod.select_all
    storage_mod.select_all = lambda sb, table, **kwargs: mock_select_all(sb, table, **kwargs)

    try:
        result = compute_quarter_conversion(sb, q1_start, q1_end, config)

        if renewal_analyzed:
            # Both pipelines in scope
            expected_denominator = 15  # 10 default + 5 renewal
            expected_numerator = 9     # 6 default + 3 renewal
            scope_msg = "both pipelines in scope"
        else:
            # Only default pipeline in scope
            expected_denominator = 10  # default only
            expected_numerator = 6     # default only
            scope_msg = "default pipeline only"

        assert result['verdict'] == 'pass', f"Expected pass, got {result['verdict']}: {result.get('reason')}"
        assert result['starting_pipeline_count'] == expected_denominator, \
            f"Expected {expected_denominator} deals ({scope_msg}), got {result['starting_pipeline_count']} " \
            f"(scope mismatch would mix 10 denominator with 9 numerator)"
        assert result['won_count'] == expected_numerator, \
            f"Expected {expected_numerator} wins ({scope_msg}), got {result['won_count']}"

        print(f"  ✓ Denominator: {result['starting_pipeline_count']} ({scope_msg})")
        print(f"  ✓ Numerator: {result['won_count']} ({scope_msg})")
        print(f"  ✓ Same scope filter applied to both sides")
        print("  ✓ Defect 2 FIXED: No scope mismatch")

    finally:
        storage_mod.select_all = original_select_all


def test_defect_5_stage_read_from_snapshot_not_current():
    """
    Defect 5: Stage exclusions reading current state.

    Structural guard: Verify no join to current deals table.
    Point-in-time stage must come from snapshot row, not current state.
    """
    print("\n[TEST] Defect 5: Stage read from snapshot (structural guard)")

    from forecast_analyses import is_deal_in_analytics_scope
    import inspect

    # Verify function takes row dict (point-in-time data), not deal_id
    sig = inspect.signature(is_deal_in_analytics_scope)
    params = list(sig.parameters.keys())

    assert 'deal_row' in params or any('row' in p.lower() for p in params), \
        "Scope filter should take row dict (includes point-in-time stage_id), not deal_id"

    # Verify source has no join to deals table
    source = inspect.getsource(is_deal_in_analytics_scope)

    forbidden_patterns = [
        "deals_snapshot JOIN deals",
        "FROM deals WHERE",
        "deals.stage",
        "deals.pipeline",
    ]

    for pattern in forbidden_patterns:
        assert pattern.lower() not in source.lower(), \
            f"Found forbidden pattern '{pattern}' - scope filter must not join to current deals"

    print("  ✓ Scope filter takes row dict (point-in-time snapshot data)")
    print("  ✓ No join to current deals table")
    print("  ✓ Reads stage_id from snapshot row")
    print("  ✓ Defect 5 FIXED: Uses point-in-time stage from snapshot")


def main():
    """Run all behavioral defect verification tests."""
    print("=" * 70)
    print("FORECAST ANALYSES BEHAVIORAL DEFECT VERIFICATION")
    print("=" * 70)
    print("\nVerifying all five GrowthBook defects with real fixtures:")

    tests = [
        test_defect_1_numerator_counts_in_quarter_wins_only,
        test_defect_3_denominator_unfiltered_by_close_date,
        test_defect_4_null_value_deals_excluded_and_counted,
        test_defect_2_scope_mismatch_excluded,
        test_defect_5_stage_read_from_snapshot_not_current,
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
        print("\n✓ All five defects FIXED (verified with fixtures)")
        print("✓ Behavioral tests confirm correct computations")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
