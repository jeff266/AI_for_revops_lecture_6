-- Migration 039: Add call_scores table for progressive scoring
-- Phase 4a: JSONB pattern for methodology-agnostic component storage
--
-- CRITICAL: Uses JSONB, not fixed columns. the reference implementation's original migration had
-- metrics_score, economic_buyer_score, etc. (7 fixed columns) which defeats
-- methodology switching. This migration uses component_scores JSONB so a
-- MEDDPICC client gets {"paper_process": 7, ...} with zero schema changes.
--
-- Progressive scoring design: Each call scored once at ingest, rollup computes
-- deal-level scores as most-recent-non-null per component. Replaces batch
-- scoring (score all calls for a deal in one pass).

CREATE TABLE IF NOT EXISTS call_scores (
  call_id                  TEXT PRIMARY KEY REFERENCES calls(call_id) ON DELETE CASCADE,
  deal_id                  TEXT,
  call_date                DATE,

  -- JSONB, not fixed columns. Methodology-agnostic.
  component_scores         JSONB,  -- {component_key: score}
  evidence                 JSONB,  -- {component_key: evidence_text}

  text_source              TEXT NOT NULL CHECK (text_source IN ('transcript', 'summary')),
  model                    TEXT NOT NULL,
  scorer_version           TEXT NOT NULL,
  scored_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_call_scores_deal_date
  ON call_scores(deal_id, call_date);

CREATE INDEX IF NOT EXISTS idx_call_scores_scorer_version
  ON call_scores(scorer_version);

-- Example JSONB content for MEDDICC:
-- component_scores: {"metrics": 7, "economic_buyer": 6, "decision_criteria": 5, ...}
-- evidence: {"metrics": "Quote: 'We need to reduce churn by 15%'", ...}
--
-- Example JSONB content for MEDDPICC (8 components):
-- component_scores: {"metrics": 7, "paper_process": 8, ...}
-- evidence: {"paper_process": "Quote: 'Legal requires security questionnaire'", ...}
--
-- Changing methodology requires zero schema changes. Query pattern:
-- SELECT component_scores->>'champion' FROM call_scores WHERE deal_id = '123'
