# MEDDICC Agent Setup Guide

Complete setup instructions for deploying the MEDDICC analysis agent.

## Prerequisites

- Python 3.11+
- GitHub repository with Actions enabled
- API access to:
  - Anthropic (Claude API)
  - Fireflies (GraphQL API)
  - Apollo.io (Video meetings)
  - HubSpot (CRM)

## Local Development Setup

### 1. Install Dependencies

```bash
cd meddicc-agent
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file or export variables:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export FIREFLIES_API_KEY="5313ce93-..."  # From Fireflies settings
export APOLLO_API_KEY="G6LzXb3K..."      # Apollo.io API key
export HUBSPOT_API_KEY="pat-na1-..."     # HubSpot private app token
```

### 3. Test Individual Components

Test each client to verify API connectivity:

```bash
# Test Fireflies (should show calls)
cd scripts
python fireflies_client.py

# Test Apollo (should show video meetings)
python apollo_client.py

# Test HubSpot (should show active deals)
python hubspot_deals.py

# Test context builder (requires ANTHROPIC_API_KEY)
python context_builder.py

# Test MEDDICC agent (full generator/evaluator loop)
python meddicc_agent.py

# Test memory layer
python github_memory.py
```

Expected outputs:
- ✅ Each test should show "Connected" and sample data
- ❌ If any fail, check API keys and network connectivity

### 4. Test End-to-End (Single Deal)

Before running the full nightly job, test with one company:

```python
# Create test_single_deal.py
from fireflies_client import get_fireflies_client
from context_builder import build_cumulative_meddicc
from meddicc_agent import run_agent

# Pick a company with multiple recorded calls
company_name = "Acme Corp"  # Replace with real company

# Get calls
fireflies = get_fireflies_client()
calls = fireflies.search_by_company(company_name, max_results=10)

if len(calls) < 2:
    print(f"Need at least 2 calls for {company_name}")
    exit(1)

# Format summaries
summaries = [fireflies.format_summary_for_meddicc(c) for c in calls]

# Split historical vs recent
recent = summaries[-1]
historical = summaries[:-1]

# Build cumulative state
cumulative = build_cumulative_meddicc(historical, company_name)

# Mock deal context (replace with real HubSpot data)
deal_context = {
    "deal": {"properties": {"dealname": f"{company_name} Deal", "dealstage": "presentationscheduled", "incremental_arr": "50000"}},
    "company": {"properties": {"name": company_name}},
    "contacts": []
}

# Run agent
result = run_agent(recent, cumulative, deal_context)

print("\n" + "="*80)
print("ANALYSIS RESULT")
print("="*80)
print(result['draft'])
print("\n" + "="*80)
print(f"Passed: {result['passed']} | Iterations: {result['iterations']}")
print("="*80)
```

Run:
```bash
python test_single_deal.py
```

### 5. Run Full Nightly Job (Local)

Test the complete orchestration:

```bash
python scripts/run_nightly.py
```

This will:
1. Fetch all active HubSpot deals
2. Find calls for each company
3. Build cumulative MEDDICC states
4. Generate and evaluate analyses
5. Update HubSpot notes
6. Save learnings
7. Generate PR (if in GitHub Actions)

**WARNING**: This updates production HubSpot data. Consider:
- Using a HubSpot sandbox/test account
- Limiting to specific deals in code
- Reviewing generated notes before running

## Production Deployment (GitHub Actions)

### 1. Push to GitHub

```bash
cd meddicc-agent
git init
git add .
git commit -m "Initial MEDDICC agent setup"
git remote add origin https://github.com/YOUR_ORG/meddicc-agent.git
git push -u origin main
```

### 2. Configure Repository Secrets

Go to: `Settings` → `Secrets and variables` → `Actions` → `New repository secret`

Add:
- `ANTHROPIC_API_KEY`
- `FIREFLIES_API_KEY`
- `APOLLO_API_KEY`
- `HUBSPOT_API_KEY`

**Note**: `GITHUB_TOKEN` is automatically provided by Actions.

### 3. Enable GitHub Actions

- Go to `Actions` tab
- Click "I understand my workflows, go ahead and enable them"

### 4. Verify Workflow

Check `.github/workflows/nightly.yml`:
- Cron schedule: `'0 2 * * *'` (2am UTC daily)
- Adjust timezone if needed

### 5. Manual Test Run

Before waiting for the cron:

1. Go to `Actions` → `MEDDICC Agent Nightly Run`
2. Click `Run workflow` → `Run workflow`
3. Monitor the run in real-time
4. Check for errors or warnings

### 6. Review First PR

After the first successful run:
1. A PR will be created automatically
2. Branch: `agent/learnings-YYYY-MM-DD`
3. Review the diff in `prompts/CLAUDE.md`
4. Check `memory/diffs/YYYY-MM-DD.md` for explanation
5. Merge if looks good

## API Key Setup

### Anthropic API

1. Go to: https://console.anthropic.com/
2. Create API key
3. Format: `sk-ant-...`

### Fireflies API

1. Go to: Fireflies Settings → Integrations → API
2. Generate API key
3. Format: UUID string

### Apollo.io API

1. Go to: Apollo.io Settings → API
2. Create API key
3. Format: alphanumeric string

**Note**: This is Apollo.io (video meetings), NOT Apollo.io (sales intelligence)

### HubSpot API

1. Go to: HubSpot Settings → Integrations → Private Apps
2. Create app with scopes:
   - `crm.objects.deals.read`
   - `crm.objects.deals.write`
   - `crm.objects.companies.read`
   - `crm.objects.contacts.read`
   - `crm.objects.notes.read`
   - `crm.objects.notes.write`
3. Generate token
4. Format: `pat-na1-...`

## Monitoring & Maintenance

### Check Nightly Run Status

- GitHub Actions tab shows run history
- Green = success, Red = failure
- Click run for detailed logs

### Review Learning Artifacts

Download from Actions run:
- `Artifacts` → `meddicc-learnings-XXX.zip`
- Contains all learning JSON files and diffs

### Monitor Memory Growth

```bash
# Check learning entries
ls -lh memory/learnings/ | wc -l

# Check total size
du -sh memory/
```

Archive old learnings after 90 days (retention policy in workflow).

### Merge PRs Regularly

- Incremental PRs: Daily
- Full rewrite PRs: Every 30 days

Unmerged PRs won't affect agent operation (uses current `main` CLAUDE.md).

## Troubleshooting

### "No calls found for company"

**Cause**: Company name mismatch between HubSpot and Fireflies/Apollo

**Fix**:
1. Check exact company name in HubSpot
2. Check call titles in Fireflies
3. Adjust search logic if needed (fuzzy matching)

### "Evaluator parse error"

**Cause**: Haiku returned invalid JSON

**Fix**:
1. Check `evaluator_rubric.md` format
2. Review learning entry for `raw_content` field
3. May need to adjust rubric instructions

### "Context builder timeout"

**Cause**: Too many historical calls (>50)

**Fix**:
1. Limit `max_results` in call search
2. Use sampling for very active accounts
3. Consider chunking for companies with 100+ calls

### "HubSpot 401 Unauthorized"

**Cause**: API token expired or invalid scopes

**Fix**:
1. Regenerate HubSpot private app token
2. Verify all required scopes are enabled
3. Update `HUBSPOT_API_KEY` secret

### "GitHub Actions quota exceeded"

**Cause**: Free tier limits (2000 min/month)

**Fix**:
1. Reduce frequency (every other day)
2. Limit deals processed per run
3. Upgrade to paid Actions tier

## Performance Optimization

### Reduce API Costs

- Use Haiku for more operations
- Cache cumulative states (requires DB)
- Process only changed deals (requires state tracking)

### Speed Up Runs

- Parallel deal processing (requires async)
- Limit call history to last 90 days
- Use call summaries only (already implemented)

### Improve Quality

- Increase max iterations (current: 3)
- Add human review step before HubSpot update
- A/B test different prompts

## Security Best Practices

- ✅ Never commit API keys to git
- ✅ Use repository secrets for credentials
- ✅ Limit private app scopes to minimum needed
- ✅ Enable 2FA on all service accounts
- ✅ Rotate API keys quarterly
- ✅ Review learning data for PII before sharing
- ✅ Use branch protection for `main`

## Next Steps

After successful deployment:

1. **Week 1**: Monitor daily, review all PRs
2. **Week 2**: Verify HubSpot note quality with sales team
3. **Week 3**: Adjust prompts based on feedback
4. **Day 30**: Review first full rewrite synthesis
5. **Month 2**: Analyze trends in learning data

## Support

For issues:
1. Check workflow logs in GitHub Actions
2. Review learning artifacts
3. Test components individually
4. Check API quotas and rate limits

---

**Setup Date**: 2026-07-29
**Last Reviewed**: 2026-07-29
