#!/usr/bin/env python3
"""
Test the call adapter factory.

Verifies:
1. All three adapters (fireflies, gong, apollo) can be instantiated
2. Factory raises on unknown adapter names
3. Factory raises on missing call_tools.primary
"""
import sys
from pathlib import Path

# Add scripts to path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from adapters.calls import get_call_adapter


def test_factory_raises_on_missing_primary():
    """Factory should raise if call_tools.primary not set."""
    config = {}

    try:
        get_call_adapter(config)
        print("  ❌ FAILED: Should have raised on missing call_tools.primary")
        return False
    except ValueError as e:
        if "call_tools.primary not set" in str(e):
            print("  ✓ Raises on missing call_tools.primary")
            return True
        else:
            print(f"  ❌ FAILED: Wrong error message: {e}")
            return False


def test_factory_raises_on_unknown_adapter():
    """Factory should raise on unknown adapter name with valid options."""
    config = {'call_tools': {'primary': 'gongg'}}  # typo

    try:
        get_call_adapter(config)
        print("  ❌ FAILED: Should have raised on unknown adapter 'gongg'")
        return False
    except ValueError as e:
        error_msg = str(e)
        if "gongg" in error_msg and "fireflies" in error_msg and "gong" in error_msg:
            print(f"  ✓ Raises on unknown adapter with helpful message")
            print(f"    Message: {error_msg}")
            return True
        else:
            print(f"  ❌ FAILED: Error message missing key info: {e}")
            return False


def test_adapter_instantiation(adapter_name: str, env_vars_needed: list):
    """Test that an adapter can be instantiated (may fail if env vars missing)."""
    config = {'call_tools': {'primary': adapter_name}}

    try:
        adapter = get_call_adapter(config)
        print(f"  ✓ {adapter_name}: instantiated successfully")
        print(f"    Type: {type(adapter).__name__}")
        return True
    except ValueError as e:
        # Expected if env vars not set
        error_msg = str(e)
        if any(env_var in error_msg for env_var in env_vars_needed):
            print(f"  ⊘ {adapter_name}: requires {', '.join(env_vars_needed)} (not set)")
            return True  # Expected failure is OK
        else:
            print(f"  ❌ FAILED: Unexpected error for {adapter_name}: {e}")
            return False
    except Exception as e:
        print(f"  ❌ FAILED: {adapter_name} raised unexpected error: {e}")
        return False


def main():
    """Run all factory tests."""
    print("=" * 70)
    print("CALL ADAPTER FACTORY TESTS")
    print("=" * 70)

    passed = 0
    failed = 0

    # Test 1: Missing primary
    print("\n[TEST 1] Missing call_tools.primary")
    if test_factory_raises_on_missing_primary():
        passed += 1
    else:
        failed += 1

    # Test 2: Unknown adapter
    print("\n[TEST 2] Unknown adapter name (typo)")
    if test_factory_raises_on_unknown_adapter():
        passed += 1
    else:
        failed += 1

    # Test 3-5: Adapter instantiation
    adapters = [
        ('fireflies', ['FIREFLIES_API_KEY']),
        ('gong', ['GONG_ACCESS_KEY', 'GONG_ACCESS_KEY_SECRET']),
        ('apollo', ['APOLLO_API_KEY'])
    ]

    for adapter_name, env_vars in adapters:
        print(f"\n[TEST] {adapter_name} instantiation")
        if test_adapter_instantiation(adapter_name, env_vars):
            passed += 1
        else:
            failed += 1

    # Summary
    print()
    print("=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
