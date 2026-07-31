# Cost Comparison: Model Routing Strategy

## Current Architecture (Haiku + Sonnet)

- **Context Builder**: Claude Haiku 4.5 ($1/M input, $5/M output)
- **Generator**: Claude Sonnet 4.5 ($3/M input, $15/M output)
- **Evaluator**: Claude Haiku 4.5 ($1/M input, $5/M output)
- **Reflection Gate**: Claude Haiku 4.5 ($1/M input, $5/M output)

## Pricing Comparison

| Model | Input ($/M) | Output ($/M) | Use Case |
|-------|------------|--------------|----------|
| **Claude Haiku 4.5** | $1.00 | $5.00 | Structured extraction, JSON validation |
| **Claude Sonnet 4.5** | $3.00 | $15.00 | Complex analysis, reasoning, generation |
| **Claude Opus 4.5** | $15.00 | $75.00 | Maximum capability (overkill for this) |
| **Kimi K3 (Fireworks)** | $3.00 | $15.00 | Frontier-tier (same as Sonnet) |

**Note on Kimi K3 Pricing**: K3 was initially evaluated at a promotional rate (~$0.27/M) and showed excellent performance in the Frontera contract extraction project. However, current production pricing is $3/$15 per million tokens — identical to Claude Sonnet 4.5. At this pricing, Claude Haiku ($1/$5) is more cost-effective for structured extraction tasks.

## Cost Per Deal Breakdown

**Typical Deal** (2 iterations to pass, 14 historical calls):

| Component | Tokens (est.) | Model | Cost |
|-----------|---------------|-------|------|
| Context Builder | 5,200 input + 3,500 output | Haiku | $0.023 |
| Generator (x2) | 8,000 input + 5,000 output | Sonnet | $0.174 |
| Evaluator (x2) | 12,000 input + 1,600 output | Haiku | $0.020 |
| Reflection (x2) | 1,000 input + 200 output | Haiku | $0.002 |
| **TOTAL** | **~42K tokens** | **Haiku + Sonnet** | **$0.219** |

**Alternative with Kimi K3 for extraction:**

| Component | Tokens (est.) | Model | Cost |
|-----------|---------------|-------|------|
| Context Builder | 5,200 input + 3,500 output | **Kimi K3** | $0.068 |
| Generator (x2) | 8,000 input + 5,000 output | Sonnet | $0.174 |
| Evaluator (x2) | 12,000 input + 1,600 output | **Kimi K3** | $0.060 |
| Reflection (x2) | 1,000 input + 200 output | **Kimi K3** | $0.006 |
| **TOTAL** | **~42K tokens** | **Kimi + Sonnet** | **$0.308** |

**Savings with Haiku**: **$0.089 per deal** (**29% cheaper** than Kimi K3 hybrid)

## Monthly Cost (50 deals/night × 30 days)

| Architecture | Cost Per Deal | Monthly Cost (1,500 deals) | Annual Cost |
|--------------|---------------|----------------------------|-------------|
| **Haiku + Sonnet (Current)** | $0.219 | **$328.50** | $3,942 |
| Kimi K3 + Sonnet | $0.308 | $462.00 | $5,544 |
| All Sonnet | $0.435 | $652.50 | $7,830 |
| All Opus | $2.175 | $3,262.50 | $39,150 |

**vs All-Sonnet**: Saves **$324/month** (**50% reduction**)
**vs Kimi Hybrid**: Saves **$133.50/month** (**29% reduction**)

## Why Haiku for Extraction?

**Structured JSON extraction tasks don't need Sonnet-tier reasoning:**
- Context builder: Extract MEDDICC evidence from call summaries → JSON
- Evaluator: Check analysis against rubric → Pass/fail JSON
- Reflection: Categorize outcome → Outcome/root_cause JSON

**Haiku excels at:**
- ✅ Pattern matching and extraction
- ✅ JSON structure validation
- ✅ Binary decisions (pass/fail)
- ✅ Classification tasks

**Sonnet is needed for:**
- ✅ Complex multi-step reasoning
- ✅ Evidence synthesis across calls
- ✅ Strategic recommendations
- ✅ Natural language generation

## Quality Validation

**Frontera Contract Project (Kimi K3 at promotional pricing)**:
- Successfully extracted 400+ contracts
- JSON parse rate: 98%+
- Cost at promotional rate: $0.90/M
- Quality: Excellent for structured extraction

**Current Status**: Kimi K3 now at frontier pricing ($3/$15), making Haiku the better choice for extraction at $1/$5.

## Recommendation

✅ **Use Haiku + Sonnet (Current Architecture)**

**Rationale**:
1. **Cost-effective**: 50% cheaper than all-Sonnet, 29% cheaper than Kimi hybrid
2. **Quality preserved**: Sonnet for generation where it matters
3. **Anthropic-native**: No multi-vendor dependency
4. **Proven**: Haiku handles structured extraction well
5. **Simple**: Single API, single billing

**Model Assignments**:
- Context Builder → **Haiku** (structured extraction from call summaries)
- Generator → **Sonnet** (complex MEDDICC analysis)
- Evaluator → **Haiku** (rubric validation, pass/fail decision)
- Reflection Gate → **Haiku** (outcome classification)

## When to Reconsider

**Use Kimi K3 if**:
- Promotional pricing returns (~$0.27/M)
- Your specific extraction task shows measurably better results with K3
- Multi-vendor architecture is required for other reasons

**Use All-Sonnet if**:
- Cost is not a constraint
- Maximum consistency across all components is critical
- You want to eliminate any quality variance

**Use Opus if**:
- You have money to burn ($39K/year for 1,500 deals/month)

## Implementation Status

**Current Setup**:
- ✅ Context Builder: Claude Haiku 4.5
- ✅ Generator: Claude Sonnet 4.5
- ✅ Evaluator: Claude Haiku 4.5
- ✅ Reflection Gate: Claude Haiku 4.5

**All components using Anthropic SDK** — no Fireworks AI dependency.

---

**Last Updated**: 2026-07-30
**Pricing Verified**: Kimi K3 = $3/$15 (frontier tier, not promotional)
**Status**: Production-ready with Haiku + Sonnet architecture
