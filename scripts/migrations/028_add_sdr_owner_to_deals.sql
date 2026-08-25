-- Migration 028: Add SDR owner field to deals
-- Ported from the reference implementation migration 031
--
-- Purpose: Track SDR/BDR attribution post-handoff to AE
-- Enables tracking SDR-sourced pipeline post-handoff to AEs
--
-- Populated from HubSpot attribution field (e.g., bdr_owner) configured in
-- config/client.yaml. Used for SDR pipeline contribution tracking and attribution
-- analysis.
--
-- Dependencies: Assumes deals table exists (migration 001)

ALTER TABLE deals
ADD COLUMN IF NOT EXISTS sdr_owner_email TEXT;

CREATE INDEX IF NOT EXISTS deals_sdr_owner_email_idx
ON deals(sdr_owner_email);

COMMENT ON COLUMN deals.sdr_owner_email IS
  'Email of SDR/BDR who sourced this deal. Populated from HubSpot attribution field configured in client.yaml (e.g., bdr_owner). Used for SDR pipeline contribution tracking.';

-- Verification
DO $$
BEGIN
    RAISE NOTICE 'Migration 028 complete - added sdr_owner_email to deals';
END $$;
