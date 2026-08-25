"""
Handler functions for CRO Slack Agent.
Each handler reads ONLY precomputed Supabase tables and returns
structured data (not prose). The router generates prose answers
from this data using Sonnet.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

# Add scripts to path for supabase_client
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from supabase_client import select_all


def _resolve_tw(params: dict) -> dict:
    """
    Resolve time_window from params, defaulting to current quarter.

    A missing time_window causes KeyError → drops to dynamic loop →
    burns 20k query budget → returns "partial data". This was the
    most common user-visible failure in GrowthBook (three incidents).

    Fix: Always return a valid time window, defaulting to current quarter.
    """
    from api.time_resolver import resolve_time_window

    tw = params.get("time_window")
    if tw:
        # Have time_window, resolve it
        return resolve_time_window(tw)
    else:
        # No time_window, default to current quarter
        return resolve_time_window({"period": "current_quarter"})


async def query_waterfall(params: dict, sb) -> dict:
    """
    Pipeline snapshot + movement in ONE handler with question-aware emphasis.

    Returns both:
    - pipeline_summary: current state (total, by-stage, needs-attention)
    - waterfall: weekly movement (new/won/lost)

    Synthesis adapts based on question framing:
    - "show me pipeline" → lead with snapshot
    - "how did pipeline change" → lead with movement

    G.7: Includes cache_payload with deal-level rows for follow-ups.
    """
    import yaml
    from pathlib import Path

    tw = _resolve_tw(params)
    question = params.get("question", "").lower()

    # Load stage config from client.yaml
    config_path = Path(__file__).parent.parent / "config" / "client.yaml"
    config = yaml.safe_load(open(config_path))

    # Build stage lookup: {stage_id: {name, order, exclude_from_analysis}}
    stage_lookup = {}
    excluded_stage_ids = set()

    for pipeline in config["pipeline"]["pipelines"]:
        if pipeline.get("analyze") is False:
            continue  # Skip renewal pipelines
        for stage in pipeline["stages"]:
            stage_id = stage["id"]
            stage_lookup[stage_id] = {
                "name": stage["name"],
                "order": stage["order"],
                "exclude_from_analysis": stage.get("exclude_from_analysis", False)
            }
            if stage.get("exclude_from_analysis"):
                excluded_stage_ids.add(stage_id)

    # === PIPELINE SUMMARY: Current state ===
    # Query active deals
    active_deals = select_all(sb, "deals",
        columns="deal_id,company_name,arr_usd,stage,deal_status",
        filters=[("eq", "deal_status", "active")])

    # Filter out excluded stages
    included_deals = [d for d in active_deals
                      if d.get("stage") not in excluded_stage_ids]

    # Total open pipeline
    total_open_arr = sum(d.get("arr_usd") or 0 for d in included_deals)
    total_open_count = len(included_deals)

    # By-stage breakdown
    from collections import defaultdict
    stage_stats = defaultdict(lambda: {"count": 0, "arr": 0})

    for d in included_deals:
        stage_id = d.get("stage")
        if stage_id in stage_lookup:
            stage_stats[stage_id]["count"] += 1
            stage_stats[stage_id]["arr"] += d.get("arr_usd") or 0

    # Sort by stage order
    by_stage = []
    for stage_id in sorted(stage_stats.keys(),
                          key=lambda sid: stage_lookup.get(sid, {}).get("order", 999)):
        stage_info = stage_lookup.get(stage_id, {})
        stats = stage_stats[stage_id]
        by_stage.append({
            "stage_name": stage_info.get("name", stage_id),
            "count": stats["count"],
            "arr": stats["arr"]
        })

    # Needs attention: deals with no ARR
    no_arr_deals = [d for d in included_deals if not d.get("arr_usd")]
    no_arr_count = len(no_arr_deals)
    no_arr_list = [d["company_name"] for d in no_arr_deals[:5]]

    # Needs attention: at-risk deals (reuse query_deals_at_risk threshold)
    # Threshold: overall_score < 40 or champion_score < 4
    analyses = select_all(sb, "analyses",
        columns="deal_id,company_name,overall_score,"
                "champion_score,analyzed_at",
        filters=[])

    # Deduplicate: keep most recent analysis per deal_id
    latest_analyses = {}
    for a in analyses:
        deal_id = a["deal_id"]
        analyzed_at = a.get("analyzed_at", "")
        if deal_id not in latest_analyses or analyzed_at > latest_analyses[deal_id].get("analyzed_at", ""):
            latest_analyses[deal_id] = a

    # Build active deal_id set for filtering
    active_deal_ids = {d["deal_id"] for d in included_deals}

    at_risk_deals = []
    for a in latest_analyses.values():
        if a["deal_id"] not in active_deal_ids:
            continue  # Only active deals
        score = a.get("overall_score", 0) or 0
        champ = a.get("champion_score", 0) or 0
        if score < 40 or champ < 4:
            risk_reason = []
            if score < 40:
                risk_reason.append(f"low MEDDICC ({score})")
            if champ < 4:
                risk_reason.append(f"champion gap ({champ})")
            at_risk_deals.append({
                "company": a["company_name"],
                "risk": " + ".join(risk_reason)
            })

    at_risk_count = len(at_risk_deals)
    at_risk_list = at_risk_deals[:5]

    pipeline_summary = {
        "total_open_arr": total_open_arr,
        "total_open_count": total_open_count,
        "by_stage": by_stage,
        "needs_attention": {
            "no_arr_count": no_arr_count,
            "no_arr_deals": no_arr_list,
            "at_risk_count": at_risk_count,
            "at_risk_deals": at_risk_list
        }
    }

    # === WATERFALL: Weekly movement (unchanged) ===
    weekly = select_all(sb, "waterfall_weekly",
        columns="week_ending,pipeline_id,new_pipeline_value,"
                "won_value,lost_value,net_change,"
                "pulled_in_value,pushed_out_value,"
                "deals_qualified_count",
        filters=[("gte", "week_ending", tw["start"]),
                 ("lte", "week_ending", tw["end"])])

    # Deal-level rows for follow-ups (cache_payload)
    deals = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,arr_usd,"
                "stage,close_date,owner_email,segment,deal_status",
        filters=[("gte", "close_date", tw["start"]),
                 ("lte", "close_date", tw["end"])])

    # === REPORT SHAPE: Question-aware emphasis ===
    # Detect question framing to select appropriate report shape
    # Use more specific patterns to avoid overlap
    movement_keywords = ["change", "moved", "movement", "trend",
                        "how did", "what happened", "new pipeline",
                        "won this", "lost this"]
    snapshot_keywords = ["current", "open", "show me", "what's in",
                        "what deals", "snapshot", "how much"]

    is_movement_question = any(kw in question for kw in movement_keywords)
    is_snapshot_question = any(kw in question for kw in snapshot_keywords)

    # Prioritize movement (trend shape) if both match
    if is_movement_question:
        report_shape = "trend"
    elif is_snapshot_question:
        report_shape = "snapshot"
    else:
        report_shape = "snapshot"  # Default to snapshot

    return {
        "pipeline_summary": pipeline_summary,  # Current state
        "waterfall": weekly,                   # Movement
        "period": tw["label"],
        "report_shape": report_shape,          # Declared shape for synthesis
        "cache_payload": {                     # Retained, NOT shown
            "deals": deals
        }
    }


async def query_arr(params: dict, sb) -> dict:
    """
    ARR by customer from the arr_by_customer view.
    Returns top N customers by ARR.
    """
    rows = select_all(sb, "arr_by_customer",
        columns="company_name,total_arr,"
                "won_deal_count,most_recent_close")
    limit = params.get("limit", 20)
    return {"arr_by_customer": rows[:limit]}


async def query_deals_at_risk(params: dict, sb) -> dict:
    """
    Deals with weak MEDDICC scores or champion gaps.

    PHASE G.10: Stage-aware risk determination.
    A deal is "at risk" if ANY component required at its CURRENT STAGE
    is below the threshold to advance. Components not yet required are
    excluded from risk determination.

    Uses stage_progression requirements from config/client.yaml.
    """
    from api.stage_requirements import get_requirements_for_stage

    tw = _resolve_tw(params)
    deal_ids = params.get("deal_ids", [])

    # Filter analyses to specific deals if context provided
    analyses_filters = [("gte", "analyzed_at", tw["start"])]
    if deal_ids:
        analyses_filters.append(
            ("in_", "deal_id", deal_ids))

    # Fetch ALL component scores (not just champion/eb)
    analyses = select_all(sb, "analyses",
        columns="deal_id,company_name,overall_score,"
                "champion_score,economic_buyer_score,"
                "metrics_score,decision_criteria_score,"
                "decision_process_score,pain_score,"
                "competition_score,analyzed_at",
        filters=analyses_filters)

    # Deduplicate: keep only the most recent analysis per deal_id
    # (analyses table has historical snapshots from nightly runs)
    latest_analyses = {}
    for a in analyses:
        deal_id = a["deal_id"]
        analyzed_at = a.get("analyzed_at", "")
        if deal_id not in latest_analyses or analyzed_at > latest_analyses[deal_id].get("analyzed_at", ""):
            latest_analyses[deal_id] = a

    analyses = list(latest_analyses.values())

    # Fetch deal stage data for stage-aware requirements
    if deal_ids:
        # Entity-filtered: only fetch stages for these deals
        deals = select_all(sb, "deals",
            columns="deal_id,company_name,deal_value,"
                    "deal_status,stage",
            filters=[("in_", "deal_id", deal_ids)])
    else:
        # Full query: only active deals
        deals = select_all(sb, "deals",
            columns="deal_id,company_name,deal_value,"
                    "deal_status,stage",
            filters=[("eq", "deal_status", "active")])

    deal_map = {d["deal_id"]: d for d in deals}
    at_risk = []

    # Component name mapping
    component_fields = {  # drift-guard: ok (field name mapping, not component enumeration)
        "pain": "pain_score",
        "champion": "champion_score",
        "metrics": "metrics_score",
        "economic_buyer": "economic_buyer_score",
        "decision_criteria": "decision_criteria_score",
        "decision_process": "decision_process_score",
        "competition": "competition_score",
    }

    for a in analyses:
        d = deal_map.get(a["deal_id"])
        if not d:
            continue

        stage_id = d.get("stage")
        if not stage_id:
            continue

        # Get requirements for this deal's current stage
        requirements = get_requirements_for_stage(stage_id)

        # No requirements = terminal/excluded stage, never at-risk
        if not requirements:
            continue

        # Check each required component
        risk_flags = []
        for component, required_threshold in requirements.items():
            field_name = component_fields.get(component)
            if not field_name:
                continue

            actual_score = a.get(field_name, 0) or 0

            if actual_score < required_threshold:
                # Stage-aware risk message
                from api.stage_requirements import _get_stage_by_id
                stage_info = _get_stage_by_id(stage_id)
                stage_name = stage_info["name"] if stage_info else "current stage"

                risk_flags.append(
                    f"{component.replace('_', ' ').title()} {actual_score}/10 "
                    f"(need {required_threshold}+ to advance from {stage_name})"
                )

        # Only flag if there are actual risk flags
        if risk_flags:
            at_risk.append({
                "deal_id":       a["deal_id"],
                "company_name":  a["company_name"],
                "overall_score": a.get("overall_score", 0) or 0,
                "champion_score": a.get("champion_score", 0) or 0,
                "deal_value":    d.get("deal_value"),
                "stage":         stage_id,
                "risk_flags":    risk_flags
            })

    at_risk.sort(key=lambda x: (x["overall_score"],
                                 -(x["deal_value"] or 0)))

    if not at_risk:
        return {
            "deals_at_risk": [],
            "total_at_risk": 0,
            "message": ("No deals currently flagged as at-risk. "
                       "Note: Recently created deals may not have "
                       "MEDDICC analysis yet — those run nightly.")
        }

    return {"deals_at_risk": at_risk[:10],
            "total_at_risk": len(at_risk)}


async def query_win_loss(params: dict, sb) -> dict:
    """
    Comprehensive win/loss analysis combining:
    - win_loss_narratives (weekly AI narratives)
    - Recent closed-lost/won deals with lost_reason
    - MEDDICC scores at time of close

    Answers: 'why did we lose?', 'what did we win?',
    'win/loss summary', 'why are we losing?'
    """
    tw = _resolve_tw(params)
    deal_ids = params.get("deal_ids", [])

    # 1. Check for AI-generated narratives first
    narratives = select_all(sb, "win_loss_narratives",
        columns="company_name,outcome,stated_reason,"
                "competitor_mentioned,key_factors,"
                "narrative,generated_at",
        filters=[("gte", "generated_at", tw["start"])])

    # 2. Get recent closed deals regardless
    # Base filters for closed deals
    deal_filters = [
        ("in_", "deal_status", ["won", "lost"]),
        ("gte", "close_date", tw["start"]),
        ("lte", "close_date", tw["end"]),
    ]
    if deal_ids:
        deal_filters.append(("in_", "deal_id", deal_ids))

    closed_deals = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,"
                "deal_status,close_date,lost_reason,"
                "owner_email,segment",
        filters=deal_filters)
    closed_deals.sort(
        key=lambda x: x.get("close_date") or "",
        reverse=True)

    # 3. Get MEDDICC scores for closed deals
    deal_ids = [d["deal_id"] for d in closed_deals[:20]]
    analyses = []
    if deal_ids:
        analyses = select_all(sb, "analyses",
            columns="deal_id,overall_score,champion_score,"
                    "economic_buyer_score,competition_score,"
                    "pain_score,analyzed_at",
            filters=[("in_", "deal_id", deal_ids)])
        # Get latest analysis per deal
        latest = {}
        for a in sorted(analyses,
                        key=lambda x: x.get("analyzed_at",""),
                        reverse=True):
            if a["deal_id"] not in latest:
                latest[a["deal_id"]] = a
        analyses = list(latest.values())

    wins  = [d for d in closed_deals
             if d.get("deal_status") == "won"]
    losses = [d for d in closed_deals
              if d.get("deal_status") == "lost"]

    return {
        "narratives":    narratives,
        "wins":          wins,
        "losses":        losses,
        "win_count":     len(wins),
        "loss_count":    len(losses),
        "analyses":      analyses,
        "period":        tw["label"],
        "has_narratives": len(narratives) > 0,
        "data_quality_note": (
            "Lost reasons are blank for most deals — "
            "recommend making lost_reason a required field "
            "in HubSpot when marking deals Closed Lost."
        ) if losses and not any(
            d.get("lost_reason") for d in losses
        ) else None,
    }


async def query_objections(params: dict, sb) -> dict:
    """
    Top objections by category for the period from objections table.
    Returns counts by category, total, and unaddressed percentage.
    """
    tw = _resolve_tw(params)
    rows = select_all(sb, "objections",
        columns="category,stage_when_raised,"
                "rep_response,company_name,extracted_at",
        filters=[("gte", "extracted_at", tw["start"])])

    by_cat = Counter(r["category"] for r in rows)
    unaddressed = [r for r in rows if not r["rep_response"]]

    return {
        "by_category":   dict(by_cat.most_common()),
        "total":         len(rows),
        "unaddressed":   len(unaddressed),
        "unaddressed_pct": round(
            len(unaddressed)/max(len(rows),1)*100, 1),
        "period": tw["label"],
    }


async def query_feature_gaps(params: dict, sb) -> dict:
    """
    Feature gaps by severity and competitor from feature_gaps table.
    Returns total, blockers, counts by category, and top competitors.
    """
    tw = _resolve_tw(params)
    rows = select_all(sb, "feature_gaps",
        columns="category,severity,competitor_mentioned,"
                "feature_description,company_name,extracted_at",
        filters=[("gte", "extracted_at", tw["start"])])

    blockers = [r for r in rows if r["severity"]=="blocker"]
    by_cat   = Counter(r["category"] for r in rows)
    competitors = Counter(
        r["competitor_mentioned"] for r in rows
        if r["competitor_mentioned"])

    return {
        "total": len(rows),
        "blockers": len(blockers),
        "by_category": dict(by_cat.most_common()),
        "competitors_mentioned": dict(competitors.most_common(5)),
        "period": tw["label"],
    }


async def query_coverage(params: dict, sb) -> dict:
    """
    Pipeline coverage vs quota targets from rep_targets and deals tables.
    Returns coverage % for each target (company/team/rep level).
    """
    tw = _resolve_tw(params)
    period_label = tw.get("label", "").replace(" ", "_")

    targets = select_all(sb, "rep_targets",
        columns="level,entity_name,role,metric,target_value",
        filters=[("eq", "period", period_label)])

    deals = select_all(sb, "deals",
        columns="deal_value,deal_status,stage,owner_email,"
                "pipeline_id,highest_stage_order_reached",
        filters=[("eq", "deal_status", "active")])

    # Only qualified deals (above threshold)
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from utils import get_pipeline_config

    pipeline = get_pipeline_config()
    qual_threshold = pipeline.get("qualified_stage_order", 2)
    qualified = [d for d in deals
                 if (d.get("highest_stage_order_reached") or 0)
                    >= qual_threshold]

    total_pipeline = sum(
        d.get("deal_value") or 0 for d in qualified)

    coverage_rows = []
    for t in targets:
        tv = t["target_value"] or 0
        coverage_rows.append({
            "entity":   t["entity_name"],
            "level":    t["level"],
            "role":     t["role"],
            "metric":   t["metric"],
            "target":   tv,
            "pipeline": total_pipeline,
            "coverage": round(total_pipeline/max(tv,1)*100, 1),
        })

    return {
        "coverage": coverage_rows,
        "total_qualified_pipeline": total_pipeline,
        "period": tw["label"],
        "note": "Coverage = qualified pipeline / target. "
                "No targets set → run 'set [team] target'.",
    }


async def query_deal(params: dict, sb) -> dict:
    """
    Deep dive on a specific company's deal.
    Returns deal info, latest MEDDICC analysis, and objections.
    """
    company = params.get("company", "")

    # If no explicit company but entity context has one,
    # use the first company from context
    company_names = params.get("company_names") or []
    if not company and company_names:
        company = company_names[0]

    if not company:
        return {"error": "Company name required"}

    deals = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,stage,"
                "deal_status,close_date,owner_email,"
                "highest_stage_order_reached,forecast_category")

    deal = next((d for d in deals
                 if company.lower() in
                    (d.get("company_name") or "").lower()), None)
    if not deal:
        return {"error": f"No deal found for '{company}'"}

    deal_id = deal["deal_id"]

    analyses = select_all(sb, "analyses",
        columns="overall_score,component_details,"
                "analyzed_at,status",
        filters=[("eq", "deal_id", deal_id)])
    analyses.sort(key=lambda x: x.get("analyzed_at",""),
                  reverse=True)
    latest = analyses[0] if analyses else {}

    objections = select_all(sb, "objections",
        columns="category,verbatim_quote,rep_response",
        filters=[("eq", "company_name", deal["company_name"])])

    # Check for deal-specific analysis file
    from pathlib import Path
    import sys
    REPO_ROOT = Path(__file__).parent.parent
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from utils import slugify

    company_slug = slugify(deal["company_name"])
    output_file = REPO_ROOT / "memory" / "analyses" / f"{company_slug}.md"

    result = {
        "deal": deal,
        "latest_analysis": latest,
        "objections": objections,
    }

    if output_file.exists():
        content = output_file.read_text()[:3000]
        result["deal_specific_next_steps"] = content
        result["next_steps_source"] = "deal_analysis"
    else:
        # Fall back to rubric bands
        from api.rubric import get_band, get_next_steps
        from api.db import unpack_jsonb
        component_details = unpack_jsonb(latest.get("component_details"), {})
        for component, data in component_details.items():
            if isinstance(data, dict):
                score = data.get("score", 0)
                data["band"] = get_band(component, score)
                data["next_steps"] = get_next_steps(component, score)
        result["next_steps_source"] = "rubric_fallback"

    return result


async def query_rubric(params: dict, sb) -> dict:
    """
    General rubric questions like 'what does a 6 mean for champion?'
    Returns band descriptions and next steps guidance.
    """
    from api.rubric import RUBRIC, get_band, get_next_steps, get_band_description

    # Extract component and score from params if specified
    # Otherwise return full rubric
    component = params.get("component")
    score = params.get("score")

    if component and score is not None:
        # Specific component + score query
        band = get_band(component, score)
        description = get_band_description(component, score)
        next_steps = get_next_steps(component, score)

        return {
            "component": component,
            "score": score,
            "band": band,
            "description": description,
            "next_steps": next_steps,
        }
    elif component:
        # Just component, return all bands
        component_key = component.lower().replace(" ", "_")
        if component_key in RUBRIC:
            return {
                "component": component,
                "bands": RUBRIC[component_key]["bands"],
                "next_steps": RUBRIC[component_key]["next_steps"],
            }
        else:
            return {"error": f"Unknown component: {component}"}
    else:
        # General rubric query - return overview
        return {
            "rubric_overview": {
                comp: {
                    "bands": data["bands"],
                    "next_steps": data["next_steps"],
                }
                for comp, data in RUBRIC.items()
            }
        }


async def generate_win_loss(params: dict, sb) -> dict:
    """
    Full narrative for a specific closed deal (slow).
    Returns narrative if exists, otherwise returns component analysis.
    """
    company = params.get("company", "")
    if not company:
        return {"error": "Company name required for win/loss narrative"}

    rows = select_all(sb, "win_loss_narratives",
        columns="*",
        filters=[("ilike", "company_name", f"%{company}%")])
    if rows:
        return {"narrative": rows[0]}

    # No narrative yet — return the component analysis instead
    deals = select_all(sb, "deals",
        columns="deal_id,company_name,deal_status,close_date")
    deal = next((d for d in deals
                 if company.lower() in
                    (d.get("company_name") or "").lower()), None)
    if not deal:
        return {"error": f"No deal found for '{company}'"}

    analyses = select_all(sb, "analyses",
        columns="component_details,overall_score,status",
        filters=[("eq", "deal_id", deal["deal_id"])])

    return {
        "deal": deal,
        "analyses": analyses[-3:],
        "note": "No narrative generated yet — "
                "runs Sunday after close.",
    }


async def set_target(params: dict, sb) -> dict:
    """
    Admin: set quota target. Auth checked in router.
    Writes to rep_targets table with upsert on conflict.
    """
    entity  = params.get("entity_name", "")
    period  = params.get("period_label", "")
    metric  = params.get("metric", "total_arr")
    value   = params.get("target_value")
    role    = params.get("role")

    if not all([entity, period, value]):
        return {"error":
            "Need: entity name, period (e.g. Q3_FY2027), "
            "and value (e.g. $500K)"}

    # Determine level from entity name
    level = "rep" if "@" in entity else "team"

    # Parse value (handle $500K, $1.2M formats)
    value_str = str(value).replace("$","").replace(",","")
    if "K" in value_str.upper():
        value_float = float(value_str.upper().replace("K","")) * 1000
    elif "M" in value_str.upper():
        value_float = float(value_str.upper().replace("M","")) * 1000000
    else:
        value_float = float(value_str)

    sb.table("rep_targets").upsert({
        "period":       period,
        "level":        level,
        "entity_name":  entity,
        "role":         role,
        "metric":       metric,
        "target_value": value_float,
    }, on_conflict="period,level,entity_name,metric").execute()

    return {"set": True, "entity": entity,
            "period": period, "value": value_float}


async def query_new_deals(params: dict, sb) -> dict:
    """
    Deals created within the time window, from the
    deals table directly. Answers 'which deals were
    created this week/quarter/period?'
    """
    tw = _resolve_tw(params)
    rows = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,stage,"
                "owner_email,create_date,forecast_category,"
                "highest_stage_order_reached,pipeline_id",
        filters=[
            ("gte", "create_date", tw["start"]),
            ("lte", "create_date", tw["end"]),
        ])
    # Sort by value descending
    rows.sort(key=lambda x: x.get("deal_value") or 0,
              reverse=True)
    return {
        "new_deals": rows,
        "count": len(rows),
        "total_value": sum(
            r.get("deal_value") or 0 for r in rows),
        "period": tw["label"],
    }


# Vocabulary for build-vs-buy / DIY competition detection.
# Covers how prospects describe in-house alternatives.
COMPETITION_VOCAB = {
    "build_vs_buy": [
        "build", "built", "building", "in-house", "inhouse",
        "homegrown", "home-grown", "internal", "internally",
        "ourselves", "own platform", "own tool", "own solution",
        "DIY", "do it ourselves", "do it yourself",
        "vibe cod", "custom", "proprietary",
    ],
    "competitors": [
        "Statsig", "LaunchDarkly", "Optimizely", "Amplitude",
        "VWO", "Adobe Target", "Split.io", "Eppo",
        "Dr. Jekyll", "WISE", "Flagsmith", "Unleash",
    ],
    "evaluation": [
        "evaluating", "comparing", "looking at", "considering",
        "alternative", "instead of", "rather than",
        "competitive", "competitor",
    ],
    "deployment_preference": [
        "self-host", "self-hosted", "on-prem",
        "on-premise", "on premise", "our infrastructure",
        "our cloud", "data sovereignty",
    ],
}


async def query_competitive_intel(params: dict, sb) -> dict:
    """
    Search for competitive signals across all enrichment sources:
    objections, feature_gaps, win_loss_narratives, and MEDDICC
    competition scores in analyses.

    Handles questions like:
    - "have we come across DIY/build-it-yourself alternatives?"
    - "which companies mentioned building their own platform?"
    - "what competitors keep coming up?"
    - "where is Statsig showing up?"
    """
    tw = _resolve_tw(params)
    search_term = params.get("search_term", "")

    # Build search vocabulary: a specific term (e.g. "Statsig", "DIY")
    # or the full build-vs-buy/competitor vocabulary
    vocab = [search_term] if search_term else (
        COMPETITION_VOCAB["build_vs_buy"] +
        COMPETITION_VOCAB["competitors"])

    # Internal calls (e.g. your own company's demo/testing calls) get
    # ingested by the same enrichment pipeline — exclude them so
    # they don't read as external competitive signal.
    # TODO: Configure your company name in config/client.yaml
    INTERNAL_COMPANIES = set()  # e.g. {"your_company", "yourco"}

    # 1. Competitor mentions in feature_gaps (most structured data)
    comp_gaps = [r for r in select_all(sb, "feature_gaps",
        columns="company_name,competitor_mentioned,"
                "feature_description,severity,category")
        if r.get("competitor_mentioned")]
    comp_gaps = [r for r in comp_gaps
                 if (r.get("company_name") or "").lower()
                 not in INTERNAL_COMPANIES]

    # 2. Objections whose verbatim quote matches the vocabulary
    all_objections = select_all(sb, "objections",
        columns="company_name,category,verbatim_quote,"
                "rep_response,stage_when_raised")
    all_objections = [r for r in all_objections
                      if (r.get("company_name") or "").lower()
                      not in INTERNAL_COMPANIES]
    matching_objections = []
    for obj in all_objections:
        quote = (obj.get("verbatim_quote") or "").lower()
        if any(term.lower() in quote for term in vocab):
            matching_objections.append(obj)

    # 3. Win/loss narratives that mention the vocabulary
    narratives = select_all(sb, "win_loss_narratives",
        columns="company_name,outcome,stated_reason,"
                "competitor_mentioned,narrative")
    matching_narratives = []
    for n in narratives:
        text = " ".join(filter(None, [
            n.get("stated_reason", ""),
            n.get("narrative", ""),
            n.get("competitor_mentioned", ""),
        ])).lower()
        if any(term.lower() in text for term in vocab):
            matching_narratives.append(n)
    matching_narratives = [r for r in matching_narratives
                           if (r.get("company_name") or "").lower()
                           not in INTERNAL_COMPANIES]

    # Self-hosting / on-prem mentions may be a deployment
    # option discussion, not a build-vs-buy competitive signal — surface
    # them separately so they don't get counted as competitive objections.
    self_host_signals = [
        obj for obj in all_objections
        if any(t.lower() in
               (obj.get("verbatim_quote") or "").lower()
               for t in
               COMPETITION_VOCAB["deployment_preference"])
    ]

    # 4. Deals with a low MEDDICC competition score, for context
    low_comp_deals = select_all(sb, "analyses",
        columns="deal_id,company_name,competition_score,"
                "component_details,analyzed_at",
        filters=[("lte", "competition_score", 4)])
    low_comp_deals.sort(
        key=lambda x: x.get("analyzed_at", ""), reverse=True)

    competitor_counts = Counter(
        r["competitor_mentioned"] for r in comp_gaps
        if r.get("competitor_mentioned"))

    return {
        "competitor_mentions_in_gaps": comp_gaps[:20],
        "competitor_counts": dict(competitor_counts.most_common(10)),
        "build_vs_buy_objections": matching_objections,
        "narrative_mentions": matching_narratives,
        "low_competition_score_deals": low_comp_deals[:10],
        "search_vocab_used": vocab[:5],
        "self_host_signals": self_host_signals,
        "self_host_note": (
            "Self-hosting mentions may be deployment preference "
            "discussions, not build-vs-buy objections."
        ) if self_host_signals else None,
        "period": tw["label"],
    }


async def query_won_deals(params: dict, sb) -> dict:
    """
    Deals that closed as won in the time window.
    Answers: 'what did we win?', 'show me our wins',
             'which deals closed won this quarter?'
    """
    tw = _resolve_tw(params)
    rows = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,stage,"
                "owner_email,close_date,forecast_category,"
                "new_arr,expansion_arr",
        filters=[
            ("eq",  "deal_status", "won"),
            ("gte", "close_date",  tw["start"]),
            ("lte", "close_date",  tw["end"]),
        ])
    rows.sort(
        key=lambda x: x.get("deal_value") or 0,
        reverse=True)
    return {
        "rows": rows,
        "count": len(rows),
        "total_value": sum(
            r.get("deal_value") or 0 for r in rows),
        "period": tw["label"],
    }

async def query_rubric_scores_bulk(params: dict, sb) -> dict:
    """MEDDICC scores for a known set of deal_ids.
    Used by entity-scoped follow-up questions like
    'what are the meddicc scores for these deals?'"""
    deal_ids = params.get("deal_ids", [])
    if not deal_ids:
        return {
            "scores": [],
            "error": "No deal IDs provided. This handler requires a list of specific deals."
        }

    rows = select_all(sb, "analyses",
        columns="deal_id,company_name,overall_score,"
                "champion_score,economic_buyer_score,"
                "decision_criteria_score,"
                "decision_process_score,competition_score,"
                "pain_score,analyzed_at",
        filters=[("in", "deal_id", deal_ids)])
    return {"scores": rows, "deal_count": len(deal_ids),
            "scored_count": len(rows)}

async def query_deal_stages_bulk(params: dict, sb) -> dict:
    """Current stage for a known set of deal_ids."""
    # Fix A2: Handle both entity-scope path (has deal_ids) and
    # direct intent path (may not have deal_ids)
    deal_ids = params.get("deal_ids", [])
    if not deal_ids:
        return {
            "stages": [],
            "error": "No deal IDs provided. This handler requires a list of specific deals."
        }

    rows = select_all(sb, "deals",
        columns="deal_id,company_name,stage,"
                "highest_stage_order_reached,close_date",
        filters=[("in_", "deal_id", deal_ids)])
    return {"stages": rows}

async def query_deal_owners_bulk(params: dict, sb) -> dict:
    """Owner for a known set of deal_ids."""
    deal_ids = params.get("deal_ids", [])
    if not deal_ids:
        return {
            "owners": [],
            "error": "No deal IDs provided. This handler requires a list of specific deals."
        }

    rows = select_all(sb, "deals",
        columns="deal_id,company_name,owner_email",
        filters=[("in", "deal_id", deal_ids)])
    return {"owners": rows}

async def query_deal_values_bulk(params: dict, sb) -> dict:
    """ARR/value for a known set of deal_ids."""
    deal_ids = params.get("deal_ids", [])
    if not deal_ids:
        return {
            "values": [],
            "total_arr": 0,
            "error": "No deal IDs provided. This handler requires a list of specific deals."
        }

    rows = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,"
                "arr_usd,new_arr,expansion_arr",
        filters=[("in", "deal_id", deal_ids)])
    total = sum(r.get("arr_usd") or 0 for r in rows)
    return {"values": rows, "total_arr": total}


async def query_deal_health(params: dict, sb) -> dict:
    """
    Deal health assessment combining MEDDICC scores with activity signals.

    Returns deals with health scores, flagging those below thresholds.
    Originally had char-iteration bug: built deal_id filter from threshold
    scan and passed string to .in_(), producing in.(6,0,1,4,...).

    Fix: Always pass deal_ids as list to .in_() filter.
    """
    from api.stage_requirements import get_components

    tw = params.get("time_window", {})
    deal_ids = params.get("deal_ids", [])
    health_threshold = params.get("threshold", 40)

    # Get all analyses, optionally filtered by deal_ids
    analyses_filters = []
    if tw and tw.get("start"):
        analyses_filters.append(("gte", "analyzed_at", tw["start"]))
    if deal_ids:
        # Production fix: Ensure deal_ids is a list, not string
        # _coerce_in_values in supabase_client handles this, but
        # verify caller passes list for clarity
        if not isinstance(deal_ids, list):
            deal_ids = [deal_ids] if isinstance(deal_ids, str) else list(deal_ids)
        analyses_filters.append(("in_", "deal_id", deal_ids))

    # Fetch component scores dynamically based on methodology
    component_cols = ["deal_id", "company_name", "overall_score", "analyzed_at"]
    for component in get_components():
        component_cols.append(f"{component}_score")

    analyses = select_all(sb, "analyses",
        columns=",".join(component_cols),
        filters=analyses_filters)

    # Deduplicate: keep most recent per deal
    latest = {}
    for a in analyses:
        deal_id = a.get("deal_id")
        analyzed_at = a.get("analyzed_at", "")
        if deal_id not in latest or analyzed_at > latest[deal_id].get("analyzed_at", ""):
            latest[deal_id] = a

    # Fetch deal data
    if deal_ids:
        # Use the verified list
        deals = select_all(sb, "deals",
            columns="deal_id,company_name,deal_value,stage,deal_status,owner_email",
            filters=[("in_", "deal_id", deal_ids)])
    else:
        deals = select_all(sb, "deals",
            columns="deal_id,company_name,deal_value,stage,deal_status,owner_email",
            filters=[("eq", "deal_status", "active")])

    # Combine and assess health
    health_results = []
    for d in deals:
        deal_id = d.get("deal_id")
        analysis = latest.get(deal_id, {})
        overall_score = analysis.get("overall_score", 0) or 0

        health_flags = []
        if overall_score < health_threshold:
            health_flags.append(f"low_overall_{overall_score}")

        # Check component-specific gaps
        for component in get_components():
            score = analysis.get(f"{component}_score", 0) or 0
            if score < 4:
                health_flags.append(f"{component}_gap_{score}")

        health_results.append({
            "deal_id": deal_id,
            "company_name": d.get("company_name"),
            "deal_value": d.get("deal_value"),
            "stage": d.get("stage"),
            "owner_email": d.get("owner_email"),
            "overall_score": overall_score,
            "health_flags": health_flags,
            "health_status": "at_risk" if health_flags else "healthy"
        })

    # Sort by health (worst first)
    health_results.sort(key=lambda x: (
        0 if x["health_status"] == "at_risk" else 1,
        x["overall_score"]
    ))

    at_risk_count = sum(1 for r in health_results if r["health_status"] == "at_risk")

    return {
        "deals": health_results,
        "total_deals": len(health_results),
        "at_risk_count": at_risk_count,
        "healthy_count": len(health_results) - at_risk_count,
        "threshold_used": health_threshold,
        "period": tw.get("label") if tw else None
    }


async def query_stale_deals(params: dict, sb) -> dict:
    """
    Deals with no recent activity (calls, updates, or stage movement).

    Answers: 'which deals are stuck?', 'what deals haven't moved?',
             'show me stale pipeline'
    """
    from datetime import datetime, timedelta

    tw = params.get("time_window", {})
    deal_ids = params.get("deal_ids", [])
    stale_days = params.get("stale_days", 30)

    # Calculate stale cutoff
    cutoff_date = (datetime.now() - timedelta(days=stale_days)).date().isoformat()

    # Get active deals
    deal_filters = [("eq", "deal_status", "active")]
    if deal_ids:
        if not isinstance(deal_ids, list):
            deal_ids = [deal_ids]
        deal_filters.append(("in_", "deal_id", deal_ids))

    deals = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,stage,owner_email,updated_at,close_date",
        filters=deal_filters)

    # Get recent call activity
    all_deal_ids = [d["deal_id"] for d in deals]
    recent_calls = []
    if all_deal_ids:
        recent_calls = select_all(sb, "calls",
            columns="call_id,deal_id,call_date,company_name",
            filters=[
                ("in_", "deal_id", all_deal_ids),
                ("gte", "call_date", cutoff_date)
            ])

    # Build map of deals with recent calls
    deals_with_calls = {c["deal_id"] for c in recent_calls if c.get("deal_id")}

    # Identify stale deals
    stale = []
    for d in deals:
        deal_id = d.get("deal_id")
        updated_at = d.get("updated_at", "")

        # Check if updated recently
        is_recently_updated = updated_at >= cutoff_date if updated_at else False
        has_recent_calls = deal_id in deals_with_calls

        if not is_recently_updated and not has_recent_calls:
            days_stale = (datetime.now().date() -
                         datetime.fromisoformat(updated_at[:10]).date()).days if updated_at else None

            stale.append({
                "deal_id": deal_id,
                "company_name": d.get("company_name"),
                "deal_value": d.get("deal_value"),
                "stage": d.get("stage"),
                "owner_email": d.get("owner_email"),
                "last_activity": updated_at,
                "days_stale": days_stale,
                "close_date": d.get("close_date")
            })

    # Sort by days stale (most stale first)
    stale.sort(key=lambda x: x.get("days_stale") or 0, reverse=True)

    return {
        "stale_deals": stale,
        "count": len(stale),
        "total_active_deals": len(deals),
        "stale_percentage": round(len(stale) / max(len(deals), 1) * 100, 1),
        "stale_threshold_days": stale_days,
        "cutoff_date": cutoff_date
    }


async def query_pre_call_brief(params: dict, sb) -> dict:
    """
    Pre-call preparation brief for a specific deal.

    Returns:
    - Current MEDDICC component scores
    - Stage-specific questions to ask (from coaching_client.yaml)
    - Recent call history
    - Known objections/gaps

    Reads STAGE_COMPONENT_QUESTIONS from config/coaching_client.yaml
    to provide stage-aware coaching guidance.
    """
    import yaml
    from pathlib import Path
    from api.stage_requirements import get_components, get_requirements_for_stage

    company = params.get("company", "")
    if not company and params.get("company_names"):
        company = params["company_names"][0]

    if not company:
        return {"error": "Company name required for pre-call brief"}

    # Get deal
    deals = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,stage,owner_email,close_date")
    deal = next((d for d in deals
                 if company.lower() in (d.get("company_name") or "").lower()), None)

    if not deal:
        return {"error": f"No deal found for '{company}'"}

    deal_id = deal["deal_id"]
    stage_id = deal.get("stage")

    # Get latest MEDDICC analysis
    component_cols = ["deal_id", "overall_score", "analyzed_at"]
    for component in get_components():
        component_cols.append(f"{component}_score")

    analyses = select_all(sb, "analyses",
        columns=",".join(component_cols),
        filters=[("eq", "deal_id", deal_id)])
    analyses.sort(key=lambda x: x.get("analyzed_at", ""), reverse=True)
    latest_analysis = analyses[0] if analyses else {}

    # Get stage requirements
    requirements = get_requirements_for_stage(stage_id) if stage_id else {}

    # Identify gaps (components below required threshold for stage)
    component_gaps = []
    for component in get_components():
        required_threshold = requirements.get(component, 0)
        actual_score = latest_analysis.get(f"{component}_score", 0) or 0

        if required_threshold and actual_score < required_threshold:
            component_gaps.append({
                "component": component,
                "current_score": actual_score,
                "required_score": required_threshold,
                "gap": required_threshold - actual_score
            })

    # Get recent calls
    calls = select_all(sb, "calls",
        columns="call_id,call_date,title,duration_minutes",
        filters=[("eq", "company_slug", deal.get("company_name", "").lower().replace(" ", "-"))])
    calls.sort(key=lambda x: x.get("call_date", ""), reverse=True)
    recent_calls = calls[:5]

    # Get objections
    objections = select_all(sb, "objections",
        columns="category,verbatim_quote,rep_response",
        filters=[("eq", "company_name", deal["company_name"])])

    # Load stage-specific questions from coaching_client.yaml
    config_path = Path(__file__).parent.parent / "config" / "coaching_client.yaml"
    config = yaml.safe_load(open(config_path))

    # STAGE_COMPONENT_QUESTIONS structure (if defined in config)
    stage_questions = config.get("stage_component_questions", {}) or {}
    relevant_questions = stage_questions.get(stage_id, {}) if stage_id else {}

    return {
        "deal": deal,
        "latest_scores": latest_analysis,
        "component_gaps": component_gaps,
        "stage_requirements": requirements,
        "recommended_questions": relevant_questions,
        "recent_calls": recent_calls,
        "known_objections": objections,
        "prep_note": (
            f"Focus on: {', '.join(g['component'] for g in component_gaps[:3])}"
            if component_gaps else "No critical gaps — focus on advancing the deal"
        )
    }


async def query_rep_pipeline(params: dict, sb) -> dict:
    """
    Pipeline for a specific rep.

    GrowthBook bugs fixed:
    1. Errored on rep names - nothing resolved "Christian" to email
    2. Param mismatch: intent prompt emitted rep_email, handler read owner_email

    Fix: Accepts owner_email, rep_email, first name, or full name.
    Resolves via user_personas table.
    """
    # Accept multiple param names
    rep_identifier = (params.get("owner_email") or
                     params.get("rep_email") or
                     params.get("rep_name") or
                     params.get("rep", ""))

    if not rep_identifier:
        return {"error": "Rep identifier required (email, first name, or full name)"}

    # Resolve to email via user_personas
    personas = select_all(sb, "user_personas",
        columns="email,display_name,name,role")

    matched_email = None
    rep_identifier_lower = rep_identifier.lower()

    for p in personas:
        email = p.get("email", "")
        display_name = (p.get("display_name") or "").lower()
        name = (p.get("name") or "").lower()

        # Match on email, display_name, name, or first name
        if (rep_identifier_lower == email.lower() or
            rep_identifier_lower == display_name or
            rep_identifier_lower == name or
            rep_identifier_lower in name.split()):
            matched_email = email
            break

    if not matched_email:
        return {
            "error": f"No user found matching '{rep_identifier}'",
            "hint": "Try full email or exact first name"
        }

    # Get rep's pipeline
    tw = _resolve_tw(params)
    deals = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,arr_usd,stage,"
                "deal_status,close_date,forecast_category",
        filters=[
            ("eq", "owner_email", matched_email),
            ("eq", "deal_status", "active")
        ])

    # Get rep's analyses
    deal_ids = [d["deal_id"] for d in deals]
    analyses = []
    if deal_ids:
        analyses = select_all(sb, "analyses",
            columns="deal_id,overall_score,champion_score,analyzed_at",
            filters=[("in_", "deal_id", deal_ids)])

        # Keep latest per deal
        latest = {}
        for a in analyses:
            deal_id = a["deal_id"]
            analyzed_at = a.get("analyzed_at", "")
            if deal_id not in latest or analyzed_at > latest[deal_id].get("analyzed_at", ""):
                latest[deal_id] = a
        analyses = list(latest.values())

    # Build analysis map
    analysis_map = {a["deal_id"]: a for a in analyses}

    # Enrich deals with scores
    enriched_deals = []
    for d in deals:
        deal_id = d["deal_id"]
        analysis = analysis_map.get(deal_id, {})
        enriched_deals.append({
            **d,
            "overall_score": analysis.get("overall_score"),
            "champion_score": analysis.get("champion_score")
        })

    # Sort by deal value
    enriched_deals.sort(key=lambda x: x.get("deal_value") or 0, reverse=True)

    total_pipeline = sum(d.get("deal_value") or 0 for d in deals)

    return {
        "rep_email": matched_email,
        "deals": enriched_deals,
        "total_pipeline": total_pipeline,
        "deal_count": len(deals),
        "period": tw.get("label")
    }


async def query_rep_attainment(params: dict, sb) -> dict:
    """
    Rep attainment vs quota target.

    Shows closed-won ARR vs target for a specific rep in a period.
    """
    # Resolve rep (same pattern as query_rep_pipeline)
    rep_identifier = (params.get("owner_email") or
                     params.get("rep_email") or
                     params.get("rep_name") or
                     params.get("rep", ""))

    if not rep_identifier:
        return {"error": "Rep identifier required"}

    # Resolve to email
    personas = select_all(sb, "user_personas",
        columns="email,display_name,name")

    matched_email = None
    rep_identifier_lower = rep_identifier.lower()

    for p in personas:
        email = p.get("email", "")
        display_name = (p.get("display_name") or "").lower()
        name = (p.get("name") or "").lower()

        if (rep_identifier_lower == email.lower() or
            rep_identifier_lower == display_name or
            rep_identifier_lower == name or
            rep_identifier_lower in name.split()):
            matched_email = email
            break

    if not matched_email:
        return {"error": f"No user found matching '{rep_identifier}'"}

    tw = _resolve_tw(params)

    # Get closed-won deals for this rep
    won_deals = select_all(sb, "deals",
        columns="deal_id,company_name,deal_value,new_arr,close_date",
        filters=[
            ("eq", "owner_email", matched_email),
            ("eq", "deal_status", "won"),
            ("gte", "close_date", tw["start"]),
            ("lte", "close_date", tw["end"])
        ])

    total_closed = sum(d.get("deal_value") or 0 for d in won_deals)

    # Get target
    period_label = tw.get("label", "").replace(" ", "_")
    targets = select_all(sb, "rep_targets",
        columns="target_value,metric",
        filters=[
            ("eq", "entity_name", matched_email),
            ("eq", "period", period_label)
        ])

    target_value = targets[0].get("target_value") if targets else None

    attainment_pct = None
    if target_value and target_value > 0:
        attainment_pct = round((total_closed / target_value) * 100, 1)

    return {
        "rep_email": matched_email,
        "total_closed": total_closed,
        "target": target_value,
        "attainment_pct": attainment_pct,
        "deal_count": len(won_deals),
        "deals": won_deals,
        "period": tw["label"]
    }


async def query_team_leaderboard(params: dict, sb) -> dict:
    """
    Team leaderboard - rep rankings by pipeline, attainment, or MEDDICC scores.

    Answers: 'show me team performance', 'who's leading?',
             'team leaderboard this quarter'
    """
    tw = _resolve_tw(params)
    metric = params.get("metric", "pipeline")  # pipeline | attainment | meddicc

    # Get all reps from user_personas
    personas = select_all(sb, "user_personas",
        columns="email,display_name,role")

    # Filter to sales reps (role = ae or sdr)
    sales_reps = [p for p in personas
                  if p.get("role", "").lower() in ["ae", "account_executive", "sales"]]

    if not sales_reps:
        return {
            "leaderboard": [],
            "note": "No sales reps found in user_personas. Run seed_user_personas.py to populate."
        }

    leaderboard = []

    if metric == "pipeline":
        # Rank by open pipeline value
        for rep in sales_reps:
            email = rep["email"]
            deals = select_all(sb, "deals",
                columns="deal_value",
                filters=[
                    ("eq", "owner_email", email),
                    ("eq", "deal_status", "active")
                ])
            total = sum(d.get("deal_value") or 0 for d in deals)
            leaderboard.append({
                "rep_email": email,
                "display_name": rep.get("display_name"),
                "value": total,
                "deal_count": len(deals)
            })

    elif metric == "attainment":
        # Rank by closed-won vs target
        period_label = tw.get("label", "").replace(" ", "_")
        for rep in sales_reps:
            email = rep["email"]
            won_deals = select_all(sb, "deals",
                columns="deal_value",
                filters=[
                    ("eq", "owner_email", email),
                    ("eq", "deal_status", "won"),
                    ("gte", "close_date", tw["start"]),
                    ("lte", "close_date", tw["end"])
                ])
            total_closed = sum(d.get("deal_value") or 0 for d in won_deals)

            # Get target
            targets = select_all(sb, "rep_targets",
                columns="target_value",
                filters=[
                    ("eq", "entity_name", email),
                    ("eq", "period", period_label)
                ])
            target = targets[0].get("target_value") if targets else None

            attainment_pct = None
            if target and target > 0:
                attainment_pct = round((total_closed / target) * 100, 1)

            leaderboard.append({
                "rep_email": email,
                "display_name": rep.get("display_name"),
                "value": total_closed,
                "target": target,
                "attainment_pct": attainment_pct,
                "deal_count": len(won_deals)
            })

    elif metric == "meddicc":
        # Rank by average MEDDICC score
        for rep in sales_reps:
            email = rep["email"]
            deals = select_all(sb, "deals",
                columns="deal_id",
                filters=[
                    ("eq", "owner_email", email),
                    ("eq", "deal_status", "active")
                ])
            deal_ids = [d["deal_id"] for d in deals]

            if not deal_ids:
                leaderboard.append({
                    "rep_email": email,
                    "display_name": rep.get("display_name"),
                    "value": 0,
                    "deal_count": 0
                })
                continue

            analyses = select_all(sb, "analyses",
                columns="deal_id,overall_score,analyzed_at",
                filters=[("in_", "deal_id", deal_ids)])

            # Keep latest per deal
            latest = {}
            for a in analyses:
                deal_id = a["deal_id"]
                analyzed_at = a.get("analyzed_at", "")
                if deal_id not in latest or analyzed_at > latest[deal_id].get("analyzed_at", ""):
                    latest[deal_id] = a

            scores = [a.get("overall_score", 0) or 0 for a in latest.values()]
            avg_score = sum(scores) / len(scores) if scores else 0

            leaderboard.append({
                "rep_email": email,
                "display_name": rep.get("display_name"),
                "value": round(avg_score, 1),
                "deal_count": len(deal_ids),
                "scored_count": len(scores)
            })

    # Sort by value descending
    leaderboard.sort(key=lambda x: x.get("value") or 0, reverse=True)

    return {
        "leaderboard": leaderboard,
        "metric": metric,
        "period": tw.get("label")
    }


async def query_coaching_priorities(params: dict, sb) -> dict:
    """
    Coaching priorities based on deal blockers and MEDDICC gaps.

    Reads blocker taxonomy from config/coaching_seed.yaml (not hardcoded).
    Returns recommended coaching focus areas with prescribed responses.
    """
    import yaml
    from pathlib import Path

    tw = _resolve_tw(params)
    rep_identifier = (params.get("owner_email") or
                     params.get("rep_email") or
                     params.get("rep_name") or
                     params.get("rep"))

    # Load blocker taxonomy from coaching_seed.yaml
    config_path = Path(__file__).parent.parent / "config" / "coaching_seed.yaml"
    config = yaml.safe_load(open(config_path))
    blocker_taxonomy = config.get("blocker_taxonomy", {})

    # Get deals (optionally filtered by rep)
    filters = [("eq", "deal_status", "active")]

    if rep_identifier:
        # Resolve rep to email (same pattern as other rep handlers)
        personas = select_all(sb, "user_personas",
            columns="email,display_name,name")

        matched_email = None
        rep_identifier_lower = rep_identifier.lower()

        for p in personas:
            email = p.get("email", "")
            display_name = (p.get("display_name") or "").lower()
            name = (p.get("name") or "").lower()

            if (rep_identifier_lower == email.lower() or
                rep_identifier_lower == display_name or
                rep_identifier_lower == name or
                rep_identifier_lower in name.split()):
                matched_email = email
                break

        if matched_email:
            filters.append(("eq", "owner_email", matched_email))

    deals = select_all(sb, "deals",
        columns="deal_id,company_name,owner_email",
        filters=filters)

    deal_ids = [d["deal_id"] for d in deals]

    # Get MEDDICC analyses to identify gaps
    from api.stage_requirements import get_components

    component_cols = ["deal_id", "company_name", "overall_score"]
    for component in get_components():
        component_cols.append(f"{component}_score")

    analyses = []
    if deal_ids:
        analyses = select_all(sb, "analyses",
            columns=",".join(component_cols),
            filters=[("in_", "deal_id", deal_ids)])

    # Identify common gaps
    gap_counts = {}
    for component in get_components():
        gap_counts[component] = 0

    for a in analyses:
        for component in get_components():
            score = a.get(f"{component}_score", 0) or 0
            if score < 4:  # Below acceptable threshold
                gap_counts[component] += 1

    # Sort gaps by frequency
    sorted_gaps = sorted(gap_counts.items(), key=lambda x: x[1], reverse=True)
    top_gaps = [{"component": comp, "deal_count": count}
                for comp, count in sorted_gaps[:3] if count > 0]

    # Get blocker signals from call_quality table (if populated)
    call_quality_rows = select_all(sb, "call_quality",
        columns="blocker_type,pattern_flags,owner_email",
        filters=[])

    blocker_counts = {"technical": 0, "resourcing": 0, "cultural": 0, "commercial": 0}
    for row in call_quality_rows:
        blocker_type = row.get("blocker_type")
        if blocker_type in blocker_counts:
            blocker_counts[blocker_type] += 1

    # Build coaching priorities
    priorities = []

    # Priority 1: Most common MEDDICC gap
    if top_gaps:
        top_gap = top_gaps[0]
        priorities.append({
            "priority": "Most common MEDDICC gap",
            "component": top_gap["component"],
            "affected_deals": top_gap["deal_count"],
            "recommendation": f"Focus discovery questions on {top_gap['component'].replace('_', ' ')}"
        })

    # Priority 2: Most common blocker type
    if blocker_counts:
        top_blocker = max(blocker_counts.items(), key=lambda x: x[1])
        if top_blocker[1] > 0:
            blocker_type, count = top_blocker
            taxonomy_entry = blocker_taxonomy.get(blocker_type, {})

            priorities.append({
                "priority": "Most common blocker",
                "blocker_type": blocker_type,
                "occurrence_count": count,
                "signals": taxonomy_entry.get("signals", []),
                "right_response": taxonomy_entry.get("right_response", "")
            })

    # Priority 3: Deals at risk (low overall scores)
    at_risk = [a for a in analyses if (a.get("overall_score") or 0) < 40]
    if at_risk:
        priorities.append({
            "priority": "Deals at risk",
            "deal_count": len(at_risk),
            "recommendation": "Review deals with overall MEDDICC score < 40"
        })

    return {
        "priorities": priorities,
        "top_meddicc_gaps": top_gaps,
        "blocker_distribution": blocker_counts,
        "total_deals_analyzed": len(deals),
        "period": tw.get("label"),
        "rep_email": matched_email if rep_identifier else None
    }


async def query_sdr_activity(params: dict, sb) -> dict:
    """
    Daily SDR activity metrics from sdr_metrics table.

    Shows calls, emails, connect rates for individual SDRs.
    Answers: 'show me SDR activity', 'how many calls did Jake make?',
             'SDR performance this week'
    """
    tw = _resolve_tw(params)
    sdr_identifier = (params.get("owner_email") or
                     params.get("sdr_email") or
                     params.get("sdr_name") or
                     params.get("sdr"))

    # Check if table has data
    sample = select_all(sb, "sdr_metrics", columns="id", filters=[])
    if not sample:
        return {
            "sdr_activity": [],
            "note": (
                "SDR metrics table exists but is empty. "
                "This feature requires configuring Apollo, Salesloft, or Aircall "
                "API keys and running scripts/etl_sdr_metrics.py."
            )
        }

    # Build filters
    filters = [
        ("gte", "metric_date", tw["start"]),
        ("lte", "metric_date", tw["end"])
    ]

    if sdr_identifier:
        # Try to resolve to user_email via sdr_users table
        sdr_users = select_all(sb, "sdr_users",
            columns="user_email,user_name,tool_user_id,tool")

        matched_tool_users = []
        sdr_identifier_lower = sdr_identifier.lower()

        for u in sdr_users:
            email = (u.get("user_email") or "").lower()
            name = (u.get("user_name") or "").lower()

            if (sdr_identifier_lower == email or
                sdr_identifier_lower == name or
                sdr_identifier_lower in name.split()):
                matched_tool_users.append({
                    "tool": u["tool"],
                    "tool_user_id": u["tool_user_id"]
                })

        if not matched_tool_users:
            return {
                "error": f"No SDR found matching '{sdr_identifier}'",
                "hint": "Check sdr_users table or run etl_sdr_metrics.py"
            }

        # Filter by tool_user_id (may be multiple if user is in multiple tools)
        # Build OR filter across tools
        rows = []
        for tu in matched_tool_users:
            tool_rows = select_all(sb, "sdr_metrics",
                columns="tool,user_name,metric_date,calls_made,"
                        "connected_calls,connect_rate,emails_sent,"
                        "emails_opened,emails_replied,open_rate,reply_rate",
                filters=filters + [
                    ("eq", "tool", tu["tool"]),
                    ("eq", "tool_user_id", tu["tool_user_id"])
                ])
            rows.extend(tool_rows)
    else:
        # All SDRs
        rows = select_all(sb, "sdr_metrics",
            columns="tool,user_name,metric_date,calls_made,"
                    "connected_calls,connect_rate,emails_sent,"
                    "emails_opened,emails_replied,open_rate,reply_rate",
            filters=filters)

    # Sort by date
    rows.sort(key=lambda x: x.get("metric_date", ""), reverse=True)

    # Calculate aggregates
    total_calls = sum(r.get("calls_made") or 0 for r in rows)
    total_connected = sum(r.get("connected_calls") or 0 for r in rows)
    total_emails = sum(r.get("emails_sent") or 0 for r in rows)

    return {
        "sdr_activity": rows,
        "total_calls": total_calls,
        "total_connected": total_connected,
        "total_emails": total_emails,
        "avg_connect_rate": round(total_connected / total_calls * 100, 1) if total_calls > 0 else None,
        "period": tw["label"],
        "sdr": sdr_identifier
    }


async def query_sdr_performance(params: dict, sb) -> dict:
    """
    SDR conversion rates and benchmarks.

    Shows connect rates, reply rates, and activity benchmarks.
    Answers: 'SDR conversion rates', 'how are SDRs performing?',
             'best performing SDR'
    """
    tw = _resolve_tw(params)

    # Check if table has data
    sample = select_all(sb, "sdr_metrics", columns="id", filters=[])
    if not sample:
        return {
            "sdr_performance": [],
            "note": "SDR metrics table is empty. Configure SDR tools and run ETL."
        }

    # Get metrics for period
    rows = select_all(sb, "sdr_metrics",
        columns="tool,user_name,tool_user_id,metric_date,"
                "calls_made,connected_calls,connect_rate,"
                "emails_sent,emails_replied,reply_rate",
        filters=[
            ("gte", "metric_date", tw["start"]),
            ("lte", "metric_date", tw["end"])
        ])

    # Aggregate by user
    from collections import defaultdict
    user_stats = defaultdict(lambda: {
        "calls_made": 0,
        "connected_calls": 0,
        "emails_sent": 0,
        "emails_replied": 0
    })

    for r in rows:
        key = (r.get("tool"), r.get("tool_user_id"), r.get("user_name"))
        user_stats[key]["calls_made"] += r.get("calls_made") or 0
        user_stats[key]["connected_calls"] += r.get("connected_calls") or 0
        user_stats[key]["emails_sent"] += r.get("emails_sent") or 0
        user_stats[key]["emails_replied"] += r.get("emails_replied") or 0

    # Build performance summary
    performance = []
    for (tool, tool_user_id, user_name), stats in user_stats.items():
        calls = stats["calls_made"]
        connected = stats["connected_calls"]
        emails = stats["emails_sent"]
        replied = stats["emails_replied"]

        connect_rate = round(connected / calls * 100, 1) if calls > 0 else None
        reply_rate = round(replied / emails * 100, 1) if emails > 0 else None

        performance.append({
            "user_name": user_name,
            "tool": tool,
            "calls_made": calls,
            "connected_calls": connected,
            "connect_rate": connect_rate,
            "emails_sent": emails,
            "emails_replied": replied,
            "reply_rate": reply_rate
        })

    # Sort by calls made
    performance.sort(key=lambda x: x.get("calls_made") or 0, reverse=True)

    # Calculate team benchmarks
    total_calls = sum(p["calls_made"] for p in performance)
    total_connected = sum(p["connected_calls"] for p in performance)
    total_emails = sum(p["emails_sent"] for p in performance)
    total_replied = sum(p["emails_replied"] for p in performance)

    team_connect_rate = round(total_connected / total_calls * 100, 1) if total_calls > 0 else None
    team_reply_rate = round(total_replied / total_emails * 100, 1) if total_emails > 0 else None

    return {
        "sdr_performance": performance,
        "team_benchmarks": {
            "total_calls": total_calls,
            "team_connect_rate": team_connect_rate,
            "total_emails": total_emails,
            "team_reply_rate": team_reply_rate
        },
        "period": tw["label"]
    }


async def query_team_sdr_metrics(params: dict, sb) -> dict:
    """
    Team-level SDR aggregates (calls, emails, trends).

    Answers: 'show me team SDR metrics', 'SDR team performance',
             'how is the SDR team doing?'
    """
    tw = _resolve_tw(params)

    # Check if table has data
    sample = select_all(sb, "sdr_metrics", columns="id", filters=[])
    if not sample:
        return {
            "team_metrics": {},
            "note": "SDR metrics table is empty. Configure SDR tools and run ETL."
        }

    # Get all metrics for period
    rows = select_all(sb, "sdr_metrics",
        columns="metric_date,calls_made,connected_calls,connect_rate,"
                "emails_sent,emails_opened,emails_replied,voicemails",
        filters=[
            ("gte", "metric_date", tw["start"]),
            ("lte", "metric_date", tw["end"])
        ])

    # Aggregate by date for trending
    from collections import defaultdict
    daily_totals = defaultdict(lambda: {
        "calls": 0, "connected": 0, "emails": 0,
        "opened": 0, "replied": 0, "voicemails": 0
    })

    for r in rows:
        date = r.get("metric_date")
        daily_totals[date]["calls"] += r.get("calls_made") or 0
        daily_totals[date]["connected"] += r.get("connected_calls") or 0
        daily_totals[date]["emails"] += r.get("emails_sent") or 0
        daily_totals[date]["opened"] += r.get("emails_opened") or 0
        daily_totals[date]["replied"] += r.get("emails_replied") or 0
        daily_totals[date]["voicemails"] += r.get("voicemails") or 0

    # Build daily trend
    daily_trend = []
    for date in sorted(daily_totals.keys()):
        stats = daily_totals[date]
        daily_trend.append({
            "date": date,
            "calls": stats["calls"],
            "connected": stats["connected"],
            "emails": stats["emails"],
            "connect_rate": round(stats["connected"] / stats["calls"] * 100, 1) if stats["calls"] > 0 else None
        })

    # Overall totals
    total_calls = sum(r.get("calls_made") or 0 for r in rows)
    total_connected = sum(r.get("connected_calls") or 0 for r in rows)
    total_emails = sum(r.get("emails_sent") or 0 for r in rows)
    total_replied = sum(r.get("emails_replied") or 0 for r in rows)
    total_voicemails = sum(r.get("voicemails") or 0 for r in rows)

    return {
        "team_metrics": {
            "total_calls": total_calls,
            "total_connected": total_connected,
            "connect_rate": round(total_connected / total_calls * 100, 1) if total_calls > 0 else None,
            "total_emails": total_emails,
            "total_replied": total_replied,
            "reply_rate": round(total_replied / total_emails * 100, 1) if total_emails > 0 else None,
            "total_voicemails": total_voicemails
        },
        "daily_trend": daily_trend,
        "period": tw["label"]
    }


async def query_pipeline_movement(params: dict, sb) -> dict:
    """
    Pipeline movement - how deals moved through stages over time.

    Uses waterfall_weekly table to show new pipeline, won, lost, and net change.
    Answers: 'show me pipeline movement', 'how did pipeline change?',
             'pipeline waterfall this quarter'
    """
    tw = _resolve_tw(params)

    # Get weekly waterfall data
    rows = select_all(sb, "waterfall_weekly",
        columns="week_ending,pipeline_id,new_pipeline_value,"
                "won_value,lost_value,net_change,"
                "pulled_in_value,pushed_out_value,deals_qualified_count",
        filters=[
            ("gte", "week_ending", tw["start"]),
            ("lte", "week_ending", tw["end"])
        ])

    if not rows:
        return {
            "pipeline_movement": [],
            "note": (
                "No waterfall data for this period. "
                "Waterfall snapshots are computed weekly. "
                "Needs at least 2 weeks of data to compute movement."
            )
        }

    # Sort by week
    rows.sort(key=lambda x: x.get("week_ending", ""))

    # Calculate period totals
    total_new = sum(r.get("new_pipeline_value") or 0 for r in rows)
    total_won = sum(r.get("won_value") or 0 for r in rows)
    total_lost = sum(r.get("lost_value") or 0 for r in rows)
    total_net_change = sum(r.get("net_change") or 0 for r in rows)
    total_qualified = sum(r.get("deals_qualified_count") or 0 for r in rows)

    return {
        "pipeline_movement": rows,
        "period_totals": {
            "new_pipeline": total_new,
            "won": total_won,
            "lost": total_lost,
            "net_change": total_net_change,
            "deals_qualified": total_qualified
        },
        "period": tw["label"]
    }


async def query_call_quality(params: dict, sb) -> dict:
    """
    Discovery call quality scores from call_quality table (migration 038).

    Returns quality assessment across 5 dimensions:
    - Quantification (did they leave with numbers?)
    - Incumbent picture (cost, contract end, what's wrong)
    - Technical picture (warehouse, SDK, who runs tests)
    - Decision process (who decides, threshold, timeline)
    - Question quality (open, one at a time, followed up)

    Answers: 'how are our discovery calls?', 'show me call quality',
             'which reps need discovery coaching?'
    """
    tw = params.get("time_window", {})
    owner_email = params.get("owner_email")
    deal_ids = params.get("deal_ids", [])

    # Check if table has any data
    sample = select_all(sb, "call_quality", columns="id", filters=[])
    if not sample:
        return {
            "call_quality": [],
            "note": (
                "Call quality table exists but is empty. "
                "This feature must be explicitly enabled and requires "
                "running discovery quality ETL to populate scores."
            )
        }

    # Build filters
    filters = []
    if tw and tw.get("start"):
        filters.append(("gte", "call_date", tw["start"]))
    if tw and tw.get("end"):
        filters.append(("lte", "call_date", tw["end"]))
    if owner_email:
        filters.append(("eq", "owner_email", owner_email))
    if deal_ids:
        if not isinstance(deal_ids, list):
            deal_ids = [deal_ids]
        filters.append(("in_", "deal_id", deal_ids))

    # Fetch quality scores
    rows = select_all(sb, "call_quality",
        columns="call_id,deal_id,company_name,owner_email,call_date,"
                "quantification_score,incumbent_picture_score,"
                "technical_picture_score,decision_process_score,"
                "question_quality_score,overall_quality_score,"
                "numbers_obtained,numbers_missing,pattern_flags,"
                "strongest_moment,weakest_moment",
        filters=filters)

    # Calculate aggregates
    if rows:
        avg_overall = sum(r.get("overall_quality_score", 0) or 0 for r in rows) / len(rows)
        avg_quantification = sum(r.get("quantification_score", 0) or 0 for r in rows) / len(rows)
        avg_incumbent = sum(r.get("incumbent_picture_score", 0) or 0 for r in rows) / len(rows)
        avg_technical = sum(r.get("technical_picture_score", 0) or 0 for r in rows) / len(rows)
        avg_decision = sum(r.get("decision_process_score", 0) or 0 for r in rows) / len(rows)
        avg_question = sum(r.get("question_quality_score", 0) or 0 for r in rows) / len(rows)

        # Common pattern flags
        all_flags = []
        for r in rows:
            all_flags.extend(r.get("pattern_flags", []) or [])
        from collections import Counter
        pattern_counts = Counter(all_flags)
    else:
        avg_overall = avg_quantification = avg_incumbent = avg_technical = 0
        avg_decision = avg_question = 0
        pattern_counts = {}

    return {
        "call_quality": rows,
        "count": len(rows),
        "averages": {
            "overall": round(avg_overall, 1),
            "quantification": round(avg_quantification, 1),
            "incumbent_picture": round(avg_incumbent, 1),
            "technical_picture": round(avg_technical, 1),
            "decision_process": round(avg_decision, 1),
            "question_quality": round(avg_question, 1)
        },
        "common_patterns": dict(pattern_counts.most_common(5)),
        "period": tw.get("label") if tw else None
    }
