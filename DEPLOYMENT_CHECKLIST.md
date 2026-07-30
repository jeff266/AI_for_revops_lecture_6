# MEDDICC Agent Deployment Checklist

## Pre-Deployment (Local Testing)

### Environment Setup
- [ ] Python 3.11+ installed
- [ ] Dependencies installed: `pip install -r requirements.txt`
- [ ] All API keys obtained and documented
- [ ] `.env` file created with test keys (never commit!)

### API Key Validation
- [ ] Anthropic API key tested (claude-sonnet-4-5 and claude-haiku-4-5 access)
- [ ] Fireflies API key tested (GraphQL access)
- [ ] Apollo.io API key tested (video meetings access)
- [ ] HubSpot private app created with correct scopes:
  - [ ] `crm.objects.deals.read`
  - [ ] `crm.objects.deals.write`
  - [ ] `crm.objects.companies.read`
  - [ ] `crm.objects.contacts.read`
  - [ ] `crm.objects.notes.read`
  - [ ] `crm.objects.notes.write`

### Component Testing
- [ ] `python scripts/fireflies_client.py` - Shows connected ✅
- [ ] `python scripts/apollo_client.py` - Shows connected ✅
- [ ] `python scripts/hubspot_deals.py` - Shows active deals ✅
- [ ] `python scripts/context_builder.py` - Generates cumulative state ✅
- [ ] `python scripts/meddicc_agent.py` - Completes generator/evaluator loop ✅
- [ ] `python scripts/github_memory.py` - Creates test learning file ✅

### Full System Test
- [ ] `python scripts/test_setup.py` - All 8 tests pass ✅
- [ ] Review test output for warnings
- [ ] Verify memory files created in `memory/` directories

### Safety Checks
- [ ] HubSpot sandbox account available (recommended for initial testing)
- [ ] Backup of existing HubSpot deal notes (if updating production)
- [ ] Rate limit considerations documented
- [ ] Cost estimate for Anthropic API usage calculated

## Deployment (GitHub Actions)

### Repository Setup
- [ ] Repository created on GitHub
- [ ] Code pushed to `main` branch
- [ ] `.gitignore` in place (no API keys committed)
- [ ] README.md reviewed and updated
- [ ] SETUP.md reviewed

### GitHub Secrets Configuration
Navigate to: `Settings` → `Secrets and variables` → `Actions`

- [ ] `ANTHROPIC_API_KEY` added
- [ ] `FIREFLIES_API_KEY` added
- [ ] `APOLLO_API_KEY` added
- [ ] `HUBSPOT_API_KEY` added
- [ ] All secrets tested (no trailing spaces/newlines)

### GitHub Actions Configuration
- [ ] Actions enabled in repository settings
- [ ] Workflow file validated: `.github/workflows/nightly.yml`
- [ ] Cron schedule confirmed: `'0 2 * * *'` (2am UTC)
- [ ] Manual trigger enabled for testing

### First Test Run
- [ ] Navigate to Actions tab
- [ ] Select "MEDDICC Agent Nightly Run"
- [ ] Click "Run workflow" → "Run workflow"
- [ ] Monitor run progress in real-time
- [ ] Check for errors in logs
- [ ] Verify learning files created in `memory/`
- [ ] Confirm HubSpot notes updated (if using production)

### First PR Review
- [ ] PR created automatically (check Pull Requests tab)
- [ ] Branch name: `agent/learnings-YYYY-MM-DD`
- [ ] Review changes to `prompts/CLAUDE.md`
- [ ] Review diff explanation in `memory/diffs/YYYY-MM-DD.md`
- [ ] Verify learning entries in `memory/learnings/`
- [ ] Merge PR if changes look good

## Post-Deployment Monitoring

### Week 1: Daily Checks
- [ ] Day 1: Verify first nightly run completed
- [ ] Day 2: Review PR and merge
- [ ] Day 3: Check HubSpot notes with sales team
- [ ] Day 4: Review learning patterns in `memory/learnings/`
- [ ] Day 5: Validate no API errors or timeouts
- [ ] Day 6-7: Monitor for consistency

### Week 2: Quality Assessment
- [ ] Sales team feedback on MEDDICC note quality
- [ ] Check average iterations to pass (target: < 2.0)
- [ ] Review common weak components
- [ ] Identify deals with repeated failures
- [ ] Adjust prompts if needed

### Week 3: Optimization
- [ ] Review API costs (Anthropic usage)
- [ ] Check GitHub Actions minutes used
- [ ] Optimize for high-volume companies (>50 calls)
- [ ] Consider filtering criteria for deals to process

### Day 30: First Full Rewrite
- [ ] Full rewrite PR created automatically
- [ ] Review synthesized CLAUDE.md
- [ ] Validate all learnings incorporated
- [ ] Compare quality before/after rewrite
- [ ] Merge full rewrite PR
- [ ] Observe impact on pass rates

## Ongoing Maintenance

### Daily
- [ ] Check Actions run status (green/red)
- [ ] Review and merge incremental PRs

### Weekly
- [ ] Review learning artifacts
- [ ] Check for API errors or warnings
- [ ] Monitor pass rate trends

### Monthly
- [ ] Review and merge full rewrite PR (day 30)
- [ ] Analyze cumulative performance metrics
- [ ] Rotate API keys (security best practice)
- [ ] Archive old learning files (>90 days)

### Quarterly
- [ ] Sales team feedback session
- [ ] Evaluate ROI and time savings
- [ ] Consider feature enhancements
- [ ] Review and update documentation

## Rollback Plan

If issues occur:

### Minor Issues (Low pass rate, formatting errors)
1. Edit `prompts/CLAUDE.md` directly
2. Commit changes to `main`
3. Next run will use updated prompts

### Major Issues (API errors, HubSpot data corruption)
1. Disable workflow: `.github/workflows/nightly.yml` → `workflow_dispatch:` only
2. Investigate root cause
3. Fix and test locally
4. Re-enable workflow

### Emergency Stop
1. Navigate to `.github/workflows/nightly.yml`
2. Comment out cron schedule
3. Commit to `main`
4. Workflow stops running automatically

## Success Metrics

Target KPIs after 30 days:
- [ ] Pass rate: >80%
- [ ] Average iterations: <2.0
- [ ] HubSpot notes updated: 100% of deals with calls
- [ ] Sales team satisfaction: Positive feedback
- [ ] Zero data corruption incidents
- [ ] API costs within budget

## Support Contacts

| Issue Type | Contact | Channel |
|------------|---------|---------|
| API Errors | Engineering | GitHub Issues |
| Sales Feedback | Sales Leadership | Slack #sales-ops |
| Cost Concerns | Finance/RevOps | Email |
| Security Issues | Security Team | Urgent Slack |

## Sign-Off

- [ ] Engineering Lead: _________________ Date: _______
- [ ] Sales Leadership: _________________ Date: _______
- [ ] RevOps: __________________________ Date: _______

---

**Deployment Date**: __________
**Deployed By**: __________
**Production URL**: __________
**Monitoring Dashboard**: __________
