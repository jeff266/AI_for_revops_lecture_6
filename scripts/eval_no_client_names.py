#!/usr/bin/env python3
"""
Test that no client names appear in tracked files.

A template must not ship one client's customer names to another.
Three sat in live prompt text sent to the classifier on every request.

Client names checked: GrowthBook, Skyscanner, Bestseller, LiveSport, ECCO
"""

import sys
from pathlib import Path

# Client names from the source implementation
FORBIDDEN_NAMES = [
    "GrowthBook",
    "Skyscanner",
    "Bestseller",
    "LiveSport",
    "ECCO",
]

# File extensions to check
EXTENSIONS = {".py", ".sh", ".sql", ".yaml", ".yml", ".json", ".md"}

# Directories to exclude
EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache"}

# Paths to exclude (session artifacts and port history with historical client names)
EXCLUDE_PATHS = {"docs/build-history", "docs/port-history"}


def test_no_client_names_in_tracked_files():
    """A template must not ship one client's customer names to another.
    Three sat in live prompt text sent to the classifier on every request."""

    print("\n[TEST] No client names in tracked files")

    violations = []
    repo_root = Path(__file__).parent.parent

    for f in repo_root.rglob("*"):
        # Skip excluded directories
        if any(exc in f.parts for exc in EXCLUDE_DIRS):
            continue

        # Skip excluded paths (session artifacts in docs/build-history/)
        try:
            rel_path = str(f.relative_to(repo_root))
            if any(rel_path.startswith(exc) for exc in EXCLUDE_PATHS):
                continue
        except ValueError:
            continue

        # Only check tracked file types
        if f.suffix not in EXTENSIONS:
            continue

        # Skip this test file itself
        if f.name == "eval_no_client_names.py":
            continue

        try:
            content = f.read_text()
            content_lower = content.lower()
            for name in FORBIDDEN_NAMES:
                # Case-insensitive matching to catch "growthbook.io", "GrowthBook", etc.
                if name.lower() in content_lower:
                    # Find line numbers
                    for i, line in enumerate(content.split("\n"), 1):
                        if name.lower() in line.lower():
                            violations.append((f.relative_to(repo_root), i, name, line.strip()[:80]))
        except Exception:
            # Binary or unreadable file
            pass

    if violations:
        print(f"\n  ❌ FAILED: Found {len(violations)} client name references\n")
        for file_path, line_num, name, line_preview in violations[:20]:  # Show first 20
            print(f"  {file_path}:{line_num} - {name}")
            print(f"    {line_preview}\n")
        if len(violations) > 20:
            print(f"  ... and {len(violations) - 20} more\n")
        raise AssertionError(
            f"Found {len(violations)} client name references in tracked files.\n"
            "Client names from one deployment must not appear in another.\n"
            f"Forbidden: {', '.join(FORBIDDEN_NAMES)}"
        )

    print(f"  ✓ No client names found in tracked files")
    print(f"  ✓ Checked extensions: {', '.join(sorted(EXTENSIONS))}")
    print(f"  ✓ Excluded paths: {', '.join(sorted(EXCLUDE_PATHS))}")
    print(f"  ✓ Forbidden names: {', '.join(FORBIDDEN_NAMES)}")


def main():
    """Run client name validation."""
    print("=" * 70)
    print("CLIENT NAME VALIDATION")
    print("=" * 70)

    try:
        test_no_client_names_in_tracked_files()
        print("\n" + "=" * 70)
        print("RESULTS: 1 passed, 0 failed")
        print("=" * 70)
        return 0
    except AssertionError as e:
        print(f"\n  ❌ {e}")
        print("\n" + "=" * 70)
        print("RESULTS: 0 passed, 1 failed")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
