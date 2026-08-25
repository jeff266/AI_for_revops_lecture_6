#!/usr/bin/env python3
"""
Component drift guard test.

Guards against: A second component list definition outside utils.py.

A MEDDPICC client would get seven components from one file and eight from
another, and which wins depends on execution order. This is the "half-rewired"
failure mode where call_scorer.py imported get_components() but still defined
COMPONENT_KEYS = [...] locally.

Run this before committing any changes to component-handling code.
"""

import sys
import re
from pathlib import Path


def test_no_file_defines_component_list_outside_utils():
    """
    utils.py is the only place the component list is defined.

    A second copy means a MEDDPICC client gets seven components from one file
    and eight from another, and which wins depends on execution order.

    Forbidden patterns:
    - COMPONENTS = [(
    - COMPONENT_KEYS = [
    - for comp in ["metrics", "economic_buyer", ...
    - _PIN_COMPONENTS (legacy hardcoding)

    Allowed:
    - get_components() and component_key() calls
    - Test fixtures (in test_*.py files)
    - utils.py itself
    """
    print("\n[TEST] No file defines component list outside utils.py")

    repo_root = Path(__file__).parent.parent
    scripts_dir = repo_root / 'scripts'
    api_dir = repo_root / 'api'

    # Forbidden patterns (module-level only, not local variables)
    patterns = [
        r'^COMPONENTS\s*=\s*\[',          # COMPONENTS = [ at line start (module-level)
        r'^COMPONENT_KEYS\s*=\s*\[',      # COMPONENT_KEYS = [ at line start
        r'_PIN_COMPONENTS\s*=',            # Legacy constant assignment
        r'for\s+comp\s+in\s+\["metrics"', # Hardcoded MEDDICC iteration
        r'for\s+comp\s+in\s+\["pain"',    # Hardcoded component iteration
    ]

    # Dict-key enumeration patterns (catch hardcoded component_mapping-style dicts)
    # Look for dicts with 3+ component names as keys (3 to avoid false positives)
    dict_enum_patterns = [
        r'"identified_pain".*"champion".*"metrics"',  # Multiple MEDDICC keys in dict
        r'"metrics".*"economic_buyer".*"decision_criteria"',  # Multiple component keys
        r'"pain".*"champion".*"economic_buyer"',      # Alternative naming
    ]

    violations = []

    # Check all Python files in scripts/ and api/
    for directory in [scripts_dir, api_dir]:
        if not directory.exists():
            continue

        for filepath in directory.rglob('*.py'):
            # Explicit exclusions (visible policy, not convention):
            # 1. utils.py - single source of truth for component definitions
            # 2. Guards (eval_*.py) - contain test fixtures and pattern literals
            # 3. Tests (test_*.py) - fixtures legitimately name components
            # All other files (including stage_requirements.py, call_scorer.py, meddicc_agent.py)
            # are scanned. Use inline '# drift-guard: ok' to opt out specific lines.
            excluded_files = {
                'utils.py',
            }

            if filepath.name in excluded_files:
                continue

            # Skip guards and tests by prefix
            if filepath.name.startswith('eval_') or filepath.name.startswith('test_'):
                continue

            # Skip __pycache__
            if '__pycache__' in str(filepath):
                continue

            # Read file
            try:
                content = filepath.read_text()
            except Exception as e:
                print(f"  ⚠️  Could not read {filepath}: {e}")
                continue

            # Check for forbidden patterns
            for pattern in patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    # Get line number
                    line_num = content[:match.start()].count('\n') + 1

                    # Get the line content
                    lines = content.split('\n')
                    if line_num <= len(lines):
                        line_content = lines[line_num - 1]

                        # Inline opt-out: skip if line has drift-guard: ok
                        if '# drift-guard: ok' in line_content:
                            continue

                        violations.append({
                            'file': str(filepath.relative_to(repo_root)),
                            'line': line_num,
                            'pattern': pattern,
                            'content': line_content.strip()
                        })

            # Check for dict-key enumeration (multi-line, so use DOTALL)
            for pattern in dict_enum_patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE | re.DOTALL)
                for match in matches:
                    # Get line number of start
                    line_num = content[:match.start()].count('\n') + 1

                    # Inline opt-out: check matched span + 5 lines before for drift-guard: ok
                    lines = content.split('\n')
                    start_line = max(0, line_num - 6)  # 5 lines before + current
                    end_line = content[:match.end()].count('\n') + 1
                    context_lines = lines[start_line:end_line]

                    if any('# drift-guard: ok' in line for line in context_lines):
                        continue

                    # Get the line content
                    if line_num <= len(lines):
                        line_content = lines[line_num - 1]

                        violations.append({
                            'file': str(filepath.relative_to(repo_root)),
                            'line': line_num,
                            'pattern': f'dict_enum:{pattern[:40]}...',
                            'content': f'{line_content.strip()[:60]}... (dict with hardcoded component keys)'
                        })

    if violations:
        print(f"\n  ❌ COMPONENT DRIFT DETECTED:\n")
        print("  Files defining component lists outside utils.py:\n")

        for v in violations:
            print(f"    {v['file']}:{v['line']}")
            print(f"      Pattern: {v['pattern']}")
            print(f"      Content: {v['content'][:80]}")
            print()

        print("  Fix: Delete local definitions, use get_components() and component_key().\n")
        raise AssertionError(
            f"Found {len(violations)} hardcoded component lists. "
            f"utils.py is the single source of truth."
        )

    print("  ✓ No hardcoded component lists found")
    print("  ✓ utils.py is the single source of truth")


def main():
    """Run component drift guard."""
    print("=" * 70)
    print("COMPONENT DRIFT GUARD")
    print("=" * 70)
    print("\nGuard against: Second component list definition (half-rewired state)")
    print("A MEDDPICC client would get 7 from one file, 8 from another.\n")

    tests = [
        test_no_file_defines_component_list_outside_utils,
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
        print("\n⚠️  FIX BEFORE COMMITTING")
        print("Delete hardcoded lists, use get_components() and component_key().")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
