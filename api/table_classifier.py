"""Classify which tables are relevant to a question using Haiku."""

import json
import logging
from typing import List

logger = logging.getLogger(__name__)

CLASSIFICATION_PROMPT = """Which Supabase tables are needed to answer this question?

Question: {question}

Available tables:
- deals: Sales opportunities/pipeline (stage, owner, value, close_date, etc.)
- analyses: MEDDICC scores per deal (champion_score, overall_score, etc.)
- calls: Sales call transcripts from Apollo/Fireflies/Gong
- objections: Customer objections extracted from calls
- feature_gaps: Missing features mentioned in calls
- competitive_signals: Competitor mentions and win/loss patterns
- pipeline_signals: Leading indicators of pipeline health
- deal_risks: Risk flags and warnings for deals
- waterfall_weekly: Weekly pipeline movement (new/won/lost)
- forecast_weekly: Weekly forecast category snapshots
- pipeline_generation_weekly: New pipeline created each week
- rep_performance: Sales rep metrics and quota attainment
- rep_targets: Quota targets by rep/period
- win_loss_narratives: Why deals closed won/lost
- deals_snapshot: Weekly deal state snapshots (LARGE - filter by snapshot_date)

Return ONLY a JSON array of table names needed, in order of importance.
Example: ["deals", "analyses"] or ["waterfall_weekly"] or ["deals", "calls", "objections"]

Include tables for:
1. Direct data (e.g., "deals" for deal questions)
2. Joins (e.g., "analyses" if filtering deals by scores)
3. Context (e.g., "calls" if question mentions call content)

Exclude tables clearly not needed. Max 5 tables.

JSON array only:"""

def classify_relevant_tables(question: str, client) -> List[str]:
    """
    Use Haiku to classify which tables are relevant to a question.

    Returns list of table names, or all tables if classification fails.
    """
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            temperature=0,
            messages=[{"role": "user", "content":
                CLASSIFICATION_PROMPT.format(question=question)}]
        )

        text = resp.content[0].text.strip()

        # Remove markdown fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        tables = json.loads(text)

        if not isinstance(tables, list):
            logger.warning(f"[TABLE_CLASSIFIER] Expected list, got {type(tables)}")
            return _all_tables()

        # Validate table names
        valid_tables = [t for t in tables if t in _all_tables()]

        if not valid_tables:
            logger.warning(f"[TABLE_CLASSIFIER] No valid tables in {tables}")
            return _all_tables()

        logger.info(f"[TABLE_CLASSIFIER] Classified relevant tables: {valid_tables}")
        return valid_tables[:5]  # Max 5

    except Exception as e:
        logger.warning(f"[TABLE_CLASSIFIER] Classification failed: {e}, using all tables")
        return _all_tables()

def _all_tables() -> List[str]:
    """Return all queryable tables as fallback."""
    return [
        "deals", "calls", "analyses", "objections", "feature_gaps",
        "waterfall_weekly", "forecast_weekly", "pipeline_generation_weekly",
        "win_loss_narratives", "competitive_signals", "pipeline_signals",
        "deal_risks", "rep_performance", "rep_targets", "deals_snapshot"
    ]
