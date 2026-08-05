# HubSpot Deal Index Setup Guide

The CSV → cache → delta pattern has been implemented for HubSpot deals, matching the pattern used for Fireflies and Apollo calls.

## What Was Implemented

### ✅ TASK 1: scripts/etl_deals.py
- Reads `data/hubspot_deals.csv` (HubSpot export)
- Builds `memory/deals/index.json` with filtered active deals
- **Filters:**
  - Excludes Renewal pipeline
  - Excludes Meeting Set stage (`appointmentscheduled`)
  - Excludes closed stages (closedwon, closedlost, renewal closed stages)
  - Excludes deals without company names
- Generates company slugs for cache matching

### ✅ TASK 2: scripts/github_memory.py
- Added `deals_dir` to memory directories
- Added `load_deals_index()` method
- Added `get_active_deals_from_index()` method

### ✅ TASK 3: scripts/run_nightly.py
- Replaced `hubspot.get_active_deals()` API call with `memory.get_active_deals_from_index()`
- Added delta fetch for recently modified deals
- Updated per-deal loop to use flat CSV structure (no more `get_deal_company()` calls)
- Still fetches contacts via API for email-based call matching

### ✅ TASK 4: scripts/hubspot_deals.py
- Added `get_deals_modified_since(since_date)` method for delta updates

### ✅ TASK 5: .gitignore
- Confirmed `data/*.csv` already excluded (line 46)

---

## Next Steps for Jeff

### 1. Export Deals from HubSpot

**In HubSpot:**
1. Go to CRM → Deals
2. Click "Actions" → "Export"
3. Select all deals (or filter to active deals)
4. Download as CSV

**Save to:**
```
/Users/jeffignacio/GrowthBook/meddicc-agent/data/hubspot_deals.csv
```

### 2. Run ETL Script

```bash
cd /Users/jeffignacio/GrowthBook/meddicc-agent
python scripts/etl_deals.py
```

**Expected output:**
```
✓ Deal index built: XXX active deals
  Skipped: X Renewal, X excluded stage, X no company
  Output: memory/deals/index.json

First 10 active deals:
  [1] Company Name | stage | pipeline | $ARR

Stages present in active deals:
  appointmentscheduled: X deals
  qualifiedtobuy: X deals
  ...
```

### 3. Verify Output

**Check the stage list** in the output. If you see a numeric stage ID that represents "Meeting Set" in a custom pipeline, add it to `EXCLUDED_STAGES` in `scripts/etl_deals.py`:

```python
EXCLUDED_STAGES = [
    'appointmentscheduled',  # Meeting Set (default pipeline)
    '79653122',              # ADD THIS IF IT'S MEETING SET IN CUSTOM PIPELINE
    'closedwon',
    'closedlost',
    '1297321623',            # Renewal - Closed Won
    '1297321624',            # Renewal - Closed Lost
]
```

Then re-run `python scripts/etl_deals.py`.

### 4. Commit Changes

```bash
git add memory/deals/ scripts/
git commit -m "Add CSV-based deal index with delta sync

Implements CSV → cache → delta pattern for HubSpot deals:
- scripts/etl_deals.py: Build deal index from CSV export
- scripts/github_memory.py: Add deal index methods
- scripts/run_nightly.py: Use deal index instead of API calls
- scripts/hubspot_deals.py: Add delta fetch for modified deals

Filters out Renewal pipeline, Meeting Set, and closed stages.
Reduces API calls by loading from CSV-built index.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

git push origin main
```

---

## How It Works

### Initial Setup (One-time)
1. Export deals from HubSpot → `data/hubspot_deals.csv`
2. Run `etl_deals.py` → builds `memory/deals/index.json`
3. Commit `memory/deals/` to repo

### Nightly Run (Automated)
1. `run_nightly.py` loads deals from `memory/deals/index.json` (no API call)
2. Fetches delta: deals modified since last run via API
3. Logs warning if deals changed since CSV export
4. Processes each deal using cached company info

### CSV Refresh (Weekly/Monthly)
1. Re-export deals from HubSpot
2. Re-run `etl_deals.py`
3. Commit updated index

---

## Benefits

✅ **Faster startup:** No API call to fetch 600+ deals
✅ **No rate limits:** Index loaded from disk
✅ **Consistent filtering:** CSV export applies deal filters once
✅ **Delta detection:** Catches stage changes between exports
✅ **Matches calls pattern:** Same architecture as Fireflies/Apollo caches

---

## Files Modified

- ✅ `scripts/etl_deals.py` (new)
- ✅ `scripts/github_memory.py` (updated)
- ✅ `scripts/run_nightly.py` (updated)
- ✅ `scripts/hubspot_deals.py` (updated)
- ✅ `.gitignore` (already configured)

All syntax checks passed ✓
