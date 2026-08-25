-- Migration 038: Create call_quality table (OPTIONAL)
-- Ported from GrowthBook migration 030
--
-- **OPTIONAL MIGRATION**
-- Only required if client wants discovery quality scoring feature.
-- Skip this migration if call quality assessment is not needed.
--
-- Purpose: Store discovery quality scores extracted from call summaries
-- Based on gb-drill-discovery framework from GrowthBook coaching skills.
-- Enables discovery coaching, rep skill trending, and pattern identification.
--
-- Consumed by:
-- - api/handlers.py (query_call_quality handler)
-- - api/router.py (call quality intent classification)
-- - Test and evaluation scripts
--
-- Scoring dimensions (1-10 each):
-- - Quantification: Did they leave with numbers?
-- - Incumbent picture: Cost, contract end, what's wrong with it
-- - Technical picture: Warehouse, SDK, who runs tests
-- - Decision process: Who decides, threshold, timeline
-- - Question quality: Open questions, one at a time, followed up
--
-- Dependencies: Assumes calls table exists (migration 001)

CREATE TABLE IF NOT EXISTS call_quality (
    id                  BIGSERIAL PRIMARY KEY,
    call_id             TEXT REFERENCES calls(call_id),
    deal_id             TEXT,
    company_name        TEXT,
    owner_email         TEXT,
    call_date           DATE,

    -- Discovery scoring (1-10 each, null if not assessable)
    -- Based on gb-drill-discovery rubric
    quantification_score    INTEGER,  -- Did they leave with numbers?
    incumbent_picture_score INTEGER,  -- Cost, contract end, what's wrong with it
    technical_picture_score INTEGER,  -- Warehouse, SDK, who runs tests
    decision_process_score  INTEGER,  -- Who decides, threshold, timeline
    question_quality_score  INTEGER,  -- Open, one at a time, followed up

    overall_quality_score   INTEGER,  -- Average of above, 1-10

    -- What was found / missing
    numbers_obtained    JSONB,   -- which of the 5 discovery numbers were captured
    numbers_missing     JSONB,   -- which were not
    blocker_type        TEXT,    -- technical | resourcing | cultural | commercial | none
    blocker_identified  BOOLEAN, -- did rep correctly identify the blocker type

    -- Evidence
    strongest_moment    TEXT,    -- verbatim quote or description
    weakest_moment      TEXT,
    pattern_flags       TEXT[],  -- ['no_followup', 'pitched_early',
                                 --  'accepted_vague_answer', 'no_number']

    -- Metadata
    assessed_at         TIMESTAMPTZ DEFAULT now(),
    assessment_source   TEXT DEFAULT 'llm'  -- 'llm' | 'human'
);

CREATE INDEX IF NOT EXISTS call_quality_deal_id_idx
    ON call_quality(deal_id);
CREATE INDEX IF NOT EXISTS call_quality_owner_email_idx
    ON call_quality(owner_email);
CREATE INDEX IF NOT EXISTS call_quality_call_date_idx
    ON call_quality(call_date);

-- Comments for documentation
COMMENT ON TABLE call_quality IS
'OPTIONAL: Discovery quality assessment. Only needed if client wants discovery coaching
feature. Scores calls on 5 dimensions (quantification, incumbent, technical, decision
process, question quality). Based on gb-drill-discovery framework.';

COMMENT ON COLUMN call_quality.numbers_obtained IS
'JSONB array of which discovery numbers were captured (e.g., ["current_cost",
"contract_end_date", "decision_timeline"]). Used to identify common gaps.';

COMMENT ON COLUMN call_quality.pattern_flags IS
'Common discovery anti-patterns identified in this call: no_followup (accepted vague
answer), pitched_early (presented before understanding), accepted_vague_answer,
no_number (left without quantification).';

COMMENT ON COLUMN call_quality.blocker_type IS
'Category of main obstacle identified: technical (integration complexity), resourcing
(budget/headcount), cultural (change resistance), commercial (pricing), none.';

-- Verification
DO $$
BEGIN
    RAISE NOTICE 'Migration 038 complete - created call_quality table (OPTIONAL)';
    RAISE NOTICE 'Discovery quality scoring feature';
    RAISE NOTICE 'Skip if client does not need discovery coaching';
END $$;
