#!/usr/bin/env python3
"""
Meetings ETL — HubSpot meetings with call recording-based held inference.

Fetches scheduled meetings from HubSpot, matches them to call recordings
(from any source: Fireflies, Gong, Apollo) to determine which meetings
were actually held, and writes to the meetings table.

Usage:
  python etl_meetings.py --since 90d
  python etl_meetings.py --since 2026-08-01 --until 2026-08-31 --dry-run
"""

import os
import sys
import argparse
import requests
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent / '.env')

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_client_config
from sdr_utils import today_in_reporting_tz
from supabase_client import SupabaseWriter

HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')

# Owner ID to email mapping (hardcoded for known SDRs)
# TODO: Move to config or separate mapping table
OWNER_EMAIL_MAP = {
    # Add SDR owner IDs and emails here
    # Example: '87573414': 'sdr@company.com',
}

# Cache for owner ID → email resolution
_owner_cache = {}


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Fetch HubSpot meetings and match to call recordings'
    )
    parser.add_argument(
        '--since',
        type=str,
        default='7d',
        help='Start date (YYYY-MM-DD or "Nd" for N days ago). Default: 7d'
    )
    parser.add_argument(
        '--until',
        type=str,
        default=None,
        help='End date (YYYY-MM-DD, defaults to today)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print meetings without writing to database'
    )

    return parser.parse_args()


def parse_date_arg(date_str: str, config: dict) -> date:
    """Parse date argument (YYYY-MM-DD or Nd)."""
    if date_str.endswith('d'):
        days = int(date_str[:-1])
        return today_in_reporting_tz(config) - timedelta(days=days)
    else:
        return date.fromisoformat(date_str)


def resolve_owner_email(hubspot_owner_id: str) -> str | None:
    """
    Resolve HubSpot owner ID to email using hardcoded mapping.

    The HubSpot owners API requires additional scopes that the private app
    token doesn't have. Instead, use a hardcoded mapping for known SDRs.
    """
    if not hubspot_owner_id:
        return None

    # Use hardcoded mapping
    return OWNER_EMAIL_MAP.get(str(hubspot_owner_id))


def fetch_hubspot_meetings(
    owner_ids: List[str],
    since: date,
    until: date
) -> List[Dict]:
    """
    Fetch meetings from HubSpot CRM objects API.
    Filter by hubspot_owner_id and date range.
    """
    print(f"\nFetching HubSpot meetings...")
    print(f"  Date range: {since} to {until}")
    print(f"  Owners: {len(owner_ids)} SDR(s)")

    url = "https://api.hubapi.com/crm/v3/objects/meetings/search"
    headers = {
        "Authorization": f"Bearer {HUBSPOT_API_KEY}",
        "Content-Type": "application/json"
    }

    # Build filter: (owner=ID1 OR owner=ID2 OR ...) AND (date >= since)
    owner_filters = [
        {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": oid}
        for oid in owner_ids
    ]

    payload = {
        "filterGroups": [{"filters": owner_filters}],
        "properties": [
            "hs_meeting_title",
            "hs_meeting_start_time",
            "hs_meeting_end_time",
            "hs_meeting_outcome",
            "hs_createdate",
            "hubspot_owner_id",
            "hs_meeting_body"
        ],
        "sorts": [{"propertyName": "hs_meeting_start_time", "direction": "DESCENDING"}],
        "limit": 100
    }

    all_meetings = []
    after = None

    while True:
        if after:
            payload["after"] = after

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"  Error fetching meetings: {e}")
            break

        meetings = data.get('results', [])
        all_meetings.extend(meetings)

        # Check for next page
        paging = data.get('paging', {})
        next_page = paging.get('next', {})
        after = next_page.get('after')

        if not after:
            break

    # Filter by date range (HubSpot filter doesn't work reliably)
    date_filtered = []
    for meeting in all_meetings:
        props = meeting.get('properties', {})
        start_time_str = props.get('hs_meeting_start_time')
        if not start_time_str:
            continue

        try:
            # Parse ISO timestamp to date
            start_dt = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
            start_date = start_dt.date()

            if since <= start_date <= until:
                date_filtered.append(meeting)
        except (ValueError, AttributeError):
            continue

    print(f"  Found {len(date_filtered)} meetings in date range")
    return date_filtered


def match_call_recording(meeting: Dict, owner_email: str, sb) -> Dict | None:
    """
    Try to find a call recording matching this meeting.

    Works with any conversation intelligence source (Fireflies, Gong, Apollo).
    A call from ANY recorder confirms a meeting was held.

    Match strategy (in order):
    1. Date match: calls.call_date within ±1 day of meeting scheduled_at
    2. Exact/fuzzy title match (prioritized - handles incomplete company names)
    3. Company name extraction + fuzzy match (fallback)

    Owner matching is NOT used because:
    - Calls table doesn't have owner_email directly
    - Many calls are held by AEs after SDR books them
    - Date + title match is sufficient

    Returns the matched calls row or None.
    """
    props = meeting.get('properties', {})

    # Parse meeting date
    start_time_str = props.get('hs_meeting_start_time')
    if not start_time_str:
        return None

    try:
        start_dt = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
        meeting_date = start_dt.date()
    except (ValueError, AttributeError):
        return None

    # Get meeting title
    title = props.get('hs_meeting_title', '')
    if not title or len(title) < 3:
        return None

    # Normalize meeting title for comparison
    title_normalized = ' '.join(title.lower().strip().split())

    # Query calls within ±1 day
    date_before = (meeting_date - timedelta(days=1)).isoformat()
    date_after = (meeting_date + timedelta(days=1)).isoformat()

    try:
        result = sb.table('calls').select(
            'call_id,company_name,title,company_slug,call_date'
        ).gte('call_date', date_before).lte('call_date', date_after).execute()

        if not result.data:
            return None

        # Find best match by title similarity first, then company name
        best_match = None
        best_score = 0.0

        for call in result.data:
            call_title = (call.get('title') or '').lower().strip()
            call_title_normalized = ' '.join(call_title.split())

            # Strategy 1: Exact/fuzzy title match
            # Calculate simple similarity ratio
            if call_title_normalized and title_normalized:
                # Exact match
                if call_title_normalized == title_normalized:
                    score = 1.0
                # Substring match (one contains the other)
                elif title_normalized in call_title_normalized or call_title_normalized in title_normalized:
                    overlap = min(len(title_normalized), len(call_title_normalized))
                    total = max(len(title_normalized), len(call_title_normalized))
                    score = overlap / total * 0.9
                else:
                    # Fuzzy match using word overlap
                    meeting_words = set(title_normalized.split())
                    call_words = set(call_title_normalized.split())
                    common = meeting_words & call_words
                    total_words = meeting_words | call_words
                    if total_words:
                        score = len(common) / len(total_words) * 0.7

                # Update best match if this is better
                if score > best_score:
                    best_score = score
                    best_match = call

        # Return match if title score is strong (>0.6)
        if best_score > 0.6:
            return best_match

        # Strategy 2: Fall back to company name extraction
        company = extract_company_from_title(title)
        if company and len(company) >= 3:
            company_lower = company.lower()

            for call in result.data:
                call_company = (call.get('company_name') or '').lower()
                call_title = (call.get('title') or '').lower()

                # Check if company name appears in call company or title
                score = 0.0
                if company_lower in call_company:
                    score = len(company_lower) / max(len(call_company), 1) * 0.6
                elif company_lower in call_title:
                    score = len(company_lower) / max(len(call_title), 1) * 0.5

                if score > best_score:
                    best_score = score
                    best_match = call

        # Return match if any score is reasonable (>0.5)
        if best_score > 0.5:
            return best_match

    except Exception as e:
        print(f"  Warning: Call recording match error: {e}")

    return None


def extract_company_from_title(title: str) -> str | None:
    """
    Extract company name from meeting title.

    Common patterns:
    - "Demo Call with X from Company" → "Company"
    - "Company and GrowthBook" → "Company"
    - "GrowthBook Introduction" → None (no external company)
    """
    if not title:
        return None

    # Pattern: "X and GrowthBook" → extract X
    if ' and GrowthBook' in title:
        company = title.split(' and GrowthBook')[0].strip()
        if company and not company.startswith('GrowthBook'):
            return company

    # Pattern: "Demo Call with X from Company" → extract Company
    if ' from ' in title:
        parts = title.split(' from ')
        if len(parts) >= 2:
            company = parts[1].strip()
            # Remove trailing email domains if present
            if '@' in company:
                company = company.split('@')[0]
            return company

    # Pattern: "Company and Something" → extract Company
    if ' and ' in title:
        parts = title.split(' and ')
        company = parts[0].strip()
        if company and 'Demo Call' not in company and 'GrowthBook' not in company:
            return company

    # No clear company pattern
    return None


def determine_held_status(
    meeting: Dict,
    call_match: Dict | None,
    hs_outcome: str | None
) -> tuple:
    """
    Determine held status and confidence.

    Returns: (held: bool | None, confidence: str | None)

    Rules:
    - hs_outcome in ('COMPLETED', 'held') → True, 'hs_outcome'
    - hs_outcome in ('NO_SHOW', 'cancelled') → False, 'hs_outcome'
    - call_match found → True, 'call_recording_match'
    - meeting is in future → None, None
    - meeting is past + no signal → None, None (unknown, not assumed no-show)
    """
    # Check HubSpot outcome first (most authoritative if populated)
    if hs_outcome:
        outcome_lower = hs_outcome.lower()
        if outcome_lower in ('completed', 'held', 'attended'):
            return (True, 'hs_outcome')
        elif outcome_lower in ('no_show', 'no-show', 'cancelled', 'canceled'):
            return (False, 'hs_outcome')

    # Check call recording match
    if call_match:
        return (True, 'call_recording_match')

    # No signal: unknown
    # Conservative: don't assume no-show for past meetings without evidence
    return (None, None)


def main():
    """Main ETL orchestration."""
    args = parse_args()
    config = load_client_config()

    # Parse date range
    until = (
        parse_date_arg(args.until, config)
        if args.until
        else today_in_reporting_tz(config)
    )
    since = parse_date_arg(args.since, config)

    print(f"\n{'='*80}")
    print("MEETINGS ETL")
    print(f"{'='*80}")
    print(f"Date range: {since} to {until}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")

    # Get SDR HubSpot owner IDs from config
    sdr_tools = config.get('sdr_tools', {})
    team_roster = config.get('team_roster', [])

    # For now, use hardcoded mapping
    # TODO: Build roster mapping from config
    owner_ids = list(OWNER_EMAIL_MAP.keys())

    if not owner_ids:
        print("\n⚠️  No SDR owner IDs configured in OWNER_EMAIL_MAP")
        print("   Add SDR HubSpot owner IDs to OWNER_EMAIL_MAP at top of script")
        return

    # Fetch HubSpot meetings
    meetings = fetch_hubspot_meetings(owner_ids, since, until)

    if not meetings:
        print("\n✓ No meetings found in date range")
        return

    # Match to call recordings and determine held status
    print(f"\nMatching to call recordings...")

    # Initialize Supabase for matching (needed even in dry-run)
    sb = SupabaseWriter().client

    enriched_meetings = []
    call_matches = 0
    hs_outcome_known = 0
    unknown_outcome = 0

    for i, meeting in enumerate(meetings, 1):
        props = meeting.get('properties', {})
        meeting_id = meeting.get('id')
        title = props.get('hs_meeting_title', '(no title)')
        start_time = props.get('hs_meeting_start_time')
        hs_outcome = props.get('hs_meeting_outcome')
        owner_id = props.get('hubspot_owner_id')

        owner_email = resolve_owner_email(owner_id)

        # Match to call recording if database available
        call_match = None
        if sb and owner_email:
            call_match = match_call_recording(meeting, owner_email, sb)

        # Determine held status
        held, confidence = determine_held_status(meeting, call_match, hs_outcome)

        # Track stats
        if confidence == 'call_recording_match':
            call_matches += 1
        elif confidence == 'hs_outcome':
            hs_outcome_known += 1
        else:
            unknown_outcome += 1

        enriched = {
            'hubspot_meeting_id': meeting_id,
            'hubspot_owner_id': owner_id,
            'owner_email': owner_email,
            'title': title,
            'scheduled_at': start_time,
            'scheduled_end_at': props.get('hs_meeting_end_time'),
            'booked_at': props.get('hs_createdate'),
            'hs_meeting_outcome': hs_outcome,
            'held': held,
            'held_confidence': confidence,
            'call_recording_id': call_match.get('call_id') if call_match else None,
            'company_name': call_match.get('company_name') if call_match else None,
        }

        enriched_meetings.append(enriched)

        if args.dry_run and i <= 10:
            match_symbol = "✓" if call_match else "✗"
            held_symbol = "HELD" if held else ("NO-SHOW" if held is False else "UNKNOWN")
            print(f"  {match_symbol} {start_time[:10]} | {title[:40]:40} | {held_symbol}")

    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Total meetings:        {len(enriched_meetings)}")
    print(f"Call recording matches: {call_matches}  ({call_matches/len(enriched_meetings)*100:.1f}%)")
    print(f"HubSpot outcome known: {hs_outcome_known}  ({hs_outcome_known/len(enriched_meetings)*100:.1f}%)")
    print(f"Unknown outcome:       {unknown_outcome}  ({unknown_outcome/len(enriched_meetings)*100:.1f}%)")

    if args.dry_run:
        print(f"\n✓ DRY RUN COMPLETE (no data written)")
        return

    # Write to database
    print(f"\nWriting to meetings table...")
    for meeting in enriched_meetings:
        try:
            sb.table('meetings').upsert(
                meeting,
                on_conflict='hubspot_meeting_id'
            ).execute()
        except Exception as e:
            print(f"  Error writing meeting {meeting['title'][:30]}: {e}")

    print(f"\n✓ {len(enriched_meetings)} meetings written to Supabase")


if __name__ == '__main__':
    main()
