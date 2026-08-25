-- Migration 035: Create proposals table for self-tuning analyses
-- Ported from the reference implementation migration 036
--
-- Purpose: Generic proposals table for self-tuning analyses
-- Part of Phase 1: Proposal Loop and Advisory Cron
--
-- This table is a recommendation ledger, NEVER a live config source.
-- Approval marks intent; a human (or gated regeneration) makes the config change.
--
-- Examples of proposal types:
-- - stage_semantics: adjusting stage progression thresholds
-- - coverage_methodology: changing snapshot window parameters
-- - field_definition: new field mappings for dynamic queries
-- - meddicc_weighting: component importance adjustments
--
-- Dependencies: None (standalone table)

CREATE TABLE IF NOT EXISTS proposals (
  id                  BIGSERIAL PRIMARY KEY,

  entity_type         TEXT NOT NULL,
    -- 'stage_semantics' | 'coverage_methodology' | 'field_definition'
    -- | 'meddicc_weighting'  (extend as analyses are added)
  entity_key          TEXT NOT NULL,
    -- what within that type: e.g. 'anchor_week', 'trailing_quarters_window',
    -- 'deals.forecast_category'

  current_value       JSONB,        -- what config/system holds today
  proposed_value      JSONB NOT NULL,-- what the analysis suggests instead
  rationale           TEXT NOT NULL, -- human-readable why

  evidence            JSONB NOT NULL,
    -- the numbers behind it. Shape is analysis-specific but ALWAYS
    -- includes sample size and the window measured, e.g.
    -- {"quarters_analyzed": 6, "deals_in_cohort": 143,
    --  "measured_value": 0.34, "effect_size": 0.11}
  evidence_count      INTEGER NOT NULL DEFAULT 0,
    -- primary sample-size number, denormalized for the evidence-bar filter

  status              TEXT NOT NULL DEFAULT 'proposed',
    -- 'proposed' | 'approved' | 'rejected' | 'superseded' | 'expired'
  proposed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  proposed_by         TEXT NOT NULL DEFAULT 'agent',
  reviewed_at         TIMESTAMPTZ,
  reviewed_by         TEXT,
  review_notes        TEXT,
  superseded_by_id    BIGINT REFERENCES proposals(id),

  affects_handlers    BOOLEAN NOT NULL DEFAULT false,
    -- true  -> approval requires config edit + regenerate + test + deploy
    -- false -> approval can take effect without a code path change
  requires_regeneration BOOLEAN NOT NULL DEFAULT false,
    -- true for anything feeding a generated module (field_semantics)

  UNIQUE (entity_type, entity_key, proposed_at)
);

CREATE INDEX IF NOT EXISTS idx_proposals_open
  ON proposals(entity_type, status) WHERE status = 'proposed';
CREATE INDEX IF NOT EXISTS idx_proposals_entity
  ON proposals(entity_type, entity_key, proposed_at DESC);

-- Comments for documentation
COMMENT ON TABLE proposals IS
'Self-improvement recommendation ledger. Agent proposes config changes based on data
analysis. Human reviews and approves. NEVER a live config source - approval triggers
manual config change or regeneration.';

COMMENT ON COLUMN proposals.entity_type IS
'Type of config being proposed: stage_semantics, coverage_methodology, field_definition,
meddicc_weighting. Extensible as new self-tuning analyses are added.';

COMMENT ON COLUMN proposals.evidence IS
'Data supporting the proposal. Always includes sample_size and measurement_window.
Shape varies by analysis type but must be sufficient to justify the change.';

COMMENT ON COLUMN proposals.affects_handlers IS
'True if approval requires regenerating handler code (field_semantics changes).
False if change can be applied dynamically (query-path only).';

-- Verification
DO $$
BEGIN
    RAISE NOTICE 'Migration 035 complete - created proposals table';
    RAISE NOTICE 'Self-improvement recommendation ledger ready';
END $$;
