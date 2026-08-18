"""Schema context builder for dynamic queries."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
_cached_context = None

def get_schema_context(sb, tables_with_descriptions=None):
    """
    Build schema context for dynamic query loop.

    Args:
        sb: Supabase client
        tables_with_descriptions: List of table names that should get full descriptions.
                                 If None, all tables get full descriptions (legacy behavior).
                                 If list, other tables get column names only.

    Returns hybrid schema:
        - ALL tables' names + column names (~1,500 tokens)
        - Full descriptions ONLY for tables in tables_with_descriptions (~2,000 tokens)
    """
    # Don't cache when using selective descriptions
    if tables_with_descriptions is not None:
        return _build_schema_context(sb, tables_with_descriptions)

    # Legacy behavior: cache full schema
    global _cached_context
    if _cached_context:
        return _cached_context
    _cached_context = _build_schema_context(sb, tables_with_descriptions=None)
    return _cached_context

def _build_schema_context(sb, tables_with_descriptions):
    """Build schema context with optional selective descriptions."""
    from supabase_client import select_all
    rows = select_all(sb, "data_dictionary",
        columns="supabase_table,supabase_column,data_type,description,enum_values,hubspot_name,source",
        filters=[("eq", "is_queryable", True)])
    if not rows:
        return _minimal_fallback_context()

    by_table = {}
    for r in rows:
        by_table.setdefault(r["supabase_table"], []).append(r)

    # Determine which tables get full descriptions
    if tables_with_descriptions is None:
        # Legacy: all tables get full descriptions
        tables_with_full_desc = set(by_table.keys())
    else:
        # Hybrid: only specified tables get full descriptions
        tables_with_full_desc = set(tables_with_descriptions)

    lines = ["QUERYABLE SUPABASE TABLES AND COLUMNS:", "(Use these exact column names in query tool calls)", ""]
    table_descriptions = {
        "deals": "Active and closed deals. One row per deal. Note: stage column contains HubSpot stage IDs (not display names). Use exact stage IDs from config when filtering.",
        "analyses": "Nightly MEDDICC scores per deal. Latest row = most recent analysis.",
        "objections": "Objections raised in sales calls, extracted by AI. One row per objection instance.",
        "feature_gaps": "Feature gaps mentioned in sales calls. One row per gap instance.",
        "win_loss_narratives": "AI-generated win/loss analysis for closed deals.",
        "waterfall_weekly": "Weekly pipeline movement: new, won, lost, net_change. Precomputed.",
        "rep_targets": "Quota targets by rep/team/period.",
        "arr_by_customer": "VIEW: total ARR per won customer."}
    join_notes = """
TABLE RELATIONSHIPS:
  deals.deal_id → analyses.deal_id (one deal → many analyses; use latest)
  deals.deal_id → objections.deal_id
  deals.deal_id → feature_gaps.deal_id
  deals.company_name ≈ objections.company_name (fuzzy — prefer deal_id)
  deals.owner_email = rep identifier (maps to rep_targets.entity_email)
"""
    for table, cols in sorted(by_table.items()):
        desc = table_descriptions.get(table, "")
        lines.append(f"TABLE: {table}")

        # Include purpose only if this table gets full descriptions
        if desc and table in tables_with_full_desc:
            lines.append(f"  Purpose: {desc}")

        for c in cols:
            col, dtype = c["supabase_column"], c["data_type"]
            enum, hs = c.get("enum_values"), c.get("hubspot_name") or ""
            hs_note = f" [HubSpot: {hs}]" if hs and hs != col else ""

            # Full description only for relevant tables
            if table in tables_with_full_desc:
                cdesc = (c.get("description") or "")[:80]
                line = f"  {col} ({dtype}){hs_note}: {cdesc}"
                if enum and dtype == "enumeration":
                    try:
                        vals = json.loads(enum) if isinstance(enum, str) else enum
                        options = ", ".join(f'"{v["value"]}"' for v in vals[:8])
                        line += f" — values: [{options}]"
                    except: pass
            else:
                # Column name and type only (no description)
                line = f"  {col} ({dtype}){hs_note}"

            lines.append(line)
        lines.append("")
    lines.append(join_notes)
    return "\n".join(lines)

def invalidate_cache():
    global _cached_context
    _cached_context = None

def _minimal_fallback_context():
    return """
QUERYABLE TABLES (data dictionary not yet populated — run discover_properties.py):
  deals: company_name, deal_value, stage, deal_status, owner_email,
         create_date, close_date, segment, forecast_category,
         sao, new_arr, expansion_arr, lost_reason, pipeline_id
         Note: stage column contains HubSpot stage IDs (not display names). Use exact stage IDs from config.
  analyses: deal_id, overall_score, champion_score, economic_buyer_score,
            decision_criteria_score, decision_process_score, pain_score,
            competition_score, component_details (JSONB), analyzed_at, status
  objections: company_name, category, verbatim_quote, rep_response,
              stage_when_raised, extracted_at
  feature_gaps: company_name, category, severity, competitor_mentioned,
                feature_description, extracted_at
  win_loss_narratives: company_name, outcome, stated_reason, narrative,
                       key_factors, generated_at
  waterfall_weekly: week_ending, pipeline_id, new_pipeline_value,
                    won_value, lost_value, net_change
  arr_by_customer: company_name, total_arr, won_deal_count

TABLE JOINS:
  deals.deal_id → analyses.deal_id, objections.deal_id, feature_gaps.deal_id
"""
