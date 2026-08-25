-- Migration 030: Create call_transcripts table
-- Ported from the reference implementation migration 041
--
-- Purpose: Store raw call transcripts in the substrate
-- (STORE_AND_BACKFILL_TRANSCRIPTS)
--
-- NormalizedCall already carries raw_transcript, but to_row() drops it — the
-- adapter contract says transcripts belong in the substrate and the write path
-- quietly diverged. This table closes that gap so coaching / deal-prep can read
-- the actual conversation, and the highest-value artifact stops living only inside
-- a vendor's API (Fireflies today, Gong tomorrow, Apollo for video meetings).
--
-- SEPARATE TABLE, not a column on calls: ~20 handlers read `calls`, several
-- paging 1000 rows at a time; a 45-min transcript is 40-60KB. Putting that on a
-- hot table changes the cost of every existing query. Keep `calls` lean.
--
-- FK note: calls.call_id is TEXT PRIMARY KEY (migration 001). We keep a FK with
-- ON DELETE CASCADE so a transcript never outlives its call. Migration 010
-- dropped call FKs on objections/feature_gaps because those are written from the
-- ANALYSIS path where the parent call row may not exist yet; transcripts are
-- written from the INGESTION path (alongside the call upsert) and the backfill
-- only iterates existing calls, so the parent always exists here.
--
-- Dependencies: Assumes calls table exists (migration 001)

CREATE TABLE IF NOT EXISTS call_transcripts (
  call_id             TEXT PRIMARY KEY REFERENCES calls(call_id) ON DELETE CASCADE,
  source              TEXT NOT NULL,            -- 'fireflies' | 'apollo' | 'gong'
  transcript          TEXT,                     -- assembled, readable; NULL if unavailable
  transcript_quality  TEXT NOT NULL
    CHECK (transcript_quality IN ('full', 'partial', 'fragments_only', 'unavailable')),
  unavailable_reason  TEXT,                     -- why NULL, when it is NULL
  char_count          INTEGER,
  fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- NULL, never an empty string or placeholder (matches the codebase's
  -- null-handling discipline). A call with no transcript is 'unavailable' + a
  -- reason, not "".
  CONSTRAINT call_transcripts_no_empty_string
    CHECK (transcript IS NULL OR transcript <> ''),
  -- If there is no transcript text, it must be explicitly marked unavailable
  -- and carry a reason — so a NULL is always an accounted-for absence.
  CONSTRAINT call_transcripts_null_is_unavailable
    CHECK (transcript IS NOT NULL
           OR (transcript_quality = 'unavailable' AND unavailable_reason IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_call_transcripts_source
  ON call_transcripts(source, transcript_quality);

-- Comments for documentation
COMMENT ON TABLE call_transcripts IS
'Raw call transcripts from call recording adapters (Fireflies, Gong, Apollo). Separate
from calls table to keep hot queries fast. Transcripts are large (40-60KB for 45min call).';

COMMENT ON COLUMN call_transcripts.transcript IS
'Assembled, readable transcript text. NULL if unavailable (with quality=unavailable and
reason set). Never empty string. Multi-speaker format: "[Speaker Name]: utterance text"';

COMMENT ON COLUMN call_transcripts.transcript_quality IS
'Quality level: full (complete transcript), partial (some utterances missing),
fragments_only (sparse coverage), unavailable (no transcript available, reason required).';

COMMENT ON COLUMN call_transcripts.unavailable_reason IS
'Why transcript is NULL: "no_recording", "api_error", "processing_failed", etc.
Required when transcript_quality=unavailable. NULL when transcript exists.';

-- Verification
DO $$
BEGIN
    RAISE NOTICE 'Migration 030 complete - created call_transcripts table';
    RAISE NOTICE 'Separate table for large transcript storage (keeps calls table lean)';
END $$;
