#!/usr/bin/env python3
"""Generic proposal pipeline. Any analysis that wants to suggest a change
writes here. Nothing here is ever read at runtime by a handler to change
behavior — this is a recommendation ledger, not a config source."""

import os
import yaml
from datetime import datetime, timezone, timedelta
from typing import Optional
from pathlib import Path


# Default evidence bar gates
_DEFAULT_GATES = {
    'enabled': True,
    'min_evidence_count': 30,
    'min_quarters_of_history': 4,
    'min_effect_size_pct': 10,
    'suppress_duplicate_days': 30,
    'max_open_proposals': 10
}


def _load_config():
    """Load proposal engine config from client.yaml."""
    config_path = Path('config/client.yaml')
    if not config_path.exists():
        return _DEFAULT_GATES.copy()

    with open(config_path) as f:
        config = yaml.safe_load(f)

    return config.get('proposal_engine', _DEFAULT_GATES.copy())


def propose(sb, *, entity_type, entity_key, current_value, proposed_value,
            rationale, evidence, evidence_count,
            affects_handlers=False, requires_regeneration=False) -> Optional[dict]:
    """Write a proposal IF it clears the evidence bar and is not a
    duplicate of an open proposal for the same entity_type+entity_key.
    Returns the row, or None if suppressed (and logs why)."""

    config = _load_config()

    # Gate 1: Feature disabled
    if not config.get('enabled', True):
        print('[proposals] Suppressed: proposal_engine.enabled = false')
        return None

    # Gate 2: Evidence count below threshold
    min_evidence = config.get('min_evidence_count', 30)
    if evidence_count < min_evidence:
        print(f'[proposals] Suppressed: evidence_count {evidence_count} < min {min_evidence}')
        return None

    # Gate 3: Effect size too small (if applicable)
    min_effect_size = config.get('min_effect_size_pct', 10) / 100.0
    if 'effect_size' in evidence:
        effect_size = abs(evidence['effect_size'])
        if effect_size < min_effect_size:
            print(f'[proposals] Suppressed: effect_size {effect_size:.1%} < min {min_effect_size:.1%}')
            return None

    # Gate 4: Max open proposals reached
    max_open = config.get('max_open_proposals', 10)
    open_count = sb.table('proposals').select('id', count='exact').eq('status', 'proposed').execute()
    if open_count.count >= max_open:
        print(f'[proposals] Suppressed: {open_count.count} open proposals >= max {max_open}')
        return None

    # Gate 5: Duplicate proposal within suppression window
    suppress_days = config.get('suppress_duplicate_days', 30)
    cutoff = datetime.now(timezone.utc) - timedelta(days=suppress_days)

    recent = sb.table('proposals').select('id, proposed_at').eq(
        'entity_type', entity_type
    ).eq('entity_key', entity_key).eq('status', 'proposed').gte(
        'proposed_at', cutoff.isoformat()
    ).execute()

    if recent.data:
        print(f'[proposals] Suppressed: duplicate proposal for {entity_type}.{entity_key} '
              f'within {suppress_days} days')
        return None

    # All gates passed — write the proposal
    row = {
        'entity_type': entity_type,
        'entity_key': entity_key,
        'current_value': current_value,
        'proposed_value': proposed_value,
        'rationale': rationale,
        'evidence': evidence,
        'evidence_count': evidence_count,
        'status': 'proposed',
        'proposed_by': 'agent',
        'affects_handlers': affects_handlers,
        'requires_regeneration': requires_regeneration
    }

    result = sb.table('proposals').insert(row).execute()

    if result.data:
        print(f'[proposals] Created proposal {result.data[0]["id"]}: '
              f'{entity_type}.{entity_key}')
        return result.data[0]

    return None


def open_proposals(sb, entity_type=None) -> list:
    """Proposals awaiting review."""
    query = sb.table('proposals').select('*').eq('status', 'proposed').order('proposed_at', desc=True)

    if entity_type:
        query = query.eq('entity_type', entity_type)

    result = query.execute()
    return result.data if result.data else []


def approve(sb, proposal_id, reviewed_by, notes=None) -> dict:
    """Mark approved. Does NOT apply the change. If affects_handlers or
    requires_regeneration is true, the returned dict includes the manual
    follow-up steps."""

    # Get the proposal
    result = sb.table('proposals').select('*').eq('id', proposal_id).execute()

    if not result.data:
        raise ValueError(f'Proposal {proposal_id} not found')

    proposal = result.data[0]

    # Update status
    update = {
        'status': 'approved',
        'reviewed_at': datetime.now(timezone.utc).isoformat(),
        'reviewed_by': reviewed_by,
        'review_notes': notes
    }

    sb.table('proposals').update(update).eq('id', proposal_id).execute()

    # Build response with follow-up steps
    response = {
        'proposal_id': proposal_id,
        'entity_type': proposal['entity_type'],
        'entity_key': proposal['entity_key'],
        'status': 'approved',
        'follow_up_steps': []
    }

    if proposal['affects_handlers']:
        response['follow_up_steps'].append(
            'MANUAL: Update handler code to use new value'
        )
        response['follow_up_steps'].append(
            'MANUAL: Run test suite to verify handlers'
        )
        response['follow_up_steps'].append(
            'MANUAL: Deploy updated handlers'
        )

    if proposal['requires_regeneration']:
        response['follow_up_steps'].append(
            'MANUAL: Update config file with new value'
        )
        response['follow_up_steps'].append(
            'MANUAL: Run regeneration script'
        )
        response['follow_up_steps'].append(
            'MANUAL: Commit regenerated module'
        )

    if not proposal['affects_handlers'] and not proposal['requires_regeneration']:
        response['follow_up_steps'].append(
            'MANUAL: Update config file with new value'
        )

    response['follow_up_steps'].append(
        'NOTE: Approval marks intent only. Config changes remain manual.'
    )

    return response


def reject(sb, proposal_id, reviewed_by, notes=None) -> dict:
    """Mark rejected with reason."""

    # Get the proposal
    result = sb.table('proposals').select('*').eq('id', proposal_id).execute()

    if not result.data:
        raise ValueError(f'Proposal {proposal_id} not found')

    proposal = result.data[0]

    # Update status
    update = {
        'status': 'rejected',
        'reviewed_at': datetime.now(timezone.utc).isoformat(),
        'reviewed_by': reviewed_by,
        'review_notes': notes
    }

    sb.table('proposals').update(update).eq('id', proposal_id).execute()

    return {
        'proposal_id': proposal_id,
        'entity_type': proposal['entity_type'],
        'entity_key': proposal['entity_key'],
        'status': 'rejected',
        'reason': notes
    }


def supersede(sb, old_id, new_id) -> None:
    """Mark old proposal as superseded by new one."""

    # Verify both proposals exist
    old_result = sb.table('proposals').select('id').eq('id', old_id).execute()
    new_result = sb.table('proposals').select('id').eq('id', new_id).execute()

    if not old_result.data:
        raise ValueError(f'Old proposal {old_id} not found')
    if not new_result.data:
        raise ValueError(f'New proposal {new_id} not found')

    # Update old proposal
    sb.table('proposals').update({
        'status': 'superseded',
        'superseded_by_id': new_id
    }).eq('id', old_id).execute()

    print(f'[proposals] Proposal {old_id} superseded by {new_id}')
