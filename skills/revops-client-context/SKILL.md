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

Eight phases. Complete each before moving to the next.

## Phase 1 — Product and ICP

Ask one at a time:
1. "What does your product do in one sentence? Be specific."
2. "Who is your ICP? Company size, industry, and buyer title."
3. "What is your primary differentiator?"
4. "What qualification methodology do you use?"
5. "What CRM do you use? (HubSpot, Salesforce, other)"
6. "What call recording platform do you use? (Fireflies, Gong, other)"
7. "What does a good first call look like for your best reps?"
8. "What timezone is your sales team primarily in?
   (e.g. America/New_York, America/Los_Angeles, Europe/London)
   This ensures CRM dates match your team's calendar."

Push back on vague answers. Ask for real examples.

## Phase 2 — Call Tool Adapter Setup

After collecting the call tool name in Phase 1, run this:

If the tool is Fireflies or Gong:
  Tell user the adapter already exists.
  Skip to next phase.

If the tool is anything else (Fathom, Avoma, Chorus, etc.):

  STEP A: Research current API docs
  Use web search to find:
  - Base API URL for {tool}
  - Authentication method (Bearer, Basic, API Key header)
  - Endpoint to list recent calls/meetings
  - Endpoint to get transcript for a call ID
  - Endpoint to get summary/AI notes
  - Whether participant emails are returned
  - Rate limits

  STEP B: Generate the adapter

  If scripts/adapters/calls/base.py does not exist in this
  repo (older fork), create it first with exactly this
  interface, then proceed:

  ```python
  from abc import ABC, abstractmethod
  from typing import List, Optional
  from datetime import datetime

  class CallAdapter(ABC):
      """
      Contract for all call intelligence adapters.
      Every tool (Fireflies, Gong, Apollo, Fathom, Avoma...)
      implements exactly this interface. Method names are
      methodology-agnostic on purpose.
      """

      @abstractmethod
      def search_by_company(self, company_name: str,
                            since_date: Optional[datetime] = None
                            ) -> List[dict]:
          """Return call dicts for a company, newest data included."""

      @abstractmethod
      def format_summary(self, call: dict) -> str:
          """Format one call dict into an analysis-ready text
          summary. Must return >100 chars for real calls
          (Guard 3 in the nightly agent)."""

      @abstractmethod
      def get_meeting_attendees(self, call_id: str) -> List[dict]:
          """Return attendees with email where available:
          [{'name': ..., 'email': ...}, ...]. Return [] if the
          tool cannot provide attendees."""

      def test_connection(self) -> bool:
          """Optional override. Default: True."""
          return True
  ```

  Create scripts/adapters/calls/{tool_slug}.py following
  the interface in scripts/adapters/calls/base.py.

  Implement:
    search_by_company(company, since_date) -> list
    format_summary(call) -> str
    get_meeting_attendees(call_id) -> list

  STEP C: Simulate a test (no API key needed)

  Generate a mock API response that matches the tool's
  documented schema. Run the adapter methods against it.
  Print a validation report:

    ✓ search_by_company() — returns list of dicts
    ✓ format_summary_for_meddicc() — 847 chars (passes Guard 3)
    ✓ get_meeting_attendees() — returns email list
    ✓ No external domains leaked (internal domain filter works)
    ✓ Adapter conforms to CallAdapter interface

  If any check fails, fix the adapter before proceeding.

  STEP D: Commit the adapter

    git add scripts/adapters/calls/{tool_slug}.py
    git commit -m "Add {Tool} call adapter from onboarding"
    git push

  Tell user:
  "Adapter built and tested against mock data.
   To activate it: add your {Tool} API credentials
   to GitHub Secrets and run the calls ETL."

## Phase 3 — Competitive landscape

Ask them to name all competitors first, then go through each one:
- Full name as it appears in prospect conversations
- Type: direct / adjacent / internal_tool / status_quo
- What prospects say when they mention this competitor
- How the rep should respond
- When you win vs lose against them
- Any aliases (other names it appears as in transcripts)

Prompt: "Any internal tools? Any build-vs-buy situations?"

## Phase 4 — Objections

For each objection (collect at least 5):
1. "What are the actual words a prospect uses?"
2. "Which stage does this typically appear at?"
3. "What's the best rep response?"
4. "Category: switching cost / budget / timing / technical /
   internal politics / product gap / trust / other?"

Prompt: "What kills the most deals? What comes up earliest?"

## Phase 5 — Feature gaps and value metrics

Feature gaps — for each:
- The feature description
- Exact language prospects use when asking about it
- Roadmap item or genuine gap?

Value metrics:
"What quantifiable outcomes do champions use for the business case?"

## Phase 6 — HubSpot stage configuration

Tell the user to run: python scripts/discover_stages.py
Ask them to paste the output.

Parse it and identify stages to EXCLUDE:
- Meeting Set equivalents (too early)
- Closed Won stages
- Closed Lost stages
- Renewal pipeline stages

Show proposed exclusion list and confirm.

## Phase 7 — Learning preferences

1. "How many companies must show a pattern before it becomes
   a permanent instruction? (default: 2)"
2. "Any instructions that should never be auto-removed?"
3. "Who reviews the learning PRs?"

## Phase 8 — Generate and deploy config files

Read all four reference files before generating anything.

Generate all four files fully populated from the interview.
No placeholder text anywhere.

When generating prompts and rubric, resolve every {{if methodology
...}} conditional against the components of the selected methodology
— never leave conditional markers in output.

### If running in Claude Code (has file system access):

Write files directly — do not show as code blocks:

1. Write config/context.yaml
2. Write config/client.yaml with:
   - Placeholder stage IDs
   - call_tools.primary set to the adapter slug from Phase 2
     (fireflies, gong, or custom tool slug)
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
(with call_tools.primary set to {adapter_slug})
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
