#!/usr/bin/env python3
"""
Proposal pipeline validation tests.

Guards against:
- Proposals bypassing evidence bar
- Approval mutating config files
- Handlers reading from proposals table at runtime

The critical test: test_approve_does_not_mutate_any_config_file.
This is the mechanical enforcement of the gated-loop design.
"""

import sys
import os
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_mock_sb():
    """Create a mock Supabase client that returns empty results by default."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_execute = MagicMock()
    mock_insert = MagicMock()
    mock_update = MagicMock()
    mock_delete = MagicMock()

    # Chain the mocks
    mock_sb.table.return_value = mock_table
    mock_table.select.return_value = mock_select
    mock_table.insert.return_value = mock_insert
    mock_table.update.return_value = mock_update
    mock_table.delete.return_value = mock_delete

    # Default responses
    mock_select.execute.return_value.data = []
    mock_select.execute.return_value.count = 0
    mock_insert.execute.return_value.data = []
    mock_update.execute.return_value.data = []
    mock_delete.execute.return_value = MagicMock()

    # Allow chaining for filters
    mock_select.eq.return_value = mock_select
    mock_select.gte.return_value = mock_select
    mock_update.eq.return_value = mock_update
    mock_delete.ilike.return_value = mock_delete

    return mock_sb


def test_propose_suppressed_below_evidence_bar():
    """
    Proposal with evidence_count below min_evidence_count is suppressed.
    """
    print("\n[TEST] Propose suppressed below evidence bar")

    from scripts.proposals import propose
    sb = _make_mock_sb()

    # Attempt to propose with low evidence count (below min 30)
    result = propose(
        sb,
        entity_type='coverage_methodology',
        entity_key='test_anchor_week_low_evidence',
        current_value={'anchor_week': 3},
        proposed_value={'anchor_week': 5},
        rationale='Test proposal with insufficient evidence',
        evidence={'quarters_analyzed': 2, 'deals_in_cohort': 15},
        evidence_count=15,  # Below min of 30
        affects_handlers=False,
        requires_regeneration=False
    )

    if result is not None:
        raise AssertionError(f'Expected None, got proposal {result["id"]}')

    print('  ✓ Proposal suppressed: evidence_count 15 < min 30')


def test_propose_suppressed_below_effect_size():
    """
    Proposal with effect_size below min_effect_size_pct is suppressed.
    """
    print("\n[TEST] Propose suppressed below effect size")

    from scripts.proposals import propose
    sb = _make_mock_sb()

    # Attempt to propose with low effect size (below min 10%)
    result = propose(
        sb,
        entity_type='coverage_methodology',
        entity_key='test_coverage_target_low_effect',
        current_value={'coverage_target': 3.0},
        proposed_value={'coverage_target': 3.2},
        rationale='Test proposal with insufficient effect size',
        evidence={
            'quarters_analyzed': 6,
            'deals_in_cohort': 100,
            'measured_value': 3.2,
            'effect_size': 0.067  # 6.7% change, below min 10%
        },
        evidence_count=100,
        affects_handlers=False,
        requires_regeneration=False
    )

    if result is not None:
        raise AssertionError(f'Expected None, got proposal {result["id"]}')

    print('  ✓ Proposal suppressed: effect_size 6.7% < min 10%')


def test_propose_suppressed_when_duplicate_open():
    """
    Proposal for same entity_type+entity_key within suppression window is blocked.
    """
    print("\n[TEST] Propose suppressed when duplicate open")

    from scripts.proposals import propose
    sb = _make_mock_sb()

    # Mock first proposal succeeding - insert returns the created row
    first_proposal_row = {
        'id': 'test-proposal-123',
        'entity_type': 'coverage_methodology',
        'entity_key': 'test_duplicate_suppression',
        'status': 'proposed'
    }
    sb.table.return_value.insert.return_value.execute.return_value.data = [first_proposal_row]

    # First proposal - should succeed (count=0, no duplicates)
    sb.table.return_value.select.return_value.execute.return_value.count = 0
    sb.table.return_value.select.return_value.execute.return_value.data = []

    first = propose(
        sb,
        entity_type='coverage_methodology',
        entity_key='test_duplicate_suppression',
        current_value={'anchor_week': 3},
        proposed_value={'anchor_week': 5},
        rationale='First proposal',
        evidence={
            'quarters_analyzed': 6,
            'deals_in_cohort': 150,
            'effect_size': 0.25
        },
        evidence_count=150
    )

    if first is None:
        raise AssertionError('First proposal should succeed')

    # Now mock duplicate check returning the existing proposal
    sb.table.return_value.select.return_value.execute.return_value.data = [{
        'id': 'test-proposal-123',
        'proposed_at': datetime.now(timezone.utc).isoformat()
    }]

    # Attempt duplicate proposal (should be suppressed)
    duplicate = propose(
        sb,
        entity_type='coverage_methodology',
        entity_key='test_duplicate_suppression',
        current_value={'anchor_week': 3},
        proposed_value={'anchor_week': 6},
        rationale='Duplicate proposal (different value)',
        evidence={
            'quarters_analyzed': 7,
            'deals_in_cohort': 200,
            'effect_size': 0.30
        },
        evidence_count=200
    )

    if duplicate is not None:
        raise AssertionError(f'Duplicate should be suppressed, got proposal {duplicate["id"]}')

    print(f'  ✓ First proposal {first["id"]} succeeded')
    print('  ✓ Duplicate proposal suppressed within 30-day window')


def test_propose_suppressed_at_max_open_proposals():
    """
    Proposal when max_open_proposals limit is reached is suppressed.
    """
    print("\n[TEST] Propose suppressed at max open proposals")

    from scripts.proposals import propose
    sb = _make_mock_sb()

    # Mock open count at the limit (10)
    sb.table.return_value.select.return_value.execute.return_value.count = 10

    result = propose(
        sb,
        entity_type='coverage_methodology',
        entity_key='test_max_open_limit',
        current_value={'anchor_week': 3},
        proposed_value={'anchor_week': 5},
        rationale='Test proposal when at max',
        evidence={
            'quarters_analyzed': 6,
            'deals_in_cohort': 150,
            'effect_size': 0.25
        },
        evidence_count=150
    )

    if result is not None:
        raise AssertionError(
            f'Proposal should be suppressed at max limit, got {result["id"]}'
        )

    print(f'  ✓ Proposal suppressed: 10 open >= max 10')


def test_approve_does_not_mutate_any_config_file():
    """
    CRITICAL: Approval marks intent, never edits config.

    Snapshot config/*.yaml checksums, approve a proposal, assert every
    checksum is unchanged. This is the mechanical enforcement of the
    gated-loop design.
    """
    print("\n[TEST] Approve does not mutate any config file")

    from scripts.proposals import propose, approve
    sb = _make_mock_sb()

    # Snapshot all config file checksums
    config_dir = Path('config')
    config_files = list(config_dir.glob('*.yaml')) + list(config_dir.glob('*.yml'))

    if not config_files:
        raise FileNotFoundError('No config files found in config/')

    def file_checksum(path):
        """Calculate MD5 checksum of file."""
        return hashlib.md5(path.read_bytes()).hexdigest()

    checksums_before = {f: file_checksum(f) for f in config_files}

    # Mock proposal creation succeeding
    proposal_row = {
        'id': 'test-proposal-456',
        'entity_type': 'coverage_methodology',
        'entity_key': 'test_approval_no_mutation',
        'affects_handlers': True,
        'requires_regeneration': True,
        'status': 'proposed'
    }
    sb.table.return_value.insert.return_value.execute.return_value.data = [proposal_row]

    # Mock open count and duplicate check as empty
    sb.table.return_value.select.return_value.execute.return_value.count = 0
    sb.table.return_value.select.return_value.execute.return_value.data = []

    # Create proposal
    proposal = propose(
        sb,
        entity_type='coverage_methodology',
        entity_key='test_approval_no_mutation',
        current_value={'anchor_week': 3},
        proposed_value={'anchor_week': 5},
        rationale='Test that approval does not mutate config',
        evidence={
            'quarters_analyzed': 6,
            'deals_in_cohort': 150,
            'effect_size': 0.25
        },
        evidence_count=150,
        affects_handlers=True,
        requires_regeneration=True
    )

    if proposal is None:
        raise AssertionError('Proposal should succeed (clears evidence bar)')

    # Mock the proposal retrieval for approve()
    sb.table.return_value.select.return_value.execute.return_value.data = [proposal_row]

    # Approve the proposal
    response = approve(sb, proposal['id'], reviewed_by='test_suite', notes='Test approval')

    # Verify response includes manual steps
    if not response.get('follow_up_steps'):
        raise AssertionError('Approval response should include follow_up_steps')

    # Verify config files unchanged
    checksums_after = {f: file_checksum(f) for f in config_files}

    changed_files = []
    for f in config_files:
        if checksums_before[f] != checksums_after[f]:
            changed_files.append(f.name)

    if changed_files:
        raise AssertionError(
            f'Config files mutated by approval: {", ".join(changed_files)}\n'
            'Approval must NEVER edit config. It marks intent only.'
        )

    print(f'  ✓ Approved proposal {proposal["id"]}')
    print(f'  ✓ Verified {len(config_files)} config files unchanged')
    print(f'  ✓ Follow-up steps returned: {len(response["follow_up_steps"])}')
    print('  ✓ CRITICAL TEST PASSED: Approval does not mutate config')


def test_handlers_never_read_proposals_table():
    """
    Static grep: api/handlers.py and api/field_semantics.py contain no
    reference to the proposals table.

    Same boundary guard as test_harness_boundary_isolation, extended
    to the new table. Handlers operate on config, never on proposals.
    """
    print("\n[TEST] Handlers never read proposals table")

    handler_files = [
        Path('api/handlers.py'),
        Path('api/field_semantics.py')
    ]

    violations = []

    for handler_file in handler_files:
        if not handler_file.exists():
            print(f'  ⚠️  File not found: {handler_file} (skipping)')
            continue

        content = handler_file.read_text()

        # Check for any reference to proposals table
        forbidden_patterns = [
            'proposals',  # table name
            '.table("proposals")',
            '.table(\'proposals\')',
            'FROM proposals',
            'from proposals'
        ]

        found_patterns = []
        for pattern in forbidden_patterns:
            if pattern.lower() in content.lower():
                # Check it's not in a comment
                for line_num, line in enumerate(content.split('\n'), 1):
                    if pattern.lower() in line.lower() and not line.strip().startswith('#'):
                        found_patterns.append((pattern, line_num, line.strip()))

        if found_patterns:
            violations.append((handler_file.name, found_patterns))

    if violations:
        print('\n  ❌ HANDLERS READ PROPOSALS TABLE:')
        for filename, patterns in violations:
            print(f'\n  {filename}:')
            for pattern, line_num, line in patterns:
                print(f'    Line {line_num}: {pattern}')
                print(f'      {line[:80]}')
        raise AssertionError(
            '\nHandlers must NEVER read proposals table at runtime.\n'
            'Proposals are a recommendation ledger, not a config source.\n'
            'Remove all proposals table references from handlers.'
        )

    checked_files = [f.name for f in handler_files if f.exists()]
    print(f'  ✓ Checked {len(checked_files)} handler files')
    print(f'  ✓ No references to proposals table found')
    print('  ✓ Handler boundary isolation maintained')


def main():
    """Run all proposal pipeline tests."""
    tests = [
        test_propose_suppressed_below_evidence_bar,
        test_propose_suppressed_below_effect_size,
        test_propose_suppressed_when_duplicate_open,
        test_propose_suppressed_at_max_open_proposals,
        test_approve_does_not_mutate_any_config_file,
        test_handlers_never_read_proposals_table,
    ]

    print("=" * 70)
    print("PROPOSAL PIPELINE VALIDATION")
    print("=" * 70)

    failed = []

    for test in tests:
        try:
            test()
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = len(tests) - len(failed)
    print(f"\nTotal tests: {len(tests)}")
    print(f"  ✓ Passed: {passed}")

    if failed:
        print(f"  ✗ Failed: {len(failed)}")
        print("\nFailed tests:")
        for name, error in failed:
            print(f"  - {name}")
            print(f"    {error[:100]}")
        print("\n" + "=" * 70)
        print(f"RESULTS: {passed} passed, {len(failed)} failed")
        print("=" * 70)
        return 1

    print("\n✅ All proposal pipeline tests passed")
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, 0 failed")
    print("=" * 70)
    return 0


if __name__ == '__main__':
    sys.exit(main())
