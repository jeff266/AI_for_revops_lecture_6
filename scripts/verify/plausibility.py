#!/usr/bin/env python3
"""
Plausibility verification: Deterministic assertions on analytical outputs.

Catches the class of failure that produces a confident wrong number instead of
a crash. Examples from GrowthBook's history:
- Conversion rate 147% (missing denominator filter)
- Win rate -23% (signed integer underflow on lost count)
- Cycle time 0 days (datetime parsing bug)
- Qualified cohort 450, Won cohort 612 (stage filter inverted)
- Pipeline value $2.3M, sum of stages $1.1M (double-counting)

Verdict:
- PASS: All assertions hold
- FAIL: Any assertion violated
- INCONCLUSIVE: Insufficient data to evaluate
"""

import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import load_client_config


def check_supabase_analytics():
    """Run plausibility checks on Supabase analytical tables."""
    try:
        from supabase_client import get_client, select_all
        sb = get_client()

        violations = []

        # Check 1: Conversion rates should be 0-100%
        conversions = select_all(sb, 'stage_conversions', columns='from_stage,to_stage,conversion_rate')
        for conv in conversions:
            rate = conv.get('conversion_rate', 0)
            if rate < 0 or rate > 1:
                violations.append(
                    f"Conversion {conv['from_stage']}→{conv['to_stage']}: rate={rate:.1%} (out of bounds)"
                )

        # Check 2: Win rate should be 0-100%
        snapshots = select_all(sb, 'deal_snapshots', columns='win_rate')
        for snap in snapshots:
            rate = snap.get('win_rate', 0)
            if rate is not None and (rate < 0 or rate > 1):
                violations.append(f"Win rate {rate:.1%} out of bounds (0-100%)")

        # Check 3: Cycle time should be non-negative
        snapshots_ct = select_all(sb, 'deal_snapshots', columns='avg_cycle_time_days')
        for snap in snapshots_ct:
            days = snap.get('avg_cycle_time_days')
            if days is not None and days < 0:
                violations.append(f"Cycle time {days} days is negative")

        # Check 4: Counts should be non-negative
        snapshots_counts = select_all(sb, 'deal_snapshots',
                                      columns='total_deals,qualified_deals,won_deals,lost_deals')
        for snap in snapshots_counts:
            for field in ['total_deals', 'qualified_deals', 'won_deals', 'lost_deals']:
                count = snap.get(field)
                if count is not None and count < 0:
                    violations.append(f"{field}={count} is negative")

        # Check 5: Subset should not exceed superset
        for snap in snapshots_counts:
            total = snap.get('total_deals', 0) or 0
            qualified = snap.get('qualified_deals', 0) or 0
            won = snap.get('won_deals', 0) or 0
            lost = snap.get('lost_deals', 0) or 0

            if qualified > total:
                violations.append(f"Qualified deals ({qualified}) > total deals ({total})")
            if won > qualified:
                violations.append(f"Won deals ({won}) > qualified deals ({qualified})")
            if won > total:
                violations.append(f"Won deals ({won}) > total deals ({total})")
            if lost > total:
                violations.append(f"Lost deals ({lost}) > total deals ({total})")

        # Check 6: Waterfall cohorts should not increase downstream
        waterfall = select_all(sb, 'waterfall_snapshots',
                               columns='snapshot_date,created_count,qualified_count,won_count,lost_count',
                               order='snapshot_date.desc',
                               limit=1)
        if waterfall:
            w = waterfall[0]
            created = w.get('created_count', 0) or 0
            qualified = w.get('qualified_count', 0) or 0
            won = w.get('won_count', 0) or 0
            lost = w.get('lost_count', 0) or 0

            if qualified > created:
                violations.append(
                    f"Waterfall: qualified ({qualified}) > created ({created})"
                )
            if won > qualified:
                violations.append(
                    f"Waterfall: won ({won}) > qualified ({qualified})"
                )
            if (won + lost) > qualified:
                violations.append(
                    f"Waterfall: won+lost ({won + lost}) > qualified ({qualified})"
                )

        return violations

    except Exception as e:
        return [f"Supabase check failed: {e}"]


def check_deal_index():
    """Run plausibility checks on deal index."""
    import json

    violations = []

    index_path = Path(__file__).parent.parent.parent / 'memory' / 'deals' / 'index.json'
    if not index_path.exists():
        return [f"Deal index not found at {index_path}"]

    try:
        with open(index_path) as f:
            deals = json.load(f)

        if not isinstance(deals, list):
            violations.append(f"Deal index is not a list (got {type(deals).__name__})")
            return violations

        # Check: All deals should have required fields
        for i, deal in enumerate(deals):
            if not deal.get('deal_id'):
                violations.append(f"Deal {i}: missing deal_id")
            if not deal.get('company_name') and not deal.get('deal_name'):
                violations.append(f"Deal {i}: missing both company_name and deal_name")

        # Check: deal_id should be unique
        deal_ids = [d.get('deal_id') for d in deals if d.get('deal_id')]
        if len(deal_ids) != len(set(deal_ids)):
            duplicates = len(deal_ids) - len(set(deal_ids))
            violations.append(f"Deal index has {duplicates} duplicate deal_id values")

    except json.JSONDecodeError as e:
        violations.append(f"Deal index JSON parse error: {e}")
    except Exception as e:
        violations.append(f"Deal index check failed: {e}")

    return violations


def render_verdict(all_violations):
    """Determine pass/fail based on violations."""
    if not all_violations:
        return 'PASS', 'All plausibility checks passed'

    # Group violations by source
    violation_summary = '\n  - '.join(all_violations)
    return 'FAIL', f"{len(all_violations)} violation(s) found:\n  - {violation_summary}"


def main():
    """Run plausibility verification check."""
    print("=" * 70)
    print("PLAUSIBILITY VERIFICATION")
    print("=" * 70)
    print("\nDeterministic assertions on analytical outputs.")
    print("Catches confident wrong numbers instead of crashes.\n")

    print("Running checks...")

    all_violations = []

    # Check Supabase analytics
    print("  - Checking Supabase analytics...")
    supabase_violations = check_supabase_analytics()
    all_violations.extend(supabase_violations)

    # Check deal index
    print("  - Checking deal index...")
    index_violations = check_deal_index()
    all_violations.extend(index_violations)

    # Verdict
    verdict, reason = render_verdict(all_violations)
    print(f"\n{'=' * 70}")
    print(f"VERDICT: {verdict}")
    print(f"REASON:  {reason}")
    print("=" * 70)

    return 0 if verdict == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
