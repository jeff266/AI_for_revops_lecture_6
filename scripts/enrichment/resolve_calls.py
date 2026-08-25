#!/usr/bin/env python3
"""
Resolve company/deal linkage and call intent for every
call in the calls table, ONCE, and store the result.

Resolution priority (most to least trustworthy):
  1. participant email domains → match to deal's company
     domain (objective, survives any naming convention)
  2. company name slug → match to known deal slugs
     (current fallback, fragile but better than nothing)
  3. flag needs_review = TRUE for anything ambiguous

Also resolves is_internal (all participant domains are
the client's own) and call_intent (using the classifier,
but now with REAL participant emails available).

Usage:
  python scripts/enrichment/resolve_calls.py --dry-run
  python scripts/enrichment/resolve_calls.py --yes
  python scripts/enrichment/resolve_calls.py \
    --only-unresolved --yes

This runs ONCE after the participant backfill. After that,
new calls get resolved incrementally as they arrive. The
enrichment scripts read the stored result — they never
re-resolve.
"""

import os
import sys
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def load_config():
    """Read client config for internal domains and
    company tokens."""
    import yaml
    cfg_path = REPO_ROOT / "config" / "client.yaml"
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def get_deal_domains(sb):
    """Build a map of email domain → deal for domain-based
    resolution. Uses the deals table's company domain if
    available, else derives from company name."""
    from supabase_client import select_all

    deals = select_all(sb, "deals",
        columns="deal_id,company_name,company_id,company_slug,company_domain")

    # Build domain map from company_domain (added in migration 024)
    domain_map = {}
    for d in deals:
        domain = d.get("company_domain")
        if domain:
            # Multiple deals can have same domain (different contacts at same company)
            # Use the most recent deal for that domain
            if domain not in domain_map:
                domain_map[domain] = d

    return domain_map, deals


def get_company_slug_map(sb):
    """Build a map of normalized slug → deals for slug-based
    resolution."""
    from supabase_client import select_all
    from scripts.utils import slugify

    deals = select_all(sb, "deals",
        columns="deal_id,company_name,company_id,company_slug")

    slug_map = {}
    for d in deals:
        slug = slugify(d.get("company_name", ""))
        if slug:
            if slug not in slug_map:
                slug_map[slug] = []
            slug_map[slug].append(d)

    return slug_map


def resolve_by_email_domain(participant_domains,
                            domain_map, internal_domains):
    """Match external participant domain to a deal's
    company domain. Returns deal dict or None."""
    for domain in (participant_domains or []):
        if domain in internal_domains:
            continue  # skip the client's own domain
        if domain in domain_map:
            return domain_map[domain]
    return None


def resolve_by_slug(company_slug, slug_map):
    """Fallback: match company slug to deal company slug."""
    if not company_slug:
        return None

    deals = slug_map.get(company_slug, [])
    if not deals:
        return None

    # If multiple deals for same company, pick most recent
    # This is imperfect but better than nothing
    deals_sorted = sorted(deals,
        key=lambda d: d.get("deal_id", ""),
        reverse=True)
    return deals_sorted[0] if deals_sorted else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
        help="Show what would be done without writing")
    parser.add_argument("--yes", action="store_true",
        help="Actually write to database")
    parser.add_argument("--only-unresolved",
        action="store_true",
        help="Only resolve calls with no deal_id yet")
    parser.add_argument("--limit", type=int,
        help="Limit number of calls to process")
    args = parser.parse_args()

    if not args.dry_run and not args.yes:
        print("Use --dry-run to preview or --yes to execute")
        sys.exit(1)

    config = load_config()

    # Get internal domains from config
    org_config = config.get("organization", {})
    internal_domains_list = config.get("organization", {}).get(
        "internal_domains", [])

    # If not in config, try to infer from org name
    if not internal_domains_list and org_config.get("name"):
        # Basic inference: "the reference implementation" → "growthbook.io"
        org_name = org_config["name"].lower().replace(" ", "")
        internal_domains_list = [f"{org_name}.io"]

    internal_domains = set(d.lower() for d in internal_domains_list)
    print(f"Internal domains: {internal_domains}")

    from supabase import create_client
    from supabase_client import select_all
    from scripts.enrichment.call_intent_classifier import (
        classify_call, INTENT_PROSPECT, INTENT_SALES_REVIEW,
        INTENT_SKIP)
    import anthropic

    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"])
    client = anthropic.Anthropic()

    domain_map, _ = get_deal_domains(sb)
    slug_map = get_company_slug_map(sb)

    # Load calls to resolve
    filters = []
    if args.only_unresolved:
        filters.append(("is_", "deal_id", None))

    calls = select_all(sb, "calls",
        columns="call_id,title,summary,company_name,"
                "company_slug,participant_emails,"
                "participant_domains,call_date",
        filters=filters)

    if args.limit:
        calls = calls[:args.limit]

    print(f"\nProcessing {len(calls)} calls...")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'WRITE'}\n")

    stats = {"email_resolved": 0, "slug_resolved": 0,
             "internal": 0, "needs_review": 0,
             "prospect": 0, "sales_review": 0, "skip": 0}

    for i, call in enumerate(calls, 1):
        if i % 50 == 0:
            print(f"  Processed {i}/{len(calls)}...")

        pdomains = call.get("participant_domains") or []
        pemails = call.get("participant_emails") or []

        # Is this internal? (all domains are the client's)
        external_domains = [
            d for d in pdomains
            if d not in internal_domains]
        is_internal = (len(pdomains) > 0
                       and len(external_domains) == 0)
        if is_internal:
            stats["internal"] += 1

        # Resolve deal
        deal = None
        method = None
        if not is_internal:
            deal = resolve_by_email_domain(
                pdomains, domain_map, internal_domains)
            if deal:
                method = "email"
                stats["email_resolved"] += 1
            else:
                slug = call.get("company_slug", "")
                deal = resolve_by_slug(slug, slug_map)
                if deal:
                    method = "slug"
                    stats["slug_resolved"] += 1

        # Classify intent — NOW with real participant emails
        participants = [{"email": e} for e in pemails]

        # Use rule-based classification first (faster)
        classification = classify_call({
            "title":        call.get("title", ""),
            "summary":      call.get("summary", ""),
            "participants": participants,
            "company":      call.get("company_name", ""),
            "tags":         [],
        }, client=None)  # client=None means use rules only

        intent = classification["intent"]
        stats[intent] = stats.get(intent, 0) + 1

        needs_review = (
            not is_internal and deal is None) or (
            classification["confidence"] < 0.6)
        if needs_review:
            stats["needs_review"] += 1

        if args.dry_run:
            deal_str = deal.get("company_name", "")[:20] if deal else "NONE"
            print(f"  {call['call_id'][:20]:20} | "
                  f"int={str(is_internal):5} | "
                  f"deal={deal_str:20} | "
                  f"intent={intent:12} | "
                  f"method={method or classification['method']}")
            continue

        # Store the resolved result
        sb.table("calls").update({
            "is_internal":       is_internal,
            "deal_id":           deal.get("deal_id") if deal else None,
            "deal_name":         deal.get("company_name") if deal else None,
            "company_id":        deal.get("company_id") if deal else None,
            "call_intent":       intent,
            "intent_confidence": classification["confidence"],
            "intent_method":     classification["method"],
            "needs_review":      needs_review,
            "resolved_at":       "now()",
            "resolved_by":       "auto",
            "resolution_notes":  (
                f"deal via {method}" if method
                else "no deal match"),
        }).eq("call_id", call["call_id"]).execute()

    print(f"\n{'='*60}")
    print("Resolution summary:")
    for k, v in sorted(stats.items()):
        print(f"  {k:20}: {v}")
    print(f"\nTotal calls processed: {len(calls)}")

    if stats["needs_review"]:
        print(f"\n⚠️  {stats['needs_review']} calls need "
              f"human review")
        print("Query: SELECT * FROM calls_needing_review;")


if __name__ == "__main__":
    main()
