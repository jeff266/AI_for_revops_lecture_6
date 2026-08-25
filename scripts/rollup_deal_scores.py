#!/usr/bin/env python3
"""
Deal-level roll-up write path (PROGRESSIVE_SCORING_SPEC, Phase 5).

Turn a deal's per-call scores (call_scores) into the deal's MEDDICC score of
record and write it through the EXISTING writers — no parallel write path. The
whole downstream contract (HubSpot note + properties, Supabase analyses) is
driven by a markdown analysis draft that carries 'Score: N/10' lines, so this
module rolls up call_scores, renders a draft in that exact format, and hands it
to hubspot.upsert_meddicc_note / write_component_scores / sb.insert_analysis
unchanged.

Roll-up = most-recent-non-null per component (call_scorer.roll_up over the stored
per-call deltas), with provenance. Bands are uniform: red 0-3 / yellow 4-6 /
green 7-10. A component no call established rolls up to null → rendered Unknown,
score 0, contributing nothing to the /70.

This is the read path the nightly uses when SCORING_MODE=progressive. It calls
the model zero times.

PHASE 4 PORT: Rewired to read from JSONB (component_scores, evidence) instead of
fixed columns. Methodology-agnostic: works for MEDDICC, MEDDPICC, SPICED, BANT.
"""
import json
from datetime import datetime

import call_scorer as cs
from utils import get_components, component_key

# Prose abbreviations for the MEDDICC output headers (M/E/D/D/I/C/C).
# Build dynamically for methodology portability
def _build_abbr():
    """Build abbreviation map for components. Uses first letter of each word."""
    abbr = {}
    for label in get_components():
        key = component_key(label)
        # Simple first-letter abbreviation
        abbr[key] = label[0].upper()
    return abbr

_ABBR = _build_abbr()


def band(score):
    if score is None:
        return "unknown"
    if score <= 3:
        return "red"
    if score <= 6:
        return "yellow"
    return "green"


def _status(score):
    """HubSpot component status from the score (mirrors the ✅/⚠️/❌ semantics)."""
    if score is None:
        return "unknown"
    if score >= 7:
        return "identified"
    if score >= 4:
        return "partial"
    return "unknown"


def _status_emoji(score):
    return {"identified": "✅", "partial": "⚠️", "unknown": "❌"}[_status(score)]


def load_deal_call_scores(sb, deal_id):
    """Load call_scores rows for a deal from Supabase (JSONB schema).

    PHASE 4 PORT: Reads component_scores and evidence as JSONB, not fixed columns.
    Migration 043 stores {component_key: score} in component_scores JSONB column.
    """
    from supabase_client import select_all
    cols = "call_id,deal_id,call_date,component_scores,evidence"
    rows = select_all(sb, "call_scores", columns=cols,
                     filters=[("eq", "deal_id", str(deal_id))])
    rows.sort(key=lambda r: (r.get("call_date") or ""))
    return rows


def _row_components(row):
    """Parse JSONB component_scores and evidence from a call_scores row.

    PHASE 4 PORT: Expects JSONB schema:
    - component_scores: {"metrics": 7, "economic_buyer": 6, ...}
    - evidence: {"metrics": "Quote: ...", "economic_buyer": "Quote: ...", ...}

    Returns {key: {"score": int|None, "evidence": str|None}} for all components.
    """
    # Parse component_scores JSONB
    scores_json = row.get("component_scores")
    if isinstance(scores_json, str):
        try:
            scores = json.loads(scores_json)
        except Exception:
            scores = {}
    elif isinstance(scores_json, dict):
        scores = scores_json
    else:
        scores = {}

    # Parse evidence JSONB
    ev_json = row.get("evidence")
    if isinstance(ev_json, str):
        try:
            ev = json.loads(ev_json)
        except Exception:
            ev = {}
    elif isinstance(ev_json, dict):
        ev = ev_json
    else:
        ev = {}

    # Build component dict for all configured components
    component_keys = [component_key(label) for label in get_components()]
    return {k: {"score": scores.get(k), "evidence": ev.get(k)} for k in component_keys}


def rollup(rows):
    """call_scores rows -> {key:{score,evidence,call_id,call_date}} (most-recent-non-null)."""
    scored = [{"call_id": r["call_id"], "call_date": r.get("call_date"),
               "components": _row_components(r)} for r in rows]
    return cs.roll_up(scored)


def component_details(rolled):
    """Shape for hubspot.write_component_scores: {key:{score,status,evidence}}."""
    out = {}
    for _, key in cs.COMPONENTS:
        c = rolled[key]
        sc = c["score"]
        out[key] = {"score": sc if sc is not None else 0,
                   "status": _status(sc),
                   "evidence": c.get("evidence") or ""}
    return out


def overall(rolled):
    return sum(v["score"] for v in rolled.values() if v.get("score") is not None)


def render_md(company, deal_id, rolled, ncalls):
    """Render a MEDDICC analysis draft whose 'Score: N/10' lines and component
    labels are exactly what hubspot._extract_scores_from_analysis expects, so the
    existing writers parse it with no changes."""
    tot = overall(rolled)
    lines = [f"# MEDDICC Analysis: {company}", ""]
    for label, key in cs.COMPONENTS:
        c = rolled[key]
        sc = c["score"]
        shown = 0 if sc is None else sc
        ev = (c.get("evidence") or "").strip()
        prov = c.get("call_date")
        lines.append(f"### {_ABBR[key]} - {label}")
        lines.append(f"**Status**: {_status_emoji(sc)}")
        lines.append(f"**Score**: {shown}/10")
        lines.append("")
        if sc is None:
            lines.append("**Evidence from calls**: Not established in any scored call yet.")
        else:
            lines.append(f"**Evidence from calls**: {ev or '(no evidence recorded)'} "
                        f"(most recently set by the call on {prov})")
        lines.append("")

    # Build component keys and label map
    component_keys = [component_key(label) for label in get_components()]
    slabel = {component_key(label): label for label in get_components()}

    strongest = max(component_keys, key=lambda k: (rolled[k]["score"] or -1))
    weakest = min(component_keys, key=lambda k: (rolled[k]["score"] if rolled[k]["score"] is not None else 99))
    wk = rolled[weakest]["score"]
    lines.append("## Summary & Recommended Actions")
    lines.append(f"Progressive roll-up across {ncalls} scored call(s): overall {tot}/70. "
                f"Strongest component is {slabel[strongest]} ({rolled[strongest]['score']}); "
                f"weakest is {slabel[weakest]} ({wk if wk is not None else 'unknown'}). "
                f"Focus the next call on advancing the weakest components with new evidence.")
    return "\n".join(lines)


def build_result(analysis_md, ncalls):
    """result dict shape consumed by sb.insert_analysis (draft/iterations/passed)."""
    return {"draft": analysis_md, "iterations": 1, "passed": True,
            "evaluation": {}, "outcome": "progressive_rollup", "root_cause": "",
            "scores_pinned": True}


def write_rollup(deal, sb, hubspot, sb_writer, output_dir):
    """Roll up one deal's call_scores and write it through the existing HubSpot +
    Supabase writers. Returns a status dict for the nightly loop, or None if the
    deal has no scored calls (nothing to roll up yet)."""
    deal_id = deal.get("deal_id")
    company = deal.get("company_name") or deal.get("deal_name") or str(deal_id)
    rows = load_deal_call_scores(sb, deal_id)
    if not rows:
        return None
    rolled = rollup(rows)
    tot = overall(rolled)
    analysis = render_md(company, deal_id, rolled, len(rows))
    details = component_details(rolled)

    from pathlib import Path
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"meddicc_rollup_{deal_id}_{ts}.md"
    with open(output_file, "w") as f:
        f.write(f"# MEDDICC Analysis: {company}\n\n**Deal ID:** {deal_id}\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        f.write(f"**Scored calls:** {len(rows)}\n**Mode:** progressive roll-up\n\n---\n\n")
        f.write(analysis)

    if hubspot:
        try:
            hubspot.upsert_meddicc_note(deal_id=deal_id, analysis_content=analysis, calls_count=len(rows))
        except Exception as e:
            print(f"   ⚠️  {company}: HubSpot note failed: {e}")
        try:
            hubspot.write_component_scores(deal_id=deal_id, component_details=details)
        except Exception as e:
            print(f"   ⚠️  {company}: HubSpot component scores failed: {e}")
    if sb_writer:
        try:
            from hubspot_deals import HubSpotDealsClient
            hs = HubSpotDealsClient.__new__(HubSpotDealsClient)
            scores = hs._extract_scores_from_analysis(analysis)
            sb_writer.insert_analysis(deal_id=str(deal_id), company_name=company,
                                     result=build_result(analysis, len(rows)),
                                     scores=scores, output_file=str(output_file.name),
                                     component_details=details)
        except Exception as e:
            print(f"   ⚠️  {company}: Supabase analysis write failed: {e}")

    return {"deal_id": deal_id, "company": company, "status": "analyzed",
            "mode": "progressive", "calls": len(rows), "overall_score": tot,
            "passed": True}
