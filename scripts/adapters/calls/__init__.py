"""
Call adapter factory.

Reads call_tools.primary from config and returns the matching adapter
instance (fireflies, gong, apollo).

Raises on unknown/typo values with the same discipline as get_components()
and the Gap 2 raises — no silent fallbacks.
"""
from typing import Any, Dict


def get_call_adapter(config: Dict[str, Any]):
    """
    Factory: Instantiate the call adapter specified in config.

    Args:
        config: Client config dict from load_client_config()

    Returns:
        CallAdapter instance (FirefliesClient, GongAdapter, or ApolloClient)

    Raises:
        ValueError: If call_tools.primary is missing or unrecognized

    Usage:
        config = load_client_config()
        adapter = get_call_adapter(config)
        calls = adapter.search_by_company("Acme Corp")
    """
    call_tools = config.get('call_tools', {})
    primary = call_tools.get('primary')

    if not primary:
        raise ValueError(
            "call_tools.primary not set in config/client.yaml. "
            "Must be one of: fireflies, gong, apollo"
        )

    # Valid adapters
    VALID_ADAPTERS = ['fireflies', 'gong', 'apollo']

    if primary not in VALID_ADAPTERS:
        raise ValueError(
            f"call_tools.primary = '{primary}' is not recognized. "
            f"Valid options: {', '.join(VALID_ADAPTERS)}"
        )

    # Import and instantiate the adapter
    if primary == 'fireflies':
        from .fireflies import FirefliesClient
        return FirefliesClient()

    elif primary == 'gong':
        from .gong import GongAdapter
        return GongAdapter()

    elif primary == 'apollo':
        from .apollo import ApolloClient
        return ApolloClient()

    # Should never reach here due to validation above, but explicit
    raise ValueError(
        f"call_tools.primary = '{primary}' validated but not implemented. "
        "This is a bug — contact support."
    )
