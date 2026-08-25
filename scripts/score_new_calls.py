#!/usr/bin/env python3
"""
Daily incremental call scoring (PROGRESSIVE_SCORING_SPEC, Phase 5b).

Runs at the tail of daily-calls-etl, right after resolve_calls has linked the
night's new calls to deals. It scores only the NEW (not-yet-scored) calls and
upserts their call_scores deltas — so the progressive roll-up is current each
morning without re-running the whole backfill.

Cumulative-context scoring means a new call's score depends on the deal's rolled
state THROUGH the calls before it. So this does not score calls in isolation:

  * For a deal with new calls that all come AFTER its already-scored calls
    (the normal case — a fresh call from last night), it reconstructs the prior
    rolled state from the stored call_scores rows and folds only the new calls
    forward, threading that state. Old calls are not re-scored.

  * If a new call lands BEFORE an already-scored call (a late/back-dated
    transcript), the append is unsafe — the fold order changed — so that deal is
    re-folded in full (correctness over cost). Full re-scores are also what the
    backfill does; this only decides WHEN a full re-fold is needed.

Idempotent: a deal whose scoreable calls are all already scored at the current
scorer_version is skipped. Reuses backfill_call_scores' loaders so there is one
book-loading + one fold implementation.

Env:
  DRY_RUN=1              report what would be scored; no model calls, no writes
  SCORING_MODEL_ROLE=... LLMClient role (default 'generator'=Sonnet)
  SCORE_DEAL_IDS=a,b,c   restrict to these deals
  SCORE_LIMIT=N          cap number of deals with new calls to process
Needs SUPABASE_URL + SUPABASE_SERVICE_KEY (+ ANTHROPIC_API_KEY unless DRY_RUN).
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

import call_scorer as cs  # noqa: E402
from backfill_call_scores import (  # noqa: E402  (one book-loader, shared)
    _load, _text_for, _company_of, _chunked, _row_components,
)
from utils import get_components, component_key  # noqa: E402

DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
MODEL_ROLE = os.getenv("SCORING_MODEL_ROLE", "generator")
ONLY = [d.strip() for d in os.getenv("SCORE_DEAL_IDS", "").split(",") if d.strip()]
LIMIT = int(os.getenv("SCORE_LIMIT", "0"))
RATES = {"generator": (3.0, 15.0), "assessor": (0.80, 4.0)}


def _stored_rows_for(sb, call_ids):
    """Stored call_scores rows for these call_ids at the current scorer_version,
    as {call_id: row}. Empty if the table isn't queryable yet.

    Template port: Reads JSONB columns (component_scores, evidence) not fixed
    per-component columns.
    """
    out = {}
    if not call_ids:
        return out
    from supabase_client import select_all
    cols = "call_id,deal_id,call_date,component_scores,evidence,scorer_version"
    try:
        for chunk in _chunked(list(call_ids), 300):
            for r in select_all(sb, "call_scores", columns=cols,
                                filters=[("in_", "call_id", chunk)]):
                if r.get("scorer_version") == cs.SCORER_VERSION:
                    out[r["call_id"]] = r
    except Exception as e:
        print(f"  (call_scores not queryable: {e})")
    return out


def _fold_rows_from_stored(stored):
    """stored rows -> [{call_id, call_date, components}] for roll_up()."""
    return [{"call_id": r["call_id"], "call_date": r.get("call_date"),
             "components": _row_components(r)} for r in stored]


def plan_deal(scoreable, done, stored_by_id):
    """Decide, purely, how a deal is scored this run.

    scoreable: [(call, text, source)] in date order, text present.
    done: set of already-scored call_ids (current scorer_version).
    stored_by_id: {call_id: stored call_scores row} for done calls.

    Returns (mode, prior_fold_rows, to_score) where:
      mode ∈ {"skip", "incremental", "full"}
      prior_fold_rows: fold-input rows seeding rolled state (incremental only)
      to_score: the [(call, text, source)] to actually score
    """
    new = [(c, t, s) for (c, t, s) in scoreable if c["call_id"] not in done]
    if not new:
        return ("skip", [], [])
    prior = [(c, t, s) for (c, t, s) in scoreable if c["call_id"] in done]
    have_all_prior_rows = all(c["call_id"] in stored_by_id for (c, _, _) in prior)
    if prior and have_all_prior_rows:
        latest_prior_date = max((c.get("call_date") or "") for (c, _, _) in prior)
        earliest_new_date = min((c.get("call_date") or "") for (c, _, _) in new)
        if earliest_new_date >= latest_prior_date:
            prior_rows = _fold_rows_from_stored(
                [stored_by_id[c["call_id"]] for (c, _, _) in prior])
            return ("incremental", prior_rows, new)
    # No usable prior state, or out-of-order arrival → re-fold the whole deal.
    return ("full", [], scoreable)


def _fold(to_score, prior_fold_rows, did, company, client):
    """Score to_score in date order, threading rolled state seeded from
    prior_fold_rows. Returns (new_rows, tok_in, tok_out)."""
    fold_rows = list(prior_fold_rows)
    rolled = cs.roll_up(fold_rows) if fold_rows else None
    new_rows, tok_in, tok_out = [], 0, 0
    for c, txt, src in to_score:
        try:
            r = cs.score_call(txt, {"company": company}, prior_state=rolled, client=client)
        except Exception as e:
            print(f"  ! {company} {c['call_id']}: score error {e}")
            continue
        tok_in += r["input_tokens"]
        tok_out += r["output_tokens"]
        row = cs.to_score_row(c["call_id"], did, c["call_date"], r, src)
        new_rows.append(row)
        fold_rows.append({"call_id": row["call_id"], "call_date": row["call_date"],
                          "components": _row_components(row)})
        rolled = cs.roll_up(fold_rows)
    return new_rows, tok_in, tok_out


def main():
    if not DRY_RUN and not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — cannot score (or set DRY_RUN=1)")
        return 2
    try:
        from api.db import get_supabase
        sb = get_supabase()
    except Exception:
        from supabase_client import SupabaseWriter
        sb = SupabaseWriter().client

    by_deal, tx, done = _load(sb)
    deals = sorted(by_deal.keys())
    if ONLY:
        deals = [d for d in deals if d in ONLY]

    rate_in, rate_out = RATES.get(MODEL_ROLE, RATES["generator"])
    print("=" * 78)
    print(f"DAILY INCREMENTAL SCORING — scorer={cs.SCORER_VERSION}  "
          f"model_role={MODEL_ROLE}  {'DRY RUN' if DRY_RUN else 'LIVE'}")
    print(f"deals(linked)={len(by_deal)}  already-scored calls={len(done)}")
    print("=" * 78)

    client = None
    if not DRY_RUN:
        from llm_client import LLMClient
        client = LLMClient.from_config(MODEL_ROLE)

    deals_incremental = deals_full = deals_skipped = 0
    calls_scored = calls_new_seen = 0
    tok_in = tok_out = 0
    processed = 0

    for did in deals:
        calls = by_deal[did]
        scoreable = [(c, *_text_for(c, tx)) for c in calls]
        scoreable = [(c, t, s) for (c, t, s) in scoreable if t]
        if not scoreable:
            continue
        new_ids = [c["call_id"] for (c, _, _) in scoreable if c["call_id"] not in done]
        if not new_ids:
            deals_skipped += 1
            continue

        # Only now (deal has new calls) fetch its stored rows for prior state.
        prior_ids = [c["call_id"] for (c, _, _) in scoreable if c["call_id"] in done]
        stored_by_id = _stored_rows_for(sb, prior_ids) if prior_ids else {}
        mode, prior_rows, to_score = plan_deal(scoreable, done, stored_by_id)
        if mode == "skip":
            deals_skipped += 1
            continue
        calls_new_seen += len(new_ids)
        company = _company_of(calls) or did

        if LIMIT and processed >= LIMIT:
            print(f"  (SCORE_LIMIT={LIMIT} reached; {did} and beyond deferred)")
            break

        if DRY_RUN:
            n = len(to_score)
            print(f"  {company} [{did}]: mode={mode}  would score {n} calls "
                  f"({len(new_ids)} new)")
            calls_scored += n
            for c, txt, src in to_score:
                tok_in += (len(txt) // 4) * 2 + 400
                tok_out += 600
            deals_incremental += mode == "incremental"
            deals_full += mode == "full"
            processed += 1
            continue

        rows, ti, to = _fold(to_score, prior_rows, did, company, client)
        for chunk in _chunked(rows, 25):
            sb.table("call_scores").upsert(chunk, on_conflict="call_id").execute()
        tok_in += ti
        tok_out += to
        calls_scored += len(rows)
        deals_incremental += mode == "incremental"
        deals_full += mode == "full"
        processed += 1
        print(f"  {company} [{did}]: mode={mode}  scored {len(rows)} calls "
              f"({len(new_ids)} new)  running {tok_in} in / {tok_out} out")

    cost = tok_in / 1e6 * rate_in + tok_out / 1e6 * rate_out
    print("\n" + "=" * 78)
    tag = "DRY RUN — would score" if DRY_RUN else "COMPLETE — scored"
    print(f"{tag} {calls_scored} calls across {processed} deals "
          f"(incremental={deals_incremental}, full-refold={deals_full}, "
          f"skipped-done={deals_skipped})")
    print(f"  new calls seen={calls_new_seen}")
    print(f"  {'est ' if DRY_RUN else ''}tokens: ~{tok_in:,} in / ~{tok_out:,} out"
          f"   {'est ' if DRY_RUN else ''}cost ~${cost:,.2f}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
