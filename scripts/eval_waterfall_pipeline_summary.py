#!/usr/bin/env python3
"""
Eval: query_waterfall pipeline_summary.

Tests that query_waterfall:
1. Excludes exclude_from_analysis stages
2. Uses stage names (not IDs)
3. Stays under 2K chars for pipeline_summary
4. Adapts synthesis emphasis based on question framing
"""

import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_pipeline_summary():
    """Test pipeline_summary structure and content."""
    import asyncio
    from api.handlers import query_waterfall

    print("="*80)
    print("QUERY_WATERFALL PIPELINE_SUMMARY EVAL")
    print("="*80)
    print()

    # Mock Supabase client
    class MockSupabase:
        def __init__(self):
            self.queries = []

        def table(self, name):
            self.current_table = name
            return self

        def select(self, columns):
            self.current_columns = columns
            return self

        def execute(self):
            self.queries.append((self.current_table, self.current_columns))

            # Return mock data based on table
            if self.current_table == "deals":
                # Simulate 200+ deals with various stages
                class Result:
                    data = []
                    # Generate realistic deal distribution
                    for i in range(250):
                        stage = [
                            "appointmentscheduled",  # Discovery (included)
                            "qualifiedtobuy",        # Scoping (included)
                            "presentationscheduled", # Tech Eval (included)
                            "24682892",              # Negotiating (included)
                            "79653122",              # Meeting Set (EXCLUDED)
                            "68509551",              # Disqualified (EXCLUDED)
                            "closedwon",             # Won (but deal_status != active)
                        ][i % 7]

                        # Only include active deals
                        if stage not in ["closedwon"]:
                            arr = (i + 1) * 1000 if i % 5 != 0 else None  # Some deals without ARR
                            data.append({
                                "deal_id": f"deal_{i}",
                                "company_name": f"Company {i}",
                                "arr_usd": arr,
                                "stage": stage,
                                "deal_status": "active"
                            })

                return Result()

            elif self.current_table == "analyses":
                # Mock analyses with some at-risk deals
                class Result:
                    data = []
                    for i in range(50):
                        # Every 3rd deal is at-risk
                        score = 35 if i % 3 == 0 else 65
                        champ = 3 if i % 3 == 0 else 7
                        data.append({
                            "deal_id": f"deal_{i}",
                            "company_name": f"Company {i}",
                            "overall_score": score,
                            "champion_score": champ,
                            "analyzed_at": "2026-08-17T10:00:00Z"
                        })
                return Result()

            elif self.current_table == "waterfall_weekly":
                class Result:
                    data = [
                        {
                            "week_ending": "2026-08-17",
                            "pipeline_id": "default",
                            "new_pipeline_value": 500000,
                            "won_value": 150000,
                            "lost_value": 75000,
                            "net_change": 375000,
                            "pulled_in_value": 0,
                            "pushed_out_value": 0,
                            "deals_qualified_count": 12
                        }
                    ]
                return Result()

            class Result:
                data = []
            return Result()

        def eq(self, col, val):
            return self

        def gte(self, col, val):
            return self

        def lte(self, col, val):
            return self

        def range(self, start, end):
            return self

    sb = MockSupabase()

    # Test 1: pipeline_summary structure and exclusions
    print("[TEST 1] pipeline_summary excludes exclude_from_analysis stages")

    params = {
        "time_window": {
            "start": "2026-08-10",
            "end": "2026-08-17",
            "label": "This Week"
        },
        "question": "show me current pipeline"
    }

    result = asyncio.run(query_waterfall(params, sb))

    pipeline_summary = result.get("pipeline_summary", {})

    print(f"  Total open ARR: ${pipeline_summary.get('total_open_arr', 0):,.0f}")
    print(f"  Total open count: {pipeline_summary.get('total_open_count', 0)}")
    print(f"  By-stage breakdown: {len(pipeline_summary.get('by_stage', []))} stages")

    # Verify structure
    assert "total_open_arr" in pipeline_summary, "Missing total_open_arr"
    assert "total_open_count" in pipeline_summary, "Missing total_open_count"
    assert "by_stage" in pipeline_summary, "Missing by_stage"
    assert "needs_attention" in pipeline_summary, "Missing needs_attention"

    # Verify by_stage uses names not IDs
    for stage in pipeline_summary["by_stage"]:
        assert "stage_name" in stage, "Missing stage_name"
        assert "count" in stage, "Missing count"
        assert "arr" in stage, "Missing arr"

        # Stage name should be human-readable, not a raw ID
        stage_name = stage["stage_name"]
        assert not stage_name.isdigit(), f"Stage name is an ID: {stage_name}"
        assert len(stage_name) > 2, f"Stage name too short: {stage_name}"

    print(f"  ✓ Structure validated (uses stage names, not IDs)")

    # Verify excluded stages are NOT in by_stage
    by_stage_names = {s["stage_name"] for s in pipeline_summary["by_stage"]}

    # These stages should be EXCLUDED
    excluded_names = ["Meeting Set", "Disqualified"]
    for excluded in excluded_names:
        assert excluded not in by_stage_names, \
            f"Excluded stage '{excluded}' found in by_stage"

    print(f"  ✓ Excluded stages not in by_stage: {excluded_names}")

    # Verify needs_attention structure
    needs_attention = pipeline_summary.get("needs_attention", {})
    assert "no_arr_count" in needs_attention, "Missing no_arr_count"
    assert "no_arr_deals" in needs_attention, "Missing no_arr_deals"
    assert "at_risk_count" in needs_attention, "Missing at_risk_count"
    assert "at_risk_deals" in needs_attention, "Missing at_risk_deals"

    # no_arr_deals should be capped at 5
    assert len(needs_attention["no_arr_deals"]) <= 5, \
        f"no_arr_deals not capped at 5: {len(needs_attention['no_arr_deals'])}"

    # at_risk_deals should be capped at 5
    assert len(needs_attention["at_risk_deals"]) <= 5, \
        f"at_risk_deals not capped at 5: {len(needs_attention['at_risk_deals'])}"

    print(f"  ✓ needs_attention validated (capped at 5)")
    print()

    # Test 2: Size constraint (under 2K chars)
    print("[TEST 2] pipeline_summary stays under 2K chars")

    summary_json = json.dumps(pipeline_summary)
    summary_size = len(summary_json)

    print(f"  pipeline_summary size: {summary_size:,} chars")
    print(f"  Size limit: 2,000 chars")

    assert summary_size < 2000, \
        f"pipeline_summary too large: {summary_size} chars (limit 2K)"

    print(f"  ✓ Size constraint met ({summary_size} < 2,000)")
    print()

    # Test 3: Report shape adapts to question framing
    print("[TEST 3] Report shape adapts to question framing")

    # Snapshot question
    params_snapshot = {
        "time_window": params["time_window"],
        "question": "show me current open pipeline"
    }

    result_snapshot = asyncio.run(query_waterfall(params_snapshot, sb))
    shape_snapshot = result_snapshot.get("report_shape", "")

    print(f"  Question: 'show me current open pipeline'")
    print(f"  Report shape: {shape_snapshot}")

    assert shape_snapshot == "snapshot", \
        f"Snapshot question should use 'snapshot' shape, got: {shape_snapshot}"

    print(f"  ✓ Snapshot question → snapshot shape")

    # Movement question
    params_movement = {
        "time_window": params["time_window"],
        "question": "how did pipeline change this week"
    }

    result_movement = asyncio.run(query_waterfall(params_movement, sb))
    shape_movement = result_movement.get("report_shape", "")

    print(f"  Question: 'how did pipeline change this week'")
    print(f"  Report shape: {shape_movement}")

    assert shape_movement == "trend", \
        f"Movement question should use 'trend' shape, got: {shape_movement}"

    print(f"  ✓ Movement question → trend shape")
    print()

    # Test 4: Both pieces always computed
    print("[TEST 4] Both pipeline_summary and waterfall always computed")

    assert "pipeline_summary" in result, "Missing pipeline_summary"
    assert "waterfall" in result, "Missing waterfall"
    assert result["pipeline_summary"] is not None, "pipeline_summary is None"
    assert result["waterfall"] is not None, "waterfall is None"

    print(f"  ✓ Both pieces present regardless of question framing")
    print()

    print("="*80)
    print("Results: All tests passed!")
    print("="*80)

if __name__ == "__main__":
    test_pipeline_summary()
