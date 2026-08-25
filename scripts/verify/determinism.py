#!/usr/bin/env python3
"""
Determinism verification: Score one call N times and report per-component spread.

A client learns their own jitter rather than inheriting an assumption. the reference implementation's
real jitter was spread-0 on 3 of 7 components and ±1 on the rest, all at band
boundaries (6→7 green/yellow transitions).

Verdict:
- PASS: All components have spread ≤ configured tolerance
- FAIL: Any component exceeds tolerance
- INCONCLUSIVE: No calls available to test
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import load_client_config, get_components, component_key


def load_test_call(call_id=None):
    """Load a call for testing. If call_id not provided, pick first available."""
    calls_dir = Path(__file__).parent.parent.parent / 'memory' / 'calls'
    if not calls_dir.exists():
        return None

    # If specific call_id provided, try to find it
    if call_id:
        for call_file in calls_dir.glob('*.json'):
            if call_file.name == '.gitkeep':
                continue
            try:
                with open(call_file) as f:
                    calls = json.load(f)
                    if isinstance(calls, list):
                        for call in calls:
                            if str(call.get('call_id')) == str(call_id):
                                return call
            except Exception:
                continue
        return None

    # Otherwise pick first call with a transcript
    for call_file in calls_dir.glob('*.json'):
        if call_file.name == '.gitkeep':
            continue
        try:
            with open(call_file) as f:
                calls = json.load(f)
                if isinstance(calls, list):
                    for call in calls:
                        if call.get('transcript_text'):
                            return call
        except Exception:
            continue

    return None


def score_call_once(call, config):
    """Score a call once and return component scores.

    This is a simplified scorer that doesn't persist results.
    In production, would use the full meddicc_agent pipeline.

    For this verification, we'll use call_scorer directly to test determinism.
    """
    try:
        # Import scoring modules
        from call_scorer import score_call_incremental

        # Extract deal context from call
        deal_context = {
            'deal_id': call.get('deal_id'),
            'company_name': call.get('company_name', 'Unknown'),
            'deal_stage': call.get('deal_stage'),
            'prior_state': {}  # Empty state for first call
        }

        # Score the call
        result = score_call_incremental(
            call_id=call.get('call_id'),
            transcript_text=call.get('transcript_text', ''),
            deal_context=deal_context,
            config=config
        )

        # Extract component scores
        component_scores = {}
        for label in get_components(config):
            key = component_key(label)
            component_scores[key] = result.get('component_scores', {}).get(key)

        return component_scores

    except Exception as e:
        print(f"   ⚠️  Scoring failed: {e}")
        return None


def compute_spread(scores_list):
    """Compute min, max, range for each component across multiple runs."""
    component_spreads = {}

    # Get all component keys from first run
    if not scores_list or not scores_list[0]:
        return None

    for key in scores_list[0].keys():
        values = [scores[key] for scores in scores_list if scores and scores.get(key) is not None]

        if not values:
            component_spreads[key] = {
                'min': None,
                'max': None,
                'range': None,
                'values': []
            }
        else:
            component_spreads[key] = {
                'min': min(values),
                'max': max(values),
                'range': max(values) - min(values),
                'values': values
            }

    return component_spreads


def render_verdict(spreads, config):
    """Determine pass/fail based on spread tolerance from config."""
    if spreads is None:
        return 'INCONCLUSIVE', 'No scoring data available'

    # Get tolerance from config (default: ±1 is acceptable)
    tolerance = config.get('quality_thresholds', {}).get('determinism', {}).get('max_spread', 1)

    failures = []
    for key, metrics in spreads.items():
        if metrics['range'] is None:
            continue
        if metrics['range'] > tolerance:
            failures.append(f"{key}: spread={metrics['range']} (min={metrics['min']}, max={metrics['max']})")

    if failures:
        return 'FAIL', f"Components exceed tolerance (max_spread={tolerance}): " + '; '.join(failures)

    # Report actual spread
    max_spread = max((m['range'] for m in spreads.values() if m['range'] is not None), default=0)
    return 'PASS', f"All components within tolerance (max_spread={tolerance}, observed={max_spread})"


def main(call_id=None, num_runs=5):
    """Run determinism verification check."""
    print("=" * 70)
    print("DETERMINISM VERIFICATION")
    print("=" * 70)
    print(f"\nScore one call {num_runs} times and report per-component spread.")
    print("Reveals LLM jitter rather than assuming determinism.\n")

    # Load config and test call
    print("Loading test call...")
    config = load_client_config()
    call = load_test_call(call_id)

    if not call:
        print("❌ INCONCLUSIVE: No calls available to test\n")
        return 1

    print(f"Testing call: {call.get('call_id')} ({call.get('company_name', 'Unknown')})")
    print(f"Running {num_runs} scoring iterations...\n")

    # Score the call N times
    scores_list = []
    for i in range(num_runs):
        print(f"  Run {i+1}/{num_runs}...", end=' ')
        scores = score_call_once(call, config)
        if scores:
            scores_list.append(scores)
            print("✓")
        else:
            print("✗ (failed)")

    if not scores_list:
        print("\n❌ INCONCLUSIVE: All scoring attempts failed\n")
        return 1

    print(f"\nCompleted {len(scores_list)}/{num_runs} successful runs")

    # Compute spread
    spreads = compute_spread(scores_list)

    # Report per-component spread
    print(f"\nPer-Component Spread:")
    print(f"{'Component':<20} {'Min':>4} {'Max':>4} {'Range':>5} {'Values'}")
    print("-" * 70)

    for label in get_components(config):
        key = component_key(label)
        metrics = spreads.get(key, {})

        if metrics.get('range') is None:
            print(f"{label:<20} {'N/A':>4} {'N/A':>4} {'N/A':>5} (no data)")
        else:
            values_str = ', '.join(str(v) for v in metrics['values'])
            print(f"{label:<20} {metrics['min']:>4} {metrics['max']:>4} {metrics['range']:>5} [{values_str}]")

    # Verdict
    verdict, reason = render_verdict(spreads, config)
    print(f"\n{'=' * 70}")
    print(f"VERDICT: {verdict}")
    print(f"REASON:  {reason}")
    print("=" * 70)

    return 0 if verdict == 'PASS' else 1


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Determinism verification')
    parser.add_argument('--call-id', help='Specific call ID to test')
    parser.add_argument('--runs', type=int, default=5, help='Number of scoring runs (default: 5)')
    args = parser.parse_args()

    sys.exit(main(call_id=args.call_id, num_runs=args.runs))
