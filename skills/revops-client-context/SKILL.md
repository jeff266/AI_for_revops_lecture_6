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
6. "What timezone is your sales team primarily in?
   (e.g. America/New_York, America/Los_Angeles, Europe/London)
   This ensures HubSpot dates match your team's calendar."

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

## Phase 7 — Generate and deploy config files

Read all four reference files before generating anything.

Generate all four files fully populated from the interview.
No placeholder text anywhere.

### If running in Claude Code (has file system access):

Write files directly — do not show as code blocks:

1. Write config/context.yaml
2. Write config/client.yaml with placeholder stage IDs
3. Write prompts/CLAUDE.md
4. Write prompts/evaluator_rubric.md

Then run stage discovery:
  python scripts/discover_stages.py

Show the output and ask: "Which stages should be excluded?
(Usually: Meeting Set, Closed Won, Closed Lost, any
Renewal pipeline stages)"

Update config/client.yaml with the real stage IDs from
their answer.

Commit everything:
  git add config/ prompts/
  git commit -m "Add [company] client context and config"
  git push

Tell the student: "Done. Config is live in the repo.
Next step: add GitHub Secrets, then run the ETL."

### If running in Claude.ai (no file system access):

Present each file as a labeled code block:

**config/context.yaml** — copy this to your repo
[content]

**config/client.yaml** — copy this to your repo
[content]

**prompts/CLAUDE.md** — copy this to your repo
[content]

**prompts/evaluator_rubric.md** — copy this to your repo
[content]

Then show the deployment checklist:
□ Copy all four files into your forked repo
□ Run: python scripts/discover_stages.py
□ Update excluded_stages in config/client.yaml
  with your real HubSpot stage IDs
□ git add config/ prompts/ && git commit -m "Add client context"
□ git push
