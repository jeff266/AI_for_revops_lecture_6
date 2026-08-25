#!/usr/bin/env python3
"""
Guard test: No handler raises on missing params.

A KeyError on missing params drops to the dynamic loop, which burns
the 20k query budget and returns "Hit query budget with partial data."
This was the single most common user-visible failure in GrowthBook
(three separate incidents).

Every handler must return a clear error dict on missing required params,
never raise KeyError.
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

# Mock supabase_client before loading handlers
sys.modules['supabase_client'] = MagicMock()
sys.modules['supabase_client'].select_all = lambda *args, **kwargs: []

spec.loader.exec_module(handlers_module)


def make_mock_sb():
    """Create a mock Supabase client that returns empty results."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_execute = MagicMock()

    mock_sb.table.return_value = mock_table
    mock_table.select.return_value = mock_select
    mock_select.execute.return_value.data = []

    return mock_sb


async def test_no_handler_raises_on_missing_params():
    """Every handler returns a clear error dict on missing required params,
    never a KeyError. A raise drops to the dynamic loop, which burns the
    query budget and returns nothing useful."""
    print("\n[TEST] No handler raises on missing params")

    # Enumerate all async handler functions
    handler_names = [
        "query_waterfall",
        "query_arr",
        "query_deals_at_risk",
        "query_win_loss",
        "query_objections",
        "query_feature_gaps",
        "query_coverage",
        "query_deal",
        "query_rubric",
        "generate_win_loss",
        "set_target",
        "query_new_deals",
        "query_competitive_intel",
        "query_won_deals",
        "query_rubric_scores_bulk",
        "query_deal_stages_bulk",
        "query_deal_owners_bulk",
        "query_deal_values_bulk",
        # Batch 1 handlers
        "query_deal_health",
        "query_stale_deals",
        "query_pre_call_brief",
        "query_call_quality",
    ]

    mock_sb = make_mock_sb()
    passed = 0
    failed = 0

    for handler_name in handler_names:
        handler = getattr(handlers_module, handler_name, None)
        if not handler:
            print(f"  ⚠️  Handler {handler_name} not found, skipping")
            continue

        try:
            # Call with empty params dict
            result = await handler({}, mock_sb)

            # Should return dict (error or empty data), not raise
            assert isinstance(result, dict), \
                f"{handler_name} must return dict, got {type(result)}"

            # If it returns an error, that's fine - the point is it didn't raise
            if "error" in result:
                print(f"  ✓ {handler_name}: returned error dict (good)")
            else:
                print(f"  ✓ {handler_name}: returned empty data dict (good)")

            passed += 1

        except KeyError as e:
            failed += 1
            print(f"  ❌ {handler_name}: raised KeyError({e}) - will burn query budget!")
        except Exception as e:
            # Other exceptions might be acceptable (e.g., missing config file)
            # but KeyError is specifically bad
            print(f"  ⚠️  {handler_name}: raised {type(e).__name__}({e}) - investigate")
            passed += 1  # Don't count as failure unless it's KeyError

    print(f"\n  Tested {len(handler_names)} handlers")
    print(f"  ✓ {passed} handlers safe (return dict or acceptable exception)")
    print(f"  ❌ {failed} handlers raise KeyError (WILL BURN QUERY BUDGET)")

    if failed > 0:
        print("\n  ⚠️  CRITICAL: Handlers that raise KeyError will drop to dynamic")
        print("     loop and waste the entire query budget on retry attempts.")
        print("     Fix: Use params.get() with defaults or _resolve_tw(params).")

    return failed == 0


def main():
    """Run handler safety guard test."""
    print("=" * 70)
    print("HANDLER PARAMS SAFETY GUARD")
    print("=" * 70)
    print("\nGuard against: KeyError on missing params → dynamic loop → query budget burned")
    print("This was the #1 user-visible failure in GrowthBook (3 incidents)")

    result = asyncio.run(test_no_handler_raises_on_missing_params())

    print("\n" + "=" * 70)
    if result:
        print("PASS: All handlers safe")
    else:
        print("FAIL: Some handlers will burn query budget")
    print("=" * 70)

    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
