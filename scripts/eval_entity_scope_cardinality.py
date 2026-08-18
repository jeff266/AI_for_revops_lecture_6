#!/usr/bin/env python3
"""
Eval: Entity scope cardinality guard.

Tests that should_use_entity_scope:
1. Returns False when stated count mismatches scope size (forces rediscovery)
2. Returns True when stated count matches scope size (bypass allowed)
3. Returns True when no count is stated (bypass allowed, existing behavior)
4. Returns True when incidental numbers appear (bypass allowed)

This prevents the bug where "what are the stages for the 10 deals you
flagged" silently answered for 4 deals when only 4 were in thread scope,
with no caveat or quality flag.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_entity_scope_cardinality():
    """Test that entity scope bypass checks cardinality."""
    from api.router import should_use_entity_scope, stated_entity_count
    from datetime import datetime, timezone
    import logging
    logging.getLogger("api.router").setLevel(logging.CRITICAL)  # Suppress logs during test

    print("="*80)
    print("ENTITY SCOPE CARDINALITY EVAL")
    print("="*80)
    print()

    # Mock prior_entities with 4 deals (fresh, < 30 minutes old)
    prior_entities = {
        "deal_ids": ["123", "456", "789", "101"],
        "company_names": ["Acme", "TechCo", "StartupX", "BizCorp"],
        "resolved_at": datetime.now(timezone.utc).isoformat()
    }

    # Test 1: stated_entity_count() helper function
    print("[TEST 1] stated_entity_count() extracts explicit counts")
    print()

    test_cases = [
        ("what are the stages for the 10 deals you flagged?", 10, "digit count"),
        ("show me those 3", 3, "those N"),
        ("all 5 of them", 5, "all N of"),
        ("these two deals", 2, "number word"),
        ("the one you mentioned", 1, "the one"),
        ("deals closing in Q3", None, "incidental Q3"),
        ("show me $2M pipeline", None, "dollar amount"),
        ("which deals?", None, "no count"),
        ("the three companies", 3, "the three"),
        ("those seven at risk", 7, "those seven"),
    ]

    for question, expected, description in test_cases:
        result = stated_entity_count(question)
        status = "✓" if result == expected else "✗"
        print(f"  {status} \"{question}\"")
        print(f"     → {result} (expected: {expected}) [{description}]")
        assert result == expected, f"Failed: {description}"

    print()

    # Test 2: Stated count matches scope size (bypass allowed)
    print("[TEST 2] Stated count matches scope size → bypass allowed")

    question_match = "what are the stages for the 4 deals you flagged?"
    result_match = should_use_entity_scope(question_match, prior_entities)

    print(f"  Question: \"{question_match}\"")
    print(f"  Scope size: {len(prior_entities['deal_ids'])}")
    print(f"  Stated count: {stated_entity_count(question_match)}")
    print(f"  Result: {result_match} (expected: True)")

    assert result_match is True, "Should bypass when stated count matches scope"
    print(f"  ✓ Bypass allowed (cardinality matches)")
    print()

    # Test 3: Stated count differs from scope size (rediscovery forced)
    print("[TEST 3] Stated count differs from scope → rediscovery forced")

    question_mismatch = "what are the stages for the 10 deals you flagged?"
    result_mismatch = should_use_entity_scope(question_mismatch, prior_entities)

    print(f"  Question: \"{question_mismatch}\"")
    print(f"  Scope size: {len(prior_entities['deal_ids'])}")
    print(f"  Stated count: {stated_entity_count(question_mismatch)}")
    print(f"  Result: {result_mismatch} (expected: False)")

    assert result_mismatch is False, "Should force rediscovery when cardinality mismatches"
    print(f"  ✓ Rediscovery forced (cardinality mismatch: 10 != 4)")
    print()

    # Test 4: No stated count (bypass allowed, existing behavior)
    print("[TEST 4] No stated count → bypass allowed (existing behavior)")

    question_no_count = "which deals are at risk?"
    result_no_count = should_use_entity_scope(question_no_count, prior_entities)

    print(f"  Question: \"{question_no_count}\"")
    print(f"  Scope size: {len(prior_entities['deal_ids'])}")
    print(f"  Stated count: {stated_entity_count(question_no_count)}")
    print(f"  Result: {result_no_count} (expected: True)")

    assert result_no_count is True, "Should bypass when no count stated (existing behavior)"
    print(f"  ✓ Bypass allowed (no count stated)")
    print()

    # Test 5: Incidental number (bypass allowed)
    print("[TEST 5] Incidental number → bypass allowed")

    question_incidental = "which deals close in Q3?"
    result_incidental = should_use_entity_scope(question_incidental, prior_entities)

    print(f"  Question: \"{question_incidental}\"")
    print(f"  Scope size: {len(prior_entities['deal_ids'])}")
    print(f"  Stated count: {stated_entity_count(question_incidental)}")
    print(f"  Result: {result_incidental} (expected: True)")

    assert result_incidental is True, "Should bypass when number is incidental (Q3 not a count)"
    print(f"  ✓ Bypass allowed (incidental number, not a count)")
    print()

    # Test 6: Edge case - empty scope always returns False
    print("[TEST 6] Edge case - empty scope always returns False")

    empty_prior = {
        "deal_ids": [],
        "company_names": [],
        "resolved_at": datetime.now(timezone.utc).isoformat()
    }

    question_zero = "show me those zero"
    result_zero = should_use_entity_scope(question_zero, empty_prior)

    print(f"  Question: \"{question_zero}\"")
    print(f"  Scope size: {len(empty_prior['deal_ids'])}")
    print(f"  Stated count: {stated_entity_count(question_zero)}")
    print(f"  Result: {result_zero} (expected: False)")

    assert result_zero is False, "Should return False when scope is empty (no prior entities)"
    print(f"  ✓ Correctly returns False (no prior entities to reuse)")
    print()

    print("="*80)
    print("Results: All tests passed!")
    print("="*80)
    print()
    print("VERIFIED:")
    print("- stated_entity_count() correctly extracts explicit counts")
    print("- Cardinality mismatch forces rediscovery")
    print("- Cardinality match allows bypass")
    print("- No stated count allows bypass (existing behavior preserved)")
    print("- Incidental numbers allow bypass")

if __name__ == "__main__":
    test_entity_scope_cardinality()
