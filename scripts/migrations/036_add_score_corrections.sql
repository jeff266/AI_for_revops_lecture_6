-- Migration 036: Create score_corrections table
-- Ported from the reference implementation migration 040
--
-- Purpose: Score corrections - a rep's structured disagreement with a MEDDICC
-- component score (FIX_MEDDICC_SCORING_PIPELINE, Part 7).
--
-- This is a REVIEW QUEUE, never a live score source — same discipline as the
-- proposals table (migration 035): the agent proposes a score, a human disposes.
-- Nothing here auto-adjusts a component score.
--
-- Two purposes:
--   1. A rep who can push back stops treating the tool as an accusation
--   2. We accumulate labelled examples of where the generator is wrong — the
--      only real training signal available
--
-- Dependencies: None (standalone table)

CREATE TABLE IF NOT EXISTS score_corrections (
  id                BIGSERIAL PRIMARY KEY,

  deal_id           TEXT,               -- resolved deal, if known
  company_name      TEXT,               -- as the rep named it

  component         TEXT NOT NULL,
    -- Component key from selected methodology (e.g., 'metrics', 'economic_buyer',
    -- 'decision_criteria', 'decision_process', 'pain', 'champion', 'competition')
    -- MEDDPICC adds 'paper_process'; SPICED uses different keys.
  current_score     INTEGER,            -- what the agent scored it (0-10), if known
  proposed_score    INTEGER NOT NULL,   -- what the rep says it should be (0-10)
  reason            TEXT NOT NULL,      -- the rep's justification (evidence)

  submitted_by      TEXT,               -- slack_user_id or email of the rep
  submitted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

  status            TEXT NOT NULL DEFAULT 'proposed',
    -- 'proposed' | 'accepted' | 'rejected'  (human sets accepted/rejected)
  reviewed_at       TIMESTAMPTZ,
  reviewed_by       TEXT,
  review_notes      TEXT
);

CREATE INDEX IF NOT EXISTS idx_score_corrections_open
  ON score_corrections(status) WHERE status = 'proposed';
CREATE INDEX IF NOT EXISTS idx_score_corrections_deal
  ON score_corrections(deal_id, submitted_at DESC);

-- Comments for documentation
COMMENT ON TABLE score_corrections IS
'Review queue for rep disagreements with agent scores. Reps propose corrections with
evidence. Human reviews. Accepted corrections become training signal for score improvement.
Never auto-adjusts live scores.';

COMMENT ON COLUMN score_corrections.component IS
'Component key from configured methodology (utils.component_key()). Examples: metrics,
champion, economic_buyer for MEDDICC; paper_process added for MEDDPICC; different keys
for SPICED/BANT. Methodology-agnostic - driven by config.';

COMMENT ON COLUMN score_corrections.reason IS
'Rep justification for the proposed score. Evidence from calls, emails, or other context
that the agent missed or misinterpreted. This is the training signal.';

-- Verification
DO $$
BEGIN
    RAISE NOTICE 'Migration 036 complete - created score_corrections table';
    RAISE NOTICE 'Rep feedback review queue ready';
END $$;
