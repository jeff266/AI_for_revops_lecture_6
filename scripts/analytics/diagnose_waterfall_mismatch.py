#!/usr/bin/env python3
"""
Diagnose waterfall reconciliation mismatches between snapshots.

Identifies deals that appear in the ending snapshot as active but weren't
active in the beginning snapshot, and vice versa. These cause the waterfall
math to not balance when snapshots are built with different classification rules.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client
from adapters.storage.supabase import select_all


def main():
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Find the two most recent snapshot dates
    snapshots = sb.table('deals_snapshot')\
        .select('snapshot_date')\
        .order('snapshot_date', desc=True)\
        .limit(2)\
        .execute().data

    if len(snapshots) < 2:
        print("Need at least 2 snapshots for comparison")
        return

    new_date = snapshots[0]['snapshot_date']
    prev_date = snapshots[1]['snapshot_date']

    print(f"\n{'='*70}")
    print(f"Waterfall Reconciliation Diagnostic: {prev_date} → {new_date}")
    print(f"{'='*70}\n")

    # Load both snapshots
    new_snap = {r['deal_id']: r for r in select_all(
        sb, 'deals_snapshot', '*',
        filters=[('eq', 'snapshot_date', new_date)]
    )}

    prev_snap = {r['deal_id']: r for r in select_all(
        sb, 'deals_snapshot', '*',
        filters=[('eq', 'snapshot_date', prev_date)]
    )}

    # Query 1: Deals appearing as active in new snapshot that weren't active in prev
    print("=== Deals appearing as ACTIVE in ending snapshot ===")
    print("=== that were NOT active in beginning snapshot ===")
    print("(These inflate ending_value without being captured as movements)\n")

    appeared_active = []
    for deal_id, new_deal in new_snap.items():
        if new_deal.get('deal_status') == 'active':
            prev_deal = prev_snap.get(deal_id)
            if not prev_deal or prev_deal.get('deal_status') != 'active':
                appeared_active.append({
                    'deal_id': deal_id,
                    'company_name': new_deal.get('company_name', ''),
                    'deal_value': new_deal.get('deal_value') or 0,
                    'prev_status': prev_deal.get('deal_status', 'NEW') if prev_deal else 'NEW',
                    'end_status': new_deal.get('deal_status'),
                    'pipeline_id': new_deal.get('pipeline_id', 'default')
                })

    appeared_active.sort(key=lambda x: x['deal_value'], reverse=True)

    by_pipeline = {}
    for deal in appeared_active[:20]:
        print(f"{deal['company_name'][:30]:30s} "
              f"${deal['deal_value']:>12,.0f}  "
              f"{deal['prev_status']:10s} → {deal['end_status']:10s}  "
              f"Pipeline: {deal['pipeline_id']}")

        pid = deal['pipeline_id']
        if pid not in by_pipeline:
            by_pipeline[pid] = {'count': 0, 'value': 0}
        by_pipeline[pid]['count'] += 1
        by_pipeline[pid]['value'] += deal['deal_value']

    print(f"\nShowing top 20 of {len(appeared_active)} total deals")
    print("\nBy pipeline:")
    for pid, stats in by_pipeline.items():
        print(f"  {pid}: {stats['count']} deals, ${stats['value']:,.0f}")

    # Query 2: Deals that were active in prev but not in new
    print(f"\n{'='*70}")
    print("=== Deals that were ACTIVE in beginning snapshot ===")
    print("=== but are NOT active in ending snapshot ===")
    print("(These deflate ending_value without being captured as movements)\n")

    disappeared_active = []
    for deal_id, prev_deal in prev_snap.items():
        if prev_deal.get('deal_status') == 'active':
            new_deal = new_snap.get(deal_id)
            if not new_deal or new_deal.get('deal_status') != 'active':
                disappeared_active.append({
                    'deal_id': deal_id,
                    'company_name': prev_deal.get('company_name', ''),
                    'deal_value': prev_deal.get('deal_value') or 0,
                    'prev_status': prev_deal.get('deal_status'),
                    'end_status': new_deal.get('deal_status', 'REMOVED') if new_deal else 'REMOVED',
                    'pipeline_id': prev_deal.get('pipeline_id', 'default')
                })

    disappeared_active.sort(key=lambda x: x['deal_value'], reverse=True)

    by_pipeline = {}
    for deal in disappeared_active[:20]:
        print(f"{deal['company_name'][:30]:30s} "
              f"${deal['deal_value']:>12,.0f}  "
              f"{deal['prev_status']:10s} → {deal['end_status']:10s}  "
              f"Pipeline: {deal['pipeline_id']}")

        pid = deal['pipeline_id']
        if pid not in by_pipeline:
            by_pipeline[pid] = {'count': 0, 'value': 0}
        by_pipeline[pid]['count'] += 1
        by_pipeline[pid]['value'] += deal['deal_value']

    print(f"\nShowing top 20 of {len(disappeared_active)} total deals")
    print("\nBy pipeline:")
    for pid, stats in by_pipeline.items():
        print(f"  {pid}: {stats['count']} deals, ${stats['value']:,.0f}")

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}\n")

    print(f"Deals appearing as active: {len(appeared_active)}")
    print(f"Deals disappearing from active: {len(disappeared_active)}")
    print(f"\nNet effect on active count: {len(appeared_active) - len(disappeared_active)}")

    total_appeared = sum(d['deal_value'] for d in appeared_active)
    total_disappeared = sum(d['deal_value'] for d in disappeared_active)
    print(f"\nValue appeared: ${total_appeared:,.0f}")
    print(f"Value disappeared: ${total_disappeared:,.0f}")
    print(f"Net value impact: ${total_appeared - total_disappeared:,.0f}")

    print("\nNote: If these snapshots were built with different classification rules")
    print("(e.g., different is_won_stage logic or stage_order values), the waterfall")
    print("will not reconcile. This is expected for Aug 9 → Aug 10 comparison.")
    print("Clean reconciliation will begin with snapshots built after the fix.\n")


if __name__ == '__main__':
    main()
