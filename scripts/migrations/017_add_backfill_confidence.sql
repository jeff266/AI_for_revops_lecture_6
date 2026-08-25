-- Migration 017: Add backfill confidence scoring fields
-- Merged from GrowthBook 017+039 (fold-forward pattern)
--
-- Phase D Task 2 - supports historical snapshot backfill quality tracking
--
-- Adds fields to track:
-- - History coverage levels for backfilled data (exact, pre_history, no_history)
-- - Flags for deals with known data quality issues
--
-- IMPORTANT: This migration uses the FINAL vocabulary from the start (exact,
-- pre_history, no_history) rather than the interim vocabulary (exact,
-- interpolated, inferred) that GrowthBook's 017 had before 039 widened it.
-- This prevents the 23514 constraint violation that occurred when reconstruction
-- code wrote 'pre_history' against the old CHECK.
--
-- Dependencies: Assumes deals_snapshot table exists (migration 016)

-- Add confidence scoring columns to deals_snapshot
ALTER TABLE deals_snapshot
ADD COLUMN IF NOT EXISTS backfill_confidence TEXT CHECK (backfill_confidence IN (
  'exact',          -- stage history covers this date (true point-in-time read)
  'cleared',        -- entry at or before this date exists but value is null (actively unstaged)
  'pre_history',    -- deal existed but history does not reach this date (null, not guessed)
  'no_history',     -- no stage history for the deal at all
  -- Legacy vocabulary kept for backward compatibility with any existing data:
  'interpolated', 'inferred', 'unknown', 'excluded_mismatch'
)),
ADD COLUMN IF NOT EXISTS has_property_history BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS interpolation_method TEXT,
ADD COLUMN IF NOT EXISTS data_quality_notes TEXT;

-- Add index for filtering by confidence
CREATE INDEX IF NOT EXISTS idx_snapshots_backfill_confidence
ON deals_snapshot(backfill_confidence);

-- Add index for finding deals with property history
CREATE INDEX IF NOT EXISTS idx_snapshots_has_property_history
ON deals_snapshot(has_property_history);

-- Add comments for documentation
COMMENT ON COLUMN deals_snapshot.backfill_confidence IS
'Confidence level for backfilled snapshot data:
- exact: Snapshot built from actual HubSpot property history at this date
- cleared: Entry at or before this date exists but value is null (stage was actively cleared/unstaged)
- pre_history: Deal existed but stage history does not reach this snapshot_date (returns null, never guessed)
- no_history: No stage history available for this deal
Both cleared and pre_history read as null/open, but represent different facts.
- Legacy values (interpolated/inferred/unknown/excluded_mismatch) kept for backward compatibility';

COMMENT ON COLUMN deals_snapshot.has_property_history IS
'TRUE if HubSpot property history was available for this deal at this snapshot_date.
FALSE if snapshot has no history coverage (pre_history or no_history).';

COMMENT ON COLUMN deals_snapshot.interpolation_method IS
'Method used for interpolated/inferred snapshots (e.g., "forward_fill", "last_known_state").
NULL for exact snapshots. Legacy field - new code uses backfill_confidence values.';

COMMENT ON COLUMN deals_snapshot.data_quality_notes IS
'Free-text notes about data quality issues, warnings, or special handling for this snapshot.
Examples: "Stage changed but no history available", "History gap period"';

-- Verification query to show new columns
DO $$
BEGIN
    RAISE NOTICE 'Migration 017 complete - added backfill confidence fields to deals_snapshot';
    RAISE NOTICE 'New columns: backfill_confidence, has_property_history, interpolation_method, data_quality_notes';
    RAISE NOTICE 'CHECK constraint vocabulary: exact/cleared/pre_history/no_history + legacy';
END $$;
