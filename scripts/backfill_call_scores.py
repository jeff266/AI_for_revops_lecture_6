#!/usr/bin/env python3
"""
Phase 3 backfill (PROGRESSIVE_SCORING_SPEC): populate call_scores for every deal.

Cumulative-context scoring folds a deal's calls IN DATE ORDER, so the backfill is
per-DEAL sequential (not independent per-call): for each deal, score its calls
oldest->newest, threading the rolled state as prior_state, and upsert each call's
delta row to call_scores.

Resumable + idempotent: a deal whose scoreable calls all already have call_scores
rows at the current scorer_version is skipped (unless FORCE=1); re-running a deal
re-folds from its first call and upserts (call_id PK), so partial deals self-heal.

DRY_RUN=1 scores nothing and writes nothing — it reports coverage (deals, calls,
transcript vs summary, already-done) and an estimated cost from real transcript
sizes, so the model/scope decision can be made before spending.

Env:
  DRY_RUN=1                 measure only, no model calls, no writes
  SCORING_MODEL_ROLE=...    LLMClient role for scoring (default 'generator'=Sonnet;
                            'assessor'=Haiku). Cost/quality tradeoff for the backfill.
  BACKFILL_LIMIT=N          cap number of deals (subset runs)
  BACKFILL_DEAL_IDS=a,b,c   only these deals
  FORCE=1                   re-score even deals already done at this scorer_version
Needs SUPABASE_URL + SUPABASE_SERVICE_KEY (+ ANTHROPIC_API_KEY unless DRY_RUN).
"""
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

import call_scorer as cs  # noqa: E402
from utils import get_components, component_key  # noqa: E402

DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
MODEL_ROLE = os.getenv("SCORING_MODEL_ROLE", "generator")
LIMIT = int(os.getenv("BACKFILL_LIMIT", "0"))
ONLY = [d.strip() for d in os.getenv("BACKFILL_DEAL_IDS", "").split(",") if d.strip()]
FORCE = os.getenv("FORCE", "0") == "1"

# Approximate published per-million-token rates (USD), for the dry-run estimate only.
RATES = {"generator": (3.0, 15.0), "assessor": (0.80, 4.0),
         "evaluator": (0.80, 4.0), "context_builder": (0.80, 4.0)}


def _chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _load(sb):
    """All deal-linked calls grouped by deal, plus a transcript map and the set of
    call_ids already scored at the current scorer_version."""
    from supabase_client import select_all
    calls = select_all(sb, "calls", columns="call_id,deal_id,call_date,summary,company_slug",
                        filters=[("__not_null__", "deal_id")])
    by_deal = defaultdict(list)
    for c in calls:
        if c.get("call_date"):
            by_deal[str(c["deal_id"])].append(c)
    for did in by_deal:
        by_deal[did].sort(key=lambda c: c["call_date"])

    all_ids = [c["call_id"] for cl in by_deal.values() for c in cl]
    tx = {}
    for chunk in _chunked(all_ids, 300):
        for r in select_all(sb, "call_transcripts",
                            columns="call_id,transcript_text,transcript_quality,char_count",
                            filters=[("in_", "call_id", chunk)]):
            tx[r["call_id"]] = r

    done = set()
    try:
        for chunk in _chunked(all_ids, 300):
            for r in select_all(sb, "call_scores", columns="call_id,scorer_version",
                                filters=[("in_", "call_id", chunk)]):
                if r.get("scorer_version") == cs.SCORER_VERSION:
                    done.add(r["call_id"])
    except Exception as e:
        # call_scores may not exist yet (migration 039 not applied). Dry-run does
        # not need it; a live run will fail at upsert, which is the correct signal
        # that the migration must be applied first.
        print(f"  (call_scores not queryable yet: {e}; treating as none-scored)")
    return by_deal, tx, done


def _text_for(call, tx):
    t = tx.get(call["call_id"])
    # Template uses transcript_text not transcript
    if t and (t.get("transcript_text") or "").strip() and t.get("transcript_quality") in ("full", "partial"):
        return t["transcript_text"].strip(), "transcript"
    summ = (call.get("summary") or "").strip()
    if summ:
        return summ, "summary"
    return None, None


def _company_of(calls):
    for c in calls:
        if c.get("company_slug"):
            return c["company_slug"]
    return None


def main():
    if not DRY_RUN and not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — cannot score (or set DRY_RUN=1)"); return 2
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
    if LIMIT:
        deals = deals[:LIMIT]

    rate_in, rate_out = RATES.get(MODEL_ROLE, RATES["generator"])
    print("=" * 78)
    print(f"PHASE 3 BACKFILL call_scores — scorer={cs.SCORER_VERSION}  "
          f"model_role={MODEL_ROLE}  {'DRY RUN' if DRY_RUN else 'LIVE'}")
    print(f"deals(linked)={len(by_deal)}  selected={len(deals)}  "
          f"already-scored calls={len(done)}")
    print("=" * 78)

    client = None
    if not DRY_RUN:
        from llm_client import LLMClient
        client = LLMClient.from_config(MODEL_ROLE)

    deals_processed = deals_skipped = 0
    calls_scored = calls_no_text = calls_est = 0
    est_in = est_out = 0
    tok_in = tok_out = 0

    deals_with_text = 0
    total_linked_calls = 0
    for di, did in enumerate(deals, 1):
        calls = by_deal[did]
        total_linked_calls += len(calls)
        scoreable = [(c, *_text_for(c, tx)) for c in calls]
        no_text = [c for (c, txt, src) in scoreable if not txt]
        calls_no_text += len(no_text)
        scoreable = [(c, txt, src) for (c, txt, src) in scoreable if txt]
        if not scoreable:
            continue
        deals_with_text += 1
        if not FORCE and all(c["call_id"] in done for c, _, _ in scoreable):
            deals_skipped += 1
            continue
        company = _company_of(calls) or did

        if DRY_RUN:
            for c, txt, src in scoreable:
                calls_est += 1
                t_in = (len(txt) // 4) * 2 + 400   # two passes send the transcript
                est_in += t_in; est_out += 600
            continue

        rolled = None
        rows = []
        for c, txt, src in scoreable:
            try:
                r = cs.score_call(txt, {"company": company}, prior_state=rolled, client=client)
            except Exception as e:
                print(f"  ! {company} {c['call_id']}: score error {e}")
                continue
            tok_in += r["input_tokens"]; tok_out += r["output_tokens"]
            rows.append(cs.to_score_row(c["call_id"], did, c["call_date"], r, src))
            # advance rolled state with this call's deltas
            rolled = cs.roll_up([{"call_id": rr["call_id"], "call_date": rr["call_date"],
                                  "components": _row_components(rr)} for rr in rows])
            calls_scored += 1
        for chunk in _chunked(rows, 25):
            sb.table("call_scores").upsert(chunk, on_conflict="call_id").execute()
        deals_processed += 1
        if di % 10 == 0 or di == len(deals):
            print(f"[{di}/{len(deals)}] {company}: {len(rows)} calls scored "
                  f"(running {tok_in} in / {tok_out} out)")

    print("\n" + "=" * 78)
    if DRY_RUN:
        cost = est_in / 1e6 * rate_in + est_out / 1e6 * rate_out
        print(f"DRY RUN — would score {calls_est} calls across {deals_with_text} deals")
        print(f"  linked calls total={total_linked_calls}  scoreable={calls_est}  "
              f"no-text(skipped)={calls_no_text}")
        print(f"  est tokens: ~{est_in:,} in / ~{est_out:,} out")
        print(f"  est cost @ {MODEL_ROLE} (${rate_in}/${rate_out} per M): ~${cost:,.2f}")
        for alt, (ri, ro) in RATES.items():
            if alt in ("generator", "assessor"):
                print(f"    if {alt}: ~${est_in/1e6*ri + est_out/1e6*ro:,.2f}")
        print(f"  (estimate from real transcript sizes; two passes per call)")
    else:
        cost = tok_in / 1e6 * rate_in + tok_out / 1e6 * rate_out
        print(f"BACKFILL COMPLETE — deals processed={deals_processed} skipped(done)={deals_skipped}")
        print(f"  calls scored={calls_scored}  no-text(skipped)={calls_no_text}")
        print(f"  tokens: {tok_in:,} in / {tok_out:,} out   est cost ~${cost:,.2f}")
    print("=" * 78)
    return 0


def _row_components(row):
    """Reconstruct a components dict from a call_scores row for the running fold.

    Template port: Reads from JSONB columns (component_scores, evidence) not fixed
    per-component columns. Methodology-agnostic: MEDDICC gets 7 components, MEDDPIC
    gets 8, SPICED gets 5, BANT gets 4.
    """
    import json

    # Read component_scores JSONB
    scores = row.get("component_scores")
    if isinstance(scores, str):
        try:
            scores = json.loads(scores)
        except Exception:
            scores = {}
    elif not isinstance(scores, dict):
        scores = {}

    # Read evidence JSONB
    ev = row.get("evidence")
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except Exception:
            ev = {}
    elif not isinstance(ev, dict):
        ev = {}

    # Build components dict for current methodology
    out = {}
    for label in get_components():
        key = component_key(label)
        sc = scores.get(key)
        out[key] = {"score": sc, "evidence": ev.get(key)}
    return out


if __name__ == "__main__":
    sys.exit(main())
