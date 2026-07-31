#!/usr/bin/env python3
"""
MEDDICC Agent Nightly Run

Main orchestration script that:
1. Gets active deals from HubSpot
2. Finds calls for each company
3. Builds cumulative MEDDICC state
4. Runs generator/evaluator loop
5. Updates HubSpot deal notes
6. Saves learnings
7. Creates PR with daily learnings or 30-day rewrite
"""
import os
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict

# Import agent components
from fireflies_client import get_fireflies_client
from apollo_client import get_apollo_client
from hubspot_deals import get_hubspot_deals_client
from context_builder import build_cumulative_meddicc
from meddicc_agent import run_agent
from github_memory import get_memory_manager
from token_tracker import TokenTracker


def get_most_recent_call_date(fireflies_calls: list, apollo_calls: list) -> datetime | None:
    """Extract the most recent call date from fireflies and apollo calls."""
    dates = []

    # Extract Fireflies dates (millisecond timestamp in 'date' field)
    for call in fireflies_calls:
        date_value = call.get('date')
        if date_value:
            try:
                if isinstance(date_value, (int, float)):
                    dates.append(datetime.fromtimestamp(date_value / 1000))
                elif isinstance(date_value, str):
                    dates.append(datetime.fromisoformat(date_value.replace('Z', '+00:00')))
            except:
                pass

    # Extract Apollo dates (ISO string in 'start_time' field)
    for call in apollo_calls:
        start_time = call.get('start_time')
        if start_time:
            try:
                dates.append(datetime.fromisoformat(start_time.replace('Z', '+00:00')))
            except:
                pass

    return max(dates) if dates else None


def main():
    """Main entry point for nightly MEDDICC analysis."""
    print("=" * 80)
    print("MEDDICC AGENT NIGHTLY RUN")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 80)

    # Check for test mode
    test_mode = os.getenv('TEST_MODE', 'false').lower() == 'true'
    test_deal_id = os.getenv('TEST_DEAL_ID', '').strip()  # Optional specific deal ID

    if test_mode and test_deal_id:
        print(f"\n⚠️  TEST MODE ENABLED - Will process only deal ID: {test_deal_id}")
    elif test_mode:
        print("\n⚠️  TEST MODE ENABLED - Will limit to 5 deals")

    # Initialize clients
    print("\n1. Initializing API clients...")
    fireflies = get_fireflies_client()
    apollo = get_apollo_client()
    hubspot = get_hubspot_deals_client()
    memory = get_memory_manager()
    tracker = TokenTracker(memory.memory_dir)

    # Check counter and determine run type
    print("\n2. Checking run type...")
    counter = memory.get_counter()
    is_full_rewrite = memory.should_full_rewrite()

    print(f"   Total runs: {counter['total_runs']}")
    print(f"   Runs since rewrite: {counter['runs_since_rewrite']}")
    print(f"   Run type: {'FULL REWRITE' if is_full_rewrite else 'INCREMENTAL'}")

    # Get active deals
    print("\n3. Fetching active deals from HubSpot...")
    deals = hubspot.get_active_deals()

    # Filter/limit deals in test mode
    if test_mode and test_deal_id:
        # Filter for specific deal ID
        deals = [d for d in deals if d.get('id') == test_deal_id]
        if not deals:
            print(f"   ⚠️  Deal ID {test_deal_id} not found in active deals")
            return
    elif test_mode:
        # Limit to first 5 deals
        deals = deals[:5]

    print(f"   Found {len(deals)} active deals")

    # Process each deal
    print(f"\n4. Processing deals...")
    learnings = []
    errors = []
    skipped = 0
    skipped_no_calls = 0
    skipped_no_new_calls = 0
    skipped_short = 0
    deals_processed = 0
    analyses_written = 0
    learnings_written = 0

    for i, deal in enumerate(deals, 1):
        deal_id = deal.get('id')
        deal_name = deal.get('properties', {}).get('dealname', 'Unknown')

        print(f"\n[{i}/{len(deals)}] {deal_name}")

        try:
            # Get deal context
            deal_context = hubspot.get_deal_context(deal_id)
            company = deal_context.get('company')

            if not company:
                print("   ⚠️  No company associated, skipping")
                skipped += 1
                continue

            company_name = company.get('properties', {}).get('name', '')

            if not company_name:
                print("   ⚠️  No company name, skipping")
                skipped += 1
                continue

            # Check last analysis date to filter for new calls only
            last_analysis_date_str = deal.get('properties', {}).get('last_meddicc_analysis_date')
            since_date = None

            if last_analysis_date_str:
                try:
                    since_date = datetime.fromisoformat(last_analysis_date_str)
                    print(f"   Last analyzed: {last_analysis_date_str} - checking for new calls only")
                except:
                    print(f"   ⚠️  Invalid last_analysis_date format, fetching all calls")

            # Get contact emails for better matching
            contacts = deal_context.get('contacts', [])
            contact_emails = [
                c.get('properties', {}).get('email', '')
                for c in contacts
                if c.get('properties', {}).get('email')
            ]

            # HYBRID MATCHING APPROACH:
            # 1. Fireflies: Match by email (more reliable)
            # 2. Fireflies fallback: Match by company name (catches calls without contact)
            # 3. Apollo: Match by company name only (no reliable email data)

            print(f"   Searching for calls: {company_name}")
            if contact_emails:
                print(f"     Matching by {len(contact_emails)} contact email(s)")

            # Fireflies: Email-based matching (primary) - with error handling
            fireflies_calls = []
            try:
                if contact_emails:
                    fireflies_calls = fireflies.search_by_contact_emails(contact_emails, max_results=50, since_date=since_date)

                # Fireflies: Company name fallback (catches calls without tracked contacts)
                fireflies_calls_by_name = fireflies.search_by_company(company_name, max_results=50, since_date=since_date)

                # Deduplicate Fireflies calls (combine email + name matches)
                seen_fireflies_ids = set()
                for call in fireflies_calls:
                    seen_fireflies_ids.add(call.get('id'))

                for call in fireflies_calls_by_name:
                    if call.get('id') not in seen_fireflies_ids:
                        fireflies_calls.append(call)
                        seen_fireflies_ids.add(call.get('id'))

            except Exception as e:
                print(f"   ⚠️  Fireflies API error (skipping Fireflies): {e}")
                fireflies_calls = []

            # Apollo: Company name matching only (no email data available)
            apollo_calls = apollo.search_conversations_by_company(company_name, since_date=since_date)

            total_calls = len(fireflies_calls) + len(apollo_calls)

            print(f"   Found {total_calls} calls ({len(fireflies_calls)} Fireflies, {len(apollo_calls)} Apollo)")

            # Format all call summaries
            all_summaries = []

            for call in fireflies_calls:
                all_summaries.append(fireflies.format_summary_for_meddicc(call))

            for call in apollo_calls:
                all_summaries.append(apollo.format_conversation_for_meddicc(call))

            # Sort by date (should already be sorted, but ensure)
            # Note: This is approximate since summaries are strings
            # In production, you'd sort the original objects before formatting

            # GUARD 1: No calls found for company
            if len(all_summaries) == 0:
                print(f"   ⏭️  {company_name}: no calls found — skipping")
                if since_date:
                    skipped_no_new_calls += 1
                else:
                    skipped_no_calls += 1
                skipped += 1
                continue

            # GUARD 4: Most recent call already analyzed
            if since_date:
                last_call_date = get_most_recent_call_date(fireflies_calls, apollo_calls)
                if last_call_date and last_call_date <= since_date:
                    print(f"   ⏭️  {company_name}: most recent call ({last_call_date.strftime('%Y-%m-%d')}) already analyzed — skipping")
                    skipped_no_new_calls += 1
                    skipped += 1
                    continue

            # GUARD 2: Only one call exists (nothing to contextualize)
            if len(all_summaries) == 1:
                print(f"   ⚡ {company_name}: single call — skipping context builder, analyzing directly")
                recent_call_summary = all_summaries[0]
                historical_summaries = []
                cumulative_state = {
                    "company": company_name,
                    "calls_reviewed": 0,
                    "meddicc_state": {
                        k: {"status": "unknown", "evidence": "", "score": 0}
                        for k in ["metrics", "economic_buyer", "decision_criteria",
                                 "decision_process", "identified_pain", "champion", "competition"]
                    },
                    "key_context": "First call on record — no prior context."
                }
            else:
                # Split: all except most recent = cumulative, last = recent
                recent_call_summary = all_summaries[-1]
                historical_summaries = all_summaries[:-1]

                # Build cumulative MEDDICC state
                print(f"   Building cumulative state from {len(historical_summaries)} historical calls...")
                cumulative_state = build_cumulative_meddicc(historical_summaries, company_name, tracker)

            # GUARD 3: Most recent call is below minimum signal threshold
            if len(recent_call_summary.strip()) < 200:
                print(f"   ⏭️  {company_name}: most recent call summary too short ({len(recent_call_summary)} chars) — skipping")
                skipped_short += 1
                skipped += 1
                continue

            # Run MEDDICC agent
            print(f"   Running MEDDICC generator/evaluator loop...")
            result = run_agent(
                call_summary=recent_call_summary,
                cumulative_state=cumulative_state,
                deal_context=deal_context,
                tracker=tracker,
                company=company_name
            )

            # Extract results
            analysis = result['draft']
            evaluation = result['evaluation']
            iterations = result['iterations']
            passed = result['passed']
            outcome = result['outcome']
            root_cause = result['root_cause']

            print(f"   {'✓' if passed else '✗'} Analysis {'passed' if passed else 'failed'} after {iterations} iteration(s)")
            print(f"   Reflection: outcome={outcome}, root_cause={root_cause}")

            # Save analysis to file
            print(f"   Saving analysis to file...")
            output_dir = Path(__file__).parent.parent / "output"
            output_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = output_dir / f"meddicc_analysis_{deal_id}_{timestamp}.md"

            with open(output_file, 'w') as f:
                f.write(f"# MEDDICC Analysis: {company_name}\n\n")
                f.write(f"**Deal ID:** {deal_id}\n")
                f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                f.write(f"**Calls Analyzed:** {total_calls}\n")
                f.write(f"**Iterations:** {iterations}\n")
                f.write(f"**Status:** {'✓ Passed' if passed else '✗ Failed'}\n\n")
                f.write("---\n\n")
                f.write(analysis)

            print(f"   ✓ Saved to {output_file}")
            analyses_written += 1

            # Update HubSpot deal note
            print(f"   Updating HubSpot deal note...")
            try:
                hubspot.upsert_meddicc_note(
                    deal_id=deal_id,
                    analysis_content=analysis,
                    calls_count=total_calls
                )
                print(f"   ✓ HubSpot note updated")
            except Exception as hub_error:
                print(f"   ⚠️  HubSpot note failed (analysis saved to file): {hub_error}")

            # Build learning entry with reflection outcome
            learning = {
                "company": company_name,
                "deal_id": deal_id,
                "outcome": outcome,
                "root_cause": root_cause,
                "confidence": 0.8 if outcome == "candidate" else 0.5 if outcome == "observation" else 0.0,
                "loop_performance": {
                    "iterations_to_pass": iterations,
                    "passed": passed,
                    "budget_exhausted": iterations >= 3 and not passed
                },
                "cumulative_calls_context": len(historical_summaries),
                "iteration_1_failures": evaluation.get('iteration_failures', []) if iterations > 1 else [],
                "components_weak": evaluation.get('components_weak', []),
                "components_strong": evaluation.get('components_strong', []),
                "required_changes_injected": evaluation.get('required_changes') if iterations > 1 else None,
                "resolution": "Passed" if passed else f"Failed after {iterations} iterations",
                "proposed_instruction": evaluation.get('proposed_instruction', '')
            }

            # Conditional save based on outcome
            if outcome in ["observation", "candidate"]:
                learnings.append(learning)
                memory.save_learning(learning)
                learnings_written += 1
                print(f"   ✓ Learning saved (outcome={outcome})")
            elif outcome in ["bug", "prompt_issue"]:
                memory.save_issue(learning)
                learnings_written += 1
                print(f"   ✓ Issue saved (outcome={outcome})")
            else:
                # no_learning - skip save entirely
                print(f"   ✓ No learning generated (outcome={outcome})")

            # Save rubric observation (runs regardless of outcome)
            rubric_obs = result.get('rubric_observation', {})
            if rubric_obs:
                saved = memory.save_rubric_observation(
                    rubric_obs, company_name)
                if saved:
                    print(f"   ✓ Rubric observation saved")

            deals_processed += 1
            print(f"   ✓ Complete")

        except Exception as e:
            print(f"   ✗ Error: {e}")
            errors.append({
                "deal_id": deal_id,
                "deal_name": deal_name,
                "error": str(e)
            })

    # Update counter
    print("\n5. Updating run counter...")
    counter = memory.update_counter(is_full_rewrite=is_full_rewrite)

    # Generate PR
    print("\n6. Creating GitHub PR...")

    if is_full_rewrite:
        create_full_rewrite_pr(memory, learnings)
    else:
        create_incremental_pr(memory, learnings)

    # Print guard summary
    print(f"\n=== RUN SUMMARY ===")
    print(f"  Deals evaluated:    {deals_processed}")
    print(f"  Skipped (no calls): {skipped_no_calls}")
    print(f"  Skipped (no new):   {skipped_no_new_calls}")
    print(f"  Skipped (too short):{skipped_short}")
    print(f"  Analyses written:   {analyses_written}")
    print(f"  Learning entries:   {learnings_written}")

    # Save and print token usage
    print("\n7. Saving token usage...")
    usage_summary = tracker.save()
    tracker.print_summary(usage_summary,
                          deals_processed=len(learnings))

    # Print summary
    print("\n" + "=" * 80)
    print("RUN SUMMARY")
    print("=" * 80)
    print(f"Deals processed: {len(learnings)}")
    print(f"Deals skipped: {skipped}")
    print(f"Errors: {len(errors)}")

    if learnings:
        passed_count = sum(1 for l in learnings if l['loop_performance']['passed'])
        print(f"Passed evaluations: {passed_count}/{len(learnings)} ({passed_count/len(learnings)*100:.1f}%)")

        avg_iterations = sum(l['loop_performance']['iterations_to_pass'] for l in learnings) / len(learnings)
        print(f"Average iterations: {avg_iterations:.1f}")

    if errors:
        print("\nErrors encountered:")
        for err in errors[:5]:  # Show first 5
            print(f"  - {err['deal_name']}: {err['error']}")

    print("\n" + "=" * 80)
    print(f"✓ Nightly run complete")
    print(f"Finished: {datetime.now().isoformat()}")
    print("=" * 80)


def create_incremental_pr(memory: any, learnings: List[dict]) -> None:
    """Create PR with today's learnings appended to CLAUDE.md."""
    today = datetime.now().strftime('%Y-%m-%d')

    # GUARD 5: Nightly synthesizer with no candidates
    today_files = list(memory.learnings_dir.glob(f'{today}_*.json'))
    if not today_files:
        print("   ⏭️  No learning entries today — skipping PR synthesis")
        memory.save_diff("No analyses generated today — no learning entries written.")
        claude_md_path = Path(__file__).parent.parent / 'prompts' / 'CLAUDE.md'
        memory.save_version(claude_md_path.read_text())
        return

    # Get current CLAUDE.md
    current_claude_md = memory.get_current_claude_md()

    # Evidence diversity gate configuration
    MIN_EVIDENCE_COMPANIES = 2  # Threshold for instruction inclusion

    # Collect proposed instructions from today's learnings (observation/candidate only)
    candidate_instructions = []
    for learning in learnings:
        # Only consider observation and candidate outcomes
        if learning.get('outcome') not in ['observation', 'candidate']:
            continue

        instruction = learning.get('proposed_instruction', '').strip()
        if not instruction:
            continue

        # Check if already in CLAUDE.md
        if instruction in current_claude_md:
            continue

        # Store with metadata for diversity check
        candidate_instructions.append({
            'instruction': instruction,
            'components_weak': learning.get('components_weak', []),
            'company': learning.get('company', '')
        })

    if not candidate_instructions:
        print("   No candidate instructions from today's learnings")
        return

    # Load historical learnings from past 30 days for diversity check
    historical_learnings = memory.get_recent_learnings(days=30)

    # Evidence diversity gate: count unique companies per instruction
    proposed_instructions = []
    deferred_instructions = []

    for candidate in candidate_instructions:
        instruction = candidate['instruction']
        weak_components = set(candidate['components_weak'])

        # Count unique companies in historical learnings with overlapping weak components
        unique_companies = {candidate['company']}  # Start with today's company

        for hist_learning in historical_learnings:
            hist_weak = set(hist_learning.get('components_weak', []))
            hist_company = hist_learning.get('company', '')

            # If historical learning shares at least one weak component, count it
            if weak_components & hist_weak:
                unique_companies.add(hist_company)

        # Only include if meets minimum evidence threshold
        if len(unique_companies) >= MIN_EVIDENCE_COMPANIES:
            proposed_instructions.append(instruction)
            print(f"   ✓ Instruction approved: {len(unique_companies)} companies show evidence")
        else:
            deferred_instructions.append({
                'instruction': instruction,
                'company_count': len(unique_companies)
            })
            print(f"   ⚠️  Instruction deferred: only {len(unique_companies)} companies (need {MIN_EVIDENCE_COMPANIES})")

    # Generate diff explanation (always, regardless of whether instructions were promoted)
    instructions_section = "None — all candidates deferred pending evidence across more companies." if not proposed_instructions else chr(10).join(f'{i+1}. {inst}' for i, inst in enumerate(proposed_instructions))

    deferred_section = ""
    if deferred_instructions:
        deferred_section = "\n\n## Deferred Candidates\n\nThe following instructions were considered but did not meet the evidence diversity threshold (need " + str(MIN_EVIDENCE_COMPANIES) + "+ companies):\n\n"
        for item in deferred_instructions:
            deferred_section += f"- ({item['company_count']} companies) {item['instruction']}\n"

    diff_content = f"""# Daily MEDDICC Agent Learnings - {today}

## Summary

Processed {len(learnings)} deals with the following outcomes:

- Passed: {sum(1 for l in learnings if l['loop_performance']['passed'])} deals
- Failed: {sum(1 for l in learnings if not l['loop_performance']['passed'])} deals
- Average iterations: {sum(l['loop_performance']['iterations_to_pass'] for l in learnings) / len(learnings):.1f}

## New Instructions Added

{instructions_section}
{deferred_section}

## Components Analysis

**Weak components** (most frequently flagged):
{get_top_weak_components(learnings)}

**Strong components** (most frequently praised):
{get_top_strong_components(learnings)}

## Iteration Failures

Common reasons for iteration failures:
{get_common_failures(learnings)}
"""

    # Save diff and version unconditionally (audit trail)
    memory.save_diff(diff_content)
    memory.save_version(current_claude_md)

    # Only update CLAUDE.md and create PR if we have promoted instructions
    if not proposed_instructions:
        print("   No instructions met evidence diversity threshold — diff saved for audit trail")
        return

    # Append to CLAUDE.md
    learnings_section = "\n\n### Learnings from " + today + "\n\n"
    for instruction in proposed_instructions:
        learnings_section += f"- {instruction}\n"

    updated_claude_md = current_claude_md + learnings_section

    # Create PR (if in GitHub Actions)
    branch_name = f"agent/learnings-{today}"
    title = f"chore: MEDDICC agent learnings — {today}"

    memory.create_pr(
        branch_name=branch_name,
        title=title,
        body=diff_content,
        files_to_commit={
            "prompts/CLAUDE.md": updated_claude_md,
            f"memory/diffs/{today}.md": diff_content
        }
    )

    print(f"   ✓ Incremental PR created: {title}")


def create_full_rewrite_pr(memory: any, learnings: List[dict]) -> None:
    """Create PR with full CLAUDE.md rewrite synthesizing 30 days of learnings."""
    from anthropic import Anthropic

    today = datetime.now().strftime('%Y-%m-%d')

    print("   Synthesizing 30 days of learnings...")

    # Get all learnings from past 30 days
    all_learnings = memory.get_recent_learnings(days=30)

    # Get current CLAUDE.md
    current_claude_md = memory.get_current_claude_md()

    # Build synthesis prompt
    learnings_summary = json.dumps(all_learnings, indent=2)

    synthesis_prompt = f"""You are rewriting the CLAUDE.md instructions for the MEDDICC analysis generator.

You have 30 days of learning data from the evaluator feedback loop. Your job is to:

1. Review all proposed instructions from the past 30 days
2. Consolidate redundant or overlapping instructions
3. Restructure CLAUDE.md to be clearer and more effective
4. Preserve all the core rules and format requirements
5. Integrate learnings into the appropriate sections

Current CLAUDE.md:
```markdown
{current_claude_md}
```

30 days of learnings data:
```json
{learnings_summary}
```

Generate a COMPLETE rewritten CLAUDE.md that:
- Maintains the same output format specification
- Preserves all critical rules
- Integrates learnings into relevant sections (not just appended)
- Is clearer and more actionable than the current version
- Removes redundant instructions

Output ONLY the new CLAUDE.md content, no additional commentary."""

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    response = client.messages.create(
        model='claude-sonnet-4-5-20250929',
        max_tokens=8000,
        messages=[{"role": "user", "content": synthesis_prompt}]
    )

    new_claude_md = response.content[0].text

    # Generate rewrite changelog
    changelog = f"""# 30-Day MEDDICC Agent Synthesis - {today}

## Overview

This is a full rewrite of the MEDDICC agent instructions based on 30 days of learning data.

**Learnings processed**: {len(all_learnings)} entries
**Deals analyzed**: {sum(1 for l in all_learnings if l.get('deal_id'))} unique deals

## Key Changes

[Synthesized by Claude from learning patterns]

## Performance Trends

- Average pass rate: {sum(1 for l in all_learnings if l.get('loop_performance', {}).get('passed')) / len(all_learnings) * 100:.1f}%
- Average iterations to pass: {sum(l.get('loop_performance', {}).get('iterations_to_pass', 0) for l in all_learnings) / len(all_learnings):.1f}

## Next Review

Next full rewrite scheduled for: {(datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')}
"""

    # Save diff
    memory.save_diff(changelog)

    # Save version snapshot of OLD version
    memory.save_version(current_claude_md)

    # Create PR
    branch_name = f"agent/rewrite-{today}"
    title = f"chore: MEDDICC agent 30-day synthesis — {today}"

    memory.create_pr(
        branch_name=branch_name,
        title=title,
        body=changelog,
        files_to_commit={
            "prompts/CLAUDE.md": new_claude_md,
            f"memory/diffs/{today}.md": changelog
        }
    )

    print(f"   ✓ Full rewrite PR created: {title}")

    # Also create rubric update PR on 30-day cycle
    prs_created = ['full_rewrite']
    create_rubric_update_pr(memory, prs_created)


def create_rubric_update_pr(memory: any, prs_created: list) -> None:
    """
    Read all rubric observations from the past 30 days.
    If enough signal exists, propose updates to evaluator_rubric.md.
    Only runs on the 30-day cycle alongside the full rewrite.
    """
    from anthropic import Anthropic

    obs_files = sorted(memory.rubric_obs_dir.glob('*.json'))
    if not obs_files:
        print("   No rubric observations to synthesize")
        return

    # Load all observations
    observations = []
    for f in obs_files:
        with open(f) as fp:
            observations.append(json.load(fp))

    # Only proceed if we have at least 5 observations with suggested changes
    actionable = [o for o in observations if o.get('suggested_change')]
    if len(actionable) < 5:
        print(f"   Only {len(actionable)} actionable rubric observations — skipping (need 5+)")
        return

    # Load current rubric
    rubric_path = Path(__file__).parent.parent / 'prompts' / 'evaluator_rubric.md'
    current_rubric = rubric_path.read_text()

    # Synthesize with Haiku
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    synthesis_prompt = f"""You are reviewing observations about an AI evaluator rubric
used to score MEDDICC sales call analyses.

Current rubric:
{current_rubric}

Observations from the past 30 days ({len(actionable)} with suggested changes):
{json.dumps(actionable, indent=2)}

Your task:
1. Identify patterns: which criteria are consistently flagged as inappropriate?
2. Identify criteria that are too strict, too loose, or missing entirely
3. Propose a revised evaluator_rubric.md that:
   - Fixes criteria that fired inappropriately multiple times
   - Adds criteria that were clearly missing
   - Removes or softens criteria that blocked good analyses
   - Is no longer than the current rubric plus one new criterion maximum

Return ONLY the complete revised rubric as markdown.
Do not include explanations outside the rubric itself.
Add a ## Revision Notes section at the bottom explaining what changed."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": synthesis_prompt}]
    )

    new_rubric = response.content[0].text

    # Write to file and create PR
    rubric_path.write_text(new_rubric)

    branch = f"agent/rubric-update-{datetime.now().strftime('%Y-%m-%d')}"
    pr_body = f"""## Evaluator Rubric Update — 30-Day Synthesis

Based on {len(actionable)} rubric observations across {len(set(o['company'] for o in actionable))} companies.

### Criteria modified
See ## Revision Notes section in the updated rubric.

### Criteria that triggered most frequently
{chr(10).join(f"- {c}: {sum(1 for o in actionable if o.get('criterion_fired') == c)} times"
              for c in set(o.get('criterion_fired') for o in actionable if o.get('criterion_fired')))}

Review the diff carefully. The evaluator rubric affects every analysis.
"""
    memory.create_pr(
        branch_name=branch,
        title=f"chore: evaluator rubric update — {datetime.now().strftime('%Y-%m-%d')}",
        body=pr_body,
        files_to_commit={str(rubric_path): new_rubric}
    )
    print(f"   ✓ Rubric update PR created: {branch}")
    prs_created.append('rubric_update')


def get_top_weak_components(learnings: List[dict]) -> str:
    """Get most frequently weak components."""
    from collections import Counter

    weak = []
    for l in learnings:
        weak.extend(l.get('components_weak', []))

    if not weak:
        return "None"

    counts = Counter(weak)
    return "\n".join(f"- {comp}: {count} times" for comp, count in counts.most_common(5))


def get_top_strong_components(learnings: List[dict]) -> str:
    """Get most frequently strong components."""
    from collections import Counter

    strong = []
    for l in learnings:
        strong.extend(l.get('components_strong', []))

    if not strong:
        return "None"

    counts = Counter(strong)
    return "\n".join(f"- {comp}: {count} times" for comp, count in counts.most_common(5))


def get_common_failures(learnings: List[dict]) -> str:
    """Get most common iteration failure reasons."""
    from collections import Counter

    failures = []
    for l in learnings:
        failures.extend(l.get('iteration_1_failures', []))

    if not failures:
        return "None"

    counts = Counter(failures)
    return "\n".join(f"- {reason}: {count} times" for reason, count in counts.most_common(5))


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
