#!/usr/bin/env python3
"""
Backfill participant emails for all calls from the
Fireflies API. The file cache only stored a count;
this pulls the actual attendee roster so deal resolution
and intent classification can use email domains — the
trustworthy signal — instead of name-matching.

Usage:
  python scripts/enrichment/fireflies_participants.py \
    --limit 100 --dry-run
  python scripts/enrichment/fireflies_participants.py \
    --limit 2100 --yes

Writes participant_emails and participant_domains into
the calls table (creating stub rows if needed; a later
resolution pass fills company/deal linkage).
"""

import os
import sys
import argparse
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

FIREFLIES_API = "https://api.fireflies.ai/graphql"

# The Fireflies transcript query includes meeting_attendees
TRANSCRIPT_QUERY = """
query Transcripts($limit: Int, $skip: Int) {
  transcripts(limit: $limit, skip: $skip) {
    id
    title
    date
    meeting_attendees {
      displayName
      email
    }
    summary {
      overview
    }
  }
}
"""


def fetch_transcripts(api_key, limit, skip):
    """Fetch transcripts from Fireflies API with pagination."""
    import requests
    resp = requests.post(
        FIREFLIES_API,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        json={"query": TRANSCRIPT_QUERY,
              "variables": {"limit": limit, "skip": skip}},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise Exception(f"GraphQL errors: {data['errors']}")
    return data.get("data", {}).get("transcripts", [])


def extract_emails(attendees):
    """Pull emails from meeting_attendees, return
    (emails, domains)."""
    emails = []
    for a in (attendees or []):
        email = (a.get("email") or "").strip().lower()
        if email and "@" in email:
            emails.append(email)
    domains = sorted(set(
        e.split("@", 1)[1] for e in emails if "@" in e
    ))
    return emails, domains


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100,
        help="Total number of transcripts to fetch")
    parser.add_argument("--batch", type=int, default=50,
        help="Fireflies API page size")
    parser.add_argument("--dry-run", action="store_true",
        help="Show what would be done without writing")
    parser.add_argument("--yes", action="store_true",
        help="Actually write to database")
    parser.add_argument("--only-new", action="store_true",
        help="Only process calls not yet in the calls table")
    args = parser.parse_args()

    if not args.dry_run and not args.yes:
        print("Use --dry-run to preview or --yes to execute")
        sys.exit(1)

    api_key = os.environ.get("FIREFLIES_API_KEY")
    if not api_key:
        print("Set FIREFLIES_API_KEY environment variable")
        sys.exit(1)

    from supabase import create_client
    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"])

    # Get existing call_ids if --only-new
    existing_ids = set()
    if args.only_new:
        existing = sb.table("calls").select("call_id").execute()
        existing_ids = {r["call_id"] for r in existing.data}
        print(f"Found {len(existing_ids)} existing calls in table")

    fetched, updated, skipped = 0, 0, 0
    skip = 0
    no_emails_count = 0

    print(f"Fetching up to {args.limit} transcripts from Fireflies...")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'WRITE'}\n")

    while fetched < args.limit:
        page_size = min(args.batch, args.limit - fetched)
        try:
            transcripts = fetch_transcripts(api_key, page_size, skip)
        except Exception as e:
            print(f"\n❌ Error fetching transcripts: {e}")
            break

        if not transcripts:
            print("No more transcripts available")
            break

        for t in transcripts:
            call_id = t["id"]
            fetched += 1

            # Skip if already in table and --only-new
            if args.only_new and call_id in existing_ids:
                skipped += 1
                continue

            emails, domains = extract_emails(
                t.get("meeting_attendees"))

            if not emails:
                no_emails_count += 1

            if args.dry_run:
                email_str = f"{len(emails)} emails" if emails else "NO EMAILS"
                domain_str = ", ".join(domains) if domains else "none"
                print(f"  {call_id[:24]:24} | {email_str:12} | "
                      f"domains: {domain_str}")
                continue

            # Upsert into calls table — participant data only.
            # Company/deal resolution happens in Task 3.

            # Handle date - could be string or Unix timestamp
            call_date = t.get("date")
            if isinstance(call_date, int):
                # Unix timestamp - convert to ISO date
                from datetime import datetime
                call_date = datetime.fromtimestamp(
                    call_date / 1000).strftime("%Y-%m-%d")
            elif isinstance(call_date, str):
                call_date = call_date[:10] if call_date else None
            else:
                call_date = None

            sb.table("calls").upsert({
                "call_id":            call_id,
                "title":              t.get("title"),
                "call_date":          call_date,
                "participant_emails": emails,
                "participant_domains": domains,
                "participant_count":  len(emails),
                "summary":            (t.get("summary") or {})
                                      .get("overview"),
                "source":             "fireflies",
                "updated_at":         "now()",
            }, on_conflict="call_id").execute()
            updated += 1

        skip += len(transcripts)
        time.sleep(0.5)  # be polite to the API

    print(f"\n{'='*60}")
    print(f"Fetched {fetched} transcripts")
    if args.only_new:
        print(f"Skipped {skipped} already in table")
    if args.dry_run:
        print(f"Calls without emails: {no_emails_count}")
        if no_emails_count > fetched * 0.5:
            print(f"\n⚠️  WARNING: {no_emails_count}/{fetched} calls "
                  f"have no participant emails!")
            print("This suggests meeting_attendees is mostly empty.")
            print("Do NOT proceed with full backfill until this is resolved.")
    else:
        print(f"Updated {updated} call rows with participant data")
        if no_emails_count > 0:
            print(f"⚠️  {no_emails_count} calls have no participant emails")


if __name__ == "__main__":
    main()
