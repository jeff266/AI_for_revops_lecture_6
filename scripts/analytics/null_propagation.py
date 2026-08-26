"""
Null-propagation for dollar-weighted analytics (defect 4 / the ledger).

A deal whose value reconstructs to None (no value history as of the snapshot
date — Phase 2b writes a genuine null, not a proxy) must NOT be coalesced to
0.0 inside a dollar sum: that re-fabricates the number Phase 2b removed. The
ledger's prescription is to null-PROPAGATE instead:

  * exclude the unknown-value deal from the sum (from BOTH sides of a ratio),
  * COUNT the exclusion, and
  * if the excluded fraction is material (> max_null_value_pct), return the
    dollar-basis result as null with a reason — the way the sample-size gate
    already returns null for thin data.

The count basis is never affected — counts don't depend on value.
"""
from typing import Iterable, Optional, Dict, Any


def null_propagate(values: Iterable[Optional[float]],
                   max_null_pct: float = 5.0) -> Dict[str, Any]:
    """
    Sum `values` with null propagation.

    Parameters
    ----------
    values       : iterable that may contain None (unknown value).
    max_null_pct : the material threshold, in percent (config
                   forecast_analysis.max_null_value_pct, default 5).

    Returns a dict:
      sum            : sum of the non-null values (float) — the excluded-and-
                       counted total. This is NEVER a zero-filled figure.
      valued_count   : how many values were real (non-null).
      null_count     : how many were None (excluded, counted — not zero-filled).
      total          : valued_count + null_count.
      null_pct       : null_count / total * 100 (0.0 when total == 0).
      basis_null     : True when null_pct > max_null_pct — the dollar result is
                       not trustworthy and callers must surface null, not sum.
      reason         : explanation when basis_null, else None.
      dollar         : sum when trustworthy, else None (the value a caller
                       should actually report for the dollar basis).
    """
    vals = list(values)
    null_count = sum(1 for v in vals if v is None)
    real = [float(v) for v in vals if v is not None]
    valued_count = len(real)
    total = valued_count + null_count
    null_pct = (null_count / total * 100.0) if total else 0.0
    basis_null = null_pct > max_null_pct
    reason = None
    if basis_null:
        reason = (f"{null_count}/{total} deals ({null_pct:.1f}%) have unknown "
                  f"value — exceeds max_null_value_pct {max_null_pct}; dollar "
                  f"basis returns null (count basis unaffected)")
    return {
        'sum': sum(real),
        'valued_count': valued_count,
        'null_count': null_count,
        'total': total,
        'null_pct': null_pct,
        'basis_null': basis_null,
        'reason': reason,
        'dollar': (None if basis_null else sum(real)),
    }
