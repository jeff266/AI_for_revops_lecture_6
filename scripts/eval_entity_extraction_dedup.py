#!/usr/bin/env python3
"""
Eval: Entity extraction deduplication ordering.

Tests that extract_entity_context:
1. Deduplicates entity IDs BEFORE capping at 20
2. Handles result sets with duplicate deal_ids correctly
3. Returns distinct entities only

This prevents the bug where rows[:20] happened before dedup,
causing duplicate entities to be extracted when the same deal_id
appeared multiple times in the result set.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_entity_extraction_dedup():
    """Test that entity extraction deduplicates before capping."""
    from api.db import extract_entity_context
    import logging
    logging.getLogger("api.db").setLevel(logging.CRITICAL)  # Suppress logs during test

    # Mock Supabase client with entity registry
    class MockSupabase:
        def table(self, name):
            return self

        def select(self, *args):
            return self

        def execute(self):
            class Result:
                data = [
                    {"id_column": "deal_id", "entity_type": "deal",
                     "entity_label_column": "company_name", "supabase_table": "deals"}
                ]
            return Result()

    sb = MockSupabase()

    print("="*80)
    print("ENTITY EXTRACTION DEDUPLICATION EVAL")
    print("="*80)
    print()

    # Test 1: Duplicate deal_ids in result set
    print("[TEST 1] Duplicate deal_ids should deduplicate before cap")

    # Simulate query_deals_at_risk with duplicate analyses
    # (same deal analyzed multiple times)
    tool_results = {
        "deals_at_risk": [
            {"deal_id": "123", "company_name": "Acme", "overall_score": 30},
            {"deal_id": "456", "company_name": "TechCo", "overall_score": 25},
            {"deal_id": "123", "company_name": "Acme", "overall_score": 32},  # Duplicate
            {"deal_id": "789", "company_name": "StartupX", "overall_score": 35},
            {"deal_id": "456", "company_name": "TechCo", "overall_score": 28},  # Duplicate
        ]
    }

    result = extract_entity_context(tool_results, sb=sb)

    print(f"  Input: 5 rows (3 unique deal_ids, 2 duplicates)")
    print(f"  Extracted deal_ids: {result.get('deal_ids', [])}")
    print(f"  Extracted company_names: {result.get('company_names', [])}")

    # Should extract 3 unique deal_ids, not 5
    assert len(result.get('deal_ids', [])) == 3, \
        f"Expected 3 unique deal_ids, got {len(result.get('deal_ids', []))}"

    # Check for duplicates
    deal_ids = result.get('deal_ids', [])
    assert len(deal_ids) == len(set(deal_ids)), \
        f"Duplicate deal_ids found: {deal_ids}"

    print(f"  ✓ Extracted 3 distinct deal_ids (duplicates removed)")
    print()

    # Test 2: Cap at 20 AFTER dedup, not before
    print("[TEST 2] Cap should apply AFTER dedup, not before")

    # Create 25 rows with 15 unique deal_ids (some duplicates)
    rows = []
    for i in range(15):
        rows.append({"deal_id": f"deal_{i}", "company_name": f"Company {i}"})
        if i < 10:  # Add duplicates for first 10
            rows.append({"deal_id": f"deal_{i}", "company_name": f"Company {i}"})

    tool_results_capped = {"rows": rows}

    print(f"  Input: {len(rows)} rows, 15 unique deal_ids (with duplicates)")

    result_capped = extract_entity_context(tool_results_capped, sb=sb)

    print(f"  Extracted: {len(result_capped.get('deal_ids', []))} deal_ids")

    # Should extract 15 unique deal_ids (all unique ones)
    # NOT 20 (which would happen if we did rows[:20] before dedup)
    assert len(result_capped.get('deal_ids', [])) == 15, \
        f"Expected 15 unique deal_ids, got {len(result_capped.get('deal_ids', []))}"

    # Verify no duplicates
    deal_ids_capped = result_capped.get('deal_ids', [])
    assert len(deal_ids_capped) == len(set(deal_ids_capped)), \
        f"Duplicate deal_ids found: {deal_ids_capped}"

    print(f"  ✓ Extracted all 15 unique deal_ids (dedup before cap)")
    print()

    # Test 3: Cap at 20 when there are >20 unique entities
    print("[TEST 3] Cap at 20 when >20 unique entities exist")

    # Create 30 rows with 25 unique deal_ids
    rows_large = []
    for i in range(25):
        rows_large.append({"deal_id": f"deal_{i}", "company_name": f"Company {i}"})
        if i < 5:  # Add some duplicates
            rows_large.append({"deal_id": f"deal_{i}", "company_name": f"Company {i}"})

    tool_results_large = {"rows": rows_large}

    print(f"  Input: {len(rows_large)} rows, 25 unique deal_ids")

    result_large = extract_entity_context(tool_results_large, sb=sb)

    print(f"  Extracted: {len(result_large.get('deal_ids', []))} deal_ids")

    # Should extract exactly 20 (capped after dedup)
    assert len(result_large.get('deal_ids', [])) == 20, \
        f"Expected 20 deal_ids (capped), got {len(result_large.get('deal_ids', []))}"

    # Verify no duplicates
    deal_ids_large = result_large.get('deal_ids', [])
    assert len(deal_ids_large) == len(set(deal_ids_large)), \
        f"Duplicate deal_ids found: {deal_ids_large}"

    print(f"  ✓ Capped at 20 after dedup (25 unique → 20)")
    print()

    # Test 4: Order preservation after dedup
    print("[TEST 4] Dedup preserves first occurrence order")

    tool_results_order = {
        "rows": [
            {"deal_id": "A", "company_name": "Alpha"},
            {"deal_id": "B", "company_name": "Beta"},
            {"deal_id": "A", "company_name": "Alpha"},  # Duplicate
            {"deal_id": "C", "company_name": "Gamma"},
            {"deal_id": "B", "company_name": "Beta"},   # Duplicate
        ]
    }

    result_order = extract_entity_context(tool_results_order, sb=sb)

    print(f"  Input order: A, B, A, C, B")
    print(f"  Output order: {result_order.get('deal_ids', [])}")

    # Should preserve order: A, B, C (first occurrences)
    expected_order = ["A", "B", "C"]
    assert result_order.get('deal_ids', []) == expected_order, \
        f"Expected order {expected_order}, got {result_order.get('deal_ids', [])}"

    print(f"  ✓ Preserved first occurrence order: {expected_order}")
    print()

    print("="*80)
    print("Results: All tests passed!")
    print("="*80)

if __name__ == "__main__":
    test_entity_extraction_dedup()
