#!/usr/bin/env python3
"""
Per-call MEDDICC scorer (PROGRESSIVE_SCORING_SPEC, Phase 1).

Score ONE call in isolation: "what did THIS call establish about each of the
seven MEDDICC components?" Return a 0-10 score with evidence, or null when the
call is silent on a component. A later call supersedes an earlier one at the
roll-up (most-recent-non-null), so a single call is a smaller, better-posed
question than "what do four calls establish about seven components?".

Design constraints (from the spec, enforced here):
  - One call per pass. This module never batches calls into one prompt.
  - Null when a call says nothing about a component — never zero, never a guess.
  - Evidence (a quote/fact from THIS call) accompanies every non-null score.
  - Stage NEVER enters the scoring prompt; it applies only at the reporting
    layer. deal_context carries company identity, nothing stage-derived.
  - Temperature 0, via LLMClient.complete (extra_body mechanism).

The calibration bands and the "score on action, not sentiment / default to the
lower score on ambiguity" rules are lifted verbatim from prompts/CLAUDE.md so a
per-call score is anchored to the same rubric as the batch scorer. The batch
scorer's carry-forward / cumulative-state language is deliberately omitted —
there is no prior state in a single-call pass.

PHASE 4 PORT: Rewired to use get_components() + component_key() from utils.py.
Replaces fixed-column to_score_row() with JSONB for methodology-agnostic storage.
"""
import json
import re
from utils import get_components, component_key

# Dynamic component loading — methodology comes from config/client.yaml
# MEDDICC: 7 components, MEDDPIC: 8 (adds Paper Process), SPICED: 5, BANT: 4
# No local copy — use get_components() and component_key() directly

def _component_keys():
    """Get current methodology's component keys. Not cached - call sparingly."""
    return [component_key(label) for label in get_components()]

# Bump when the prompt/rubric changes so a re-backfill can find stale rows.
SCORER_VERSION = "phase4-progressive-jsonb-v1"

# Two passes, cumulative-context. Prompt-level "return null" does NOT make a model
# abstain — handed a rich transcript and a seven-field form it fills every field
# (empirically: null never fired across two prompt revisions). So abstention is its
# own step: PASS 1 SELECTS which components THIS call changes versus what earlier
# calls already established; PASS 2 scores only those, as the CUMULATIVE
# understanding through this call. Components the call leaves unchanged are omitted
# and carry forward at the roll-up. This reproduces a human's carry-forward reading
# (a later shallow mention cannot lower a deep earlier score; a component can climb
# across calls to a level no single call reaches in isolation) while keeping the
# spec's schema, most-recent-non-null roll-up, and downward regression intact.
#
# The one deviation from spec §1 ("you have no prior calls"): the scorer is shown
# the ROLLED SCORES so far — not the raw prior transcripts. That is a lightweight
# state carry, not the batch scorer's whole-history pass.

def _build_gate_system_prompt():
    """Build the gate system prompt dynamically based on configured methodology."""
    component_lines = []
    for label in get_components():
        key = component_key(label)
        # Methodology-specific descriptions
        if key == "metrics":
            desc = "quantified business impact / value metrics"
        elif key == "economic_buyer":
            desc = "who controls budget; confirmed authority; buyer-owned approval steps"
        elif key == "decision_criteria":
            desc = "the stated requirements / evaluation criteria"
        elif key == "decision_process":
            desc = "timeline, stakeholders, approval steps"
        elif key == "pain":
            desc = "the problem, its urgency and business impact"
        elif key == "champion":
            desc = "a person taking internal action to advance the deal"
        elif key == "competition":
            desc = "competitors, incumbent tools, evaluation status"
        elif key == "paper_process":
            desc = "legal/procurement requirements, security questionnaire, formal review steps"
        # SPICED components
        elif key == "situation":
            desc = "current state, pain drivers, urgency context"
        elif key == "impact":
            desc = "quantified business impact if solved / not solved"
        elif key == "critical_event":
            desc = "forcing function, deadline, catalyst for change"
        elif key == "decision":
            desc = "decision makers, approval process, budget authority"
        # BANT components
        elif key == "budget":
            desc = "confirmed budget, authority to spend"
        elif key == "authority":
            desc = "decision maker identified and engaged"
        elif key == "need":
            desc = "specific business need or pain"
        elif key == "timeline":
            desc = "decision timeline, implementation schedule"
        else:
            desc = f"{label.lower()} (component-specific criteria)"

        component_lines.append(f"  {key:<20} — {desc}")

    component_list = "\n".join(component_lines)
    return f"""\
You are given ONE sales call plus the MEDDICC picture established by EARLIER calls
on this deal. Your only job: decide which components THIS call CHANGES — adds new
substantive evidence that would RAISE a component, or shows a genuine setback that
would LOWER it, or establishes a component that had nothing before.

The components (use these exact keys):
{component_list}

Return a JSON array of the component keys THIS call changes, and NOTHING else.
Example: ["economic_buyer", "decision_process"]

Select a component if this call adds ANY new SPECIFIC evidence to it — even
incrementally. Several components ACCRETE across calls: decision_criteria (each
call may add a new requirement), decision_process (new stakeholder, new timeline
detail), metrics (a new number), competition (a new competitor or comparison).
Do NOT skip such a component just because an earlier call already touched it — if
this call adds a new specific, SELECT it so its cumulative score can climb. A
technical deep-dive typically advances decision_criteria and competition; a
commercial/pricing call typically advances metrics, economic_buyer, and
competition.

Still be honest: if this call merely REPEATS what is already established, adding no
new specific, do not select it — it carries forward unchanged. A truly narrow call
changes few components; a broad discovery or technical call may change many. An
empty array [] is valid. Do not consider the deal's pipeline stage.
"""

# Score system prompt uses the same calibration bands, methodology-agnostic
SCORE_SYSTEM_PROMPT = """\
You are given ONE sales call, the MEDDICC picture from EARLIER calls, and a list of
components THIS call changes. For each, give the CUMULATIVE score 0-10 — the deal's
standing on that component through this call, i.e. everything established so far
PLUS what this call adds — with evidence (a quote or specific fact from THIS call
that justifies the change).

Return a JSON object whose keys are exactly the components you were asked to score,
each {"score": <1-10 integer>, "evidence": "<quote/fact from this call>"}. No other
keys, no prose, no markdown fences.

RULES
- The score is cumulative, not "this call in isolation." A call that adds the final
  piece of a criteria list can reach 8 even though it only stated one new criterion.
- Only LOWER a component below its earlier value if THIS call shows a real setback
  (e.g. the champion left, a requirement was dropped). Absent that, a component you
  were asked to score should not fall below what earlier calls established.
- Default to the LOWER score on ambiguity. Enthusiasm without specifics = 1/10.
- Score Champion and Economic Buyer on what the buyer DOES, not how they FELT.
  A contact who sounds excited but owns no internal next step is Champion 1-2.
- Do NOT consider the deal's pipeline stage; it is not provided and must not be inferred.

SCORING CALIBRATION
Metrics:            9-10 quantified metric; 7-8 clear business impact; 5-6 pain mentioned not quantified; 3-4 vague; 1-2 barely.
Economic Buyer:     9-10 direct engagement + budget authority confirmed; 7-8 named + budget holder confirmed; 5-6 role unclear on budget; 3-4 generic "leadership"; 1-2 name/title only.
Decision Criteria:  9-10 formal criteria/scorecard; 7-8 key criteria stated; 5-6 some criteria incomplete; 3-4 vague requirements; 1-2 barely.
Decision Process:   9-10 full timeline + stakeholders + approvals; 7-8 timeline and key stakeholders; 5-6 timeline OR stakeholders; 3-4 vague timing; 1-2 barely.
Identified Pain:    9-10 specific urgent pain w/ impact + timeline; 7-8 clear pain w/ context; 5-6 pain not urgent/specific; 3-4 generic interest; 1-2 barely.
Champion:           9-10 active internal selling / business case; 7-8 facilitating access, owns next steps; 5-6 engaged not selling; 3-4 responsive but passive; 1-2 no owned internal action.
Competition:        9-10 full landscape + eval status + our differentiation; 7-8 current tool + limitations; 5-6 competitor mentioned, limited detail; 3-4 vague "other tools"; 1-2 barely.
"""

# Cache the gate system prompt (built once, reused)
_GATE_SYSTEM_PROMPT_CACHE = None

def _get_gate_system_prompt():
    global _GATE_SYSTEM_PROMPT_CACHE
    if _GATE_SYSTEM_PROMPT_CACHE is None:
        _GATE_SYSTEM_PROMPT_CACHE = _build_gate_system_prompt()
    return _GATE_SYSTEM_PROMPT_CACHE


def _company_header(deal_context):
    if deal_context:
        company = (deal_context.get("company") or deal_context.get("company_name") or "").strip()
        if company:
            return f"Company: {company}\n\n"
    return ""


def _format_prior_state(prior_state):
    """Readable summary of the rolled-so-far scores for the prompt. prior_state is
    a roll_up() result ({key:{score,evidence,call_id,call_date}}) or None."""
    if not prior_state:
        return "No earlier calls — this is the first call on the deal; nothing is established yet."
    lines = []
    for label in get_components():
        key = component_key(label)
        cell = prior_state.get(key) or {}
        sc = cell.get("score")
        if sc is None:
            lines.append(f"- {label}: not yet established")
        else:
            ev = (cell.get("evidence") or "").strip().replace("\n", " ")
            if len(ev) > 200:
                ev = ev[:200] + "…"
            lines.append(f"- {label}: {sc}/10 — {ev}" if ev else f"- {label}: {sc}/10")
    return "MEDDICC established by earlier calls:\n" + "\n".join(lines)


def build_gate_messages(call_text, deal_context=None, prior_state=None):
    return [{
        "role": "user",
        "content": (
            f"{_company_header(deal_context)}{_format_prior_state(prior_state)}\n\n"
            f"Which MEDDICC components does THIS call change versus the above? "
            f"Return the JSON array only.\n\n=== CALL ===\n{call_text}"
        ),
    }]


def build_score_messages(call_text, components, deal_context=None, prior_state=None):
    keys = ", ".join(components)
    return [{
        "role": "user",
        "content": (
            f"{_company_header(deal_context)}{_format_prior_state(prior_state)}\n\n"
            f"Score ONLY these components as the cumulative standing through this call: "
            f"{keys}. Return the JSON object with exactly those keys.\n\n=== CALL ===\n{call_text}"
        ),
    }]


def _parse_advanced(text):
    """Parse PASS 1's JSON array into a list of valid component keys (order
    preserved, de-duped, unknown keys dropped). Tolerant of fences/prose."""
    if not text:
        return []
    obj = _extract_json_value(text, "[", "]")
    if not isinstance(obj, list):
        return []
    seen, out = set(), []
    component_keys = _component_keys()
    for item in obj:
        k = str(item).strip().lower()
        if k in component_keys and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _coerce_score(v):
    """0-10 int, or None. Rejects out-of-range and non-numeric; 'null'/'' → None.
    A bare 0 is treated as None: the rubric forbids 0-means-not-discussed, so a 0
    is a model slip for null, not a real score."""
    if v is None:
        return None
    if isinstance(v, bool):  # guard: bool is an int subclass
        return None
    if isinstance(v, str):
        v = v.strip()
        if v == "" or v.lower() == "null":
            return None
        try:
            v = float(v)
        except ValueError:
            return None
    if isinstance(v, float):
        if v != v:  # NaN
            return None
        v = int(round(v))
    if isinstance(v, int):
        if v <= 0:
            return None
        return v if 0 <= v <= 10 else None
    return None


def _coerce_evidence(v, score):
    if score is None:
        return None
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def parse_call_scores(text):
    """Parse the model's JSON into {key: {"score": int|None, "evidence": str|None}}
    for all components. Tolerant of code fences and trailing prose; any
    component the model omits or malforms becomes null (safe: null = 'said
    nothing'). Never raises."""
    component_keys = _component_keys()
    out = {k: {"score": None, "evidence": None} for k in component_keys}
    if not text:
        return out
    obj = _extract_json_object(text)
    if not isinstance(obj, dict):
        return out
    for key in component_keys:
        cell = obj.get(key)
        if isinstance(cell, dict):
            score = _coerce_score(cell.get("score"))
            out[key] = {"score": score, "evidence": _coerce_evidence(cell.get("evidence"), score)}
        else:
            # Some models emit a bare number/null instead of {score, evidence}.
            score = _coerce_score(cell)
            out[key] = {"score": score, "evidence": None}
    return out


def _extract_json_object(text):
    """First balanced {...} object in text, JSON-parsed. Returns None on failure."""
    obj = _extract_json_value(text, "{", "}")
    return obj if isinstance(obj, dict) else None


def _extract_json_value(text, open_ch="{", close_ch="}"):
    """First balanced JSON value delimited by open_ch/close_ch, parsed. Handles
    ```json fences and trailing commentary. Returns the parsed value or None."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    start = t.find(open_ch)
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(t)):
        if t[i] == open_ch:
            depth += 1
        elif t[i] == close_ch:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except Exception:
                    return None
    return None


def score_call(call_text, deal_context=None, prior_state=None, client=None):
    """Score one call in two passes against the deal's rolled state so far:
      1. SELECT the components THIS call changes vs prior_state.
      2. SCORE only those, as the CUMULATIVE standing through this call.

    prior_state is a roll_up() result ({key:{score,evidence,call_id,call_date}}) or
    None for the first call. Returns a DELTA: only changed components are non-null,
    so the result feeds call_scores / roll_up unchanged (most-recent-non-null over
    the deltas replays the fold).

    Returns:
        {"components": {key: {"score": int|None, "evidence": str|None}},
         "advanced": [keys changed by this call],
         "model": str, "input_tokens": int, "output_tokens": int}
    Raises ValueError on empty input (a call with no text cannot be scored —
    that is an 'unavailable' condition the caller handles, not a null score)."""
    if not call_text or not call_text.strip():
        raise ValueError("score_call: empty call_text")
    if client is None:
        from llm_client import LLMClient
        client = LLMClient.from_config("generator")

    component_keys = _component_keys()
    components = {k: {"score": None, "evidence": None} for k in component_keys}
    tok_in = tok_out = 0
    model = None

    # PASS 1 — selection: which components does this call change vs prior_state.
    gate = client.complete(
        messages=build_gate_messages(call_text, deal_context, prior_state),
        system=_get_gate_system_prompt(),
        max_tokens=200,
        temperature=0,
    )
    tok_in += getattr(gate, "input_tokens", 0) or 0
    tok_out += getattr(gate, "output_tokens", 0) or 0
    model = getattr(gate, "model", None)
    advanced = _parse_advanced(gate.text)

    # PASS 2 — cumulative score for only the changed components.
    if advanced:
        score = client.complete(
            messages=build_score_messages(call_text, advanced, deal_context, prior_state),
            system=SCORE_SYSTEM_PROMPT,
            max_tokens=1200,
            temperature=0,
        )
        tok_in += getattr(score, "input_tokens", 0) or 0
        tok_out += getattr(score, "output_tokens", 0) or 0
        model = getattr(score, "model", None) or model
        parsed = parse_call_scores(score.text)
        # Keep only the selected components; a stray extra key from pass 2 is ignored.
        for k in advanced:
            components[k] = parsed[k]

    return {
        "components": components,
        "advanced": advanced,
        "model": model,
        "input_tokens": tok_in,
        "output_tokens": tok_out,
    }


def roll_up(scored_calls):
    """Deal-level roll-up: the most-recent-non-null call score per component.

    scored_calls: iterable of {"call_id", "call_date", "components": {key:{score,evidence}}}.
    Sorted here by call_date ascending; a later call supersedes an earlier one,
    so regression is possible (a champion leaving lowers the score) — there is no
    max() floor. A component null in every call rolls up to null.

    Returns {key: {"score", "evidence", "call_id", "call_date"}} with full
    provenance; score is None (and call_id/date None) if no call scored it.
    """
    component_keys = _component_keys()
    rolled = {k: {"score": None, "evidence": None, "call_id": None, "call_date": None}
              for k in component_keys}
    ordered = sorted(scored_calls, key=lambda r: (r.get("call_date") or ""))
    for row in ordered:
        comps = row.get("components") or {}
        for key in component_keys:
            cell = comps.get(key) or {}
            if cell.get("score") is not None:
                rolled[key] = {
                    "score": cell["score"],
                    "evidence": cell.get("evidence"),
                    "call_id": row.get("call_id"),
                    "call_date": row.get("call_date"),
                }
    return rolled


def rollup_total(rolled):
    """Sum of non-null rolled component scores (the /70 headline). Null
    components contribute nothing."""
    return sum(v["score"] for v in rolled.values() if v.get("score") is not None)


def to_score_row(call_id, deal_id, call_date, result, text_source):
    """Build a call_scores row (matching migration 043 JSONB schema) from a score_call result.

    PHASE 4 PORT: Uses JSONB for component_scores and evidence instead of fixed columns.
    Methodology-agnostic: MEDDICC gets 7 keys, MEDDPIC gets 8 (with paper_process),
    SPICED gets 5, BANT gets 4. Zero schema changes when switching methodologies.
    """
    comps = result["components"]
    component_keys = _component_keys()

    # Build component_scores JSONB: {component_key: score} for non-null scores
    component_scores = {k: comps[k]["score"] for k in component_keys
                       if comps[k]["score"] is not None}

    # Build evidence JSONB: {component_key: evidence_text} for non-null evidence
    evidence = {k: comps[k]["evidence"] for k in component_keys
               if comps[k]["score"] is not None and comps[k]["evidence"]}

    return {
        "call_id": str(call_id),
        "deal_id": str(deal_id) if deal_id else None,
        "call_date": call_date,
        "component_scores": json.dumps(component_scores) if component_scores else None,
        "evidence": json.dumps(evidence) if evidence else None,
        "text_source": text_source,
        "model": result.get("model") or "unknown",
        "scorer_version": SCORER_VERSION,
    }
