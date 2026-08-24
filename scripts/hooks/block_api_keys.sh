#!/bin/bash
# Block commits containing API key patterns and forbidden client names
# Called by pre-commit framework (see .pre-commit-config.yaml)

# Check for Anthropic API keys (sk-ant-...)
# Check for HubSpot tokens (pat-na1-..., pat-eu1-...)
# Check for generic long hex strings (32+ chars, likely secrets)

if git diff --cached | grep -nE "sk-ant-|pat-na1|pat-eu1|[a-f0-9]{32,}" >/dev/null; then
  echo "❌ BLOCKED: Staged changes contain what looks like an API key or secret."
  echo ""
  echo "Detected patterns:"
  git diff --cached | grep -nE "sk-ant-|pat-na1|pat-eu1|[a-f0-9]{32,}" | head -5
  echo ""
  echo "Fix: Move credentials to environment variables (.env) before committing."
  echo "Never commit API keys, access tokens, or other secrets to version control."
  exit 1
fi

# Check for forbidden client-specific names (if list exists)
# Names are stored in gitignored .forbidden_names file (one per line)
FORBIDDEN_NAMES_FILE=".forbidden_names"

if [ -f "$FORBIDDEN_NAMES_FILE" ]; then
  while IFS= read -r name; do
    # Skip empty lines and comments
    [[ -z "$name" || "$name" =~ ^# ]] && continue

    # Check if name appears in staged changes (case insensitive, word boundary)
    if git diff --cached | grep -niE "\b${name}\b" >/dev/null; then
      echo "❌ BLOCKED: Staged changes contain forbidden client-specific naming."
      echo ""
      echo "Detected forbidden name in:"
      git diff --cached | grep -niE "\b${name}\b" | head -3
      echo ""
      echo "Fix: Replace with generic 'template' or 'client' language."
      echo "This repo must be client-agnostic - describe code properties, not recipients."
      exit 1
    fi
  done < "$FORBIDDEN_NAMES_FILE"
fi
