"""Obsidian active note operations — get and open."""

from cli_anything.obsidian.utils.obsidian_backend import api_get, api_put


def get_active(base_url: str, api_key: str) -> dict:
    """Get the currently active (open) note in Obsidian."""
    return api_get(base_url, "/active/", api_key)


def open_note(base_url: str, api_key: str, path: str) -> dict:
    """Open a note in Obsidian."""
    return api_put(base_url, "/active/", api_key, content=path,
                   content_type="text/plain")
