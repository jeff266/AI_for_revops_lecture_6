# Phase 4: Port Session Work - Implementation Plan

**Status:** Ready to execute
**Prerequisites:** ✅ Phases 1-3 complete, JSONB pattern decided, 28 files inventoried

---

## Execution Sequence (4a → 4d)

### 4a. Schema - Create call_scores Migration

**File:** `scripts/migrations/043_add_call_scores.sql`

**CRITICAL: Use JSONB pattern, NOT fixed columns**

```sql
CREATE TABLE IF NOT EXISTS call_scores (
  call_id                  TEXT PRIMARY KEY REFERENCES calls(call_id) ON DELETE CASCADE,
  deal_id                  TEXT,
  call_date                DATE,

  -- JSONB, not fixed columns. Methodology-agnostic.
  component_scores         JSONB,  -- {component_key: score}
  evidence                 JSONB,  -- {component_key: evidence_text}

  text_source              TEXT NOT NULL CHECK (text_source IN ('transcript', 'summary')),
  model                    TEXT NOT NULL,
  scorer_version           TEXT NOT NULL,
  scored_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_call_scores_deal_date
  ON call_scores(deal_id, call_date);

CREATE INDEX IF NOT EXISTS idx_call_scores_scorer_version
  ON call_scores(scorer_version);
```

**Why JSONB:** GrowthBook's migration 043 has fixed columns (`metrics_score`, `economic_buyer_score`, etc.) that defeat methodology switching. A MEDDPICC client needs `paper_process_score`; SPICED needs entirely different columns. The template's `analyses.component_scores` already uses JSONB (migration 003). One pattern throughout.

**Porting Note:** GrowthBook's migration uses fixed columns because that code predates Phase 1. Port the table structure, replace column definitions with JSONB.

---

### 4b. Progressive Scoring Trio

Port and rewire these three files in order:

**1. `scripts/call_scorer.py`**
- **GrowthBook line 29-37:** Hardcoded `COMPONENTS = [("Metrics", "metrics"), ...]`
- **Rewire to:** `COMPONENTS = [(label, component_key(label)) for label in get_components()]`
- **Test signature:** `_PIN_COMPONENTS` comment on line 27 says "identical to meddicc_agent._PIN_COMPONENTS" — confirms the duplication

**2. `scripts/rollup_deal_scores.py`**
- Reads `call_scores` table and computes deal-level rollup (most-recent-non-null per component)
- **Rewire:** Replace any hardcoded component iteration with `get_components()` + `component_key()`
- **Schema dependency:** Expects `component_scores JSONB` and `evidence JSONB` (from 4a)

**3. Update `scripts/meddicc_agent.py`**
- **GrowthBook line 40-48:** `_PIN_COMPONENTS` list
- **Rewire to:** `get_components()` + `component_key()`
- **Design change:** Template's meddicc_agent does batch scoring (score all calls for a deal in one pass). GrowthBook's call_scorer does progressive scoring (score each call once at ingest). Progressive is the better design. After porting call_scorer + rollup, the template can retire batch scoring or keep both paths.

---

### 4b Acceptance Test (STOP HERE IF IT FAILS)

**Test:**
1. Set `sales_methodology: "MEDDPICC"` in `config/client.yaml`
2. Run `scripts/call_scorer.py` on a sample call
3. Check `call_scores.component_scores` JSONB output
4. **Expected:** 8 components including `{"paper_process": N, ...}`
5. **No Python edited** to make it happen

**If this fails, stop.** The rest of Phase 4 depends on get_components() + component_key() working end-to-end. Debug before proceeding to 4c/4d.

---

### 4c. Substrate Files

Port supporting files that the progressive trio depends on:

**Source: `/Users/jeffignacio/MEDDICC-agent`**

- `scripts/point_in_time.py` - deal snapshot logic
- `scripts/transcript_store.py` - call transcript storage
- Migrations for `call_transcripts` (041), `deals_snapshot` fields

**Rewiring Rule:** Each file gets `from utils import get_components, component_key` at import, then replaces hardcoded lists with dynamic calls. **Never port a hardcoded list as-is to "clean up later."** Rewire on the way in.

**Three GrowthBook Comment Strings to Fix:**
1. `transcript_store.py:128` - "Not in GrowthBook's priority"
2. `point_in_time.py:62` - "HubSpot sends stage ids as"
3. `point_in_time.py:389` - "the GrowthBook rule"

Replace with generic equivalents or remove client-specific references.

**Fix PRs to Port (#17-24 from GrowthBook):**
- `_coerce_in_values` - entity-scope precedence fix
- Multi-company resolution
- Confidence floor (low-assessed answers don't ship)
- Empty-result honesty (null when call says nothing)
- Evidence contract (per-component evidence in scoring)
- Unread/red distinction (never-discussed 0 ≠ red flag)
- Synthesis house style (emoji bands, one em dash per sentence)

---

### 4d. Handlers & Analytics

Rewire remaining production files:

**API Layer (4 files):**
- `api/handlers.py` - GrowthBook line 2113: `COMPONENTS = {...}` dict
- `api/router.py`
- `api/field_semantics.py`
- `api/stage_requirements.py`

**Analytics (2 files):**
- `scripts/analytics/slip_diagnosis.py`
- `scripts/analytics/stage_score_hygiene.py`

**Core Scripts (5 files):**
- `scripts/context_builder.py` - has `COMPONENT_DESCRIPTIONS` dict (lines 16-36)
- `scripts/hubspot_deals.py`
- `scripts/run_nightly.py`
- `scripts/discover_properties.py`
- `scripts/setup_hubspot_properties.py` - line 14: `COMPONENTS = [(key, label), ...]`

**Total:** 14 production files

**Rewiring Pattern:**
```python
# Before (hardcoded)
COMPONENTS = [
    ("Metrics", "metrics"),
    ("Economic Buyer", "economic_buyer"),
    ...
]

# After (dynamic)
from utils import get_components, component_key

components = get_components()
component_map = {c: component_key(c) for c in components}
```

For `COMPONENT_DESCRIPTIONS` in context_builder.py: Keep the dict (it's universal descriptions for all methodologies), but iterate over `get_components()` to select which ones to use.

---

## Files Inventoried

**Production (14 files - must rewire):**
1. api/field_semantics.py
2. api/handlers.py
3. api/router.py
4. api/stage_requirements.py
5. scripts/analytics/slip_diagnosis.py
6. scripts/analytics/stage_score_hygiene.py
7. scripts/call_scorer.py
8. scripts/context_builder.py
9. scripts/discover_properties.py
10. scripts/hubspot_deals.py
11. scripts/meddicc_agent.py
12. scripts/rollup_deal_scores.py
13. scripts/run_nightly.py
14. scripts/setup_hubspot_properties.py

**Test/Eval/Diagnostic (14 files - can stay hardcoded):**
- All `eval_*`, `test_*`, `diag_*`, `phase*`, `characterize*`, `verify*` files
- Test fixtures with hardcoded components are fine

---

## CRM Adapter Decision

**Port through the CRM adapter (`adapters/crm/hubspot.py`).**

The template already has production files using the adapter: `discover_stages.py`, `run_nightly.py`, and others import `HubSpotDealsClient`. Porting HubSpot-direct would introduce a second pattern into a repo with a working one — exactly the drift Phases 1-3 exist to prevent.

The interface already fits: `write_analysis(deal_id, scores, ...)` takes scores with "one <component_key>_score per configured component" (lines 416-428), which is methodology-aware and consistent with `get_components()`.

**Two-Layer Storage Pattern (CRM + Storage):**

1. **CRM writes (HubSpot):** Individual deal properties
   - `meddicc_champion_score`, `meddicc_economic_buyer_score`, etc.
   - Real HubSpot custom fields (one per component)
   - Written via `HubSpotDealsClient.write_analysis()`
   - Lines 444-447: Checks `if 'Champion' in components` before writing

2. **Storage writes (Supabase):** JSONB aggregates
   - `analyses.component_scores` JSONB: `{component_key: score}`
   - `call_scores.component_scores` JSONB: `{component_key: score}` (Phase 4a)
   - `call_scores.evidence` JSONB: `{component_key: evidence_text}` (Phase 4a)
   - Written via `SupabaseWriter.insert_analysis()` and new `write_call_scores()`
   - Lives in `adapters/storage/supabase.py`, NOT the CRM adapter

**Why this split:**
- HubSpot needs real properties for filters, workflows, UI (CRM layer)
- Supabase stores methodology-agnostic history for queries (storage layer)
- Progressive scorer writes to BOTH: HubSpot deal rollup + Supabase call_scores

**Action for Phase 4:**
- All HubSpot operations route through `HubSpotDealsClient`
- All Supabase operations route through `SupabaseWriter`
- Add `write_call_scores()` method to `adapters/storage/supabase.py` for progressive scoring

---

## Critical Rules

1. **JSONB everywhere for components** - `call_scores.component_scores`, `call_scores.evidence`, `analyses.component_scores`. Never fixed columns.

2. **Rewire on the way in** - Import `get_components() + component_key()`, replace hardcoded lists during the port. Never "port then clean up."

3. **4b acceptance test gates 4c/4d** - If MEDDPICC doesn't return 8 components with paper_process, stop. The system is broken.

4. **Component descriptions are universal** - `context_builder.py`'s `COMPONENT_DESCRIPTIONS` dict covers all methodologies. Keep it, iterate over `get_components()` to filter.

5. **Two-layer storage** - CRM writes (individual HubSpot properties) + Storage writes (JSONB in Supabase). Both layers required, different purposes.

---

## Source Repository

**GrowthBook Production:** `/Users/jeffignacio/MEDDICC-agent`
**Template (Destination):** `/Users/jeffignacio/GrowthBook/AI_for_revops_lecture_6`

GrowthBook repo is read-only for this port. After pull on 2026-08-24, it has:
- Latest progressive scoring work (call_scorer, rollup_deal_scores)
- 28 files with component references (14 production, 14 test/diagnostic)
- Commit `ecd7d10`: "Synthesis house style: emoji bands, one em dash per sentence"

---

## Success Criteria

Phase 4 is complete when:

1. ✅ Migration 043 created with JSONB (not fixed columns)
2. ✅ Progressive trio ported and rewired (call_scorer, rollup, meddicc_agent verified clean)
3. ✅ MEDDPICC acceptance test PASSED
   - **Fix applied:** Renamed dict key from `'MEDDPIC'` to `'MEDDPICC'`
   - **Loud failure added:** get_components() now raises ValueError on unrecognized methodology
   - **Test result:** MEDDPICC returns 8 components with paper_process, MEDDICC returns 7
   - **No Python edited** to switch between methodologies
4. ⏳ All 14 production files rewired to `get_components()` + `component_key()`
5. ⏳ Three GrowthBook comment strings replaced
6. ✅ CRM adapter touchpoints documented (Phase 4 planning)
7. ⏳ Fix PRs #17-24 ported

**Phase 5 verification fixes applied:**
- ✅ Transition count corrected: N open stages = N transitions (including terminal)
- ✅ .forbidden_names.example added with .gitignore entries

**Next:** Unblock 4b (fix MEDDPIC/MEDDPICC mismatch), then 4c (substrate files), 4d (rewire 14 files), Phase 5 already complete, Phase 6 (prove it with fictional client)
