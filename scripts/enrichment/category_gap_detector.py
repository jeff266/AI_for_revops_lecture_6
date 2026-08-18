#!/usr/bin/env python3
"""
Detects gaps between questions users ask about objections/
feature gaps and the categories that actually exist in
the enrichment schema.

When users ask "have we seen vibe coding objections?" and
the category doesn't exist, the agent returns empty results
— even if the signal exists in call transcripts.

This detector:
1. Reads unanswered_queries for objection/gap questions
2. Checks what categories exist in the DB
3. Identifies implied-but-missing categories
4. Clusters growing "other" category content
5. Proposes extraction prompt additions for human review

Usage:
  python scripts/enrichment/category_gap_detector.py
  python scripts/enrichment/category_gap_detector.py --days 30
  python scripts/enrichment/category_gap_detector.py --dry-run
  python scripts/enrichment/category_gap_detector.py --create-pr

Never runs re-enrichment automatically.
Never modifies extraction prompts without human approval.
"""

import os, sys, json
from pathlib import Path
from datetime import date, timedelta
from collections import Counter

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

# Questions that imply objection/gap category queries
OBJECTION_SIGNALS = [
    "objection", "pushback", "hesitation", "concern",
    "resistance", "blocker", "barrier",
]
GAP_SIGNALS = [
    "feature gap", "feature request", "missing feature",
    "can't do", "doesn't support", "limitation",
]

# Current known categories — used to detect implied-but-missing
KNOWN_OBJECTION_CATEGORIES = {
    "switching_cost", "budget", "timing", "technical",
    "internal_politics", "product_gap", "trust",
    "build_vs_buy", "other",
}
KNOWN_GAP_CATEGORIES = {
    "platform_capability", "integration", "reporting",
    "permissions_security", "pricing_packaging", "other",
}

# Category keyword mappings — natural language → category
# Used to detect when a user's question implies a category
CATEGORY_HINTS = {
    # Objection categories
    "vibe cod":         "build_vs_buy",
    "build it":         "build_vs_buy",
    "build themselves": "build_vs_buy",
    "diy":              "build_vs_buy",
    "in-house":         "build_vs_buy",
    "engineer":         "build_vs_buy",
    "cursor":           "build_vs_buy",
    "self.host":        "deployment_preference",
    "on.prem":          "deployment_preference",
    "data sovereignty": "deployment_preference",
    "gdpr":             "compliance",
    "soc 2":            "compliance",
    "security review":  "compliance",
    "legal":            "legal_review",
    "procurement":      "procurement_process",
    "contract":         "procurement_process",
    "roi":              "budget",
    "payback":          "budget",
    # Gap categories
    "workflow":         "workflow_automation",
    "ai":               "ai_features",
    "llm":              "ai_features",
    "agent":            "ai_features",
    "mobile":           "mobile_support",
    "offline":          "offline_support",
    "export":           "data_export",
    "import":           "data_import",
    "sso":              "sso_scim",
    "saml":             "sso_scim",
    "scim":             "sso_scim",
    "audit":            "audit_logging",
}


def get_existing_categories(sb) -> dict:
    """
    Read the actual categories present in the DB.
    Returns {"objections": Counter, "feature_gaps": Counter}
    """
    from supabase_client import select_all

    obj_rows = select_all(sb, "objections",
        columns="category")
    gap_rows = select_all(sb, "feature_gaps",
        columns="category")

    return {
        "objections": Counter(
            r.get("category", "unknown") for r in obj_rows),
        "feature_gaps": Counter(
            r.get("category", "unknown") for r in gap_rows),
    }


def get_unanswered_questions(sb, days: int = 7) -> list:
    """Read unanswered queries from the last N days."""
    from supabase_client import select_all
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return select_all(sb, "unanswered_queries",
        columns="question,reason,asked_at",
        filters=[
            ("gte", "asked_at", cutoff),
            ("neq", "asked_by", "system_assessment"),
        ])


def cluster_other_category(sb) -> list:
    """
    Read all "other" category objections and feature gaps.
    Use Claude to cluster them into emerging patterns.
    Returns list of {pattern, count, sample_quotes, suggested_category}
    """
    from supabase_client import select_all
    import anthropic

    other_objections = select_all(sb, "objections",
        columns="verbatim_quote,company_name,extracted_at",
        filters=[("eq", "category", "other")])
    other_gaps = select_all(sb, "feature_gaps",
        columns="feature_description,company_name,extracted_at",
        filters=[("eq", "category", "other")])

    if not other_objections and not other_gaps:
        return []

    client = anthropic.Anthropic()

    CLUSTER_PROMPT = """These are sales call objections and
feature gaps that were filed under "other" because no
existing category matched.

Objections (other):
{objections}

Feature gaps (other):
{gaps}

Identify emerging patterns that should become their own
category. For each pattern:
1. What is the underlying theme?
2. How many items fit it?
3. What should the category be named?
4. Give a 1-line definition for the extraction prompt

Respond with JSON:
[{{
  "pattern": "description of the emerging theme",
  "count": N,
  "sample": "example quote",
  "suggested_category": "snake_case_name",
  "suggested_definition": "one line for the extraction prompt",
  "table": "objections" or "feature_gaps"
}}]

Return [] if no clear patterns emerge (random noise).
"""

    obj_sample = [
        r.get("verbatim_quote", "")[:100]
        for r in other_objections[:20]
    ]
    gap_sample = [
        r.get("feature_description", "")[:100]
        for r in other_gaps[:20]
    ]

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system="Respond with valid JSON only.",
        messages=[{"role": "user", "content":
            CLUSTER_PROMPT.format(
                objections=json.dumps(obj_sample, indent=2),
                gaps=json.dumps(gap_sample, indent=2),
            )
        }]
    )

    try:
        text = resp.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
    except Exception:
        return []

    if not isinstance(parsed, list):
        return []

    # Normalize — the report and PR builder both index into these
    # keys, and a malformed cluster must not crash the weekly run.
    clusters = []
    for c in parsed:
        if not isinstance(c, dict):
            continue
        category = (c.get("suggested_category") or "").strip()
        if not category:
            continue
        clusters.append({
            "pattern": c.get("pattern", "") or "",
            "count": c.get("count") or 0,
            "sample": c.get("sample", "") or "",
            "suggested_category": category,
            "suggested_definition": (
                c.get("suggested_definition", "") or ""),
            "table": c.get("table") or "objections",
        })
    return clusters


def detect_implied_categories(questions: list) -> dict:
    """
    Scan unanswered questions for implied-but-missing
    category signals.

    Returns {implied_category: [questions that imply it]}
    """
    implied = {}
    for q in questions:
        text = (q.get("question") or "").lower()
        # Check if this question is about objections or gaps
        is_obj = any(s in text for s in OBJECTION_SIGNALS)
        is_gap = any(s in text for s in GAP_SIGNALS)
        if not (is_obj or is_gap):
            continue

        # Look for category hints in the question
        for keyword, category in CATEGORY_HINTS.items():
            if keyword.replace(".", " ") in text or \
               keyword.replace(".", "-") in text:
                implied.setdefault(category, []).append(
                    q.get("question", ""))
                break

    return implied


def build_report(
        existing_categories: dict,
        implied_categories: dict,
        other_clusters: list,
        days: int) -> str:
    """Build the human-readable gap report."""
    lines = [
        f"*Enrichment Schema Gap Report*",
        f"_{date.today().strftime('%B %d, %Y')} | "
        f"Last {days} days_",
        "",
    ]

    # Existing category health
    obj_counts = existing_categories["objections"]
    gap_counts = existing_categories["feature_gaps"]

    other_obj = obj_counts.get("other", 0)
    other_gap = gap_counts.get("other", 0)
    total_obj = sum(obj_counts.values())
    total_gap = sum(gap_counts.values())

    other_obj_pct = (other_obj / total_obj * 100
                     if total_obj else 0)
    other_gap_pct = (other_gap / total_gap * 100
                     if total_gap else 0)

    lines.append("*Current category distribution:*")
    lines.append(f"• Objections: {total_obj} total, "
                 f"{other_obj} in 'other' "
                 f"({other_obj_pct:.0f}%)")
    lines.append(f"• Feature gaps: {total_gap} total, "
                 f"{other_gap} in 'other' "
                 f"({other_gap_pct:.0f}%)")

    # Alert if "other" is too large
    if other_obj_pct > 15:
        lines.append(
            f"\n⚠️ 'other' objections exceed 15% — "
            f"emerging patterns likely exist")
    if other_gap_pct > 15:
        lines.append(
            f"\n⚠️ 'other' feature gaps exceed 15% — "
            f"emerging patterns likely exist")

    # Implied missing categories
    if implied_categories:
        lines.append("\n*Implied-but-missing categories "
                     "(from unanswered questions):*")
        for category, questions in implied_categories.items():
            is_known = (
                category in KNOWN_OBJECTION_CATEGORIES or
                category in KNOWN_GAP_CATEGORIES)
            status = "already exists" if is_known \
                else "⚠️ MISSING"
            lines.append(
                f"• `{category}` ({status}) — "
                f"{len(questions)} question(s) imply it")
            lines.append(
                f"  Sample: \"{questions[0][:60]}...\"")

    # Other clusters
    if other_clusters:
        lines.append("\n*Emerging patterns in 'other' "
                     "category:*")
        for cluster in other_clusters:
            lines.append(
                f"• *{cluster['suggested_category']}* — "
                f"{cluster['count']} items")
            lines.append(
                f"  Pattern: {cluster['pattern']}")
            lines.append(
                f"  Definition: "
                f"{cluster['suggested_definition']}")

    if not implied_categories and not other_clusters:
        lines.append("\n✓ No schema gaps detected this week")

    lines.append("\n_Requires human approval before any "
                 "prompt changes or re-enrichment runs._")

    return "\n".join(lines)


def generate_pr_content(
        implied_categories: dict,
        other_clusters: list):
    """
    Generate the content for an extraction prompt update PR.
    Returns PR body text or None if nothing to add.
    """
    additions = []

    # Categories implied by failed questions
    for category, questions in implied_categories.items():
        if category not in KNOWN_OBJECTION_CATEGORIES and \
           category not in KNOWN_GAP_CATEGORIES:
            additions.append({
                "category": category,
                "source": "unanswered_questions",
                "questions": questions[:3],
            })

    # Categories from "other" clustering
    for cluster in other_clusters:
        cat = cluster["suggested_category"]
        if cat not in KNOWN_OBJECTION_CATEGORIES and \
           cat not in KNOWN_GAP_CATEGORIES:
            additions.append({
                "category": cat,
                "definition": cluster["suggested_definition"],
                "source": "other_cluster",
                "count": cluster["count"],
                "table": cluster.get("table", "objections"),
            })

    if not additions:
        return None

    pr_body = f"""## Proposed extraction category additions

**Generated by:** category_gap_detector.py on {date.today()}
**Requires:** human review before re-enrichment runs

### New categories proposed:
"""
    for a in additions:
        pr_body += f"\n#### `{a['category']}`\n"
        if "definition" in a:
            pr_body += f"Definition: {a['definition']}\n"
        if "questions" in a:
            pr_body += "Questions that implied this:\n"
            for q in a.get("questions", []):
                pr_body += f"- {q}\n"
        if "count" in a:
            pr_body += (f"Items in 'other' that match: "
                        f"{a['count']}\n")

    pr_body += """
### After merging this PR:
1. Re-enrichment must be run manually:
   ```
   python scripts/enrichment/run_backfill.py \\
     --category <category> --table objections \\
     --limit 200 --yes
   ```
2. New categories will appear in future call analysis
3. Historical calls are NOT retroactively reclassified —
   only calls scanned after the merge pick up the new
   category, plus whatever the backfill re-scans

### Human review checklist:
- [ ] Category name is clear and distinct
- [ ] Definition is specific enough to classify correctly
- [ ] Won't create false positives in existing data
- [ ] Re-enrichment scope is appropriate

**DO NOT MERGE without review.**
"""
    return pr_body


def create_category_pr(pr_body: str, additions_summary: str):
    """
    Open a PR carrying the proposed category additions as a
    review document, via the GitHub Contents API (same pattern
    as handler_generator.create_github_pr).

    Deliberately does NOT edit the extraction prompts itself —
    a category change rewrites how every future call is
    interpreted, so the wording stays a human decision. The PR
    body is the proposal; the reviewer applies it.

    Returns the PR URL or None.
    """
    from datetime import datetime
    from github_memory import GitHubMemory

    stamp = datetime.now().strftime('%Y%m%d%H%M%S')
    branch = f"auto-category-proposal-{stamp}"
    doc_path = f"memory/proposals/category_gaps_{stamp}.md"

    gm = GitHubMemory(REPO_ROOT)
    pr_url = gm.create_pr(
        branch_name=branch,
        title=(f"Proposed enrichment categories "
               f"({additions_summary})"),
        body=pr_body,
        files_to_commit={doc_path: pr_body},
    )
    if pr_url:
        print(f"PR created: {pr_url}")
    else:
        print("PR creation failed (or not running in GitHub "
              "Actions) — the proposal above is unchanged.")
    return pr_url


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--create-pr", action="store_true")
    parser.add_argument("--slack", action="store_true")
    args = parser.parse_args()

    from supabase import create_client
    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"])

    print("Reading existing categories...")
    existing = get_existing_categories(sb)

    print(f"Reading unanswered questions "
          f"(last {args.days} days)...")
    questions = get_unanswered_questions(sb, args.days)

    print(f"Detecting implied categories from "
          f"{len(questions)} unanswered questions...")
    implied = detect_implied_categories(questions)

    print("Clustering 'other' category content...")
    clusters = cluster_other_category(sb)

    report = build_report(existing, implied, clusters,
                          args.days)
    print("\n" + report)

    if args.dry_run:
        print("\n--dry-run: no PR created")
        return

    if args.create_pr:
        pr_content = generate_pr_content(implied, clusters)
        if pr_content:
            print("\nPR content generated:")
            print(pr_content)
            create_category_pr(
                pr_content,
                f"{len(implied) + len(clusters)} candidate(s)")
        else:
            print("\nNo new categories to propose")

    if args.slack:
        _post_to_slack(report)


def _post_to_slack(report: str):
    import requests
    ZAP_URL = os.environ.get("ZAP_REPLY_URL", "")
    if not ZAP_URL:
        return
    requests.post(ZAP_URL, json={
        "channel_id": os.environ.get(
            "SLACK_REPORT_CHANNEL", ""),
        "thread_ts": "",
        "text": report,
    }, timeout=10)


if __name__ == "__main__":
    main()
