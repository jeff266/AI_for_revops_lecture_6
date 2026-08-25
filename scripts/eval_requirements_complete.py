#!/usr/bin/env python3
"""
Dependency-drift guard: ensures all imports are declared in requirements.txt.

Scans shipped code for imports, subtracts stdlib and local modules, maps import
names to pip package names via an alias map, fails if anything imported isn't
in requirements.txt.

WHY: Behavioral tests can pass locally (with accumulated pip installs) but fail
on fresh clone because yaml/dotenv/etc were undeclared. This catches that gap
before it ships.

Design points:
1. Unknown import FAILS rather than skipping (prevents alias map going stale)
2. Scanned paths are explicit named constant (not directory convention)
3. Declared-but-unimported packages reported as WARNING, not FAILURE
"""
import sys
import ast
from pathlib import Path

# Paths to scan for imports (explicit, not convention-based)
SCANNED_PATHS = [
    "api/*.py",
    "scripts/*.py",
    "scripts/adapters/*.py",
]

# Import name → pip package name aliases
# CRITICAL: Unknown imports FAIL to prevent this map going stale
IMPORT_TO_PACKAGE = {
    # Standard aliases (import name != pip package name)
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "anthropic": "anthropic",
    "supabase": "supabase",
    "openai": "openai",
    "cv2": "opencv-python",
    "PIL": "Pillow",

    # Direct matches (import name == pip package name)
    "requests": "requests",
    "pandas": "pandas",
    "numpy": "numpy",
    "pytest": "pytest",
    "flask": "flask",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "httpx": "httpx",
    "jinja2": "jinja2",
    "markdown": "markdown",
    "openpyxl": "openpyxl",
    "xlsxwriter": "xlsxwriter",
    "psycopg2": "psycopg2-binary",
    "dateutil": "python-dateutil",
}

# Python stdlib modules (don't require pip install)
STDLIB_MODULES = {
    "__future__",  # Future imports
    "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio", "asyncore",
    "atexit", "audioop", "base64", "bdb", "binascii", "bisect", "builtins", "bz2",
    "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd", "code", "codecs",
    "codeop", "collections", "colorsys", "compileall", "concurrent", "configparser",
    "contextlib", "contextvars", "copy", "copyreg", "crypt", "csv", "ctypes",
    "curses", "dataclasses", "datetime", "dbm", "decimal", "difflib", "dis",
    "distutils", "doctest", "email", "encodings", "enum", "errno", "faulthandler",
    "fcntl", "filecmp", "fileinput", "fnmatch", "formatter", "fractions", "ftplib",
    "functools", "gc", "getopt", "getpass", "gettext", "glob", "graphlib", "grp",
    "gzip", "hashlib", "heapq", "hmac", "html", "http", "imaplib", "imghdr", "imp",
    "importlib", "inspect", "io", "ipaddress", "itertools", "json", "keyword",
    "lib2to3", "linecache", "locale", "logging", "lzma", "mailbox", "mailcap",
    "marshal", "math", "mimetypes", "mmap", "modulefinder", "msilib", "msvcrt",
    "multiprocessing", "netrc", "nis", "nntplib", "numbers", "operator", "optparse",
    "os", "ossaudiodev", "parser", "pathlib", "pdb", "pickle", "pickletools",
    "pipes", "pkgutil", "platform", "plistlib", "poplib", "posix", "posixpath",
    "pprint", "profile", "pstats", "pty", "pwd", "py_compile", "pyclbr", "pydoc",
    "queue", "quopri", "random", "re", "readline", "reprlib", "resource", "rlcompleter",
    "runpy", "sched", "secrets", "select", "selectors", "shelve", "shlex", "shutil",
    "signal", "site", "smtpd", "smtplib", "sndhdr", "socket", "socketserver",
    "spwd", "sqlite3", "ssl", "stat", "statistics", "string", "stringprep",
    "struct", "subprocess", "sunau", "symbol", "symtable", "sys", "sysconfig",
    "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile", "termios", "test",
    "textwrap", "threading", "time", "timeit", "tkinter", "token", "tokenize",
    "trace", "traceback", "tracemalloc", "tty", "turtle", "turtledemo", "types",
    "typing", "typing_extensions", "unicodedata", "unittest", "urllib", "uu", "uuid",
    "venv", "warnings", "wave", "weakref", "webbrowser", "winreg", "winsound",
    "wsgiref", "xdrlib", "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
    # Python 3.10+
    "graphlib", "zoneinfo",
    # Python 3.11+
    "tomllib",
}


def extract_imports_from_file(file_path: Path) -> set:
    """Extract all top-level import names from a Python file."""
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except Exception as e:
        print(f"  ⚠️  Failed to parse {file_path}: {e}")
        return set()

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Extract top-level module name
                module = alias.name.split('.')[0]
                imports.add(module)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                # Extract top-level module name
                module = node.module.split('.')[0]
                imports.add(module)

    return imports


def get_local_modules(repo_root: Path) -> set:
    """Get set of local module names (api, scripts, etc.)."""
    local = set()

    # Top-level directories that are local modules
    for path in repo_root.iterdir():
        if path.is_dir() and not path.name.startswith('.') and not path.name.startswith('__'):
            # Check if it has __init__.py or .py files
            if (path / "__init__.py").exists() or any(path.glob("*.py")):
                local.add(path.name)

    # Also scan scripts subdirectories (scripts/adapters, scripts/analytics, etc.)
    scripts_dir = repo_root / "scripts"
    if scripts_dir.exists():
        for subdir in scripts_dir.iterdir():
            if subdir.is_dir() and not subdir.name.startswith('.') and not subdir.name.startswith('__'):
                # Check if it has __init__.py or .py files
                if (subdir / "__init__.py").exists() or any(subdir.glob("*.py")):
                    local.add(subdir.name)

        # Also scan individual .py files in scripts/ (call_scorer.py, utils.py, etc.)
        for py_file in scripts_dir.glob("*.py"):
            if not py_file.name.startswith('_'):
                # Add module name without .py extension
                local.add(py_file.stem)

    # Also scan api/ for individual .py files (router.py, db.py, etc.)
    api_dir = repo_root / "api"
    if api_dir.exists():
        for py_file in api_dir.glob("*.py"):
            if not py_file.name.startswith('_'):
                # Add module name without .py extension
                local.add(py_file.stem)

    # Also scan scripts/adapters subdirectories (calls, crm, storage)
    adapters_dir = repo_root / "scripts" / "adapters"
    if adapters_dir.exists():
        for subdir in adapters_dir.iterdir():
            if subdir.is_dir() and not subdir.name.startswith('.') and not subdir.name.startswith('__'):
                # Check if it has __init__.py or .py files
                if (subdir / "__init__.py").exists() or any(subdir.glob("*.py")):
                    local.add(subdir.name)

    # Known local modules (legacy/dead code that may be imported but file doesn't exist)
    # hubspot_deals: imported in rollup_deal_scores.py but file is missing (dead code)
    local.add("hubspot_deals")

    return local


def get_declared_packages(repo_root: Path) -> set:
    """Get set of packages declared in requirements.txt."""
    req_file = repo_root / "requirements.txt"
    if not req_file.exists():
        print(f"  ❌ requirements.txt not found at {req_file}")
        return set()

    declared = set()
    for line in req_file.read_text().splitlines():
        line = line.strip()
        # Skip empty lines and comments
        if not line or line.startswith('#'):
            continue
        # Extract package name (before ==, >=, etc.)
        package = line.split('==')[0].split('>=')[0].split('<=')[0].split('~=')[0].strip()
        declared.add(package)

    return declared


def run():
    repo_root = Path(__file__).resolve().parent.parent

    print("=" * 72)
    print("DEPENDENCY DRIFT GUARD")
    print("=" * 72)
    print()
    print("Guard against: Undeclared imports (tests pass locally, fail on fresh clone)")
    print()

    # Scan all Python files for imports
    all_imports = set()
    scanned_files = []

    for pattern in SCANNED_PATHS:
        for file_path in repo_root.glob(pattern):
            if file_path.is_file():
                scanned_files.append(file_path)
                imports = extract_imports_from_file(file_path)
                all_imports.update(imports)

    print(f"Scanned {len(scanned_files)} files across {len(SCANNED_PATHS)} path patterns")
    print(f"Found {len(all_imports)} unique imports")
    print()

    # Filter out stdlib and local modules
    local_modules = get_local_modules(repo_root)
    print(f"Local modules: {sorted(local_modules)}")

    third_party_imports = all_imports - STDLIB_MODULES - local_modules
    print(f"Third-party imports: {len(third_party_imports)}")
    print()

    # Map imports to package names
    required_packages = set()
    unknown_imports = []

    for imp in sorted(third_party_imports):
        if imp in IMPORT_TO_PACKAGE:
            required_packages.add(IMPORT_TO_PACKAGE[imp])
        else:
            unknown_imports.append(imp)

    # Get declared packages
    declared_packages = get_declared_packages(repo_root)

    # Check for missing packages
    missing = required_packages - declared_packages

    # Check for unused packages (warning only)
    unused = declared_packages - required_packages

    # Report results
    passed = 0
    failed = 0

    print("[TEST] All third-party imports are declared in requirements.txt")

    if unknown_imports:
        failed += 1
        print(f"  ❌ Unknown imports (not in IMPORT_TO_PACKAGE alias map):")
        for imp in unknown_imports:
            print(f"     - {imp}")
        print()
        print("  Fix: Add to IMPORT_TO_PACKAGE in this file")
        print("  (Unknown imports FAIL to prevent alias map going stale)")
        print()

    if missing:
        failed += 1
        print(f"  ❌ Missing from requirements.txt:")
        for pkg in sorted(missing):
            print(f"     - {pkg}")
        print()
        print("  Fix: Add to requirements.txt")
        print()

    if not unknown_imports and not missing:
        passed += 1
        print("  ✓ All imports are declared in requirements.txt")
        print()

    # Warnings (not failures)
    if unused:
        print(f"  ⚠️  Declared but not imported ({len(unused)} packages):")
        for pkg in sorted(unused):
            print(f"     - {pkg}")
        print()
        print("  This is a WARNING, not a failure (packages may be runtime-only)")
        print()

    print("=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 72)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
