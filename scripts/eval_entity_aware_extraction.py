#!/usr/bin/env python3
"""
Eval: Entity-aware accumulated data extraction.

Tests that _extract_rows_from_accumulated:
1. Prefers entity-bearing steps for entity extraction
2. Returns last step for synthesis mode
3. Generalizes to any registered entity (not hardcoded deal_id)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_entity_aware_extraction():
    """Test entity-aware extraction from accumulated data."""
    from api.router import _extract_rows_from_accumulated, logger
    import logging
    logger.setLevel(logging.CRITICAL)  # Suppress logs during test

    # Mock Supabase client
    class MockSupabase:
        def table(self, name):
            return self

        def select(self, *args):
            return self

        def execute(self):
            # Return entity registry data
            class Result:
                data = [
                    {"id_column": "deal_id"},
                    {"id_column": "call_id"},
                    {"id_column": "company_id"}
                ]
            return Result()

    sb = MockSupabase()

    print("="*80)
    print("ENTITY-AWARE EXTRACTION EVAL")
    print("="*80)
    print()

    # Test 1: Entity-bearing step followed by aggregate
    print("[TEST 1] Entity-bearing step (step_0) followed by aggregate (step_2)")

    accumulated_data = {
        "step_0": {
            "rows": [
                {"deal_id": "123", "company_name": "Acme", "deal_value": 50000},
                {"deal_id": "456", "company_name": "TechCo", "deal_value": 75000},
                {"deal_id": "789", "company_name": "StartupX", "deal_value": 30000}
            ],
            "table": "deals"
        },
        "step_1": {
            "rows": [
                {"deal_id": "123", "company_name": "Acme", "overall_score": 85},
                {"deal_id": "456", "company_name": "TechCo", "overall_score": 72},
            ],
            "table": "analyses"
        },
        "step_2": {
            "rows": [
                {"stage": "appointmentscheduled", "count": 45},
                {"stage": "qualifiedtobuy", "count": 32},
                {"stage": "decisionmakerboughtin", "count": 18}
            ],
            "table": "aggregated"
        }
    }

    # Entity extraction mode should prefer entity-bearing steps
    result = _extract_rows_from_accumulated(accumulated_data, mode="entity_extraction", sb=sb)

    print(f"  Result has {len(result.get('rows', []))} rows")
    print(f"  From table: {result.get('table')}")

    # Should NOT return step_2 (aggregate with no entities)
    assert len(result.get('rows', [])) != 3 or "count" not in result['rows'][0], \
        "Should not return aggregate step for entity extraction"

    # Should return step_1 or step_0 (both have deal_id)
    first_row = result['rows'][0] if result.get('rows') else {}
    assert "deal_id" in first_row, \
        f"Should return entity-bearing step, got: {first_row}"

    print("  ✓ Returned entity-bearing step (has deal_id)")
    print()

    # Test 2: Synthesis mode returns last step
    print("[TEST 2] Synthesis mode returns last step (aggregate)")

    result_synth = _extract_rows_from_accumulated(accumulated_data, mode="synthesis", sb=sb)

    print(f"  Result has {len(result_synth.get('rows', []))} rows")
    print(f"  From table: {result_synth.get('table')}")

    # Should return step_2 (last step)
    assert len(result_synth.get('rows', [])) == 3, \
        f"Synthesis mode should return last step, got {len(result_synth.get('rows', []))} rows"

    first_row_synth = result_synth['rows'][0]
    assert "count" in first_row_synth, \
        f"Synthesis mode should return aggregate, got: {first_row_synth}"

    print("  ✓ Synthesis mode returned last step (aggregate)")
    print()

    # Test 3: Multiple entity-bearing steps - prefer most recent
    print("[TEST 3] Multiple entity-bearing steps - prefer most recent")

    accumulated_multi = {
        "step_0": {
            "rows": [
                {"deal_id": "123", "company_name": "Acme"},
                {"deal_id": "456", "company_name": "TechCo"}
            ],
            "table": "deals"
        },
        "step_1": {
            "rows": [
                {"call_id": "call_1", "title": "Discovery call"},
                {"call_id": "call_2", "title": "Demo"}
            ],
            "table": "calls"
        }
    }

    result_multi = _extract_rows_from_accumulated(accumulated_multi, mode="entity_extraction", sb=sb)

    print(f"  Result has {len(result_multi.get('rows', []))} rows")
    print(f"  From table: {result_multi.get('table')}")

    # Should prefer step_1 (most recent entity-bearing)
    first_row_multi = result_multi['rows'][0]
    assert "call_id" in first_row_multi, \
        f"Should prefer most recent entity-bearing step (step_1), got: {first_row_multi}"

    print("  ✓ Preferred most recent entity-bearing step (step_1 with call_id)")
    print()

    # Test 4: No entity-bearing steps - fallback to last with data
    print("[TEST 4] No entity-bearing steps - fallback to last with data")

    accumulated_no_entities = {
        "step_0": {
            "rows": [
                {"category": "pricing", "count": 12},
                {"category": "features", "count": 8}
            ],
            "table": "aggregated"
        }
    }

    result_fallback = _extract_rows_from_accumulated(
        accumulated_no_entities, mode="entity_extraction", sb=sb)

    print(f"  Result has {len(result_fallback.get('rows', []))} rows")

    # Should fallback to step_0 (only step with data)
    assert len(result_fallback.get('rows', [])) == 2, \
        "Should fallback to last step with data"

    print("  ✓ Fallback to last step when no entities found")
    print()

    # Test 5: Generalizes to any registered entity
    print("[TEST 5] Generalizes to registered entities (not hardcoded)")

    # Mock different entity registry
    class MockSupabaseWithCompany:
        def table(self, name):
            return self

        def select(self, *args):
            return self

        def execute(self):
            class Result:
                data = [
                    {"id_column": "company_id"},  # Only company_id registered
                    {"id_column": "campaign_id"}  # Hypothetical future entity
                ]
            return Result()

    sb_company = MockSupabaseWithCompany()

    accumulated_company = {
        "step_0": {
            "rows": [
                {"deal_id": "123", "company_name": "Acme"},  # Has deal_id but not registered
            ],
            "table": "deals"
        },
        "step_1": {
            "rows": [
                {"company_id": "comp_1", "name": "Acme Corp"},  # Registered entity
                {"company_id": "comp_2", "name": "TechCo"}
            ],
            "table": "companies"
        }
    }

    result_company = _extract_rows_from_accumulated(
        accumulated_company, mode="entity_extraction", sb=sb_company)

    first_row_company = result_company['rows'][0]
    assert "company_id" in first_row_company, \
        f"Should recognize company_id from registry, got: {first_row_company}"

    print("  ✓ Recognized company_id from entity_registry (not hardcoded)")
    print()

    print("="*80)
    print("Results: All tests passed!")
    print("="*80)

if __name__ == "__main__":
    test_entity_aware_extraction()
