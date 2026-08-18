#!/usr/bin/env python3
"""
Run re-enrichment for specific categories after schema
evolution. Always requires explicit confirmation.

Usage:
  # Scan calls never enriched before (safe, additive):
  python scripts/enrichment/run_backfill.py \
    --category build_vs_buy \
    --table objections \
    --limit 200 \
    --yes

  # Re-scan calls already in the ledger, so a newly added
  # category can be applied to historical calls:
  python scripts/enrichment/run_backfill.py \
    --category build_vs_buy --table objections \
    --limit 200 --rescan --yes

WHY --rescan EXISTS
  Adding a category to an extraction prompt does not
  retroactively tag old calls. The extractors skip every
  call already recorded in the enrichment_scans ledger, so
  a plain run finds nothing to do once the backlog is clear
  — the historical calls stay classified under the old
  taxonomy forever.

  --rescan clears the ledger rows for the calls being
  reprocessed AND deletes their existing rows in the target
  table, so the re-extraction replaces them instead of
  duplicating them. That is destructive by design: the
  previous extraction for those calls is discarded and
  redone under the new prompt. It is gated behind explicit
  confirmation and is never run automatically.

Cost: ~$0.004 per call (Haiku). 100 calls ≈ $0.40,
500 calls ≈ $2.00. Always shown before confirmation.
"""

import os, sys, argparse
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

COST_PER_CALL = 0.004

JOB_FOR_TABLE = {
    "objections": "objections",
    "feature_gaps": "feature_gaps",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", required=True,
        help="New category to backfill")
    parser.add_argument("--table",
        choices=["objections", "feature_gaps"],
        default="objections")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--yes", action="store_true",
        help="Skip confirmation prompt")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rescan", action="store_true",
        help="Re-process calls already in the ledger "
             "(destructive: replaces their existing rows)")
    args = parser.parse_args()

    from supabase import create_client
    from supabase_client import select_all

    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"])

    job = JOB_FOR_TABLE[args.table]

    print(f"Backfill: {args.category} → {args.table}")
    print(f"Limit: {args.limit} calls")
    print(f"Estimated cost: "
          f"${args.limit * COST_PER_CALL:.2f} (upper bound)")

    # Report the current footprint of the target category so the
    # operator can compare before/after.
    before = select_all(sb, args.table, columns="category")
    before_n = sum(1 for r in before
                   if r.get("category") == args.category)
    print(f"Existing '{args.category}' rows in "
          f"{args.table}: {before_n}")

    scanned_rows = select_all(
        sb, "enrichment_scans", columns="call_id,job",
        filters=[("eq", "job", job)])
    print(f"Calls already in the '{job}' ledger: "
          f"{len(scanned_rows)}")

    if args.rescan:
        targets = [r["call_id"] for r in scanned_rows][:args.limit]
        print(f"\n--rescan: {len(targets)} previously scanned "
              f"call(s) will be reprocessed.")
        print("  Their existing "
              f"{args.table} rows will be DELETED and rebuilt "
              "under the current extraction prompt.")
        if not targets:
            print("Nothing in the ledger to re-scan.")
            return
    else:
        targets = []
        print("\nNo --rescan: only calls that have never been "
              "scanned will be processed.")
        print("  (If the ledger is already complete, this run "
              "will find nothing to do.)")

    if args.dry_run:
        print("\n--dry-run: no changes made")
        if targets:
            print(f"  Would clear {len(targets)} ledger row(s) "
                  f"and their {args.table} rows.")
        _delegate(args, dry_run=True)
        return

    if not args.yes:
        confirm = input(
            f"Re-enrich up to {args.limit} calls "
            f"for category '{args.category}'? (y/N): ")
        if confirm.lower() != 'y':
            print("Aborted.")
            return

    if targets:
        print(f"\nClearing {len(targets)} ledger row(s) and "
              f"their existing {args.table} rows...")
        deleted_rows, cleared = 0, 0
        for i in range(0, len(targets), 50):
            chunk = targets[i:i + 50]
            res = (sb.table(args.table).delete()
                   .in_("call_id", chunk).execute())
            deleted_rows += len(res.data or [])
            res2 = (sb.table("enrichment_scans").delete()
                    .eq("job", job)
                    .in_("call_id", chunk).execute())
            cleared += len(res2.data or [])
        print(f"  Deleted {deleted_rows} {args.table} row(s), "
              f"cleared {cleared} ledger row(s)")

    _delegate(args, dry_run=False)

    after = select_all(sb, args.table, columns="category")
    after_n = sum(1 for r in after
                  if r.get("category") == args.category)
    print(f"\n'{args.category}' rows in {args.table}: "
          f"{before_n} → {after_n} "
          f"({after_n - before_n:+d})")


def _delegate(args, dry_run: bool):
    """Run the matching extraction script for the target table."""
    if args.table == "objections":
        script = (REPO_ROOT / "scripts" / "enrichment" /
                  "extract_objections.py")
    else:
        script = (REPO_ROOT / "scripts" / "enrichment" /
                  "extract_feature_gaps.py")

    import subprocess
    cmd = [
        sys.executable, str(script),
        "--limit", str(args.limit),
        "--yes",
    ]
    if dry_run:
        cmd.append("--dry-run")

    print(f"\nRunning: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
