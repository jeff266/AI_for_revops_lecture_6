#!/usr/bin/env python3
"""
CRM crosscheck: Compare agent's pipeline counts against CRM and explain the difference.

GrowthBook's 78-vs-44 was a scope difference (agent used last 90 days, CRM showed
all-time), not a bug, but nobody could tell until it was reconciled explicitly.

This check:
1. Counts deals in memory/deals/index.json (agent's view)
2. Counts deals from HubSpot API (CRM's view)
3. Reports the difference with observable causes:
   - Close-date filter (agent excludes deals closed > N days ago)
   - Excluded stages (agent skips stages marked exclude_from_analysis)
   - Pipeline scope (agent may focus on primary pipeline only)

Verdict:
- PASS: Counts match within tolerance
- FAIL: Difference unexplained by observable filters
- INCONCLUSIVE: CRM unavailable or insufficient data
"""

import sys
from pathlib import Path
import json
from datetime import datetime, timedelta

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import load_client_config, get_pipeline_config


def load_deal_index():
    """Load deals from memory/deals/index.json."""
    index_path = Path(__file__).parent.parent.parent / 'memory' / 'deals' / 'index.json'
    if not index_path.exists():
        return []
    with open(index_path) as f:
        return json.load(f)


def get_crm_deal_count():
    """Get deal count directly from HubSpot API."""
    try:
        from adapters.crm.hubspot import HubSpotDealsClient
        hs = HubSpotDealsClient()

        # Get all deals (no filters)
        all_deals = hs._fetch_all_deals(properties=['dealstage', 'pipeline', 'closedate'])

        return all_deals
    except Exception as e:
        print(f"   ⚠️  HubSpot API unavailable: {e}")
        return None


def analyze_difference(agent_deals, crm_deals, config):
    """Analyze difference between agent and CRM counts."""
    if crm_deals is None:
        return None

    agent_count = len(agent_deals)
    crm_count = len(crm_deals)
    difference = crm_count - agent_count

    # Build explanation
    explanation = []

    # Check 1: Close-date filter
    call_lookback_days = config.get('etl', {}).get('call_lookback_days', 90)
    cutoff_date = datetime.now() - timedelta(days=call_lookback_days)

    # Count CRM deals outside lookback window
    old_deals = 0
    for deal in crm_deals:
        closedate_str = deal.get('properties', {}).get('closedate')
        if closedate_str:
            try:
                closedate = datetime.fromisoformat(closedate_str.replace('Z', '+00:00'))
                if closedate < cutoff_date:
                    old_deals += 1
            except Exception:
                pass

    if old_deals > 0:
        explanation.append(f"{old_deals} deals closed before {call_lookback_days}-day lookback window")

    # Check 2: Excluded stages
    pipeline_config = get_pipeline_config(config=config)
    excluded_stages = [s['id'] for s in pipeline_config.get('stages', [])
                      if s.get('exclude_from_analysis')]

    if excluded_stages:
        excluded_count = sum(
            1 for d in crm_deals
            if d.get('properties', {}).get('dealstage') in excluded_stages
        )
        if excluded_count > 0:
            explanation.append(f"{excluded_count} deals in excluded stages ({', '.join(excluded_stages)})")

    # Check 3: Pipeline scope
    primary_pipeline = pipeline_config.get('id')
    if primary_pipeline:
        other_pipeline_count = sum(
            1 for d in crm_deals
            if d.get('properties', {}).get('pipeline') != primary_pipeline
        )
        if other_pipeline_count > 0:
            explanation.append(f"{other_pipeline_count} deals in non-primary pipelines")

    return {
        'agent_count': agent_count,
        'crm_count': crm_count,
        'difference': difference,
        'explanation': explanation
    }


def render_verdict(analysis, config):
    """Determine pass/fail based on count reconciliation."""
    if analysis is None:
        return 'INCONCLUSIVE', 'CRM unavailable'

    tolerance = config.get('quality_thresholds', {}).get('crm_crosscheck', {}).get('tolerance', 0.05)
    agent_count = analysis['agent_count']
    crm_count = analysis['crm_count']

    if crm_count == 0:
        return 'INCONCLUSIVE', 'No deals in CRM'

    diff_pct = abs(analysis['difference']) / crm_count

    if diff_pct <= tolerance:
        return 'PASS', f"Counts match within {tolerance:.0%} tolerance (agent={agent_count}, CRM={crm_count})"

    # Check if difference is explained
    explained_count = sum(int(e.split()[0]) for e in analysis['explanation'] if e.split()[0].isdigit())
    unexplained = abs(analysis['difference']) - explained_count

    if unexplained <= (crm_count * tolerance):
        explanation_str = '; '.join(analysis['explanation'])
        return 'PASS', f"Difference explained by filters: {explanation_str}"

    explanation_str = '; '.join(analysis['explanation']) if analysis['explanation'] else 'No observable cause'
    return 'FAIL', f"Unexplained difference of {unexplained} deals ({diff_pct:.1%}). {explanation_str}"


def main():
    """Run CRM crosscheck verification."""
    print("=" * 70)
    print("CRM CROSSCHECK VERIFICATION")
    print("=" * 70)
    print("\nCompare agent's pipeline counts against CRM and explain the difference.\n")

    print("Loading data...")
    config = load_client_config()
    agent_deals = load_deal_index()
    crm_deals = get_crm_deal_count()

    if crm_deals is None:
        print("\n❌ INCONCLUSIVE: CRM unavailable\n")
        return 1

    # Analyze difference
    analysis = analyze_difference(agent_deals, crm_deals, config)

    # Report counts
    print(f"\nDeal Counts:")
    print(f"  Agent (memory/deals/index.json): {analysis['agent_count']}")
    print(f"  CRM (HubSpot API):               {analysis['crm_count']}")
    print(f"  Difference:                      {analysis['difference']:+d}")

    # Report explanation
    if analysis['explanation']:
        print(f"\nExplained by:")
        for reason in analysis['explanation']:
            print(f"  - {reason}")

    # Verdict
    verdict, reason = render_verdict(analysis, config)
    print(f"\n{'=' * 70}")
    print(f"VERDICT: {verdict}")
    print(f"REASON:  {reason}")
    print("=" * 70)

    return 0 if verdict == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
