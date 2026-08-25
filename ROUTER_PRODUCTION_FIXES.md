# Router.py Production Fixes to Port

**Source:** GrowthBook MEDDICC-agent (2302 lines)
**Target:** Template (1357 lines)
**Delta:** 945 lines

---

## 1. _coerce_in_values - Deal ID String Iteration Bug

**Location:** `supabase_client.py` / `tools.py`

**Bug:** A deal_id string iterated character-by-character produced `in.(6,0,1,4,...)`

**Fix:** Coerce string values to list before passing to `.in_()`:
```python
def _coerce_in_values(val):
    """['60148'] OK, '60148' iterated to ['6','0','1','4','8'] NOT OK."""
    if isinstance(val, str):
        if ',' in val:
            return [v.strip() for v in val.split(',')]
        return [val]
    if isinstance(val, list):
        return val
    return [val]
```

**Usage in tools.py:**
```python
# Line ~79
processed_filters.append(("in_", col, _coerce_in_values(val)))
```

---

## 2. Current-Message Entities Override Thread Context

**Location:** `router.py` entity scope resolution

**Bug:** A cached deal_id hijacked every follow-up in a thread, including ones with explicit IDs pasted

**Fix:** Check if current message names its own entities before using thread context:
```python
def extract_explicit_deal_ids(question: str) -> list:
    """Deal IDs mentioned in THIS message (overrides thread context)."""
    return re.findall(r'\b\d{5,}\b', question)

def message_names_known_company(question: str, sb) -> bool:
    """Does THIS message name a company we have data for?"""
    # Check against known companies in database

# In route_question:
explicit_deal_ids = extract_explicit_deal_ids(question)
msg_names_company = message_names_known_company(question, sb)
msg_has_own_entities = bool(explicit_deal_ids or msg_names_company)

if should_use_entity_scope() and not msg_has_own_entities:
    # Only use thread context if current message has NO explicit entities
    params["deal_ids"] = entity_params["deal_ids"]
    params["company_names"] = entity_params["company_names"]
```

---

## 3. Multi-Company Resolution

**Bug:** query_rubric_scores_bulk took one company, so four named accounts extracted to none

**Fix:** Support multiple company names in extraction and resolution

---

## 4. Empty-Result Honesty

**Bug:** Synthesis invented three causes for a broken query rather than saying what it looked for

**Fix:** `_result_summary()` and `_honest_miss()` functions:
```python
def _result_summary(tool_results: dict) -> str:
    """Factual, count-only description. States ONLY what system has, never a guessed cause."""
    if not tool_results:
        return "no data came back"
    for key in ("scores", "rows", "deals", "narratives", "analyses"):
        v = tool_results.get(key)
        if isinstance(v, list):
            return f"{len(v)} row{'s' if len(v) != 1 else ''} came back" if v else "no matching rows came back"
    return "no matching data came back"

def _honest_miss(handler_name: str, tool_results: dict) -> str:
    """Only facts the system has. No speculation about WHY."""
    return (
        "I couldn't answer that reliably — my own check on the drafted answer "
        f"came back below the confidence floor. (I routed to `{handler_name}` "
        f"and {_result_summary(tool_results)}.) A confident wrong answer is "
        "worse than telling you I missed."
    )
```

---

## 5. Confidence Floor

**Bug:** Assessor scores of 0.00 and 0.50 shipped unchanged

**Fix:** `ASSESS_CORRECTNESS_FLOOR` with below-floor blocking:
```python
_DEFAULT_ASSESS_FLOOR = 0.30
ASSESS_CORRECTNESS_FLOOR = float(os.getenv("ASSESS_CORRECTNESS_FLOOR", _DEFAULT_ASSESS_FLOOR))

def _below_floor(assessment: dict, floor: float = None) -> bool:
    """Should this answer be blocked as low-confidence?"""
    floor = ASSESS_CORRECTNESS_FLOOR if floor is None else floor
    a = assessment or {}
    if a.get("skipped") or a.get("issue") == "data_gap":
        return False  # Don't block skipped assessments or acknowledged gaps
    score = a.get("score", 0.5)
    return isinstance(score, (int, float)) and score < floor

# In route_question after assessment:
if _below_floor(assessment):
    return _honest_miss(handler_name, tool_results)
```

---

## 6. Bounded Fallback Columns

**Bug:** 180KB dumped into synthesis

**Fix:** `SYNTH_PAYLOAD_CHARS` limit:
```python
SYNTH_PAYLOAD_CHARS = 20000  # Multi-deal case sized

# Before synthesis:
tool_results_str = json.dumps(tool_results, default=str)
if len(tool_results_str) > SYNTH_PAYLOAD_CHARS:
    tool_results_str = tool_results_str[:SYNTH_PAYLOAD_CHARS] + "... (truncated)"
```

---

## 7. Synthesis Output Ceiling

**Bug:** A two-deal answer truncated mid-sentence

**Fix:** Increased max_tokens with truncation detection:
```python
SYNTH_MAX_TOKENS = 4000
SYNTH_MAX_TOKENS_RETRY = 8000

def _looks_truncated(text: str) -> bool:
    """Did answer get cut off (max_tokens ceiling)?"""
    _TERMINAL_ENDINGS = ".!?)\"'`]}…"
    t = (text or "").rstrip().rstrip("*_`> ").rstrip()
    if not t:
        return False
    return t[-1] not in _TERMINAL_ENDINGS

# In synthesis with retry:
answer = client.messages(..., max_tokens=SYNTH_MAX_TOKENS)
if _looks_truncated(answer):
    answer = client.messages(..., max_tokens=SYNTH_MAX_TOKENS_RETRY)
```

---

## Summary

All seven fixes address live production failures. Port these BEFORE handlers to ensure handlers inherit the robust foundation.

**New functions to add to router.py:**
- `extract_explicit_deal_ids()`
- `message_names_known_company()`
- `_result_summary()`
- `_below_floor()`
- `_honest_miss()`
- `_looks_truncated()`

**New constants:**
- `SYNTH_MAX_TOKENS`, `SYNTH_MAX_TOKENS_RETRY`
- `SYNTH_PAYLOAD_CHARS`
- `ASSESS_CORRECTNESS_FLOOR`
- `_TERMINAL_ENDINGS`

**Imports to add:**
- `import re`
- `from supabase_client import _coerce_in_values`

**Files to update:**
- `api/router.py` (all 7 fixes)
- `api/tools.py` (_coerce_in_values usage)
- `scripts/supabase_client.py` (_coerce_in_values definition)
