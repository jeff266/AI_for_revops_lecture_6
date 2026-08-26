# ETL Reconciliation - Diff Report

**Comparing:** Template vs GrowthBook `/Users/jeffignacio/MEDDICC-agent`

---

## etl_calls.py

**File sizes:**
- Template: 675 lines
- GrowthBook: 935 lines
- Delta: **260 lines missing** (27% smaller)

### Critical Missing Features

#### 1. ❌ Fireflies Transcript Fetch (BLOCKING)

**Status:** Template CANNOT populate call_transcripts table

**What's missing:**
- Template only fetches summaries via `adapter.get_transcripts(limit=50, skip=skip)`
- GrowthBook fetches full utterance-level transcripts via `fetch_utterances()` from `transcript_store.py`
- This is the primary blocker - migration 030 created call_transcripts table but ETL can't populate it

**Impact:**
- call_transcripts table remains empty
- No transcript metrics (talk_time, question_count, monologue detection)
- Downstream coaching features blocked

**GrowthBook code (lines 885-912):**
```python
try:
    from transcript_store import fetch_utterances, build_transcript_row
    clients, rows, deferred = {}, [], 0
    for slug, data in calls_by_company.items():
        for c in data.get('calls', []):
            cid, src = str(c.get('id') or ''), c.get('source') or ''
            if not cid or not src:
                continue
            utts, err = fetch_utterances(src, cid, clients)
            if err:
                # Transient fetch failure - don't write a row; the
                # call is left absent so the next nightly re-attempts
                deferred += 1
                continue
            rows.append(build_transcript_row(src, cid, utts, error=None,
                                            call_date=c.get('date')))
    stored = sb.bulk_upsert_transcripts(rows)
    have = sum(1 for r in rows if r.get('transcript'))
    print(f"  ✓ Supabase: {stored} transcripts upserted "
          f"({have} with text, {stored - have} unavailable, {deferred} deferred)")
except Exception as te:
    print(f"  ⚠️  Transcript persist failed (calls unaffected): {te}")
```

**Template code (lines 640-656):**
```python
# Write to Supabase if configured
if os.getenv('SUPABASE_URL'):
    print(f"\n📤 Writing to Supabase...")
    try:
        sb = get_storage_adapter()
        total = 0
        for slug, data in calls_by_company.items():
            calls = data.get('calls', [])
            if calls:
                for c in calls:
                    c['company_slug'] = slug
                n = sb.bulk_upsert_calls(calls, data['company'])
                total += n
        print(f"  ✓ Supabase: {total} calls upserted")
    except Exception as e:
        print(f"  ⚠️  Supabase write failed: {e}")
```

**Missing:**
- No `transcript_store` import
- No `fetch_utterances()` call
- No `build_transcript_row()` call
- No `sb.bulk_upsert_transcripts()` call
- No deferred retry logic for transient failures

#### 2. ❌ Rate-Limit Backoff on GraphQL Body Errors

**Status:** Template's retry logic never fires

**Problem:**
- Fireflies returns throttling in GraphQL response **body**, not HTTP status
- Template only catches HTTP exceptions
- GrowthBook: "This failed 1,920 of 2,189 calls before it was caught"

**Impact:** 88% failure rate on throttling (1920/2189)

**What's needed:**
- Check response body for rate limit messages
- Implement exponential backoff
- Retry on body-level throttling, not just HTTP 429

**Missing from template:**
- No GraphQL error parsing
- No body-level throttle detection
- No sleep/retry loop

**Note:** This logic may be in `fireflies_client.py` or adapter layer, not directly in etl_calls.py. Need to check adapter implementation.

#### 3. ❌ Source-Priority Dedup

**Status:** Template uses single source only

**What's missing:**
- Template: `call_tools.primary` selects ONE adapter
- GrowthBook: Fetches from ALL configured sources, deduplicates by priority

**GrowthBook code (lines 180-250):**
```python
# Get all configured call sources in priority order
all_calls = []
for source_name in get_call_sources():  # e.g., ['fireflies', 'apollo']
    ...fetch from source...
    all_calls.extend(calls_from_this_source)

# Deduplicate by source priority
deduped = deduplicate_calls_by_source_priority(all_calls)
print(f"   After dedup: {len(deduped)} calls")
```

**Template code:**
- Only calls single adapter: `adapter = get_call_adapter()` (singular)
- No multi-source fetch
- No dedup logic

**Priority order (GrowthBook):**
```python
source_priority = {
    "fireflies": 0,   # highest priority (rich transcripts)
    "gong": 1,
    "apollo": 2,       # lowest priority (video meetings, weaker summaries)
    "unknown": 3
}
```

**Real use case:** Fireflies records Zoom calls + Apollo records video meetings
- Same call appears in both sources
- Fireflies has better transcript → prioritize it
- Without dedup: duplicate calls in cache

#### 4. Missing Imports/Dependencies

**Template lacks:**
```python
import logging
from datetime import timezone as _stdlib_tz
from sdr_utils import utc_to_reporting_date
from llm_client import LLMClient
from transcript_store import fetch_utterances, build_transcript_row
```

**Template has:**
```python
from utils import slugify
from adapters import get_call_adapter, get_storage_adapter
```

**Issues:**
- No logging configured (GrowthBook has logger.debug/info/warning)
- No timezone handling utilities
- No LLM client for Apollo summarization
- No transcript store module

### Minor Differences

**GrowthBook enhancements:**
- Better error messages with context
- Logging at DEBUG level for diagnostics
- More robust domain filtering (excludes `resource.calendar.google.com`, `group.calendar.google.com`)
- Apollo summarization with fallback handling

**Template missing:**
- Diagnostic logging
- Extended Google Calendar resource filtering
- Robust Apollo transcript summarization error handling

---

## etl_deals.py

**File sizes:**
- Template: 782 lines
- GrowthBook: 865 lines
- Delta: **83 lines missing** (9% smaller)

### Critical Checks Required

#### 1. ✅ Forecast Fields Present

Both have:
- `fiscal_quarter`
- `week_of_quarter`
- `forecast_category`

**Verification needed:**
- Are these populated correctly?
- Do they use point-in-time logic or current state?

#### 2. ⚠️ Snapshot Inclusion Rule

**The critical rule:** A deal belongs in snapshot for date D only if:
1. Created by date D (deal exists)
2. NOT terminal before date D (still open on that date)

**Without this rule:**
- Every deal appears in every snapshot forever
- Closed deals from months ago inflate denominators
- Week-3 coverage shows 914 deals instead of ~221
- Produces 14.96x coverage (looks plausible, completely wrong)

**Need to verify in template:**
```python
# Pseudo-code of correct inclusion
for deal in all_deals:
    if deal.created_date <= snapshot_date:
        if not deal_was_terminal_before(snapshot_date):
            include_in_snapshot(deal, snapshot_date)
```

**Anti-pattern to check for:**
```python
# WRONG: includes all deals regardless of lifecycle
for deal in all_deals:
    snapshot_row = {
        'deal_id': deal.id,
        'snapshot_date': snapshot_date,
        'stage': deal.current_stage,  # ← reading CURRENT state
        ...
    }
```

#### 3. ⚠️ Point-in-Time Field Population

**The invariant:** Every field in deals_snapshot is the value **as of snapshot_date**, never current state.

**Fields that commonly read current state incorrectly:**
- `dealstage` - must read stage history, not deal.stage
- `amount` - must read value history, not deal.amount
- `closedate` - must read close date history
- `hubspot_owner_id` - must read owner history
- `deal_status` - must be derived from stage as-of date

**Correct pattern (from GrowthBook's point_in_time.py):**
```python
def get_field_at_date(deal_id, field_name, as_of_date):
    """Read field value as of historical date."""
    # Query property history for this field
    # Return value at or before as_of_date
    # Return NULL if no history (never guess/default)
```

**Anti-pattern:**
```python
# WRONG: Reading current state
snapshot_row = {
    'deal_id': deal['id'],
    'stage': deal['dealstage'],           # ← current stage, not historical
    'amount': deal['amount'],             # ← current amount
    'owner': deal['hubspot_owner_id'],   # ← current owner
}
```

**Need to check:**
- Does template have `point_in_time.py` module? **NO** (file doesn't exist)
- Does template use `get_field_at_date()` helper? **UNKNOWN** (need to read etl_deals.py)
- Does template join to live deals table for historical rows? **MUST CHECK**

### Missing Module: point_in_time.py

**Status:** File does not exist in template

**What it does:**
- `get_field_at_date(deal_id, field, as_of_date)` - read property history
- `get_stage_at_date(deal_id, as_of_date)` - read stage history
- `deal_was_terminal_before(deal_id, date)` - inclusion rule check
- Handles NULL correctly (no history = NULL, not a default)
- Handles backward-moving stages (deal regressing)

**Impact of missing:**
- Template CANNOT do point-in-time correctly
- Must be reading current state for historical snapshots
- All historical analyses wrong

---

## Summary of Critical Gaps

### etl_calls.py - 4 blocking issues

1. **No transcript fetch** - call_transcripts table can't be populated ⚠️ BLOCKING
2. **No rate-limit backoff** - 88% failure rate on throttling ⚠️ HIGH IMPACT
3. **No multi-source dedup** - single source only ⚠️ FEATURE GAP
4. **Missing transcript_store module** - dependency doesn't exist ⚠️ BLOCKING

### etl_deals.py - 2 critical unknowns

1. **Snapshot inclusion rule** - need to verify ⚠️ CRITICAL
2. **Point-in-time vs current state** - likely reading current ⚠️ CRITICAL
3. **Missing point_in_time.py module** - doesn't exist ⚠️ BLOCKING

---

## Verification Steps Needed

Before porting fixes, verify in template's etl_deals.py:

### Check 1: Inclusion Rule
```bash
grep -A20 "def.*snapshot\|snapshot.*write" scripts/etl_deals.py
```
Look for: Deal filtering by created_date and terminal status

### Check 2: Point-in-Time vs Current
```bash
grep "deal\[.*stage\|deal\[.*amount\|\.stage\|\.amount" scripts/etl_deals.py
```
Look for: Direct field access (current state) vs history reads

### Check 3: Forecast Field Population
```bash
grep -B5 -A5 "fiscal_quarter\|week_of_quarter" scripts/etl_deals.py
```
Look for: How these are computed and when

---

## Next Steps

**DO NOT PORT YET**

1. Read template's etl_deals.py lines with snapshot writing
2. Verify inclusion rule implementation
3. Verify point-in-time field reading
4. Report findings
5. THEN port fixes

**Porting order (after verification):**
1. point_in_time.py (substrate - needed first)
2. transcript_store.py (substrate - needed for etl_calls)
3. etl_calls.py fixes (depends on transcript_store)
4. etl_deals.py fixes (depends on point_in_time)
