#!/usr/bin/env python3
"""
ETL: HubSpot Deals API → Deal Index

Fetches all deals from HubSpot API and builds memory/deals/index.json.
Auto-detects pipeline stages to exclude (closed won/lost, meeting set).
"""
import json
import sys
import os
from pathlib import Path
from datetime import datetime
import re

# Add parent directory to path for imports
REPO_ROOT = Path(__file__).parent.parent
DEALS_DIR = REPO_ROOT / 'memory' / 'deals'
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

DEALS_DIR.mkdir(parents=True, exist_ok=True)

# Exclude Renewal Pipeline (both by name and ID)
EXCLUDED_PIPELINES = ['renewal', '866608541']

# Exclude Disqualified stage
DISQUALIFIED_STAGES = ['68509551']

# Exclude Meeting Set stages (always filter these out)
# 'appointmentscheduled' = Discovery in some views, but actually Meeting Set
# '79653122' = Meeting Set (numeric ID)
MEETING_SET_STAGES = ['appointmentscheduled', '79653122']


def slugify(name: str) -> str:
    """
    Convert company name to slug (e.g., 'Skyscanner + GrowthBook' -> 'skyscanner').
    Same logic as etl_calls.py for consistency.
    """
    if not name:
        return ''

    parts = re.split(r'\s*[-–—]\s+', name, maxsplit=1)
    company_part = parts[0]
    company_part = re.sub(r'growthbook', '', company_part, flags=re.IGNORECASE)
    company_part = re.sub(r'[+<>&/,]', ' ', company_part)
    company_part = re.sub(
        r'\b(and|the|with|vs|versus|for|at|in|of)\b',
        '', company_part, flags=re.IGNORECASE
    )
    company_part = re.sub(r'\s+', ' ', company_part).strip().lower()
    company_part = re.sub(r'[^a-z0-9\s]', '', company_part)
    slug = company_part.replace(' ', '_').strip('_')
    return slug if len(slug) >= 3 else ''


def get_meeting_set_stages(hubspot):
    """
    Fetch pipeline stages and auto-detect Meeting Set stages.
    Returns list of stage IDs.
    """
    # Start with hardcoded Meeting Set stages
    meeting_set_stages = list(MEETING_SET_STAGES)

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
        return MEETING_SET_STAGES


def main():
    print("=" * 80)
    print("HUBSPOT DEALS ETL")
    print("=" * 80)

    # Initialize HubSpot client
    print("\n1. Connecting to HubSpot API...")
    try:
        from hubspot_deals import get_hubspot_deals_client
        hubspot = get_hubspot_deals_client()
    except Exception as e:
        print(f"❌ Failed to initialize HubSpot client: {e}")
        print("\nMake sure HUBSPOT_API_KEY environment variable is set.")
        return

    # Auto-detect Meeting Set stages
    print("\n2. Auto-detecting Meeting Set stages...")
    meeting_set_stages = get_meeting_set_stages(hubspot)
    print(f"   Meeting Set stages: {meeting_set_stages}")

    # Fetch all active deals (already excludes closed stages via dynamic filtering)
    print("\n3. Fetching active deals from HubSpot API...")
    try:
        all_deals_api = hubspot.get_active_deals()
        closed_stages = hubspot._get_closed_stage_ids()
        print(f"   Fetched {len(all_deals_api)} deals")
        print(f"   Auto-excluded closed stages: {closed_stages}")
    except Exception as e:
        print(f"❌ Failed to fetch deals: {e}")
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
        owner_id = props.get('hubspot_owner_id', '')

        if not deal_id:
            continue

        # Filter: exclude Renewal pipeline (by ID or name)
        if pipeline in EXCLUDED_PIPELINES or any(excl in pipeline.lower() for excl in EXCLUDED_PIPELINES if excl.isalpha()):
            skipped['renewal_pipeline'] += 1
            continue

        # Filter: exclude Disqualified stage
        if stage in DISQUALIFIED_STAGES:
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

        deals[deal_id] = {
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

    # Build index
    print(f"\n5. Building index...")
    index = {
        'last_etl_date': datetime.now().isoformat(),
        'total_deals': len(deals),
        'excluded_closed_stages': closed_stages,
        'excluded_meeting_set_stages': meeting_set_stages,
        'excluded_disqualified_stages': DISQUALIFIED_STAGES,
        'excluded_renewal_pipeline': EXCLUDED_PIPELINES,
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

    # Write to Supabase if configured
    if os.getenv('SUPABASE_URL'):
        print(f'\n6. Writing to Supabase...')
        try:
            sys.path.insert(0, str(REPO_ROOT / 'scripts'))
            from supabase_client import SupabaseWriter
            sb = SupabaseWriter()
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
