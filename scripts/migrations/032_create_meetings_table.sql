-- Migration 032: Create meetings table for SDR metrics
-- Merged from the reference implementation 033+035 (fold-forward pattern)
--
-- Purpose: Track HubSpot meeting bookings with call recording held inference
--
-- Data sources:
--   - HubSpot meetings API (scheduled meetings)
--   - Call recordings (held meetings with transcripts from Fireflies/Gong/Apollo)
--
-- Key insight: hs_meeting_outcome is not always populated in HubSpot.
-- Instead, match meetings to call recordings by date/owner/company to infer
-- which meetings were actually held.
--
-- IMPORTANT: This migration uses call_recording_id from the start (not
-- fireflies_call_id). the reference implementation's 033 created it as fireflies_call_id, then
-- 035 renamed it when Apollo was added. The template gets the final naming
-- to support multiple call adapters (Fireflies, Gong, Apollo) without migration.
--
-- Dependencies: Assumes calls table exists (migration 001)

CREATE TABLE IF NOT EXISTS meetings (
    id                    BIGSERIAL PRIMARY KEY,
    hubspot_meeting_id    TEXT UNIQUE NOT NULL,
    hubspot_owner_id      TEXT,
    owner_email           TEXT,
    title                 TEXT,
    scheduled_at          TIMESTAMPTZ NOT NULL,
    scheduled_end_at      TIMESTAMPTZ,
    booked_at             TIMESTAMPTZ,
    hs_meeting_outcome    TEXT,  -- Usually null, but capture if populated

    -- Held inference
    held                  BOOLEAN,  -- True=held, False=confirmed no-show, null=unknown
    held_confidence       TEXT,     -- 'recording_match' | 'hs_outcome' | null
    call_recording_id     TEXT REFERENCES calls(call_id),
        -- FK to calls table. Adapter-agnostic naming supports Fireflies, Gong, Apollo.

    -- Associations
    contact_email         TEXT,
    company_name          TEXT,
    deal_id               TEXT,

    -- Metadata
    created_at            TIMESTAMPTZ DEFAULT now(),
    updated_at            TIMESTAMPTZ DEFAULT now()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS meetings_owner_email_idx
    ON meetings(owner_email);

CREATE INDEX IF NOT EXISTS meetings_scheduled_at_idx
    ON meetings(scheduled_at);

CREATE INDEX IF NOT EXISTS meetings_held_idx
    ON meetings(held);

CREATE INDEX IF NOT EXISTS meetings_owner_date_idx
    ON meetings(owner_email, scheduled_at);

CREATE INDEX IF NOT EXISTS meetings_call_recording_idx
    ON meetings(call_recording_id);

-- Comments for documentation
COMMENT ON TABLE meetings IS
'SDR meeting bookings with call recording held inference. hs_meeting_outcome is not
always populated in HubSpot, so held status is inferred by matching scheduled meetings
to call recordings by date/owner/company.';

COMMENT ON COLUMN meetings.held IS
'True=held (recording match or HubSpot outcome), False=confirmed no-show, null=unknown
(past meeting with no signal, or future meeting)';

COMMENT ON COLUMN meetings.held_confidence IS
'Source of held inference: recording_match (matched to call transcript), hs_outcome
(HubSpot field populated), or null (unknown)';

COMMENT ON COLUMN meetings.call_recording_id IS
'Foreign key to calls table. References the call recording (from Fireflies, Gong, or
Apollo) that corresponds to this meeting, if one was found. Used to infer held=true.';

-- Verification
DO $$
BEGIN
    RAISE NOTICE 'Migration 032 complete - created meetings table';
    RAISE NOTICE 'Uses call_recording_id (adapter-agnostic) for multi-source support';
END $$;
