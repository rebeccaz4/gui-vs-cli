"""Security module tests.

Tests URL validation. No Safari or npx required.
"""

import importlib

from cli_anything.safari.utils import security


def _reload_security_module():
    """Reload the security module to pick up env var changes."""
    importlib.reload(security)


_reload_security_module()

from cli_anything.safari.utils.security import (
    get_allowed_schemes,
    get_blocked_schemes,
    is_private_network_blocked,
    validate_url,
)


class TestURLValidation:
    """URL validation security checks."""

    # ── Allowed schemes ──────────────────────────────────────────
    def test_valid_http_url(self):
        ok, err = validate_url("http://example.com")
        assert ok
        assert err == ""

    def test_valid_https_url(self):
        ok, err = validate_url("https://example.com")
        assert ok
        assert err == ""

    def test_valid_https_with_path_and_query(self):
        ok, err = validate_url("https://example.com/path/page?q=value&b=1")
        assert ok
        assert err == ""

    def test_valid_https_with_port(self):
        ok, err = validate_url("https://example.com:8443/")
        assert ok
        assert err == ""

    # ── Blocked schemes ──────────────────────────────────────────
    def test_blocked_file_scheme(self):
        ok, err = validate_url("file:///etc/passwd")
        assert not ok
        assert "Blocked URL scheme: file" in err

    def test_blocked_javascript_scheme(self):
        ok, err = validate_url("javascript:alert(1)")
        assert not ok
        assert "Blocked URL scheme: javascript" in err

    def test_blocked_data_scheme(self):
        ok, err = validate_url("data:text/html,<script>alert(1)</script>")
        assert not ok
        assert "Blocked URL scheme: data" in err

    def test_blocked_about_scheme(self):
        ok, err = validate_url("about:blank")
        assert not ok
        assert "Blocked URL scheme: about" in err

    def test_blocked_vbscript_scheme(self):
        ok, err = validate_url("vbscript:msgbox(1)")
        assert not ok
        assert "Blocked URL scheme: vbscript" in err

    def test_blocked_webkit_scheme(self):
        ok, err = validate_url("webkit:inspector")
        assert not ok
        assert "Blocked URL scheme: webkit" in err

    def test_blocked_safari_scheme(self):
        ok, err = validate_url("safari:history")
        assert not ok
        assert "Blocked URL scheme: safari" in err

    # ── Malformed inputs ─────────────────────────────────────────
    def test_empty_string(self):
        ok, err = validate_url("")
        assert not ok
        assert "non-empty" in err.lower()

    def test_whitespace_only(self):
        ok, err = validate_url("   ")
        assert not ok
        assert "empty" in err.lower() or "whitespace" in err.lower()

    def test_none_input(self):
        ok, err = validate_url(None)  # type: ignore
        assert not ok

    def test_non_string_input(self):
        ok, err = validate_url(12345)  # type: ignore
        assert not ok

    def test_missing_scheme(self):
        ok, err = validate_url("example.com/path")
        assert not ok
        assert "scheme" in err.lower()

    def test_missing_hostname(self):
        ok, err = validate_url("https://")
        assert not ok
        assert "hostname" in err.lower()

    def test_unknown_scheme(self):
        ok, err = validate_url("ftp://example.com")
        assert not ok
        assert "Unsupported URL scheme: ftp" in err

    def test_unknown_scheme_ws(self):
        ok, err = validate_url("ws://example.com")
        assert not ok

    # ── Scheme helpers ───────────────────────────────────────────
    def test_get_allowed_schemes(self):
        allowed = get_allowed_schemes()
        assert "http" in allowed
        assert "https" in allowed
        assert "file" not in allowed

    def test_get_blocked_schemes(self):
        blocked = get_blocked_schemes()
        assert "file" in blocked
        assert "javascript" in blocked
        assert "data" in blocked
        assert "safari" in blocked
        assert "webkit" in blocked
        assert "http" not in blocked



class TestPrivateNetworkConfig:
    """Test the env-var controlled private network blocking."""

    def test_default_private_not_blocked(self):
        """By default, private networks are NOT blocked (dev-friendly)."""
        assert is_private_network_blocked() is False

    def test_localhost_allowed_by_default(self):
        ok, _ = validate_url("http://localhost:3000")
        assert ok

    def test_127_0_0_1_allowed_by_default(self):
        ok, _ = validate_url("http://127.0.0.1:8080/api")
        assert ok

    def test_private_ip_allowed_by_default(self):
        ok, _ = validate_url("http://192.168.1.1/")
        assert ok
