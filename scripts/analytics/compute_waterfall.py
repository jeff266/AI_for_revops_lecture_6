#!/usr/bin/env python3
"""
Computes week-over-week pipeline waterfall from deals_snapshot.
Uses the two most recent snapshot dates (not "exactly 7 days
prior" — uses nearest prior to survive missed crons).
Writes to waterfall_weekly table.

IMPORTANT: This tracks the QUALIFIED pipeline only. Membership is point-in-time
(defect 5): a deal counts for a week only once its qualified_date — the immutable
event when it first crossed the threshold — has occurred on or before that week's
snapshot date. It is NOT gated on the current-state highest_stage_order_reached.
Meeting Set stage deals (order 0-1) are excluded from beginning/ending values
and all waterfall movements to match HubSpot's qualified pipeline definition.

Usage:
    python scripts/analytics/compute_waterfall.py              # Prospective mode (latest week)
    python scripts/analytics/compute_waterfall.py --backfill   # Historical mode (all weeks)
"""

import os
import sys
import json
import argparse
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def _qualified_as_of(qual_map, deal_id, as_of_iso):
    """Point-in-time qualified-pipeline membership (defect 5).

    A deal is in the qualified pipeline as of a date only once its
    qualified_date (the immutable event when it first crossed the qualification
    threshold — seeded from HubSpot dealstage history) has occurred on or
    before that date. Uses the event timestamp, NEVER the current-state
    highest_stage_order_reached, which is the stage the deal has reached BY NOW
    and would count a not-yet-qualified deal as already in an earlier week's
    pipeline.
    """
    qd = (qual_map.get(deal_id) or {}).get('qualified_date')
    if not qd:
        return False
    try:
        return date.fromisoformat(qd) <= date.fromisoformat(as_of_iso)
    except (ValueError, TypeError):
        return False


def main():
    parser = argparse.ArgumentParser(description='Compute pipeline waterfall')
    parser.add_argument('--backfill', action='store_true',
                       help='Backfill mode: compute waterfall for all historical snapshot pairs')
    args = parser.parse_args()

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    from supabase import create_client
    import sys
    sys.path.insert(0, str(REPO_ROOT / 'scripts'))
    from utils import load_client_config, get_fiscal_quarter, get_pipeline_config
    from adapters.storage.supabase import select_all
    from datetime import datetime

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    config = load_client_config()

    # Load qualification threshold — raises if not set (Gap 2)
    pipeline_cfg = get_pipeline_config(config=config)
    threshold = pipeline_cfg.get('qualified_stage_order')
    if threshold is None:
        raise ValueError(
            "qualified_stage_order not set in config/client.yaml\n"
            "This setting determines which stage counts as 'qualified' for waterfall analytics.\n"
            "Set qualified_stage_order on the primary pipeline in config/client.yaml.\n"
            "Example: pipelines:\n"
            "  - id: default\n"
            "    qualified_stage_order: 3  # stage order where deals become 'qualified'"
        )

    print(f"Qualification threshold (config): stage_order >= {threshold}; "
          f"membership is point-in-time via qualified_date")

    # Point-in-time qualified-pipeline membership (defect 5). qualified_date is
    # the IMMUTABLE event timestamp of when a deal first crossed the
    # qualification threshold (seed_qualification_history replays dealstage
    # history) — an event fact, like a won deal's close_date, NOT current state.
    # We deliberately do NOT read highest_stage_order_reached: that is the stage
    # the deal has reached BY NOW, and gating a historical week on it would
    # count a not-yet-qualified deal as already in that week's pipeline. Stage
    # exclusions come from the point-in-time snapshot; membership from the event.
    qual_rows = select_all(sb, 'deals',
                          columns='deal_id, qualified_date')
    qual_map = {
        row['deal_id']: {'qualified_date': row.get('qualified_date')}
        for row in qual_rows
    }
    print(f"Loaded qualification (event) data for {len(qual_map)} deals")

    if args.backfill:
        # Backfill mode: get all snapshot dates and compute waterfalls for all pairs
        print()
        print("=" * 70)
        print("BACKFILL MODE: Computing waterfall for all historical snapshot pairs")
        print("=" * 70)
        print()

        # Get ONLY dates where ALL snapshots are backfilled
        # (excludes overlap dates that have prospective rows)
        all_snapshots = select_all(sb, 'deals_snapshot',
                                   columns='snapshot_date,snapshot_source')
        from collections import defaultdict
        date_sources = defaultdict(set)
        for row in all_snapshots:
            date_sources[row['snapshot_date']].add(row['snapshot_source'])

        backfill_dates = sorted(
            d for d, sources in date_sources.items()
            if sources == {'backfilled'}   # ONLY pure backfill dates
        )

        if len(backfill_dates) < 2:
            print("Insufficient backfilled snapshot history — skipping")
            return

        print(f"Found {len(backfill_dates)} backfilled snapshot dates")
        print(f"  Oldest: {backfill_dates[0]}")
        print(f"  Newest: {backfill_dates[-1]}")
        print()
        print(f"Will compute {len(backfill_dates) - 1} weekly waterfalls")
        print()

        # Compute waterfall for each consecutive pair
        for i in range(len(backfill_dates) - 1):
            prev_date = backfill_dates[i]
            new_date = backfill_dates[i + 1]

            print(f"[{i + 1}/{len(backfill_dates) - 1}] Computing {new_date} vs {prev_date}")

            compute_waterfall_for_dates(
                sb, config, qual_map, threshold,
                prev_date, new_date,
                computed_source='backfill'
            )
            print()

        print("=" * 70)
        print("✓ BACKFILL COMPLETE")
        print("=" * 70)

    else:
        # Prospective mode: compute waterfall for the two most recent snapshots
        def latest_date_before(sb, before=None):
            q = sb.table('deals_snapshot')\
                .select('snapshot_date')\
                .order('snapshot_date', desc=True)\
                .limit(1)
            if before:
                q = q.lt('snapshot_date', before)
            rows = q.execute().data or []
            return rows[0]['snapshot_date'] if rows else None

        new_date  = latest_date_before(sb)
        prev_date = latest_date_before(sb, before=new_date)

        if not new_date or not prev_date:
            print("Insufficient snapshot history — need at least 2 "
                  "snapshot dates. Skipping waterfall computation.")
            return

        print(f"Comparing {new_date} vs {prev_date}")

        compute_waterfall_for_dates(
            sb, config, qual_map, threshold,
            prev_date, new_date,
            computed_source='prospective'
        )


def compute_waterfall_for_dates(sb, config, qual_map, threshold, prev_date, new_date, computed_source='prospective'):
    """
    Compute waterfall between two snapshot dates.

    Args:
        sb: Supabase client
        config: Client configuration
        qual_map: {deal_id: {'qualified_date': ...}} — point-in-time membership
        threshold: Qualification stage_order threshold
        prev_date: Previous snapshot date (str)
        new_date: New snapshot date (str)
        computed_source: 'prospective' or 'backfill'
    """
    from utils import get_fiscal_quarter
    from adapters.storage.supabase import select_all
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))  # analytics/ for null_propagation
    from null_propagation import null_propagate

    # Null-propagation threshold (defect 4). A deal whose deal_value is None is
    # EXCLUDED from every dollar sum and COUNTED — never coalesced to 0.0, which
    # would re-fabricate the number Phase 2b removed.
    max_null_pct = float(config.get('forecast_analysis', {})
                         .get('max_null_value_pct', 5))

    def _deal_value(row):
        """deal_value as float, or None when unknown — NEVER 0-coalesced."""
        if not row:
            return None
        v = row.get('deal_value')
        return float(v) if v is not None else None

    # Load both snapshots (paginated)
    def load_snapshot(snap_date: str) -> dict:
        rows = select_all(
            sb, 'deals_snapshot', '*',
            filters=[('eq', 'snapshot_date', snap_date)]
        )
        return {r['deal_id']: r for r in rows}

    new_snap = load_snapshot(new_date)
    prev_snap = load_snapshot(prev_date)

    # Get current fiscal quarter boundaries
    q_start, q_end, q_label = get_fiscal_quarter(date.fromisoformat(new_date), config)
    if computed_source == 'prospective':
        print(f"  Fiscal quarter: {q_label} ({q_start} to {q_end})")

    # Diff into waterfall categories per pipeline
    from collections import defaultdict
    pipeline_waterfalls = defaultdict(lambda: {
        'beginning_value': 0.0,
        'ending_value': 0.0,
        'new_pipeline_value': 0.0,
        'newly_qualified_value': 0.0,
        'moved_forward_value': 0.0,
        'moved_backward_value': 0.0,
        'won_value': 0.0,
        'lost_value': 0.0,
        'pulled_in_value': 0.0,
        'pushed_out_value': 0.0,
        'arr_change_value': 0.0,
        'net_change': 0.0,
        'deals_created_count': 0,
        'deals_qualified_count': 0,
        'null_value_excluded_count': 0,   # deals dropped from dollar sums (unknown value)
        'details': [],
    })

    # Beginning/ending values (qualified pipeline only), null-propagated:
    # collect per-pipeline value lists (None for unknown), then exclude-and-
    # count via null_propagate rather than coalescing null -> 0.
    from collections import defaultdict as _dd
    begin_values, end_values = _dd(list), _dd(list)
    for deal_id, p in prev_snap.items():
        if (p.get('deal_status') == 'active' and
            _qualified_as_of(qual_map, deal_id, prev_date)):
            begin_values[p.get('pipeline_id', 'default')].append(_deal_value(p))
    for deal_id, n in new_snap.items():
        if (n.get('deal_status') == 'active' and
            _qualified_as_of(qual_map, deal_id, new_date)):
            end_values[n.get('pipeline_id', 'default')].append(_deal_value(n))

    for pid, vals in begin_values.items():
        npr = null_propagate(vals, max_null_pct)
        pipeline_waterfalls[pid]['beginning_value'] = npr['sum']  # excludes nulls, never 0-filled
        pipeline_waterfalls[pid]['beginning_null_excluded'] = npr['null_count']
        pipeline_waterfalls[pid]['beginning_dollar_basis_null'] = npr['basis_null']
    for pid, vals in end_values.items():
        npr = null_propagate(vals, max_null_pct)
        pipeline_waterfalls[pid]['ending_value'] = npr['sum']
        pipeline_waterfalls[pid]['ending_null_excluded'] = npr['null_count']
        pipeline_waterfalls[pid]['ending_dollar_basis_null'] = npr['basis_null']

    all_deal_ids = set(new_snap) | set(prev_snap)

    for deal_id in all_deal_ids:
        n = new_snap.get(deal_id)
        p = prev_snap.get(deal_id)

        # Skip deals not yet in the qualified pipeline as of this week (defect
        # 5: point-in-time via qualified_date, not the current high-water mark).
        qual_info = qual_map.get(deal_id, {})
        if not _qualified_as_of(qual_map, deal_id, new_date):
            continue

        pipeline_id = (n or p).get('pipeline_id', 'default')
        wf = pipeline_waterfalls[pipeline_id]
        # None when value is unknown — NEVER 0-coalesced. A dollar category adds
        # `value` only when known; an unknown-value deal is counted (count basis)
        # and tallied into null_value_excluded_count (dollar basis).
        value = _deal_value(n or p)
        value_known = value is not None
        if not value_known:
            wf['null_value_excluded_count'] += 1

        # Check if deal was newly qualified this week using qualified_date
        qualified_date_str = qual_info.get('qualified_date')
        newly_qualified_this_week = False
        if qualified_date_str:
            try:
                qualified_dt = date.fromisoformat(qualified_date_str)
                prev_dt = date.fromisoformat(prev_date)
                new_dt = date.fromisoformat(new_date)
                newly_qualified_this_week = prev_dt < qualified_dt <= new_dt
            except (ValueError, TypeError):
                pass

        if n and not p:
            # New deal created this week AND already qualified
            if value_known:
                wf['new_pipeline_value'] += value
            wf['deals_created_count'] += 1
            wf['details'].append({
                'deal_id': deal_id,
                'company_name': n.get('company_name', ''),
                'close_date': n.get('close_date'),
                'change_type': 'new',
                'value': value,
            })
        elif newly_qualified_this_week and p:
            # Deal existed before and crossed qualification threshold this week
            if value_known:
                wf['newly_qualified_value'] += value
            wf['deals_qualified_count'] += 1
            wf['details'].append({
                'deal_id': deal_id,
                'company_name': n.get('company_name', '') if n else p.get('company_name', ''),
                'close_date': n.get('close_date') if n else p.get('close_date'),
                'change_type': 'newly_qualified',
                'value': value,
                'qualified_date': qualified_date_str,
            })
        else:
            # Handle existing deals (may be None if deal only exists in one snapshot)
            n_order = n.get('stage_order', 0) or 0 if n else 0
            p_order = p.get('stage_order', 0) or 0 if p else 0
            n_status = n.get('deal_status', 'active') if n else 'active'
            p_status = p.get('deal_status', 'active') if p else 'active'

            # Parse close dates for fiscal quarter analysis
            n_close_raw = n.get('close_date') if n else None
            p_close_raw = p.get('close_date') if p else None

            try:
                n_close = date.fromisoformat(n_close_raw) if n_close_raw else None
            except (ValueError, TypeError):
                n_close = None

            try:
                p_close = date.fromisoformat(p_close_raw) if p_close_raw else None
            except (ValueError, TypeError):
                p_close = None

            # Detect all changes
            changes = []

            if n_status == 'won' and p_status != 'won':
                changes.append('won')
            elif n_status == 'lost' and p_status != 'lost':
                changes.append('lost')

            # Check pulled_in/pushed_out
            if n_close and p_close:
                n_in_quarter = q_start <= n_close <= q_end
                p_in_quarter = q_start <= p_close <= q_end

                if not p_in_quarter and n_in_quarter:
                    changes.append('pulled_in')
                elif p_in_quarter and not n_in_quarter:
                    changes.append('pushed_out')

            # Only compare stage movement for active deals.
            # Won/lost deals are already handled above; including
            # them in the stage diff produces false backward movement
            # when closed stage_order differs from prior snapshot.
            if n_status not in ('won', 'lost') and \
               p_status not in ('won', 'lost'):
                n_order_real = n_order if (n_order or 0) > 0 else None
                p_order_real = p_order if (p_order or 0) > 0 else None
                if n_order_real and p_order_real:
                    if n_order_real > p_order_real:
                        changes.append('moved_forward')
                    elif n_order_real < p_order_real:
                        changes.append('moved_backward')
                # Deals at order 0 (Meeting Set / pre-pipeline) are
                # not counted as stage movement — they haven't entered
                # the qualified pipeline yet.

            # Check ARR change — null-propagated: an unknown value on either
            # side is not a fabricated 0, so we do not manufacture an arr_change
            # from it. Only a real change between two KNOWN values counts.
            n_value = _deal_value(n)
            p_value = _deal_value(p)
            if n_value is not None and p_value is not None and n_value != p_value:
                changes.append('arr_change')

            # Apply value to highest precedence category
            precedence = ['won', 'lost', 'pulled_in', 'pushed_out', 'moved_forward', 'moved_backward', 'arr_change']
            primary_change = None
            for category in precedence:
                if category in changes:
                    primary_change = category
                    break

            # Update waterfall values — dollar categories only when the value
            # is known; an unknown-value deal is already counted in
            # null_value_excluded_count and must not become a fabricated 0.
            if value_known:
                if primary_change == 'won':
                    wf['won_value'] += value
                elif primary_change == 'lost':
                    wf['lost_value'] += value
                elif primary_change == 'pulled_in':
                    wf['pulled_in_value'] += value
                elif primary_change == 'pushed_out':
                    wf['pushed_out_value'] += value
                elif primary_change == 'moved_forward':
                    wf['moved_forward_value'] += value
                elif primary_change == 'moved_backward':
                    wf['moved_backward_value'] += value
                elif primary_change == 'arr_change':
                    wf['arr_change_value'] += value

            # Add to details with all relevant metadata
            if changes:
                detail = {
                    'deal_id': deal_id,
                    'company_name': n.get('company_name', '') if n else (p.get('company_name', '') if p else ''),
                    'close_date': n.get('close_date') if n else (p.get('close_date') if p else None),
                    'change_type': primary_change,
                    'value': value,
                }

                if 'moved_forward' in changes or 'moved_backward' in changes:
                    detail['from_order'] = p_order
                    detail['to_order'] = n_order

                if 'pulled_in' in changes or 'pushed_out' in changes:
                    detail['prev_close_date'] = p_close_raw
                    detail['new_close_date'] = n_close_raw

                if 'arr_change' in changes:
                    detail['prev_value'] = p_value
                    detail['new_value'] = n_value

                if len(changes) > 1:
                    detail['secondary_changes'] = [c for c in changes if c != primary_change]

                wf['details'].append(detail)

    for pipeline_id, wf in pipeline_waterfalls.items():
        # Surface the null-value exclusion in details (schema-safe: no new
        # column). A material fraction means the dollar figures understate the
        # pipeline because unknown-value deals were excluded, not zero-filled.
        excluded = wf.get('null_value_excluded_count', 0)
        begin_excl = wf.get('beginning_null_excluded', 0)
        end_excl = wf.get('ending_null_excluded', 0)
        if excluded or begin_excl or end_excl:
            wf['details'].insert(0, {
                'change_type': 'null_value_excluded_summary',
                'movement_null_value_excluded': excluded,
                'beginning_null_value_excluded': begin_excl,
                'ending_null_value_excluded': end_excl,
                'beginning_dollar_basis_null': wf.get('beginning_dollar_basis_null', False),
                'ending_dollar_basis_null': wf.get('ending_dollar_basis_null', False),
                'note': 'unknown-value deals excluded from dollar sums (not 0-filled); counts unaffected',
            })

        wf['net_change'] = (
            wf['new_pipeline_value']
            + wf['newly_qualified_value']
            + wf['moved_forward_value']
            - wf['moved_backward_value']
            - wf['won_value']
            - wf['lost_value']
        )

        # Reconciliation check: ending = beginning + net_change
        expected_ending = wf['beginning_value'] + wf['net_change']
        actual_ending = wf['ending_value']
        if abs(expected_ending - actual_ending) > 0.01:  # Allow for floating point errors
            print(f"  ⚠️  Reconciliation mismatch for {pipeline_id}:")
            print(f"      Expected ending: {expected_ending:.2f}")
            print(f"      Actual ending:   {actual_ending:.2f}")
            print(f"      Difference:      {actual_ending - expected_ending:.2f}")

        row = {
            'week_ending': new_date,
            'pipeline_id': pipeline_id,
            'beginning_value': wf['beginning_value'],
            'ending_value': wf['ending_value'],
            'new_pipeline_value': wf['new_pipeline_value'],
            'newly_qualified_value': wf['newly_qualified_value'],
            'moved_forward_value': wf['moved_forward_value'],
            'moved_backward_value': wf['moved_backward_value'],
            'won_value': wf['won_value'],
            'lost_value': wf['lost_value'],
            'pulled_in_value': wf['pulled_in_value'],
            'pushed_out_value': wf['pushed_out_value'],
            'arr_change_value': wf['arr_change_value'],
            'net_change': wf['net_change'],
            'deals_created_count': wf['deals_created_count'],
            'deals_qualified_count': wf['deals_qualified_count'],
            'details': json.dumps(wf['details']),
            'computed_source': computed_source,
        }

        if computed_source == 'backfill':
            existing = sb.table('waterfall_weekly')\
                .select('computed_source')\
                .eq('week_ending', new_date)\
                .eq('pipeline_id', pipeline_id)\
                .execute()
            if existing.data and existing.data[0].get(
                    'computed_source') == 'prospective':
                print(f"  Skipping {pipeline_id} {new_date} — "
                      f"prospective row exists")
                continue

        sb.table('waterfall_weekly').upsert(
            row, on_conflict='week_ending,pipeline_id'
        ).execute()

        if computed_source == 'prospective':
            print(f"\n{'='*70}")
            print(f"✓ Waterfall {new_date} / {pipeline_id} (QUALIFIED PIPELINE ONLY)")
            print(f"{'='*70}")
            print(f"Beginning Value:        ${wf['beginning_value']:>12,.0f}")
            print(f"")
            print(f"+ New Created:          ${wf['new_pipeline_value']:>12,.0f}  ({wf['deals_created_count']} deals)")
            print(f"+ Newly Qualified:      ${wf['newly_qualified_value']:>12,.0f}  ({wf['deals_qualified_count']} deals)")
            print(f"+ Moved Forward:        ${wf['moved_forward_value']:>12,.0f}")
            print(f"- Moved Backward:       ${wf['moved_backward_value']:>12,.0f}")
            print(f"- Won:                  ${wf['won_value']:>12,.0f}")
            print(f"- Lost:                 ${wf['lost_value']:>12,.0f}")
            print(f"")
            print(f"= Net Change:           ${wf['net_change']:>12,.0f}")
            print(f"")
            print(f"Ending Value:           ${wf['ending_value']:>12,.0f}")
            print(f"{'='*70}")

            # Reconciliation check
            calc_end = (wf['beginning_value'] + wf['new_pipeline_value'] +
                        wf['moved_forward_value'] - wf['moved_backward_value'] -
                        wf['won_value'] - wf['lost_value'])
            diff = abs(calc_end - wf['ending_value'])
            if diff > 1:
                print(f"⚠️  Reconciliation gap: ${diff:,.0f}")
                print(f"    This can occur when two snapshots were built")
                print(f"    with different deal_status classification rules")
                print(f"    (e.g. after a config change). Gap resolves")
                print(f"    naturally once both snapshots use the same config.")


if __name__ == '__main__':
    main()
