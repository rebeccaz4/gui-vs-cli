"""E2E tests for cli-anything-safari — Requires Safari + macOS.

These tests interact with real Safari via the safari-mcp MCP server. They are
SKIPPED by default because:
1. Safari MCP kills stale instances (>10s) which can disrupt other agents
   using Safari MCP concurrently
2. E2E tests mutate browser state (open tabs, navigate, read cookies)
3. They require macOS + Safari with Apple Events enabled

To enable:
    export SAFARI_E2E=1
    python -m pytest cli_anything/safari/tests/test_full_e2e.py -v -s

To also enforce the installed command (not module fallback):
    CLI_ANYTHING_FORCE_INSTALLED=1 SAFARI_E2E=1 \\
        python -m pytest cli_anything/safari/tests/test_full_e2e.py -v -s
"""

import json
import os
import shutil
import subprocess
import sys

import pytest
from click.testing import CliRunner

from cli_anything.safari.utils.safari_backend import is_available
from cli_anything.safari.safari_cli import cli


# ── Feature flag and skip rule ───────────────────────────────────────
SAFARI_E2E_ENABLED = os.environ.get("SAFARI_E2E", "").lower() in {"1", "true", "yes"}


def _should_skip_e2e() -> bool:
    """Decide whether to skip the E2E file.

    Evaluated lazily so that pytest --collect-only does not call
    ``is_available()`` (which would hit the npm registry with up to a
    15-second timeout) when the feature flag is off. Only when
    SAFARI_E2E=1 do we actually probe for safari-mcp availability.
    """
    if not SAFARI_E2E_ENABLED:
        return True
    return not is_available()[0]


# Skip all tests when E2E is disabled or safari-mcp is unreachable.
pytestmark = pytest.mark.skipif(
    _should_skip_e2e(),
    reason=(
        "Safari E2E tests are disabled or safari-mcp is not available. "
        "Set SAFARI_E2E=1 and ensure Safari is installed with 'Allow "
        "JavaScript from Apple Events' enabled (Safari → Develop menu)."
    ),
)

# A stable read-only target for navigation tests.
TEST_URL = "https://example.com"


# ── CLI resolver (mandatory per HARNESS.md) ──────────────────────────
def _resolve_cli(name: str):
    """Resolve installed CLI command; falls back to python -m for dev.

    Set env CLI_ANYTHING_FORCE_INSTALLED=1 to require the installed command.
    This matches the pattern from HARNESS.md Phase 5.
    """
    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        print(f"[_resolve_cli] Using installed command: {path}")
        return [path]
    if force:
        raise RuntimeError(
            f"{name} not found in PATH. Install with: pip install -e ."
        )
    # Fallback: run as module
    module = "cli_anything.safari.safari_cli"
    print(f"[_resolve_cli] Falling back to: {sys.executable} -m {module}")
    return [sys.executable, "-m", module]


@pytest.fixture
def runner():
    return CliRunner()


# ── CliRunner-based tests (fast in-process) ──────────────────────────
class TestDependencyChecks:
    """Verify dependency checking works with Safari MCP available."""

    def test_cli_help_works(self, runner):
        """--help must succeed even when Safari MCP is reachable."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Safari CLI" in result.output

    def test_cli_shows_all_command_groups(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        for group in ("tool", "tools", "raw", "session", "repl"):
            assert group in result.output


class TestSessionCommands:
    """Test session management via CliRunner."""

    def test_session_status_json(self, runner):
        result = runner.invoke(cli, ["--json", "session", "status"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "last_url" in data
        assert "current_tab_index" in data


class TestSecurityIntegration:
    """URL validation must block dangerous schemes at the CLI layer."""

    def test_file_url_blocked(self, runner):
        result = runner.invoke(cli, ["tool", "navigate", "--url", "file:///etc/passwd"])
        assert result.exit_code != 0
        assert "Blocked URL scheme" in result.output or "file" in result.output

    def test_javascript_url_blocked(self, runner):
        result = runner.invoke(cli, ["tool", "navigate", "--url", "javascript:alert(1)"])
        assert result.exit_code != 0
        assert "Blocked" in result.output or "javascript" in result.output

    def test_about_url_blocked(self, runner):
        result = runner.invoke(cli, ["tool", "navigate", "--url", "about:blank"])
        assert result.exit_code != 0

    def test_missing_scheme_rejected(self, runner):
        result = runner.invoke(cli, ["tool", "navigate", "--url", "example.com"])
        assert result.exit_code != 0

    def test_raw_navigate_also_blocked(self, runner):
        """The raw escape hatch must also enforce URL validation."""
        result = runner.invoke(
            cli,
            ["raw", "safari_navigate", "--json-args", '{"url":"file:///etc/passwd"}']
        )
        assert result.exit_code != 0


# ── Real MCP round-trip (mutates Safari state) ───────────────────────
class TestRealSafariRoundTrip:
    """These tests actually talk to Safari. Only run when SAFARI_E2E=1."""

    def test_tab_list_returns_json(self, runner):
        """list-tabs should round-trip through safari-mcp and return valid JSON."""
        result = runner.invoke(cli, ["--json", "tool", "list-tabs"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data is not None

    def test_navigate_and_read_example_com(self, runner):
        """End-to-end navigation: open example.com and read title."""
        result = runner.invoke(
            cli, ["--json", "tool", "navigate-and-read", "--url", TEST_URL]
        )
        assert result.exit_code == 0
        assert "Example" in result.output or "example" in result.output


# ── Subprocess tests (HARNESS.md requirement) ────────────────────────
class TestCLISubprocess:
    """Invoke the installed CLI command as a real user/agent would.

    This class is required by HARNESS.md Phase 5: tests must exercise the
    actual installed `cli-anything-safari` command via subprocess, not just
    source imports via CliRunner. ``CLI_BASE`` is a cached class property
    rather than a class attribute so pytest collection does not call
    ``_resolve_cli`` (which can raise when ``CLI_ANYTHING_FORCE_INSTALLED=1``
    is set but the command is not in PATH).
    """

    _cli_base: "list[str] | None" = None

    @property
    def CLI_BASE(self) -> list[str]:
        base = type(self)._cli_base
        if base is None:
            base = _resolve_cli("cli-anything-safari")
            type(self)._cli_base = base
        return base

    def _run(self, args, check=True):
        return subprocess.run(
            self.CLI_BASE + args,
            capture_output=True,
            text=True,
            check=check,
        )

    def test_help(self):
        result = self._run(["--help"])
        assert result.returncode == 0
        assert "Safari CLI" in result.stdout

    def test_tool_group_help(self):
        result = self._run(["tool", "--help"])
        assert result.returncode == 0
        # Spot-check short names from each category — these are the MCP
        # tool names with the safari_ prefix stripped, so they're stable.
        for short in (
            "navigate", "snapshot", "click", "fill",
            "screenshot", "evaluate", "list-tabs", "mock-route",
        ):
            assert short in result.stdout, f"missing '{short}' in tool --help"

    def test_tools_count_is_84(self):
        result = self._run(["tools", "count"])
        assert result.returncode == 0
        assert result.stdout.strip() == "84"

    def test_tools_describe_scroll(self):
        result = self._run(["tools", "describe", "safari_scroll"])
        assert result.returncode == 0
        assert "direction" in result.stdout
        assert "amount" in result.stdout

    def test_tool_scroll_help_uses_schema(self):
        """Verify the auto-generated command matches the MCP schema exactly."""
        result = self._run(["tool", "scroll", "--help"])
        assert result.returncode == 0
        assert "--direction" in result.stdout
        assert "--amount" in result.stdout
        assert "up|down" in result.stdout  # enum choices

    def test_raw_help(self):
        result = self._run(["raw", "--help"])
        assert result.returncode == 0
        assert "tool_name" in result.stdout.lower()

    def test_session_status_json(self):
        result = self._run(["--json", "session", "status"])
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "last_url" in data
        assert "current_tab_index" in data

    def test_blocked_scheme_exits_nonzero(self):
        # Note: check=False because we expect non-zero exit
        result = self._run(
            ["tool", "navigate", "--url", "file:///etc/passwd"], check=False
        )
        assert result.returncode != 0

    def test_list_tabs_json_roundtrip(self):
        """End-to-end: installed CLI → safari-mcp → Safari → back."""
        result = self._run(["--json", "tool", "list-tabs"])
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data is not None
        print(f"\n  list-tabs: {len(data) if isinstance(data, list) else 'n/a'} tabs")
