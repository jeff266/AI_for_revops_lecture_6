"""
Verification suite for RevOps MEDDICC Agent.

Run during onboarding to help clients find their own bad numbers rather than
inheriting the reference implementation's assumptions.

Available checks:
- coverage.py: What fraction of deals have calls, transcripts, scores, snapshots
- determinism.py: Score one call N times, report per-component spread
- plausibility.py: Deterministic assertions on analytical outputs
- crm_crosscheck.py: Compare agent counts vs CRM and explain difference
- reconciliation.py: Reusable pattern to wrap writes and validate changes

Run all checks:
    python scripts/verify/run_all.py

Run individual check:
    python scripts/verify/coverage.py
    python scripts/verify/determinism.py --runs 10
    python scripts/verify/plausibility.py
    python scripts/verify/crm_crosscheck.py
"""

from .reconciliation import ReconciliationGuard, ReconciliationError

__all__ = ['ReconciliationGuard', 'ReconciliationError']
