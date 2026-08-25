#!/usr/bin/env python3
"""
Run all verification checks and report results.

This is the final onboarding step - helps clients validate their data quality
before deploying the agent to production.

Usage:
    python scripts/verify/run_all.py
    python scripts/verify/run_all.py --skip-determinism  # Skip slow LLM test
"""

import sys
import subprocess
from pathlib import Path
import argparse


def run_check(script_name, args=None):
    """Run a verification check and return (verdict, return_code)."""
    script_path = Path(__file__).parent / script_name

    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)

    print(f"\n{'=' * 70}")
    print(f"Running {script_name}...")
    print(f"{'=' * 70}\n")

    try:
        result = subprocess.run(cmd, capture_output=False, text=True)
        return result.returncode
    except Exception as e:
        print(f"❌ Failed to run {script_name}: {e}")
        return 1


def main():
    """Run all verification checks."""
    parser = argparse.ArgumentParser(description='Run all verification checks')
    parser.add_argument('--skip-determinism', action='store_true',
                       help='Skip determinism check (requires LLM calls)')
    args = parser.parse_args()

    print("=" * 70)
    print("VERIFICATION SUITE")
    print("=" * 70)
    print("\nRunning all verification checks to validate data quality.")
    print("This is the final onboarding step.\n")

    results = {}

    # Run coverage check
    results['coverage'] = run_check('coverage.py')

    # Run determinism check (optional - requires LLM calls)
    if not args.skip_determinism:
        results['determinism'] = run_check('determinism.py', ['--runs', '3'])
    else:
        print("\n[Skipping determinism check - requires LLM calls]")
        results['determinism'] = None

    # Run plausibility check
    results['plausibility'] = run_check('plausibility.py')

    # Run CRM crosscheck
    results['crm_crosscheck'] = run_check('crm_crosscheck.py')

    # Summary
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)

    passed = sum(1 for code in results.values() if code == 0)
    failed = sum(1 for code in results.values() if code and code != 0)
    skipped = sum(1 for code in results.values() if code is None)

    for check, code in results.items():
        if code == 0:
            status = "✓ PASS"
        elif code is None:
            status = "⊘ SKIPPED"
        else:
            status = "✗ FAIL"
        print(f"  {check:20} {status}")

    print(f"\nResults: {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 70)

    # Return non-zero if any checks failed
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
