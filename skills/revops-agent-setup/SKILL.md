---
name: revops-agent-setup
description: >
  Collect all credentials and API keys needed to deploy the RevOps
  MEDDICC agent. Use this skill when setting up a new client deployment,
  when credentials need to be rotated, or when someone asks how to
  configure the agent environment. Walks through each credential one at
  a time, explains where to find it, validates the format, and outputs
  a ready-to-paste .env file for Railway and a GitHub Secrets checklist.
  Triggers on: set up the agent, configure environment, I need credentials,
  where do I get my API keys, Railway setup, GitHub Secrets setup.
---

# RevOps Agent Environment Setup

Walk through each credential in sequence. Explain where to find each one
before asking. Validate format before proceeding. At the end, output two
artifacts: the Railway .env file and the GitHub Secrets checklist.

Never ask for multiple credentials at once. One at a time keeps errors
out and makes it easy to pause and come back.

## Step 0 — Platform Discovery

Ask these questions first to determine which credentials are needed:

Ask: "What CRM do you use? (HubSpot, Salesforce, other)"
Store the answer.

Ask: "What call recording platform do you use? (Fireflies, Gong, other)"
Store the answer.

If they answer "other" for either, tell them:
"Currently this agent supports HubSpot + (Fireflies or Gong).
You'll need to fork the repo and add a custom client for [their platform].
Should we continue with manual setup, or pause here?"

Use these answers to determine which credentials to collect in subsequent steps.

## Step 0a — Install dependencies

Tell the user:
"Before collecting credentials, install the required Python dependencies.
This ensures imports work when testing your setup.

From the repo root, run:

  pip install -r requirements.txt

This installs: anthropic, requests, PyYAML, supabase, and other dependencies.

If you see import errors later (ModuleNotFoundError), this step was skipped."

Wait for confirmation before proceeding.

## Step 1 — Anthropic API Key

Tell the user:
"First we need your Anthropic API key. This is what powers Claude.
To get it: platform.anthropic.com → API Keys → Create Key
Format: starts with sk-ant-"

Ask: "Paste your Anthropic API key:"
Validate: must start with sk-ant-

## Step 2 — Call intelligence platform credentials

Use the answer from Step 0 to determine which credentials to collect.

### If using Gong:

Tell the user:
"You're configured to use Gong for call intelligence.
To get your credentials:
1. Go to: Gong → Settings → Company Settings → API
2. Create a new Technical User or use existing
3. You'll need: Access Key and Access Key Secret

Gong API docs: https://gong.app.gong.io/settings/api/documentation"

Ask: "Paste your Gong Access Key:"
Store as: GONG_ACCESS_KEY

Ask: "Paste your Gong Access Key Secret:"
Store as: GONG_ACCESS_KEY_SECRET

### If using Fireflies:

Tell the user:
"You're configured to use Fireflies for call intelligence.
To get it: app.fireflies.ai → Integrations → API → copy the key

IMPORTANT: The API key must have TRANSCRIPT scope, not just summaries.
When creating the key, ensure 'Access to transcripts' is enabled.
Without it, the progressive scorer can't analyze call content."

Ask: "Paste your Fireflies API key (or SKIP):"
Store as: FIREFLIES_API_KEY

### If using a custom call tool (Fathom, Avoma, Chorus, etc.):

Tell the user:
"You're using {tool_name} for call intelligence.
If you've already built the adapter (from client context onboarding),
provide the API credential(s) now.

Credential name should match what the adapter expects.
Check scripts/adapters/calls/{tool_slug}.py for the exact env var name."

Ask: "Paste your {Tool} API credential:"
Store as: {TOOL}_API_KEY (or whatever name the adapter uses)

If they haven't built the adapter yet, tell them:
"Run 'start client onboarding' first to generate the call adapter,
then come back here for credential setup."

## Step 3 — Apollo API Key

Tell the user:
"Apollo is used for video call recordings.
Note: this is the meeting recorder, not the sales intelligence tool.
To get it: your Apollo workspace → Settings → API"

Ask: "Paste your Apollo API key (or SKIP):"
Store as: APOLLO_API_KEY

## Step 4 — CRM credentials

### If using HubSpot:

Tell the user:
"HubSpot is your CRM. The agent reads active deals and writes
MEDDICC scores back as deal properties.

To get it:
1. HubSpot → Settings → Integrations → Private Apps
2. Required scopes:
   - crm.objects.deals.read
   - crm.objects.deals.write
   - crm.objects.companies.read
   - crm.objects.contacts.read
   - crm.objects.owners.read
   - crm.schemas.deals.read
   - crm.schemas.deals.write
3. Copy the access token (starts with pat-na1-)

IMPORTANT: crm.schemas.deals.write is a SEPARATE permission toggle from
crm.objects.deals.write. Many users have object write but not schema write
— it's a different checkbox in the HubSpot UI. You need both. Schema write
is what setup_hubspot_properties.py needs to create custom properties.

Also important: rotate this token if it was ever in a public repo."

Ask: "Paste your HubSpot private app token:"
Validate: should start with pat-

## Step 5 — Supabase credentials

Tell the user:
"Supabase is the query database for the Slack agent.
Go to: Supabase dashboard → your project → Settings → API
You need two things: Project URL and service_role key (not anon)."

Ask: "Paste your Supabase Project URL:"
Validate: must start with https:// and end with .supabase.co

Ask: "Paste your Supabase service_role key:"
Validate: starts with eyJ

Tell the user:
"One more Supabase credential — the direct database connection string.
This is DIFFERENT from the Project URL and is required to run schema migrations.

WHY: The PostgREST API (Project URL + service_role key) can't execute DDL
(CREATE TABLE, ALTER, etc.). setup_supabase.py needs direct Postgres access
to run migrations.

Go to: Supabase dashboard → your project → Settings → Database → Connection string → URI tab.

Copy the pooler URI (it contains .pooler.supabase.com) and replace [YOUR-PASSWORD]
with your database password (set at project creation; also shown on that page).

Note: the hostname is NOT db.<ref>.supabase.co — free-tier projects only resolve
the pooler hostname."

Ask: "Paste your Supabase connection string:"
Validate: starts with postgresql:// and contains supabase.com
Store as: SUPABASE_DB_URL

## Step 6 — GitHub repository

Ask: "Enter your GitHub repo (owner/repo-name):"
Example: acme/AI_for_revops_lecture_6

## Step 7 — Zapier catch hook URL

Tell the user:
"This is the Zap 2 catch hook URL — skip if not set up yet."

Ask: "Paste your Zapier catch hook URL (or SKIP):"

## Step 8 — Install secret protection hooks

Tell the user:
"Installing pre-commit hooks to block API keys from being committed.
These hooks prevent secrets from entering version control — critical
for a template repo where every client starts from a fresh clone."

Run: ./scripts/install_hooks.sh

If it fails with permission denied:
  chmod +x scripts/install_hooks.sh scripts/hooks/block_api_keys.sh
  ./scripts/install_hooks.sh

Tell the user:
"✓ Hooks installed. Git will now block commits containing API keys.
To bypass when needed: git commit --no-verify"

## Step 9 — Generate outputs

Write a .env file to the repo root with all collected values.

Then print the GitHub Secrets checklist based on the selected platforms:

**If using Fireflies:**

GitHub Secrets — Environment: Agent

□ ANTHROPIC_API_KEY
□ FIREFLIES_API_KEY
□ APOLLO_API_KEY            (blank if skipped)
□ HUBSPOT_API_KEY
□ SUPABASE_URL
□ SUPABASE_SERVICE_KEY
□ SUPABASE_DB_URL
□ ZAP_RESPONSE_URL          (blank if skipped)

**If using Gong:**

GitHub Secrets — Environment: Agent

□ ANTHROPIC_API_KEY
□ GONG_ACCESS_KEY
□ GONG_ACCESS_KEY_SECRET
□ APOLLO_API_KEY            (blank if skipped)
□ HUBSPOT_API_KEY
□ SUPABASE_URL
□ SUPABASE_SERVICE_KEY
□ SUPABASE_DB_URL
□ ZAP_RESPONSE_URL          (blank if skipped)

**If using a custom call tool:**

Include the credential name(s) for the custom adapter instead
of Fireflies or Gong credentials.

Fastest way to add them:
  gh secret set --env Agent --env-file .env

Note: GITHUB_TOKEN and GITHUB_REPO are automatic — do not add them.

SUPABASE_DB_URL is needed by anyone running setup_supabase.py or --verify-all locally.

Tell the user: "Credentials done. Now run the context onboarding:
say 'start client onboarding'"

## Step 10 — Verification suite (run after Supabase setup)

Tell the user:
"After you complete context onboarding, stage discovery, and Supabase setup,
run the verification suite to validate your data quality before the first nightly:

  python scripts/verify/run_all.py

This checks five things:
1. Coverage — what fraction of deals have calls, transcripts, scores, snapshots
2. Determinism — LLM scoring jitter (spread per component)
3. Plausibility — sanity checks on analytical outputs (no negative counts,
   conversions ≤100%, subsets smaller than supersets)
4. CRM crosscheck — agent pipeline count vs HubSpot, with explanation
5. Reconciliation — pattern for write guards (examples, not run automatically)

**Expected verdicts PRE-ETL (before first nightly):**
- Coverage: INCONCLUSIVE (no deals in memory/deals/index.json yet)
- Determinism: INCONCLUSIVE (no calls in memory/calls/*.json yet)
- Plausibility: FAIL (missing deal index and Supabase credentials not wired)
- CRM crosscheck: INCONCLUSIVE (no agent deals to compare)

These are CORRECT, not broken. They confirm the checks are wired.

**Expected verdicts POST-ETL (after first nightly):**
- Coverage: PASS or specific percentages (e.g., '26.2% snapshot coverage')
- Determinism: PASS (spread ≤1 per component) or specific jitter report
- Plausibility: PASS (all assertions hold) or FAIL with specific violations
- CRM crosscheck: PASS (counts reconcile) or difference with explanation

Run it TWICE:
1. Now (confirms wiring, expect INCONCLUSIVE)
2. After first nightly completes (see your own numbers)

If you see unexpected FAILs after the first nightly (e.g., 'Qualified deals > total deals',
'Conversion rate 147%'), those are real data quality issues to investigate.

The verification suite helps you find your own bad numbers rather than inheriting
the template's default assumptions."
