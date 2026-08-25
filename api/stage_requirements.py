"""
Stage-aware MEDDICC requirements for deal risk assessment.

Loads stage progression requirements from config/client.yaml and provides
helpers to determine which components are expected at each stage.

Design: Stage requirements are derived from config ONLY, never hardcoded.
Uses stage.order to map to stage_progression entries, making this work
for any client's stage IDs/names without code changes.
"""
import sys
import yaml
from pathlib import Path
from typing import Dict, Optional

# Add scripts to path for utils
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / 'scripts'))

from utils import get_components, component_key, get_methodology

# Cache the config to avoid repeated file reads
_config_cache = None
_stage_lookup_cache = None

def _load_config() -> dict:
    """Load config from client.yaml (cached)."""
    global _config_cache
    if _config_cache is None:
        config_path = Path(__file__).parent.parent / "config" / "client.yaml"
        with open(config_path) as f:
            _config_cache = yaml.safe_load(f)
    return _config_cache


def _get_stage_lookup() -> Dict[str, dict]:
    """
    Build stage lookup from config: {stage_id: {name, order, flags}}.
    Cached to avoid rebuilding on every call.
    Reuses same pattern as query_waterfall for consistency.
    """
    global _stage_lookup_cache
    if _stage_lookup_cache is not None:
        return _stage_lookup_cache

    config = _load_config()
    stage_lookup = {}

    for pipeline in config.get("pipeline", {}).get("pipelines", []):
        # Skip excluded pipelines (e.g., renewal)
        if pipeline.get("analyze") is False:
            continue

        for stage in pipeline.get("stages", []):
            stage_id = stage.get("id")
            if stage_id:
                stage_lookup[stage_id] = {
                    "id": stage_id,
                    "name": stage["name"],
                    "order": stage["order"],
                    "exclude_from_analysis": stage.get("exclude_from_analysis", False),
                    "is_won": stage.get("is_won", False),
                    "is_lost": stage.get("is_lost", False),
                }

    _stage_lookup_cache = stage_lookup
    return stage_lookup


def _get_stage_by_id(stage_id: str) -> Optional[dict]:
    """Get stage metadata by ID from config."""
    return _get_stage_lookup().get(stage_id)


def get_requirements_for_stage(stage_id: str) -> Dict[str, int]:
    """
    Returns the component score requirements a deal at this stage needs
    to meet to ADVANCE to the next stage.

    For example, a Discovery-stage deal returns {"pain": 5, "champion": 4}
    — the requirements to reach Scoping. Components not in this dict are
    not yet expected to be strong.

    Returns {} for terminal stages (Closed Won/Lost) or stages with
    exclude_from_analysis=true.

    Design: Maps stage.order from config to stage_progression entries.
    No hardcoded stage IDs — works for any client's stage configuration.
    """
    config = _load_config()
    stage_prog = config.get("stage_progression", {})

    # Get stage metadata by ID
    stage = _get_stage_by_id(stage_id)
    if not stage:
        return {}

    # Terminal or excluded stages have no requirements
    if stage.get("exclude_from_analysis") or stage.get("is_won") or stage.get("is_lost"):
        return {}

    # Map stage order to progression key
    # Order 1 = first qualified stage (discovery_to_scoping)
    # Order 2 = second stage (scoping_to_proposal), etc.
    order = stage.get("order")
    if order is None:
        return {}

    # stage_progression keys in config are in order
    # (discovery_to_scoping, scoping_to_proposal, proposal_to_negotiating, negotiating_to_closed_won)
    progression_keys = list(stage_prog.keys())

    # Map order to progression index (order 1 → index 0, order 2 → index 1, etc.)
    # But skip order 0 if it's excluded (Meeting Set)
    # Find the first non-excluded order to establish the baseline
    stage_lookup = _get_stage_lookup()
    non_excluded_orders = sorted([
        s["order"] for s in stage_lookup.values()
        if not s.get("exclude_from_analysis")
        and not s.get("is_won")
        and not s.get("is_lost")
    ])

    if order not in non_excluded_orders:
        return {}

    # Map this stage's order to progression index
    progression_index = non_excluded_orders.index(order)

    if progression_index >= len(progression_keys):
        # Order beyond defined progressions (e.g., extra stages)
        return {}

    progression_key = progression_keys[progression_index]

    # Load requirements for this progression
    reqs = stage_prog.get(progression_key, {})

    # Derive component mapping from configured methodology (not hardcoded list)
    # Works for MEDDICC (7), MEDDPICC (8), SPICED (5), BANT (4) without code changes
    component_mapping = {component_key(c): component_key(c) for c in get_components()}
    component_mapping["all_components_minimum"] = "__all__"  # Special marker

    requirements = {}
    for config_key, threshold in reqs.items():
        if config_key == "minimum_stakeholders":
            # Not a MEDDICC component score, skip
            continue

        component = component_mapping.get(config_key)
        if component is None:
            # Unmapped key — fail loudly, don't silently drop
            valid_keys = sorted([k for k in component_mapping.keys() if k != "__all__"])
            valid_keys.append("all_components_minimum")
            valid_keys.append("minimum_stakeholders")
            raise ValueError(
                f"Unknown component '{config_key}' in stage_progression.{progression_key}. "
                f"Valid component keys for {get_methodology()}: {', '.join(valid_keys)}. "
                f"Check config/client.yaml stage_progression section."
            )

        if component != "__all__":
            requirements[component] = threshold
        else:
            # All components must meet this threshold
            for label in get_components():
                comp_key = component_key(label)
                if comp_key not in requirements:  # Don't override specific higher requirements
                    requirements[comp_key] = threshold

    return requirements


def get_component_risk_level(stage_id: str, component: str, score: int) -> Optional[str]:
    """
    Returns "at_risk" if this component's score is below what's required
    to advance FROM the deal's current stage.

    Returns None if this component isn't part of the current stage's
    requirements (i.e. not yet due — NOT a risk signal, regardless of
    how low the score is).

    Args:
        stage_id: Deal's current HubSpot stage ID
        component: MEDDICC component name (e.g., "champion", "economic_buyer")
        score: Current score for this component (0-10)

    Returns:
        "at_risk" if below requirement, None if not required or score is sufficient
    """
    requirements = get_requirements_for_stage(stage_id)

    # Component not required at this stage
    if component not in requirements:
        return None

    required_threshold = requirements[component]

    # Score is below requirement
    if score < required_threshold:
        return "at_risk"

    # Score meets or exceeds requirement
    return None
