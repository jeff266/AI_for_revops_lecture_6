#!/usr/bin/env python3
"""
Reconciliation pattern: Capture before/after state and refuse unexplained changes.

Used by any script that mutates analytical data. A write that changes pipeline
value from $2.3M to $1.8M without explanation should abort, not commit.

Example usage:

    from verify.reconciliation import ReconciliationGuard

    # Define what to measure
    def measure_pipeline():
        return {
            'total_value': sum(d['amount'] for d in deals),
            'deal_count': len(deals)
        }

    # Define what changes are expected
    def explain_change(before, after):
        expected_delta = calculate_expected_delta()
        actual_delta = after['total_value'] - before['total_value']
        if abs(actual_delta - expected_delta) < 0.01:
            return f"Expected change: {expected_delta}"
        return None  # Unexplained

    # Use guard
    guard = ReconciliationGuard(
        measure_fn=measure_pipeline,
        explain_fn=explain_change,
        abort_on_unexplained=True
    )

    with guard:
        # Mutate data
        update_pipeline_values()

    # If change was unexplained, guard raises ReconciliationError
"""

import sys
from pathlib import Path
from typing import Callable, Dict, Any, Optional

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class ReconciliationError(Exception):
    """Raised when a write causes unexplained data changes."""
    pass


class ReconciliationGuard:
    """
    Context manager that captures state before/after a write and validates changes.

    Args:
        measure_fn: Function that returns a dict of metrics to track
        explain_fn: Function that takes (before, after) dicts and returns
                   explanation string if change is expected, None if unexplained
        abort_on_unexplained: If True, raise ReconciliationError on unexplained changes
        verbose: If True, print before/after/diff to stdout
    """

    def __init__(
        self,
        measure_fn: Callable[[], Dict[str, Any]],
        explain_fn: Callable[[Dict, Dict], Optional[str]],
        abort_on_unexplained: bool = True,
        verbose: bool = False
    ):
        self.measure_fn = measure_fn
        self.explain_fn = explain_fn
        self.abort_on_unexplained = abort_on_unexplained
        self.verbose = verbose

        self.before = None
        self.after = None
        self.explanation = None
        self.diff = None

    def __enter__(self):
        """Capture state before write."""
        self.before = self.measure_fn()
        if self.verbose:
            print(f"[Reconciliation] Before: {self.before}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Capture state after write and validate."""
        # If an exception occurred in the context, don't reconcile
        if exc_type is not None:
            return False

        self.after = self.measure_fn()
        if self.verbose:
            print(f"[Reconciliation] After:  {self.after}")

        # Compute diff
        self.diff = self._compute_diff(self.before, self.after)
        if self.verbose:
            print(f"[Reconciliation] Diff:   {self.diff}")

        # Check if change is explained
        self.explanation = self.explain_fn(self.before, self.after)

        if self.explanation is None:
            # Unexplained change
            if self.abort_on_unexplained:
                raise ReconciliationError(
                    f"Unexplained data change detected.\n"
                    f"Before: {self.before}\n"
                    f"After:  {self.after}\n"
                    f"Diff:   {self.diff}"
                )
            elif self.verbose:
                print("[Reconciliation] ⚠️  Unexplained change (not aborting)")
        elif self.verbose:
            print(f"[Reconciliation] ✓ Explained: {self.explanation}")

        return False  # Don't suppress exceptions

    def _compute_diff(self, before: Dict, after: Dict) -> Dict:
        """Compute difference between before and after states."""
        diff = {}
        all_keys = set(before.keys()) | set(after.keys())

        for key in all_keys:
            before_val = before.get(key)
            after_val = after.get(key)

            if before_val != after_val:
                # Compute delta for numeric values
                if isinstance(before_val, (int, float)) and isinstance(after_val, (int, float)):
                    diff[key] = {
                        'before': before_val,
                        'after': after_val,
                        'delta': after_val - before_val,
                        'pct_change': ((after_val - before_val) / before_val * 100)
                                     if before_val != 0 else None
                    }
                else:
                    diff[key] = {
                        'before': before_val,
                        'after': after_val
                    }

        return diff

    def get_report(self) -> str:
        """Get a formatted reconciliation report."""
        if self.before is None or self.after is None:
            return "Reconciliation not yet complete"

        lines = ["=" * 70]
        lines.append("RECONCILIATION REPORT")
        lines.append("=" * 70)

        lines.append("\nBefore:")
        for key, val in self.before.items():
            lines.append(f"  {key}: {val}")

        lines.append("\nAfter:")
        for key, val in self.after.items():
            lines.append(f"  {key}: {val}")

        if self.diff:
            lines.append("\nChanges:")
            for key, change in self.diff.items():
                if 'delta' in change:
                    pct_str = f" ({change['pct_change']:+.1f}%)" if change['pct_change'] is not None else ""
                    lines.append(
                        f"  {key}: {change['before']} → {change['after']} "
                        f"(Δ{change['delta']:+.2f}{pct_str})"
                    )
                else:
                    lines.append(f"  {key}: {change['before']} → {change['after']}")
        else:
            lines.append("\nNo changes detected")

        if self.explanation:
            lines.append(f"\nExplanation: {self.explanation}")
        else:
            lines.append("\n⚠️  UNEXPLAINED CHANGE")

        lines.append("=" * 70)
        return "\n".join(lines)


# Example usage and test
def _example():
    """Example usage of ReconciliationGuard."""
    # Mock data
    deals = [
        {'amount': 10000, 'stage': 'open'},
        {'amount': 20000, 'stage': 'open'},
        {'amount': 15000, 'stage': 'won'}
    ]

    def measure():
        return {
            'total_value': sum(d['amount'] for d in deals),
            'deal_count': len(deals),
            'avg_value': sum(d['amount'] for d in deals) / len(deals)
        }

    def explain(before, after):
        # Expected: we're going to close one deal
        expected_delta = 0  # Moving from open to won doesn't change value
        actual_delta = after['total_value'] - before['total_value']

        if abs(actual_delta - expected_delta) < 0.01:
            return "Stage change only, no value change expected"
        return None

    guard = ReconciliationGuard(
        measure_fn=measure,
        explain_fn=explain,
        abort_on_unexplained=False,
        verbose=True
    )

    try:
        with guard:
            # Mutate data - close a deal
            deals[0]['stage'] = 'won'

        print("\n" + guard.get_report())

    except ReconciliationError as e:
        print(f"\n❌ Reconciliation failed: {e}")


if __name__ == '__main__':
    print("ReconciliationGuard example:")
    print("=" * 70)
    _example()
