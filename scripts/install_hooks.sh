#!/bin/bash
# Install pre-commit hooks for secret protection
# Run this after cloning the repo: ./scripts/install_hooks.sh

set -e

echo "Installing pre-commit hooks..."

# Check if pre-commit is installed
if ! command -v pre-commit &> /dev/null; then
    echo "❌ pre-commit not found. Installing..."

    # Try pip install
    if command -v pip3 &> /dev/null; then
        pip3 install pre-commit
    elif command -v pip &> /dev/null; then
        pip install pre-commit
    else
        echo "❌ Error: pip not found. Install pre-commit manually:"
        echo "   pip install pre-commit"
        echo "   Or: brew install pre-commit (macOS)"
        exit 1
    fi
fi

# Install hooks
pre-commit install

# Create empty secrets baseline if it doesn't exist
if [ ! -f .secrets.baseline ]; then
    echo "Creating .secrets.baseline..."
    detect-secrets scan > .secrets.baseline 2>/dev/null || echo "{}" > .secrets.baseline
fi

echo "✅ Pre-commit hooks installed successfully!"
echo ""
echo "What this does:"
echo "  • Blocks commits containing API keys (Anthropic, HubSpot patterns)"
echo "  • Scans for secrets using detect-secrets"
echo "  • Prevents large files (>1MB) from being committed"
echo ""
echo "To bypass (use sparingly): git commit --no-verify"
