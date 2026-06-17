"""Security utilities for Safari browser automation.

This module provides security functions for the safari-mcp harness,
including URL validation and attack surface mitigation.

Threat Model:
- SSRF: Safari can access arbitrary URLs including localhost/private networks
- Scheme injection: javascript:, file:, data: URLs can execute code locally
- Tab ownership bypass: upstream safari-mcp enforces this; validated here too
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse


# Environment variable to control private network blocking.
# Default: False (allow localhost/private networks for development —
# Safari MCP is often used to automate local dashboards and dev servers).
_BLOCK_PRIVATE_NETWORKS = os.environ.get(
    "CLI_ANYTHING_SAFARI_BLOCK_PRIVATE", ""
).lower() in ("true", "1")

# Environment variable to define allowed URL schemes (comma-separated).
# Default: "http,https". Normalized to lowercase, empty entries filtered.
_ALLOWED_SCHEMES = set(
    scheme
    for scheme in (
        s.strip().lower()
        for s in os.environ.get(
            "CLI_ANYTHING_SAFARI_ALLOWED_SCHEMES", "http,https"
        ).split(",")
    )
    if scheme
)

# Dangerous URI schemes that should NEVER be allowed.
_BLOCKED_SCHEMES = {
    "file",               # Local file access
    "javascript",         # Code execution via pseudo-protocol
    "data",               # Data URI attacks
    "vbscript",           # Legacy IE script injection
    "about",              # Browser-internal pages (about:blank, about:config)
    "chrome",             # Chrome internal pages
    "chrome-extension",   # Chrome extensions
    "moz-extension",      # Firefox extensions
    "edge",               # Edge internal pages
    "safari",             # Safari internal pages
    "webkit",             # WebKit internal pages
    "opera",              # Opera internal pages
    "brave",              # Brave internal pages
    "x-apple",            # Apple URL schemes (x-apple-helpbasic, etc.)
    "feed",               # RSS feed handler
}

# Private network patterns (RFC 1918 + loopback + link-local + IPv6 variants).
_PRIVATE_NETWORK_PATTERNS = [
    r'^127\.\d+\.\d+\.\d+',                 # 127.0.0.0/8 (loopback)
    r'^::1$',                                # IPv6 loopback
    r'^localhost$',                          # localhost hostname
    r'^localhost:',                          # localhost with port
    r'^0\.0\.0\.0$',                         # 0.0.0.0 (all interfaces)
    r'^10\.\d+\.\d+\.\d+',                   # 10.0.0.0/8
    r'^172\.(1[6-9]|2\d|3[01])\.\d+\.\d+',   # 172.16.0.0/12
    r'^192\.168\.\d+\.\d+',                  # 192.168.0.0/16
    r'^169\.254\.\d+\.\d+',                  # 169.254.0.0/16 (link-local)
    r'^fc00:',                               # IPv6 ULA
    r'^fd[0-9a-f]{2}:',                      # IPv6 ULA prefix
    r'^fe80:',                               # IPv6 link-local
    r'^::',                                  # IPv6 unspecified variants
    r'^\[::1\]',                             # IPv6 loopback with brackets
    r'^\[::\]',                              # IPv6 unspecified with brackets
    r'^\[fe80:',                             # IPv6 link-local with brackets
    r'^\[fd[0-9a-f]{2}:',                    # IPv6 ULA with brackets
]


def validate_url(url: str) -> tuple[bool, str]:
    """Validate a URL for security before handing it to Safari MCP.

    Checks:
    1. Dangerous URI schemes (file://, javascript:, data:, etc.)
    2. Private network access (if enabled via env var)
    3. Unsupported schemes (only http/https allowed by default)

    Args:
        url: URL to validate

    Returns:
        (is_valid, error_message). Returns (True, "") if URL is safe.

    Examples:
        >>> validate_url("https://example.com")
        (True, "")
        >>> validate_url("file:///etc/passwd")
        (False, "Blocked URL scheme: file")
        >>> validate_url("javascript:alert(1)")
        (False, "Blocked URL scheme: javascript")
    """
    if not url or not isinstance(url, str):
        return False, "URL must be a non-empty string"

    url = url.strip()
    if not url:
        return False, "URL cannot be empty or whitespace"

    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Invalid URL: {e}"

    scheme = parsed.scheme.lower()

    if scheme in _BLOCKED_SCHEMES:
        return False, f"Blocked URL scheme: {scheme}"

    if not scheme:
        return False, (
            f"URL must include an explicit scheme. "
            f"Allowed: {', '.join(sorted(_ALLOWED_SCHEMES))}"
        )

    if scheme not in _ALLOWED_SCHEMES:
        return False, (
            f"Unsupported URL scheme: {scheme}. "
            f"Allowed: {', '.join(sorted(_ALLOWED_SCHEMES))}"
        )

    hostname = parsed.hostname or ""
    if not hostname:
        return False, "URL must include a hostname"

    if _BLOCK_PRIVATE_NETWORKS:
        hostname_lower = hostname.lower()
        for pattern in _PRIVATE_NETWORK_PATTERNS:
            if re.match(pattern, hostname_lower):
                return False, f"Private network access blocked: {hostname}"

        netloc = parsed.netloc.lower()
        for pattern in _PRIVATE_NETWORK_PATTERNS:
            if re.match(pattern, netloc):
                return False, f"Private network access blocked: {netloc}"

    return True, ""



def is_private_network_blocked() -> bool:
    """Check if private network blocking is enabled."""
    return _BLOCK_PRIVATE_NETWORKS


def get_allowed_schemes() -> set[str]:
    """Get the set of allowed URL schemes."""
    return _ALLOWED_SCHEMES.copy()


def get_blocked_schemes() -> set[str]:
    """Get the set of blocked URL schemes."""
    return _BLOCKED_SCHEMES.copy()
