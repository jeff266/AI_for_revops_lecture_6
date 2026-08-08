"""
Adapter factories. Read config/client.yaml and return the
right implementation. All repos (nightly agent, CRO agent)
import from here — never from tool modules directly.
"""
import yaml
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent


def _load_config() -> dict:
    p = _REPO_ROOT / 'config' / 'client.yaml'
    if not p.exists():
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


def get_call_adapter(tool: str = None):
    """Return the primary call adapter (or a named one)."""
    config = _load_config()
    tool = (tool or config.get('call_tools', {})
                        .get('primary', 'fireflies')).lower()
    if tool == 'fireflies':
        from .calls.fireflies import FirefliesClient
        return FirefliesClient()
    if tool == 'gong':
        from .calls.gong import GongAdapter
        return GongAdapter()
    if tool == 'apollo':
        from .calls.apollo import ApolloClient
        return ApolloClient()
    raise ValueError(
        f"Unknown call tool '{tool}'. Add an adapter at "
        f"scripts/adapters/calls/{tool}.py implementing "
        f"CallAdapter (see calls/base.py), then register it here.")
