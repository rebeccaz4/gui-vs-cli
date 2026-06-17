"""
Test Chrome verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (Chrome not running, bad args)
  - CDP endpoints (tabs, url, title, text, html, eval, select, cookies, navigate)
  - SQLite endpoints (history, downloads, bookmarks, extensions, prefs)
  - Composite check-* endpoints (positive and negative cases)

Usage:
    python verifiers/chrome/test_chrome.py
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

VERIFIER_LOCAL = Path(__file__).parent / "chrome.py"
VERIFIER_REMOTE = "/home/user/verifiers/chrome.py"
V = f"python3 {VERIFIER_REMOTE}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

passed = 0
failed = 0
errors: list[str] = []


class CmdResult:
    """Minimal wrapper to normalize both success and CommandExitException results."""
    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def run(sandbox: Sandbox, cmd: str, timeout: int = 30) -> dict | list:
    """Run a verifier CLI command, parse JSON output."""
    r = run_raw(sandbox, cmd, timeout)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


def run_raw(sandbox: Sandbox, cmd: str, timeout: int = 30) -> CmdResult:
    """Run a command and return a CmdResult (never throws on non-zero exit)."""
    try:
        result = sandbox.commands.run(f"{V} {cmd}", timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def check(name: str, condition: bool, detail: str = ""):
    """Record a test result."""
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f"  — {detail}"
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
    """--help should print usage and exit 0."""
    print("\n=== Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
    check("help mentions commands", "Commands:" in result.stdout, result.stdout[:100])


def test_errors_chrome_not_running(sandbox: Sandbox):
    """CDP endpoints should return error JSON when Chrome is not running."""
    print("\n=== Errors (Chrome not running) ===")

    data = run(sandbox, "tabs")
    if isinstance(data, list):
        data = data[0]
    check("tabs returns error", "error" in data, str(data)[:100])

    data = run(sandbox, "url")
    check("url returns error", "error" in data, str(data)[:100])

    # File-based endpoints may also error if Chrome never launched (no profile)
    data = run(sandbox, "prefs")
    # This might work or error depending on whether profile dir exists
    check("prefs returns dict", isinstance(data, dict), str(type(data)))


def test_errors_bad_args(sandbox: Sandbox):
    """Missing/invalid arguments should return error JSON, not crash."""
    print("\n=== Errors (bad args) ===")

    # Missing required arg
    result = run_raw(sandbox, "check-tab-open")
    check("missing arg exits 1", result.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Unknown command
    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])


def test_cdp_endpoints(sandbox: Sandbox):
    """Test all CDP-based endpoints with Chrome running."""
    print("\n=== CDP Endpoints ===")

    # tabs
    data = run(sandbox, "tabs")
    check("tabs returns list", isinstance(data, list), str(type(data)))
    check("tabs has entries", len(data) > 0, f"got {len(data)} tabs")
    if data and "error" not in data[0]:
        check("tab has url key", "url" in data[0], str(data[0].keys()))

    # url
    data = run(sandbox, "url")
    check("url returns dict", isinstance(data, dict))
    check("url has value", "value" in data or "error" in data, str(data)[:100])

    # title
    data = run(sandbox, "title")
    check("title returns dict", isinstance(data, dict))
    check("title has value", "value" in data or "error" in data, str(data)[:100])

    # text
    data = run(sandbox, "text")
    check("text returns dict", isinstance(data, dict))

    # html
    data = run(sandbox, "html")
    check("html returns dict", isinstance(data, dict))
    if "value" in data and data["value"]:
        check("html contains <", "<" in str(data["value"]), str(data["value"])[:80])

    # eval
    data = run(sandbox, "eval '1+1'")
    check("eval returns dict", isinstance(data, dict))
    check("eval 1+1 = 2", data.get("value") == 2, f"got value={data.get('value')} full={data}")

    data = run(sandbox, "eval 'document.title'")
    check("eval title is string", data.get("type") == "string", f"got type={data.get('type')} full={data}")

    # select - look for <body> which always exists
    data = run(sandbox, "select body")
    check("select returns dict", isinstance(data, dict))

    # cookies
    data = run(sandbox, "cookies")
    check("cookies returns dict", isinstance(data, dict))
    check("cookies has key", "cookies" in data or "error" in data, str(data.keys()))

    # screenshot
    data = run(sandbox, "screenshot")
    check("screenshot returns dict", isinstance(data, dict))
    check("screenshot has data", "data_base64" in data or "error" in data, str(data.keys()))


def test_navigate(sandbox: Sandbox):
    """Navigate to a known page and verify the URL changed."""
    print("\n=== Navigate ===")

    data = run(sandbox, "navigate https://example.com", timeout=15)
    check("navigate returns dict", isinstance(data, dict))

    # Give page time to load
    time.sleep(3)

    data = run(sandbox, "url")
    url_val = data.get("value", "")
    check("navigated to example.com", "example.com" in str(url_val), f"url={url_val}")

    data = run(sandbox, "title")
    title_val = data.get("value", "")
    check("title is Example Domain", "Example" in str(title_val), f"title={title_val}")


def test_sqlite_endpoints(sandbox: Sandbox):
    """Test SQLite-based endpoints (history, downloads, bookmarks, extensions, prefs)."""
    print("\n=== SQLite / File Endpoints ===")

    # After navigating to example.com, history should have it
    data = run(sandbox, "history")
    check("history returns list", isinstance(data, list), str(type(data)))
    if data and "error" not in data[0]:
        check("history has url key", "url" in data[0], str(data[0].keys()))

    data = run(sandbox, "history example.com")
    check("history search returns list", isinstance(data, list))

    # downloads (may be empty, that's ok)
    data = run(sandbox, "downloads")
    check("downloads returns list", isinstance(data, list))

    # bookmarks
    data = run(sandbox, "bookmarks")
    check("bookmarks returns dict", isinstance(data, dict))
    check("bookmarks has count", "count" in data or "error" in data, str(data.keys()))

    # extensions
    data = run(sandbox, "extensions")
    check("extensions returns list", isinstance(data, list))

    # prefs (no key = list top-level keys)
    data = run(sandbox, "prefs")
    check("prefs returns dict", isinstance(data, dict))
    if "keys" in data:
        check("prefs has keys list", isinstance(data["keys"], list), str(data["keys"])[:100])


def test_checks_positive(sandbox: Sandbox):
    """Composite check-* endpoints — positive cases (should return true)."""
    print("\n=== Checks (positive) ===")

    # We navigated to example.com earlier, so these should be true

    # check-tab-open
    data = run(sandbox, "check-tab-open example.com")
    check("check-tab-open found=bool", isinstance(data.get("found"), bool), str(data))
    check("check-tab-open found=true", data.get("found") is True, str(data)[:100])

    # check-url-visited (wait for Chrome to flush history to SQLite)
    time.sleep(5)
    data = run(sandbox, "check-url-visited example.com")
    check("check-url-visited visited=bool", isinstance(data.get("visited"), bool), str(data))
    check("check-url-visited visited=true", data.get("visited") is True, str(data)[:100])

    # check-page-contains (example.com has "Example Domain" text)
    data = run(sandbox, 'check-page-contains "Example Domain"')
    check("check-page-contains contains=bool", isinstance(data.get("contains"), bool), str(data))
    check("check-page-contains contains=true", data.get("contains") is True, str(data)[:100])
    check("check-page-contains has snippet", data.get("snippet") is not None, str(data.get("snippet")))

    # check-element-exists (example.com has <h1>)
    data = run(sandbox, "check-element-exists h1")
    check("check-element-exists has exists key", "exists" in data or "error" in data, str(data)[:100])


def test_checks_negative(sandbox: Sandbox):
    """Composite check-* endpoints — negative cases (should return false)."""
    print("\n=== Checks (negative) ===")

    # check-tab-open for a site we never opened
    data = run(sandbox, "check-tab-open totallynonexistentsite12345.com")
    check("check-tab-open found=false", data.get("found") is False, str(data)[:100])

    # check-url-visited for something not in history
    data = run(sandbox, "check-url-visited totallynonexistentsite12345.com")
    check("check-url-visited visited=false", data.get("visited") is False, str(data)[:100])

    # check-page-contains for text not on the page
    data = run(sandbox, 'check-page-contains "xyzzy_not_on_any_page_12345"')
    check("check-page-contains contains=false", data.get("contains") is False, str(data)[:100])
    check("check-page-contains snippet=None", data.get("snippet") is None, str(data.get("snippet")))

    # check-download for a file we never downloaded
    data = run(sandbox, "check-download nonexistent_file_12345.zip")
    check("check-download downloaded=false", data.get("downloaded") is False, str(data)[:100])

    # check-bookmark for something not bookmarked (fresh profile may not have Bookmarks file)
    data = run(sandbox, "check-bookmark xyzzy_no_bookmark_12345")
    check("check-bookmark exists=false or error",
          data.get("exists") is False or "error" in data, str(data)[:100])


def test_all_commands_return_json(sandbox: Sandbox):
    """Every CLI command should output valid JSON (not crash with a traceback)."""
    print("\n=== JSON validity (all commands) ===")

    # Commands that need no args
    no_arg_cmds = ["tabs", "url", "title", "text", "html", "cookies", "screenshot",
                   "history", "downloads", "bookmarks", "extensions", "prefs"]

    for cmd in no_arg_cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        check(f"{cmd} returns valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # Commands that need args (use dummy values)
    arg_cmds = [
        ("eval", "'1+1'"),
        ("select", "body"),
        ("input", "input"),
        ("navigate", "about:blank"),
        ("history", "test"),
        ("bookmarks", "test"),
        ("prefs", "profile"),
        ("check-url-visited", "test"),
        ("check-tab-open", "test"),
        ("check-page-contains", "test"),
        ("check-element-exists", "body"),
        ("check-download", "test"),
        ("check-bookmark", "test"),
        ("check-cookie", "test"),
    ]

    for cmd, arg in arg_cmds:
        result = run_raw(sandbox, f"{cmd} {arg}")
        valid = is_valid_json(result.stdout)
        check(f"{cmd} {arg} returns valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed

    print("=" * 60)
    print("Chrome Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # Install websocket-client for CDP WebSocket commands
        print("Installing websocket-client...")
        r = sandbox.commands.run("pip install websocket-client 2>&1", timeout=60)
        print(f"  pip: {r.stdout.strip()[-80:]}")

        # --- Tests with Chrome NOT running ---
        test_help(sandbox)
        test_errors_chrome_not_running(sandbox)
        test_errors_bad_args(sandbox)

        # --- Launch Chrome with CDP ---
        CHROME_CMD = (
            "google-chrome --no-first-run --no-default-browser-check "
            "--no-sandbox --disable-dev-shm-usage --disable-gpu "
            "--disable-background-networking --disable-sync "
            "--disable-translate --disable-extensions "
            "--disable-component-update --disable-hang-monitor "
            "--disable-breakpad --disable-domain-reliability "
            "--metrics-recording-only --safebrowsing-disable-auto-update "
            "--remote-debugging-port=9222 "
            "--remote-allow-origins=* "
            "--user-data-dir=/tmp/chrome-test-profile "
            "about:blank"
        )

        def launch_chrome():
            """Kill existing Chrome and launch fresh."""
            try:
                sandbox.commands.run("pkill -9 -f chrome", timeout=5)
            except (CommandExitException, Exception):
                pass
            time.sleep(1)

            sandbox.commands.run(
                f"{CHROME_CMD} > /tmp/chrome.log 2>&1",
                background=True,
            )
            for i in range(20):
                try:
                    r = sandbox.commands.run(
                        "curl -s http://127.0.0.1:9222/json", timeout=3
                    )
                    if r.stdout.strip().startswith("["):
                        print(f"  Chrome CDP ready (attempt {i+1})")
                        return True
                except (CommandExitException, Exception):
                    pass
                time.sleep(1)
            # Debug: show chrome log on failure
            try:
                r = sandbox.commands.run("tail -30 /tmp/chrome.log", timeout=3)
                print(f"  [chrome log] {r.stdout[-500:]}")
            except (CommandExitException, Exception):
                pass
            try:
                r = sandbox.commands.run("pgrep -la chrome", timeout=3)
                print(f"  [processes] {r.stdout.strip()[:200]}")
            except (CommandExitException, Exception):
                print("  No Chrome processes found!")
            return False

        def ensure_cdp():
            """Check if CDP is alive, relaunch Chrome if not."""
            try:
                r = sandbox.commands.run(
                    "curl -s http://127.0.0.1:9222/json", timeout=3
                )
                if r.stdout.strip().startswith("["):
                    return True
            except (CommandExitException, Exception):
                pass
            print("  [debug] CDP dead — relaunching Chrome...")
            return launch_chrome()

        print("\nLaunching Chrome with --remote-debugging-port=9222...")
        if not launch_chrome():
            print("  WARNING: Chrome CDP not ready — CDP tests may fail")

        # --- Tests with Chrome running ---
        test_cdp_endpoints(sandbox)
        ensure_cdp()
        test_navigate(sandbox)
        ensure_cdp()
        test_sqlite_endpoints(sandbox)
        ensure_cdp()
        test_checks_positive(sandbox)
        ensure_cdp()
        test_checks_negative(sandbox)
        test_all_commands_return_json(sandbox)

    except Exception:
        traceback.print_exc()
        failed += 1
        errors.append(f"Unhandled exception: {traceback.format_exc()}")

    finally:
        sandbox.kill()
        print("\nSandbox killed.")

    # --- Summary ---
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  - {e}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
