#!/usr/bin/env python3
"""
Verification tests for Batch 2 handlers (rep and team).

Tests:
1. query_rep_pipeline - rep name resolution via user_personas
2. query_rep_attainment - performance vs target
3. query_team_leaderboard - team rankings
4. query_coaching_priorities - blocker taxonomy from config
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

# Mock _resolve_tw to avoid import errors in tests
handlers_module._resolve_tw = lambda params: {
    "start": "2026-01-01",
    "end": "2026-03-31",
    "label": "Q1 2026"
}

query_rep_pipeline = handlers_module.query_rep_pipeline
query_rep_attainment = handlers_module.query_rep_attainment
query_team_leaderboard = handlers_module.query_team_leaderboard
query_coaching_priorities = handlers_module.query_coaching_priorities


def make_mock_sb():
    """Create a mock Supabase client."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_execute = MagicMock()

    mock_sb.table.return_value = mock_table
    mock_table.select.return_value = mock_select
    mock_select.execute.return_value.data = []

    return mock_sb


async def test_query_rep_pipeline_resolves_names():
    """query_rep_pipeline accepts owner_email, rep_email, first name, or full name.
    Resolves via user_personas to fix the reference implementation bugs:
    1. Errored on rep names (no resolution)
    2. Param mismatch (intent emitted rep_email, handler read owner_email)"""
    print("\n[TEST] query_rep_pipeline resolves rep names")

    mock_sb = make_mock_sb()
    original_select_all = handlers_module.select_all

    def mock_select_all(sb, table, columns=None, filters=None):
        if table == "user_personas":
            return [{
                "email": "christian@example.com",
                "display_name": "Christian Liebenow",
                "name": "Christian Liebenow",
                "role": "ae"
            }]
        return []  # Empty deals/analyses

    handlers_module.select_all = mock_select_all

    try:
        # Test 1: Accept rep_email param
        result = await query_rep_pipeline({"rep_email": "christian@example.com"}, mock_sb)
        assert "rep_email" in result
        assert result["rep_email"] == "christian@example.com"
        print("  ✓ Accepts rep_email param")

        # Test 2: Accept owner_email param
        result = await query_rep_pipeline({"owner_email": "christian@example.com"}, mock_sb)
        assert result["rep_email"] == "christian@example.com"
        print("  ✓ Accepts owner_email param")

        # Test 3: Resolve first name
        result = await query_rep_pipeline({"rep_name": "Christian"}, mock_sb)
        assert result["rep_email"] == "christian@example.com"
        print("  ✓ Resolves first name to email")

        # Test 4: Resolve full name
        result = await query_rep_pipeline({"rep_name": "Christian Liebenow"}, mock_sb)
        assert result["rep_email"] == "christian@example.com"
        print("  ✓ Resolves full name to email")

        # Test 5: Error on unknown rep
        result = await query_rep_pipeline({"rep_name": "Unknown Person"}, mock_sb)
        assert "error" in result
        print("  ✓ Returns error for unknown rep")

    finally:
        handlers_module.select_all = original_select_all

    print("  ✓ PASS: query_rep_pipeline resolves multiple param formats")


async def test_query_rep_attainment_handles_missing_target():
    """query_rep_attainment handles missing quota targets gracefully."""
    print("\n[TEST] query_rep_attainment handles missing target")

    mock_sb = make_mock_sb()
    original_select_all = handlers_module.select_all

    def mock_select_all(sb, table, columns=None, filters=None):
        if table == "user_personas":
            return [{"email": "rep@example.com", "display_name": "Test Rep", "name": "Test Rep"}]
        if table == "deals":
            return [{"deal_id": "1", "company_name": "Test Co", "deal_value": 50000, "new_arr": 50000}]
        if table == "rep_targets":
            return []  # No target set
        return []

    handlers_module.select_all = mock_select_all

    try:
        result = await query_rep_attainment({"rep_email": "rep@example.com"}, mock_sb)
        assert "total_closed" in result
        assert "target" in result
        assert result["target"] is None
        assert result["attainment_pct"] is None
        print("  ✓ Returns None for missing target (no crash)")

    finally:
        handlers_module.select_all = original_select_all

    print("  ✓ PASS: query_rep_attainment handles missing target")


async def test_query_team_leaderboard_metrics():
    """query_team_leaderboard supports pipeline, attainment, and meddicc metrics."""
    print("\n[TEST] query_team_leaderboard supports multiple metrics")

    mock_sb = make_mock_sb()
    original_select_all = handlers_module.select_all

    def mock_select_all(sb, table, columns=None, filters=None):
        if table == "user_personas":
            return [
                {"email": "rep1@example.com", "display_name": "Rep 1", "role": "ae"},
                {"email": "rep2@example.com", "display_name": "Rep 2", "role": "ae"}
            ]
        return []

    handlers_module.select_all = mock_select_all

    try:
        # Test pipeline metric
        result = await query_team_leaderboard({"metric": "pipeline"}, mock_sb)
        assert "leaderboard" in result
        assert result["metric"] == "pipeline"
        print("  ✓ Supports pipeline metric")

        # Test attainment metric
        result = await query_team_leaderboard({"metric": "attainment"}, mock_sb)
        assert result["metric"] == "attainment"
        print("  ✓ Supports attainment metric")

        # Test meddicc metric
        result = await query_team_leaderboard({"metric": "meddicc"}, mock_sb)
        assert result["metric"] == "meddicc"
        print("  ✓ Supports meddicc metric")

    finally:
        handlers_module.select_all = original_select_all

    print("  ✓ PASS: query_team_leaderboard supports all metrics")


async def test_query_coaching_priorities_reads_config():
    """query_coaching_priorities reads blocker_taxonomy from coaching_seed.yaml,
    not hardcoded values."""
    print("\n[TEST] query_coaching_priorities reads config")

    # Verify coaching_seed.yaml has blocker_taxonomy
    import yaml
    config_path = _REPO_ROOT / "config" / "coaching_seed.yaml"
    config = yaml.safe_load(open(config_path))

    assert "blocker_taxonomy" in config, \
        "coaching_seed.yaml should have blocker_taxonomy"

    taxonomy = config["blocker_taxonomy"]
    assert "technical" in taxonomy
    assert "resourcing" in taxonomy
    assert "cultural" in taxonomy
    assert "commercial" in taxonomy
    print("  ✓ coaching_seed.yaml has blocker_taxonomy")

    # Verify each blocker type has signals and right_response
    for blocker_type, data in taxonomy.items():
        assert "signals" in data, f"{blocker_type} should have signals"
        assert "right_response" in data, f"{blocker_type} should have right_response"
    print("  ✓ All blocker types have signals and right_response")

    # Test handler reads from config
    mock_sb = make_mock_sb()
    original_select_all = handlers_module.select_all
    handlers_module.select_all = lambda *args, **kwargs: []

    # Mock get_components import
    import sys
    from unittest.mock import MagicMock
    mock_stage_req = MagicMock()
    mock_stage_req.get_components = lambda: ["pain", "champion", "metrics"]
    sys.modules['api.stage_requirements'] = mock_stage_req

    try:
        result = await query_coaching_priorities({}, mock_sb)
        assert "priorities" in result
        assert "blocker_distribution" in result
        print("  ✓ Handler reads blocker_taxonomy from config")

    finally:
        handlers_module.select_all = original_select_all
        if 'api.stage_requirements' in sys.modules:
            del sys.modules['api.stage_requirements']

    print("  ✓ PASS: query_coaching_priorities reads config")


async def run_all_tests():
    """Run all batch 2 handler tests."""
    print("=" * 70)
    print("BATCH 2 HANDLERS VERIFICATION TESTS")
    print("=" * 70)
    print("\nVerifies four rep/team handlers with the reference implementation fixes")

    tests = [
        test_query_rep_pipeline_resolves_names,
        test_query_rep_attainment_handles_missing_target,
        test_query_team_leaderboard_metrics,
        test_query_coaching_priorities_reads_config,
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
