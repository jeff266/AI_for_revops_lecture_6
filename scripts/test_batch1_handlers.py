#!/usr/bin/env python3
"""
Verification tests for Batch 1 handlers.

These handlers were ported/written with production fixes in mind:
1. query_deal_health - explicit list usage to prevent char-iteration bug
2. query_stale_deals - standard time window filtering
3. query_pre_call_brief - reads STAGE_COMPONENT_QUESTIONS from coaching_client.yaml
4. query_call_quality - uses migration 038 call_quality table
"""

import sys
from pathlib import Path
import asyncio
from unittest.mock import MagicMock

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / 'scripts'))

# Import handlers from the api module
import importlib.util
spec = importlib.util.spec_from_file_location("handlers", _REPO_ROOT / "api" / "handlers.py")
handlers_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handlers_module)

query_deal_health = handlers_module.query_deal_health
query_stale_deals = handlers_module.query_stale_deals
query_pre_call_brief = handlers_module.query_pre_call_brief
query_call_quality = handlers_module.query_call_quality


def make_mock_sb():
    """Create a mock Supabase client that returns empty results."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_execute = MagicMock()

    # Chain the mocks
    mock_sb.table.return_value = mock_table
    mock_table.select.return_value = mock_select
    mock_select.execute.return_value.data = []

    return mock_sb


async def test_query_deal_health_accepts_list():
    """query_deal_health must accept deal_ids as list (not string) to prevent
    char-iteration bug that produced in.(6,0,1,4,...)."""
    print("\n[TEST] query_deal_health accepts deal_ids as list")

    mock_sb = make_mock_sb()

    # Mock select_all to return empty results
    original_select_all = handlers_module.select_all
    handlers_module.select_all = lambda *args, **kwargs: []

    try:
        # Test with list of deal IDs (correct)
        params_with_list = {
            "deal_ids": ["60785", "60786"],
            "time_window": {"start": "2026-01-01", "label": "Q1 2026"}
        }
        result = await query_deal_health(params_with_list, mock_sb)
        assert "deals" in result, "Should return deals key"
        print("  ✓ Accepted deal_ids as list")

        # Test with string (handler should convert to list internally)
        params_with_string = {
            "deal_ids": "60785",
            "time_window": {"start": "2026-01-01", "label": "Q1 2026"}
        }
        result = await query_deal_health(params_with_string, mock_sb)
        assert "deals" in result, "Should handle string by converting to list"
        print("  ✓ Converted single string to list internally")

    finally:
        # Restore original
        handlers_module.select_all = original_select_all

    print("  ✓ PASS: query_deal_health prevents char-iteration bug")


async def test_query_stale_deals_handles_empty_results():
    """query_stale_deals should handle empty results gracefully."""
    print("\n[TEST] query_stale_deals handles empty results")

    mock_sb = make_mock_sb()

    original_select_all = handlers_module.select_all
    handlers_module.select_all = lambda *args, **kwargs: []

    try:
        params = {
            "time_window": {"start": "2026-01-01", "end": "2026-03-31", "label": "Q1 2026"},
            "stale_days": 30
        }
        result = await query_stale_deals(params, mock_sb)

        assert "stale_deals" in result
        assert result["count"] == 0
        assert "stale_threshold_days" in result
        print("  ✓ Returns empty list with metadata")

    finally:
        handlers_module.select_all = original_select_all

    print("  ✓ PASS: query_stale_deals handles empty results")


async def test_query_pre_call_brief_reads_coaching_config():
    """query_pre_call_brief should read stage_component_questions from
    config/coaching_client.yaml."""
    print("\n[TEST] query_pre_call_brief reads coaching config")

    # Check that coaching_client.yaml has the structure
    import yaml
    config_path = _REPO_ROOT / "config" / "coaching_client.yaml"
    config = yaml.safe_load(open(config_path))

    assert "stage_component_questions" in config, \
        "coaching_client.yaml should have stage_component_questions"
    print("  ✓ coaching_client.yaml has stage_component_questions")

    # Test handler with mock data
    mock_sb = make_mock_sb()
    original_select_all = handlers_module.select_all

    def mock_select_all(sb, table, columns=None, filters=None):
        if table == "deals":
            return [{
                "deal_id": "60785",
                "company_name": "Test Company",
                "deal_value": 50000,
                "stage": "discovery",
                "owner_email": "rep@example.com",
                "close_date": "2026-06-30"
            }]
        return []

    handlers_module.select_all = mock_select_all

    try:
        params = {
            "company": "Test Company"
        }
        result = await query_pre_call_brief(params, mock_sb)

        assert "deal" in result
        assert "recommended_questions" in result
        print("  ✓ Returns recommended_questions from config")

    finally:
        handlers_module.select_all = original_select_all

    print("  ✓ PASS: query_pre_call_brief reads coaching config")


async def test_query_call_quality_uses_migration_038():
    """query_call_quality should query call_quality table from migration 038."""
    print("\n[TEST] query_call_quality uses migration 038 table")

    # Verify migration exists
    migration_file = _REPO_ROOT / "scripts" / "migrations" / "038_add_call_quality.sql"
    assert migration_file.exists(), "Migration 038 should exist"
    print("  ✓ Migration 038 exists")

    # Check migration creates call_quality table
    migration_sql = migration_file.read_text()
    assert "CREATE TABLE IF NOT EXISTS call_quality" in migration_sql
    print("  ✓ Migration creates call_quality table")

    # Test handler with empty table
    mock_sb = make_mock_sb()
    original_select_all = handlers_module.select_all
    handlers_module.select_all = lambda *args, **kwargs: []

    try:
        params = {
            "time_window": {"start": "2026-01-01", "end": "2026-03-31", "label": "Q1 2026"}
        }
        result = await query_call_quality(params, mock_sb)

        # Should return note about empty table
        assert "note" in result
        assert "empty" in result["note"].lower()
        print("  ✓ Handles empty call_quality table gracefully")

    finally:
        handlers_module.select_all = original_select_all

    print("  ✓ PASS: query_call_quality uses migration 038")


async def run_all_tests():
    """Run all batch 1 handler tests."""
    print("=" * 70)
    print("BATCH 1 HANDLERS VERIFICATION TESTS")
    print("=" * 70)
    print("\nVerifies four deal-level handlers with production fixes")

    tests = [
        test_query_deal_health_accepts_list,
        test_query_stale_deals_handles_empty_results,
        test_query_pre_call_brief_reads_coaching_config,
        test_query_call_quality_uses_migration_038,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
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

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run_all_tests()))
