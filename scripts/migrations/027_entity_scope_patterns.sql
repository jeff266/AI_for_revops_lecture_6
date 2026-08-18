-- Migration 027: Track successful entity-scope query patterns
--
-- Purpose: Log which questions route successfully through entity-scope handlers
-- to build a pattern library for future improvements and handler generation.

CREATE TABLE IF NOT EXISTS entity_scope_patterns (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    handler_name TEXT NOT NULL,
    entity_count INTEGER NOT NULL,
    quality_score NUMERIC(3,2),
    asked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for pattern analysis queries
CREATE INDEX IF NOT EXISTS idx_entity_patterns_handler
    ON entity_scope_patterns(handler_name, asked_at DESC);

CREATE INDEX IF NOT EXISTS idx_entity_patterns_quality
    ON entity_scope_patterns(quality_score DESC, asked_at DESC);

-- View: Recent successful patterns (quality >= 0.7)
CREATE OR REPLACE VIEW entity_scope_patterns_recent AS
SELECT
    handler_name,
    question,
    entity_count,
    quality_score,
    asked_at
FROM entity_scope_patterns
WHERE quality_score >= 0.7
ORDER BY asked_at DESC
LIMIT 100;

COMMENT ON TABLE entity_scope_patterns IS
    'Logs successful entity-scope routing patterns for handler generation and improvement';
COMMENT ON COLUMN entity_scope_patterns.question IS
    'The original user question that was routed';
COMMENT ON COLUMN entity_scope_patterns.handler_name IS
    'Which bulk handler was classified and executed';
COMMENT ON COLUMN entity_scope_patterns.entity_count IS
    'Number of entities (deal_ids) in the context';
COMMENT ON COLUMN entity_scope_patterns.quality_score IS
    'Evaluation score (0.0-1.0) from assess_result_quality';
