# Batch 1: Deal-Level Handlers — COMPLETE

## Summary

Ported 4 deal-level handlers with production fixes in place. All guards pass (11/11 tests).

## Handlers Implemented

### 1. query_deal_health
**Purpose:** Deal health assessment combining MEDDICC scores with activity signals.

**Production Fix:** Originally had char-iteration bug where deal_id filter from threshold scan passed string to `.in_()`, producing `in.(6,0,1,4,...)`. Fixed with explicit list conversion and verification.

**Key Features:**
- Accepts `deal_ids` as list (required) or string (auto-converts)
- Uses `get_components()` for dynamic component enumeration
- Returns health flags for each deal with at-risk/healthy status
- Filters by time window and deal_status

**Test Coverage:** Verifies list usage to prevent char-iteration bug

---

### 2. query_stale_deals
**Purpose:** Identifies deals with no recent activity (calls, updates, or stage movement).

**Key Features:**
- Configurable stale threshold (default: 30 days)
- Checks both deal updates and call activity
- Returns days_stale metric for each stale deal
- Calculates stale percentage across active pipeline

**Test Coverage:** Handles empty results gracefully

---

### 3. query_pre_call_brief
**Purpose:** Pre-call preparation brief showing MEDDICC scores, stage requirements, and recommended questions.

**Configuration:** Reads `stage_component_questions` from `config/coaching_client.yaml` to provide stage-aware coaching guidance.

**Key Features:**
- Shows current MEDDICC scores vs stage requirements
- Identifies component gaps (below threshold for current stage)
- Lists recent call history
- Returns known objections for the company
- Provides recommended questions based on stage and gaps

**Config Added:**
```yaml
# config/coaching_client.yaml
stage_component_questions:
  # Example structure - customize per HubSpot stage IDs
  # discovery:
  #   pain:
  #     - "What's not working with your current process?"
  #     - "What's the cost of the problem?"
```

**Test Coverage:** Verifies coaching_client.yaml structure exists and is read

---

### 4. query_call_quality
**Purpose:** Discovery call quality scores from `call_quality` table (migration 038).

**Scoring Dimensions (1-10 each):**
- Quantification: Did they leave with numbers?
- Incumbent picture: Cost, contract end, what's wrong
- Technical picture: Warehouse, SDK, who runs tests
- Decision process: Who decides, threshold, timeline
- Question quality: Open, one at a time, followed up

**Key Features:**
- Aggregates scores across time window or by rep
- Identifies common anti-patterns (no_followup, pitched_early, etc.)
- Returns empty-table note if feature not enabled
- Uses migration 038 `call_quality` table schema

**Test Coverage:** Verifies migration 038 exists and table is queried

---

## Files Modified

### api/handlers.py
Added 4 new handler functions (lines 966-1422):
- `query_deal_health()` - 90 lines
- `query_stale_deals()` - 75 lines
- `query_pre_call_brief()` - 77 lines
- `query_call_quality()` - 90 lines

### config/coaching_client.yaml
Added `stage_component_questions` structure with example format

### scripts/test_batch1_handlers.py (NEW)
Created comprehensive test suite for batch 1 handlers:
- 4 test functions covering all handlers
- Verifies production fixes (list usage, config reading, table queries)
- Handles empty/missing data gracefully

---

## Production Fixes Applied

All batch 1 handlers follow these fixes:

1. **Char-iteration prevention:** Use `params.get()` and verify list types before `.in_()` filters
2. **Dynamic components:** Use `get_components()` instead of hardcoded component lists
3. **Safe defaults:** Handle missing config keys with `or {}` fallback
4. **Empty data handling:** Return informative messages when tables/results are empty

---

## Test Results

All guards and tests passing:

```
✓ 4/4 router production fixes tests
✓ 1/1 drift guard test
✓ 2/2 stage requirements tests
✓ 4/4 batch 1 handlers tests
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  11/11 TOTAL TESTS PASSING
```

**Router Production Fixes:**
- ✓ Deal ID string not char-iterated
- ✓ Explicit IDs override thread context
- ✓ Below-floor honest miss (no speculation)
- ✓ Multi-deal synthesis not truncated

**Drift Guard:**
- ✓ No hardcoded component lists found

**Stage Requirements:**
- ✓ MEDDPICC paper_process in stage requirements
- ✓ Unmapped component key fails loudly

**Batch 1 Handlers:**
- ✓ query_deal_health accepts deal_ids as list
- ✓ query_stale_deals handles empty results
- ✓ query_pre_call_brief reads coaching config
- ✓ query_call_quality uses migration 038

---

## Next Steps

Ready for Batch 2 (Rep and Team handlers):
- query_rep_pipeline
- query_rep_attainment
- query_team_leaderboard
- query_coaching_priorities

Batch 3 will cover SDR handlers + query_pipeline_movement.
