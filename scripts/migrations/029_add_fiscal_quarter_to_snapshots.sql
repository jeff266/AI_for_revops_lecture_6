-- Migration 029: Add forecast analysis fields to deals_snapshot
-- Merged from GrowthBook 037+038 (fold-forward pattern)
--
-- Part of Phase 2: Snapshot Schema for Forecast Analyses
--
-- Enables week-3 conversion analysis, category churn tracking, and
-- commit calibration analysis in Phase 3.
--
-- IMPORTANT: This migration includes fiscal_quarter as NOT NULL from the start.
-- GrowthBook's 037 created it nullable, then 038 added the constraint after
-- backfilling. The template gets the final schema without the intermediate state.
--
-- Dependencies: Assumes deals_snapshot table exists (migration 016)

ALTER TABLE deals_snapshot
  ADD COLUMN IF NOT EXISTS forecast_category TEXT,
    -- COMMIT | BEST_CASE | PIPELINE | OMITTED (client vocabulary varies)
    -- Backfillable if fetch-property-history.yml captured it
  ADD COLUMN IF NOT EXISTS fiscal_quarter TEXT NOT NULL,
    -- e.g. 'FY2027-Q3', from get_fiscal_quarter()
    -- Derivable from snapshot_date + fiscal config - backfillable for ALL rows
    -- NOT NULL from start: every snapshot must have a fiscal quarter
  ADD COLUMN IF NOT EXISTS week_of_quarter INTEGER;
    -- 1-13, computed at snapshot time from fiscal calendar
    -- Derivable from snapshot_date + fiscal config - backfillable for ALL rows

-- Index for forecast analyses (category churn, commit calibration, week-3 conversion)
CREATE INDEX IF NOT EXISTS idx_snapshot_category
  ON deals_snapshot(fiscal_quarter, week_of_quarter, forecast_category);

-- Index for anchor week analysis (per-week snapshots)
CREATE INDEX IF NOT EXISTS idx_snapshot_fiscal_week
  ON deals_snapshot(fiscal_quarter, week_of_quarter);

-- Add comments for documentation
COMMENT ON COLUMN deals_snapshot.forecast_category IS
'HubSpot forecast category at snapshot_date (COMMIT, BEST_CASE, PIPELINE, OMITTED).
Client vocabulary varies - captured as-is from HubSpot property history.';

COMMENT ON COLUMN deals_snapshot.fiscal_quarter IS
'Fiscal quarter for this snapshot (e.g., FY2027-Q3). Computed from snapshot_date
and fiscal year configuration. NOT NULL - every snapshot must have a fiscal quarter.';

COMMENT ON COLUMN deals_snapshot.week_of_quarter IS
'Week within fiscal quarter (1-13). Computed from snapshot_date and fiscal calendar.
Used for week-3 conversion analysis and anchor week comparisons.';

-- Verification
DO $$
BEGIN
    RAISE NOTICE 'Migration 029 complete - added forecast fields to deals_snapshot';
    RAISE NOTICE 'New columns: forecast_category, fiscal_quarter (NOT NULL), week_of_quarter';
END $$;
