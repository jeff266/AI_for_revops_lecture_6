#!/usr/bin/env python3
"""
Backfill participant emails and account linkage for all calls
from the Apollo.io API. Apollo provides richer structured data
than Fireflies, including direct HubSpot IDs.

Resolution priority:
  1. accounts[].hubspot_id → direct join to deals.company_id
  2. accounts[].domain → domain matching to deals.company_domain
  3. participants_info[].email domains → fallback if accounts[] empty

Uses the /conversations/search endpoint (0 credits) which
includes participants_info, account_ids, and deals[] — no need
to call the detail endpoint (costs 1 credit per conversation).

Usage:
  python scripts/enrichment/apollo_participants.py \
    --limit 100 --dry-run
  python scripts/enrichment/apollo_participants.py \
    --limit 2000 --yes

Writes participant_emails, participant_domains, and company_id
into the calls table (creating stub rows if needed; a later
resolution pass fills final company/deal linkage).
"""

import os
import sys
import argparse
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

APOLLO_API_BASE = "https://api.apollo.io/api/v1"


def fetch_conversations(api_key, page, per_page):
    """
    Fetch conversations from Apollo /conversations/search endpoint.

    Returns dict with:
      - conversations: list of conversation objects
      - pagination: {page, per_page, total_entries, total_pages}
    """
    import requests
    resp = requests.post(
        f"{APOLLO_API_BASE}/conversations/search",
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": api_key
        },
        json={"page": page, "per_page": per_page},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "conversations": data.get("conversations", []),
        "pagination": data.get("pagination", {})
    }


def extract_participant_data(conv):
    """
    Extract emails and domains from participants_info.

    Returns:
      - emails: list of participant emails (both internal and external)
      - domains: sorted list of unique domains
      - external_domains: domains from external participants only
    """
    emails = []
    external_emails = []

    # participants_info includes all participants with emails
    for p in (conv.get("participants_info") or []):
        email = (p.get("email") or "").strip().lower()
        if email and "@" in email:
            emails.append(email)
            # Track external participant emails separately
            if not p.get("is_internal_participant"):
                external_emails.append(email)

    # Extract all domains
    all_domains = sorted(set(
        e.split("@", 1)[1] for e in emails if "@" in e
    ))

    # Extract external-only domains (for deal matching)
    external_domains = sorted(set(
        e.split("@", 1)[1] for e in external_emails if "@" in e
    ))

    return emails, all_domains, external_domains


def extract_account_data(conv):
    """
    Extract account linking data from accounts_info.

    Returns:
      - hubspot_ids: list of HubSpot company IDs (for direct join)
      - account_domains: list of account domains (for domain matching)

    Note: These are extracted from participants_info in search response.
    The full accounts[] array with domain is only in detail response.
    """
    hubspot_ids = []
    account_names = set()

    # In search response, we don't get accounts[] with domains
    # Only account_ids (Apollo internal IDs) and participants_info with account_name
    # We'll need to rely on participant email domains for matching

    for p in (conv.get("participants_info") or []):
        # Skip internal participants for account matching
        if p.get("is_internal_participant"):
            continue
        account_name = p.get("account_name")
        if account_name:
            account_names.add(account_name)

    # Note: hubspot_id is NOT in the search response participants_info
    # It's only in the detail response accounts[] array
    # For now, return empty - we'll rely on email domain matching
    return hubspot_ids, list(account_names)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100,
        help="Total number of conversations to fetch")
    parser.add_argument("--per-page", type=int, default=50,
        help="Apollo API page size (max 100)")
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

    api_key = os.environ.get("APOLLO_API_KEY")
    if not api_key:
        print("Set APOLLO_API_KEY environment variable")
        sys.exit(1)

    # Initialize Supabase client (skip in dry-run mode if credentials missing)
    sb = None
    existing_ids = set()

    if not args.dry_run or args.only_new:
        if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_KEY"):
            print("❌ Supabase credentials not set (SUPABASE_URL, SUPABASE_SERVICE_KEY)")
            if not args.dry_run:
                sys.exit(1)
            print("⚠️  Dry-run mode: skipping database connection")
        else:
            from supabase import create_client
            sb = create_client(
                os.environ["SUPABASE_URL"],
                os.environ["SUPABASE_SERVICE_KEY"])

            # Get existing call_ids if --only-new
            if args.only_new:
                existing = sb.table("calls").select("call_id").execute()
                existing_ids = {r["call_id"] for r in existing.data}
                print(f"Found {len(existing_ids)} existing calls in table")

    fetched, updated, skipped = 0, 0, 0
    page = 1
    no_emails_count = 0
    internal_count = 0
    failed_count = 0

    print(f"Fetching up to {args.limit} conversations from Apollo...")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'WRITE'}\n")

    while fetched < args.limit:
        try:
            result = fetch_conversations(api_key, page, args.per_page)
            conversations = result["conversations"]
            pagination = result["pagination"]
        except Exception as e:
            print(f"\n❌ Error fetching conversations: {e}")
            break

        if not conversations:
            print("No more conversations available")
            break

        for conv in conversations:
            conv_id = conv.get("id")
            fetched += 1

            # Skip if already in table and --only-new
            if args.only_new and conv_id in existing_ids:
                skipped += 1
                continue

            # Skip failed recordings
            state = conv.get("state")
            if state == "failed":
                failed_count += 1
                if args.dry_run:
                    print(f"  {conv_id[:24]:24} | FAILED | "
                          f"reason: {conv.get('failure_code', 'unknown')}")
                continue

            # Check if internal call using Apollo's flag
            is_internal = conv.get("is_internal", False)
            if is_internal:
                internal_count += 1
                if args.dry_run:
                    print(f"  {conv_id[:24]:24} | INTERNAL | "
                          f"topic: {conv.get('topic', 'Untitled')[:40]}")
                continue

            # Extract participant data
            emails, all_domains, external_domains = extract_participant_data(conv)

            # Extract account data (note: search response doesn't have full accounts[])
            hubspot_ids, account_names = extract_account_data(conv)

            if not emails:
                no_emails_count += 1

            if args.dry_run:
                email_str = f"{len(emails)} emails" if emails else "NO EMAILS"
                domain_str = ", ".join(external_domains[:3]) if external_domains else "none"
                if len(external_domains) > 3:
                    domain_str += f" +{len(external_domains)-3} more"
                account_str = ", ".join(list(account_names)[:2]) if account_names else "none"
                print(f"  {conv_id[:24]:24} | {email_str:12} | "
                      f"ext_domains: {domain_str:30} | "
                      f"accounts: {account_str}")
                continue

            # Upsert into calls table
            # Company/deal resolution happens in resolve_calls.py

            # Handle date - Apollo returns ISO timestamp
            call_date = conv.get("start_time")
            if call_date:
                call_date = call_date[:10]  # Truncate to YYYY-MM-DD

            # Prepare upsert data
            call_data = {
                "call_id":            conv_id,
                "title":              conv.get("topic"),
                "call_date":          call_date,
                "participant_emails": emails,
                "participant_domains": all_domains,
                "participant_count":  len(emails),
                "is_internal":        is_internal,  # Use Apollo's flag directly
                "source":             "apollo",
                "updated_at":         "now()",
            }

            # Note: We don't set company_id here because search response
            # doesn't include accounts[].hubspot_id - that's only in detail response.
            # Resolution via email domains will happen in resolve_calls.py.
            # To get hubspot_id, we'd need to call GET /conversations/{id} which
            # costs 1 credit per call. User said to skip this for now.

            sb.table("calls").upsert(
                call_data, on_conflict="call_id"
            ).execute()
            updated += 1

        # Check if we've reached the limit or last page
        if fetched >= args.limit:
            break
        if page >= pagination.get("total_pages", 0):
            print(f"\nReached last page ({page}/{pagination.get('total_pages', 0)})")
            break

        page += 1
        time.sleep(0.5)  # be polite to the API

    print(f"\n{'='*60}")
    print(f"Fetched {fetched} conversations")
    if failed_count > 0:
        print(f"Skipped {failed_count} failed recordings")
    if internal_count > 0:
        print(f"Skipped {internal_count} internal calls")
    if args.only_new:
        print(f"Skipped {skipped} already in table")
    if args.dry_run:
        print(f"Calls without emails: {no_emails_count}")
        if no_emails_count > (fetched - failed_count - internal_count) * 0.5:
            print(f"\n⚠️  WARNING: {no_emails_count} calls have no participant emails!")
            print("This suggests participants_info is mostly empty.")
            print("Do NOT proceed with full backfill until this is resolved.")
    else:
        print(f"Updated {updated} call rows with participant data")
        if no_emails_count > 0:
            print(f"⚠️  {no_emails_count} calls have no participant emails")

    # Summary of what would be resolved
    if args.dry_run and updated == 0:
        qualifying_calls = fetched - failed_count - internal_count - skipped
        print(f"\n📊 Summary:")
        print(f"  Total processed: {fetched}")
        print(f"  Failed recordings: {failed_count}")
        print(f"  Internal calls: {internal_count}")
        print(f"  Already in table: {skipped}")
        print(f"  Would insert/update: {qualifying_calls}")
        print(f"\nResolution will happen via email domain matching in resolve_calls.py")
        print(f"(accounts[].hubspot_id not available in search response)")


if __name__ == "__main__":
    main()
