"""Obsidian server info — status check."""

from cli_anything.obsidian.utils.obsidian_backend import api_get


def server_status(base_url: str, api_key: str) -> dict:
    """Check if Obsidian REST API is running and authenticated.

    Returns:
        Dict with server status info.
    """
    return api_get(base_url, "/", api_key)
