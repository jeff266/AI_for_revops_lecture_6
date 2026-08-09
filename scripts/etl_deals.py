#!/usr/bin/env python3
"""
ETL: HubSpot Deals API → Deal Index

Modes:
  --mode active (default): Fetches active deals only, writes to memory/deals/index.json and Supabase
  --mode history: Fetches ALL deals including closed, writes to Supabase only for CRO history queries

Auto-detects pipeline stages to exclude (closed won/lost, meeting set) in active mode.
"""
import json
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime
import re

# Add parent directory to path for imports
REPO_ROOT = Path(__file__).parent.parent
DEALS_DIR = REPO_ROOT / 'memory' / 'deals'
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from utils import slugify
from adapters import get_crm_adapter, get_storage_adapter

DEALS_DIR.mkdir(parents=True, exist_ok=True)

# Default exclusions — these are HubSpot universal defaults only.
# For your specific stage IDs, run: python scripts/discover_stages.py
# and update config/client.yaml with your actual stage IDs.
# Do NOT hardcode appointmentscheduled — it means different things
# in different HubSpot pipelines.

EXCLUDED_PIPELINES_DEFAULT = []
CLOSED_WON_STAGES_DEFAULT = ['closedwon']
CLOSED_LOST_STAGES_DEFAULT = ['closedlost']


def _excluded_stages_from_pipeline_config(pipelines: list) -> dict:
    """
    Derive the legacy excluded_stages return shape from the new
    pipeline.pipelines[] stage-order model (config/client.yaml).

    The new schema unifies what used to be two separate concepts
    (Meeting Set / Disqualified) under per-stage flags:
      - exclude_from_analysis alone  → 'meeting_set' (pre-discovery,
        still open — e.g. Meeting Set)
      - exclude_from_analysis + is_lost together → 'disqualified'
        (terminal — the config's RULE requires Disqualified-type
        stages to carry both flags, so deal_status still flips to
        'lost' via closed_lost below)
    The two output lists are mutually exclusive; a stage can't land in
    both. closed_won/closed_lost are independent of exclude_from_analysis
    — any is_won/is_lost stage always resolves deal_status, regardless
    of whether it's also excluded from active analysis. A pipeline
    flagged analyze: false contributes its ID to excluded_pipelines;
    its individual stages don't need to be enumerated since the
    pipeline-level exclusion already covers them.
    """
    meeting_set = []
    disqualified = []
    closed_won = []
    closed_lost = []
    excluded_pipelines = []

    for p in pipelines:
        if p.get('analyze') is False:
            pid = p.get('id')
            if pid:
                excluded_pipelines.append(pid)
            continue

        for stage in p.get('stages', []):
            sid = stage.get('id')
            if not sid:
                continue
            excludes = bool(stage.get('exclude_from_analysis'))
            lost = bool(stage.get('is_lost'))
            won = bool(stage.get('is_won'))

            if excludes and lost:
                disqualified.append(sid)
            elif excludes:
                meeting_set.append(sid)

            if won:
                closed_won.append(sid)
            if lost:
                closed_lost.append(sid)

    return {
        'meeting_set': meeting_set,
        'disqualified': disqualified,
        'closed_won': closed_won or CLOSED_WON_STAGES_DEFAULT,
        'closed_lost': closed_lost or CLOSED_LOST_STAGES_DEFAULT,
        'excluded_pipelines': excluded_pipelines,
    }


def get_excluded_stages() -> dict:
    """
    Load stage exclusions from config/client.yaml.

    Prefers the new pipeline.pipelines[] stage-order model — see
    _excluded_stages_from_pipeline_config(). Falls back to the legacy
    flat excluded_stages block for older forks that haven't migrated.
    If both shapes are present in the same file, the new shape wins —
    they describe the same underlying stages and must not drift apart.

    Returns the same 5-key shape either way so downstream callers
    (get_deal_status, get_meeting_set_stages, the active/history mode
    filters in main()) don't need to know which config shape is in use.
    """
    default_result = {
        'meeting_set': [],
        'disqualified': [],
        'closed_won': CLOSED_WON_STAGES_DEFAULT,
        'closed_lost': CLOSED_LOST_STAGES_DEFAULT,
        'excluded_pipelines': EXCLUDED_PIPELINES_DEFAULT,
    }

    try:
        import yaml
        config_path = REPO_ROOT / 'config' / 'client.yaml'
        if not config_path.exists():
            print("  ⚠️  config/client.yaml not found")
            print("     Run: python scripts/discover_stages.py")
            print("     Then configure your stage IDs in client.yaml")
            return default_result

        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

        # New shape: pipeline.pipelines[] with per-stage order/flags.
        new_pipelines = config.get('pipeline', {}).get('pipelines', [])
        if new_pipelines:
            return _excluded_stages_from_pipeline_config(new_pipelines)

        # Legacy shape: flat excluded_stages block (older forks).
        excluded = config.get('excluded_stages', {})
        if excluded:
            def get_ids(section):
                stages = excluded.get(section, [])
                if isinstance(stages, list):
                    return [s.get('id') for s in stages if s.get('id')
                            and 'YOUR_' not in str(s.get('id', ''))]
                return []

            excluded_pipelines = []
            for pipeline in config.get('pipelines', {}).get('excluded', []):
                pipeline_id = pipeline.get('id', '')
                if pipeline_id and 'YOUR_' not in str(pipeline_id):
                    excluded_pipelines.append(pipeline_id)

            return {
                'meeting_set': get_ids('meeting_set'),
                'disqualified': get_ids('disqualified'),
                'closed_won': get_ids('closed_won') or CLOSED_WON_STAGES_DEFAULT,
                'closed_lost': get_ids('closed_lost') or CLOSED_LOST_STAGES_DEFAULT,
                'excluded_pipelines': excluded_pipelines,
            }

        return default_result
    except Exception as e:
        print(f"  ⚠️  Could not load client.yaml: {e}")
        return default_result


def get_deal_status(stage: str, excluded_stages: dict) -> str:
    """Determine deal status for history mode."""
    if stage in excluded_stages['closed_won']:
        return 'won'
    if stage in excluded_stages['closed_lost']:
        return 'lost'
    return 'active'


def calculate_days_to_close(create_date_str: str, close_date_str: str) -> int:
    """Calculate days from create to close for closed deals."""
    try:
        if not create_date_str or not close_date_str:
            return None
        create_date = datetime.fromisoformat(create_date_str.split('T')[0])
        close_date = datetime.fromisoformat(close_date_str.split('T')[0])
        return (close_date - create_date).days
    except Exception:
        return None


def get_meeting_set_stages(hubspot, excluded_stages: dict):
    """
    Fetch pipeline stages and auto-detect Meeting Set stages.
    Returns list of stage IDs from config + auto-detected.
    """
    # Start with config-defined Meeting Set stages
    meeting_set_stages = list(excluded_stages['meeting_set'])

    try:
        endpoint = "/crm/v3/pipelines/deals"
        response = hubspot._get(endpoint)
        pipelines = response.get('results', [])

        for pipeline in pipelines:
            stages = pipeline.get('stages', [])
            for stage in stages:
                stage_label = stage.get('label', '').lower()
                stage_id = stage.get('id', '')

                # Auto-detect additional meeting set stages by label
                if 'meeting set' in stage_label and stage_id not in meeting_set_stages:
                    meeting_set_stages.append(stage_id)

        return meeting_set_stages

    except Exception as e:
        print(f"⚠️  Could not fetch stages: {e}")
        return excluded_stages['meeting_set']


def main():
    parser = argparse.ArgumentParser(description="ETL HubSpot deals to memory/Supabase")
    parser.add_argument(
        '--mode',
        type=str,
        choices=['active', 'history'],
        default='active',
        help='active: fetch active deals only (default) | history: fetch ALL deals including closed'
    )
    parser.add_argument(
        '--file',
        type=str,
        help='CSV file path (for history mode bulk import from HubSpot export)'
    )
    args = parser.parse_args()

    # Validate: --file requires --mode history
    if args.file and args.mode != 'history':
        print("ERROR: --file can only be used with --mode history")
        return

    print("=" * 80)
    print(f"HUBSPOT DEALS ETL - MODE: {args.mode.upper()}")
    print("=" * 80)

    # Load stage exclusions from config
    excluded_stages = get_excluded_stages()

    # Initialize HubSpot client
    print("\n1. Connecting to HubSpot API...")
    try:
        hubspot = get_crm_adapter()
    except Exception as e:
        print(f"❌ Failed to initialize HubSpot client: {e}")
        print("\nMake sure HUBSPOT_API_KEY environment variable is set.")
        return

    # Determine which deals to fetch based on mode
    if args.mode == 'active':
        # Auto-detect Meeting Set stages
        print("\n2. Auto-detecting Meeting Set stages...")
        meeting_set_stages = get_meeting_set_stages(hubspot, excluded_stages)
        print(f"   Meeting Set stages: {meeting_set_stages}")

        # Fetch active deals only (excludes closed stages via dynamic filtering)
        print("\n3. Fetching active deals from HubSpot API...")
        try:
            all_deals_api = hubspot.get_active_deals()
            closed_stages = hubspot._get_closed_stage_ids()
            print(f"   Fetched {len(all_deals_api)} deals")
            print(f"   Auto-excluded closed stages: {closed_stages}")
        except Exception as e:
            print(f"❌ Failed to fetch deals: {e}")
            return
    else:  # history mode
        meeting_set_stages = []
        closed_stages = []

        if args.file:
            # Load from CSV export
            print(f"\n2. Loading deals from CSV: {args.file}...")
            try:
                import csv
                all_deals_api = []
                with open(args.file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Convert CSV row to deal object format
                        deal_obj = {
                            'id': row.get('Record ID') or row.get('deal_id'),
                            'properties': {
                                'dealname': row.get('Deal Name') or row.get('dealname', ''),
                                'pipeline': row.get('Pipeline') or row.get('pipeline', ''),
                                'dealstage': row.get('Deal Stage') or row.get('dealstage', ''),
                                'incremental_arr': row.get('Incremental ARR') or row.get('amount', '0'),
                                'closedate': row.get('Close Date') or row.get('closedate', ''),
                                'createdate': row.get('Create Date') or row.get('createdate', ''),
                                'hubspot_owner_id': row.get('Deal owner') or row.get('hubspot_owner_id', ''),
                                'hs_object_id': row.get('Record ID') or row.get('deal_id'),
                            }
                        }
                        all_deals_api.append(deal_obj)
                print(f"   Loaded {len(all_deals_api)} deals from CSV")
            except Exception as e:
                print(f"❌ Failed to load CSV: {e}")
                print("   Make sure CSV has columns: Record ID, Deal Name, Pipeline, Deal Stage, Close Date, Create Date")
                return
        else:
            # Fetch ALL deals including closed from API
            print("\n2. Fetching ALL deals (including closed) from HubSpot API...")
            print("   Note: For large datasets, use --file with a CSV export instead")
            try:
                # Use search API without stage filters
                all_deals_api = hubspot.get_all_deals_including_closed()
                print(f"   Fetched {len(all_deals_api)} deals (active + closed)")
            except Exception as e:
                print(f"❌ Failed to fetch deals: {e}")
                print("   Try exporting from HubSpot and using --file instead")
                return

    # Process deals
    print("\n4. Processing deals and fetching company info...")
    deals = {}
    skipped = {
        'renewal_pipeline': 0,
        'meeting_set': 0,
        'disqualified': 0,
        'no_company': 0,
        'no_slug': 0
    }

    for i, deal_obj in enumerate(all_deals_api, 1):
        if i % 50 == 0:
            print(f"   Processed {i}/{len(all_deals_api)} deals...")

        deal_id = deal_obj.get('id')
        props = deal_obj.get('properties', {})

        deal_name = props.get('dealname', '')
        pipeline = props.get('pipeline') or ''
        stage = props.get('dealstage') or ''
        arr = props.get('incremental_arr') or props.get('amount', '0')
        close_date = props.get('closedate', '')
        create_date = props.get('createdate', '')
        owner_id = props.get('hubspot_owner_id', '')

        if not deal_id:
            continue

        # In active mode, apply stage filters. In history mode, include everything.
        if args.mode == 'active':
            # Filter: exclude Renewal pipeline (by ID or name)
            excluded_pipelines = excluded_stages['excluded_pipelines']
            if pipeline in excluded_pipelines or any(excl in pipeline.lower() for excl in excluded_pipelines if excl.isalpha()):
                skipped['renewal_pipeline'] += 1
                continue

            # Filter: exclude Disqualified stage
            if stage in excluded_stages['disqualified']:
                skipped['disqualified'] += 1
                continue

            # Filter: exclude Meeting Set stages
            if stage in meeting_set_stages:
                skipped['meeting_set'] += 1
                continue

        # Get company (with error handling)
        try:
            company_obj = hubspot.get_deal_company(deal_id)
            if not company_obj:
                skipped['no_company'] += 1
                continue

            company_name = company_obj.get('properties', {}).get('name', '')
            if not company_name.strip():
                skipped['no_company'] += 1
                continue

        except Exception as e:
            skipped['no_company'] += 1
            continue

        # Generate slug
        slug = slugify(company_name)
        if not slug:
            skipped['no_slug'] += 1
            continue

        # Build deal object with mode-specific fields
        deal_dict = {
            'deal_id': deal_id,
            'deal_name': deal_name,
            'company_name': company_name,
            'company_slug': slug,
            'pipeline': pipeline,
            'stage': stage,
            'arr': arr,
            'close_date': close_date,
            'owner_id': owner_id,
            'last_modified': datetime.now().isoformat(),
        }

        # Add history-specific fields
        if args.mode == 'history':
            deal_status = get_deal_status(stage, excluded_stages)
            deal_dict['deal_status'] = deal_status
            deal_dict['create_date'] = create_date

            # Calculate days_to_close for closed deals
            if deal_status in ('won', 'lost'):
                days = calculate_days_to_close(create_date, close_date)
                deal_dict['days_to_close'] = days

        deals[deal_id] = deal_dict

    # In active mode, write memory/deals/index.json. In history mode, skip (Supabase only).
    if args.mode == 'active':
        # Build index
        print(f"\n5. Building index...")
        index = {
            'last_etl_date': datetime.now().isoformat(),
            'total_deals': len(deals),
            'excluded_closed_stages': closed_stages,
            'excluded_meeting_set_stages': meeting_set_stages,
            'excluded_disqualified_stages': excluded_stages['disqualified'],
            'excluded_renewal_pipeline': excluded_stages['excluded_pipelines'],
            'deals': deals,
        }

        out = DEALS_DIR / 'index.json'
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

        print(f'\n✓ Deal index built: {len(deals)} active deals')
        print(f'  Skipped breakdown:')
        print(f'    {skipped["renewal_pipeline"]} Renewal pipeline')
        print(f'    {skipped["disqualified"]} Disqualified')
        print(f'    {skipped["meeting_set"]} Meeting Set stage')
        print(f'    {skipped["no_company"]} No company')
        print(f'    {skipped["no_slug"]} Invalid slug')
        print(f'  Output: {out}')
    else:  # history mode
        print(f"\n5. Processed {len(deals)} deals (active + closed)")
        # Count by status
        status_counts = {}
        for d in deals.values():
            status = d.get('deal_status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
        print(f'  Status breakdown:')
        for status, count in sorted(status_counts.items()):
            print(f'    {status}: {count} deals')

    # Write to Supabase if configured
    if os.getenv('SUPABASE_URL'):
        print(f'\n6. Writing to Supabase...')
        try:
            sb = get_storage_adapter()
            count = 0
            for deal_id, deal in deals.items():
                try:
                    sb.upsert_deal(deal)
                    count += 1
                except Exception as e:
                    print(f'  ⚠️  Supabase upsert failed for '
                          f'{deal.get("company_name")}: {e}')
            print(f'  ✓ Supabase: {count} deals upserted')
        except Exception as e:
            print(f'  ⚠️  Supabase write failed: {e}')
    else:
        print(f'\n  ⏭️  SUPABASE_URL not set — skipping Supabase write')

    # Print first 10 for verification
    print('\nFirst 10 active deals:')
    for i, (did, d) in enumerate(list(deals.items())[:10], 1):
        print(f'  [{i}] {d["company_name"]} | {d["stage"]} | '
              f'{d["pipeline"]} | ${d["arr"]}')

    # Print unique stages
    stages = sorted(set(d['stage'] for d in deals.values()))
    print(f'\nStages in index ({len(stages)} total):')
    for s in stages:
        count = sum(1 for d in deals.values() if d['stage'] == s)
        print(f'  {s}: {count} deals')

    print("\n" + "=" * 80)
    print("✓ ETL Complete")
    print("=" * 80)


if __name__ == '__main__':
    main()
