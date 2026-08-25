#!/usr/bin/env python3
"""
Phase 4b acceptance test: End-to-end methodology switching.

Test scenario:
1. Set sales_methodology: "MEDDPICC"
2. Confirm get_components() returns 8 components (including Paper Process)
3. Create a mock score dict and confirm it has paper_process
4. Mock rollup and confirm it handles 8 components
5. Set back to MEDDICC
6. Confirm 7 components
"""

import sys
import yaml
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent))

from utils import get_components, component_key


def test_meddpicc_has_eight_components():
    """Test that MEDDPICC returns 8 components including paper_process."""
    print("\n[TEST] MEDDPICC has 8 components including Paper Process")

    # Load config and set to MEDDPICC
    config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Temporarily set to MEDDPICC
    original_methodology = config.get('organization', {}).get('sales_methodology', 'MEDDICC')
    if 'organization' not in config:
        config['organization'] = {}
    config['organization']['sales_methodology'] = 'MEDDPICC'

    # Write updated config
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # Clear cache and reload
    import utils
    utils._CONFIG_CACHE = None

    # Get components
    components = get_components()
    print(f"  Components: {components}")

    # Verify 8 components
    assert len(components) == 8, f"Expected 8 components, got {len(components)}"

    # Verify Paper Process is included
    component_keys = [component_key(label) for label in components]
    assert 'paper_process' in component_keys, \
        f"Expected 'paper_process' in component keys, got {component_keys}"

    print("  ✓ MEDDPICC returns 8 components")
    print("  ✓ Paper Process included")

    # Test call_scorer mock
    from call_scorer import _component_keys
    scorer_keys = _component_keys()
    assert len(scorer_keys) == 8, f"call_scorer should see 8 components, got {len(scorer_keys)}"
    assert 'paper_process' in scorer_keys, "call_scorer should have paper_process"

    print("  ✓ call_scorer._component_keys() returns 8")

    # Test rollup mock
    from rollup_deal_scores import _build_abbr
    abbr = _build_abbr()
    assert len(abbr) == 8, f"rollup abbreviations should have 8, got {len(abbr)}"
    assert 'paper_process' in abbr, "rollup should have paper_process abbreviation"

    print("  ✓ rollup_deal_scores._build_abbr() has 8 entries")

    # Restore original methodology
    if 'organization' not in config:
        config['organization'] = {}
    config['organization']['sales_methodology'] = original_methodology
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    utils._CONFIG_CACHE = None


def test_meddicc_has_seven_components():
    """Test that MEDDICC returns 7 components (no Paper Process)."""
    print("\n[TEST] MEDDICC has 7 components (no Paper Process)")

    # Load config and set to MEDDICC
    config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Set to MEDDICC
    if 'organization' not in config:
        config['organization'] = {}
    config['organization']['sales_methodology'] = 'MEDDICC'

    # Write updated config
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # Clear cache and reload
    import utils
    utils._CONFIG_CACHE = None

    # Get components
    components = get_components()
    print(f"  Components: {components}")

    # Verify 7 components
    assert len(components) == 7, f"Expected 7 components, got {len(components)}"

    # Verify Paper Process is NOT included
    component_keys = [component_key(label) for label in components]
    assert 'paper_process' not in component_keys, \
        f"Expected no 'paper_process' in component keys, got {component_keys}"

    print("  ✓ MEDDICC returns 7 components")
    print("  ✓ Paper Process excluded")

    # Test call_scorer mock
    from call_scorer import _component_keys
    scorer_keys = _component_keys()
    assert len(scorer_keys) == 7, f"call_scorer should see 7 components, got {len(scorer_keys)}"
    assert 'paper_process' not in scorer_keys, "call_scorer should not have paper_process"

    print("  ✓ call_scorer._component_keys() returns 7")

    # Test rollup mock
    from rollup_deal_scores import _build_abbr
    abbr = _build_abbr()
    assert len(abbr) == 7, f"rollup abbreviations should have 7, got {len(abbr)}"
    assert 'paper_process' not in abbr, "rollup should not have paper_process"

    print("  ✓ rollup_deal_scores._build_abbr() has 7 entries")


def main():
    """Run 4b acceptance test."""
    print("=" * 70)
    print("PHASE 4B ACCEPTANCE TEST")
    print("=" * 70)
    print("\nEnd-to-end methodology switching:")
    print("- MEDDPICC → 8 components (with Paper Process)")
    print("- MEDDICC → 7 components (without Paper Process)\n")

    tests = [
        test_meddpicc_has_eight_components,
        test_meddicc_has_seven_components,
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

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
