#!/usr/bin/env python3
"""
Regression test for MEDDPICC stage_progression with paper_process.

Guards against: paper_process requirement silently dropped from stage thresholds.

This is the Northwind seam failure from Phase 6 — a MEDDPICC client configured
validate_to_commit.paper_process: 5 but get_requirements_for_stage() returned
requirements without paper_process. The component_mapping dict was hardcoded with
only 7 MEDDICC components, missing paper_process.

Fix: component_mapping derived dynamically from get_components(), and unmapped
config keys now raise ValueError instead of silent drop.
"""

import sys
from pathlib import Path

# Add api and scripts to path
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / 'scripts'))


def test_meddpicc_paper_process_in_stage_requirements():
    """
    MEDDPICC client with paper_process in stage_progression should return
    paper_process in get_requirements_for_stage().

    Config fixture: Northwind Logistics
    - Methodology: MEDDPICC (8 components including Paper Process)
    - 3 open stages: Qualify (order 1), Validate (order 2), Commit (order 3)
    - stage_progression.validate_to_commit.paper_process: 5

    Expected: get_requirements_for_stage('commit') includes paper_process: 5
    """
    print("\n[TEST] MEDDPICC paper_process in stage requirements")

    import api.stage_requirements as stage_req_module
    from api.stage_requirements import get_requirements_for_stage

    # Northwind config fixture
    northwind_config = {
        'organization': {
            'name': 'Northwind Logistics',
            'sales_methodology': 'MEDDPICC',
        },
        'pipeline': {
            'pipelines': [{
                'id': 'default',
                'name': 'Sales Pipeline',
                'stages': [
                    {'id': 'qualify', 'name': 'Qualify', 'order': 1, 'exclude_from_analysis': True},
                    {'id': 'validate', 'name': 'Validate', 'order': 2},
                    {'id': 'commit', 'name': 'Commit', 'order': 3},
                    {'id': 'closedwon', 'name': 'Closed Won', 'order': 4, 'is_won': True},
                ]
            }]
        },
        'stage_progression': {
            'qualify_to_validate': {
                'identified_pain': 5,
                'champion': 4,
            },
            'validate_to_commit': {
                'metrics': 6,
                'economic_buyer': 6,
                'champion': 6,
                'decision_criteria': 5,
                'paper_process': 5,  # CRITICAL: MEDDPICC-specific component
            },
            'commit_to_closed_won': {
                'all_components_minimum': 8,
                'decision_process': 7,
                'competition': 6,
                'paper_process': 7,  # Raised threshold at final stage
            }
        }
    }

    # Inject config (monkey-patch both stage_requirements and utils)
    import utils as utils_module

    original_load_stage = stage_req_module._load_config
    original_load_utils = utils_module.load_client_config

    def mock_load():
        return northwind_config

    stage_req_module._load_config = mock_load
    utils_module.load_client_config = mock_load
    stage_req_module._config_cache = None
    stage_req_module._stage_lookup_cache = None

    try:
        # Test validate stage (qualify → validate transition)
        reqs_validate = get_requirements_for_stage('validate')
        print(f"  validate requirements: {reqs_validate}")

        assert 'identified_pain' in reqs_validate or 'pain' in reqs_validate, \
            "validate should require identified_pain"
        assert 'champion' in reqs_validate, \
            "validate should require champion"

        # Test commit stage (validate → commit transition)
        # MUST include paper_process: 5
        reqs_commit = get_requirements_for_stage('commit')
        print(f"  commit requirements: {reqs_commit}")

        if 'paper_process' not in reqs_commit:
            raise AssertionError(
                f"REGRESSION: paper_process missing from commit requirements.\n"
                f"  Config says: validate_to_commit.paper_process = 5\n"
                f"  Function returned: {reqs_commit}\n"
                f"  This is the Northwind Phase 6 seam failure — paper_process silently dropped."
            )

        if reqs_commit['paper_process'] != 5:
            raise AssertionError(
                f"paper_process threshold wrong: expected 5, got {reqs_commit['paper_process']}"
            )

        # Verify other components present
        assert reqs_commit['metrics'] == 6, "metrics threshold wrong"
        assert reqs_commit['economic_buyer'] == 6, "economic_buyer threshold wrong"
        assert reqs_commit['champion'] == 6, "champion threshold wrong"
        assert reqs_commit['decision_criteria'] == 5, "decision_criteria threshold wrong"

        print("  ✓ paper_process correctly included with threshold 5")
        print("  ✓ All other components present")

    finally:
        # Restore
        stage_req_module._load_config = original_load_stage
        utils_module.load_client_config = original_load_utils
        stage_req_module._config_cache = None
        stage_req_module._stage_lookup_cache = None


def test_unmapped_component_fails_loudly():
    """
    A stage_progression entry with an unknown component key should raise
    ValueError, not silently drop the requirement.

    This guards against the silent-drop mechanism that let paper_process hide.
    """
    print("\n[TEST] Unmapped component key fails loudly")

    import api.stage_requirements as stage_req_module
    from api.stage_requirements import get_requirements_for_stage

    # Config with typo: 'champoin' instead of 'champion'
    bad_config = {
        'organization': {
            'sales_methodology': 'MEDDICC',
        },
        'pipeline': {
            'pipelines': [{
                'id': 'default',
                'stages': [
                    {'id': 'discovery', 'name': 'Discovery', 'order': 1},
                    {'id': 'scoping', 'name': 'Scoping', 'order': 2},
                ]
            }]
        },
        'stage_progression': {
            'discovery_to_scoping': {
                'identified_pain': 5,
                'champoin': 4,  # TYPO - should fail loudly
            }
        }
    }

    import utils as utils_module

    original_load_stage = stage_req_module._load_config
    original_load_utils = utils_module.load_client_config

    def mock_load():
        return bad_config

    stage_req_module._load_config = mock_load
    utils_module.load_client_config = mock_load
    stage_req_module._config_cache = None
    stage_req_module._stage_lookup_cache = None

    try:
        # Should raise ValueError with helpful message
        # Note: get_requirements_for_stage returns requirements to ADVANCE FROM the stage
        # So to test discovery_to_scoping requirements, call with 'discovery'
        try:
            reqs = get_requirements_for_stage('discovery')
            raise AssertionError(
                f"REGRESSION: Unmapped key 'champoin' did not raise.\n"
                f"  Returned: {reqs}\n"
                f"  Silent drop allowed typos to hide. Must fail loudly."
            )
        except ValueError as e:
            error_msg = str(e)
            print(f"  ✓ Raised ValueError: {error_msg[:80]}...")

            # Verify helpful error message
            assert 'champoin' in error_msg, "Error should name the bad key"
            assert 'discovery_to_scoping' in error_msg, "Error should name the progression"
            assert 'Valid component keys' in error_msg or 'valid' in error_msg.lower(), \
                "Error should list valid options"

            print("  ✓ Error message names bad key and lists valid options")

    finally:
        stage_req_module._load_config = original_load_stage
        utils_module.load_client_config = original_load_utils
        stage_req_module._config_cache = None
        stage_req_module._stage_lookup_cache = None


def main():
    """Run MEDDPICC stage_requirements regression tests."""
    print("=" * 70)
    print("MEDDPICC STAGE_REQUIREMENTS REGRESSION TESTS")
    print("=" * 70)
    print("\nGuards against: paper_process silently dropped (Northwind Phase 6 seam)")

    tests = [
        test_meddpicc_paper_process_in_stage_requirements,
        test_unmapped_component_fails_loudly,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"\n❌ FAILED: {test.__name__}")
            print(f"   {e}")
        except Exception as e:
            failed += 1
            print(f"\n❌ ERROR in {test.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    if failed > 0:
        print("\n⚠️  REGRESSION DETECTED")
        print("The Northwind paper_process seam failure has returned.")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
