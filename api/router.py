"""
Intent router for CRO Slack Agent.
Classifies incoming questions with Haiku, dispatches to handlers,
generates answers with Sonnet, verifies numbers with Haiku.
"""

import json
import os
import logging
import anthropic
from api.db import get_supabase, log_unanswered, is_admin, get_prior_entities, get_api_history
from api import handlers

# Configure logging for Railway (stderr is better captured than stdout)
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("cro_agent")
logger.info("[STARTUP] Phase G.2 robust router with evaluation loop loaded")

FOLLOWUP_PRONOUNS = [
    "which of those", "which of them", "which of these",
    "of those", "of them", "of these",
    "those deals", "them deals", "these deals",
    "are those", "are they", "are them",
    "do those", "do they",
    "from those", "from them",
    "for those", "for them", "for these",
    "those", "these", "them", "they", "it",
    "that deal", "that one", "this deal",
    "the ones", "the same", "same deals",
    "any of those", "any of these",
]

NEW_DISCOVERY_SIGNALS = [
    # Phrasing that means "ignore known entities, find a NEW set"
    # Should NOT trigger entity-scoped bypass even if entities exist in thread
    "instead", "other deals", "different", "besides",
    "not in", "excluding", "new list", "all deals",
    "everything", "start over",
]

# Maps question keywords to bulk handler names for entity-scoped queries
# Handler descriptions - single source of truth for both INTENT_PROMPT and entity-scope classification
HANDLER_DESCRIPTIONS = {
    "query_waterfall": "pipeline movement, new/won/lost this week/quarter",
    "query_new_deals": "which deals were created, added to pipeline, or started in a time window",
    "query_won_deals": "which deals did we ALREADY win/close (past tense), retrospective wins/bookings. NOT future close dates.",
    "query_arr": "ARR by customer, total ARR",
    "query_deals_at_risk": "weak MEDDICC scores, deals at risk, champion gaps",
    "query_win_loss": "why deals were won/lost, narratives",
    "query_objections": "objections by category/stage/trend",
    "query_feature_gaps": "feature gaps by severity/competitor",
    "query_coverage": "pipeline coverage vs target, quota attainment",
    "query_deal": "deep dive on a specific company's deal",
    "query_rubric": "general scoring questions like \"what does a 6 mean for champion?\"",
    "generate_win_loss": "full narrative for a specific closed deal (slow)",
    "query_competitive_intel": "competitive intelligence: which companies mentioned DIY/build-it-themselves, named competitors showing up in calls, build-vs-buy signals, what alternatives prospects are evaluating",
    "set_target": "admin: set quota or target (requires auth)",
    "query_rubric_scores_bulk": "MEDDICC component scores for a known set of deals",
    "query_deal_stages_bulk": "current stage for a known set of deals",
    "query_deal_owners_bulk": "owner/rep for a known set of deals",
    "query_deal_values_bulk": "ARR/deal value for a known set of deals",
    "dynamic_query": "question requires combining data from multiple tables or filters not covered by the precomputed handlers above. Use when no other handler fits but the data likely exists in Supabase.",
    "unanswerable": "question cannot be answered with available data",
}

# Bulk handlers that can operate on entity scopes (deal_ids from prior context)
ENTITY_SCOPE_BULK_HANDLERS = [
    "query_deals_at_risk",
    "query_rubric_scores_bulk",
    "query_objections",
    "query_deal_stages_bulk",
    "query_deal_owners_bulk",
    "query_deal_values_bulk",
]

def has_followup_pronoun(question: str) -> bool:
    """Detect if question references prior answer entities."""
    q = question.lower()
    return any(p in q for p in FOLLOWUP_PRONOUNS)

def build_entity_hint(entities: dict) -> str:
    """Build a context hint for the intent classifier."""
    if not entities:
        return ""
    names = entities.get("company_names", [])[:10]
    ids   = entities.get("deal_ids", [])[:10]
    parts = []
    if names:
        parts.append(f"companies: {', '.join(names)}")
    if ids and not names:
        parts.append(f"deal_ids: {', '.join(str(i) for i in ids)}")
    return (f"\nThe user is asking a follow-up about "
            f"these specific entities from the prior answer: "
            f"{'; '.join(parts)}")

def should_use_entity_scope(question: str, prior_entities: dict) -> bool:
    """
    Decide whether to bypass discovery and query directly
    against known entities from the thread.

    Returns True when:
    - prior_entities has deal_ids
    - entities are not stale (< 30 minutes old)
    - question does not contain a NEW_DISCOVERY_SIGNAL
    """
    from datetime import datetime, timezone, timedelta

    if not prior_entities or not prior_entities.get("deal_ids"):
        return False

    # Check staleness: entities older than 30 minutes force rediscovery
    if prior_entities.get("resolved_at"):
        try:
            resolved_at = datetime.fromisoformat(
                prior_entities["resolved_at"].replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - resolved_at
            if age > timedelta(minutes=30):
                logger.info(f"[ENTITY_SCOPE] entities stale "
                           f"({age.total_seconds():.0f}s old), "
                           f"forcing rediscovery")
                return False
        except Exception as e:
            logger.warning(f"[ENTITY_SCOPE] failed to parse "
                          f"resolved_at: {e}")

    q_lower = question.lower()
    if any(sig in q_lower for sig in NEW_DISCOVERY_SIGNALS):
        return False
    return True

def classify_entity_scope_handler(question: str, entity_context: str, client) -> str | None:
    """
    Use Haiku to classify which bulk handler should handle this entity-scoped question.

    Args:
        question: User question
        entity_context: Description of prior entities (e.g., "3 deals from prior answer")
        client: Anthropic client

    Returns:
        Handler name from ENTITY_SCOPE_BULK_HANDLERS, or None if no match
    """
    import logging
    logger = logging.getLogger(__name__)

    # Build handler summary for entity-scope bulk handlers only
    bulk_handlers_lines = []
    for name in ENTITY_SCOPE_BULK_HANDLERS:
        desc = HANDLER_DESCRIPTIONS.get(name)
        if not desc:
            logger.warning(f"[CLASSIFIER] no description for handler {name} — omitting from classifier prompt")
            continue
        bulk_handlers_lines.append(f"  {name:25s} - {desc}")

    bulk_handlers_text = "\n".join(bulk_handlers_lines)

    prompt = f"""You have prior context about specific deals from a previous answer.
The user is asking a follow-up question about those deals.

{entity_context}

Question: {question}

Which bulk handler should answer this question?

Available handlers:
{bulk_handlers_text}

Reply with ONLY the handler name, or "none" if the question doesn't match any handler.
No explanation, no JSON."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}]
        )

        handler_name = response.content[0].text.strip()

        # Validate it's a known bulk handler
        if handler_name in ENTITY_SCOPE_BULK_HANDLERS:
            logger.info(f"[ENTITY_SCOPE] classified '{question[:50]}...' → {handler_name}")
            return handler_name
        elif handler_name.lower() == "none":
            logger.info(f"[ENTITY_SCOPE] no bulk handler matched question")
            return None
        else:
            logger.warning(f"[ENTITY_SCOPE] Haiku returned unknown handler: {handler_name}")
            return None

    except Exception as e:
        logger.error(f"[ENTITY_SCOPE] classification failed: {e}")
        return None


def log_entity_scope_pattern(question: str, handler_name: str,
                             entity_count: int, quality_score: str, sb) -> None:
    """
    Log successful entity-scope routing pattern for analysis and handler generation.

    Task G.8.4: Track which questions route successfully to build pattern library.
    """
    try:
        # Convert quality evaluation to numeric score
        quality_map = {"good": 0.9, "partial": 0.7, "empty": 0.0}
        score = quality_map.get(quality_score, 0.5)

        sb.table("entity_scope_patterns").insert({
            "question": question,
            "handler_name": handler_name,
            "entity_count": entity_count,
            "quality_score": score
        }).execute()
    except Exception as e:
        # Don't fail the request if pattern logging fails
        import logging
        logging.getLogger(__name__).warning(
            f"[ENTITY_SCOPE] Failed to log pattern: {e}")

async def route_entity_scoped_question(
        question: str, prior_entities: dict, sb, client) -> tuple[dict, str] | None:
    """
    Use LLM classification to match question to a bulk handler and execute it against
    known deal_ids without running dynamic_query_loop discovery.

    Returns (tool_results, handler_name) if a matching handler exists
    and returns non-empty results, or None if no handler matches.
    Caller runs normal synthesis (Step 6) on the tool_results.
    """
    from api.evaluator import evaluate_result
    from api import handlers
    from api.time_resolver import resolve_time_window
    import logging
    logger = logging.getLogger(__name__)

    deal_ids = prior_entities["deal_ids"]
    entity_context = f"Prior context: {len(deal_ids)} deals from previous answer"

    # All handlers (both pre-G.6 and new bulk handlers) need time_window
    # Pre-G.6 handlers require it; new bulk handlers ignore it
    default_tw = resolve_time_window({"period": "current_quarter"})

    # Classify which handler to use (LLM-based, replaces keyword matching)
    handler_name = classify_entity_scope_handler(question, entity_context, client)

    if not handler_name:
        return None

    # Execute the classified handler
    handler_fn = getattr(handlers, handler_name, None)
    if not handler_fn:
        logger.warning(f"[ENTITY_SCOPE] handler {handler_name} not found in handlers module")
        return None

    try:
        result = await handler_fn(
            {"deal_ids": deal_ids, "time_window": default_tw}, sb)
        evaluation = evaluate_result(result, handler_name)

        if evaluation != "empty":
            logger.info(f"[ENTITY_SCOPE] {handler_name} (quality={evaluation})")
            # Task G.8.4: Log successful pattern for analysis
            log_entity_scope_pattern(
                question, handler_name, len(deal_ids), evaluation, sb)
            return (result, handler_name)
        else:
            logger.info(f"[ENTITY_SCOPE] {handler_name} returned empty")
            return None

    except Exception as e:
        logger.error(f"[ENTITY_SCOPE] handler {handler_name} raised: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

def build_intent_prompt(today: str, current_quarter: str, history: str, question: str) -> str:
    """Build INTENT_PROMPT from HANDLER_DESCRIPTIONS (single source of truth)."""
    handlers_text = "\n".join([
        f"  {name:25s} - {desc}"
        for name, desc in HANDLER_DESCRIPTIONS.items()
    ])

    return f"""Classify this Slack question into one of
these handler types. Reply with JSON only.

Handlers:
{handlers_text}

Required JSON:
{{
  "handler": "<handler_name>",
  "params": {{
    "time_window": {{
      "period": "current_quarter|current_week|last_N_days|specific",
      "start": "YYYY-MM-DD or null",
      "end":   "YYYY-MM-DD or null"
    }},
    "company": "<company name or null>",
    "rep_email": "<email or null>",
    "role": "ae|am|null",
    "metric": "new_arr|expansion_arr|total_arr|null",
    "target_value": "<number or null>",
    "entity_name": "<rep/team name for set_target or null>",
    "period_label": "Q3_FY2027 or null",
    "search_term": "<specific competitor/term for query_competitive_intel or null>",
    "is_slow": false
  }},
  "unanswerable_reason": "no_data|out_of_scope|ambiguous|null",
  "confidence": 0.0-1.0
}}

For time windows, use the fiscal calendar:
  FY starts February. Q1=Feb-Apr, Q2=May-Jul,
  Q3=Aug-Oct, Q4=Nov-Jan.
  Today is {today}. Current quarter: {current_quarter}.

Conversation history (for follow-up context):
{history}

Question: {question}"""

VERIFY_PROMPT = """You generated this answer to a Slack
question. Verify that every number in the answer comes
directly from the tool results below. If any number was
invented or inferred without data support, rewrite the
sentence to either use the actual data or remove the claim.

Question: {question}
Your answer: {answer}
Tool results: {tool_results}

Reply with the verified answer only — no commentary.
If the answer is already fully supported, repeat it
unchanged."""

# ══════════════════════════════════════════════════════════════
# REPORT SHAPES — Reusable structure declarations
# ══════════════════════════════════════════════════════════════
# Handlers can optionally declare which shape(s) their data fits.
# Synthesis adapts emphasis based on shape + question framing.

REPORT_SHAPES = {
    "snapshot": {
        "order": ["headline_number", "breakdown", "flags", "bottom_line"],
        "description": ("point-in-time state — a total, a breakdown by category, "
                       "what needs attention")
    },
    "trend": {
        "order": ["headline_change", "detail_by_period", "context", "bottom_line"],
        "description": ("movement over time — what changed, by how much, "
                       "is that good or bad")
    },
    "risk_alert": {
        "order": ["count_at_risk", "named_examples", "common_pattern", "bottom_line"],
        "description": ("a filtered list of concerning items — lead with how many, "
                       "name a few, note the pattern")
    },
    "comparison": {
        "order": ["headline_comparison", "breakdown_by_entity", "outliers", "bottom_line"],
        "description": ("ranking or comparing across reps/segments/deals — "
                       "who's ahead, who's behind, why")
    },
}

SYNTHESIS_SYSTEM_PROMPT = """You answer RevOps questions
for a B2B SaaS CRO in Slack.

VOICE — You are reporting as a VP of RevOps briefing a CRO or CEO.
Write the way that role writes:

- Lead with the number that matters most. State it first, then support it.
  Never bury the headline under context.
- Flag risk explicitly. A concerning number sitting quietly inside a list
  is a failure to communicate it — call it out.
- Close with one sentence of judgment: are we on track, and why. Not a
  restatement of the data — an actual read on it.
- Be concise. A VP's Slack update is scannable in 15 seconds, not a
  report to read end to end.

Example — a snapshot-shaped answer done well:

📊 *Current Pipeline — $14.4M across 144 deals*

*By Stage:*
• Discovery — 20 deals, $2.0M
• Scoping — 30 deals, $3.5M
• Technical Evaluation — 40 deals, $5.0M
• Negotiating — 25 deals, $2.9M

⚠️ *Needs Attention:* 12 deals missing ARR (incl. Company A, Company B...);
8 deals flagged at-risk (weak champion or economic buyer signals).

Bottom line: pipeline is healthy in volume but ARR hygiene is lagging — get
the 12 unvalued deals updated before they skew the forecast.

REASONING AGAINST DATA:
When answering, reason about the question against the data
— don't just report what fields are populated.

- If the question asks about X but the data contains Y
  which is semantically related, surface it:
  "No exact mentions of X, but we found related signals:
   [specific examples with company names]"
- Never say "zero mentions" or "no data" if the data
  contains semantically adjacent signals. "Have we seen
  DIY alternatives?" should surface "in-house platform"
  and "build vs buy" mentions even if "DIY" doesn't appear
  verbatim.
- If data is genuinely absent, say so plainly and suggest
  what related data does exist.

FORMATTING (Slack-native):
- Never use markdown tables. Use bullet lists.
- Bold with *asterisks*, not **double**
- Deal format: • *Company* — $Value | Stage | Close | Score
- 5-8 lines max. Lead with the direct answer.
- End with one actionable insight when relevant.
- Never invent numbers. Use $ and K/M suffixes.

When data includes band_description and next_steps,
format coaching as:
  *[Component]: [Score]/10 — [band_description]*
  Next step: [next_steps]

When data includes deal_specific_next_steps, reference
those directly rather than generic rubric guidance."""

DYNAMIC_SYSTEM_PROMPT = """CRITICAL: Respond with ONLY a JSON object. No prose,
no explanation, no markdown. Your entire response must
be valid JSON starting with {{ and ending with }}.
Either a tool call: {{"tool": "...", "params": {{...}}}}
Or your final answer: {{"answer": "..."}}
Nothing else.

You answer RevOps questions for a B2B SaaS CRO using query tools.
You have access to tools that read Supabase tables.

{schema_context}

TOOLS YOU CAN CALL:
  filter_table(table, columns, filters, limit, order_by)
  join_tables(primary_table, primary_key, joined_table,
              foreign_key, primary_filters, joined_columns, limit)
  aggregate_results(data, group_by, aggregations)
    data: list of dicts from a previous filter_table result,
          OR the string key "step_N" to reference a prior
          tool result (e.g. "step_0" for the first result)
    group_by: column name to group by
    aggregations: dict of {{"column": "sum"|"count"|"avg"}}
    Example: aggregate_results(
      data="step_1",
      group_by="owner_email",
      aggregations={{"deal_value": "sum", "deal_id": "count"}}
    )
  compare_periods(table, column, agg, period_a, period_b,
                  date_column)

RULES:
- Only use column names that appear in the schema above
- Filters: [["operator", "column", "value"], ...]
  operators: eq neq gt gte lt lte like ilike is_ in_
- Maximum 5 tool calls per question
- If data genuinely doesn't exist, say so plainly
- Never invent numbers

DATES: Always use the exact time_window dates provided
in the question context. Never compute your own fiscal
quarters — the resolved start/end dates are always given.

QUERY EFFICIENCY:
When filtering on analysis scores (champion_score, overall_score, etc.),
always query the analyses table FIRST to get matching deal_ids, then look
up those specific deals. Never fetch all deals and then filter on analyses
— it hits the token budget.

EFFICIENCY: For questions that need data from two
tables filtered together (e.g. deals in a specific
stage WITH a specific score), use join_tables in ONE
call rather than filter_table twice then aggregate.

Example for 'deals in Technical Evaluation with low
economic buyer score':
join_tables(
  primary_table='deals',
  primary_key='deal_id',
  joined_table='analyses',
  foreign_key='deal_id',
  primary_filters=[
    ['eq', 'stage', 'presentationscheduled'],
    ['eq', 'deal_status', 'active']
  ],
  joined_columns=['economic_buyer_score',
                  'overall_score', 'component_details'],
  limit=50
)
Then filter the joined rows in memory for low scores.

RANKING QUERIES: For 'strongest/weakest/highest/lowest'
questions about scores, ALWAYS:
1. Query analyses first with score threshold filter
   (not all 1800 deals)
2. Get the top 10-20 by score using limit parameter
3. Then look up company names for just those deal_ids
Never fetch all active deals first — analyses table
has scores, use it as the primary filter.

Example for 'strongest decision process':
Step 1: filter_table(analyses, columns=[deal_id,
  decision_process_score], filters=[], limit=20,
  order_by='decision_process_score DESC')
Step 2: filter_table(deals, columns=[deal_id,
  company_name, deal_value, owner_email, stage],
  filters=[['in_', 'deal_id', <step_1_ids>]])
Step 3: synthesize

ANSWER FORMATTING (for final {{"answer": "..."}} only):
When you have enough data to answer, format for Slack:
- Use bullet points (•) not markdown tables (| col | col |)
- Bold company names with *asterisks*
- Deal format: • *Company* — $Value | Stage | Date | Score X/10
- Keep to 5-8 lines max
- Lead with direct answer, then supporting detail
- End with one actionable insight if relevant

RESPONSE FORMAT (pure JSON, nothing else):
{{"tool": "filter_table", "params": {{...}}}}
OR
{{"answer": "your answer here"}}
"""

def _extract_json(text: str) -> dict | None:
    """Extract first JSON object from text, even if wrapped in prose or markdown."""
    text = text.strip()
    # Try direct parse first (handles newlines in values)
    try:
        return json.loads(text)
    except Exception:
        pass
    # Strip markdown fences
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            try:
                return json.loads(block)
            except Exception:
                continue
    # Find outermost { } — use a proper JSON decoder
    # that handles nested quotes, not regex
    for start in range(len(text)):
        if text[start] == '{':
            for end in range(len(text), start, -1):
                if text[end-1] == '}':
                    try:
                        return json.loads(text[start:end])
                    except Exception:
                        continue
    return None

def _summarize_accumulated(data: dict) -> str:
    """Summarize accumulated tool results for budget overflow message."""
    parts = []
    for key, result in data.items():
        rows = result.get("rows", [])
        if rows:
            parts.append(f"{len(rows)} rows from {result.get('table', key)}")
    return "; ".join(parts) if parts else "no data found"

def _extract_rows_from_accumulated(accumulated_data: dict, mode: str = "entity_extraction", sb=None) -> dict:
    """
    Extract rows from accumulated_data for entity context or synthesis.

    Args:
        accumulated_data: {"step_0": {...}, "step_1": {...}}
        mode: "entity_extraction" or "synthesis"
        sb: Supabase client (required for entity_extraction mode)

    Returns dict with "rows" key for extract_entity_context().

    Modes:
    - "entity_extraction": Prefer steps with entity ID columns (from entity_registry)
    - "synthesis": Return last step with data (for aggregates/rollups)
    """
    logger.info(f"[EXTRACT] mode={mode}, accumulated_data keys={list(accumulated_data.keys())}")

    if not accumulated_data:
        logger.info(f"[EXTRACT] empty accumulated_data, returning empty dict")
        return {}

    if mode == "synthesis":
        # Synthesis mode: return last step with data (current behavior)
        step_keys = sorted(accumulated_data.keys(), reverse=True)
        for step_key in step_keys:
            step_data = accumulated_data.get(step_key, {})
            rows = step_data.get("rows", [])
            if rows:
                logger.info(f"[EXTRACT] synthesis mode: returning {len(rows)} rows from {step_key}")
                return {"rows": rows, "table": step_data.get("table", "unknown")}
        return {}

    # Entity extraction mode: prefer entity-bearing steps
    # Load entity registry to know which columns are entity IDs
    entity_id_columns = set()
    if sb:
        try:
            result = sb.table("entity_registry").select("id_column").execute()
            entity_id_columns = {row["id_column"] for row in result.data}
            logger.info(f"[EXTRACT] entity ID columns from registry: {entity_id_columns}")
        except Exception as e:
            logger.warning(f"[EXTRACT] failed to load entity_registry: {e}")

    # Scan steps in reverse order, looking for entity-bearing rows
    step_keys = sorted(accumulated_data.keys(), reverse=True)
    entity_bearing_steps = []

    for step_key in step_keys:
        step_data = accumulated_data.get(step_key, {})
        rows = step_data.get("rows", [])

        if not rows:
            continue

        # Check if rows contain any registered entity ID columns
        if rows and isinstance(rows, list) and len(rows) > 0:
            first_row = rows[0]
            if isinstance(first_row, dict):
                row_columns = set(first_row.keys())
                matching_entities = row_columns & entity_id_columns

                if matching_entities:
                    entity_bearing_steps.append((step_key, step_data, matching_entities))
                    logger.info(f"[EXTRACT] {step_key}: {len(rows)} rows with entities {matching_entities}")
                else:
                    logger.info(f"[EXTRACT] {step_key}: {len(rows)} rows, no entity columns")

    # Return most recent entity-bearing step
    if entity_bearing_steps:
        step_key, step_data, entities = entity_bearing_steps[0]  # Already sorted reverse
        rows = step_data.get("rows", [])
        logger.info(f"[EXTRACT] returning {len(rows)} rows from {step_key} (has entities: {entities})")
        return {"rows": rows, "table": step_data.get("table", "unknown")}

    # Fallback: no entity-bearing steps found, return last step with data
    for step_key in step_keys:
        step_data = accumulated_data.get(step_key, {})
        rows = step_data.get("rows", [])
        if rows:
            logger.info(f"[EXTRACT] fallback: returning {len(rows)} rows from {step_key} (no entities found)")
            return {"rows": rows, "table": step_data.get("table", "unknown")}

    logger.info(f"[EXTRACT] no rows found in any step, returning empty dict")
    return {}

async def dynamic_query_loop(question, history, params,
                              sb, client,
                              hint: str = "") -> dict:
    """
    Multi-turn tool-calling loop for novel questions.
    Agent calls tools until it has enough data to answer.
    Capped at 5 iterations and $0.08 token budget.
    """
    from api.schema_context import get_schema_context
    from api.table_classifier import classify_relevant_tables
    from api import tools as T

    # Hybrid schema: classify relevant tables for full descriptions
    relevant_tables = classify_relevant_tables(question, client)
    logger.info(f"[SCHEMA] Relevant tables for full descriptions: {relevant_tables}")

    schema = get_schema_context(sb, tables_with_descriptions=relevant_tables)
    system = DYNAMIC_SYSTEM_PROMPT.format(schema_context=schema)

    # Build question with time window and optional hint
    history_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-4:]
        if m["role"] in ("user", "assistant")
    ]

    messages = [
        *history_messages,
        {"role": "user",
         "content": f"Question: {question}\n\n"
                    f"Time context: {params['time_window']['label']} "
                    f"= {params['time_window']['start']} to "
                    f"{params['time_window']['end']}\n\n"
                    f"{f'Context: {hint}' if hint else ''}"}
    ]
    accumulated_data = {}
    executed_tools = []  # Track tool calls to detect near-duplicates
    TOKEN_BUDGET = 20000  # ~$0.20 at Sonnet pricing - complex joins need headroom
    tokens_used = 0
    MAX_ITERATIONS = 5
    EVAL_PROMPT = """Score this answer 0-1:
  1.0 = fully answers with specific data
  0.7 = partially answers, some specifics
  0.4 = answers adjacent question
  0.0 = no substantive data

Question: {question}
Answer: {answer}

Reply with JSON only: {{"score": 0.8, "missing": "..."}}"""

    for iteration in range(MAX_ITERATIONS):
        # Predictive budget check BEFORE making call
        # Estimate: current system + messages + 800 output
        estimated_input = len(system) // 4 + sum(len(str(m.get('content', ''))) // 4 for m in messages)
        estimated_call_tokens = estimated_input + 800
        projected_total = tokens_used + estimated_call_tokens

        if projected_total > TOKEN_BUDGET:
            partial = _summarize_accumulated(accumulated_data)
            logger.info(f"[LOOP] declining iteration {iteration} - would exceed budget "
                       f"(used={tokens_used}, projected={projected_total}, budget={TOKEN_BUDGET})")
            tool_results = _extract_rows_from_accumulated(accumulated_data, sb=sb)
            answer = (f"Hit query budget with partial data: {partial}. "
                     f"Try a more specific question.")
            return {"answer": answer, "tool_results": tool_results}

        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            system=system,
            messages=messages,
        )
        tokens_used += resp.usage.input_tokens + resp.usage.output_tokens

        # Post-call verification (should never trigger if prediction is accurate)
        if tokens_used > TOKEN_BUDGET:
            partial = _summarize_accumulated(accumulated_data)
            logger.info(f"[LOOP] fallback to unanswerable after "
                        f"{iteration+1} iterations, tokens={tokens_used}")
            tool_results = _extract_rows_from_accumulated(accumulated_data, sb=sb)
            answer = (f"Hit query budget with partial data: {partial}. "
                     f"Try a more specific question.")
            return {"answer": answer, "tool_results": tool_results}

        raw = resp.content[0].text.strip()

        # DEBUG: Log raw response
        logger.info(f"[LOOP iter={iteration}] raw response: {raw[:200]}")

        parsed = _extract_json(raw)

        # DEBUG: Log parsed result
        logger.info(f"[LOOP iter={iteration}] parsed={parsed is not None} "
                    f"tool={parsed.get('tool') if parsed else 'none'} "
                    f"has_answer={'answer' in (parsed or {})}")

        if not parsed:
            # Check if model gave prose answer directly
            stripped = raw.strip()
            if (stripped and
                not stripped.startswith('{') and
                not stripped.startswith('```') and
                len(stripped) > 50 and
                'tool' not in stripped[:20].lower()):
                # Treat as direct prose answer
                logger.info(f"[LOOP iter={iteration}] prose answer detected")
                # Extract rows from accumulated data for entity context
                tool_results = _extract_rows_from_accumulated(accumulated_data, sb=sb)
                return {"answer": stripped, "tool_results": tool_results}
            # Otherwise log parse failure as before
            logger.info(f"[LOOP] JSON parse failed, raw={raw[:300]}")
            continue

        if "answer" in parsed:
            # Evaluate answer quality with Haiku
            try:
                eval_resp = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=100,
                    messages=[{"role": "user", "content":
                        EVAL_PROMPT.format(question=question, answer=parsed["answer"])
                    }]
                )
                eval_result = _extract_json(eval_resp.content[0].text)
                score = eval_result.get("score", 0.5) if eval_result else 0.5
                if score < 0.7 and iteration < MAX_ITERATIONS - 1:
                    missing = eval_result.get("missing", "more specifics") if eval_result else "more specifics"
                    messages.append({"role": "user",
                        "content": f"Score: {score:.1f}/1. Missing: {missing}. Improve with more specific data."})
                    continue
            except Exception:
                pass
            # Extract rows from accumulated data for entity context
            logger.info(f"[ANSWER] extracting entity context from accumulated_data with keys: {list(accumulated_data.keys())}")
            tool_results = _extract_rows_from_accumulated(accumulated_data, sb=sb)
            logger.info(f"[ANSWER] extracted tool_results with {len(tool_results.get('rows',[]))} rows")
            return {"answer": parsed["answer"], "tool_results": tool_results}

        tool_name = parsed.get("tool", "")
        tool_params = parsed.get("params", {})

        # Check for near-duplicate tool calls
        # Near-duplicate: same (tool, table, columns, filters), ignoring limit
        is_duplicate = False
        if tool_name in ["filter_table", "join_tables"]:
            # Normalize columns (can be list or comma-separated string)
            cols = tool_params.get("columns") or []
            if isinstance(cols, str):
                cols = [c.strip() for c in cols.split(",") if c.strip()]
            cols_key = str(sorted(cols))

            # Normalize filters (can be list or None)
            filters = tool_params.get("filters") or []
            if not isinstance(filters, list):
                filters = []
            filters_key = str(sorted(filters, key=str))

            # Normalize table names (handle both filter_table and join_tables)
            if tool_name == "filter_table":
                table_key = str(tool_params.get("table", ""))
            else:  # join_tables
                # Include both primary and joined table
                primary = tool_params.get("primary_table", "")
                joined = tool_params.get("joined_table", "")
                table_key = f"{primary}+{joined}"

            tool_signature = (tool_name, table_key, cols_key, filters_key)

            for prev_sig, prev_iter in executed_tools:
                if prev_sig == tool_signature:
                    logger.info(f"[LOOP iter={iteration}] duplicate tool call detected "
                               f"(same as iteration {prev_iter}), skipping execution")
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user",
                        "content": f"You already queried this in iteration {prev_iter}. "
                                  f"Use the existing data from step_{prev_iter}."})
                    is_duplicate = True
                    break

            if not is_duplicate:
                executed_tools.append((tool_signature, iteration))

        if is_duplicate:
            continue  # Skip to next iteration

        tool_fn = {
            "filter_table": T.filter_table,
            "join_tables": T.join_tables,
            "aggregate_results": T.aggregate_results,
            "compare_periods": T.compare_periods,
        }.get(tool_name)

        if not tool_fn:
            tool_results = _extract_rows_from_accumulated(accumulated_data, sb=sb)
            answer = (f"I tried to use an unknown tool ({tool_name}). "
                     f"I can't answer this question with available data.")
            return {"answer": answer, "tool_results": tool_results}

        if tool_name == "aggregate_results":
            data = tool_params.get("data", [])
            if isinstance(data, str):
                # Agent passed a key reference like "step_0"
                data = accumulated_data.get(data, {}).get("rows", [])
            elif not isinstance(data, list):
                data = []
            tool_params["data"] = data
            result = await tool_fn(**tool_params)
        elif tool_name == "compare_periods":
            result = await tool_fn(sb, **tool_params)
        else:
            result = await tool_fn(sb, **tool_params)

        # DEBUG: Log tool execution result
        logger.info(f"[TOOL] {tool_name} rows={len(result.get('rows',[]))} "
                    f"error={result.get('error','none')}")

        accumulated_data[f"step_{iteration}"] = result
        logger.info(f"[STORE] saved step_{iteration} with {len(result.get('rows',[]))} rows, "
                    f"accumulated_data now has keys: {list(accumulated_data.keys())}")
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user",
            "content": f"Tool result: {json.dumps(result, default=str)[:3000]}"})

    logger.info(f"[LOOP] fallback to unanswerable after "
                f"{MAX_ITERATIONS} iterations, tokens={tokens_used}")
    tool_results = _extract_rows_from_accumulated(accumulated_data, sb=sb)
    answer = ("I couldn't fully answer this question within the allowed steps. "
             "The data exists but requires a more complex analysis. "
             "Try breaking it into simpler questions.")
    return {"answer": answer, "tool_results": tool_results}

async def route_question(question: str, user_id: str,
                          history: list, sb, thread_ts: str = "") -> dict:
    """
    Robust question routing with inner evaluation loop.

    Flow:
      1. Classify intent (Haiku, cheap)
      2. Auth check for write commands
      3. Try precomputed handler
      4. Evaluate result quality
      5. Dynamic fallback if needed
      6. Honest "no data" if both fail
      7. Synthesize answer (Sonnet)
      8. Verify numbers against tool results (Haiku)
    """
    from datetime import date
    from api.time_resolver import resolve_time_window, current_quarter_label
    from api.evaluator import evaluate_result, extract_missing_hint

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    today  = date.today().isoformat()
    cq     = current_quarter_label()

    # ── -1. Entity-scope check (structural bypass) ───
    # Check if thread has known entities BEFORE pronoun matching
    prior_entities = get_prior_entities(history)
    skip_normal_routing = False
    tool_results = {}
    handler_name = ""
    result_quality = "empty"
    is_slow = False
    intent_resp = None  # Only assigned in normal routing path

    if should_use_entity_scope(question, prior_entities):
        logger.info(f"[ENTITY_SCOPE] using "
                    f"{len(prior_entities['deal_ids'])} "
                    f"known deal_ids, bypassing discovery")
        entity_match = await route_entity_scoped_question(
            question, prior_entities, sb, client)
        if entity_match is not None:
            tool_results, handler_name = entity_match
            result_quality = "good"
            skip_normal_routing = True
            # Skip to synthesis with these tool_results
        else:
            # No matching bulk handler, fall through to normal routing
            logger.info("[ENTITY_SCOPE] no matching bulk handler, "
                        "falling through to normal routing")

    # ── G.7 cache fallback — only when no usable entity IDs ──
    # Prefer entity_context (live re-query) over stale cache
    if not skip_normal_routing and has_followup_pronoun(question):
        from api.db import load_result_cache
        cached = load_result_cache(sb, thread_ts) if thread_ts else None
        if cached:
            logger.info("[CACHE] answering follow-up from cached payload "
                       "(no entity IDs available)")
            tool_results = cached
            handler_name = "cached_result"
            result_quality = "good"
            skip_normal_routing = True

    # ── 0. Pronoun resolution (fallback path) ────────
    # This now serves as backup when entity-scope didn't match
    if not skip_normal_routing:
        entity_params  = {}

        if has_followup_pronoun(question):
            prior_entities = get_prior_entities(history)
            if prior_entities:
                entity_params = {
                    "deal_ids":      prior_entities.get("deal_ids", []),
                    "company_names": prior_entities.get(
                        "company_names", []),
                }
                logger.info(f"[CONTEXT] pronoun detected, "
                            f"resolved {len(entity_params['deal_ids'])} "
                            f"deal_ids from prior turn")

            # ── 1. Classify ──────────────────────────────────
        intent_resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system="Respond with valid JSON only. No markdown, "
                   "no backticks, no explanation.",
            messages=[{"role": "user", "content":
                build_intent_prompt(
                    today=today,
                    current_quarter=cq,
                    history=json.dumps(get_api_history(history)[-4:]),
                    question=question,
                ) + build_entity_hint(prior_entities)
            }]
        )
        try:
            intent = _extract_json(intent_resp.content[0].text)
        except Exception:
            _log_unanswered(sb, question, user_id, "ambiguous")
            return {"answer":
                "I couldn't understand that question. Try asking "
                "about pipeline, deals, coverage, objections, "
                "or feature gaps.",
                "handler_name": "parse_failure",
                "tool_results": {}}

        handler_name = intent.get("handler", "unanswerable")
        params = intent.get("params", {})
        params["time_window"] = resolve_time_window(
            params.get("time_window", {}))

        # Inject prior entity context for pronoun follow-ups
        if entity_params:
            params["deal_ids"]      = entity_params["deal_ids"]
            params["company_names"] = entity_params["company_names"]

        confidence = intent.get("confidence", 0.5)

        print(f"[INTENT] handler={handler_name} "
              f"confidence={confidence:.2f}", flush=True)

        # ── 2. Auth check ─────────────────────────────────
        if handler_name == "set_target":
            if not is_admin(user_id):
                return {"answer":
                    "Only admins can update targets. "
                    "Ask Jeff or Ryan.",
                    "handler_name": "set_target",
                    "tool_results": {}}

        # ── 3. Try precomputed handler ────────────────────
        tool_results = {}
        result_quality = "empty"
        is_slow = handler_name == "generate_win_loss"

        if handler_name == "unanswerable":
            result_quality = "unanswerable"

        elif handler_name != "dynamic_query":
            handler_fn = getattr(handlers, handler_name, None)
            if handler_fn:
                try:
                    tool_results = await handler_fn(params, sb)
                    result_quality = evaluate_result(
                        tool_results, handler_name)
                    print(f"[HANDLER] {handler_name} → "
                          f"{result_quality}", flush=True)
                except Exception as e:
                    import traceback
                    print(f"[HANDLER ERROR] {handler_name}: {e}",
                          flush=True)
                    print(traceback.format_exc(), flush=True)
                    result_quality = "error"

        # ── 4. Dynamic fallback ───────────────────────────
        if result_quality in ("empty", "error") \
           and confidence >= 0.5 \
           and handler_name not in ("unanswerable", "set_target"):

            print(f"[ROUTING] dynamic fallback "
                  f"(quality={result_quality})", flush=True)
            hint = extract_missing_hint(tool_results, handler_name)
            dynamic_result = await dynamic_query_loop(
                question=question,
                history=history,
                params=params,
                sb=sb,
                client=client,
                hint=hint,
            )
            dynamic_answer = dynamic_result.get("answer", "")
            dynamic_tool_results = dynamic_result.get("tool_results", {})
            if dynamic_answer and \
               "don't have data" not in dynamic_answer.lower() and \
               "couldn't" not in dynamic_answer.lower():
                return {"answer": dynamic_answer,
                        "needs_ack": is_slow,
                        "tool_results": dynamic_tool_results,
                        "handler_name": f"{handler_name}_dynamic_fallback"}

        # Handle direct dynamic_query intent
        if handler_name == "dynamic_query":
            print(f"[ROUTING] dynamic_query (direct)", flush=True)
            dynamic_result = await dynamic_query_loop(
                question=question,
                history=history,
                params=params,
                sb=sb,
                client=client,
                hint="",
            )
            return {"answer": dynamic_result.get("answer", ""),
                    "needs_ack": is_slow,
                    "tool_results": dynamic_result.get("tool_results", {}),
                    "handler_name": "dynamic_query"}

        # ── 5. Honest "no data" ───────────────────────────
        if result_quality in ("empty", "error", "unanswerable"):
            reason = intent.get("unanswerable_reason",
                                "no_data")
            _log_unanswered(sb, question, user_id, reason)
            return {"answer":
                "I don't have data to answer that yet. "
                "I've logged the question — it may be something "
                "we can add to the data layer.",
                "handler_name": handler_name,
                "tool_results": {}}

    # ── 6. Synthesize ─────────────────────────────────
    answer_resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=SYNTHESIS_SYSTEM_PROMPT,
        messages=[
            *[{"role": m["role"], "content": m["content"]}
              for m in history[-4:]
              if m.get("role") in ("user", "assistant")],
            {"role": "user",
             "content": f"Question: {question}\n\n"
                        f"Data:\n"
                        f"{json.dumps(tool_results, indent=2, default=str)[:3000]}"}
        ]
    )
    raw_answer = answer_resp.content[0].text.strip()

    # ── 7. Verify ─────────────────────────────────────
    verify_resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system="Respond with only the verified answer text. "
               "No JSON, no explanation.",
        messages=[{"role": "user", "content":
            VERIFY_PROMPT.format(
                question=question,
                answer=raw_answer,
                tool_results=json.dumps(
                    tool_results, default=str)[:2000],
            )
        }]
    )
    verified = verify_resp.content[0].text.strip()

    # ── 8. Correctness assessment + retry loop ───────────
    from api.assessor import (assess_correctness,
                               should_retry,
                               build_retry_context)

    MAX_RETRIES = 2
    retry_count = 0
    tokens_used = 0
    if intent_resp is not None:
        tokens_used += (intent_resp.usage.input_tokens +
                       intent_resp.usage.output_tokens)
    tokens_used += (answer_resp.usage.input_tokens +
                   answer_resp.usage.output_tokens +
                   verify_resp.usage.input_tokens +
                   verify_resp.usage.output_tokens)

    while retry_count <= MAX_RETRIES:
        assessment = await assess_correctness(
            question=question,
            handler_used=handler_name,
            tool_results=tool_results,
            answer=verified,
            client=client,
            budget_used=tokens_used * 0.000003,
            # approximate cost: tokens × $3/1M
        )

        tone_score = assessment.get('tone_score', 0.0)
        tone_issue = assessment.get('tone_issue')

        logger.info(f"[ASSESS] score={assessment.get('score', 0):.2f} "
              f"issue={assessment.get('issue')} "
              f"tone_score={tone_score:.2f} "
              f"tone_issue={tone_issue or 'none'} "
              f"retry={retry_count}")

        # TONE RETRY DECISION: Log only, no retry (Phase G.9 Task 4 option a)
        # Low tone_score should NOT trigger retry — that path re-runs data
        # gathering, which is the wrong tool for a phrasing problem.
        # Establish the metric first, look at it after a week of real traffic,
        # decide if re-synthesis is warranted.
        # A separate cheap re-synthesis-only retry (same data, rewrite) could
        # be added later if the data shows it's needed.

        if assessment.get("correct", True) or \
           not should_retry(assessment, retry_count):
            break

        # ── Guided retry ──────────────────────────────────
        retry_count += 1
        retry_context = build_retry_context(assessment, question)

        print(f"[RETRY {retry_count}] {retry_context[:100]}",
              flush=True)

        # Try the suggested handler first
        suggested = assessment.get("suggested_handler")
        if suggested and suggested != handler_name:
            handler_fn = getattr(handlers, suggested, None)
            if handler_fn:
                try:
                    tool_results = await handler_fn(params, sb)
                    handler_name = suggested
                except Exception as e:
                    print(f"[RETRY] handler failed: {e}",
                          flush=True)
                    tool_results = {}

        # If no suggested handler or it failed, try dynamic
        if not tool_results or not tool_results.get("rows",
            tool_results.get("deal")):
            dynamic_result = await dynamic_query_loop(
                question=question,
                history=history,
                params=params,
                sb=sb,
                client=client,
                hint=retry_context,
            )
            # dynamic_query_loop returns {"answer": str, "tool_results": dict}
            dynamic_answer = dynamic_result.get("answer", "")
            dynamic_tool_results = dynamic_result.get("tool_results", {})
            if dynamic_answer and \
               "don't have data" not in dynamic_answer.lower() and \
               "couldn't" not in dynamic_answer.lower():
                # Log the learning note before returning
                _log_learning(sb, question, handler_name,
                             assessment, retry_count)
                return {"answer": dynamic_answer,
                        "needs_ack": is_slow,
                        "tool_results": dynamic_tool_results,
                        "handler_name": f"{handler_name}_retry_dynamic"}
            break

        # Re-synthesize with the new tool results
        answer_resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system=SYNTHESIS_SYSTEM_PROMPT,
            messages=[
                *[{"role": m["role"], "content": m["content"]}
                  for m in history[-4:]
                  if m.get("role") in ("user", "assistant")],
                {"role": "user",
                 "content": f"Question: {question}\n\n"
                            f"Context: {retry_context}\n\n"
                            f"Data:\n{json.dumps(tool_results, indent=2, default=str)[:3000]}"}
            ]
        )
        verified = answer_resp.content[0].text.strip()

    # ── 9. Log learning note (win or lose) ────────────────
    _log_learning(sb, question, handler_name,
                 assessment, retry_count)

    return {"answer": verified, "needs_ack": is_slow,
            "tool_results": tool_results,
            "handler_name": handler_name}


# Helper to keep route_question() clean
def _log_unanswered(sb, question, user_id, reason):
    try:
        log_unanswered(sb, question, user_id, "", "", reason)
    except Exception:
        pass


def _log_learning(sb, question, handler, assessment,
                  retries_used):
    """Log the assessment for the weekly learning report."""
    try:
        note = assessment.get("learning_note")
        issue = assessment.get("issue")
        suggested_fix = assessment.get("suggested_handler")
        retry_succeeded = assessment.get("correct", False)

        if not note and not issue:
            return

        sb.table("learning_log").insert({
            "question":  question,
            "handler_used": handler,
            "issue_type": issue,
            "suggested_fix": suggested_fix or note,
            "retry_succeeded": retry_succeeded,
            "retries_used": retries_used,
        }).execute()
    except Exception as e:
        print(f"[LEARNING] log failed: {e}", flush=True)
