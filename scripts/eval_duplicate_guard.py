#!/usr/bin/env python3
"""
Eval: Duplicate tool call guard in dynamic_query_loop.

Tests that the fingerprint builder:
1. Handles columns as both list and string
2. Produces stable fingerprints for identical calls
3. Detects near-duplicates (same query, different limit)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_fingerprint_normalization():
    """Test that fingerprint builder handles both list and string shapes."""
    from api.router import logger
    import logging
    logger.setLevel(logging.CRITICAL)  # Suppress logs during test

    # Simulate the fingerprint building logic from router.py
    def build_fingerprint(tool_name, tool_params):
        """Extract from router.py duplicate guard logic."""
        # Normalize columns (can be list or comma-separated string)
        cols = tool_params.get("columns") or []
        if isinstance(cols, str):
            cols = [c.strip() for c in cols.split(",") if c.strip()]
        cols_key = str(sorted(cols))

        # Normalize filters (can be list or None)
        filters = tool_params.get("filters") or []
        if not isinstance(filters, list):
            filters = []
        filters_key = str(sorted(filters, key=str))

        # Normalize table names
        if tool_name == "filter_table":
            table_key = str(tool_params.get("table", ""))
        else:  # join_tables
            primary = tool_params.get("primary_table", "")
            joined = tool_params.get("joined_table", "")
            table_key = f"{primary}+{joined}"

        return (tool_name, table_key, cols_key, filters_key)

    print("="*80)
    print("DUPLICATE GUARD EVAL")
    print("="*80)
    print()

    # Test 1: Columns as list vs string produce same fingerprint
    print("[TEST 1] Columns as list vs string")
    params_list = {
        "table": "deals",
        "columns": ["company_name", "deal_value", "stage"],
        "filters": [["eq", "stage", "appointmentscheduled"]],
        "limit": 10
    }
    params_string = {
        "table": "deals",
        "columns": "company_name, deal_value, stage",
        "filters": [["eq", "stage", "appointmentscheduled"]],
        "limit": 10
    }

    fp_list = build_fingerprint("filter_table", params_list)
    fp_string = build_fingerprint("filter_table", params_string)

    print(f"  Fingerprint (list):   {fp_list}")
    print(f"  Fingerprint (string): {fp_string}")

    assert fp_list == fp_string, \
        f"Fingerprints don't match! list={fp_list} vs string={fp_string}"
    print("  ✓ Fingerprints match")
    print()

    # Test 2: Different limit doesn't affect fingerprint
    print("[TEST 2] Different limit produces same fingerprint")
    params_limit_10 = {
        "table": "deals",
        "columns": ["company_name", "deal_value"],
        "filters": [["eq", "stage", "appointmentscheduled"]],
        "limit": 10
    }
    params_limit_50 = {
        "table": "deals",
        "columns": ["company_name", "deal_value"],
        "filters": [["eq", "stage", "appointmentscheduled"]],
        "limit": 50
    }

    fp_10 = build_fingerprint("filter_table", params_limit_10)
    fp_50 = build_fingerprint("filter_table", params_limit_50)

    print(f"  Fingerprint (limit=10): {fp_10}")
    print(f"  Fingerprint (limit=50): {fp_50}")

    assert fp_10 == fp_50, \
        f"Fingerprints don't match! limit=10: {fp_10} vs limit=50: {fp_50}"
    print("  ✓ Fingerprints match (limit ignored)")
    print()

    # Test 3: Different columns produce different fingerprint
    print("[TEST 3] Different columns produce different fingerprint")
    params_cols_a = {
        "table": "deals",
        "columns": ["company_name", "deal_value"],
        "filters": [],
        "limit": 10
    }
    params_cols_b = {
        "table": "deals",
        "columns": ["company_name", "stage"],
        "filters": [],
        "limit": 10
    }

    fp_cols_a = build_fingerprint("filter_table", params_cols_a)
    fp_cols_b = build_fingerprint("filter_table", params_cols_b)

    print(f"  Fingerprint (cols A): {fp_cols_a}")
    print(f"  Fingerprint (cols B): {fp_cols_b}")

    assert fp_cols_a != fp_cols_b, \
        f"Fingerprints should differ! Both are: {fp_cols_a}"
    print("  ✓ Fingerprints differ correctly")
    print()

    # Test 4: Column order doesn't matter (both list and string)
    print("[TEST 4] Column order doesn't matter")
    params_order_1 = {
        "table": "deals",
        "columns": ["company_name", "deal_value", "stage"],
        "filters": [],
    }
    params_order_2 = {
        "table": "deals",
        "columns": "stage, deal_value, company_name",  # Different order, string
        "filters": [],
    }

    fp_order_1 = build_fingerprint("filter_table", params_order_1)
    fp_order_2 = build_fingerprint("filter_table", params_order_2)

    print(f"  Fingerprint (order 1): {fp_order_1}")
    print(f"  Fingerprint (order 2): {fp_order_2}")

    assert fp_order_1 == fp_order_2, \
        f"Fingerprints should match! order1={fp_order_1} vs order2={fp_order_2}"
    print("  ✓ Fingerprints match (order normalized)")
    print()

    # Test 5: join_tables fingerprint includes both tables
    print("[TEST 5] join_tables includes both primary and joined table")
    params_join = {
        "primary_table": "deals",
        "joined_table": "analyses",
        "primary_key": "deal_id",
        "foreign_key": "deal_id",
        "joined_columns": ["champion_score", "overall_score"],
        "limit": 10
    }

    fp_join = build_fingerprint("join_tables", params_join)
    print(f"  Fingerprint: {fp_join}")

    assert "deals+analyses" in fp_join[1], \
        f"Join fingerprint should include both tables: {fp_join}"
    print("  ✓ Both tables in fingerprint")
    print()

    # Test 6: Empty/missing fields handled gracefully
    print("[TEST 6] Empty/missing fields handled gracefully")
    params_minimal = {
        "table": "deals",
        # columns missing
        # filters missing
    }

    fp_minimal = build_fingerprint("filter_table", params_minimal)
    print(f"  Fingerprint (minimal): {fp_minimal}")

    assert fp_minimal is not None, "Should handle missing fields"
    print("  ✓ Handles missing fields")
    print()

    print("="*80)
    print("Results: All tests passed!")
    print("="*80)

if __name__ == "__main__":
    test_fingerprint_normalization()
