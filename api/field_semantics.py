"""
Field semantics - stage classification and bucketing.

Reads from config/field_semantics.yaml to classify stages as
discovery/scoping/proposal/closed_won/closed_lost.

This is a minimal version for snapshot_deals.py. Full generator-based
version with auto-regeneration can be added later.
"""
import yaml
from pathlib import Path
from typing import Optional

_CACHE = None


def _load_config():
    """Load and cache field_semantics.yaml."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    config_path = Path(__file__).parent.parent / 'config' / 'field_semantics.yaml'
    if not config_path.exists():
        raise FileNotFoundError(f"field_semantics.yaml not found at {config_path}")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Build STAGE_MAP from yaml
    stage_map = {}
    for stage_id, info in config.get('stages', {}).items():
        stage_map[str(stage_id)] = info

    # Build OUTCOME_BUCKETS - read from yaml and build 'open' list
    outcome_buckets = config.get('outcome_buckets', {})
    if 'won' not in outcome_buckets:
        outcome_buckets['won'] = ['closed_won']
    if 'lost' not in outcome_buckets:
        outcome_buckets['lost'] = ['closed_lost']
    if 'open' not in outcome_buckets:
        # Build open list from stage_map buckets that aren't won/lost
        open_buckets = set()
        for stage_id, info in stage_map.items():
            bucket = info.get('bucket', '')
            if bucket and bucket not in outcome_buckets['won'] and bucket not in outcome_buckets['lost']:
                open_buckets.add(bucket)
        outcome_buckets['open'] = list(open_buckets) if open_buckets else ['discovery', 'scoping', 'proposal']

    _CACHE = {
        'stage_map': stage_map,
        'outcome_buckets': outcome_buckets
    }
    return _CACHE


def stage_bucket(stage_id: Optional[str]) -> str:
    """
    Return the pipeline bucket for a stage id:
    'discovery'|'scoping'|'proposal'|'closed_won'|'closed_lost'|'unknown'.

    Examples:
        stage_bucket('appointmentscheduled') -> 'discovery'
        stage_bucket('closedwon') -> 'closed_won'
        stage_bucket('unknown_stage') -> 'unknown'
    """
    if not stage_id:
        return 'unknown'

    config = _load_config()
    stage_info = config['stage_map'].get(str(stage_id))

    if not stage_info:
        return 'unknown'

    return stage_info.get('bucket', 'unknown')


def stage_label(stage_id: Optional[str]) -> str:
    """
    Human label for a stage id, e.g. 'Technical Evaluation'.
    Returns the stage_id if not found.
    """
    if not stage_id:
        return stage_id or ''

    config = _load_config()
    stage_info = config['stage_map'].get(str(stage_id))

    if not stage_info:
        return stage_id

    return stage_info.get('label', stage_id)


def is_won(stage_id: Optional[str]) -> bool:
    """True if this stage id means closed won."""
    if not stage_id:
        return False
    bucket = stage_bucket(stage_id)
    config = _load_config()
    return bucket in config['outcome_buckets']['won']


def is_lost(stage_id: Optional[str]) -> bool:
    """True if this stage id means closed lost."""
    if not stage_id:
        return False
    bucket = stage_bucket(stage_id)
    config = _load_config()
    return bucket in config['outcome_buckets']['lost']


def is_open(stage_id: Optional[str]) -> bool:
    """
    True if the deal is still open (not won/lost).
    Unknown stages default to open for safety.
    """
    if not stage_id:
        return True  # Unknown stages treated as open for safety

    bucket = stage_bucket(stage_id)
    config = _load_config()

    # Unknown bucket also treated as open for safety
    return bucket in config['outcome_buckets']['open'] or bucket == 'unknown'


# Export for point_in_time module
OUTCOME_BUCKETS = None  # Lazy loaded via _load_config()


def get_outcome_buckets():
    """Get OUTCOME_BUCKETS dict (lazy loaded)."""
    global OUTCOME_BUCKETS
    if OUTCOME_BUCKETS is None:
        config = _load_config()
        OUTCOME_BUCKETS = config['outcome_buckets']
    return OUTCOME_BUCKETS
