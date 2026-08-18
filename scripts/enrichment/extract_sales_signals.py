#!/usr/bin/env python3
"""
Extract structured sales signals from resolved calls in the calls table.
Runs against calls not yet in the enrichment_scans ledger.

Reads call_intent, is_internal, and deal_id from the calls table
instead of re-deriving via slugify.

Usage:
  python scripts/enrichment/extract_sales_signals.py
  python scripts/enrichment/extract_sales_signals.py --dry-run
  python scripts/enrichment/extract_sales_signals.py --limit 50 --yes
"""

import os
import json
import argparse
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent.parent.parent
JOB_NAME = 'sales_signals'

PROMPT = """Read this internal sales team
call and extract sales intelligence signals.

This is a {call_type} call (forecast review, pipeline
discussion, deal strategy, or competitive debrief).

Call summary:
{call_summary}

Extract:

1. deal_risks: deals mentioned as at-risk, stalled, or
   in trouble. For each:
   - company_name
   - risk_description (what the rep said about the risk)
   - rep_name (who raised it, if mentioned)

2. competitive_signals: competitor mentions or competitive
   situations discussed:
   - competitor_name
   - context (what was said)
   - deal_company (which prospect deal, if mentioned)

3. pipeline_signals: pipeline accuracy or forecast notes:
   - signal_type: commit_risk | upside | slip | pull_in
   - company_name (deal being discussed)
   - description

Return JSON:
{{
  "deal_risks": [...],
  "competitive_signals": [...],
  "pipeline_signals": [...]
}}
Empty arrays if nothing found. No prose outside JSON."""


def _stamp(sb, call_id, job, slug, n):
    """Record scan completion in enrichment_scans ledger."""
    sb.table('enrichment_scans').upsert({
        'call_id': call_id,
        'job': job,
        'company_slug': slug,
        'items_found': n,
        'scanned_at': datetime.utcnow().isoformat(),
    }, on_conflict='call_id,job').execute()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=50,
                        help='Max calls to scan (across all files)')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--yes', action='store_true')
    args = parser.parse_args()

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
    ANTHROPIC_KEY = os.getenv('ANTHROPIC_API_KEY')
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  Supabase credentials not set")
        return

    from supabase import create_client
    import sys
    sys.path.insert(0, str(REPO_ROOT / 'scripts'))
    sys.path.insert(0, str(REPO_ROOT))
    from supabase_client import select_all
    from scripts.enrichment.call_intent_classifier import ENRICHMENT_PROFILE

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 1. Load scan ledger once
    scanned = {r['call_id'] for r in select_all(
        sb, 'enrichment_scans', columns='call_id,job',
        filters=[('eq', 'job', JOB_NAME)])}

    # 2. Query calls table for unscanned calls with resolved metadata
    # Filter: non-internal calls with intent that should be scanned for objections
    all_calls = select_all(sb, 'calls',
        columns='call_id,company_name,deal_id,title,summary,call_date,call_intent,is_internal,intent_confidence')

    # Filter to qualifying calls:
    # - Not already scanned
    # - Not internal calls
    # - Has call_intent (resolved)
    # - Intent suggests sales signal extraction is appropriate
    candidate_calls = []
    for call in all_calls:
        call_id = call.get('call_id')
        if not call_id or call_id in scanned:
            continue

        # Skip internal calls (already filtered by resolution)
        if call.get('is_internal'):
            continue

        # Check if this intent type should extract objections
        intent = call.get('call_intent')
        if intent and intent in ENRICHMENT_PROFILE:
            profile = ENRICHMENT_PROFILE[intent]
            if profile.get('extract_sales_signals'):
                candidate_calls.append(call)

    print(f"Found {len(candidate_calls)} unscanned non-internal calls eligible for sales signal extraction")
    print(f"  ({len(all_calls)} total calls, {len(scanned)} already scanned, {len([c for c in all_calls if c.get('is_internal')])} internal)")

    # Apply limit
    to_process = []
    for call in candidate_calls[:args.limit]:
        call_id = call.get('call_id')
        summary = call.get('summary', '')

        to_process.append({
            'call_id': call_id,
            'company': call.get('company_name') or 'Unknown',
            'title': call.get('title', '') or '',
            'summary': summary,
            'call_date': call.get('call_date', ''),
            'deal_id': call.get('deal_id'),  # Already resolved!
            'call_intent': call.get('call_intent'),
            'intent_confidence': call.get('intent_confidence'),
        })

    if not to_process:
        print("No unscanned calls found.")
        return

    est_cost = len(to_process) * 0.02  # Haiku, small prompt
    print(f"{len(to_process)} calls to scan, "
          f"estimated cost: ${est_cost:.2f}")

    if args.dry_run:
        print("\n--dry-run: First 15 calls:")
        for i, c in enumerate(to_process[:15], 1):
            print(f"  {i:2d}. {c['company']:30s} | "
                  f"call:{c['call_id'][:20]} | "
                  f"date:{c['call_date'] or 'unknown':10s} | "
                  f"intent:{c.get('call_intent', 'NULL'):12s} | "
                  f"deal_id:{c['deal_id'] or 'NULL'}")
        return

    if len(to_process) >= 20 and not args.yes:
        if input("Proceed? (y/N): ").lower() != 'y':
            print("Aborted.")
            return

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    from token_tracker import TokenTracker
    tracker = TokenTracker(REPO_ROOT / 'memory')

    written, scanned = 0, 0
    deal_id_resolved = 0
    companies = set()

    for call_data in to_process:
        call_id = call_data['call_id']
        company = call_data['company']
        summary = call_data['summary']
        call_date = call_data['call_date']
        deal_id = call_data['deal_id']
        call_intent = call_data['call_intent']

        if len(summary) < 100:
            # Stamp scanned anyway — nothing to extract
            _stamp(sb, call_id, JOB_NAME, company or 'unknown', 0)
            scanned += 1
            continue

        # Intent already determined and filtered in query above,
        # but double-check profile allows sales signal extraction
        profile = ENRICHMENT_PROFILE.get(call_intent, {})
        if not profile.get("extract_sales_signals"):
            print(f"  ↷ {company}: "
                  f"{call_intent} call — "
                  f"skipping sales signal extraction")
            _stamp(sb, call_id, JOB_NAME, company or 'unknown', 0)
            scanned += 1
            continue

        prompt = PROMPT.format(call_summary=summary[:4000])

        try:
            resp = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=500,
                messages=[{'role': 'user', 'content': prompt}]
            )
            tracker.record(resp, 'claude-haiku-4-5-20251001',
                           'sales_signal_extraction', company)

            # Parse JSON response (strip markdown code fences if present)
            text = resp.content[0].text.strip()
            if text.startswith('```'):
                # Remove markdown code fences
                text = text.split('\n', 1)[1]  # Remove first line (```json)
                text = text.rsplit('\n', 1)[0]  # Remove last line (```)
            signals = json.loads(text.strip())

            for signal in signals:
                if not deal_id:
                    print(f"Skipping enrichment record with no deal_id: "
                          f"{company}", flush=True)
                    continue
                sb.table('sales_signals').insert({
                    'deal_id': deal_id,
                    'company_name': company,
                    'call_id': call_id,
                    'signal_type': signal.get('signal_type', ''),
                    'indicator': signal.get('indicator', ''),
                    'verbatim_evidence': signal.get('verbatim_evidence', ''),
                    'strength': signal.get('strength', 'weak'),
                    'extracted_at': datetime.utcnow().isoformat(),
                }).execute()
                written += 1

            _stamp(sb, call_id, JOB_NAME, company or 'unknown', len(signals))
            scanned += 1
            companies.add(company or 'unknown')
            if deal_id:
                deal_id_resolved += 1
            print(f"  ✓ {company}: {len(signals)} signal(s)")

        except Exception as e:
            print(f"  ✗ {company} ({call_id[:20]}): {e}")

    summary_stats = tracker.save()
    tracker.print_summary(summary_stats, scanned)

    pct_resolved = (deal_id_resolved / scanned * 100) if scanned > 0 else 0
    print(f"\n✓ Scanned {scanned} calls, {written} signals written")
    print(f"  Deal ID resolved: {deal_id_resolved} ({pct_resolved:.1f}%)")
    print(f"  Deal ID NULL: {scanned - deal_id_resolved} ({100-pct_resolved:.1f}%)")
    print(f"  Distinct companies: {len(companies)}")


if __name__ == '__main__':
    main()
