# MEDDICC Analysis Agent

Production MEDDICC analysis system that runs nightly as a GitHub Actions cron job.

## Overview

This agent analyzes sales calls and generates MEDDICC (Metrics, Economic Buyer, Decision Criteria, Decision Process, Identified Pain, Champion, Competition) assessments for active deals.

**Key Feature**: Builds cumulative MEDDICC state from ALL historical calls before analyzing the most recent one, preventing redundant gap identification.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ GitHub Actions (Cron: 2am UTC daily)                        │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ run_nightly.py - Main Orchestrator                          │
│  1. Get active HubSpot deals                                │
│  2. Find Fireflies + Apollo calls per company               │
│  3. Build cumulative MEDDICC state (Haiku)                  │
│  4. Generate analysis (Sonnet 4.6)                          │
│  5. Evaluate (Haiku 4.5)                                    │
│  6. Update HubSpot deal notes                               │
│  7. Save learnings                                          │
│  8. Create PR (incremental or 30-day rewrite)               │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Memory Layer (GitHub repo)                                  │
│  ├─ memory/learnings/      (learning entries)               │
│  ├─ memory/versions/       (CLAUDE.md snapshots)            │
│  ├─ memory/diffs/          (daily changelogs)               │
│  └─ memory/meta/           (counter.json)                   │
└─────────────────────────────────────────────────────────────┘
```

## Components

### Core Scripts

- **run_nightly.py** - Main orchestration
- **meddicc_agent.py** - Generator/evaluator loop (Sonnet 4.6 + Haiku 4.5)
- **context_builder.py** - Cumulative MEDDICC state builder (Haiku 4.5)
- **github_memory.py** - Memory layer manager

### API Clients

- **fireflies_client.py** - Fireflies call summaries by company
- **apollo_client.py** - Apollo.io video meetings by company
- **hubspot_deals.py** - HubSpot deal management and notes

### Prompts

- **prompts/CLAUDE.md** - Generator instructions (evolves via learnings)
- **prompts/evaluator_rubric.md** - Evaluation criteria

## Environment Variables

Required secrets in GitHub Actions:

```bash
ANTHROPIC_API_KEY      # Claude API key
FIREFLIES_API_KEY      # Fireflies GraphQL API key
APOLLO_API_KEY         # Apollo.io API key
HUBSPOT_API_KEY        # HubSpot private app token
GITHUB_TOKEN           # Auto-provided by GitHub Actions

# Optional: For Kimi K3 cost optimization (~70% cost reduction)
FIREWORKS_API_KEY      # Fireworks AI API key for Kimi K3
```

### Cost Optimization with Kimi K3

The system supports a **Kimi K3 hybrid architecture** for ~70% cost reduction on context building and evaluation:

- **All-Claude**: $103.50/month (50 deals/night)
- **Kimi Hybrid**: $93.60/month (~10% savings)

See `KIMI_COST_COMPARISON.md` for detailed analysis and setup instructions.

**To enable Kimi K3:**
1. Get Fireworks API key: https://fireworks.ai/
2. Set `FIREWORKS_API_KEY` environment variable
3. Update imports in `run_nightly.py` to use Kimi modules

Proven in production on Frontera contract extraction project (400+ deals).

## Learning Loop

### Incremental Updates (Daily)

1. Process all active deals
2. Collect proposed instructions from evaluator feedback
3. Check if instruction already in CLAUDE.md
4. Append new learnings to CLAUDE.md
5. Create PR with daily diff

### Full Rewrite (Every 30 Days)

1. Synthesize all learnings from past 30 days
2. Use Sonnet 4.6 to restructure CLAUDE.md
3. Create PR with full file replacement
4. Reset counter

## Memory Structure

```
memory/
├── learnings/
│   ├── 2026-07-29_001.json   # Learning from run #1
│   ├── 2026-07-29_002.json   # Learning from run #2
│   └── ...
├── versions/
│   ├── CLAUDE_2026-07-29.md  # Daily snapshot
│   └── ...
├── diffs/
│   ├── 2026-07-29.md         # Daily changelog
│   └── ...
└── meta/
    └── counter.json          # Run counter and rewrite schedule
```

## Learning Entry Schema

```json
{
  "id": "2026-07-29_001",
  "timestamp": "2026-07-29T02:15:00Z",
  "company": "Acme Corp",
  "deal_id": "123456",
  "loop_performance": {
    "iterations_to_pass": 2,
    "passed": true,
    "budget_exhausted": false
  },
  "cumulative_calls_context": 3,
  "iteration_1_failures": ["Evidence quality"],
  "components_weak": ["Champion"],
  "components_strong": ["Metrics", "Economic Buyer"],
  "required_changes_injected": "Added specific evidence",
  "resolution": "Passed on iteration 2",
  "proposed_instruction": "Always quote specific evidence from calls"
}
```

## Local Development

### Setup

```bash
cd meddicc-agent
pip install anthropic requests PyGithub

# Set environment variables
export ANTHROPIC_API_KEY="..."
export FIREFLIES_API_KEY="..."
export APOLLO_API_KEY="..."
export HUBSPOT_API_KEY="..."
```

### Test Individual Components

```bash
# Test Fireflies client
python scripts/fireflies_client.py

# Test HubSpot deals
python scripts/hubspot_deals.py

# Test context builder
python scripts/context_builder.py

# Test MEDDICC agent
python scripts/meddicc_agent.py

# Test memory layer
python scripts/github_memory.py
```

### Run Full Pipeline (Local)

```bash
python scripts/run_nightly.py
```

## Workflow Schedule

- **Cron**: 2am UTC daily
- **Manual Trigger**: Via GitHub Actions UI

## Error Handling

If the nightly run fails:
1. GitHub Actions creates an issue with label `meddicc-agent-error`
2. Issue includes workflow run link and timestamp
3. Learning artifacts uploaded even on failure
4. Memory state preserved for recovery

## Monitoring

Key metrics tracked in learning entries:
- Pass rate (% of deals that pass evaluation)
- Average iterations to pass
- Most common weak components
- Most common failure reasons

View in:
- Daily diffs (`memory/diffs/*.md`)
- Learning entries (`memory/learnings/*.json`)
- PR descriptions

## Production Deployment

1. Fork or clone this repo
2. Add required secrets to GitHub repository settings
3. Enable GitHub Actions
4. Workflow runs automatically at 2am UTC
5. Review and merge PRs with learnings

## Design Decisions

### Why cumulative state?

Evaluating a single call in isolation produces incomplete analyses. If the Economic Buyer was identified on Call 1, a Call 3 analysis shouldn't flag it as a gap.

### Why two models?

- **Sonnet 4.6**: Higher quality for generation (analysis writing)
- **Haiku 4.5**: Faster and cheaper for evaluation (pass/fail checks)

### Why 30-day rewrites?

Prevents instruction bloat. Instead of accumulating 30+ appended learnings, we synthesize them into a cleaner, restructured prompt.

### Why GitHub for memory?

- Version control for all learnings
- PR review workflow for prompt changes
- Artifact retention
- Free hosting

## Future Enhancements

- [ ] Deal risk scoring based on MEDDICC completeness
- [ ] Slack notifications for high-risk deals
- [ ] Trend analysis dashboard
- [ ] Multi-language support
- [ ] Integration with Gong for additional call sources

## License

Internal GrowthBook tool.

---

**Last Updated**: 2026-07-29
**Version**: 1.0.0
