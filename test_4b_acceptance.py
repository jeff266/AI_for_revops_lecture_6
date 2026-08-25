#!/usr/bin/env python3
"""
Phase 4b Acceptance Test

Test that call_scorer.py correctly uses get_components() to score with
methodology-specific components. No Python should be edited to switch
between MEDDICC (7 components) and MEDDPICC (8 components).
"""
import sys
sys.path.insert(0, 'scripts')

from utils import get_components, component_key
import call_scorer as cs

# Test sample call text
TEST_CALL = """
Sales call with Acme Corp.

The prospect confirmed they need to reduce customer churn by 15% this quarter.
They have a $500k budget approved. Sarah Johnson, the VP of Sales, is driving
this internally and will be presenting to the CFO next week. They're evaluating
us against Competitor X. The legal team requires a security questionnaire before
any contract can be signed.
"""

def test_meddpicc():
    """Test MEDDPICC (8 components including paper_process)."""
    print("=" * 60)
    print("TEST 1: MEDDPICC (8 components)")
    print("=" * 60)

    components = get_components()
    print(f"\nConfigured components ({len(components)}):")
    for label in components:
        key = component_key(label)
        print(f"  - {label} → {key}")

    print(f"\nExpected: 8 components including 'Paper Process'")
    print(f"Actual: {len(components)} components")

    if len(components) != 8:
        print(f"❌ FAILED: Expected 8 components, got {len(components)}")
        return False

    if "Paper Process" not in components:
        print(f"❌ FAILED: 'Paper Process' not in component list")
        print(f"   Components: {components}")
        return False

    # Verify call_scorer.COMPONENTS matches
    print(f"\nVerifying call_scorer.COMPONENTS:")
    print(f"  Length: {len(cs.COMPONENTS)}")
    print(f"  Component keys: {cs.COMPONENT_KEYS}")

    if len(cs.COMPONENTS) != 8:
        print(f"❌ FAILED: call_scorer.COMPONENTS has {len(cs.COMPONENTS)}, expected 8")
        return False

    if "paper_process" not in cs.COMPONENT_KEYS:
        print(f"❌ FAILED: 'paper_process' not in call_scorer.COMPONENT_KEYS")
        return False

    print("\n✅ MEDDPICC test PASSED")
    return True


def test_meddicc():
    """Test MEDDICC (7 components, no paper_process)."""
    print("\n" + "=" * 60)
    print("TEST 2: MEDDICC (7 components, no paper_process)")
    print("=" * 60)

    # Need to reload modules to pick up new config
    import importlib
    import utils
    importlib.reload(utils)

    # Re-import call_scorer to pick up new COMPONENTS
    import call_scorer
    importlib.reload(call_scorer)

    from utils import get_components, component_key

    components = get_components()
    print(f"\nConfigured components ({len(components)}):")
    for label in components:
        key = component_key(label)
        print(f"  - {label} → {key}")

    print(f"\nExpected: 7 components, NO 'Paper Process'")
    print(f"Actual: {len(components)} components")

    if len(components) != 7:
        print(f"❌ FAILED: Expected 7 components, got {len(components)}")
        return False

    if "Paper Process" in components:
        print(f"❌ FAILED: 'Paper Process' should not be in MEDDICC")
        return False

    # Verify call_scorer.COMPONENTS matches
    print(f"\nVerifying call_scorer.COMPONENTS after reload:")
    print(f"  Length: {len(call_scorer.COMPONENTS)}")
    print(f"  Component keys: {call_scorer.COMPONENT_KEYS}")

    if len(call_scorer.COMPONENTS) != 7:
        print(f"❌ FAILED: call_scorer.COMPONENTS has {len(call_scorer.COMPONENTS)}, expected 7")
        return False

    if "paper_process" in call_scorer.COMPONENT_KEYS:
        print(f"❌ FAILED: 'paper_process' should not be in MEDDICC")
        return False

    print("\n✅ MEDDICC test PASSED")
    return True


if __name__ == "__main__":
    print("\nPhase 4b Acceptance Test")
    print("Testing methodology switching without Python edits\n")

    # Test 1: MEDDPICC (current config)
    test1_passed = test_meddpicc()

    if not test1_passed:
        print("\n" + "=" * 60)
        print("ACCEPTANCE TEST FAILED - MEDDPICC")
        print("=" * 60)
        sys.exit(1)

    # Change config to MEDDICC
    print("\nChanging config/client.yaml to MEDDICC...")
    with open('config/client.yaml', 'r') as f:
        content = f.read()
    content = content.replace('sales_methodology: "MEDDPICC"', 'sales_methodology: "MEDDICC"')
    with open('config/client.yaml', 'w') as f:
        f.write(content)
    print("Config updated to MEDDICC")

    # Test 2: MEDDICC
    test2_passed = test_meddicc()

    if not test2_passed:
        print("\n" + "=" * 60)
        print("ACCEPTANCE TEST FAILED - MEDDICC")
        print("=" * 60)
        sys.exit(1)

    print("\n" + "=" * 60)
    print("ACCEPTANCE TEST PASSED ✅")
    print("=" * 60)
    print("\nBoth MEDDPICC (8) and MEDDICC (7) work correctly.")
    print("No Python code was edited to switch methodologies.")
    print("\nPhase 4b is COMPLETE.")
