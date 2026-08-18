"""
Fiscal time window resolver for CRO Slack Agent.
Converts natural language time references to concrete start/end dates
using the fiscal calendar configuration.
"""

from datetime import date, timedelta
import sys
import yaml
from pathlib import Path

def _fiscal_config() -> dict:
    """Load fiscal configuration from client.yaml."""
    cfg_path = Path(__file__).parent.parent / "config" / "client.yaml"
    cfg = yaml.safe_load(open(cfg_path))
    return cfg.get("fiscal", {"fy_start_month": 2})

def current_quarter_label() -> str:
    """
    Returns current fiscal quarter label, e.g. 'Q3_FY2027'.
    Uses utils.get_fiscal_quarter from scripts/.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from utils import get_fiscal_quarter

    cfg = _fiscal_config()
    _, _, label = get_fiscal_quarter(
        date.today(), {"fiscal": cfg})
    return label.replace(" ", "_")

def resolve_time_window(tw: dict) -> dict:
    """
    Convert the classifier's time_window object to
    concrete start/end dates based on fiscal calendar.
    Falls back to current quarter if unclear.

    Input:
      {
        "period": "current_quarter|current_week|last_N_days|specific",
        "start": "YYYY-MM-DD or null",
        "end":   "YYYY-MM-DD or null",
        "n":     <int or null>  # for last_N_days
      }

    Output:
      {
        "start": "YYYY-MM-DD",
        "end":   "YYYY-MM-DD",
        "label": "Q3 FY2027" or "this week" or "last 30 days"
      }
    """
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from utils import get_fiscal_quarter

    today = date.today()
    period = tw.get("period", "current_quarter")
    cfg_wrap = {"fiscal": _fiscal_config()}

    if period == "current_quarter":
        s, e, label = get_fiscal_quarter(today, cfg_wrap)
        return {"start": s.isoformat(), "end": e.isoformat(),
                "label": label}
    elif period == "current_week":
        monday = today - timedelta(days=today.weekday())
        return {"start": monday.isoformat(),
                "end": today.isoformat(), "label": "this week"}
    elif period == "last_N_days":
        n = tw.get("n", 30)
        return {"start": (today - timedelta(days=n)).isoformat(),
                "end": today.isoformat(),
                "label": f"last {n} days"}
    elif period == "specific" and tw.get("start"):
        return {"start": tw["start"],
                "end": tw.get("end", today.isoformat()),
                "label": "custom range"}
    else:
        # Fallback to current quarter
        s, e, label = get_fiscal_quarter(today, cfg_wrap)
        return {"start": s.isoformat(), "end": e.isoformat(),
                "label": label}
