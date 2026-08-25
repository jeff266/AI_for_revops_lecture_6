"""Single source for loading coaching config. Merges seed (universal,
never edited per client) with client (the reference implementation's specifics, what a
new client fills in). Replaces six inline yaml.safe_load(context.yaml)
calls in api/handlers.py."""
import yaml
from pathlib import Path
from functools import lru_cache

SEED_PATH = Path(__file__).parent.parent / "config" / "coaching_seed.yaml"
CLIENT_PATH = Path(__file__).parent.parent / "config" / "coaching_client.yaml"

@lru_cache(maxsize=1)
def load_coaching_config() -> dict:
    """
    Merged coaching config: seed values as base, client values override/
    extend. Cached — call config-reload utilities if hot-reload is ever
    needed, but coaching config changing mid-process is not expected.
    """
    seed = yaml.safe_load(SEED_PATH.read_text()) or {}
    client = yaml.safe_load(CLIENT_PATH.read_text()) or {}
    merged = {**seed, **client}   # client keys override seed keys at top level
    return merged
