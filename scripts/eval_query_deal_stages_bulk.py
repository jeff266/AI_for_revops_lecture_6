#!/usr/bin/env python3
"""
Eval: query_deal_stages_bulk dual-path crash fixes.

Tests that:
1. Entity-scope path with deal_ids succeeds (regression for Bug A1: "in" filter)
2. Direct intent path without deal_ids fails gracefully (regression for Bug A2: KeyError)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_query_deal_stages_bulk():
    """Test query_deal_stages_bulk fixes."""
    import asyncio
    from api.handlers import query_deal_stages_bulk
    from scripts.supabase_client import select_all

    print("="*80)
    print("QUERY_DEAL_STAGES_BULK DUAL-PATH CRASH FIXES")
    print("="*80)
    print()

    # Mock Supabase client
    class MockSupabase:
        def table(self, name):
            self.current_table = name
            return self

        def select(self, columns):
            self.current_columns = columns
            return self

        def in_(self, col, values):
            self.filter_col = col
            self.filter_values = values
            return self

        def range(self, start, end):
            return self

        def execute(self):
            # Return mock stages data
            class Result:
                data = [
                    {
                        "deal_id": "deal_1",
                        "company_name": "Company A",
                        "stage": "qualifiedtobuy",
                        "highest_stage_order_reached": 3,
                        "close_date": "2026-08-30"
                    },
                    {
                        "deal_id": "deal_2",
                        "company_name": "Company B",
                        "stage": "appointmentscheduled",
                        "highest_stage_order_reached": 2,
                        "close_date": None
                    }
                ]
            return Result()

    sb = MockSupabase()

    # Test 1: Entity-scope path with deal_ids succeeds
    print("[TEST 1] Entity-scope path with deal_ids succeeds (Bug A1 regression)")

    params_with_ids = {
        "deal_ids": ["deal_1", "deal_2"],
        "time_window": {
            "start": "2026-08-10",
            "end": "2026-08-17",
            "label": "This Week"
        }
    }

    result = asyncio.run(query_deal_stages_bulk(params_with_ids, sb))

    assert "stages" in result, "Missing 'stages' key"
    assert isinstance(result["stages"], list), "stages should be a list"
    assert len(result["stages"]) == 2, f"Expected 2 stages, got {len(result['stages'])}"
    assert result["stages"][0]["deal_id"] == "deal_1", "Wrong deal_id"
    assert result["stages"][0]["stage"] == "qualifiedtobuy", "Wrong stage"

    print(f"  ✓ Returned {len(result['stages'])} stages for 2 deal_ids")
    print(f"  ✓ Filter used 'in_' method (no AttributeError on reserved keyword 'in')")
    print()

    # Test 2: Direct intent path without deal_ids fails gracefully
    print("[TEST 2] Direct intent path without deal_ids fails gracefully (Bug A2 regression)")

    params_no_ids = {
        "time_window": {
            "start": "2026-08-10",
            "end": "2026-08-17",
            "label": "This Week"
        }
    }

    result_no_ids = asyncio.run(query_deal_stages_bulk(params_no_ids, sb))

    assert "stages" in result_no_ids, "Missing 'stages' key"
    assert result_no_ids["stages"] == [], "Should return empty list when no deal_ids"
    assert "error" in result_no_ids, "Should include 'error' message when no deal_ids"
    assert "No deal IDs provided" in result_no_ids["error"], "Error message should be clear"

    print(f"  ✓ No KeyError crash when deal_ids missing")
    print(f"  ✓ Returns empty list with clear error message:")
    print(f"     '{result_no_ids['error']}'")
    print()

    # Test 3: select_all handles both "in" and "in_" filter operators
    print("[TEST 3] select_all handles both 'in' and 'in_' filter operators")

    # Test with "in_" (recommended)
    rows_in_ = select_all(sb, "deals",
        columns="deal_id,stage",
        filters=[("in_", "deal_id", ["deal_1", "deal_2"])])

    assert len(rows_in_) == 2, f"Expected 2 rows with 'in_', got {len(rows_in_)}"
    print(f"  ✓ 'in_' filter works: {len(rows_in_)} rows")

    # Test with "in" (legacy, should still work via Bug A1 fix)
    rows_in = select_all(sb, "deals",
        columns="deal_id,stage",
        filters=[("in", "deal_id", ["deal_1", "deal_2"])])

    assert len(rows_in) == 2, f"Expected 2 rows with 'in', got {len(rows_in)}"
    print(f"  ✓ 'in' filter works (via fix that maps to 'in_'): {len(rows_in)} rows")
    print()

    print("="*80)
    print("Results: All tests passed!")
    print("="*80)

if __name__ == "__main__":
    test_query_deal_stages_bulk()
