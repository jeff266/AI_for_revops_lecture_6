# Batch 3: SDR + Pipeline Movement Handlers — COMPLETE

## Summary

**CORRECTED** batch 3 after drift. Ported 4 correct handlers from MEDDICC-agent with all helpers and production fixes in place. All guards pass (18/18 tests).

## Critical Correction

**Drift Identified:**
- Initially invented 4 different handlers (query_sdr_activity, query_sdr_performance, query_team_sdr_metrics, query_pipeline_movement reading waterfall_weekly)
- User caught the drift and instructed to port from source: `/Users/jeffignacio/MEDDICC-agent/api/handlers.py`

**Root Cause:**
- Built from description instead of reading available source code
- Waterfall_weekly table exists but has no writer (would query empty table)

**Correction:**
- Removed all 4 invented handlers (lines 1739-2053, ~309 lines)
- Ported 4 correct handlers by name from MEDDICC-agent
- Added _resolve_owner_email helper and all 15 pipeline movement helpers

## Handlers Implemented

### 1. query_sdr_pipeline_sourced
**Purpose:** SDR-sourced pipeline analysis — which SDRs are generating qualified pipeline.

**Production Fix:** Uses `("__not_null__", "sdr_owner_email")` filter. The old `"not.is"` operator raised `AttributeError` when `select_all` tried `getattr(q, "not.is")`. The correct operator is `"__not_null__"`.

**Key Features:**
- Reads deals table for SDR attribution
- Aggregates by SDR (deal_count, total_value, total_arr)
- Returns top SDRs by pipeline value
- Uses __not_null__ operator (not "not.is")

**Test Coverage:** Verifies correct filter operator usage

---

### 2. query_sdr_metrics
**Purpose:** Individual SDR activity metrics from sdr_metrics, sdr_users, and meetings tables.

**Key Features:**
- Queries 3 tables: sdr_metrics, sdr_users, meetings
- Aggregates call/email metrics across tools (Apollo, Salesloft, Aircall)
- Returns calls_summary and meetings_summary
- Uses _resolve_owner_email for name resolution

**Test Coverage:** Verifies all 3 tables queried

---

### 3. query_sdr_leaderboard
**Purpose:** Team leaderboard ranking SDRs by activity and performance.

**Key Features:**
- Aggregates by (tool, tool_user_id) unique key
- Ranks by calls, emails, or meetings metric
- Supports multiple SDR tools per user
- Returns leaderboard sorted by selected metric

**Test Coverage:** Verifies aggregation by user key

---

### 4. query_pipeline_movement
**Purpose:** Pipeline movement / composition / deal-level changes / coverage curve.

**CRITICAL:** Reads from `deals_snapshot` table (point-in-time substrate), NOT `waterfall_weekly` (which has no writer in template).

**5 Views:**
1. **movement** - Stage-by-stage movement (new, entered, exited)
2. **composition** - Weekly stage composition over time
3. **deal_changes** - Individual deal movements with direction
4. **curve** - Coverage curve (deal count over time)
5. **stage_deals** - Drill-down to specific stage

**Key Features:**
- COUNTS ONLY — never dollars (basis='count' explicit)
- Scope statement explains what's counted (all open deals by default, or current_quarter for CRM reconciliation)
- Confidence tracking (exact, pre_history, no_history)
- Entity-bearing rows for follow-up questions
- 15 helper functions (_pm_*)

**Test Coverage:** Verifies reads deals_snapshot (not waterfall_weekly), returns basis='count'

---

## Helper Functions Added

### _resolve_owner_email (line 39)
- Resolves rep name or email to email address
- Tries email keys first, then name resolution via user_personas
- Returns (email_or_None, note_or_None)
- Used by: query_sdr_pipeline_sourced, query_sdr_metrics

### Pipeline Movement Helpers (15 functions)
All prefixed with `_pm_*` to namespace pipeline movement utilities:

1. **_pm_load_scoping()** - Import shared analytics-scoping functions
2. **_pm_current_quarter_label()** - Current fiscal quarter label
3. **_pm_stage_name()** - Stage ID → stage name (degrades gracefully)
4. **_pm_stage_order()** - Stage order for sorting
5. **_pm_in_scope()** - Analytics scope filter (null-stage counted, closed dropped)
6. **_pm_confidence_mix()** - Aggregate backfill confidence levels
7. **_pm_latest_row_per_deal()** - Deduplicate to 1 row per deal per date
8. **_pm_by_date()** - Group rows by snapshot_date
9. **_pm_stage_sets()** - Build stage → deal sets for one date
10. **_pm_company_map()** - Fetch deal_id → company_name mapping
11. **_pm_deal_rows()** - Entity rows for thread context
12. **_pm_view_movement()** - Movement view (prior vs current)
13. **_pm_view_composition()** - Composition grid
14. **_pm_left_reason()** - Why a deal left pipeline (won/lost/excluded)
15. **_pm_view_deal_changes()** - Individual deal changes
16. **_pm_view_curve()** - Coverage curve

**Constants:**
- `_PM_SNAPSHOT_COLUMNS` - Column list (deal_value intentionally absent)
- `_PM_CONFIDENCE_KEYS` - Confidence levels
- `_PM_VIEWS` - Valid view names

---

## Files Modified

### api/handlers.py
- **Removed:** 4 invented handlers (lines 1739-2053, ~309 lines)
- **Added:** _resolve_owner_email helper (54 lines, line 39)
- **Added:** 4 correct batch 3 handlers (~850 lines):
  - query_sdr_pipeline_sourced (72 lines)
  - query_sdr_metrics (117 lines)
  - query_sdr_leaderboard (79 lines)
  - query_pipeline_movement (540 lines + 15 helpers)

### scripts/test_no_handler_raises.py
Updated handler list (lines 84-87):
- Replaced: query_sdr_activity, query_sdr_performance, query_team_sdr_metrics
- With: query_sdr_pipeline_sourced, query_sdr_metrics, query_sdr_leaderboard
- Kept: query_pipeline_movement (corrected implementation)

### scripts/test_batch3_handlers.py (COMPLETELY REWRITTEN)
New test suite for corrected batch 3 handlers:
- 4 test functions covering all handlers
- Verifies "__not_null__" filter fix (not "not.is")
- Verifies deals_snapshot usage (not waterfall_weekly)
- Verifies COUNTS ONLY (basis='count')
- Verifies multi-table queries (sdr_metrics + sdr_users + meetings)

---

## Production Fixes Applied

All batch 3 handlers follow these fixes:

1. **"not.is" operator bug:** Use `("__not_null__", column)` not `("not.is", column)` — the latter raises AttributeError
2. **Name resolution:** Use `_resolve_owner_email()` to accept names or emails
3. **Safe defaults:** Handle missing config/data gracefully
4. **Empty data handling:** Return informative messages when tables empty
5. **Counts only:** query_pipeline_movement never selects or emits deal_value

---

## Test Results

All guards and tests passing:

```
✓ 30/30 handler params safety tests
✓ 4/4 router production fixes tests
✓ 2/2 stage requirements tests
✓ 4/4 batch 1 handlers tests
✓ 4/4 batch 2 handlers tests
✓ 4/4 batch 3 handlers tests
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  48/48 TOTAL TESTS PASSING
```

**Batch 3 Specific Tests:**
- ✓ query_sdr_pipeline_sourced uses __not_null__ operator
- ✓ query_sdr_metrics queries sdr_metrics + sdr_users + meetings
- ✓ query_sdr_leaderboard aggregates by user key
- ✓ query_pipeline_movement reads deals_snapshot (not waterfall_weekly)

---

## Lessons Learned

### Process Error: Invented from Description
**What happened:** User said "SDR + pipeline movement handlers" without listing exact names. I invented 4 different handlers instead of reading the available source.

**User feedback:**
> "The drift happened because I said 'SDR + pipeline movement handlers' without listing exact names. But the deeper issue is that you built from a description instead of reading the source — and the source was available."

**Correct process going forward:**
1. **Read the source first** (MEDDICC-agent/api/handlers.py)
2. **Port it** (copy implementation, adapt imports)
3. **Then adapt** (fix bugs, update for template differences)

**Never:** Invent handlers from descriptions when source code is available.

### Technical Discovery: waterfall_weekly Has No Writer
During investigation, discovered that `waterfall_weekly` table exists (migration 012) but nothing writes to it in the template repo. The correct handler reads `deals_snapshot` (migration 005) for point-in-time pipeline reconstruction.

**Decision:** Leave waterfall_weekly table in place but drop the invented handler that reads it. The correct implementation uses deals_snapshot.

---

## Next Steps

**Batch 3 complete.** All 12 handlers now ported from MEDDICC-agent:
- Batch 1: 4 deal-level handlers ✓
- Batch 2: 4 rep/team handlers ✓
- Batch 3: 4 SDR/pipeline handlers ✓

**Pending:** Router integration
- Intent classification (classify questions → handler names)
- Synthesis prompts (format handler outputs)
- Entity extraction (save deal_ids, company_names for follow-ups)

User acknowledged router integration as "next after batch 3 lands."
