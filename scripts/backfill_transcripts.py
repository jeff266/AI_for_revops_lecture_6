#!/usr/bin/env python3
"""
Backfill call transcripts into the substrate (STORE_AND_BACKFILL_TRANSCRIPTS,
Phase 4). Iterate existing `calls`, fetch each transcript through the
source-agnostic transcript_store, and upsert into call_transcripts.

Discipline (from the spec):
  - DRY RUN reports per-source counts BEFORE any write (--dry-run).
  - Resumable + idempotent: skips call_ids already in call_transcripts, so a
    re-run continues where it stopped; the table itself is the checkpoint.
  - Batched writes (not row-by-row — an earlier row-by-row job here hit
    connection limits).
  - Retry with backoff on transient fetch failure; a call that still fails is
    recorded 'unavailable' with a reason and the run continues.
  - No source branching in this loop — transcript_store handles the source
    difference; we iterate the configured source priority.
  - Progress printed incrementally.

Needs SUPABASE_URL + SUPABASE_SERVICE_KEY, and the source API keys
(FIREFLIES_API_KEY / APOLLO_API_KEY). Requires migration 041 applied.

Runtime:
- Bounded by one transcript fetch per call (API call to Fireflies/Gong/Apollo)
- Estimate: ~1-3 seconds per call on average (depends on source API latency)
- No LLM calls (free except source API usage)
- Resumable: skips call_ids already in call_transcripts; killed runs continue

Usage:
  python scripts/backfill_transcripts.py --dry-run          # report, no writes
  python scripts/backfill_transcripts.py                    # write
  python scripts/backfill_transcripts.py --source apollo --limit 20
"""
import argparse
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

# Line-buffer stdout so incremental progress survives a kill (CI block-buffers
# stdout by default; a SIGTERM'd run otherwise flushes nothing — a long backfill
# then looks like it did nothing even though batched writes persisted).
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass


def _sources():
    """Configured source priority (fireflies, apollo), from client.yaml."""
    try:
        from adapters import get_source_priority
        pri = get_source_priority()
        if pri:
            return pri
    except Exception:
        pass
    return ["fireflies", "apollo"]


def _done_transcript_ids(client):
    """call_ids that are DONE (resume skips them): rows with text, or TERMINAL
    empties (old calls that will never have a transcript). A RETRY/pending empty
    is re-attempted. is_done() in transcript_store is the shared authority."""
    from supabase_client import select_all
    from transcript_store import is_done
    try:
        rows = select_all(client, "call_transcripts",
                          columns="call_id,transcript_quality,unavailable_reason")
    except Exception as e:
        # Table not applied yet — treat as none done so a dry-run still reports.
        print(f"  ⚠️  could not read call_transcripts ({type(e).__name__}) — "
              "assuming none done (is migration 041/042 applied?)")
        return set()
    return {r["call_id"] for r in rows if r.get("call_id")
            and is_done(r.get("transcript_quality"), r.get("unavailable_reason"))}


def _calls_for_source(client, source):
    from supabase_client import select_all
    rows = select_all(client, "calls", columns="call_id,source,company_name,call_date",
                      filters=[("eq", "source", source)])
    # deterministic order → stable, resumable progress
    rows = [r for r in rows if r.get("call_id")]
    rows.sort(key=lambda r: str(r["call_id"]))
    return rows


def backfill(dry_run=True, only_source=None, limit=None, batch=25):
    from supabase_client import SupabaseWriter
    from transcript_store import fetch_utterances, build_transcript_row, UNAVAILABLE

    writer = SupabaseWriter()
    client = writer.client
    already = _done_transcript_ids(client)
    clients = {}
    sources = [s for s in _sources() if (only_source is None or s == only_source)]
    # Fireflies rate-limits a fast sequential sweep; throttle it. Apollo did 553
    # clean with no throttle. Override via TRANSCRIPT_THROTTLE_SECONDS.
    throttle = {"fireflies": float(os.getenv("TRANSCRIPT_THROTTLE_SECONDS", "1.0")),
                "apollo": 0.0, "gong": 0.0}

    print("=" * 78)
    print(f"TRANSCRIPT BACKFILL — {'DRY RUN (no writes)' if dry_run else 'WRITING'}")
    print(f"sources: {sources}  |  already stored: {len(already)}"
          + (f"  |  limit/source: {limit}" if limit else ""))
    print("=" * 78)

    grand = {}
    for source in sources:
        calls = _calls_for_source(client, source)
        todo = [c for c in calls if str(c["call_id"]) not in already]
        if limit:
            todo = todo[:limit]
        stats = {"calls": len(calls), "already": len(calls) - len(todo),
                 "attempted": 0, "with_text": 0, "unavailable": 0,
                 "deferred": 0, "written": 0, "chars": [], "reasons": Counter()}
        print(f"\n[{source}] {len(calls)} calls, {stats['already']} done, "
              f"{len(todo)} to process  (throttle={throttle.get(source, 0.0)}s)")

        pending = []
        for i, c in enumerate(todo, 1):
            cid = str(c["call_id"])
            utts, err = fetch_utterances(source, cid, clients,
                                         throttle=throttle.get(source, 0.0))
            stats["attempted"] += 1
            if err:
                # Transient fetch failure (e.g. rate limit that outlasted the
                # backoff). Do NOT write a row — leaving the call absent means a
                # later run RE-ATTEMPTS it, instead of recording a false
                # 'unavailable' that resume would skip forever.
                stats["deferred"] += 1
                stats["reasons"][("defer: " + err)[:48]] += 1
            else:
                row = build_transcript_row(source, cid, utts, error=None,
                                           call_date=c.get("call_date"))
                if row.get("transcript_quality") == UNAVAILABLE:
                    stats["unavailable"] += 1   # genuine no-content
                    stats["reasons"][(row.get("unavailable_reason") or "")[:48]] += 1
                else:
                    stats["with_text"] += 1
                    # char_count might be in row already from build_transcript_row,
                    # or compute from transcript_text
                    char_count = row.get("char_count")
                    if char_count is None:
                        text = row.get("transcript_text") or row.get("transcript") or ""
                        char_count = len(text)
                    stats["chars"].append(char_count)
                pending.append(row)

            if not dry_run and len(pending) >= batch:
                stats["written"] += writer.bulk_upsert_transcripts(pending)
                pending = []
            if i % 25 == 0 or i == len(todo):
                print(f"    {i}/{len(todo)}  text={stats['with_text']} "
                      f"no_content={stats['unavailable']} deferred={stats['deferred']}"
                      + ("" if dry_run else f" written={stats['written']}"))

        if not dry_run and pending:
            stats["written"] += writer.bulk_upsert_transcripts(pending)

        # per-source report
        chars = sorted(stats["chars"])
        if chars:
            total_kb = sum(chars) / 1024
            print(f"  → text {stats['with_text']}/{stats['attempted']}  "
                  f"no_content {stats['unavailable']}  deferred {stats['deferred']}  "
                  f"chars: min={chars[0]} median={int(statistics.median(chars))} "
                  f"max={chars[-1]}  est_store={total_kb:.0f}KB")
        else:
            print(f"  → text 0/{stats['attempted']}  deferred {stats['deferred']}")
        for reason, n in stats["reasons"].most_common(6):
            print(f"     ×{n}: {reason}")
        grand[source] = stats

    print("\n" + "=" * 78)
    verb = "WOULD WRITE" if dry_run else "WROTE"
    for source, s in grand.items():
        n = s["with_text"] + s["unavailable"] if dry_run else s["written"]
        tail = (f"  |  {s['deferred']} DEFERRED (transient — re-run to retry)"
                if s["deferred"] else "")
        print(f"  {source:10} {verb} {n} rows "
              f"({s['with_text']} with text, {s['unavailable']} no-content){tail}")
    if dry_run:
        print("\nDRY RUN — nothing written. Re-run without --dry-run to backfill.")
    elif any(s["deferred"] for s in grand.values()):
        print("\nSome calls DEFERRED (transient failures, no row written) — "
              "re-run to retry them; done rows are skipped.")
    print("=" * 78)
    return grand


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report per-source counts, write nothing")
    ap.add_argument("--source", default=None, help="only this source")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap calls processed per source (testing)")
    args = ap.parse_args()
    if not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY")):
        print("cannot run — SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
        return 2
    backfill(dry_run=args.dry_run, only_source=args.source, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
