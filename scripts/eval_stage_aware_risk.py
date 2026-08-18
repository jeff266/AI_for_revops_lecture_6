#!/usr/bin/env python3
"""
Eval: Stage-aware deal risk methodology (Phase G.10 Fix B).

Tests that:
1. Discovery deal with EB=0 but Champion=5 NOT flagged (EB not required yet)
2. Discovery deal with Champion=0 IS flagged with stage-aware reason
3. Proposal deal with EB=3 IS flagged (EB required at Proposal→Negotiating)
4. Closed Won/excluded stages produce empty requirements, never flagged
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_stage_aware_risk():
    """Test stage-aware risk determination."""
    import asyncio
    from api.handlers import query_deals_at_risk
    from api.stage_requirements import get_requirements_for_stage

    print("="*80)
    print("PHASE G.10 STAGE-AWARE RISK METHODOLOGY")
    print("="*80)
    print()

    # Test stage requirements loading first
    print("[SETUP] Verify stage requirements from config")

    discovery_reqs = get_requirements_for_stage("appointmentscheduled")
    print(f"  Discovery requirements: {discovery_reqs}")
    assert "pain" in discovery_reqs, "Discovery should require pain"
    assert "champion" in discovery_reqs, "Discovery should require champion"
    assert discovery_reqs["champion"] == 4, "Discovery champion threshold should be 4"

    scoping_reqs = get_requirements_for_stage("qualifiedtobuy")
    print(f"  Scoping requirements: {scoping_reqs}")
    assert "economic_buyer" in scoping_reqs, "Scoping should require economic_buyer"
    assert scoping_reqs["economic_buyer"] == 6, "Scoping EB threshold should be 6"

    tech_eval_reqs = get_requirements_for_stage("presentationscheduled")
    print(f"  Tech Eval requirements: {tech_eval_reqs}")
    assert len(tech_eval_reqs) >= 6, "Tech Eval should require most components"

    print("  ✓ Stage requirements loaded from config")
    print()

    # Mock Supabase client
    class MockSupabase:
        def __init__(self, analyses_data, deals_data):
            self.analyses_data = analyses_data
            self.deals_data = deals_data

        def table(self, name):
            self.current_table = name
            return self

        def select(self, columns):
            self.current_columns = columns
            return self

        def eq(self, col, val):
            return self

        def gte(self, col, val):
            return self

        def in_(self, col, values):
            return self

        def range(self, start, end):
            return self

        def execute(self):
            class Result:
                def __init__(self, data):
                    self.data = data

            if self.current_table == "analyses":
                return Result(self.analyses_data)
            elif self.current_table == "deals":
                return Result(self.deals_data)
            return Result([])

    # Test 1: Discovery deal with EB=0 but Champion=5 NOT flagged
    print("[TEST 1] Discovery deal with EB=0 but Champion=5 NOT flagged")
    print("         (EB not required until Scoping→Proposal)")

    analyses_t1 = [{
        "deal_id": "deal_discovery_ok",
        "company_name": "USIM",
        "overall_score": 45,
        "champion_score": 5,  # Meets Discovery requirement (4+)
        "economic_buyer_score": 0,  # Below threshold but NOT required yet
        "pain_score": 6,
        "metrics_score": 0,
        "decision_criteria_score": 0,
        "decision_process_score": 0,
        "competition_score": 0,
        "analyzed_at": "2026-08-17T10:00:00Z"
    }]

    deals_t1 = [{
        "deal_id": "deal_discovery_ok",
        "company_name": "USIM",
        "deal_value": 100000,
        "deal_status": "active",
        "stage": "appointmentscheduled"  # Discovery
    }]

    sb_t1 = MockSupabase(analyses_t1, deals_t1)
    params_t1 = {
        "time_window": {
            "start": "2026-08-10",
            "end": "2026-08-17",
            "label": "This Week"
        }
    }

    result_t1 = asyncio.run(query_deals_at_risk(params_t1, sb_t1))

    assert "deals_at_risk" in result_t1, "Missing deals_at_risk key"
    assert result_t1["total_at_risk"] == 0, \
        f"Discovery deal with EB=0 should NOT be flagged (got {result_t1['total_at_risk']} at-risk)"

    print("  ✓ Discovery deal with EB=0 but Champion=5 NOT flagged")
    print("  ✓ Confirms EB not required at Discovery stage")
    print()

    # Test 2: Discovery deal with Champion=0 IS flagged
    print("[TEST 2] Discovery deal with Champion=0 IS flagged")
    print("         (Champion IS required to advance from Discovery)")

    analyses_t2 = [{
        "deal_id": "deal_discovery_bad",
        "company_name": "Bad Champion Co",
        "overall_score": 30,
        "champion_score": 0,  # Below Discovery requirement (4)
        "economic_buyer_score": 0,
        "pain_score": 6,
        "metrics_score": 0,
        "decision_criteria_score": 0,
        "decision_process_score": 0,
        "competition_score": 0,
        "analyzed_at": "2026-08-17T10:00:00Z"
    }]

    deals_t2 = [{
        "deal_id": "deal_discovery_bad",
        "company_name": "Bad Champion Co",
        "deal_value": 50000,
        "deal_status": "active",
        "stage": "appointmentscheduled"  # Discovery
    }]

    sb_t2 = MockSupabase(analyses_t2, deals_t2)
    params_t2 = {
        "time_window": {
            "start": "2026-08-10",
            "end": "2026-08-17",
            "label": "This Week"
        }
    }

    result_t2 = asyncio.run(query_deals_at_risk(params_t2, sb_t2))

    assert result_t2["total_at_risk"] == 1, \
        f"Discovery deal with Champion=0 should be flagged (got {result_t2['total_at_risk']})"

    flagged_deal = result_t2["deals_at_risk"][0]
    assert "Champion" in " ".join(flagged_deal["risk_flags"]), \
        "Risk flags should mention Champion specifically"
    assert "Discovery" in " ".join(flagged_deal["risk_flags"]), \
        "Risk flags should name the current stage"
    assert "Economic Buyer" not in " ".join(flagged_deal["risk_flags"]), \
        "Risk flags should NOT mention EB (not required at Discovery)"

    print(f"  ✓ Discovery deal with Champion=0 IS flagged")
    print(f"  ✓ Risk reason: {flagged_deal['risk_flags'][0]}")
    print(f"  ✓ Mentions Champion and Discovery stage, not EB")
    print()

    # Test 3: Proposal deal with EB=3 IS flagged
    print("[TEST 3] Proposal (Tech Eval) deal with EB=3 IS flagged")
    print("         (EB required at Tech Eval→Negotiating)")

    analyses_t3 = [{
        "deal_id": "deal_proposal_eb_low",
        "company_name": "Low EB Corp",
        "overall_score": 55,
        "champion_score": 7,
        "economic_buyer_score": 3,  # Below Tech Eval requirement (6)
        "pain_score": 7,
        "metrics_score": 7,
        "decision_criteria_score": 6,
        "decision_process_score": 7,
        "competition_score": 6,
        "analyzed_at": "2026-08-17T10:00:00Z"
    }]

    deals_t3 = [{
        "deal_id": "deal_proposal_eb_low",
        "company_name": "Low EB Corp",
        "deal_value": 200000,
        "deal_status": "active",
        "stage": "presentationscheduled"  # Tech Eval (Proposal)
    }]

    sb_t3 = MockSupabase(analyses_t3, deals_t3)
    params_t3 = {
        "time_window": {
            "start": "2026-08-10",
            "end": "2026-08-17",
            "label": "This Week"
        }
    }

    result_t3 = asyncio.run(query_deals_at_risk(params_t3, sb_t3))

    assert result_t3["total_at_risk"] == 1, \
        f"Tech Eval deal with EB=3 should be flagged (got {result_t3['total_at_risk']})"

    flagged_deal_t3 = result_t3["deals_at_risk"][0]
    risk_text = " ".join(flagged_deal_t3["risk_flags"])
    assert "Economic Buyer" in risk_text, \
        "Risk flags should mention Economic Buyer"
    assert "3/10" in risk_text, \
        "Risk flags should show actual score"
    assert "6+" in risk_text, \
        "Risk flags should show required threshold"

    print(f"  ✓ Tech Eval deal with EB=3 IS flagged")
    print(f"  ✓ Risk reason: {flagged_deal_t3['risk_flags'][0]}")
    print(f"  ✓ Shows score, threshold, and stage context")
    print()

    # Test 4: Closed Won stage produces empty requirements
    print("[TEST 4] Closed Won deal has empty requirements, never flagged")

    analyses_t4 = [{
        "deal_id": "deal_won",
        "company_name": "Won Deal Inc",
        "overall_score": 30,  # Low score, but deal is won
        "champion_score": 2,
        "economic_buyer_score": 2,
        "pain_score": 2,
        "metrics_score": 2,
        "decision_criteria_score": 2,
        "decision_process_score": 2,
        "competition_score": 2,
        "analyzed_at": "2026-08-17T10:00:00Z"
    }]

    deals_t4 = [{
        "deal_id": "deal_won",
        "company_name": "Won Deal Inc",
        "deal_value": 300000,
        "deal_status": "active",
        "stage": "closedwon"  # Closed Won
    }]

    sb_t4 = MockSupabase(analyses_t4, deals_t4)
    params_t4 = {
        "time_window": {
            "start": "2026-08-10",
            "end": "2026-08-17",
            "label": "This Week"
        }
    }

    result_t4 = asyncio.run(query_deals_at_risk(params_t4, sb_t4))

    # Verify Closed Won returns empty requirements
    won_reqs = get_requirements_for_stage("closedwon")
    assert won_reqs == {}, "Closed Won should have empty requirements"

    # Verify deal not flagged
    assert result_t4["total_at_risk"] == 0, \
        "Closed Won deal should never be flagged (terminal stage)"

    print(f"  ✓ Closed Won stage returns empty requirements: {won_reqs}")
    print(f"  ✓ Closed Won deal NOT flagged despite low scores")
    print()

    # Test 5: Excluded stage (Meeting Set) has empty requirements
    print("[TEST 5] Excluded stage (Meeting Set) has empty requirements")

    excluded_reqs = get_requirements_for_stage("79653122")  # Meeting Set
    assert excluded_reqs == {}, \
        "Excluded stage (Meeting Set) should have empty requirements"

    print(f"  ✓ Meeting Set (exclude_from_analysis=true) returns: {excluded_reqs}")
    print()

    print("="*80)
    print("Results: All tests passed!")
    print("="*80)

if __name__ == "__main__":
    test_stage_aware_risk()
