#!/usr/bin/env python3
"""
Behavioral tests for compute_waterfall.py - verify defects with real fixtures.

Two critical fixes:
1. Null-propagation: unknown values excluded from dollar sums (not 0-filled)
2. Point-in-time qualification: uses qualified_date (not current stage high-water mark)
"""

import sys
from pathlib import Path
from datetime import date, timedelta

# Add scripts to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'scripts' / 'analytics'))


def get_test_config():
    """Minimal config for tests."""
    return {
        'pipeline': {
            'qualified_stage_order': 3,
            'pipelines': [
                {
                    'id': 'default',
                    'name': 'Sales Pipeline',
                    'is_primary': True,
                    'qualified_stage_order': 3,
                    'stages': [
                        {'id': 'discovery', 'name': 'Discovery', 'order': 2},
                        {'id': 'scoping', 'name': 'Scoping', 'order': 3},
                        {'id': 'evaluation', 'name': 'Evaluation', 'order': 4},
                        {'id': 'closedwon', 'name': 'Closed Won', 'order': 6, 'is_won': True},
                        {'id': 'closedlost', 'name': 'Closed Lost', 'order': 6, 'is_lost': True},
                    ]
                }
            ]
        },
        'fiscal': {'fy_start_month': 2},  # Q1 starts Feb 1
        'forecast_analysis': {'max_null_value_pct': 5.0},
    }


class MockSupabase:
    """Mock Supabase client for waterfall tests."""

    def __init__(self, fixture_data):
        self.fixture_data = fixture_data
        self.upserted = []

    def table(self, name):
        self.current_table = name
        return self

    def select(self, cols):
        self.current_cols = cols
        return self

    def eq(self, col, val):
        self.current_filter = ('eq', col, val)
        return self

    def lt(self, col, val):
        self.current_filter = ('lt', col, val)
        return self

    def order(self, col, desc=False):
        return self

    def limit(self, n):
        return self

    def execute(self):
        data = self.fixture_data.get(self.current_table, [])
        if hasattr(self, 'current_filter'):
            op, col, val = self.current_filter
            if op == 'eq':
                data = [r for r in data if str(r.get(col)) == str(val)]
        return type('obj', (object,), {'data': data})

    def upsert(self, row, on_conflict=None):
        self.upserted.append((self.current_table, row))
        return self


def mock_select_all(sb, table, columns=None, filters=None):
    """Mock select_all that applies filters."""
    data = sb.fixture_data.get(table, [])

    if filters:
        for filter_op, filter_col, filter_val in filters:
            if filter_op == 'eq':
                data = [r for r in data if str(r.get(filter_col)) == str(filter_val)]

    return data


def test_unknown_value_excluded_from_dollar_sum_not_zero_filled():
    """
    Defect 4 (null-propagation): 10 deals, 3 with null deal_value.

    Dollar sums must use 7 deals only (exclude the 3 unknowns).
    The 3 must be COUNTED in null_value_excluded_count, NEVER coerced to 0.0.

    Before fix: null -> 0.0 coalescing re-fabricated the number Phase 2b removed.
    After fix: null-propagate — exclude from sum, count the exclusion.
    """
    print("\n[TEST] Defect 4: Unknown value excluded from dollar sum (not 0-filled)")

    from compute_waterfall import compute_waterfall_for_dates

    week1 = date(2026, 3, 1)
    week2 = date(2026, 3, 8)

    # Fixture: 10 deals in both snapshots
    # - 7 with deal_value = 10000 each
    # - 3 with deal_value = None (unknown)
    # All qualified as of week 1 (qualified_date before week1)
    fixture = {
        'deals': [
            # All 10 deals have qualified_date before week1
            *[{'deal_id': f'valued_{i}', 'qualified_date': '2026-02-15'}
              for i in range(1, 8)],
            *[{'deal_id': f'unknown_{i}', 'qualified_date': '2026-02-15'}
              for i in range(1, 4)],
        ],
        'deals_snapshot': [
            # Week 1 snapshot: 10 active deals, 7 valued + 3 unknown
            *[{'deal_id': f'valued_{i}', 'snapshot_date': str(week1), 'pipeline_id': 'default',
               'stage_id': 'scoping', 'stage_order': 3, 'deal_status': 'active',
               'deal_value': 10000.0, 'company_name': f'Company {i}'}
              for i in range(1, 8)],
            *[{'deal_id': f'unknown_{i}', 'snapshot_date': str(week1), 'pipeline_id': 'default',
               'stage_id': 'scoping', 'stage_order': 3, 'deal_status': 'active',
               'deal_value': None, 'company_name': f'Company Unknown {i}'}
              for i in range(1, 4)],

            # Week 2 snapshot: same 10 deals still active
            *[{'deal_id': f'valued_{i}', 'snapshot_date': str(week2), 'pipeline_id': 'default',
               'stage_id': 'scoping', 'stage_order': 3, 'deal_status': 'active',
               'deal_value': 10000.0, 'company_name': f'Company {i}'}
              for i in range(1, 8)],
            *[{'deal_id': f'unknown_{i}', 'snapshot_date': str(week2), 'pipeline_id': 'default',
               'stage_id': 'scoping', 'stage_order': 3, 'deal_status': 'active',
               'deal_value': None, 'company_name': f'Company Unknown {i}'}
              for i in range(1, 4)],
        ]
    }

    sb = MockSupabase(fixture)
    config = get_test_config()

    # Monkey-patch select_all and utils
    import adapters.storage.supabase as storage_mod
    original_select_all = storage_mod.select_all
    storage_mod.select_all = lambda sb, table, **kwargs: mock_select_all(sb, table, **kwargs)

    # Build qual_map from fixture
    qual_map = {row['deal_id']: {'qualified_date': row['qualified_date']}
                for row in fixture['deals']}

    try:
        compute_waterfall_for_dates(
            sb, config, qual_map, threshold=3,
            prev_date=str(week1), new_date=str(week2),
            computed_source='test'
        )

        # Verify upserted row
        assert len(sb.upserted) == 1, f"Expected 1 upsert, got {len(sb.upserted)}"
        table, row = sb.upserted[0]
        assert table == 'waterfall_weekly'

        # Beginning value = 7 * 10000 = 70000 (excludes 3 unknowns, never 0-filled)
        # Ending value = same (no changes between weeks)
        assert row['beginning_value'] == 70000.0, \
            f"Expected 70000 (7 deals * 10000), got {row['beginning_value']} " \
            f"(zero-filling would give 100000)"
        assert row['ending_value'] == 70000.0, \
            f"Expected 70000, got {row['ending_value']}"

        # Details should have null_value_excluded_summary
        import json
        details = json.loads(row['details'])
        summary = details[0] if details and details[0].get('change_type') == 'null_value_excluded_summary' else None
        assert summary is not None, "Expected null_value_excluded_summary in details"
        assert summary['beginning_null_value_excluded'] == 3, \
            f"Expected 3 null deals excluded from beginning, got {summary['beginning_null_value_excluded']}"
        assert summary['ending_null_value_excluded'] == 3, \
            f"Expected 3 null deals excluded from ending, got {summary['ending_null_value_excluded']}"

        print(f"  ✓ Beginning value: $70,000 (7 valued deals)")
        print(f"  ✓ NOT $100,000 (would be if 3 unknowns zero-filled to 0)")
        print(f"  ✓ 3 unknown-value deals counted in exclusion summary")
        print("  ✓ Defect 4 FIXED: Null-propagation excludes unknowns from dollar sums")

    finally:
        storage_mod.select_all = original_select_all


def test_qualification_uses_qualified_date_not_current_stage():
    """
    Defect 5 (point-in-time qualification): Deal qualified in week 5 must NOT
    appear in week 2's qualified pipeline.

    Before fix: Used highest_stage_order_reached (current-state high-water mark) —
    leaked up to 137 not-yet-qualified deals into early weeks' qualified pipeline.

    After fix: Uses qualified_date (immutable event timestamp) — a deal is only
    in the qualified pipeline for weeks AFTER it crossed the threshold.

    Fixture: 5 deals total
    - 3 qualified on 2026-02-10 (before week 1) -> in both week 1 and week 2
    - 2 qualified on 2026-03-18 (between week 2 and week 3) -> NOT in week 2, YES in week 3
    """
    print("\n[TEST] Defect 5: Qualification uses qualified_date (not current stage)")

    from compute_waterfall import compute_waterfall_for_dates

    week1 = date(2026, 3, 1)   # Mar 1
    week2 = date(2026, 3, 8)   # Mar 8
    week3 = date(2026, 3, 15)  # Mar 15

    # Fixture: 5 deals
    # - 3 early qualifiers (qualified_date = 2026-02-10, before week1)
    # - 2 late qualifiers (qualified_date = 2026-03-18, after week2 but before week3)
    fixture = {
        'deals': [
            *[{'deal_id': f'early_{i}', 'qualified_date': '2026-02-10'}
              for i in range(1, 4)],
            *[{'deal_id': f'late_{i}', 'qualified_date': '2026-03-18'}
              for i in range(1, 3)],
        ],
        'deals_snapshot': [
            # Week 1: Only 3 early qualifiers (late ones haven't qualified yet)
            *[{'deal_id': f'early_{i}', 'snapshot_date': str(week1), 'pipeline_id': 'default',
               'stage_id': 'scoping', 'stage_order': 3, 'deal_status': 'active',
               'deal_value': 10000.0, 'company_name': f'Early {i}'}
              for i in range(1, 4)],

            # Week 2: All 5 exist, but late ones STILL not qualified yet
            *[{'deal_id': f'early_{i}', 'snapshot_date': str(week2), 'pipeline_id': 'default',
               'stage_id': 'scoping', 'stage_order': 3, 'deal_status': 'active',
               'deal_value': 10000.0, 'company_name': f'Early {i}'}
              for i in range(1, 4)],
            # Late deals exist but are in Discovery (order 2, below qualified threshold 3)
            *[{'deal_id': f'late_{i}', 'snapshot_date': str(week2), 'pipeline_id': 'default',
               'stage_id': 'discovery', 'stage_order': 2, 'deal_status': 'active',
               'deal_value': 10000.0, 'company_name': f'Late {i}'}
              for i in range(1, 3)],

            # Week 3: All 5 qualified now (late ones crossed threshold on 2026-03-18)
            *[{'deal_id': f'early_{i}', 'snapshot_date': str(week3), 'pipeline_id': 'default',
               'stage_id': 'scoping', 'stage_order': 3, 'deal_status': 'active',
               'deal_value': 10000.0, 'company_name': f'Early {i}'}
              for i in range(1, 4)],
            *[{'deal_id': f'late_{i}', 'snapshot_date': str(week3), 'pipeline_id': 'default',
               'stage_id': 'scoping', 'stage_order': 3, 'deal_status': 'active',
               'deal_value': 10000.0, 'company_name': f'Late {i}'}
              for i in range(1, 3)],
        ]
    }

    sb = MockSupabase(fixture)
    config = get_test_config()

    # Monkey-patch
    import adapters.storage.supabase as storage_mod
    original_select_all = storage_mod.select_all
    storage_mod.select_all = lambda sb, table, **kwargs: mock_select_all(sb, table, **kwargs)

    qual_map = {row['deal_id']: {'qualified_date': row['qualified_date']}
                for row in fixture['deals']}

    try:
        # Compute waterfall from week1 to week2
        sb.upserted = []
        compute_waterfall_for_dates(
            sb, config, qual_map, threshold=3,
            prev_date=str(week1), new_date=str(week2),
            computed_source='test'
        )

        table, row_w2 = sb.upserted[0]

        # Week 2: Only 3 early qualifiers in the pipeline
        # (late deals exist but haven't crossed qualified_date yet)
        assert row_w2['beginning_value'] == 30000.0, \
            f"Expected 30000 (3 early deals), got {row_w2['beginning_value']} " \
            f"(reading current stage would leak 5)"
        assert row_w2['ending_value'] == 30000.0, \
            f"Expected 30000 (3 early deals), got {row_w2['ending_value']}"

        # No newly_qualified in week 2 (late deals qualify on 3/18, after this week)
        assert row_w2['deals_qualified_count'] == 0, \
            f"Expected 0 newly qualified in week 2, got {row_w2['deals_qualified_count']}"

        print(f"  ✓ Week 2 beginning: $30,000 (3 early qualifiers)")
        print(f"  ✓ NOT $50,000 (would include 2 late deals if using current stage)")
        print(f"  ✓ 0 newly qualified (late deals qualify next week)")

        # Compute waterfall from week2 to week3
        sb.upserted = []
        compute_waterfall_for_dates(
            sb, config, qual_map, threshold=3,
            prev_date=str(week2), new_date=str(week3),
            computed_source='test'
        )

        table, row_w3 = sb.upserted[0]

        # Week 3: Now all 5 qualified (late deals crossed threshold between week2 and week3)
        assert row_w3['beginning_value'] == 30000.0, \
            f"Expected 30000 (week2 ending), got {row_w3['beginning_value']}"
        assert row_w3['ending_value'] == 50000.0, \
            f"Expected 50000 (3 early + 2 late), got {row_w3['ending_value']}"

        # 2 newly qualified this week (late deals)
        assert row_w3['deals_qualified_count'] == 2, \
            f"Expected 2 newly qualified in week 3, got {row_w3['deals_qualified_count']}"
        assert row_w3['newly_qualified_value'] == 20000.0, \
            f"Expected 20000 (2 late deals), got {row_w3['newly_qualified_value']}"

        print(f"  ✓ Week 3 ending: $50,000 (3 early + 2 late)")
        print(f"  ✓ 2 newly qualified (late deals crossed threshold)")
        print("  ✓ Defect 5 FIXED: Point-in-time via qualified_date, not current stage")

    finally:
        storage_mod.select_all = original_select_all


def main():
    """Run all waterfall tests."""
    print("=" * 70)
    print("WATERFALL BEHAVIORAL TESTS")
    print("=" * 70)

    passed = 0
    failed = 0

    try:
        test_unknown_value_excluded_from_dollar_sum_not_zero_filled()
        passed += 1
    except AssertionError as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    try:
        test_qualification_uses_qualified_date_not_current_stage()
        passed += 1
    except AssertionError as e:
        print(f"  ❌ FAILED: {e}")
        failed += 1

    print()
    print("=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
