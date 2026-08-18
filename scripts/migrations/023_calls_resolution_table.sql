-- ============================================================
-- Phase E.3 — proper calls table with resolve-once deal linkage
--
-- THE PROBLEM:
-- The existing 35-row calls table holds enrichment scan
-- timestamps only — no deal_id, no participants, no transcript.
-- The real call data is 2,084 records in memory/calls/*.json.
-- Every enrichment script re-resolves deal_id from slug + date
-- proximity EVERY RUN. Participant emails were never pulled.
--
-- THE FIX:
-- 1. Rename existing table to preserve enrichment ledger
-- 2. Build a real calls table with participant emails,
--    resolved deal linkage, and call intent stored once
-- 3. Migrate enrichment scripts to read from table
-- ============================================================

-- Preserve existing scan-tracking table
-- First drop indexes that would conflict
DROP INDEX IF EXISTS idx_calls_company_slug;
DROP INDEX IF EXISTS idx_calls_call_date;
DROP INDEX IF EXISTS idx_calls_deal_id;
DROP INDEX IF EXISTS idx_calls_intent;
DROP INDEX IF EXISTS idx_calls_needs_review;

ALTER TABLE IF EXISTS calls RENAME TO calls_scan_ledger;

-- The new resolved calls table
CREATE TABLE calls (
    call_id            TEXT PRIMARY KEY,
    source             TEXT NOT NULL DEFAULT 'fireflies',
                       -- 'fireflies' | 'apollo'
    title              TEXT,
    call_date          DATE,

    -- Company / deal linkage (resolved once, stored)
    company_name       TEXT,
    company_slug       TEXT,
    company_id         TEXT,
    deal_id            TEXT,
    deal_name          TEXT,

    -- Participant data (backfilled from Fireflies)
    participant_count  INTEGER,
    participant_emails TEXT[],          -- full roster
    participant_domains TEXT[],         -- derived from emails

    -- Classification (resolved once, stored)
    is_internal        BOOLEAN DEFAULT FALSE,
    call_intent        TEXT,
                       -- 'prospect' | 'sales_review' | 'skip'
    intent_confidence  NUMERIC,
    intent_method      TEXT,            -- 'email' | 'rule' | 'llm'

    -- Content
    summary            TEXT,

    -- Resolution audit trail
    resolved_at        TIMESTAMPTZ,
    resolved_by        TEXT,            -- 'auto' | 'human' | 'llm'
    resolution_notes   TEXT,
    needs_review       BOOLEAN DEFAULT FALSE,

    -- Bookkeeping
    created_at         TIMESTAMPTZ DEFAULT now(),
    updated_at         TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_calls_deal_id      ON calls (deal_id);
CREATE INDEX idx_calls_company_slug ON calls (company_slug);
CREATE INDEX idx_calls_call_date    ON calls (call_date);
CREATE INDEX idx_calls_intent       ON calls (call_intent);
CREATE INDEX idx_calls_needs_review ON calls (needs_review)
    WHERE needs_review = TRUE;

-- View: calls that couldn't be auto-resolved, for review
CREATE OR REPLACE VIEW calls_needing_review AS
SELECT call_id, title, call_date, company_name,
       company_slug, deal_id, is_internal, call_intent,
       intent_confidence, resolution_notes
FROM calls
WHERE needs_review = TRUE
ORDER BY call_date DESC;

-- Data dictionary entries
INSERT INTO data_dictionary (
    source, supabase_table, supabase_column, data_type,
    description, is_queryable
) VALUES
(
    'supabase', 'calls', 'call_intent', 'text',
    'Call classification: prospect (external participant), sales_review (internal sales intelligence), skip (operational/non-sales)',
    true
),
(
    'supabase', 'calls', 'is_internal', 'boolean',
    'True when all participant domains match the client''s internal domain (no external participants)',
    true
),
(
    'supabase', 'calls', 'participant_emails', 'text[]',
    'Full roster of participant email addresses from call recording platform',
    true
),
(
    'supabase', 'calls', 'participant_domains', 'text[]',
    'Unique email domains derived from participant_emails, used for deal resolution',
    true
)
ON CONFLICT (supabase_table, supabase_column)
DO UPDATE SET description = EXCLUDED.description;

SELECT pg_notify('pgrst', 'reload schema');
