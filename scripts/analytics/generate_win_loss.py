#!/usr/bin/env python3
"""
Generates win/loss narratives for newly-closed deals.
Reads call cache + MEDDICC analysis history + stated CRM reason.
Writes to win_loss_narratives table.

THREE OUTCOMES (not two): won, lost, slipped. A deal that closed in a later
quarter than committed is slipped, not lost — different diagnosis, different
coaching. Never collapse slipped into lost (Kellogg critique).

POINT-IN-TIME: Reads stage, value, segment from deals_snapshot as of close_date,
never joins to current deals table state. A won deal's segment is what it was
WHEN it won, not what the company's segment is today.

GATES: min_evidence_count applies. Below threshold returns null with reason
rather than generating narrative from thin data.

Defaults to deals closed AFTER qualification_seeded_at in
analytics_meta.json to avoid unbounded first-run cost.
Use --include-historical to process older closed deals.
Use --limit N to cap per run (default 25).
Use --yes to skip cost confirmation prompt.

Usage:
  python scripts/analytics/generate_win_loss.py
  python scripts/analytics/generate_win_loss.py --limit 5 --dry-run
  python scripts/analytics/generate_win_loss.py
    --include-historical --limit 10 --yes
"""

import os
import sys
import re
import json
import argparse
from datetime import datetime, date
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from llm_client import LLMClient


def classify_outcome(deal, snapshots_for_deal):
    """
    Classify deal outcome as won/lost/slipped (three outcomes, never two).

    Args:
        deal: Deal row with deal_status, close_date
        snapshots_for_deal: List of snapshot rows for this deal over time

    Returns:
        'won', 'lost', or 'slipped'

    Slipped: Deal closed as won/lost but in a later quarter than originally
    committed. Requires comparing earliest qualified-pipeline close_date to
    actual close_date quarter.
    """
    status = deal.get('deal_status', '')
    if not snapshots_for_deal:
        # No snapshot history — fall back to simple won/lost
        return 'won' if status == 'won' else 'lost'

    # Find the earliest snapshot where deal was in qualified pipeline
    # (stage_order >= qualified threshold) with a close_date set
    from utils import load_client_config, get_fiscal_quarter
    config = load_client_config()

    # Get qualified_stage_order from config (Gap 2 made this raise if not set)
    from utils import get_pipeline_config
    pipeline_cfg = get_pipeline_config(config=config)
    threshold = pipeline_cfg.get('qualified_stage_order')
    if threshold is None:
        # Shouldn't happen (Gap 2 makes it raise) but handle gracefully
        return 'won' if status == 'won' else 'lost'

    # Sort snapshots by date (oldest first)
    sorted_snaps = sorted(snapshots_for_deal,
                         key=lambda s: s.get('snapshot_date', ''))

    earliest_committed_close = None
    for snap in sorted_snaps:
        order = snap.get('stage_order', 0) or 0
        close_date_str = snap.get('close_date')
        if order >= threshold and close_date_str:
            earliest_committed_close = close_date_str
            break

    if not earliest_committed_close:
        # Never had a committed close_date in qualified pipeline
        return 'won' if status == 'won' else 'lost'

    # Compare quarters
    actual_close_str = deal.get('close_date', '')
    if not actual_close_str:
        return 'won' if status == 'won' else 'lost'

    try:
        committed_date = date.fromisoformat(earliest_committed_close[:10])
        actual_date = date.fromisoformat(actual_close_str[:10])

        _, _, committed_q = get_fiscal_quarter(committed_date, config)
        _, _, actual_q = get_fiscal_quarter(actual_date, config)

        if committed_q != actual_q:
            # Closed in different quarter than committed — SLIPPED
            return 'slipped'

    except (ValueError, TypeError):
        pass

    # Same quarter or couldn't parse — won/lost
    return 'won' if status == 'won' else 'lost'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--include-historical', action='store_true',
                        help='Include deals closed before seeded_at cutoff')
    parser.add_argument('--limit', type=int, default=25,
                        help='Max narratives to generate per run (default 25)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would be generated without calling Claude')
    parser.add_argument('--yes', action='store_true',
                        help='Skip cost confirmation prompt')
    args = parser.parse_args()

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
    ANTHROPIC_KEY = os.getenv('ANTHROPIC_API_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE credentials not set")
        return
    if not ANTHROPIC_KEY and not args.dry_run:
        print("⚠️  ANTHROPIC_API_KEY not set")
        return

    from supabase import create_client
    from token_tracker import TokenTracker
    from adapters.storage.supabase import select_all
    from utils import load_client_config

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    config = load_client_config()
    tracker = TokenTracker(REPO_ROOT / 'memory', job='win_loss')

    # Load min_evidence_count gate from config
    min_evidence = config.get('proposal_engine', {}).get('min_evidence_count', 30)
    print(f"Min evidence threshold: {min_evidence} (deals below this return null with reason)")

    # Determine cutoff date
    meta_path = REPO_ROOT / 'memory' / 'meta' / 'analytics_meta.json'
    cutoff = None
    if meta_path.exists() and not args.include_historical:
        meta = json.load(open(meta_path))
        cutoff = meta.get('qualification_seeded_at', '')[:10]
        print(f"Processing deals closed after: {cutoff}")
        print("  (use --include-historical for older deals)")

    # Find closed deals without a narrative yet (paginated)
    # Point-in-time: Read from deals table (closed deals are historical facts)
    filters = [('in_', 'deal_status', ['won', 'lost'])]
    if cutoff:
        filters.append(('gte', 'close_date', cutoff))
    closed = select_all(
        sb, 'deals',
        'deal_id, company_name, deal_status, lost_reason, close_date',
        filters=filters
    )

    # Filter out deals that already have narratives (paginated)
    existing_ids = {
        r['deal_id'] for r in
        select_all(sb, 'win_loss_narratives', 'deal_id')
    }
    to_process = [d for d in closed
                  if d['deal_id'] not in existing_ids][:args.limit]

    if not to_process:
        print("No new closed deals need narratives.")
        return

    # Load all snapshots for these deals (for slipped classification)
    deal_ids_to_process = [d['deal_id'] for d in to_process]
    all_snapshots = select_all(
        sb, 'deals_snapshot',
        'deal_id, snapshot_date, stage_order, close_date',
        filters=[('in_', 'deal_id', deal_ids_to_process)]
    )
    snapshots_by_deal = {}
    for snap in all_snapshots:
        deal_id = snap.get('deal_id')
        if deal_id not in snapshots_by_deal:
            snapshots_by_deal[deal_id] = []
        snapshots_by_deal[deal_id].append(snap)

    # Classify outcomes (won/lost/slipped)
    for deal in to_process:
        snapshots = snapshots_by_deal.get(deal['deal_id'], [])
        deal['outcome'] = classify_outcome(deal, snapshots)

    # Cost estimate and confirmation
    est_cost = len(to_process) * 0.08  # ~$0.08/narrative (Sonnet)
    print(f"\n{len(to_process)} deals to process, "
          f"estimated cost: ${est_cost:.2f}")
    outcome_counts = {}
    for d in to_process:
        outcome_counts[d['outcome']] = outcome_counts.get(d['outcome'], 0) + 1
    print(f"  Outcomes: {', '.join(f'{k}={v}' for k, v in sorted(outcome_counts.items()))}")

    if len(to_process) >= 5 and not args.yes and not args.dry_run:
        confirm = input("Proceed? (y/N): ")
        if confirm.lower() != 'y':
            print("Aborted.")
            return

    # Generate narratives
    client = LLMClient.from_config("generator") \
        if not args.dry_run else None

    written = 0
    for deal in to_process:
        deal_id = deal['deal_id']
        company_name = deal.get('company_name', 'Unknown')
        outcome = deal.get('outcome', 'unknown')
        stated_reason = deal.get('lost_reason', '')

        if args.dry_run:
            print(f"  Would generate: {company_name} ({outcome})")
            continue

        # Load call summaries for this company
        from utils import slugify
        company_slug = slugify(company_name)
        cache_path = (REPO_ROOT / 'memory' / 'calls'
                      / f'{company_slug}.json')
        calls_text = ""
        call_count = 0
        if cache_path.exists():
            cache = json.load(open(cache_path))
            summaries = [
                c.get('formatted_summary') or c.get('summary', '')
                for c in cache.get('calls', [])
                if c.get('formatted_summary') or c.get('summary')
            ]
            call_count = len(summaries)
            calls_text = "\n\n---\n\n".join(summaries[-5:])
            # last 5 calls only — sufficient for narrative

        # Load MEDDICC score progression
        analyses = sb.table('analyses')\
            .select('component_scores, analyzed_at')\
            .eq('deal_id', deal_id)\
            .order('analyzed_at')\
            .execute().data or []
        score_progression = json.dumps(
            [a['component_scores'] for a in analyses], indent=2
        ) if analyses else "No score history available"

        # Evidence gate: min_evidence_count
        evidence_count = call_count + len(analyses)
        if evidence_count < min_evidence:
            # Below threshold — write null narrative with reason
            sb.table('win_loss_narratives').upsert({
                'deal_id': deal_id,
                'company_name': company_name,
                'outcome': outcome,
                'stated_reason': stated_reason,
                'narrative': None,
                'key_factors': None,
                'competitor_mentioned': None,
                'generated_at': datetime.utcnow().isoformat(),
                'null_reason': f"Insufficient evidence: {evidence_count} items "
                              f"(need {min_evidence}). {call_count} calls, "
                              f"{len(analyses)} analyses.",
            }, on_conflict='deal_id').execute()
            print(f"  ⊘ {company_name} ({outcome}) — below evidence threshold")
            continue

        # Outcome-specific prompt guidance
        outcome_guidance = {
            'won': "Focus on what the rep did right and why it worked.",
            'lost': "Focus on what went wrong and what should have been done differently.",
            'slipped': "This deal SLIPPED (closed in a later quarter than committed). "
                      "Focus on why the close_date moved and what forecasting discipline broke down. "
                      "A slipped deal is different from a lost deal — diagnose the push, not the loss."
        }

        prompt = f"""Analyze this {outcome.upper()} deal for {company_name}
and write a concise win/loss analysis.

Outcome: {outcome.upper()}
{outcome_guidance.get(outcome, '')}
Rep-stated reason: {stated_reason or 'Not provided'}

Call history (last 5 calls):
{calls_text or 'No call transcripts available'}

MEDDICC score progression over time:
{score_progression}

Write a 150-250 word analysis covering:
1. What ultimately drove the {outcome} outcome
2. Strongest and weakest MEDDICC components
3. Key inflection point (moment things turned)
4. Whether the stated reason aligns with or contradicts
   what the calls show — this is the most important insight
5. One specific coaching recommendation for future similar deals

Also identify:
- competitor_mentioned: name of competitor if one appeared,
  or null
- key_factors: list of 3-5 short factor strings

Return JSON only, no prose outside it:
{{
  "narrative": "...",
  "competitor_mentioned": "...",
  "key_factors": ["...", "..."]
}}

Return ONLY the JSON object, no markdown formatting,
no code fences, no preamble or explanation."""

        try:
            resp = client.complete(
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=600
            )
            tracker.record(resp, client.model,
                           'win_loss', company_name)
            raw = resp.text.strip()
            if raw.startswith('```'):
                raw = re.sub(r'^```[a-z]*\n?', '', raw)
                raw = re.sub(r'\n?```$', '', raw)
                raw = raw.strip()
            parsed = json.loads(raw)

            sb.table('win_loss_narratives').upsert({
                'deal_id': deal_id,
                'company_name': company_name,
                'outcome': outcome,
                'stated_reason': stated_reason,
                'narrative': parsed.get('narrative', ''),
                'key_factors':
                    json.dumps(parsed.get('key_factors', [])),
                'competitor_mentioned':
                    parsed.get('competitor_mentioned'),
                'generated_at':
                    datetime.utcnow().isoformat(),
            }, on_conflict='deal_id').execute()
            written += 1
            print(f"  ✓ {company_name} ({outcome})")

        except Exception as e:
            print(f"  ✗ {company_name}: {e}")

    if not args.dry_run:
        summary = tracker.save()
        tracker.print_summary(summary, written)
    print(f"\n✓ Generated {written} win/loss narratives")


if __name__ == '__main__':
    main()
