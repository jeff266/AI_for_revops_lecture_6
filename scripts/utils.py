"""
Shared utility functions for MEDDICC agent.

This module provides common functionality used across ETL and analysis scripts.
"""

import re


def slugify(name: str) -> str:
    """
    Convert a company name to a cache file slug.
    MUST be identical across etl_calls.py, etl_deals.py,
    and run_nightly.py. Uses hyphens to match existing cache.

    Examples:
        'Acme Corp' -> 'acme-corp'
        'Scale AI' -> 'scale-ai'
        'Notion Labs Inc' -> 'notion-labs-inc'
        'Skyscanner + GrowthBook' -> 'skyscanner'
    """
    if not name:
        return ''

    # Split on session descriptors before the dash
    parts = re.split(r'\s*[-–—]\s+', name, maxsplit=1)
    company_part = parts[0]

    # Remove vendor name
    company_part = re.sub(r'growthbook', '', company_part, flags=re.IGNORECASE)

    # Remove connectors
    company_part = re.sub(r'[+<>&/,]', ' ', company_part)

    # Remove filler words
    company_part = re.sub(
        r'\b(and|the|with|vs|versus|for|at|in|of)\b',
        '', company_part, flags=re.IGNORECASE
    )

    # Clean and lowercase
    company_part = re.sub(r'\s+', ' ', company_part).strip().lower()
    company_part = re.sub(r'[^a-z0-9\s]', '', company_part)

    # Use hyphens (matches existing 905 cache files)
    slug = company_part.replace(' ', '-').strip('-')

    return slug if len(slug) >= 3 else ''
