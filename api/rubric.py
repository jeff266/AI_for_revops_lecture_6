"""
MEDDICC scoring rubric with bands and next steps.
Used for general coaching when deal-specific analysis unavailable.
"""

RUBRIC = {  # drift-guard: ok (scoring rubric data structure, not component enumeration)
    "metrics": {
        "bands": {
            "red": (0, 3, "No quantified business case"),
            "yellow": (4, 6, "Partial metrics identified"),
            "green": (7, 10, "Strong quantified value"),
        },
        "next_steps": {
            "red": "Ask: 'What specific metrics would you use to measure success?' Get quantified ROI.",
            "yellow": "Confirm: 'You mentioned [metric] — can you share the baseline and target?' Validate business case.",
            "green": "Verify: 'How will you track [metric] post-implementation?' Ensure alignment on success criteria.",
        }
    },
    "economic_buyer": {
        "bands": {
            "red": (0, 3, "Budget holder not identified"),
            "yellow": (4, 6, "Suspected but not confirmed"),
            "green": (7, 10, "Confirmed with access"),
        },
        "next_steps": {
            "red": "Ask: 'Who has final budget approval for [dollar amount] purchases?' Get introduced.",
            "yellow": "Confirm: 'Is [name] the final approver or does it need to go higher?' Validate authority.",
            "green": "Engage: 'What does [EB name] need to see to approve this?' Align on their success criteria.",
        }
    },
    "decision_criteria": {
        "bands": {
            "red": (0, 3, "Criteria unknown"),
            "yellow": (4, 6, "Some criteria surfaced"),
            "green": (7, 10, "Complete criteria documented"),
        },
        "next_steps": {
            "red": "Ask: 'What are the top 3 things you're evaluating solutions on?' Document criteria.",
            "yellow": "Confirm: 'Are there any other must-haves beyond [criteria]?' Complete the list.",
            "green": "Validate: 'How do we score on your criteria?' Ensure alignment and identify gaps.",
        }
    },
    "decision_process": {
        "bands": {
            "red": (0, 3, "Process undefined"),
            "yellow": (4, 6, "Partial timeline known"),
            "green": (7, 10, "Full process mapped"),
        },
        "next_steps": {
            "red": "Ask: 'What does your typical buying process look like for tools like this?' Map stakeholders.",
            "yellow": "Confirm: 'After [step], what happens next and who's involved?' Complete the map.",
            "green": "Align: 'What could slow down your [date] timeline?' Identify and mitigate risks.",
        }
    },
    "identify_pain": {
        "bands": {
            "red": (0, 3, "No business pain articulated"),
            "yellow": (4, 6, "Pain acknowledged but not urgent"),
            "green": (7, 10, "Critical pain with urgency"),
        },
        "next_steps": {
            "red": "Ask: 'What happens if you don't solve this problem?' Quantify impact.",
            "yellow": "Confirm: 'Why is this a priority now vs. 6 months from now?' Establish urgency.",
            "green": "Validate: 'What's the cost of delay on [pain]?' Reinforce urgency and timeline.",
        }
    },
    "champion": {
        "bands": {
            "red": (0, 3, "No internal advocate"),
            "yellow": (4, 6, "Engaged but not selling"),
            "green": (7, 10, "Actively selling internally"),
        },
        "next_steps": {
            "red": "Ask: 'Who internally would benefit most from this?' Identify potential champion.",
            "yellow": "Confirm: 'Would you be comfortable presenting this to [stakeholder]?' Test willingness.",
            "green": "Enable: 'What do you need from us to sell this internally?' Provide champion enablement.",
        }
    },
    "competition": {
        "bands": {
            "red": (0, 3, "Competitive landscape unknown"),
            "yellow": (4, 6, "Competitors identified"),
            "green": (7, 10, "Our position vs. competitors clear"),
        },
        "next_steps": {
            "red": "Ask: 'Are you evaluating any other solutions?' Surface competitors.",
            "yellow": "Confirm: 'How are you thinking about us vs. [competitor]?' Understand positioning.",
            "green": "Reinforce: 'Based on [criteria], here's why we're best fit.' Maintain differentiation.",
        }
    },
}


def get_band(component: str, score: int) -> str:
    """
    Return the band name (red/yellow/green) for a component score.

    Args:
        component: MEDDICC component name (metrics, economic_buyer, etc.)
        score: Numeric score 0-10

    Returns:
        Band name string ("red", "yellow", or "green")
    """
    component_key = component.lower().replace(" ", "_")
    if component_key not in RUBRIC:
        return "unknown"

    bands = RUBRIC[component_key]["bands"]
    for band_name, (min_score, max_score, _) in bands.items():
        if min_score <= score <= max_score:
            return band_name

    return "unknown"


def get_next_steps(component: str, score: int) -> str:
    """
    Return coaching next steps for a component score.

    Args:
        component: MEDDICC component name
        score: Numeric score 0-10

    Returns:
        Next steps guidance string
    """
    component_key = component.lower().replace(" ", "_")
    if component_key not in RUBRIC:
        return "No guidance available for this component."

    band = get_band(component, score)
    if band == "unknown":
        return "Score out of range."

    return RUBRIC[component_key]["next_steps"].get(
        band, "No next steps defined for this band."
    )


def get_band_description(component: str, score: int) -> str:
    """
    Return the band description for a component score.

    Args:
        component: MEDDICC component name
        score: Numeric score 0-10

    Returns:
        Band description string
    """
    component_key = component.lower().replace(" ", "_")
    if component_key not in RUBRIC:
        return "Unknown component"

    bands = RUBRIC[component_key]["bands"]
    for band_name, (min_score, max_score, description) in bands.items():
        if min_score <= score <= max_score:
            return description

    return "Score out of range"
