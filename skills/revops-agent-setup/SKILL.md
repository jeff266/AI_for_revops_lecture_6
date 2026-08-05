# RevOps Agent Setup Skill

**NOTE**: This is a placeholder for the SKILL.md content.

The actual skill content should be pasted here from the course materials.

This file should contain the complete credential interview script that:
1. Collects HubSpot API key
2. Collects Fireflies API key
3. Collects Apollo.io API key
4. Collects Anthropic API key
5. Collects Supabase URL and service key
6. Writes all credentials to .env file
7. Prints GitHub Secrets checklist

When Claude Code reads this file via the root CLAUDE.md instructions,
it will run this interview inline to set up a fresh fork of the repo.

## Expected Interview Flow

The skill should:
- Introduce itself and explain what it will collect
- Ask for each credential one at a time
- Validate format where possible (e.g., API keys start with expected prefixes)
- Explain what each credential is used for
- Write the complete .env file
- Print final checklist of GitHub Secrets to add

## Output Format

The skill should write a .env file in this format:

```
# HubSpot Configuration
HUBSPOT_API_KEY=pat-na1-...

# Call Transcript Sources
FIREFLIES_API_KEY=...
APOLLO_API_KEY=...

# AI Model
ANTHROPIC_API_KEY=sk-ant-...

# Supabase
SUPABASE_URL=https://...supabase.co
SUPABASE_SERVICE_KEY=eyJhbGci...
```

## To Complete This File

Replace this placeholder content with the actual SKILL.md from:
- Course materials → skills → revops-agent-setup → SKILL.md
- Or from the skill package source files
