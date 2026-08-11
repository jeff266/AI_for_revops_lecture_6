# RevOps MEDDICC Agent

Nightly AI-powered deal qualification for your HubSpot pipeline.
Analyzes sales calls, scores every active deal on your qualification
methodology — MEDDICC by default; MEDDPIC, SPICED, and BANT supported
via config/client.yaml — writes scores back to HubSpot, and gets
smarter over time.

---

## Setup — three steps

### Step 1 · Credentials

Open this repo in Claude Code. If this is a fresh fork,
Claude Code will detect the missing config files and guide
you through setup automatically.

Just open the project and say: **"set up this repo"**

Claude Code will:
- Walk through every credential and API key
- Write config/client.yaml and config/context.yaml
- Discover your HubSpot stage IDs
- Set up Supabase
- Verify everything before the first run

### Step 2 · Add GitHub Secrets

After Claude Code generates your .env file, add the
values as GitHub Secrets:

**repo → Settings → Environments → Agent → Add Secret**

Or with the GitHub CLI:
```bash
gh secret set --env Agent --env-file .env
```

### Step 3 · First run

Go to: **Actions → MEDDICC Agent Nightly Run → Run workflow**

Watch the logs. First run analyzes your full active pipeline.
After that the agent runs every night at 2am UTC automatically.

### What runs automatically

| Time (UTC) | Job | What it does |
|---|---|---|
| 1:00 AM | Daily Deal ETL | Updates active deal index from HubSpot |
| 1:30 AM | Daily Calls ETL | Fetches new calls for active deals |
| 2:00 AM | MEDDICC Agent | Analyzes deals, writes to HubSpot + Supabase |

---

## Call intelligence platforms

The agent supports two call recording platforms:

**Fireflies** (default) — Fireflies.ai call transcripts
- Most common for SMB/mid-market
- Simple API key authentication
- Set `call_tools.primary: "fireflies"` in config/client.yaml

**Gong** — Gong.io enterprise call intelligence
- Enterprise standard for larger sales teams
- Provides richer structured data (topics, action items, talk time)
- Requires Access Key + Access Key Secret
- Set `call_tools.primary: "gong"` in config/client.yaml

Claude Code will automatically detect your choice during setup
and collect the right credentials.

---

## What runs nightly

```
2am UTC: GitHub Actions fires
  → Load active deals from deal index
  → For each deal: load call cache → context builder (Haiku)
  → Generator (Sonnet) → Evaluator (Haiku) → Reflection gate
  → Write analysis to GitHub output/
  → Write 6 MEDDICC scores to HubSpot deal properties
  → Write analysis to Supabase for query layer
  → Update CLAUDE.md via PR if new patterns emerge
```

---

## Files to know

| File | What it does |
|---|---|
| `scripts/run_nightly.py` | Main orchestration — runs every night |
| `scripts/meddicc_agent.py` | Generator + evaluator + reflection loop |
| `scripts/etl_calls.py` | Builds call cache from CSV exports |
| `scripts/etl_deals.py` | Builds deal index from HubSpot |
| `prompts/CLAUDE.md` | Generator instructions — edit to calibrate |
| `prompts/evaluator_rubric.md` | Evaluation criteria — auto-improves |
| `config/client.yaml` | Your HubSpot stage IDs and thresholds |
| `config/context.yaml` | Your competitors, objections, feature gaps |
| `memory/calls/` | Call cache — 1 JSON per company |
| `memory/learnings/` | What the agent is learning |
| `output/` | MEDDICC analysis files |

---

## Costs

| Scenario | Cost |
|---|---|
| First full pipeline run | ~$3-5 |
| Nightly steady state | ~$0.10-0.30 |
| Monthly total | ~$10-15 |

---

## Skills for Claude.ai

Once the agent is running, install these skills in Claude.ai
for on-demand analysis:

- `skills/revops-agent-setup.skill` — credential setup wizard
- `skills/revops-client-context.skill` — client context onboarding

Open each file in Claude.ai and click Save skill.
