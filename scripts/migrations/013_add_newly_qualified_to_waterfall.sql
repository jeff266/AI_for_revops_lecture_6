-- Add newly_qualified_value column to waterfall_weekly
-- This tracks deals that crossed from unqualified (Meeting Set) to qualified stages

ALTER TABLE waterfall_weekly
ADD COLUMN IF NOT EXISTS newly_qualified_value NUMERIC DEFAULT 0;
