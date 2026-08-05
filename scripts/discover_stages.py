#!/usr/bin/env python3
"""
HubSpot Stage Discovery Tool

Connects to HubSpot and prints all pipeline stages with their IDs.
Output is formatted for easy copying into config/client.yaml.

Usage:
    export HUBSPOT_API_KEY="pat-na1-..."
    python scripts/discover_stages.py

Output:
    Prints all pipelines and stages in YAML format
    Copy relevant sections into config/client.yaml
"""
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from hubspot_deals import HubSpotDeals
except ImportError:
    print("❌ Error: hubspot_deals.py not found")
    print("   Make sure you're running from the repo root")
    sys.exit(1)


def format_stage_for_yaml(stage, indent=4):
    """Format a stage dict as YAML with proper indentation"""
    spaces = " " * indent
    return (
        f"{spaces}- name: \"{stage['label']}\"\n"
        f"{spaces}  id: \"{stage['id']}\""
    )


def main():
    # Check for API key
    api_key = os.getenv("HUBSPOT_API_KEY")
    if not api_key:
        print("❌ Error: HUBSPOT_API_KEY environment variable not set")
        print("\nUsage:")
        print("    export HUBSPOT_API_KEY=\"pat-na1-your-key-here\"")
        print("    python scripts/discover_stages.py")
        sys.exit(1)

    print("🔍 Discovering HubSpot Pipeline Stages...\n")

    # Initialize HubSpot client
    try:
        hubspot = HubSpotDeals(api_key)
    except Exception as e:
        print(f"❌ Error initializing HubSpot client: {e}")
        sys.exit(1)

    # Fetch all pipelines
    try:
        endpoint = "/crm/v3/pipelines/deals"
        response = hubspot._get(endpoint)
        pipelines = response.get('results', [])

        if not pipelines:
            print("⚠️  No pipelines found")
            sys.exit(1)

        print(f"✅ Found {len(pipelines)} pipeline(s)\n")
        print("=" * 80)
        print("COPY THIS INTO config/client.yaml")
        print("=" * 80)
        print()

        # Print each pipeline with its stages
        for pipeline in pipelines:
            pipeline_label = pipeline.get('label', 'Unknown')
            pipeline_id = pipeline.get('id', 'unknown')
            stages = pipeline.get('stages', [])

            # Print pipeline header
            print(f"# {pipeline_label} (ID: {pipeline_id})")
            print(f"# {len(stages)} stages")
            print()

            # Print stages
            for idx, stage in enumerate(stages, 1):
                stage_label = stage.get('label', 'Unknown')
                stage_id = stage.get('id', 'unknown')
                metadata = stage.get('metadata', {})
                is_closed_won = metadata.get('isClosed') == 'true' and metadata.get('probability') == '1.0'
                is_closed_lost = metadata.get('isClosed') == 'true' and metadata.get('probability') == '0.0'

                # Add annotations for special stages
                annotation = ""
                if is_closed_won:
                    annotation = "  # ← Closed Won stage"
                elif is_closed_lost:
                    annotation = "  # ← Closed Lost stage"
                elif 'meeting' in stage_label.lower() or 'appointment' in stage_label.lower():
                    annotation = "  # ← Consider excluding (too early)"
                elif 'disqualified' in stage_label.lower():
                    annotation = "  # ← Consider excluding (disqualified)"

                print(f"  {idx}. {stage_label:<30} (ID: {stage_id}){annotation}")

            print()
            print("-" * 80)
            print()

        # Print suggested configuration sections
        print()
        print("=" * 80)
        print("SUGGESTED CONFIGURATION SECTIONS")
        print("=" * 80)
        print()

        # Suggest pipelines to include/exclude
        print("# Pipelines to include in active deal analysis:")
        print("pipelines:")
        print("  included:")
        for pipeline in pipelines:
            label = pipeline.get('label', 'Unknown')
            pid = pipeline.get('id', 'unknown')
            # Suggest excluding renewal pipelines
            if 'renewal' in label.lower():
                print(f"    # - name: \"{label}\"  # ← Excluded below")
            else:
                print(f"    - name: \"{label}\"")
            print(f"      id: \"{pid}\"")
        print()

        print("  excluded:")
        for pipeline in pipelines:
            label = pipeline.get('label', 'Unknown')
            pid = pipeline.get('id', 'unknown')
            if 'renewal' in label.lower():
                print(f"    - name: \"{label}\"")
                print(f"      id: \"{pid}\"")
        print()

        # Suggest stages to exclude
        print("# Stages to exclude from active deal analysis:")
        print("excluded_stages:")
        print("  meeting_set:")

        meeting_stages = []
        for pipeline in pipelines:
            for stage in pipeline.get('stages', []):
                label = stage.get('label', '')
                sid = stage.get('id', '')
                if any(keyword in label.lower() for keyword in ['meeting', 'appointment', 'scheduled']):
                    if sid not in [s['id'] for s in meeting_stages]:
                        meeting_stages.append({'label': label, 'id': sid})

        if meeting_stages:
            for stage in meeting_stages:
                print(format_stage_for_yaml(stage))
        else:
            print("    # No meeting-related stages found")

        print()
        print("  disqualified:")

        disqualified_stages = []
        for pipeline in pipelines:
            for stage in pipeline.get('stages', []):
                label = stage.get('label', '')
                sid = stage.get('id', '')
                if 'disqualified' in label.lower():
                    if sid not in [s['id'] for s in disqualified_stages]:
                        disqualified_stages.append({'label': label, 'id': sid})

        if disqualified_stages:
            for stage in disqualified_stages:
                print(format_stage_for_yaml(stage))
        else:
            print("    # No disqualified stages found")

        print()
        print("  closed_won:")

        closed_won_stages = []
        for pipeline in pipelines:
            for stage in pipeline.get('stages', []):
                metadata = stage.get('metadata', {})
                if metadata.get('isClosed') == 'true' and metadata.get('probability') == '1.0':
                    label = stage.get('label', '')
                    sid = stage.get('id', '')
                    if sid not in [s['id'] for s in closed_won_stages]:
                        closed_won_stages.append({'label': label, 'id': sid})

        if closed_won_stages:
            for stage in closed_won_stages:
                print(format_stage_for_yaml(stage))
        else:
            print("    # No closed won stages found")

        print()
        print("  closed_lost:")

        closed_lost_stages = []
        for pipeline in pipelines:
            for stage in pipeline.get('stages', []):
                metadata = stage.get('metadata', {})
                if metadata.get('isClosed') == 'true' and metadata.get('probability') == '0.0':
                    label = stage.get('label', '')
                    sid = stage.get('id', '')
                    if sid not in [s['id'] for s in closed_lost_stages]:
                        closed_lost_stages.append({'label': label, 'id': sid})

        if closed_lost_stages:
            for stage in closed_lost_stages:
                print(format_stage_for_yaml(stage))
        else:
            print("    # No closed lost stages found")

        print()
        print("=" * 80)
        print()
        print("✅ Stage discovery complete!")
        print()
        print("Next steps:")
        print("  1. Copy relevant sections above into config/client.yaml")
        print("  2. Review excluded pipelines and stages")
        print("  3. Adjust stage progression requirements if needed")
        print()

    except Exception as e:
        print(f"❌ Error fetching pipelines: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
