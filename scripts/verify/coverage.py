#!/usr/bin/env python3
"""
Coverage verification: What fraction of deals have calls, transcripts, scores, snapshots.

Reports per-source (Fireflies, Apollo, Gong), never averaged. Thin coverage is a
finding, not a failure — a client with 10% snapshot coverage learns that fact
explicitly rather than discovering it when the waterfall stays empty.

Verdict:
- PASS: Coverage meets minimum thresholds from config
- FAIL: Coverage below thresholds (if configured)
- INCONCLUSIVE: Insufficient data (< 10 deals in index)
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import load_client_config


def load_deal_index():
    """Load deals from memory/deals/index.json."""
    index_path = Path(__file__).parent.parent.parent / 'memory' / 'deals' / 'index.json'
    if not index_path.exists():
        return []
    with open(index_path) as f:
        return json.load(f)


def load_call_cache():
    """Load all cached calls from memory/calls/*.json."""
    calls_dir = Path(__file__).parent.parent.parent / 'memory' / 'calls'
    if not calls_dir.exists():
        return []

    all_calls = []
    for call_file in calls_dir.glob('*.json'):
        if call_file.name == '.gitkeep':
            continue
        try:
            with open(call_file) as f:
                calls = json.load(f)
                if isinstance(calls, list):
                    all_calls.extend(calls)
        except Exception:
            continue
    return all_calls


def get_supabase_coverage():
    """Get deal coverage from Supabase (scores and snapshots)."""
    try:
        from supabase_client import SupabaseWriter, select_all
        writer = SupabaseWriter()
        sb = writer.client

        # Get deals with analyses
        analyses = select_all(sb, 'analyses', columns='deal_id')
        deals_with_scores = set(str(a['deal_id']) for a in analyses if a.get('deal_id'))

        # Get deals with snapshots
        snapshots = select_all(sb, 'deal_snapshots', columns='deal_id')
        deals_with_snapshots = set(str(s['deal_id']) for s in snapshots if s.get('deal_id'))

        return deals_with_scores, deals_with_snapshots
    except Exception as e:
        print(f"   ⚠️  Supabase unavailable: {e}")
        return set(), set()


def compute_coverage(deals, calls, deals_with_scores, deals_with_snapshots):
    """Compute coverage metrics per source and overall."""
    total_deals = len(deals)

    if total_deals == 0:
        return None

    # Group calls by deal_id and source
    calls_by_deal = defaultdict(list)
    calls_by_source = defaultdict(list)

    for call in calls:
        deal_id = str(call.get('deal_id', ''))
        source = call.get('source', 'unknown')
        if deal_id:
            calls_by_deal[deal_id].append(call)
            calls_by_source[source].append(call)

    # Deals with at least one call
    deals_with_calls = set(calls_by_deal.keys())

    # Deals with transcripts (calls that have non-null transcript_text)
    deals_with_transcripts = set()
    for deal_id, deal_calls in calls_by_deal.items():
        if any(call.get('transcript_text') for call in deal_calls):
            deals_with_transcripts.add(deal_id)

    # Per-source breakdown
    source_coverage = {}
    for source, source_calls in calls_by_source.items():
        source_deal_ids = set(str(c.get('deal_id', '')) for c in source_calls if c.get('deal_id'))
        source_with_transcripts = set()
        for call in source_calls:
            deal_id = str(call.get('deal_id', ''))
            if call.get('transcript_text') and deal_id:
                source_with_transcripts.add(deal_id)

        source_coverage[source] = {
            'deals': len(source_deal_ids),
            'with_transcripts': len(source_with_transcripts),
            'transcript_rate': len(source_with_transcripts) / len(source_deal_ids) if source_deal_ids else 0
        }

    return {
        'total_deals': total_deals,
        'deals_with_calls': len(deals_with_calls),
        'call_coverage': len(deals_with_calls) / total_deals,
        'deals_with_transcripts': len(deals_with_transcripts),
        'transcript_coverage': len(deals_with_transcripts) / total_deals,
        'deals_with_scores': len(deals_with_scores),
        'score_coverage': len(deals_with_scores) / total_deals,
        'deals_with_snapshots': len(deals_with_snapshots),
        'snapshot_coverage': len(deals_with_snapshots) / total_deals,
        'source_coverage': source_coverage
    }


def render_verdict(coverage, config):
    """Determine pass/fail/inconclusive based on coverage and config thresholds."""
    if coverage is None:
        return 'INCONCLUSIVE', 'No deals in index'

    if coverage['total_deals'] < 10:
        return 'INCONCLUSIVE', f"Only {coverage['total_deals']} deals in index (need 10+ for meaningful coverage)"

    # Check config thresholds if they exist
    thresholds = config.get('quality_thresholds', {}).get('coverage', {})
    min_call_coverage = thresholds.get('minimum_call_coverage', 0.5)  # Default 50%
    min_snapshot_coverage = thresholds.get('minimum_snapshot_coverage', 0.3)  # Default 30%

    failures = []
    if coverage['call_coverage'] < min_call_coverage:
        failures.append(f"Call coverage {coverage['call_coverage']:.1%} below threshold {min_call_coverage:.1%}")

    if coverage['snapshot_coverage'] < min_snapshot_coverage:
        failures.append(f"Snapshot coverage {coverage['snapshot_coverage']:.1%} below threshold {min_snapshot_coverage:.1%}")

    if failures:
        return 'FAIL', '; '.join(failures)

    return 'PASS', f"Coverage meets thresholds (calls {coverage['call_coverage']:.1%}, snapshots {coverage['snapshot_coverage']:.1%})"


def main():
    """Run coverage verification check."""
    print("=" * 70)
    print("COVERAGE VERIFICATION")
    print("=" * 70)
    print("\nWhat fraction of deals have calls, transcripts, scores, snapshots.")
    print("Reports per-source to reveal data gaps.\n")

    # Load data
    print("Loading data...")
    config = load_client_config()
    deals = load_deal_index()
    calls = load_call_cache()
    deals_with_scores, deals_with_snapshots = get_supabase_coverage()

    # Compute coverage
    coverage = compute_coverage(deals, calls, deals_with_scores, deals_with_snapshots)

    if coverage is None:
        print("❌ INCONCLUSIVE: No deals in index\n")
        return 1

    # Report overall coverage
    print(f"\nOverall Coverage (n={coverage['total_deals']} deals):")
    print(f"  Calls:       {coverage['deals_with_calls']:>4} / {coverage['total_deals']} ({coverage['call_coverage']:>6.1%})")
    print(f"  Transcripts: {coverage['deals_with_transcripts']:>4} / {coverage['total_deals']} ({coverage['transcript_coverage']:>6.1%})")
    print(f"  Scores:      {coverage['deals_with_scores']:>4} / {coverage['total_deals']} ({coverage['score_coverage']:>6.1%})")
    print(f"  Snapshots:   {coverage['deals_with_snapshots']:>4} / {coverage['total_deals']} ({coverage['snapshot_coverage']:>6.1%})")

    # Report per-source coverage
    if coverage['source_coverage']:
        print(f"\nPer-Source Coverage:")
        for source, metrics in sorted(coverage['source_coverage'].items()):
            print(f"  {source:12} {metrics['deals']:>4} deals, "
                  f"{metrics['with_transcripts']:>4} transcripts ({metrics['transcript_rate']:>6.1%})")

    # Verdict
    verdict, reason = render_verdict(coverage, config)
    print(f"\n{'=' * 70}")
    print(f"VERDICT: {verdict}")
    print(f"REASON:  {reason}")
    print("=" * 70)

    return 0 if verdict == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
