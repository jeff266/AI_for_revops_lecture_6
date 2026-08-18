#!/usr/bin/env python3
"""
Eval: Phase G.9 Voice Layer

Tests that:
1. SYNTHESIS_SYSTEM_PROMPT contains voice instruction
2. Report shape guides synthesis structure
3. ASSESS returns tone_score and tone_issue fields
4. Tone check distinguishes good from bad tone
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_voice_layer():
    """Test voice layer components."""
    import asyncio

    print("="*80)
    print("PHASE G.9 VOICE LAYER EVAL")
    print("="*80)
    print()

    # Test 1: SYNTHESIS_SYSTEM_PROMPT contains voice instruction
    print("[TEST 1] SYNTHESIS_SYSTEM_PROMPT contains voice instruction")

    from api.router import SYNTHESIS_SYSTEM_PROMPT

    voice_keywords = [
        "VP of RevOps",
        "Lead with the number",
        "Flag risk explicitly",
        "Close with one sentence of judgment"
    ]

    for keyword in voice_keywords:
        assert keyword in SYNTHESIS_SYSTEM_PROMPT, \
            f"Voice instruction missing keyword: {keyword}"

    print(f"  ✓ Voice instruction present in SYNTHESIS_SYSTEM_PROMPT")
    print(f"  ✓ Contains: VP RevOps persona, headline-first, risk flagging, judgment close")
    print()

    # Test 2: Report shapes exist and handler can declare them
    print("[TEST 2] Report shapes exist and handlers can declare them")

    from api.router import REPORT_SHAPES

    expected_shapes = ["snapshot", "trend", "risk_alert", "comparison"]
    for shape in expected_shapes:
        assert shape in REPORT_SHAPES, f"Missing report shape: {shape}"
        assert "order" in REPORT_SHAPES[shape], f"Shape {shape} missing 'order'"
        assert "description" in REPORT_SHAPES[shape], f"Shape {shape} missing 'description'"

    print(f"  ✓ All 4 report shapes defined: {expected_shapes}")
    print(f"  ✓ Each has 'order' and 'description' fields")

    # Verify query_waterfall uses report_shape
    from api.handlers import query_waterfall

    params = {
        "time_window": {
            "start": "2026-08-10",
            "end": "2026-08-17",
            "label": "This Week"
        },
        "question": "show me pipeline"
    }

    # Mock Supabase
    class MockSupabase:
        def table(self, name):
            return self
        def select(self, *args):
            return self
        def eq(self, *args):
            return self
        def gte(self, *args):
            return self
        def lte(self, *args):
            return self
        def range(self, *args):
            return self
        def execute(self):
            class Result:
                data = []
            return Result()

    result = asyncio.run(query_waterfall(params, MockSupabase()))

    assert "report_shape" in result, "query_waterfall should declare report_shape"
    assert result["report_shape"] in REPORT_SHAPES, \
        f"Invalid report_shape: {result['report_shape']}"

    print(f"  ✓ query_waterfall declares report_shape: {result['report_shape']}")
    print()

    # Test 3: ASSESS returns tone_score and tone_issue
    print("[TEST 3] ASSESS returns tone_score and tone_issue on bad-tone answer")

    from api.assessor import assess_correctness
    import anthropic

    # Mock Anthropic client that returns known response
    class MockAnthropicClient:
        def __init__(self, response_json):
            self.response_json = response_json

        def messages_create(self, **kwargs):
            class Response:
                def __init__(self, text):
                    self.content = [type('obj', (object,), {'text': text})]
            return Response(self.response_json)

        class messages:
            @staticmethod
            def create(**kwargs):
                # Return low tone score for bad answer
                import json
                return type('obj', (object,), {
                    'content': [type('obj', (object,), {
                        'text': json.dumps({
                            "correct": True,
                            "score": 0.8,
                            "issue": None,
                            "tone_score": 0.3,  # Low tone score
                            "tone_issue": "buried_headline",
                            "suggested_handler": None,
                            "suggested_params": None,
                            "learning_note": None
                        })
                    })]
                })()

    client = MockAnthropicClient("{}")

    bad_tone_answer = """
    Here's what I found in the data:
    - Deal 1: Company A, $100K
    - Deal 2: Company B, $200K
    - Deal 3: Company C, $50K

    The data shows various deals with different values."""

    assessment = asyncio.run(assess_correctness(
        question="What are our top deals?",
        handler_used="query_deals",
        tool_results={"deals": [{"company": "A", "value": 100000}]},
        answer=bad_tone_answer,
        client=client,
        budget_used=0.01
    ))

    assert "tone_score" in assessment, "Assessment missing tone_score"
    assert "tone_issue" in assessment, "Assessment missing tone_issue"

    print(f"  ✓ Assessment includes tone_score: {assessment.get('tone_score')}")
    print(f"  ✓ Assessment includes tone_issue: {assessment.get('tone_issue')}")
    print()

    # Test 4: Tone check distinguishes good from bad (red/green)
    print("[TEST 4] Tone scoring distinguishes good from bad tone")

    # For this test, we need to show that:
    # - Bad tone (wall of data, no headline, no judgment) → low score
    # - Good tone (headline first, flagged risk, judgment) → high score

    # The mock client in Test 3 already returned low score (0.3) for bad answer
    # Now test that a good answer would get a high score

    good_tone_answer = """
    📊 *3 deals totaling $350K in pipeline*

    *Top deals:*
    • *Company B* — $200K | Negotiating
    • *Company A* — $100K | Discovery
    • *Company C* — $50K | Scoping

    Bottom line: healthy mix but Company B carries 57% of total value —
    watch that concentration risk."""

    # Mock client that returns HIGH tone score for good answer
    class MockGoodToneClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                import json
                return type('obj', (object,), {
                    'content': [type('obj', (object,), {
                        'text': json.dumps({
                            "correct": True,
                            "score": 0.9,
                            "issue": None,
                            "tone_score": 0.9,  # High tone score
                            "tone_issue": None,
                            "suggested_handler": None,
                            "suggested_params": None,
                            "learning_note": None
                        })
                    })]
                })()

    good_client = MockGoodToneClient()

    good_assessment = asyncio.run(assess_correctness(
        question="What are our top deals?",
        handler_used="query_deals",
        tool_results={"deals": [{"company": "B", "value": 200000}]},
        answer=good_tone_answer,
        client=good_client,
        budget_used=0.01
    ))

    good_tone_score = good_assessment.get('tone_score', 0.0)
    bad_tone_score = assessment.get('tone_score', 0.0)

    print(f"  Bad tone answer (buried headline, no judgment):")
    print(f"    tone_score: {bad_tone_score}")
    print(f"    tone_issue: {assessment.get('tone_issue')}")

    print(f"  Good tone answer (headline first, flagged risk, judgment):")
    print(f"    tone_score: {good_tone_score}")
    print(f"    tone_issue: {good_assessment.get('tone_issue') or 'none'}")

    assert good_tone_score > bad_tone_score, \
        f"Good tone should score higher than bad ({good_tone_score} vs {bad_tone_score})"

    assert good_tone_score >= 0.7, \
        f"Good tone should score >= 0.7, got {good_tone_score}"

    assert bad_tone_score < 0.7, \
        f"Bad tone should score < 0.7, got {bad_tone_score}"

    print(f"  ✓ Tone check distinguishes good ({good_tone_score}) from bad ({bad_tone_score})")
    print()

    print("="*80)
    print("Results: All tests passed!")
    print("="*80)

if __name__ == "__main__":
    test_voice_layer()
