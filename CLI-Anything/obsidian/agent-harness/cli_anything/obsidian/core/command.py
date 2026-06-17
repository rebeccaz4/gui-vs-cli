"""Obsidian command operations — list and execute."""

from cli_anything.obsidian.utils.obsidian_backend import api_get, api_post


def list_commands(base_url: str, api_key: str) -> dict:
    """List available Obsidian commands."""
    return api_get(base_url, "/commands/", api_key)


def execute_command(base_url: str, api_key: str, command_id: str) -> dict:
    """Execute an Obsidian command by ID."""
    endpoint = f"/commands/{command_id}/"
    return api_post(base_url, endpoint, api_key)
