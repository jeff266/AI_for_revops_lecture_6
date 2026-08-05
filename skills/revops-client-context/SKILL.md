---
name: revops-client-context
description: >
  Onboard a new client by building their competitive, product, and
  sales context. Use this skill when setting up a new deployment,
  calibrating the MEDDICC agent for a specific client, or updating
  context when the competitive landscape changes. Produces four files:
  config/context.yaml, config/client.yaml, prompts/CLAUDE.md, and
  prompts/evaluator_rubric.md. Triggers on: start client onboarding,
  set up context, configure the agent, calibrate for my client,
  update competitive context, who are our competitors, what are our
  objections.
---

# RevOps Client Context Onboarding

Build the context baseline that makes every intelligence layer accurate.
Read references/context-schema.md before starting.

Six phases. Complete each before moving to the next.

## Phase 1 — Product and ICP

Ask one at a time:
1. "What does your product do in one sentence? Be specific."
2. "Who is your ICP? Company size, industry, and buyer title."
3. "What is your primary differentiator?"
4. "What qualification methodology do you use?"
5. "What does a good first call look like for your best reps?"

Push back on vague answers. Ask for real examples.

## Phase 2 — Competitive landscape

Ask them to name all competitors first, then go through each one:
- Full name as it appears in prospect conversations
- Type: direct / adjacent / internal_tool / status_quo
- What prospects say when they mention this competitor
- How the rep should respond
- When you win vs lose against them
- Any aliases (other names it appears as in transcripts)

Prompt: "Any internal tools? Any build-vs-buy situations?"

## Phase 3 — Objections

For each objection (collect at least 5):
1. "What are the actual words a prospect uses?"
2. "Which stage does this typically appear at?"
3. "What's the best rep response?"
4. "Category: switching cost / budget / timing / technical /
   internal politics / product gap / trust / other?"

Prompt: "What kills the most deals? What comes up earliest?"

## Phase 4 — Feature gaps and value metrics

Feature gaps — for each:
- The feature description
- Exact language prospects use when asking about it
- Roadmap item or genuine gap?

Value metrics:
"What quantifiable outcomes do champions use for the business case?"

## Phase 5 — HubSpot stage configuration

Tell the user to run: python scripts/discover_stages.py
Ask them to paste the output.

Parse it and identify stages to EXCLUDE:
- Meeting Set equivalents (too early)
- Closed Won stages
- Closed Lost stages
- Renewal pipeline stages

Show proposed exclusion list and confirm.

## Phase 6 — Learning preferences

1. "How many companies must show a pattern before it becomes
   a permanent instruction? (default: 2)"
2. "Any instructions that should never be auto-removed?"
3. "Who reviews the learning PRs?"

## Phase 7 — Generate output files

Read all reference files in references/ before generating.
Generate all four files fully populated — no placeholder text.

config/context.yaml
config/client.yaml
prompts/CLAUDE.md
prompts/evaluator_rubric.md

Write them directly to the repo.

Then show deployment checklist:
□ python scripts/setup_supabase.py
□ python scripts/etl_deals.py --mode active
□ python scripts/etl_calls.py --fireflies data/... --apollo data/...
□ Trigger nightly workflow manually to verify
