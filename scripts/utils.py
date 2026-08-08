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
        'GrowthBook <> ClickHouse' -> 'clickhouse'
    """
    if not name:
        return ''

    # Get vendor name from config
    vendor = 'growthbook'  # Default
    try:
        import yaml
        from pathlib import Path
        config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
        if config_path.exists():
            config = yaml.safe_load(open(config_path))
            org_name = config.get('organization', {}).get('name', '')
            if org_name and 'YOUR_' not in org_name:
                vendor = org_name.lower()
    except Exception:
        pass  # Use default if config fails

    # First: check if name contains vendor with connectors (vendor-first or vendor-last)
    # Split on connector symbols AND dashes to get all parts
    parts = re.split(r'\s*[-–—<>&+/]\s*|\s+and\s+', name, flags=re.IGNORECASE)

    # Remove the vendor/internal company name and empty parts
    company_parts = [
        p.strip() for p in parts
        if p.strip() and vendor not in p.lower()
    ]

    # Use first non-vendor part, or first part if all contain vendor
    if company_parts:
        name = company_parts[0]
    else:
        name = parts[0] if parts else name

    # Clean - remove filler words and session descriptors
    name = re.sub(
        r'\b(and|the|with|vs|versus|for|at|in|of|call|meeting|onsite|demo|kickoff|discovery|scoping)\b',
        '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+', ' ', name).strip().lower()
    name = re.sub(r'[^a-z0-9\s]', '', name)

    slug = name.replace(' ', '-').strip('-')
    return slug if len(slug) >= 3 else ''


METHODOLOGY_COMPONENTS = {
    'MEDDICC': ['Metrics', 'Economic Buyer', 'Decision Criteria',
                'Decision Process', 'Identified Pain',
                'Champion', 'Competition'],
    'MEDDPIC': ['Metrics', 'Economic Buyer', 'Decision Criteria',
                'Decision Process', 'Paper Process',
                'Identified Pain', 'Champion', 'Competition'],
    'SPICED':  ['Situation', 'Pain', 'Impact',
                'Critical Event', 'Decision'],
    'BANT':    ['Budget', 'Authority', 'Need', 'Timeline'],
}


def load_client_config() -> dict:
    import yaml
    from pathlib import Path
    p = Path(__file__).parent.parent / 'config' / 'client.yaml'
    if not p.exists():
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


def get_methodology(config: dict = None) -> str:
    if config is None:
        config = load_client_config()
    m = (config.get('methodology')
         or config.get('organization', {}).get('sales_methodology')
         or 'MEDDICC')
    return str(m).upper()


def get_components(config: dict = None) -> list:
    return METHODOLOGY_COMPONENTS.get(
        get_methodology(config), METHODOLOGY_COMPONENTS['MEDDICC'])


def component_key(name: str) -> str:
    """'Economic Buyer' -> 'economic_buyer';
       'Identified Pain' -> 'identified_pain'"""
    return name.lower().replace(' ', '_')
