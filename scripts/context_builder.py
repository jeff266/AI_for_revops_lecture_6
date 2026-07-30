"""
Context Builder for MEDDICC Agent

Builds cumulative MEDDICC state from historical call summaries using Claude Haiku.
"""
import os
import json
from typing import List, Dict
from anthropic import Anthropic


def build_cumulative_meddicc(call_summaries: List[str], company: str) -> dict:
    """
    Build cumulative MEDDICC state from all historical call summaries.

    Args:
        call_summaries: List of formatted call summaries (excluding most recent)
        company: Company name

    Returns:
        Structured MEDDICC state object with status, evidence, and scores
    """
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Build prompt
    system_prompt = """You are a MEDDICC sales methodology analyzer.

Your job is to review ALL historical call summaries for a company and extract the cumulative MEDDICC state across all conversations.

For each MEDDICC component, determine:
1. **Status**: identified (confirmed with specific evidence), partial (mentioned but not confirmed), or unknown (not discussed)
2. **Evidence**: Direct quote or paraphrase from the calls that supports the status
3. **Score**: 1-10 rating based on clarity and strength of evidence

MEDDICC Components:
- Metrics: Quantifiable business outcomes the buyer cares about
- Economic Buyer: Person with budget authority and final say
- Decision Criteria: Technical and business requirements for selecting a solution
- Decision Process: Steps, timeline, stakeholders involved in making the decision
- Identified Pain: Specific business problem or challenge being solved
- Champion: Internal advocate who will sell on your behalf
- Competition: Other solutions being evaluated

Output a JSON object with this exact structure:
{
  "company": "CompanyName",
  "calls_reviewed": <number>,
  "meddicc_state": {
    "metrics": {
      "status": "identified|partial|unknown",
      "evidence": "Specific quote or detail from calls",
      "score": 1-10
    },
    "economic_buyer": { ... },
    "decision_criteria": { ... },
    "decision_process": { ... },
    "identified_pain": { ... },
    "champion": { ... },
    "competition": { ... }
  },
  "key_context": "2-3 sentence summary of the overall deal context and stage"
}

CRITICAL RULES:
1. Evidence MUST come from the call summaries - no inference
2. If something hasn't been discussed across ANY call, mark it as "unknown"
3. Status "identified" requires specific, clear evidence
4. Status "partial" means mentioned but lacking details
5. Scores reflect evidence quality: 1-3 = weak/unknown, 4-6 = partial, 7-10 = strong/identified"""

    # Combine all call summaries
    combined_summaries = "\n\n" + "\n\n---\n\n".join(call_summaries)

    user_message = f"""Company: {company}

Analyze the following {len(call_summaries)} call summaries and extract the cumulative MEDDICC state:

{combined_summaries}

Output ONLY valid JSON with no additional text."""

    # Call Haiku
    response = client.messages.create(
        model="claude-3-7-haiku-20250219",
        max_tokens=2000,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": user_message
        }]
    )

    # Extract JSON from response
    content = response.content[0].text

    # Try to parse JSON
    try:
        # Handle markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        meddicc_state = json.loads(content)

        # Validate structure
        if "meddicc_state" not in meddicc_state:
            raise ValueError("Missing meddicc_state key")

        # Add metadata
        meddicc_state["company"] = company
        meddicc_state["calls_reviewed"] = len(call_summaries)

        return meddicc_state

    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON response: {e}")
        print(f"Response content: {content}")

        # Return empty state on parse failure
        return {
            "company": company,
            "calls_reviewed": len(call_summaries),
            "meddicc_state": {
                "metrics": {"status": "unknown", "evidence": "Parse error", "score": 0},
                "economic_buyer": {"status": "unknown", "evidence": "Parse error", "score": 0},
                "decision_criteria": {"status": "unknown", "evidence": "Parse error", "score": 0},
                "decision_process": {"status": "unknown", "evidence": "Parse error", "score": 0},
                "identified_pain": {"status": "unknown", "evidence": "Parse error", "score": 0},
                "champion": {"status": "unknown", "evidence": "Parse error", "score": 0},
                "competition": {"status": "unknown", "evidence": "Parse error", "score": 0}
            },
            "key_context": "Error parsing cumulative state",
            "error": str(e)
        }


if __name__ == "__main__":
    # Test with sample call summaries
    test_summaries = [
        """# Discovery Call - Acme Corp
Date: 2026-07-15 | Duration: 30m

## Summary
Spoke with Sarah Chen (VP Engineering) about their feature flagging challenges. Currently using LaunchDarkly but frustrated with pricing and complexity. Team of 50 engineers. Looking to reduce experimentation risk and speed up releases. Mentioned CFO approval needed for any purchases over $50k. Timeline: need solution before Q4 planning in September.

## Keywords
feature flags, experimentation, LaunchDarkly, pricing, CFO approval

## Action Items
- Send pricing proposal by Friday
- Schedule technical deep-dive with engineering team
- Get ROI calculator to Sarah for CFO meeting""",

        """# Technical Deep Dive - Acme Corp
Date: 2026-07-20 | Duration: 45m

## Summary
Deep dive with Sarah Chen and Mark Liu (Tech Lead). Confirmed they need: visual editor for non-technical users, statsig-quality experimentation engine, sub-100ms flag evaluation, and SSO/SAML. Mark is very excited about our SDK quality compared to LaunchDarkly. Sarah mentioned John Torres (CFO) makes all final vendor decisions. Budget approved for $100k solution if ROI is clear.

## Keywords
SDK quality, visual editor, experimentation, SSO, SAML, budget approval

## Action Items
- Create POC environment for Mark's team
- Schedule CFO meeting with John Torres
- Provide security questionnaire responses"""
    ]

    print("Testing context builder...")
    print(f"Processing {len(test_summaries)} call summaries")

    result = build_cumulative_meddicc(test_summaries, "Acme Corp")

    print("\n" + "=" * 80)
    print("CUMULATIVE MEDDICC STATE")
    print("=" * 80)
    print(json.dumps(result, indent=2))
    print("=" * 80)

    # Validate structure
    assert "meddicc_state" in result
    assert "metrics" in result["meddicc_state"]
    assert "economic_buyer" in result["meddicc_state"]
    assert result["calls_reviewed"] == 2

    print("\n✓ Context builder test passed")
