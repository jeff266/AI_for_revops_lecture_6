# RevOps Client Context Skill

**NOTE**: This is a placeholder for the SKILL.md content.

The actual skill content should be pasted here from the course materials.

This file should contain the complete context interview script that:
1. Asks about the client's product and ICP
2. Collects competitor information
3. Identifies common objection categories
4. Discovers feature gaps prospects mention
5. Reviews HubSpot stage names and progression
6. Sets learning preferences
7. Writes four output files based on responses

When Claude Code reads this file via the root CLAUDE.md instructions,
it will run this interview inline to configure the agent for a specific client.

## Expected Interview Flow

The skill should ask about:

### Product & ICP
- What does the product do?
- Who is the ideal customer?
- What industries do you serve?

### Competitors
- Direct competitors (same category)
- Indirect competitors (adjacent solutions)
- Incumbent solutions (homegrown, manual processes)

### Objections
- Pricing objections and typical responses
- Timing objections and how to handle them
- Technical complexity concerns
- Feature gap patterns
- Stakeholder alignment challenges

### Feature Gaps
- High priority gaps (frequently requested, high deal impact)
- Medium and low priority gaps
- Workarounds for each gap
- Roadmap status

### Value Metrics
- Revenue metrics (conversion rate, ARPU)
- Cost savings (failed releases, engineering efficiency)
- Risk reduction (rollback time, deployment risk)
- Velocity improvements (release frequency, time to value)

### Learning Preferences
- Prompt update frequency
- Minimum iterations before auto-update
- Failure pattern tracking preferences

## Output Files

The skill should write:

1. **config/client.yaml** - Stage IDs, pipeline config, thresholds
2. **config/context.yaml** - Competitors, objections, feature gaps, value metrics
3. **prompts/CLAUDE.md** - Customized generator system prompt
4. **prompts/evaluator_rubric.md** - Customized evaluation criteria

## To Complete This File

Replace this placeholder content with the actual SKILL.md from:
- Course materials → skills → revops-client-context → SKILL.md
- Or from the skill package source files
