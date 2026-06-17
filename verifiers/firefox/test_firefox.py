"""
Test Firefox ESR verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (Firefox not running, bad args)
  - SQLite endpoints (history, bookmarks, cookies, prefs)
  - Marionette live endpoints (tabs, eval, navigate, selector)
  - Composite check-* endpoints — positive and negative cases
  - JSON validity for all commands

Usage:
    python verifiers/firefox/test_firefox.py
"""

import json
import sys
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "firefox.py"
VERIFIER_REMOTE = "/home/user/verifiers/firefox.py"
V = f"python3 {VERIFIER_REMOTE}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

passed = 0
failed = 0
errors: list[str] = []


class CmdResult:
    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def run(sandbox: Sandbox, cmd: str, timeout: int = 30) -> dict | list:
    r = run_raw(sandbox, cmd, timeout)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


def run_raw(sandbox: Sandbox, cmd: str, timeout: int = 30) -> CmdResult:
    try:
        result = sandbox.commands.run(f"{V} {cmd}", timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def run_shell(sandbox: Sandbox, cmd: str, timeout: int = 60) -> CmdResult:
    try:
        result = sandbox.commands.run(cmd, timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f"  -- {detail}"
        print(msg)
        errors.append(f"{name}: {detail}")


def is_valid_json(stdout: str) -> bool:
    try:
        json.loads(stdout)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    print("\n=== Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
    check("help mentions commands", "Commands:" in result.stdout, result.stdout[:100])


def test_errors_firefox_not_running(sandbox: Sandbox):
    """Test error handling when Firefox is not running."""
    print("\n=== Errors (Firefox not running) ===")
    for cmd, name in [("tabs", "tabs"), ("url", "url"), ("title", "title")]:
        data = run(sandbox, cmd)
        check(f"{name} returns error when FF down",
              "error" in (data if isinstance(data, dict) else data[0] if data else {}),
              str(data)[:100])


def test_errors_bad_args(sandbox: Sandbox):
    print("\n=== Errors (bad args) ===")
    result = run_raw(sandbox, "check-url-visited")
    check("missing arg exits 1", result.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])


def test_marionette_tabs(sandbox: Sandbox):
    """Test live tab inspection via Marionette."""
    print("\n=== Marionette Tabs ===")

    data = run(sandbox, "tabs")
    if isinstance(data, list):
        check("tabs returns list", len(data) > 0, str(data)[:100])
        if data and "error" not in data[0]:
            check("tab has url", "url" in data[0], str(data[0])[:100])
            check("tab has title", "title" in data[0], str(data[0])[:100])
            check("tab has active", "active" in data[0], str(data[0])[:100])
    else:
        check("tabs returns list", False, str(data)[:100])


def test_marionette_eval(sandbox: Sandbox):
    """Test JavaScript evaluation."""
    print("\n=== Marionette JS Eval ===")

    data = run(sandbox, 'eval "document.title"')
    check("eval document.title works", "value" in data and "error" not in data, str(data)[:100])

    data = run(sandbox, 'eval "1 + 1"')
    check("eval 1+1 = 2", data.get("value") == 2, f"value={data.get('value')}")

    data = run(sandbox, 'eval "window.location.href"')
    check("eval location.href returns string", isinstance(data.get("value"), str), str(data)[:100])


def test_marionette_navigate(sandbox: Sandbox):
    """Test navigation and page content."""
    print("\n=== Marionette Navigate ===")

    # Navigate to about:support (always available offline)
    data = run(sandbox, 'navigate "about:support"', timeout=15)
    check("navigate returns url", "url" in data and "error" not in data, str(data)[:100])

    # Check page title after navigation
    data = run(sandbox, "title")
    check("title after navigate", "value" in data and "error" not in data, str(data)[:100])

    # Get page text
    data = run(sandbox, "text")
    check("text returns content", "value" in data and "error" not in data, str(data)[:100])


def test_marionette_selectors(sandbox: Sandbox):
    """Test CSS selector queries."""
    print("\n=== Marionette Selectors ===")

    # Navigate to a page with known structure
    run(sandbox, 'navigate "about:about"', timeout=10)
    time.sleep(1)

    data = run(sandbox, 'select "a"')
    check("select a finds links", "value" in data and "error" not in data, str(data)[:100])
    val = data.get("value", {})
    if isinstance(val, dict):
        check("select returns count", isinstance(val.get("count"), int), str(val)[:100])


def test_sqlite_history(sandbox: Sandbox):
    """Test history queries after browsing."""
    print("\n=== SQLite History ===")

    # Navigate to a few pages to generate history
    run(sandbox, 'navigate "about:about"', timeout=10)
    time.sleep(1)
    run(sandbox, 'navigate "about:support"', timeout=10)
    time.sleep(1)

    data = run(sandbox, "history")
    check("history returns list", isinstance(data, list), str(data)[:100])

    data = run(sandbox, "history about")
    check("history query returns list", isinstance(data, list), str(data)[:100])


def test_sqlite_bookmarks(sandbox: Sandbox):
    """Test bookmark queries."""
    print("\n=== SQLite Bookmarks ===")

    # Debug: find where Firefox profile actually is
    try:
        r = sandbox.commands.run("find / -name 'places.sqlite' 2>/dev/null | head -5", timeout=15)
        print(f"  [debug] places.sqlite locations: {r.stdout.strip()}")
        r2 = sandbox.commands.run("find / -name 'prefs.js' -path '*firefox*' 2>/dev/null | head -5", timeout=15)
        print(f"  [debug] prefs.js locations: {r2.stdout.strip()}")
    except Exception:
        pass

    data = run(sandbox, "bookmarks")
    check("bookmarks returns dict", isinstance(data, dict) and "error" not in data, str(data)[:100])
    if "error" not in data:
        check("bookmarks has count", "count" in data, str(data.keys()))
        check("bookmarks has matches", "matches" in data, str(data.keys()))


def test_sqlite_cookies(sandbox: Sandbox):
    """Test cookie queries."""
    print("\n=== SQLite Cookies ===")

    data = run(sandbox, "cookies")
    check("cookies returns dict", isinstance(data, dict), str(data)[:100])


def test_prefs(sandbox: Sandbox):
    """Test preferences reading."""
    print("\n=== Preferences ===")

    data = run(sandbox, "prefs")
    check("prefs returns dict", isinstance(data, dict) and "error" not in data, str(data)[:100])
    if "error" not in data:
        check("prefs has count", "count" in data, str(data.keys()))


def test_checks_positive(sandbox: Sandbox):
    """Composite check-* endpoints — positive cases."""
    print("\n=== Checks (positive) ===")

    # Navigate to create history
    run(sandbox, 'navigate "about:support"', timeout=10)
    time.sleep(2)

    # check-tab-open
    data = run(sandbox, 'check-tab-open about:support')
    check("check-tab-open about:support found", data.get("found") is True, str(data)[:100])

    # check-page-contains (about:support page has known content)
    data = run(sandbox, 'check-page-contains "Troubleshooting"')
    check("check-page-contains Troubleshooting",
          data.get("contains") is True, str(data)[:100])


def test_checks_negative(sandbox: Sandbox):
    """Composite check-* endpoints — negative cases."""
    print("\n=== Checks (negative) ===")

    # check-tab-open for nonexistent URL
    data = run(sandbox, "check-tab-open nonexistent-site-12345.com")
    check("check-tab-open nonexistent=false", data.get("found") is False, str(data)[:100])

    # check-page-contains for text not on page
    data = run(sandbox, 'check-page-contains "XYZZY_NONEXISTENT_TEXT_12345"')
    check("check-page-contains nonexistent=false", data.get("contains") is False, str(data)[:100])

    # check-download nonexistent
    data = run(sandbox, "check-download nonexistent_file_12345.pdf")
    check("check-download nonexistent=false", data.get("downloaded") is False, str(data)[:100])

    # check-bookmark nonexistent
    data = run(sandbox, "check-bookmark nonexistent_bookmark_12345")
    check("check-bookmark nonexistent=false", data.get("exists") is False, str(data)[:100])


def test_all_commands_return_json(sandbox: Sandbox):
    """Every CLI command should output valid JSON."""
    print("\n=== JSON validity (all commands) ===")

    no_arg_cmds = ["tabs", "url", "title", "text", "html", "screenshot",
                   "history", "bookmarks", "downloads", "cookies", "prefs", "form-history"]
    for cmd in no_arg_cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        check(f"{cmd} valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    arg_cmds = [
        ("eval", '"document.title"'),
        ("select", '"body"'),
        ("input", '"input"'),
        ("history", "about"),
        ("cookies", "localhost"),
        ("check-tab-open", "about:"),
        ("check-page-contains", "Firefox"),
        ("check-element-exists", "body"),
        ("check-download", "test.pdf"),
        ("check-bookmark", "test"),
    ]
    for cmd, arg in arg_cmds:
        result = run_raw(sandbox, f"{cmd} {arg}")
        valid = is_valid_json(result.stdout)
        check(f"{cmd} {arg} valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def launch_firefox(sandbox: Sandbox) -> bool:
    """Launch Firefox with Marionette enabled."""
    try:
        sandbox.commands.run("pkill -9 firefox", timeout=5)
    except (CommandExitException, Exception):
        pass
    time.sleep(2)

    # Install marionette_driver
    print("  Installing marionette_driver...")
    r = run_shell(sandbox, "pip install marionette_driver -q", timeout=120)
    if r.exit_code != 0:
        print(f"  WARNING: pip install failed: {r.stderr[:200]}")

    launch_script = '''#!/bin/bash
firefox-esr --marionette --no-remote > /tmp/firefox.log 2>&1
'''
    sandbox.files.write("/tmp/launch_ff.sh", launch_script)
    sandbox.commands.run("chmod +x /tmp/launch_ff.sh", timeout=3)
    sandbox.commands.run("/tmp/launch_ff.sh", background=True)

    # Wait for Marionette to be ready
    for i in range(30):
        try:
            r = sandbox.commands.run(
                "python3 -c \"from marionette_driver.marionette import Marionette; "
                "c = Marionette(host='127.0.0.1', port=2828); c.start_session(); "
                "print('READY'); c.delete_session()\"",
                timeout=10
            )
            if "READY" in r.stdout:
                print(f"  Firefox Marionette ready (attempt {i+1})")
                return True
        except (CommandExitException, Exception) as e:
            if i > 15:
                print(f"  attempt {i+1}: {str(e)[:80]}")
        time.sleep(2)

    try:
        r = sandbox.commands.run("tail -20 /tmp/firefox.log", timeout=3)
        print(f"  [ff log] {r.stdout[-300:]}")
    except (CommandExitException, Exception):
        pass
    return False


def main():
    global passed, failed

    print("=" * 60)
    print("Firefox ESR Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # ── Tests with Firefox NOT running ──
        test_help(sandbox)
        test_errors_firefox_not_running(sandbox)
        test_errors_bad_args(sandbox)

        # ── Launch Firefox ──
        print("\nLaunching Firefox with Marionette...")
        ff_ready = launch_firefox(sandbox)
        if not ff_ready:
            print("  WARNING: Firefox Marionette not ready -- live tests may fail")

        # ── Live tests ──
        test_marionette_tabs(sandbox)
        test_marionette_eval(sandbox)
        test_marionette_navigate(sandbox)
        test_marionette_selectors(sandbox)

        # ── SQLite tests (after browsing to generate some data) ──
        test_sqlite_history(sandbox)
        test_sqlite_bookmarks(sandbox)
        test_sqlite_cookies(sandbox)
        test_prefs(sandbox)

        # ── Check tests ──
        test_checks_positive(sandbox)
        test_checks_negative(sandbox)
        test_all_commands_return_json(sandbox)

    except Exception:
        traceback.print_exc()
        failed += 1
        errors.append(f"Unhandled exception: {traceback.format_exc()}")

    finally:
        sandbox.kill()
        print("\nSandbox killed.")

    # ── Summary ──
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print("=" * 60)

    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  - {e}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
