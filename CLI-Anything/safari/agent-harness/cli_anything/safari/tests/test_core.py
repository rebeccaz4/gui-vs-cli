"""Unit tests for cli-anything-safari — Core modules with mocked backend.

These tests use synthetic data and mock the MCP backend. No Safari, npx,
or network access required. Covers:
    - Platform gating (Darwin-only)
    - MCP result unwrapping (JSON parsing)
    - Argument cleaning (strip None values)
    - Session state management

Usage:
    python -m pytest cli_anything/safari/tests/test_core.py -v
"""

import platform
from unittest.mock import patch, MagicMock


class TestPlatformCheck:
    def test_refuses_non_darwin(self):
        from cli_anything.safari.utils import safari_backend as backend

        with patch.object(platform, "system", return_value="Linux"):
            available, msg = backend.is_available()
            assert available is False
            assert "macOS" in msg

    def test_accepts_darwin_if_deps_present(self):
        from cli_anything.safari.utils import safari_backend as backend

        with patch.object(platform, "system", return_value="Darwin"), \
             patch.object(backend, "_check_npx", return_value=True), \
             patch.object(backend, "_check_safari_mcp_package",
                          return_value=(True, "2.7.8")):
            available, msg = backend.is_available()
            assert available is True
            assert "2.7.8" in msg


class TestUnwrap:
    def test_unwrap_json_text(self):
        from cli_anything.safari.utils.safari_backend import _unwrap

        result = MagicMock()
        item = MagicMock()
        item.text = '{"ok": true, "url": "https://example.com"}'
        result.content = [item]

        parsed = _unwrap(result)
        assert parsed == {"ok": True, "url": "https://example.com"}

    def test_unwrap_plain_text(self):
        from cli_anything.safari.utils.safari_backend import _unwrap

        result = MagicMock()
        item = MagicMock()
        item.text = "not json, just a string"
        result.content = [item]

        assert _unwrap(result) == "not json, just a string"

    def test_unwrap_multiple_parts(self):
        from cli_anything.safari.utils.safari_backend import _unwrap

        result = MagicMock()
        a, b = MagicMock(), MagicMock()
        a.text = '{"a": 1}'
        b.text = '{"b": 2}'
        result.content = [a, b]

        parts = _unwrap(result)
        assert parts == [{"a": 1}, {"b": 2}]

    def test_unwrap_empty(self):
        from cli_anything.safari.utils.safari_backend import _unwrap

        result = MagicMock()
        result.content = []
        assert _unwrap(result) is None

    def test_unwrap_image_content(self):
        """ImageContent items must NOT be silently dropped.

        Regression test for the bug where _unwrap only checked for
        ``.text`` and returned None for screenshot tools, which
        return ``{type:'image', data:<base64>, mimeType:...}``.
        """
        from cli_anything.safari.utils.safari_backend import _unwrap

        result = MagicMock()
        item = MagicMock(spec=["data", "mimeType"])
        item.data = "base64encodedimagedata=="
        item.mimeType = "image/jpeg"
        result.content = [item]

        unwrapped = _unwrap(result)
        assert unwrapped is not None
        assert unwrapped["type"] == "image"
        assert unwrapped["data"] == "base64encodedimagedata=="
        assert unwrapped["mimeType"] == "image/jpeg"

    def test_unwrap_image_content_default_mimetype(self):
        from cli_anything.safari.utils.safari_backend import _unwrap

        result = MagicMock()
        item = MagicMock(spec=["data"])
        item.data = "abc"
        # No mimeType attribute
        result.content = [item]

        unwrapped = _unwrap(result)
        assert unwrapped is not None
        assert unwrapped["type"] == "image"
        assert unwrapped["data"] == "abc"
        assert unwrapped["mimeType"] == "application/octet-stream"


class TestCallForwarding:
    """Verify backend.call() forwards args, strips None, and unwraps results."""

    def test_strips_none_args_before_call(self):
        from cli_anything.safari.utils import safari_backend as backend

        captured: dict = {}

        async def fake_call_tool(tool_name, arguments):
            captured["tool"] = tool_name
            captured["args"] = arguments
            result = MagicMock()
            item = MagicMock()
            item.text = '{"ok": true}'
            result.content = [item]
            return result

        with patch.object(backend, "_call_tool", side_effect=fake_call_tool):
            result = backend.call("safari_navigate", url="https://example.com",
                                  selector=None, x=None, y=42)

        assert captured["tool"] == "safari_navigate"
        # None values must be stripped; non-None must be forwarded.
        assert captured["args"] == {"url": "https://example.com", "y": 42}
        # The MCP CallToolResult must be unwrapped to the inner JSON.
        assert result == {"ok": True}

    def test_passes_full_arg_set_when_none_omitted(self):
        from cli_anything.safari.utils import safari_backend as backend

        captured: dict = {}

        async def fake_call_tool(tool_name, arguments):
            captured["args"] = arguments
            result = MagicMock()
            result.content = []
            return result

        with patch.object(backend, "_call_tool", side_effect=fake_call_tool):
            backend.call("safari_click", ref="0_5", selector="#submit")

        assert captured["args"] == {"ref": "0_5", "selector": "#submit"}

    def test_unwraps_plain_text_when_not_json(self):
        from cli_anything.safari.utils import safari_backend as backend

        captured: dict = {}

        async def fake_call_tool(tool_name, arguments):
            captured["tool"] = tool_name
            captured["args"] = arguments
            result = MagicMock()
            item = MagicMock()
            item.text = "not a json string"
            result.content = [item]
            return result

        with patch.object(backend, "_call_tool", side_effect=fake_call_tool):
            # Note: safari_evaluate's parameter is "script", not "code".
            # This test doubles as a regression lock for the doc bug
            # where examples used --code by mistake.
            result = backend.call("safari_evaluate", script="document.title")

        assert captured["tool"] == "safari_evaluate"
        assert captured["args"] == {"script": "document.title"}
        assert result == "not a json string"


class TestSessionState:
    def test_session_defaults(self):
        from cli_anything.safari.core.session import Session

        s = Session()
        assert s.current_tab_index is None
        assert s.last_url == ""

    def test_set_url_updates_last_url(self):
        from cli_anything.safari.core.session import Session

        s = Session()
        s.set_url("https://example.com")
        assert s.last_url == "https://example.com"

    def test_set_tab_updates_current_tab(self):
        from cli_anything.safari.core.session import Session

        s = Session()
        s.set_tab(3)
        assert s.current_tab_index == 3

    def test_status_contains_expected_keys(self):
        from cli_anything.safari.core.session import Session

        s = Session()
        s.set_url("https://example.com")
        s.set_tab(2)

        status = s.status()
        assert status["last_url"] == "https://example.com"
        assert status["current_tab_index"] == 2
        assert "daemon_mode" not in status  # removed in v1

    def test_status_empty_url_returns_sentinel(self):
        from cli_anything.safari.core.session import Session

        s = Session()
        # last_url not set yet — status() should return the sentinel
        # so REPL display has something readable.
        status = s.status()
        assert status["last_url"] == "(no navigation yet)"
        assert status["current_tab_index"] is None
