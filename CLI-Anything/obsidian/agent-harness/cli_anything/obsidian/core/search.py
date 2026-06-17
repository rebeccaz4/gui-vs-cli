"""Obsidian search operations — query and simple text search."""

from cli_anything.obsidian.utils.obsidian_backend import api_post


def search_query(base_url: str, api_key: str, query: str) -> dict:
    """Search vault using Obsidian's search engine.

    Args:
        base_url: API base URL.
        api_key: Bearer token.
        query: Search query string (Obsidian search syntax).

    Returns:
        Search results from Obsidian.
    """
    return api_post(base_url, "/search/", api_key, data={"query": query})


def search_simple(base_url: str, api_key: str, query: str,
                  context_length: int = 100) -> dict:
    """Simple text search across the vault.

    Args:
        base_url: API base URL.
        api_key: Bearer token.
        query: Plain text to search for.
        context_length: Number of context characters around matches.

    Returns:
        List of search results with filename and matches.
    """
    return api_post(base_url, "/search/simple/", api_key,
                    params={"query": query, "contextLength": context_length})
