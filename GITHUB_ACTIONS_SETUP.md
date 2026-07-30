# GitHub Actions Setup Guide

Complete step-by-step instructions to deploy the MEDDICC agent on GitHub Actions.

## Prerequisites

✅ Repository: https://github.com/jeff266/AI_for_revops_lecture_6
✅ Code pushed to `main` branch
✅ API keys for all services

---

## Step 1: Configure Repository Secrets

GitHub Actions needs API keys to run the agent. These are stored as encrypted secrets.

### Navigate to Secrets Settings

1. Go to: https://github.com/jeff266/AI_for_revops_lecture_6/settings/secrets/actions
2. Or: Repository → Settings → Secrets and variables → Actions → New repository secret

### Add Required Secrets

Click **"New repository secret"** for each of the following:

#### 1. ANTHROPIC_API_KEY

**Name**: `ANTHROPIC_API_KEY`
**Value**: Your Claude API key (starts with `sk-ant-...`)

**How to get it**:
- Go to: https://console.anthropic.com/settings/keys
- Click "Create Key"
- Copy the key (shown only once!)

**Cost**: ~$93-103/month for 50 deals/night

---

#### 2. FIREFLIES_API_KEY

**Name**: `FIREFLIES_API_KEY`
**Value**: Your Fireflies GraphQL API key

**How to get it**:
- Log into Fireflies.ai
- Go to: Settings → Integrations → API
- Generate new API key
- Copy the key

**Cost**: Free (included in Fireflies subscription)

---

#### 3. APOLLO_API_KEY

**Name**: `APOLLO_API_KEY`
**Value**: Your Apollo.io API key

**How to get it**:
- Log into Apollo.io (video meetings platform)
- Go to: Settings → API
- Create API key
- Copy the key

**Note**: This is Apollo.io for VIDEO MEETINGS, not Apollo.io sales intelligence.

**Cost**: Free (included in Apollo subscription)

---

#### 4. HUBSPOT_API_KEY

**Name**: `HUBSPOT_API_KEY`
**Value**: Your HubSpot private app token (starts with `pat-na1-...`)

**How to get it**:
1. Go to: HubSpot → Settings → Integrations → Private Apps
2. Click "Create a private app"
3. Name it: "MEDDICC Agent"
4. Add scopes (CRITICAL - must have ALL of these):

**Required Scopes**:
```
crm.objects.deals.read
crm.objects.deals.write
crm.objects.companies.read
crm.objects.contacts.read
crm.objects.notes.read
crm.objects.notes.write
```

5. Click "Create app"
6. Copy the access token (starts with `pat-na1-...`)

**Cost**: Free (HubSpot private apps are free)

---

#### 5. FIREWORKS_API_KEY (Optional - for Kimi K3)

**Name**: `FIREWORKS_API_KEY`
**Value**: Your Fireworks AI API key

**How to get it**:
- Go to: https://fireworks.ai/
- Sign up / Log in
- Go to: Account → API Keys
- Create new key
- Copy the key

**When to use**:
- Only needed if using Kimi K3 hybrid architecture
- Saves ~10% on API costs ($93.60/month vs $103.50/month)
- Optional - agent works without it (uses all-Claude)

**Cost**: ~$93/month for 50 deals/night (vs $103 for all-Claude)

---

### Verify All Secrets Added

After adding all secrets, you should see:

```
ANTHROPIC_API_KEY     ••••••••••••••••
FIREFLIES_API_KEY     ••••••••••••••••
APOLLO_API_KEY        ••••••••••••••••
HUBSPOT_API_KEY       ••••••••••••••••
FIREWORKS_API_KEY     ••••••••••••••••  (optional)
```

**Note**: `GITHUB_TOKEN` is automatically provided by GitHub Actions - don't add it manually.

---

## Step 2: Enable GitHub Actions

### Check if Actions is Enabled

1. Go to: https://github.com/jeff266/AI_for_revops_lecture_6/actions
2. If you see a message "Workflows aren't being run on this repository", click **"I understand my workflows, go ahead and enable them"**

### Verify Workflow File Exists

1. Go to: https://github.com/jeff266/AI_for_revops_lecture_6/blob/main/.github/workflows/nightly.yml
2. Confirm the file exists and shows:

```yaml
name: MEDDICC Agent Nightly Run

on:
  schedule:
    - cron: '0 2 * * *'  # 2am UTC daily
  workflow_dispatch:  # Manual trigger
```

---

## Step 3: Run a Manual Test

**Before waiting for the 2am cron**, test the workflow manually:

### Trigger Manual Run

1. Go to: https://github.com/jeff266/AI_for_revops_lecture_6/actions
2. Click on **"MEDDICC Agent Nightly Run"** in the left sidebar
3. Click **"Run workflow"** button (top right)
4. Select branch: `main`
5. Click **"Run workflow"** (green button)

### Monitor the Run

1. A new workflow run will appear (refreshing in real-time)
2. Click on the run to see details
3. Click on the job **"run-meddicc-agent"**
4. Watch the logs in real-time

**Expected duration**: 15-45 minutes (depends on number of active deals)

---

## Step 4: Interpret the Results

### Success Indicators ✅

Look for these in the logs:

```
✓ Connected to Fireflies
✓ Connected to Apollo.io
✓ Connected to HubSpot
Found X active deals

Processing deals...
[1/X] Company Name
  Found N calls (M Fireflies, P Apollo)
  Building cumulative state from N historical calls...
  Running MEDDICC generator/evaluator loop...
  ✓ Analysis passed after N iteration(s)
  Updating HubSpot deal note...
  ✓ Complete

RUN SUMMARY
Deals processed: X
Deals skipped: Y
Errors: 0
Passed evaluations: X/X (100%)

✓ Nightly run complete
```

### What Happens on Success

1. **HubSpot Notes Updated**:
   - Each deal gets a note titled "## MEDDICC Analysis"
   - Note includes deal context, MEDDICC assessment, next steps
   - Previous MEDDICC notes are replaced (not appended)

2. **Learning Files Created**:
   - `memory/learnings/YYYY-MM-DD_NNN.json` for each deal
   - Tracks performance, failures, proposed instructions

3. **PR Created**:
   - Branch: `agent/learnings-YYYY-MM-DD`
   - Title: "chore: MEDDICC agent learnings — YYYY-MM-DD"
   - Appends new learnings to `prompts/CLAUDE.md`

4. **Memory Committed**:
   - Learning files committed to `main` branch
   - Automatic commit: "Update MEDDICC agent memory [skip ci]"

### Common Errors and Fixes

#### Error: "401 Unauthorized" (HubSpot)

**Cause**: API key expired or missing scopes

**Fix**:
1. Go to HubSpot → Settings → Private Apps → MEDDICC Agent
2. Verify all 6 scopes are enabled
3. If not, add missing scopes
4. Regenerate token if needed
5. Update `HUBSPOT_API_KEY` secret in GitHub

---

#### Error: "No calls found for company"

**Cause**: Company name mismatch between HubSpot and Fireflies/Apollo

**Fix**:
- This is expected for some deals (no recorded calls)
- Deals with <2 calls are automatically skipped
- Check that company names match exactly in HubSpot and call titles

---

#### Error: "ANTHROPIC_API_KEY not set"

**Cause**: Secret not configured correctly

**Fix**:
1. Go to repository secrets
2. Verify `ANTHROPIC_API_KEY` exists
3. Check for typos in secret name (case-sensitive!)
4. Re-add secret if needed

---

#### Error: "Failed to parse evaluator JSON"

**Cause**: LLM returned invalid JSON (rare)

**Fix**:
- Usually self-corrects on next iteration
- If persistent, check learning entry for `raw_content`
- May need to adjust evaluator rubric

---

## Step 5: Review First PR

After the successful run, a PR will be automatically created.

### Find the PR

1. Go to: https://github.com/jeff266/AI_for_revops_lecture_6/pulls
2. Look for: "chore: MEDDICC agent learnings — YYYY-MM-DD"

### Review PR Contents

The PR will contain:

1. **Changes to prompts/CLAUDE.md**:
   - New learnings appended under "## Learnings" section
   - Example: "Always quote specific evidence from calls, not generic statements"

2. **Daily diff explanation**:
   - File: `memory/diffs/YYYY-MM-DD.md`
   - Summary of deals processed
   - Common failures and strong components

### Merge or Close

**Option 1: Merge** (recommended for first run)
- Click "Merge pull request"
- These learnings will improve future runs

**Option 2: Close** (if you want to review manually first)
- Close without merging
- Can manually add learnings later

---

## Step 6: Verify HubSpot Updates

Check that deal notes were updated:

1. Log into HubSpot
2. Go to Sales → Deals
3. Open an active deal that has recorded calls
4. Check Timeline for new note titled "## MEDDICC Analysis"
5. Verify note contains:
   - Deal context
   - MEDDICC component assessments (M, E, D, D, I, C, C)
   - Summary & recommended actions

**Example Note**:
```markdown
## MEDDICC Analysis
**Generated:** 2026-07-29 02:15 UTC
**Based on:** 5 recorded calls

# MEDDICC Analysis: Acme Corp

## Deal Context
- **Stage**: Demo Conducted
- **ARR**: $95,000
- **Expected Close**: 2026-09-15
...
```

---

## Step 7: Set Up Monitoring (Optional)

### Email Notifications

1. Go to: https://github.com/jeff266/AI_for_revops_lecture_6/settings/notifications
2. Enable "Actions" notifications
3. Choose email frequency

### Slack Notifications (Advanced)

Add to `.github/workflows/nightly.yml`:

```yaml
- name: Notify Slack on failure
  if: failure()
  uses: slackapi/slack-github-action@v1
  with:
    payload: |
      {
        "text": "MEDDICC Agent failed: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
      }
  env:
    SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
```

---

## Cron Schedule

The workflow runs automatically at **2am UTC daily**.

### Convert to Your Timezone

| Timezone | Cron Time (UTC) | Local Time |
|----------|-----------------|------------|
| PST (UTC-8) | `0 2 * * *` | 6pm previous day |
| EST (UTC-5) | `0 2 * * *` | 9pm previous day |
| CST (UTC-6) | `0 2 * * *` | 8pm previous day |
| GMT (UTC+0) | `0 2 * * *` | 2am same day |

### Change Schedule (Optional)

To run at a different time, edit `.github/workflows/nightly.yml`:

```yaml
schedule:
  - cron: '0 14 * * *'  # 2pm UTC (9am EST)
```

**Cron syntax**: `minute hour day month weekday`
- `0 2 * * *` = Every day at 2am UTC
- `0 14 * * 1-5` = Weekdays at 2pm UTC

---

## Cost Management

### Monitor GitHub Actions Minutes

1. Go to: https://github.com/settings/billing
2. Check "Actions & Packages"
3. Free tier: 2000 minutes/month

**Usage**: ~30-60 minutes per run
- 30 runs/month = 900-1800 minutes
- Well within free tier

### Monitor Anthropic API Costs

1. Go to: https://console.anthropic.com/settings/billing
2. Set budget alert: $150/month
3. Monitor daily usage

**Expected**: $93-103/month for 50 deals/night

---

## Troubleshooting

### Workflow Not Running

**Check**:
1. Actions enabled? (Settings → Actions → Allow all actions)
2. Workflow file exists? (`.github/workflows/nightly.yml`)
3. Branch is `main`? (Cron only runs on default branch)

### Workflow Runs But Fails

**Check logs**:
1. Go to Actions tab
2. Click failed run
3. Click job name
4. Read error message
5. Common fixes:
   - Missing API key → Add to secrets
   - Invalid scope → Update HubSpot app
   - Rate limit → Wait and retry

### No PR Created

**Possible reasons**:
1. No new learnings (all passed on first iteration)
2. PR creation failed (check logs)
3. Already have open PR for same day

---

## Success Checklist

After first successful run, verify:

- [x] Workflow completed without errors
- [x] HubSpot deal notes updated
- [x] Learning files created in `memory/learnings/`
- [x] PR created with daily learnings
- [x] Memory committed to `main` branch
- [x] No critical errors in logs

---

## Next Steps

### Week 1: Daily Monitoring
- Review workflow logs daily
- Check HubSpot note quality
- Merge daily PRs

### Week 2: Sales Team Feedback
- Ask sales team about MEDDICC note usefulness
- Identify gaps in analysis
- Adjust prompts if needed

### Day 30: Full Rewrite
- System automatically creates full rewrite PR
- Review synthesized CLAUDE.md
- Merge to activate improved prompts

---

## Quick Reference

**Repository**: https://github.com/jeff266/AI_for_revops_lecture_6

**Key URLs**:
- Actions: https://github.com/jeff266/AI_for_revops_lecture_6/actions
- Secrets: https://github.com/jeff266/AI_for_revops_lecture_6/settings/secrets/actions
- PRs: https://github.com/jeff266/AI_for_revops_lecture_6/pulls

**Support**:
- Workflow logs: Actions tab → Click run → Click job
- Learning data: `memory/learnings/*.json`
- Errors: Check workflow logs and HubSpot API responses

---

**Last Updated**: 2026-07-29
**Version**: 1.0
