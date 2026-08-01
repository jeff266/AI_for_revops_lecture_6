#!/usr/bin/env python3
"""
ETL: Extract call transcripts from CSV files and build call cache.

Reads:
  - data/apollo_transcripts.csv (Apollo.io calls with transcript previews)
  - data/fireflies_transcripts.csv (Fireflies calls with summaries)

Outputs:
  - memory/calls/<company-slug>.json (one file per company with all calls)

Apollo calls are summarized via Claude Haiku (transcript_preview -> summary).
Fireflies calls use summary_text directly (already AI-generated).
"""

import os
import csv
import json
import argparse
import re
from pathlib import Path
from datetime import datetime
from anthropic import Anthropic


def slugify(company_name: str) -> str:
    """Convert company name to slug (e.g., 'Acme Corp' -> 'acme-corp')."""
    slug = company_name.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug


def extract_company_from_title(title: str) -> str:
    """
    Extract company name from call title.

    Common patterns:
    - "Company Name - Topic"
    - "Topic - Company Name"
    - "Company Name: Topic"
    - "First Last (Company Name)"
    """
    if not title:
        return "Unknown"

    # Try dash separator
    if ' - ' in title:
        parts = title.split(' - ')
        # Take first part if it looks like a company (>3 chars, not generic)
        if len(parts[0]) > 3 and not parts[0].lower().startswith(('demo', 'call', 'meeting')):
            return parts[0].strip()
        # Otherwise try second part
        if len(parts) > 1:
            return parts[1].strip()

    # Try colon separator
    if ': ' in title:
        parts = title.split(': ')
        return parts[0].strip()

    # Try parentheses
    paren_match = re.search(r'\(([^)]+)\)$', title)
    if paren_match:
        return paren_match.group(1).strip()

    # Fallback: use first 3 words
    words = title.split()[:3]
    return ' '.join(words)


def summarize_with_haiku(transcript_preview: str, title: str) -> str:
    """Summarize Apollo transcript preview using Claude Haiku."""
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = f"""Summarize this sales call transcript in 2-3 sentences. Focus on:
- What was discussed (product, features, pain points)
- Key participants and their roles
- Next steps or action items

Call Title: {title}

Transcript Preview:
{transcript_preview}

Provide only the summary, no preamble."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text.strip()


def process_apollo_csv(csv_path: Path, calls_by_company: dict, total_summarized: list):
    """Process Apollo CSV and add calls to company dict."""
    print(f"\n📞 Processing Apollo calls from {csv_path}")

    if not csv_path.exists():
        print(f"   ⚠️  File not found, skipping")
        return

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"   Found {len(rows)} Apollo calls")

    for i, row in enumerate(rows, 1):
        title = row.get('title', '')
        transcript_preview = row.get('transcript_preview', '')

        # Skip if no transcript
        if not transcript_preview or len(transcript_preview) < 50:
            continue

        # Extract company
        company = extract_company_from_title(title)
        slug = slugify(company)

        # Summarize with Haiku
        print(f"   [{i}/{len(rows)}] Summarizing: {title[:50]}...")
        try:
            summary = summarize_with_haiku(transcript_preview, title)
            total_summarized[0] += 1
        except Exception as e:
            print(f"      ✗ Error: {e}")
            summary = f"[Summary failed] {transcript_preview[:200]}"

        # Add to company dict
        if slug not in calls_by_company:
            calls_by_company[slug] = {
                "company": company,
                "slug": slug,
                "calls": []
            }

        calls_by_company[slug]["calls"].append({
            "id": row.get('transcript_id', ''),
            "source": "apollo",
            "title": title,
            "date": row.get('date', ''),
            "duration_minutes": int(float(row.get('duration_minutes', 0) or 0)),
            "summary": summary,
            "host": row.get('host', ''),
            "participants": int(float(row.get('participant_count', 0) or 0))
        })


def process_fireflies_csv(csv_path: Path, calls_by_company: dict):
    """Process Fireflies CSV and add calls to company dict."""
    print(f"\n🔥 Processing Fireflies calls from {csv_path}")

    if not csv_path.exists():
        print(f"   ⚠️  File not found, skipping")
        return

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"   Found {len(rows)} Fireflies calls")

    for i, row in enumerate(rows, 1):
        title = row.get('title', '')
        summary_text = row.get('summary_text', '')

        # Skip if no summary
        if not summary_text:
            continue

        # Extract company
        company = extract_company_from_title(title)
        slug = slugify(company)

        # Add to company dict
        if slug not in calls_by_company:
            calls_by_company[slug] = {
                "company": company,
                "slug": slug,
                "calls": []
            }

        calls_by_company[slug]["calls"].append({
            "id": row.get('transcript_id', ''),
            "source": "fireflies",
            "title": title,
            "date": row.get('date', ''),
            "duration_minutes": int(float(row.get('duration_minutes', 0) or 0)),
            "summary": summary_text,
            "organizer": row.get('organizer_email', ''),
            "participants": int(float(row.get('participants_count', 0) or 0)),
            "keywords": row.get('keywords', ''),
            "action_items": row.get('action_items', '')
        })

        if (i % 50) == 0:
            print(f"   [{i}/{len(rows)}] Processed")


def save_call_caches(calls_by_company: dict, output_dir: Path):
    """Save one JSON file per company."""
    print(f"\n💾 Saving call caches to {output_dir}/")

    output_dir.mkdir(parents=True, exist_ok=True)

    for slug, data in calls_by_company.items():
        # Sort calls by date (newest first)
        data["calls"].sort(key=lambda c: c.get("date", ""), reverse=True)

        output_path = output_dir / f"{slug}.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"   ✓ {slug}.json ({len(data['calls'])} calls)")

    print(f"\n✅ Created {len(calls_by_company)} company cache files")


def main():
    parser = argparse.ArgumentParser(description="ETL call transcripts to cache")
    parser.add_argument(
        '--apollo',
        type=str,
        default='data/apollo_transcripts.csv',
        help='Path to Apollo CSV file'
    )
    parser.add_argument(
        '--fireflies',
        type=str,
        default='data/fireflies_transcripts.csv',
        help='Path to Fireflies CSV file'
    )
    args = parser.parse_args()

    # Setup paths
    repo_root = Path(__file__).parent.parent
    apollo_csv = Path(args.apollo)
    fireflies_csv = Path(args.fireflies)
    output_dir = repo_root / 'memory' / 'calls'

    # Track progress
    calls_by_company = {}
    total_summarized = [0]  # Use list to allow mutation in function

    # Process CSVs
    start_time = datetime.now()

    process_apollo_csv(apollo_csv, calls_by_company, total_summarized)
    process_fireflies_csv(fireflies_csv, calls_by_company)

    # Save results
    save_call_caches(calls_by_company, output_dir)

    # Summary
    elapsed = (datetime.now() - start_time).total_seconds()
    total_calls = sum(len(c["calls"]) for c in calls_by_company.values())

    print(f"\n{'='*60}")
    print(f"ETL Complete")
    print(f"{'='*60}")
    print(f"Companies: {len(calls_by_company)}")
    print(f"Total calls: {total_calls}")
    print(f"Apollo calls summarized: {total_summarized[0]}")
    print(f"Time: {elapsed:.1f}s")
    print(f"Output: {output_dir}/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
