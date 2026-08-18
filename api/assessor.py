"""
Response correctness assessor for CRO Slack Agent.
Checks whether synthesized answers addressed the right question
with the right data, and provides retry guidance when needed.
"""

CORRECTNESS_PROMPT = """You are checking whether an AI
assistant's answer correctly addressed a question using the
data it queried.

Question: {question}
Handler used: {handler_used}
Data queried: {tool_results_summary}
Answer given: {answer}

Assess DATA CORRECTNESS:
1. Did the answer address the actual question asked?
   (e.g. "what deals did we win?" should return won deals,
   not waterfall aggregate totals)
2. Was the right data source used?
   (e.g. waterfall ≠ individual deal records)
3. Are there obvious gaps in the data that made the answer
   incomplete or potentially misleading?
4. Did the answer acknowledge its own limitations when
   the data was insufficient?

Also assess TONE, separately from data correctness:
- Does the answer lead with the headline number/finding?
- Is risk or bad news stated plainly, not buried in a list?
- Does it close with a one-sentence judgment, not just a data restatement?

Respond with JSON only:
{{
  "correct": true/false,
  "score": 0.0-1.0,
  "issue": null or one of:
    "wrong_handler"       - wrong precomputed handler used
    "wrong_table"         - dynamic loop queried wrong table
    "missing_join"        - needed cross-table data, got one
    "wrong_time_window"   - filtered on wrong date range
    "should_be_dynamic"   - precomputed handler too limited
    "data_gap"            - data genuinely missing, handled ok
    "format_only"         - correct data, poor presentation
  "suggested_handler": null or handler name to try instead,
  "suggested_params": null or parameter adjustments,
  "learning_note": null or one-line note for routing improvement,
  "tone_score": 0.0-1.0,
  "tone_issue": null or one of: "buried_headline", "no_bottom_line",
                "risk_not_flagged", "too_verbose"
}}"""


async def assess_correctness(
    question: str,
    handler_used: str,
    tool_results: dict,
    answer: str,
    client,
    budget_used: float,
    budget_cap: float = 0.15,
) -> dict:
    """
    Run a correctness check on the synthesized answer.
    Returns assessment dict with retry guidance if needed.
    Only runs if budget remains.
    """
    import json

    # Budget guard — don't spend more than $0.01 on this check
    # if we're already near the cap
    if budget_used > budget_cap - 0.02:
        return {
            "correct": True,  # assume ok if no budget
            "score": 0.5,
            "issue": None,
            "skipped": True,
            "reason": "budget_exhausted",
        }

    # Check if answer is an honest data gap explanation
    answer_lower = answer.lower()
    HONEST_GAP_SIGNALS = [
        "no lost_reason",
        "not recorded",
        "data is missing",
        "data on our last",
        "no company name",
        "crm hygiene",
        "worth flagging",
        "no objections recorded",
        "no data",
        "not captured",
        "data simply isn't there",
        "can't determine why",
        "largely missing",
        "very sparse",
        "blank in the crm",
        "reps aren't logging",
        "no actionable",
        "unfortunately",  # most honest gap answers start this way
    ]
    if any(sig in answer_lower for sig in HONEST_GAP_SIGNALS):
        # Also verify the answer has SOME content (>100 chars)
        if len(answer.strip()) > 100:
            return {
                "correct": True,
                "score": 0.9,
                "issue": "data_gap",
                "skipped": True,
                "reason": "honest_gap_answer",
            }

    # Compact the tool results to save tokens
    summary = _compact_results(tool_results)

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system="Respond with valid JSON only. No markdown.",
            messages=[{"role": "user", "content":
                CORRECTNESS_PROMPT.format(
                    question=question,
                    handler_used=handler_used,
                    tool_results_summary=summary,
                    answer=answer[:500],
                )
            }]
        )
        from api.router import _extract_json
        result = _extract_json(resp.content[0].text)
        if not result:
            return {"correct": True, "score": 0.5,
                    "issue": None}
        return result

    except Exception as e:
        print(f"[ASSESSOR] correctness check failed: {e}",
              flush=True)
        return {"correct": True, "score": 0.5, "issue": None}


def _compact_results(tool_results: dict) -> str:
    """Summarize tool results in <200 chars for the prompt."""
    import json
    parts = []
    for key, val in tool_results.items():
        if isinstance(val, list):
            parts.append(f"{key}: {len(val)} rows")
        elif isinstance(val, dict):
            parts.append(f"{key}: {list(val.keys())[:5]}")
        elif val is not None:
            parts.append(f"{key}: {str(val)[:50]}")
    return "; ".join(parts)[:300]


def should_retry(assessment: dict,
                 iteration: int,
                 max_retries: int = 2) -> bool:
    """
    Decide whether to attempt a retry.
    Only retry on actionable issues, not data gaps.
    Never retry if we've hit the cap.
    """
    if iteration >= max_retries:
        return False
    issue = assessment.get("issue")
    # Retryable: we can try a different approach
    retryable = {
        "wrong_handler",
        "wrong_table",
        "missing_join",
        "wrong_time_window",
        "should_be_dynamic",
    }
    # Not retryable: data genuinely doesn't exist
    non_retryable = {"data_gap", "format_only", None}
    return issue in retryable


def build_retry_context(assessment: dict,
                         question: str) -> str:
    """Build the context hint for a retry attempt."""
    issue = assessment.get("issue", "")
    suggestion = assessment.get("suggested_handler", "")
    note = assessment.get("learning_note", "")

    hints = {
        "wrong_handler": (
            f"Previous approach used the wrong handler. "
            f"Try: {suggestion}. {note}"
        ),
        "wrong_table": (
            f"Previous query used the wrong table. "
            f"Try querying: {note}"
        ),
        "missing_join": (
            f"Answer needs data from multiple tables. "
            f"Join deals + analyses or deals + objections. {note}"
        ),
        "wrong_time_window": (
            f"Previous filter used wrong date range. "
            f"Check create_date vs close_date. {note}"
        ),
        "should_be_dynamic": (
            f"Precomputed handler too limited for this question. "
            f"Use dynamic query tools to combine tables. {note}"
        ),
    }
    return hints.get(issue, note or "Try a different approach.")
