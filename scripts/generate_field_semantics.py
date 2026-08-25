#!/usr/bin/env python3
"""
Generate api/field_semantics.py from config/field_semantics.yaml.
Also writes semantics to data_dictionary table for dynamic path consumption.

Run after editing config/field_semantics.yaml to regenerate the constants module.
"""

import sys
import yaml
from pathlib import Path
from datetime import datetime

# Add paths for Supabase client
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

def load_semantics():
    """Load field_semantics.yaml"""
    config_path = Path(__file__).parent.parent / "config" / "field_semantics.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)

def build_alias_map(stage_map):
    """Build reverse map: alias -> canonical stage_id"""
    alias_to_canonical = {}
    for stage_id, info in stage_map.items():
        # Stage ID itself maps to itself
        alias_to_canonical[stage_id] = stage_id
        # Each alias maps to canonical
        for alias in info.get('aliases', []):
            alias_to_canonical[alias] = stage_id
    return alias_to_canonical

def build_label_map(stage_map):
    """Build reverse map: display label -> stage_id (for CSV imports)"""
    label_to_id = {}
    for stage_id, info in stage_map.items():
        # Primary label
        label = info.get('label')
        if label:
            label_to_id[label] = stage_id
        # Alternate labels (e.g., "Disqualified" for closedlost)
        for alias_label in info.get('alias_labels', []):
            label_to_id[alias_label] = stage_id
    return label_to_id

def generate_module(semantics):
    """Generate api/field_semantics.py from semantics dict"""
    stage_map = semantics['stage_map']
    outcome_buckets = semantics['outcome_buckets']
    field_units = semantics['field_units']
    retired_stages = semantics.get('retired_stages', {})

    alias_map = build_alias_map(stage_map)
    label_map = build_label_map(stage_map)

    # Build the Python module as a string
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')

    module_content = f'''"""
AUTO-GENERATED from config/field_semantics.yaml by scripts/generate_field_semantics.py.
DO NOT EDIT BY HAND. Regenerate after changing the yaml.

Generated: {timestamp}
"""

STAGE_MAP = {repr(stage_map)}

OUTCOME_BUCKETS = {repr(outcome_buckets)}

FIELD_UNITS = {repr(field_units)}

# Hard-deleted stage ids seen only in property history. Acknowledged, but
# deliberately NOT classified — see config/field_semantics.yaml.
RETIRED_STAGES = {repr(retired_stages)}

# Reverse lookup: alias -> canonical stage_id
_ALIAS_TO_CANONICAL = {repr(alias_map)}

# Reverse lookup: display label -> stage_id (for CSV imports with display names)
_LABEL_TO_STAGE_ID = {repr(label_map)}

def canonical_stage(stage_id: str) -> str:
    """
    Resolve a raw stage id (including numeric aliases) to its canonical stage key.
    Unknown ids return the input unchanged.

    Examples:
        canonical_stage('1297321623') -> 'closedwon'
        canonical_stage('closedwon') -> 'closedwon'
        canonical_stage('unknown_stage') -> 'unknown_stage'
    """
    if not stage_id:
        return stage_id
    return _ALIAS_TO_CANONICAL.get(stage_id, stage_id)

def stage_bucket(stage_id: str) -> str:
    """
    Return the pipeline bucket for a stage id:
    'discovery'|'scoping'|'proposal'|'closed_won'|'closed_lost'|'unknown'.

    Resolves aliases first. This REPLACES the _stage_bucket() helper
    currently inline in handlers.py.

    Examples:
        stage_bucket('appointmentscheduled') -> 'discovery'
        stage_bucket('presentationscheduled') -> 'proposal'
        stage_bucket('1297321623') -> 'closed_won'
        stage_bucket('68509551') -> 'closed_lost'
    """
    if not stage_id:
        return 'unknown'
    canonical = canonical_stage(stage_id)
    stage_info = STAGE_MAP.get(canonical)
    if not stage_info:
        return 'unknown'
    return stage_info.get('bucket', 'unknown')

def stage_label(stage_id: str) -> str:
    """
    Human label for a stage id, e.g. 'Technical Evaluation'.
    Returns the stage_id if not found.

    Examples:
        stage_label('presentationscheduled') -> 'Technical Evaluation'
        stage_label('1297321623') -> 'Closed Won'
    """
    if not stage_id:
        return stage_id
    canonical = canonical_stage(stage_id)
    stage_info = STAGE_MAP.get(canonical)
    if not stage_info:
        return stage_id
    return stage_info.get('label', stage_id)

def is_won(stage_id: str) -> bool:
    """
    True if this stage id (or alias) means closed won.

    Examples:
        is_won('closedwon') -> True
        is_won('1297321623') -> True
        is_won('closedlost') -> False
    """
    if not stage_id:
        return False
    bucket = stage_bucket(stage_id)
    return bucket in OUTCOME_BUCKETS['won']

def is_lost(stage_id: str) -> bool:
    """
    True if this stage id (or alias) means closed lost.

    Examples:
        is_lost('closedlost') -> True
        is_lost('68509551') -> True  # Disqualified alias
        is_lost('closedwon') -> False
    """
    if not stage_id:
        return False
    bucket = stage_bucket(stage_id)
    return bucket in OUTCOME_BUCKETS['lost']

def is_open(stage_id: str) -> bool:
    """
    True if the deal is still open (not won/lost).

    Examples:
        is_open('appointmentscheduled') -> True
        is_open('presentationscheduled') -> True
        is_open('closedwon') -> False
        is_open('1297321623') -> False
        is_open('unknown_stage') -> True  # Unknown stages default to open
    """
    if not stage_id:
        return True  # Unknown stages treated as open for safety
    bucket = stage_bucket(stage_id)
    # Unknown bucket also treated as open for safety
    return bucket in OUTCOME_BUCKETS['open'] or bucket == 'unknown'

def stage_transition(stage_id: str) -> str | None:
    """
    The transition key for a stage, e.g. 'discovery_to_scoping'.
    Returns None if no transition defined.

    Examples:
        stage_transition('appointmentscheduled') -> 'discovery_to_scoping'
        stage_transition('closedwon') -> None
    """
    if not stage_id:
        return None
    canonical = canonical_stage(stage_id)
    stage_info = STAGE_MAP.get(canonical)
    if not stage_info:
        return None
    return stage_info.get('transition')

def is_historical_stage(stage_id: str) -> bool:
    \"\"\"
    True if this stage is classified but is not a stage in any live pipeline.

    Such a stage must stay classified so reconstruction can read the history
    that contains it, while being legitimately absent from client.yaml. This
    is a third category, separate from retired_stages (which cannot be
    classified at all).
    \"\"\"
    if not stage_id:
        return False
    info = STAGE_MAP.get(canonical_stage(stage_id))
    return bool(info and info.get('historical'))

def is_retired_stage(stage_id: str) -> bool:
    \"\"\"
    True if this id is an acknowledged hard-deleted stage.

    Acknowledged is not classified: reconstruction still raises on these.
    This exists so the discovery gate can tell "known and unreachable" apart
    from "new and unknown", which is a genuine blocker.
    \"\"\"
    if not stage_id:
        return False
    return str(stage_id) in RETIRED_STAGES

def label_to_stage_id(display_label: str) -> str:
    """
    Convert a display label to its stage ID.
    Used for CSV imports that return display names instead of stage IDs.

    Returns the input unchanged if not found (allowing passthrough for already-canonical IDs).

    Examples:
        label_to_stage_id('Closed Won') -> 'closedwon'
        label_to_stage_id('Disqualified') -> '68509551'
        label_to_stage_id('Discovery') -> 'appointmentscheduled'
        label_to_stage_id('appointmentscheduled') -> 'appointmentscheduled'  # passthrough
    """
    if not display_label:
        return display_label
    return _LABEL_TO_STAGE_ID.get(display_label, display_label)
'''

    return module_content

def write_to_data_dictionary(semantics):
    """
    Write stage semantics to data_dictionary table for dynamic path consumption.
    """
    try:
        from supabase_client import get_supabase
        sb = get_supabase()

        stage_map = semantics['stage_map']

        # Upsert each stage definition
        for stage_id, info in stage_map.items():
            description = (
                f"{info['label']} (bucket: {info['bucket']}). "
                f"Stage ID: '{stage_id}'."
            )

            # Add aliases to description if present
            if info.get('aliases'):
                aliases_str = ', '.join(f"'{a}'" for a in info['aliases'])
                description += f" Aliases: {aliases_str}."

            sb.table('data_dictionary').upsert({
                'table_name': 'deals',
                'column_name': f'stage_{stage_id}',
                'data_type': 'stage_definition',
                'description': description,
                'example_values': [stage_id] + info.get('aliases', []),
                'source': 'field_semantics.yaml'
            }, on_conflict='table_name,column_name').execute()

        print(f"✓ Wrote {len(stage_map)} stage definitions to data_dictionary")

    except Exception as e:
        print(f"⚠ Could not write to data_dictionary (non-fatal): {e}")
        print("  This is OK if running without database credentials.")

def main():
    print("Generating api/field_semantics.py from config/field_semantics.yaml...")

    # Load config
    semantics = load_semantics()

    # Generate module
    module_content = generate_module(semantics)

    # Write to api/field_semantics.py
    output_path = Path(__file__).parent.parent / "api" / "field_semantics.py"
    with open(output_path, 'w') as f:
        f.write(module_content)

    print(f"✓ Generated {output_path}")

    # Write to database
    write_to_data_dictionary(semantics)

    print("\n✓ Generation complete. Remember to commit the generated file.")
    print("  Run tests: PYTHONPATH=scripts:api:. python3 scripts/eval_field_semantics.py")

if __name__ == '__main__':
    main()
