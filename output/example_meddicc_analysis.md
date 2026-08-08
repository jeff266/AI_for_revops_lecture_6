> **Note for students**: This is an anonymized example showing what a high-quality MEDDICC analysis looks like after 13 calls. Company name, contacts, and product details have been changed. Your first run will produce similar output for your active deals. This example uses MEDDICC; your output follows whichever methodology you configure.

# MEDDICC Analysis: Acme Corp

**Deal ID:** 000000000000
**Generated:** YYYY-MM-DD HH:MM:SS UTC
**Calls Analyzed:** 13
**Iterations:** 1
**Status:** ✓ Passed

---

# MEDDICC Analysis: Acme Corp

## Deal Context
- **Stage**: Presentation Scheduled
- **ARR**: $125,000
- **Expected Close**: End of Q4 2026
- **Contacts**: Alex Chen (Evaluation Lead), Sarah Kim (Product Manager/Main POC), Tom Walsh (Engineering Manager), Priya Patel (Engineering Manager), Jordan Lee (Analytics Lead), Marco Silva (Product Strategy), Chris Park (Procurement)

## MEDDICC Assessment

### M - Metrics
**Status**: ✅ Identified
**Score**: 9/10

Acme Corp has clear quantifiable targets tied to experimentation velocity and revenue impact. They plan to scale from 30-100 experiments in H2 2026 to 1,000 experiments annually by 2027. The Q4 content experiments are specifically aimed at driving "significant incremental revenue from core product vertical." User scaling metrics are precise: 50 users in Q4 2026, growing to 300-400 users by mid-2027.

**Evidence from calls**: Recent call confirmed the phased timeline: "Q3 dev evaluation (mid-quarter to end of Q3), Q4 production testing with 50 users, then full rollout in 2027." Previous calls established: "30 to 100 experiments in latter half of 2026, reaching 1000 annually by 2027. Revenue expectations from Q4 content experiments aimed at driving significant incremental revenue from core product vertical."

**Next steps**: During commercial quote discussion next week, quantify expected ROI from increased experiment velocity (e.g., "If you hit 1000 experiments vs current rate, what's the expected revenue impact?")

### E - Economic Buyer
**Status**: ⚠️ Partial
**Score**: 6/10

Chris from procurement has been identified as involved in commercial decisions, and Tom Walsh has demonstrated decision authority (providing user numbers, coordinating proposals). However, the ultimate budget holder with final signature authority remains unclear. Multiple senior stakeholders (Alex Chen leading evaluation, Jordan Lee, Marco Silva) suggest committee-based decision making.

**Evidence from calls**: Recent call: "Connect Chris Park (Procurement) next week" and "Vendor to provide commercial quote for Q4 (50 licenses) and discuss structure for 2027." Previous calls noted: "Tom Walsh appears to have decision authority (tasked with emailing user numbers)."

**Next steps**: Ask Sarah Kim in next week's procurement call with Chris: "Walk me through the approval process once you receive our quote. After Chris reviews pricing, who needs to sign off before we can move to contract? Is there a budget threshold that requires VP or C-level approval?"

### D - Decision Criteria
**Status**: ✅ Identified
**Score**: 9/10

Technical and business requirements are well-documented across multiple dimensions: enterprise features (fine-grain permissions, audit logs, efficient database queries), visual editor for non-technical CX teams, self-hosting preference, data warehouse integration, SPA implementation without flicker, AI capabilities, and compliance program support. Recent call added specific requirements for content experimentation with CMS integration (their CMS platform) and feature flagging evaluation.

**Evidence from calls**: Recent call: "Content experimentation on web, integration with CMS (their CMS platform), phased approach from dev evaluation to production. Feature flagging evaluation, AA tests, ad tests." Previous calls: "Enterprise features required: fine-grain permissions, audit logs, 10x more efficient database queries. Visual editor for non-technical CX teams. Hybrid architecture integrating with existing tools. Self-hosting option preferred."

**Next steps**: Confirm with Sarah during evaluation criteria finalization: "Are there any additional technical requirements for the their CMS platform integration or feature flagging that we should address in the Q3 evaluation plan?"

### D - Decision Process
**Status**: ✅ Identified
**Score**: 9/10

The decision process is clearly mapped with specific dates and phases: Q3 dev evaluation (mid-quarter to end of Q3), evaluation criteria and technical design finalization in progress, decision target end of quarter, Q4 production testing with 50 users starting around Q4 start, full rollout in 2027. Commercial structure involves separating technical evaluation from procurement discussions, with Chris Park (Procurement) engagement next week and regular weekly check-ins established.

**Evidence from calls**: Recent call: "Timeline: Q3 dev evaluation (mid-quarter to end of Q3), Q4 production testing with 50 users, then full rollout in 2027. Acme Corp team to finalize evaluation criteria and technical design; Vendor to provide commercial quote for Q4 (50 licenses). Connect Chris Park (Procurement) next week. Regular weekly check-ins." Previous calls: "Decision target by end of quarter. Operational start by Q4 start, with testing extending into early Q4."

**Next steps**: Confirm with Chris in next week's procurement call: "After you review the Q4 quote, what's your internal timeline for budget approval? Are there any fiscal year constraints or quarterly budget cycles we should be aware of for the Q4 start?"

### I - Identified Pain
**Status**: ✅ Identified
**Score**: 9/10

Multiple acute pain points are well-documented: current in-house platform ("Dr. Legacy") lacks scalability for desired experiment velocity, non-technical CX teams cannot run copy-only tests independently, data integration requires extensive BI team collaboration, compliance program creates delays, and they need to democratize experimentation while maintaining control. The urgency is clear: they want to move from current experiment rates to 1000 annually by 2027.

**Evidence from calls**: Recent call: "Acme Corp currently using internal tool 'Dr. Legacy' and wants to migrate. Pain points: need for content experimentation on web, integration with CMS (their CMS platform)." Previous calls: "Experiment velocity challenges. Scalability concerns with current in-house experimentation platform. Need to democratize copy-only tests to non-technical teams. Data integration challenges requiring BI team collaboration. Compliance program delays."

**Next steps**: No additional discovery needed - pain is well-established. Focus on demonstrating how the platform solves these specific challenges during Q3 evaluation.

### C - Champion
**Status**: ⚠️ Partial
**Score**: 6/10

Sarah Kim is the main POC and product manager moving to experimentation full-time, indicating strong ownership. Tom Walsh actively coordinates proposals and user estimates, showing advocacy. However, there's no explicit evidence of someone who will "sell on behalf of the platform" in internal meetings when the team isn't present. Multiple influential stakeholders (Jordan Lee, Marco Silva) exist but their level of advocacy is unclear.

**Evidence from calls**: Recent call: "Sarah Kim (Acme Corp - product manager moving to experimentation, main POC contact)" and "Tom Walsh (Acme Corp - likely product or engineering manager)" actively engaged. Previous calls: "Tom Walsh appears to be a key internal advocate, tasked with providing user estimates and coordinating on proposals. However, no explicit internal champion identified who will 'sell on behalf' internally."

**Next steps**: Ask Sarah in Friday's check-in: "As you finalize the evaluation criteria with Alex and Tom, are there any internal stakeholders who might have concerns about moving from Dr. Legacy to an external platform? Who should we make sure is fully bought in before the end of quarter decision?"

### C - Competition
**Status**: ⚠️ Partial
**Score**: 5/10

The primary "competition" is their internal platform "Dr. Legacy" and the option to continue building in-house (hybrid build-vs-buy approach mentioned previously). Recent call confirms they're actively migrating away from Dr. Legacy but no other external vendors are explicitly mentioned. The fact they're evaluating feature flagging, AA tests, and ad tests suggests they may be looking at alternatives, but no competitors are named.

**Evidence from calls**: Recent call: "Acme Corp currently using internal tool 'Dr. Legacy' and wants to migrate." Previous calls: "Acme Corp has an existing in-house experimentation platform and is considering hybrid build-vs-buy architecture, implying they could build internally. No specific competitor solutions explicitly mentioned by name."

**Next steps**: Ask Sarah or Alex during evaluation criteria discussion: "Are you evaluating any other experimentation platforms alongside the platform? Understanding your selection criteria relative to other options would help us tailor our POC to what matters most in your comparison."

## Summary & Recommended Actions

Acme Corp deal is progressing well with clear technical requirements, timeline, and pain points. Strong momentum toward Q3 evaluation and Q4 production start. Primary gaps: no confirmed economic buyer with final budget authority, champion advocacy level unclear, and competitive landscape unknown beyond internal build option. The end of quarter decision deadline is 30-45 days away.

**Immediate next steps**:
1. **This week**: Add Jamie (solutions engineer) to Slack channel and ensure evaluation criteria document is shared for review before finalization
2. **Next week (Chris procurement call)**: Ask Chris to walk through approval process after quote review, identify who has final signature authority, and confirm Q4 budget availability with fiscal year constraints
3. **Next Friday check-in with Sarah**: Identify potential internal skeptics about moving from Dr. Legacy, ask about other platforms being evaluated, and ensure Jordan Lee and Marco Silva are aligned on the end of quarter timeline

**Deal risks**:
- **Economic buyer unclear**: Without knowing who controls final budget approval, pricing discussions with Chris may stall. Risk: Quote gets stuck in procurement limbo or requires unexpected VP/C-level escalation.
- **No confirmed champion**: Sarah and Tom are engaged, but no evidence anyone will advocate strongly in internal meetings. Risk: Deal loses momentum if technical evaluation goes well but lacks internal champion to drive decision by Sept 30.
- **Unknown competition**: If they're evaluating alternatives beyond build-vs-buy, we're blind to our differentiation opportunities. Risk: Another vendor could be addressing pain points we haven't positioned against.

**Win likelihood**: Medium-High - Strong technical alignment, clear timeline, and well-documented pain, but economic buyer and champion gaps create execution risk. end of quarter decision date is aggressive (30-45 days) and requires rapid procurement cycle with currently unknown approval process.
