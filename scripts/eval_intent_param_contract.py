#!/usr/bin/env python3
"""
Eval: the classifier's output schema and the handlers' expected params agree.

WHY (FIX_DYNAMIC_FALLBACK_PATTERN follow-up):
query_rep_pipeline failed not only for missing name resolution but because of a
CONTRACT DRIFT: build_intent_prompt tells the classifier to emit `rep_email`,
while the handler read `owner_email`. A correctly-classified request with a
resolved email still fell through — straight into the budget-burning dynamic
loop. Nothing verified that the two contracts agree.

This test enforces the invariant: every param the intent prompt instructs the
classifier to EMIT must be a param that SOME handler (or the router) actually
READS. A param emitted but read nowhere is dead contract — a latent bug the
day a handler is expected to honour it.

Direction is emitted ⊆ read. The reverse is fine: handlers legitimately read
params the classifier never emits (deal_ids / company_names come from thread
entity-scope; owner_email is the resolved form of rep_email; score/component
come from other paths).
"""
import re
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

if "supabase" not in sys.modules:
    _f = types.ModuleType("supabase")
    _f.create_client = lambda *a, **k: None
    _f.Client = type("Client", (), {})
    sys.modules["supabase"] = _f


def emitted_params() -> set:
    """Keys the classifier is told to emit — the `params` object of the
    prompt, read by brace-depth so nested keys (time_window's) don't count as
    separate top-level params."""
    from api.router import build_intent_prompt
    prompt = build_intent_prompt(today="2026-08-21",
                                 current_quarter="FY2027 Q3",
                                 history="[]", question="test")
    anchor = prompt.index('"params"')
    brace = prompt.index("{", anchor)
    depth, i, keys = 0, brace, set()
    while i < len(prompt):
        c = prompt[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        elif c == '"' and depth == 1:
            # a top-level key is a quoted token immediately followed by ':'
            m = re.match(r'"([a-z_]+)"\s*:', prompt[i:])
            if m:
                keys.add(m.group(1))
                i += m.end() - 1
        i += 1
    return keys


def read_params() -> set:
    """Every param key any handler or the router reads via params.get("x")
    or params["x"]."""
    pat = re.compile(r'params(?:\.get\(|\[)\s*["\']([a-z_]+)["\']')
    keys = set()
    for rel in ("api/handlers.py", "api/router.py"):
        src = (REPO / rel).read_text()
        keys.update(pat.findall(src))
    return keys


def run():
    print("=" * 72)
    print("INTENT PARAM CONTRACT — classifier emits ⊆ handlers/router read")
    print("=" * 72)

    emitted = emitted_params()
    read = read_params()

    # Sanity: the parse must actually find the schema, or the test is vacuous.
    assert "time_window" in emitted and "rep_email" in emitted, \
        f"schema parse failed — emitted={sorted(emitted)}"

    orphans = sorted(emitted - read)

    print(f"\n  emitted by classifier ({len(emitted)}): {sorted(emitted)}")
    print(f"  read by handlers/router ({len(read)})")
    print()

    passed = failed = 0
    # The specific drift that caused the outage: rep_email / sdr_email must be
    # consumed, since the prompt tells the classifier to put resolved emails
    # there for rep and SDR questions.
    for k in ("rep_email", "sdr_email"):
        if k in read:
            passed += 1; print(f"  ✓ '{k}' (classifier's rep/SDR email slot) is read")
        else:
            failed += 1; print(f"  ❌ '{k}' emitted by classifier but read by NO handler")

    if orphans:
        failed += 1
        print(f"  ❌ emitted but read nowhere (dead contract): {orphans}")
    else:
        passed += 1
        print(f"  ✓ every emitted param is read by a handler or the router")

    print("\n" + "=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
