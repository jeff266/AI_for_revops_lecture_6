#!/usr/bin/env python3
"""
Merge duplicate call cache files for the same company.
Run after ETL if you see ambiguous slug warnings.

Usage:
  python scripts/dedupe_cache.py

Shows duplicates and merges on confirmation.
"""
import json
from pathlib import Path
from collections import defaultdict

CALLS_DIR = Path(__file__).parent.parent / 'memory' / 'calls'


def get_base_slug(stem: str) -> str:
    """Extract the company name from a cache filename."""
    # Remove common vendor suffixes/prefixes
    stem = stem.replace('growthbook-', '') \
               .replace('-growthbook', '')
    # Take first meaningful segment
    return stem.split('-')[0] if '-' in stem else stem


def main():
    files = list(CALLS_DIR.glob('*.json'))
    files = [f for f in files if f.name != '.gitkeep']

    # Group by base slug
    groups = defaultdict(list)
    for f in files:
        base = get_base_slug(f.stem)
        groups[base].append(f)

    duplicates = {k: v for k, v in groups.items()
                  if len(v) > 1}

    if not duplicates:
        print('No duplicate cache files found.')
        return

    print(f'Found {len(duplicates)} potential duplicates:\n')
    for base, files in sorted(duplicates.items()):
        print(f'  {base}:')
        for f in files:
            d = json.load(open(f))
            print(f'    {f.name} ({len(d.get("calls",[]))} calls)')

    print()
    confirm = input('Merge duplicates? (y/N): ')
    if confirm.lower() != 'y':
        print('Aborted.')
        return

    for base, dupe_files in sorted(duplicates.items()):
        # Collect all calls, deduplicate by ID
        all_calls = {}
        company_name = ''
        for f in dupe_files:
            d = json.load(open(f))
            company_name = company_name or d.get('company', '')
            for call in d.get('calls', []):
                all_calls[call['id']] = call

        merged = sorted(all_calls.values(),
                        key=lambda c: c.get('date', ''))

        # Write to canonical name (shortest = cleanest)
        canonical = min(dupe_files, key=lambda f: len(f.stem))
        with open(canonical, 'w') as out:
            json.dump({
                'company': company_name,
                'calls': merged
            }, out, indent=2)

        # Delete the others
        for f in dupe_files:
            if f != canonical:
                f.unlink()
                print(f'  Deleted: {f.name}')
        print(f'  Merged → {canonical.name} ({len(merged)} calls)')


if __name__ == '__main__':
    main()
