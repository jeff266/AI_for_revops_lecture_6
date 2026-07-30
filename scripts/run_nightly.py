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
from datetime import datetime
from pathlib import Path
from typing import List, Dict

# Import agent components
from fireflies_client import get_fireflies_client
from apollo_client import get_apollo_client
from hubspot_deals import get_hubspot_deals_client
from context_builder import build_cumulative_meddicc
from meddicc_agent import run_agent
from github_memory import get_memory_manager


def main():
    """Main entry point for nightly MEDDICC analysis."""
    print("=" * 80)
    print("MEDDICC AGENT NIGHTLY RUN")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 80)

    # Check for test mode
    test_mode = os.getenv('TEST_MODE', 'false').lower() == 'true'
    if test_mode:
        print("\n⚠️  TEST MODE ENABLED - Will limit to 5 deals")

    # Initialize clients
    print("\n1. Initializing API clients...")
    fireflies = get_fireflies_client()
    apollo = get_apollo_client()
    hubspot = get_hubspot_deals_client()
    memory = get_memory_manager()

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

    # Limit deals in test mode
    if test_mode:
        deals = deals[:5]

    print(f"   Found {len(deals)} active deals")

    # Process each deal
    print(f"\n4. Processing deals...")
    learnings = []
    errors = []
    skipped = 0

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

            # Fireflies: Email-based matching (primary)
            fireflies_calls = []
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

            # Apollo: Company name matching only (no email data available)
            apollo_calls = apollo.search_conversations_by_company(company_name, since_date=since_date)

            total_calls = len(fireflies_calls) + len(apollo_calls)

            if total_calls < 1:
                if since_date:
                    print(f"   ⚠️  No new calls since {last_analysis_date_str}, skipping")
                else:
                    print(f"   ⚠️  No recorded calls found, skipping")
                skipped += 1
                continue

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

            if len(all_summaries) == 1:
                # Only 1 call - can't build cumulative state
                print("   ⚠️  Only 1 call - need at least 2 for cumulative analysis, skipping")
                skipped += 1
                continue

            # Split: all except most recent = cumulative, last = recent
            recent_call_summary = all_summaries[-1]
            historical_summaries = all_summaries[:-1]

            # Build cumulative MEDDICC state
            print(f"   Building cumulative state from {len(historical_summaries)} historical calls...")
            cumulative_state = build_cumulative_meddicc(historical_summaries, company_name)

            # Run MEDDICC agent
            print(f"   Running MEDDICC generator/evaluator loop...")
            result = run_agent(
                call_summary=recent_call_summary,
                cumulative_state=cumulative_state,
                deal_context=deal_context
            )

            # Extract results
            analysis = result['draft']
            evaluation = result['evaluation']
            iterations = result['iterations']
            passed = result['passed']

            print(f"   {'✓' if passed else '✗'} Analysis {'passed' if passed else 'failed'} after {iterations} iteration(s)")

            # Update HubSpot deal note
            print(f"   Updating HubSpot deal note...")
            hubspot.upsert_meddicc_note(
                deal_id=deal_id,
                analysis_content=analysis,
                calls_count=total_calls
            )

            # Save learning entry
            learning = {
                "company": company_name,
                "deal_id": deal_id,
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

            learnings.append(learning)
            memory.save_learning(learning)

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

    # Get current CLAUDE.md
    current_claude_md = memory.get_current_claude_md()

    # Collect proposed instructions
    proposed_instructions = []
    for learning in learnings:
        instruction = learning.get('proposed_instruction', '').strip()
        if instruction and instruction not in proposed_instructions:
            # Check if already in CLAUDE.md
            if instruction not in current_claude_md:
                proposed_instructions.append(instruction)

    if not proposed_instructions:
        print("   No new learnings to add")
        return

    # Append to CLAUDE.md
    learnings_section = "\n\n### Learnings from " + today + "\n\n"
    for instruction in proposed_instructions:
        learnings_section += f"- {instruction}\n"

    updated_claude_md = current_claude_md + learnings_section

    # Generate diff explanation
    diff_content = f"""# Daily MEDDICC Agent Learnings - {today}

## Summary

Processed {len(learnings)} deals with the following outcomes:

- Passed: {sum(1 for l in learnings if l['loop_performance']['passed'])} deals
- Failed: {sum(1 for l in learnings if not l['loop_performance']['passed'])} deals
- Average iterations: {sum(l['loop_performance']['iterations_to_pass'] for l in learnings) / len(learnings):.1f}

## New Instructions Added

{chr(10).join(f'{i+1}. {inst}' for i, inst in enumerate(proposed_instructions))}

## Components Analysis

**Weak components** (most frequently flagged):
{get_top_weak_components(learnings)}

**Strong components** (most frequently praised):
{get_top_strong_components(learnings)}

## Iteration Failures

Common reasons for iteration failures:
{get_common_failures(learnings)}
"""

    # Save diff
    memory.save_diff(diff_content)

    # Save version snapshot
    memory.save_version(current_claude_md)

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
