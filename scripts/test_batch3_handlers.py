#!/usr/bin/env python3
"""
Verification tests for Batch 3 handlers (SDR + pipeline movement).

Tests:
1. query_sdr_activity - individual SDR daily activity
2. query_sdr_performance - conversion rates and benchmarks
3. query_team_sdr_metrics - team-level aggregates
4. query_pipeline_movement - waterfall movement data
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

# Mock _resolve_tw to avoid import errors
handlers_module._resolve_tw = lambda params: {
    "start": "2026-01-01",
    "end": "2026-03-31",
    "label": "Q1 2026"
}

query_sdr_activity = handlers_module.query_sdr_activity
query_sdr_performance = handlers_module.query_sdr_performance
query_team_sdr_metrics = handlers_module.query_team_sdr_metrics
query_pipeline_movement = handlers_module.query_pipeline_movement


def make_mock_sb():
    """Create a mock Supabase client."""
    return MagicMock()


async def test_query_sdr_activity_handles_empty_table():
    """query_sdr_activity handles empty sdr_metrics table gracefully."""
    print("\n[TEST] query_sdr_activity handles empty table")

    mock_sb = make_mock_sb()
    original_select_all = handlers_module.select_all
    handlers_module.select_all = lambda *args, **kwargs: []

    try:
        result = await query_sdr_activity({}, mock_sb)
        assert "note" in result
        assert "empty" in result["note"].lower()
        print("  ✓ Returns informative note for empty table")

    finally:
        handlers_module.select_all = original_select_all

    print("  ✓ PASS: query_sdr_activity handles empty table")


async def test_query_sdr_performance_calculates_benchmarks():
    """query_sdr_performance calculates team benchmarks from individual metrics."""
    print("\n[TEST] query_sdr_performance calculates benchmarks")

    mock_sb = make_mock_sb()
    original_select_all = handlers_module.select_all

    def mock_select_all(sb, table, columns=None, filters=None):
        if table == "sdr_metrics":
            # Return sample data
            return [
                {
                    "id": 1,  # Sample row to indicate table has data
                    "tool": "apollo",
                    "user_name": "SDR 1",
                    "tool_user_id": "user1",
                    "calls_made": 50,
                    "connected_calls": 10,
                    "emails_sent": 30,
                    "emails_replied": 3
                },
                {
                    "id": 2,
                    "tool": "salesloft",
                    "user_name": "SDR 2",
                    "tool_user_id": "user2",
                    "calls_made": 40,
                    "connected_calls": 8,
                    "emails_sent": 20,
                    "emails_replied": 2
                }
            ]
        return []

    handlers_module.select_all = mock_select_all

    try:
        result = await query_sdr_performance({}, mock_sb)
        assert "team_benchmarks" in result
        assert "sdr_performance" in result

        benchmarks = result["team_benchmarks"]
        assert benchmarks["total_calls"] == 90
        assert benchmarks["team_connect_rate"] == 20.0  # 18/90 * 100
        print("  ✓ Calculates team benchmarks correctly")

    finally:
        handlers_module.select_all = original_select_all

    print("  ✓ PASS: query_sdr_performance calculates benchmarks")


async def test_query_team_sdr_metrics_builds_daily_trend():
    """query_team_sdr_metrics aggregates daily totals and builds trend."""
    print("\n[TEST] query_team_sdr_metrics builds daily trend")

    mock_sb = make_mock_sb()
    original_select_all = handlers_module.select_all

    def mock_select_all(sb, table, columns=None, filters=None):
        if table == "sdr_metrics":
            return [
                {
                    "id": 1,
                    "metric_date": "2026-01-15",
                    "calls_made": 25,
                    "connected_calls": 5,
                    "emails_sent": 15,
                    "emails_opened": 8,
                    "emails_replied": 2,
                    "voicemails": 10
                },
                {
                    "id": 2,
                    "metric_date": "2026-01-15",
                    "calls_made": 30,
                    "connected_calls": 6,
                    "emails_sent": 20,
                    "emails_opened": 10,
                    "emails_replied": 3,
                    "voicemails": 12
                }
            ]
        return []

    handlers_module.select_all = mock_select_all

    try:
        result = await query_team_sdr_metrics({}, mock_sb)
        assert "team_metrics" in result
        assert "daily_trend" in result

        metrics = result["team_metrics"]
        assert metrics["total_calls"] == 55
        assert metrics["total_connected"] == 11
        print("  ✓ Aggregates team metrics correctly")

        trend = result["daily_trend"]
        assert len(trend) == 1  # One unique date
        assert trend[0]["date"] == "2026-01-15"
        assert trend[0]["calls"] == 55
        print("  ✓ Builds daily trend correctly")

    finally:
        handlers_module.select_all = original_select_all

    print("  ✓ PASS: query_team_sdr_metrics builds daily trend")


async def test_query_pipeline_movement_uses_waterfall():
    """query_pipeline_movement reads from waterfall_weekly table."""
    print("\n[TEST] query_pipeline_movement uses waterfall table")

    mock_sb = make_mock_sb()
    original_select_all = handlers_module.select_all

    def mock_select_all(sb, table, columns=None, filters=None):
        if table == "waterfall_weekly":
            return [
                {
                    "week_ending": "2026-01-12",
                    "pipeline_id": "default",
                    "new_pipeline_value": 100000,
                    "won_value": 50000,
                    "lost_value": 20000,
                    "net_change": 30000,
                    "pulled_in_value": 0,
                    "pushed_out_value": 0,
                    "deals_qualified_count": 5
                }
            ]
        return []

    handlers_module.select_all = mock_select_all

    try:
        result = await query_pipeline_movement({}, mock_sb)
        assert "pipeline_movement" in result
        assert "period_totals" in result

        totals = result["period_totals"]
        assert totals["new_pipeline"] == 100000
        assert totals["won"] == 50000
        assert totals["lost"] == 20000
        assert totals["net_change"] == 30000
        print("  ✓ Calculates period totals from waterfall data")

    finally:
        handlers_module.select_all = original_select_all

    print("  ✓ PASS: query_pipeline_movement uses waterfall table")


async def run_all_tests():
    """Run all batch 3 handler tests."""
    print("=" * 70)
    print("BATCH 3 HANDLERS VERIFICATION TESTS")
    print("=" * 70)
    print("\nVerifies SDR + pipeline movement handlers")

    tests = [
        test_query_sdr_activity_handles_empty_table,
        test_query_sdr_performance_calculates_benchmarks,
        test_query_team_sdr_metrics_builds_daily_trend,
        test_query_pipeline_movement_uses_waterfall,
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
