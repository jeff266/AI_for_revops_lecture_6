#!/usr/bin/env python3
"""
Verification tests for Batch 3 handlers (SDR + pipeline movement).

Tests:
1. query_sdr_pipeline_sourced - SDR attribution, "__not_null__" operator fix
2. query_sdr_metrics - individual SDR activity metrics
3. query_sdr_leaderboard - team rankings by activity
4. query_pipeline_movement - reads deals_snapshot (NOT waterfall_weekly)
"""

import sys
import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

_REPO_ROOT = Path(__file__).parent.parent

# Load handlers module
spec = importlib.util.spec_from_file_location("handlers", _REPO_ROOT / "api" / "handlers.py")
handlers_module = importlib.util.module_from_spec(spec)

# Mock supabase_client before loading
sys.modules['supabase_client'] = MagicMock()
sys.modules['supabase_client'].select_all = lambda *args, **kwargs: []

spec.loader.exec_module(handlers_module)

# Mock _resolve_tw and _resolve_owner_email to avoid import errors
handlers_module._resolve_tw = lambda params: {
    "start": "2026-01-01",
    "end": "2026-03-31",
    "label": "Q1 2026"
}
handlers_module._resolve_owner_email = lambda params, sb: (None, None)

query_sdr_pipeline_sourced = handlers_module.query_sdr_pipeline_sourced
query_sdr_metrics = handlers_module.query_sdr_metrics
query_sdr_leaderboard = handlers_module.query_sdr_leaderboard
query_pipeline_movement = handlers_module.query_pipeline_movement


def make_mock_sb():
    """Create a mock Supabase client."""
    return MagicMock()


async def test_query_sdr_pipeline_sourced_uses_not_null():
    """query_sdr_pipeline_sourced uses '__not_null__' operator, not 'not.is'.

    The production fix: The old 'not.is' operator raised AttributeError
    when select_all tried getattr(q, 'not.is'). The correct operator is
    '__not_null__'.
    """
    print("\n[TEST] query_sdr_pipeline_sourced uses __not_null__ operator")

    mock_sb = make_mock_sb()
    original_select_all = handlers_module.select_all

    # Track the filter operators used
    filters_seen = []

    def mock_select_all(sb, table, columns=None, filters=None):
        if table == "deals":
            filters_seen.extend(filters or [])
        return []

    handlers_module.select_all = mock_select_all

    try:
        result = await query_sdr_pipeline_sourced({}, mock_sb)

        # Verify __not_null__ was used
        has_not_null = any(f[0] == "__not_null__" and f[1] == "sdr_owner_email"
                          for f in filters_seen)
        assert has_not_null, \
            "query_sdr_pipeline_sourced must use ('__not_null__', 'sdr_owner_email') filter"

        # Verify 'not.is' was NOT used (would raise AttributeError)
        has_not_is = any(f[0] == "not.is" for f in filters_seen)
        assert not has_not_is, "Must not use 'not.is' operator (raises AttributeError)"

        print("  ✓ Uses ('__not_null__', 'sdr_owner_email') filter")
        print("  ✓ Does NOT use 'not.is' operator")

    finally:
        handlers_module.select_all = original_select_all

    print("  ✓ PASS: query_sdr_pipeline_sourced uses correct filter operator")


async def test_query_sdr_metrics_queries_multiple_tables():
    """query_sdr_metrics queries sdr_metrics, sdr_users, and meetings tables."""
    print("\n[TEST] query_sdr_metrics queries multiple tables")

    mock_sb = make_mock_sb()
    original_select_all = handlers_module.select_all
    original_resolve_owner = handlers_module._resolve_owner_email

    tables_queried = set()

    def mock_select_all(sb, table, columns=None, filters=None):
        tables_queried.add(table)
        if table == "sdr_metrics":
            return [{"id": 1}]  # Sample to pass empty check
        if table == "sdr_users":
            return [{
                "user_email": "sdr@example.com",
                "user_name": "SDR User",
                "tool": "apollo",
                "tool_user_id": "user123"
            }]
        return []

    # Mock _resolve_owner_email to return the email directly
    handlers_module._resolve_owner_email = lambda params, sb: ("sdr@example.com", None)
    handlers_module.select_all = mock_select_all

    try:
        result = await query_sdr_metrics({"sdr_email": "sdr@example.com"}, mock_sb)

        assert "sdr_metrics" in tables_queried, "Must query sdr_metrics table"
        assert "sdr_users" in tables_queried, "Must query sdr_users table"
        assert "meetings" in tables_queried, "Must query meetings table"

        assert "calls_summary" in result
        assert "meetings_summary" in result

        print("  ✓ Queries sdr_metrics, sdr_users, and meetings tables")
        print("  ✓ Returns calls_summary and meetings_summary")

    finally:
        handlers_module.select_all = original_select_all
        handlers_module._resolve_owner_email = original_resolve_owner

    print("  ✓ PASS: query_sdr_metrics queries correct tables")


async def test_query_sdr_leaderboard_aggregates_by_user():
    """query_sdr_leaderboard aggregates by (tool, tool_user_id) key."""
    print("\n[TEST] query_sdr_leaderboard aggregates by user")

    mock_sb = make_mock_sb()
    original_select_all = handlers_module.select_all

    def mock_select_all(sb, table, columns=None, filters=None):
        if table == "sdr_metrics":
            # Return sample data with duplicates for same user
            return [
                {
                    "tool": "apollo",
                    "tool_user_id": "user1",
                    "user_name": "SDR 1",
                    "metric_date": "2026-01-15",
                    "calls_made": 25,
                    "connected_calls": 5,
                    "emails_sent": 15,
                    "emails_replied": 2,
                    "meeting_booked": 1
                },
                {
                    "tool": "apollo",
                    "tool_user_id": "user1",  # Same user, different date
                    "user_name": "SDR 1",
                    "metric_date": "2026-01-16",
                    "calls_made": 30,
                    "connected_calls": 6,
                    "emails_sent": 20,
                    "emails_replied": 3,
                    "meeting_booked": 2
                }
            ]
        return [{"id": 1}]  # Sample to pass empty check

    handlers_module.select_all = mock_select_all

    try:
        result = await query_sdr_leaderboard({}, mock_sb)

        assert "leaderboard" in result
        assert len(result["leaderboard"]) == 1, "Should aggregate duplicate user to 1 entry"

        user = result["leaderboard"][0]
        assert user["calls_made"] == 55, "Should sum calls across dates"
        assert user["connected_calls"] == 11, "Should sum connected calls"

        print("  ✓ Aggregates by (tool, tool_user_id) key")
        print("  ✓ Sums metrics across dates for same user")

    finally:
        handlers_module.select_all = original_select_all

    print("  ✓ PASS: query_sdr_leaderboard aggregates correctly")


async def test_query_pipeline_movement_reads_deals_snapshot():
    """query_pipeline_movement reads deals_snapshot table, NOT waterfall_weekly.

    This is the critical batch 3 correction: the invented handler read
    waterfall_weekly (which has no writer), but the correct handler reads
    deals_snapshot for point-in-time pipeline reconstruction.
    """
    print("\n[TEST] query_pipeline_movement reads deals_snapshot")

    mock_sb = make_mock_sb()
    original_select_all = handlers_module.select_all

    # Mock the helper functions that query_pipeline_movement needs
    def mock_load_scope_config():
        return set(), {}  # excluded_pipelines, stage_cfg

    def mock_is_in_scope(stage_id, pipeline_id, excluded_pipelines, stage_cfg):
        return True

    handlers_module._pm_load_scoping = lambda: (mock_load_scope_config, mock_is_in_scope)
    handlers_module._pm_current_quarter_label = lambda: "FY2027 Q2"

    tables_queried = set()

    def mock_select_all(sb, table, columns=None, filters=None):
        tables_queried.add(table)
        return []

    handlers_module.select_all = mock_select_all

    try:
        result = await query_pipeline_movement({}, mock_sb)

        assert "deals_snapshot" in tables_queried, \
            "query_pipeline_movement MUST read deals_snapshot, not waterfall_weekly"

        assert "waterfall_weekly" not in tables_queried, \
            "Must NOT read waterfall_weekly (has no writer in template)"

        assert "basis" in result and result["basis"] == "count", \
            "Must return basis='count' (COUNTS ONLY, never dollars)"

        print("  ✓ Reads deals_snapshot table")
        print("  ✓ Does NOT read waterfall_weekly")
        print("  ✓ Returns basis='count' (COUNTS ONLY)")

    finally:
        handlers_module.select_all = original_select_all

    print("  ✓ PASS: query_pipeline_movement uses correct substrate")


async def run_all_tests():
    """Run all batch 3 handler tests."""
    print("=" * 70)
    print("BATCH 3 HANDLERS VERIFICATION TESTS")
    print("=" * 70)
    print("\nVerifies SDR + pipeline movement handlers (CORRECTED from drift)")

    tests = [
        test_query_sdr_pipeline_sourced_uses_not_null,
        test_query_sdr_metrics_queries_multiple_tables,
        test_query_sdr_leaderboard_aggregates_by_user,
        test_query_pipeline_movement_reads_deals_snapshot,
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
