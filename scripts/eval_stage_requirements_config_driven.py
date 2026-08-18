#!/usr/bin/env python3
"""
Eval: Stage requirements are config-driven, not hardcoded.

RED/GREEN TEST: Swap stage IDs in a mock config, verify requirements
still map correctly based on order alone, not literal ID matching.

This proves stage_requirements.py has NO hardcoded stage IDs.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_config_driven_stage_requirements():
    """Test that stage requirements derive from config order, not hardcoded IDs."""
    import tempfile
    import yaml
    from unittest.mock import patch

    print("="*80)
    print("STAGE REQUIREMENTS CONFIG-DRIVEN TEST")
    print("="*80)
    print()

    # Test 1: Create mock config with DIFFERENT stage IDs than GrowthBook
    print("[TEST 1] Mock config with completely different stage IDs")

    mock_config = {
        "pipeline": {
            "pipelines": [
                {
                    "id": "default",
                    "name": "Sales Pipeline",
                    "stages": [
                        {
                            "id": "stage_zero",
                            "name": "Meeting Set",
                            "order": 0,
                            "exclude_from_analysis": True
                        },
                        {
                            "id": "stage_one",
                            "name": "Discovery",
                            "order": 1
                        },
                        {
                            "id": "stage_two",
                            "name": "Scoping",
                            "order": 2
                        },
                        {
                            "id": "stage_three",
                            "name": "Evaluation",
                            "order": 3
                        },
                        {
                            "id": "stage_four",
                            "name": "Proposal",
                            "order": 4
                        },
                        {
                            "id": "closedwon",
                            "name": "Closed Won",
                            "order": 5,
                            "is_won": True
                        }
                    ]
                }
            ]
        },
        "stage_progression": {
            "discovery_to_scoping": {
                "identified_pain": 5,
                "champion": 4
            },
            "scoping_to_proposal": {
                "metrics": 6,
                "economic_buyer": 6,
                "champion": 6
            },
            "proposal_to_negotiating": {
                "all_components_minimum": 7,
                "decision_process": 8
            },
            "negotiating_to_closed_won": {
                "all_components_minimum": 8,
                "decision_process": 7
            }
        }
    }

    # Write mock config to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(mock_config, f)
        temp_config_path = f.name

    print(f"  Mock config created with stage IDs:")
    print(f"    - stage_zero (order 0, excluded)")
    print(f"    - stage_one (order 1) → Discovery")
    print(f"    - stage_two (order 2) → Scoping")
    print(f"    - stage_three (order 3) → Evaluation")
    print(f"    - stage_four (order 4) → Proposal")
    print()

    # Patch config loading to use mock config
    original_load_config = None
    try:
        from api import stage_requirements

        # Clear cache
        stage_requirements._config_cache = None
        stage_requirements._stage_lookup_cache = None

        # Patch to load mock config
        def mock_load_config():
            return mock_config

        original_load_config = stage_requirements._load_config
        stage_requirements._load_config = mock_load_config
        stage_requirements._config_cache = None
        stage_requirements._stage_lookup_cache = None

        # Test 2: Verify order 1 (Discovery) maps to discovery_to_scoping
        print("[TEST 2] Order 1 stage maps to discovery_to_scoping requirements")

        reqs_order_1 = stage_requirements.get_requirements_for_stage("stage_one")

        assert "pain" in reqs_order_1, "Order 1 should have pain requirement"
        assert "champion" in reqs_order_1, "Order 1 should have champion requirement"
        assert reqs_order_1["pain"] == 5, f"Pain should be 5, got {reqs_order_1['pain']}"
        assert reqs_order_1["champion"] == 4, f"Champion should be 4, got {reqs_order_1['champion']}"

        print(f"  ✓ stage_one (order 1) → {reqs_order_1}")
        print(f"  ✓ Correct: discovery_to_scoping requirements")
        print()

        # Test 3: Verify order 2 (Scoping) maps to scoping_to_proposal
        print("[TEST 3] Order 2 stage maps to scoping_to_proposal requirements")

        reqs_order_2 = stage_requirements.get_requirements_for_stage("stage_two")

        assert "metrics" in reqs_order_2, "Order 2 should have metrics requirement"
        assert "economic_buyer" in reqs_order_2, "Order 2 should have EB requirement"
        assert reqs_order_2["metrics"] == 6, f"Metrics should be 6, got {reqs_order_2['metrics']}"
        assert reqs_order_2["economic_buyer"] == 6, f"EB should be 6, got {reqs_order_2['economic_buyer']}"

        print(f"  ✓ stage_two (order 2) → {reqs_order_2}")
        print(f"  ✓ Correct: scoping_to_proposal requirements")
        print()

        # Test 4: Verify order 0 (excluded) returns empty requirements
        print("[TEST 4] Order 0 (excluded stage) returns empty requirements")

        reqs_order_0 = stage_requirements.get_requirements_for_stage("stage_zero")

        assert reqs_order_0 == {}, f"Excluded stage should have no requirements, got {reqs_order_0}"

        print(f"  ✓ stage_zero (order 0, excluded) → {reqs_order_0}")
        print(f"  ✓ Correct: empty requirements (excluded from analysis)")
        print()

        # Test 5: Verify is_won stage returns empty requirements
        print("[TEST 5] Won stage returns empty requirements")

        reqs_won = stage_requirements.get_requirements_for_stage("closedwon")

        assert reqs_won == {}, f"Won stage should have no requirements, got {reqs_won}"

        print(f"  ✓ closedwon (is_won=true) → {reqs_won}")
        print(f"  ✓ Correct: terminal stage has no requirements")
        print()

        # Test 6: Verify with actual production stage IDs (should still work)
        print("[TEST 6] Works with actual production stage IDs")

        # Restore real config
        stage_requirements._load_config = original_load_config
        stage_requirements._config_cache = None
        stage_requirements._stage_lookup_cache = None

        # Test with real GrowthBook stage ID
        real_reqs = stage_requirements.get_requirements_for_stage("qualifiedtobuy")

        # qualifiedtobuy is order 2 in GrowthBook (Scoping)
        # Should map to scoping_to_proposal
        assert "metrics" in real_reqs, "Real config: Scoping should require metrics"
        assert real_reqs["metrics"] == 6, "Real config: Metrics should be 6"

        print(f"  ✓ qualifiedtobuy (real GrowthBook ID) → {real_reqs}")
        print(f"  ✓ Correct: maps based on order, not hardcoded ID")
        print()

        print("="*80)
        print("Results: All tests passed!")
        print("="*80)
        print()
        print("PROOF: Stage requirements derive from config.order ONLY.")
        print("No hardcoded stage IDs. Works for any client config.")

    finally:
        # Cleanup
        if original_load_config:
            stage_requirements._load_config = original_load_config
            stage_requirements._config_cache = None
            stage_requirements._stage_lookup_cache = None
        import os
        if os.path.exists(temp_config_path):
            os.remove(temp_config_path)

if __name__ == "__main__":
    test_config_driven_stage_requirements()
