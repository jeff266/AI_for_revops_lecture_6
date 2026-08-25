-- Migration 034: Add proposal lifecycle to data_dictionary
-- Ported from GrowthBook migration 034 (Phase 5)
--
-- Purpose: Enable self-improvement loop where the agent can propose new field
-- definitions without immediately affecting production queries.
--
-- Extends data_dictionary with proposal lifecycle columns to track:
-- - Proposal status (draft, active, accepted, rejected, superseded)
-- - Review workflow (who proposed, who reviewed, when)
-- - Supersession chain (replacement tracking)
-- - Handler impact flag (affects generated code vs dynamic queries)
--
-- Dependencies: Assumes data_dictionary table exists (migration 007)

-- Add proposal lifecycle columns
ALTER TABLE data_dictionary
  ADD COLUMN IF NOT EXISTS proposal_status TEXT DEFAULT 'accepted',
    -- 'draft' | 'active' | 'accepted' | 'rejected' | 'superseded'
    -- draft: proposed but not yet reviewed
    -- active: under review/testing
    -- accepted: production-ready (default for backfilled rows)
    -- rejected: proposed but declined
    -- superseded: replaced by a newer definition

  ADD COLUMN IF NOT EXISTS proposed_at TIMESTAMPTZ DEFAULT now(),
    -- When this definition was proposed

  ADD COLUMN IF NOT EXISTS proposed_by TEXT DEFAULT 'backfill',
    -- 'agent' | 'human' | 'backfill' | specific user email
    -- Tracks who/what created this definition

  ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ,
    -- When this proposal was reviewed (null if not yet reviewed)

  ADD COLUMN IF NOT EXISTS reviewed_by TEXT,
    -- Who reviewed this proposal (null if not yet reviewed)

  ADD COLUMN IF NOT EXISTS review_notes TEXT,
    -- Optional notes from review process

  ADD COLUMN IF NOT EXISTS superseded_by_id BIGINT REFERENCES data_dictionary(id),
    -- If superseded, points to the replacement definition
    -- NULL for active definitions

  ADD COLUMN IF NOT EXISTS affects_handlers BOOLEAN DEFAULT false;
    -- True if this field is consumed by handlers (requires regeneration)
    -- False if only used by dynamic query path (can change without code changes)

-- Create index for active proposals (what dynamic path queries)
CREATE INDEX IF NOT EXISTS idx_dict_active_proposals
  ON data_dictionary(proposal_status)
  WHERE proposal_status IN ('active', 'accepted');

-- Create index for superseded chain
CREATE INDEX IF NOT EXISTS idx_dict_superseded_by
  ON data_dictionary(superseded_by_id)
  WHERE superseded_by_id IS NOT NULL;

-- Create index for affects_handlers (critical for generator gate)
CREATE INDEX IF NOT EXISTS idx_dict_affects_handlers
  ON data_dictionary(affects_handlers)
  WHERE affects_handlers = true;

-- Backfill existing rows: mark as accepted, backfill source
UPDATE data_dictionary
SET
  proposal_status = 'accepted',
  proposed_by = 'backfill',
  proposed_at = COALESCE(last_refreshed, now())
WHERE proposal_status IS NULL;

-- Verification
DO $$
BEGIN
    RAISE NOTICE 'Migration 034 complete - added proposal lifecycle to data_dictionary';
    RAISE NOTICE 'Backfilled existing rows as proposal_status=accepted, proposed_by=backfill';
END $$;
