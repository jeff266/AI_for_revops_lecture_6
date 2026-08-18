-- Migration 024: Add company_domain column and fix nullable constraints
-- This enables email domain-based call resolution

-- Add company_domain column
ALTER TABLE deals
ADD COLUMN IF NOT EXISTS company_domain TEXT;

-- Create index for efficient domain lookups
CREATE INDEX IF NOT EXISTS idx_deals_company_domain
ON deals(company_domain)
WHERE company_domain IS NOT NULL;

-- Make company_name nullable (some deals have company_id but no name in HubSpot)
ALTER TABLE deals
ALTER COLUMN company_name DROP NOT NULL;

-- Make company_slug nullable (follows company_name nullability)
ALTER TABLE deals
ALTER COLUMN company_slug DROP NOT NULL;
