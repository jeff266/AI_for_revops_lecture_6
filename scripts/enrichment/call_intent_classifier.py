#!/usr/bin/env python3
"""
Classifies calls by intent before enrichment.
Determines whether a call should be enriched and with
what extraction profile.

Three intent classes:
  prospect      - external participant present, or
                  clearly a customer/prospect conversation
  sales_review  - internal sales intelligence: forecast,
                  pipeline review, deal strategy, win/loss
                  debrief, competitive discussion
  skip          - internal operational: standup, product
                  planning, recruiting, all-hands, 1:1

Enrichment profiles by intent:
  prospect    → extract objections + feature gaps (existing)
  sales_review → extract deal risk flags, competitive
                 signals, pipeline accuracy signals (new)
  skip        → no enrichment

Usage:
  from scripts.enrichment.call_intent_classifier import (
      classify_call, INTENT_PROSPECT,
      INTENT_SALES_REVIEW, INTENT_SKIP
  )
  intent = classify_call(call_data, client)

NOTE ON REAL CACHE DATA:
  memory/calls/*.json stores `participants` as an integer
  count, never a list of {email: ...} dicts, and carries no
  `tags` key at all. The participant/tag rules below are
  therefore only exercised by callers that supply richer
  metadata (or by tests). Everything here treats missing
  email data as "unknown" rather than "all internal", so a
  count never masquerades as a roster.
"""

import json

INTENT_PROSPECT     = "prospect"
INTENT_SALES_REVIEW = "sales_review"
INTENT_SKIP         = "skip"

INTERNAL_DOMAIN = "growthbook.io"  # keep for email checks
# Company *names* never carry the domain suffix — the cache stores
# "GrowthBook", "GrowthBook AI", "EA + GrowthBook". Matching those
# against the domain string reads them as external, so name checks
# use these tokens instead.
INTERNAL_COMPANY_TOKENS = ("growthbook", "growth book")

# Keywords that strongly signal sales review intent
SALES_REVIEW_KEYWORDS = [
    "forecast", "pipeline review", "commit", "upside",
    "at risk", "deal review", "pipeline call",
    "win/loss", "win loss", "post-mortem", "lost deal",
    "competitive", "statsig", "launchdarkly",
    "quota", "attainment", "number", "target",
    "qbr", "quarterly business review",
    "rep review", "account review",
    "best case", "most likely",
]

# Keywords that signal skip intent
SKIP_KEYWORDS = [
    "standup", "stand-up", "stand up",
    "all hands", "all-hands",
    "product planning", "roadmap planning",
    "recruiting", "interview", "candidate",
    "onboarding", "orientation",
    "design review", "eng review", "sprint",
    "retro", "retrospective",
    "1:1", "one on one", "one-on-one",
    "social", "happy hour", "team lunch",
]

CLASSIFICATION_PROMPT = """Classify this sales call by intent.

Call title: {title}
Participants: {participants}
Summary excerpt: {summary_excerpt}

Intent options:
  prospect      - conversation with an external prospect
                  or customer (even if internal staff also
                  present). Or: any call containing deal-
                  specific objections, demo feedback,
                  pricing discussions, technical evaluation.
  sales_review  - internal sales team call with valuable
                  sales intelligence: forecast review,
                  pipeline health, deal strategy, win/loss
                  debrief, competitive intelligence.
                  Includes calls where reps discuss specific
                  deals, risks, or competitive situations.
  skip          - internal operational call with no sales
                  intelligence value: standup, product
                  planning, engineering review, recruiting,
                  all-hands, 1:1 between non-sales staff.

Respond with JSON only:
{{
  "intent": "prospect" | "sales_review" | "skip",
  "confidence": 0.0-1.0,
  "reason": "one sentence explanation"
}}"""


def _is_internal_company(company: str) -> bool:
    """
    True when a company name refers to GrowthBook and nothing else.

    Cache company names pair both sides of the call — "Acorns +
    GrowthBook", "GrowthBook <> ECCO" — so a bare substring test for
    "growthbook" marks every prospect internal. slugify() strips the
    GrowthBook half and returns '' only when nothing else remains
    ("GrowthBook", "GrowthBook AI", "EA + GrowthBook"), which is
    exactly the internal set.
    """
    if not company:
        return False
    try:
        from utils import slugify
    except ImportError:
        # Standalone use without scripts/ on sys.path — fall back to a
        # whole-name match, correct for the bare internal names.
        return company.strip().lower() in INTERNAL_COMPANY_TOKENS
    return not slugify(company)


def _participant_emails(participants) -> list:
    """
    Extract known participant emails.

    Real cache data stores `participants` as an integer count,
    so anything that is not a list of mappings carrying an
    'email' yields no emails at all.
    """
    if not isinstance(participants, list):
        return []
    return [
        (p.get("email") or "").lower()
        for p in participants
        if isinstance(p, dict) and p.get("email")
    ]


def _all_internal(participants) -> bool:
    """
    True only if every participant with a known email is on the
    internal domain.

    Returns False when no email data exists (including the integer
    participant counts the call cache actually stores) — "unknown"
    must never be mistaken for "all internal", and this must never
    raise on a non-list input.
    """
    emails = _participant_emails(participants)
    if not emails:
        return False
    return all(INTERNAL_DOMAIN in e for e in emails)


def _keyword_classify(title: str,
                       summary: str) -> str | None:
    """
    Fast keyword-based classification.
    Returns intent or None if ambiguous (needs LLM).
    """
    text = (title + " " + summary[:500]).lower()

    # Strong skip signals
    if any(kw in text for kw in SKIP_KEYWORDS):
        return INTENT_SKIP

    # Strong sales review signals
    if any(kw in text for kw in SALES_REVIEW_KEYWORDS):
        return INTENT_SALES_REVIEW

    return None  # Needs LLM


def classify_call(call_data: dict,
                  client=None,
                  use_llm: bool = True) -> dict:
    """
    Classify a call by intent.

    Args:
        call_data: dict with keys: title, participants,
                   summary, company (optional)
        client: anthropic.Anthropic() instance (for LLM
                fallback). If None, keyword-only.
        use_llm: whether to use LLM for ambiguous cases

    Returns:
        {
          "intent": INTENT_PROSPECT | INTENT_SALES_REVIEW
                    | INTENT_SKIP,
          "confidence": float,
          "reason": str,
          "method": "rule" | "llm",
        }
    """
    title   = call_data.get("title", "") or ""
    summary = call_data.get("summary", "") or ""
    participants = call_data.get("participants", []) or []
    company = call_data.get("company", "") or ""

    emails_known = bool(_participant_emails(participants))

    # Rule 1: external participant → prospect
    if emails_known and not _all_internal(participants):
        return {
            "intent": INTENT_PROSPECT,
            "confidence": 0.95,
            "reason": "External participant present",
            "method": "rule",
        }

    # Rule 2: no participant email data + has company name
    # → treat as prospect (legacy calls without metadata).
    # The call cache only carries a participant *count*, so this
    # is the path virtually every real enrichment call takes.
    if not emails_known and company and \
       not _is_internal_company(company):
        return {
            "intent": INTENT_PROSPECT,
            "confidence": 0.7,
            "reason": "No participant data, external company",
            "method": "rule",
        }

    # Rule 3: Fireflies/Gong tags
    tags = [str(t).lower() for t in (call_data.get("tags") or [])]
    if "skip-enrichment" in tags:
        return {
            "intent": INTENT_SKIP,
            "confidence": 1.0,
            "reason": "Explicitly tagged skip-enrichment",
            "method": "rule",
        }
    if "prospect-call" in tags:
        return {
            "intent": INTENT_PROSPECT,
            "confidence": 1.0,
            "reason": "Explicitly tagged prospect-call",
            "method": "rule",
        }
    if "sales-review" in tags:
        return {
            "intent": INTENT_SALES_REVIEW,
            "confidence": 1.0,
            "reason": "Explicitly tagged sales-review",
            "method": "rule",
        }

    # Rule 4: keyword classification
    keyword_intent = _keyword_classify(title, summary)
    if keyword_intent:
        return {
            "intent": keyword_intent,
            "confidence": 0.85,
            "reason": f"Keyword match → {keyword_intent}",
            "method": "rule",
        }

    # Rule 5: all internal + no keywords → LLM or skip
    if _all_internal(participants):
        if not use_llm or client is None:
            return {
                "intent": INTENT_SKIP,
                "confidence": 0.6,
                "reason": "All internal, no sales keywords",
                "method": "rule",
            }

        # LLM classification for ambiguous cases
        try:
            participant_list = [
                p.get("email", "unknown")
                for p in participants[:5]
                if isinstance(p, dict)
            ]
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                system="Respond with valid JSON only.",
                messages=[{"role": "user", "content":
                    CLASSIFICATION_PROMPT.format(
                        title=title[:100],
                        participants=", ".join(participant_list),
                        summary_excerpt=summary[:300],
                    )
                }]
            )
            text = resp.content[0].text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            result = json.loads(text)
            result["method"] = "llm"
            return result
        except Exception as e:
            # LLM failed — default to skip for all-internal
            return {
                "intent": INTENT_SKIP,
                "confidence": 0.5,
                "reason": f"LLM classification failed: {e}",
                "method": "rule",
            }

    # Default: can't determine, skip
    return {
        "intent": INTENT_SKIP,
        "confidence": 0.4,
        "reason": "Cannot determine intent",
        "method": "rule",
    }


# Enrichment routing table
ENRICHMENT_PROFILE = {
    INTENT_PROSPECT: {
        "extract_objections": True,
        "extract_feature_gaps": True,
        "extract_sales_signals": False,
    },
    INTENT_SALES_REVIEW: {
        "extract_objections": False,
        "extract_feature_gaps": False,
        "extract_sales_signals": True,
    },
    INTENT_SKIP: {
        "extract_objections": False,
        "extract_feature_gaps": False,
        "extract_sales_signals": False,
    },
}
