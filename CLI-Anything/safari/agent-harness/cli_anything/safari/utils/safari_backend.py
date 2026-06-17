"""Safari MCP client wrapper — communicates with safari-mcp server via stdio.

Provides a synchronous Python interface to safari-mcp's MCP server.
Every call spawns a fresh ``npx safari-mcp`` subprocess, performs one
tool call, and exits. This keeps the wrapper simple and avoids async
event-loop lifecycle issues.

Requires Node.js 18+ (for npx) and macOS.
"""

import asyncio
import os
import subprocess
import shutil
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DEFAULT_SERVER_CMD = "npx"
DEFAULT_SERVER_ARGS = ["-y", "safari-mcp"]


def _check_npx() -> bool:
    return shutil.which("npx") is not None


def _check_platform() -> bool:
    import platform
    return platform.system() == "Darwin"


def _check_safari_mcp_package() -> tuple[bool, str]:
    """Check whether the safari-mcp package is resolvable.

    Safari MCP is a pure MCP stdio server — it does not respond to
    ``--version`` or ``--help``. We instead query the npm registry via
    ``npm view`` which is fast and does not spawn the server.

    Returns:
        (found, version_or_error)
    """
    try:
        result = subprocess.run(
            ["npm", "view", "safari-mcp", "version"],
            capture_output=True,
            timeout=15,
            text=True,
        )
        if result.returncode != 0:
            return False, result.stderr.strip() or "npm view failed"
        version = result.stdout.strip()
        return bool(version), version or "(no version)"
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, str(e)


def is_available() -> tuple[bool, str]:
    """Check if the safari-mcp MCP server is reachable.

    Returns:
        (available, message): tuple of availability and a descriptive message.
    """
    if not _check_platform():
        return (
            False,
            "Safari MCP only supports macOS. "
            "Detected non-Darwin platform.",
        )

    if not _check_npx():
        return (
            False,
            "npx not found. Install Node.js 18+ from https://nodejs.org/",
        )

    found, version_or_err = _check_safari_mcp_package()
    if not found:
        return (
            False,
            f"safari-mcp package not found on npm registry: {version_or_err}\n"
            f"Check your network connection and npm access.",
        )

    return True, f"safari-mcp v{version_or_err} is available"


async def _call_tool(tool_name: str, arguments: dict) -> Any:
    """Spawn safari-mcp, call one tool, and return the result."""
    server_params = StdioServerParameters(
        command=DEFAULT_SERVER_CMD,
        args=DEFAULT_SERVER_ARGS,
        env=os.environ.copy(),
    )
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(tool_name, arguments)
    except Exception as e:
        raise RuntimeError(
            f"safari-mcp tool call failed: {e}\n"
            f"Ensure Safari is running and 'Allow JavaScript from Apple Events' "
            f"is enabled (Safari → Develop menu). "
            f"See https://github.com/achiya-automation/safari-mcp"
        ) from e


# ── Generic sync entry point ────────────────────────────────────────
def call(tool_name: str, **arguments) -> Any:
    """Call any safari-mcp tool synchronously.

    This is the primary entry point for the CLI. All 84 Safari MCP tools
    are reachable via this single function; the Click layer generates
    ergonomic commands but ultimately funnels here.

    Note:
        Uses ``asyncio.run()`` internally. This will raise
        ``RuntimeError`` if called from an already-running event loop
        (e.g. inside Jupyter or an async framework). Callers in async
        contexts should use ``_call_tool()`` directly with ``await``.

    Args:
        tool_name: Full MCP tool name, e.g. "safari_navigate"
        **arguments: Tool arguments (forwarded to the MCP server)

    Returns:
        Parsed tool result. Safari MCP returns text content — if the text
        parses as JSON we return the decoded dict/list, otherwise the raw
        string.

    Example:
        >>> call("safari_navigate", url="https://example.com")
        {"ok": True, "url": "https://example.com"}
    """
    # Drop None values so optional args don't confuse the schema
    clean_args = {k: v for k, v in arguments.items() if v is not None}
    result = asyncio.run(_call_tool(tool_name, clean_args))
    return _unwrap(result)


def _unwrap(result: Any) -> Any:
    """Extract the payload from an MCP ``CallToolResult``.

    Safari MCP wraps tool output in ``{content: [...]}`` where each item
    is either:

    - **TextContent**: ``{type: 'text', text: '...'}`` — returned by most
      tools. The text is JSON-decoded when possible, otherwise returned
      as a raw string.
    - **ImageContent**: ``{type: 'image', data: '<base64>', mimeType: 'image/...'}``
      — returned by ``safari_screenshot`` and ``safari_screenshot_element``.
      We return ``{type: 'image', data: <base64>, mimeType: <str>}`` so
      callers can decode the base64 (e.g. ``base64.b64decode(d['data'])``)
      and write it to a file.

    Multiple content items are returned as a list. A single item is
    unwrapped.
    """
    import json

    try:
        content = result.content
    except AttributeError:
        return result

    if not content:
        return None

    parts = []
    for item in content:
        # TextContent — has .text
        text = getattr(item, "text", None)
        if text is not None:
            try:
                parts.append(json.loads(text))
            except (json.JSONDecodeError, ValueError):
                parts.append(text)
            continue

        # ImageContent — has .data and .mimeType
        data = getattr(item, "data", None)
        if data is not None:
            mime_type = getattr(item, "mimeType", None) or "application/octet-stream"
            parts.append({
                "type": "image",
                "data": data,
                "mimeType": mime_type,
            })
            continue

        # Unknown content type — preserve the raw object so the caller
        # at least sees something rather than silently dropping it.
        parts.append(item)

    if len(parts) == 1:
        return parts[0]
    return parts
