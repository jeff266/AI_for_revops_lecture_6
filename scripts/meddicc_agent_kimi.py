"""
MEDDICC Agent with Kimi K3 Integration

Hybrid architecture:
- Generator: Claude Sonnet 4.5 (quality)
- Evaluator: Kimi K3 (cost)
- Context Builder: Kimi K3 (cost)

Cost reduction: ~70% vs all-Claude architecture
"""
import os
import json
from pathlib import Path
from typing import Dict, Optional
from anthropic import Anthropic
from kimi_client import get_kimi_client


def load_claude_md() -> str:
    """Load current CLAUDE.md instructions."""
    prompts_dir = Path(__file__).parent.parent / "prompts"
    claude_md_path = prompts_dir / "CLAUDE.md"

    with open(claude_md_path, 'r') as f:
        return f.read()


def load_evaluator_rubric() -> str:
    """Load evaluator rubric."""
    prompts_dir = Path(__file__).parent.parent / "prompts"
    rubric_path = prompts_dir / "evaluator_rubric.md"

    with open(rubric_path, 'r') as f:
        return f.read()


def build_initial_messages(
    call_summary: str,
    cumulative_state: dict,
    deal_context: dict,
    previous_feedback: Optional[str] = None
) -> list:
    """Build initial messages for generator."""

    # Format cumulative state
    cumulative_json = json.dumps(cumulative_state, indent=2)

    # Format deal context
    deal_props = deal_context.get('deal', {}).get('properties', {})
    company_props = deal_context.get('company', {}).get('properties', {}) if deal_context.get('company') else {}
    contacts = deal_context.get('contacts', [])

    deal_info = f"""**Company**: {company_props.get('name', 'Unknown')}
**Stage**: {deal_props.get('dealstage', 'Unknown')}
**ARR**: ${deal_props.get('incremental_arr', deal_props.get('amount', 0)):,}
**Close Date**: {deal_props.get('closedate', 'Unknown')}
**Contacts**: {len(contacts)} contacts associated"""

    # Build user message
    user_content = f"""# Recent Call Summary

{call_summary}

---

# Cumulative MEDDICC State (from all previous calls)

```json
{cumulative_json}
```

---

# Deal Context (from HubSpot)

{deal_info}

---

Generate a MEDDICC analysis following the format in your instructions."""

    if previous_feedback:
        user_content += f"""

---

# EVALUATOR FEEDBACK - PLEASE ADDRESS

The previous analysis failed evaluation. You must fix these issues:

{previous_feedback}

Regenerate the analysis addressing all the feedback above."""

    return [{"role": "user", "content": user_content}]


def generate(
    call_summary: str,
    cumulative_state: dict,
    deal_context: dict,
    previous_feedback: Optional[str],
    claude_md: str,
    client: Anthropic
) -> Dict:
    """
    Generate MEDDICC analysis using Claude Sonnet 4.5.

    Returns:
        Dict with content and cost
    """
    messages = build_initial_messages(
        call_summary,
        cumulative_state,
        deal_context,
        previous_feedback
    )

    # Inner tool loop
    while True:
        response = client.messages.create(
            model='claude-sonnet-4-5-20250929',
            system=claude_md,
            messages=messages,
            max_tokens=4000
        )

        # Check stop reason
        if response.stop_reason == 'end_turn':
            # Extract text from response
            text_content = ""
            for block in response.content:
                if block.type == 'text':
                    text_content += block.text

            # Calculate cost (Sonnet 4.5 pricing)
            cost = (
                response.usage.input_tokens / 1_000_000 * 3.0 +  # $3/M input
                response.usage.output_tokens / 1_000_000 * 15.0  # $15/M output
            )

            return {
                "content": text_content,
                "cost": cost,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens
                }
            }

        elif response.stop_reason == 'tool_use':
            # Add assistant message
            messages.append({"role": "assistant", "content": response.content})

            # Add tool results (reject tool use)
            tool_results = []
            for block in response.content:
                if block.type == 'tool_use':
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Tool use not supported for MEDDICC analysis. Please generate the analysis directly."
                    })

            messages.append({"role": "user", "content": tool_results})

        else:
            # Max tokens or other stop reason
            text_content = ""
            for block in response.content:
                if block.type == 'text':
                    text_content += block.text

            if not text_content:
                return {"content": "[Generation error: no text content returned]", "cost": 0.0, "usage": {}}

            cost = (
                response.usage.input_tokens / 1_000_000 * 3.0 +
                response.usage.output_tokens / 1_000_000 * 15.0
            )

            return {"content": text_content, "cost": cost, "usage": {}}


def evaluate_kimi(
    draft: str,
    call_summary: str,
    cumulative_state: dict,
    rubric: str,
    client
) -> dict:
    """
    Evaluate MEDDICC analysis using Kimi K3.

    ~80% cost reduction vs Claude Haiku.
    """
    cumulative_json = json.dumps(cumulative_state, indent=2)

    evaluation_prompt = f"""# Generated MEDDICC Analysis to Evaluate

{draft}

---

# Recent Call Summary (source material)

{call_summary}

---

# Cumulative MEDDICC State (historical context)

```json
{cumulative_json}
```

---

Evaluate this analysis against the rubric and return ONLY a JSON object with your assessment. No additional text."""

    result = client.create_message(
        system=rubric,
        messages=[{"role": "user", "content": evaluation_prompt}],
        max_tokens=2000,
        temperature=0.0
    )

    content = result["content"]

    try:
        # Handle markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        evaluation = json.loads(content)

        # Validate structure
        required_keys = ['pass', 'required_changes', 'iteration_failures',
                        'components_weak', 'components_strong', 'proposed_instruction']

        for key in required_keys:
            if key not in evaluation:
                evaluation[key] = None if key in ['required_changes', 'proposed_instruction'] else []

        # Add cost metadata
        evaluation['_cost'] = result["cost"]
        evaluation['_model'] = "kimi_k3"

        return evaluation

    except json.JSONDecodeError as e:
        print(f"Failed to parse Kimi evaluator JSON: {e}")
        print(f"Response: {content[:500]}")

        return {
            "pass": False,
            "required_changes": f"Evaluator parse error: {str(e)}",
            "iteration_failures": ["evaluator_parse_error"],
            "components_weak": [],
            "components_strong": [],
            "proposed_instruction": "Fix evaluator JSON output format",
            "error": str(e),
            "raw_content": content[:500],
            "_cost": result.get("cost", 0.0),
            "_model": "kimi_k3"
        }


def run_agent(
    call_summary: str,
    cumulative_state: dict,
    deal_context: dict,
    claude_md: str = None,
    rubric: str = None,
    max_iterations: int = 3
) -> dict:
    """
    Run MEDDICC agent with Kimi K3 hybrid architecture.

    Architecture:
    - Generator: Claude Sonnet 4.5
    - Evaluator: Kimi K3
    - Context Builder: Kimi K3 (called separately)
    """
    claude_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    kimi_client = get_kimi_client()

    # Load prompts if not provided
    if claude_md is None:
        claude_md = load_claude_md()

    if rubric is None:
        rubric = load_evaluator_rubric()

    # Track costs
    total_cost = 0.0
    generation_cost = 0.0
    evaluation_cost = 0.0

    # Outer loop: max 3 iterations
    previous_feedback = None
    draft = None
    evaluation = None

    for iteration in range(1, max_iterations + 1):
        print(f"  Iteration {iteration}/{max_iterations}...")

        # Generate analysis (Claude Sonnet 4.5)
        gen_result = generate(
            call_summary,
            cumulative_state,
            deal_context,
            previous_feedback,
            claude_md,
            claude_client
        )

        draft = gen_result["content"]
        generation_cost += gen_result["cost"]

        # Evaluate analysis (Kimi K3)
        evaluation = evaluate_kimi(
            draft,
            call_summary,
            cumulative_state,
            rubric,
            kimi_client
        )

        evaluation_cost += evaluation.get("_cost", 0.0)

        # Check if passed
        if evaluation['pass']:
            print(f"  ✓ Passed on iteration {iteration}")
            break

        # Extract feedback for next iteration
        previous_feedback = evaluation.get('required_changes')
        print(f"  ✗ Failed iteration {iteration}: {len(evaluation.get('iteration_failures', []))} issues")

    total_cost = generation_cost + evaluation_cost

    # Add cumulative state cost if available
    cumulative_cost = cumulative_state.get("_cost", 0.0)
    total_cost += cumulative_cost

    # Return final result
    return {
        'draft': draft,
        'evaluation': evaluation,
        'iterations': iteration,
        'passed': evaluation['pass'] if evaluation else False,
        'model_used': {
            'generator': 'claude-sonnet-4-5',
            'evaluator': 'kimi_k3',
            'context_builder': cumulative_state.get('_model', 'unknown')
        },
        'cost_breakdown': {
            'generation': generation_cost,
            'evaluation': evaluation_cost,
            'cumulative_state': cumulative_cost,
            'total': total_cost
        }
    }


if __name__ == "__main__":
    # Test with sample data
    test_call_summary = """# Technical Deep Dive - Acme Corp
Date: 2026-07-25 | Duration: 45m

## Summary
Deep dive with Sarah Chen (VP Engineering) and Mark Liu (Tech Lead). Covered SDK quality, visual editor requirements, and SSO/SAML needs. Mark very excited about our SDK vs LaunchDarkly. Sarah mentioned John Torres (CFO) makes final vendor decisions. Budget approved for $100k solution if ROI is clear.

## Keywords
SDK quality, visual editor, experimentation, SSO, SAML, budget approval

## Action Items
- Create POC environment for Mark's team
- Schedule CFO meeting with John Torres
- Provide security questionnaire responses"""

    test_cumulative_state = {
        "company": "Acme Corp",
        "calls_reviewed": 2,
        "meddicc_state": {
            "metrics": {"status": "identified", "evidence": "Sarah mentioned $500k annual loss from failed experiments", "score": 8},
            "economic_buyer": {"status": "identified", "evidence": "John Torres (CFO) confirmed as final decision maker", "score": 9},
            "decision_criteria": {"status": "partial", "evidence": "Visual editor, SSO/SAML mentioned but not fully detailed", "score": 5},
            "decision_process": {"status": "partial", "evidence": "CFO approval needed for >$50k, timeline Q4 planning September", "score": 6},
            "identified_pain": {"status": "identified", "evidence": "LaunchDarkly pricing and complexity frustration", "score": 8},
            "champion": {"status": "partial", "evidence": "Mark Liu (Tech Lead) excited, not confirmed as champion", "score": 5},
            "competition": {"status": "identified", "evidence": "Currently using LaunchDarkly, frustrated with pricing", "score": 8}
        },
        "key_context": "Mid-stage technical evaluation with strong champion (Mark) and identified economic buyer (John Torres CFO).",
        "_cost": 0.0005,  # Simulated cumulative state cost
        "_model": "kimi_k3"
    }

    test_deal_context = {
        "deal": {"properties": {"dealname": "Acme Corp - Feature Flags", "dealstage": "presentationscheduled", "incremental_arr": "95000", "closedate": "2026-09-15"}},
        "company": {"properties": {"name": "Acme Corp", "domain": "acme.com", "numberofemployees": "250"}},
        "contacts": [
            {"properties": {"firstname": "Sarah", "lastname": "Chen", "jobtitle": "VP Engineering"}},
            {"properties": {"firstname": "Mark", "lastname": "Liu", "jobtitle": "Tech Lead"}},
            {"properties": {"firstname": "John", "lastname": "Torres", "jobtitle": "CFO"}}
        ]
    }

    print("=" * 80)
    print("TESTING KIMI K3 HYBRID MEDDICC AGENT")
    print("=" * 80)

    result = run_agent(
        call_summary=test_call_summary,
        cumulative_state=test_cumulative_state,
        deal_context=test_deal_context
    )

    print("\n" + "=" * 80)
    print("FINAL RESULT")
    print("=" * 80)
    print(f"Iterations: {result['iterations']}")
    print(f"Passed: {result['passed']}")
    print(f"Model architecture: {result['model_used']}")
    print(f"\nCost Breakdown:")
    print(f"  Generation (Sonnet): ${result['cost_breakdown']['generation']:.6f}")
    print(f"  Evaluation (Kimi):   ${result['cost_breakdown']['evaluation']:.6f}")
    print(f"  Context (Kimi):      ${result['cost_breakdown']['cumulative_state']:.6f}")
    print(f"  TOTAL:               ${result['cost_breakdown']['total']:.6f}")

    print(f"\nWeak components: {result['evaluation'].get('components_weak', [])}")
    print(f"Strong components: {result['evaluation'].get('components_strong', [])}")

    print("\n" + "=" * 80)
    print("GENERATED ANALYSIS (First 500 chars)")
    print("=" * 80)
    print(result['draft'][:500])
    print("..." if len(result['draft']) > 500 else "")
    print("=" * 80)
