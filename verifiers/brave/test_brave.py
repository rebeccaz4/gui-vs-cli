"""
Test Brave browser verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage, error cases (Brave not running, bad args)
  - CDP live endpoints (tabs, eval, navigate, selectors)
  - SQLite endpoints (history, bookmarks, downloads)
  - Composite check-* endpoints — positive and negative
  - JSON validity for all commands

Usage:
    python verifiers/brave/test_brave.py
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

VERIFIER_LOCAL = Path(__file__).parent / "brave.py"
VERIFIER_REMOTE = "/home/user/verifiers/brave.py"
V = f"python3 {VERIFIER_REMOTE}"

passed = 0
failed = 0
errors: list[str] = []


class CmdResult:
    def __init__(self, exit_code, stdout, stderr):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def run(sb, cmd, timeout=30):
    r = run_raw(sb, cmd, timeout)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


def run_raw(sb, cmd, timeout=30):
    try:
        result = sb.commands.run(f"{V} {cmd}", timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def run_shell(sb, cmd, timeout=60):
    try:
        result = sb.commands.run(cmd, timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def check(name, condition, detail=""):
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


def is_valid_json(s):
    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


def test_help(sb):
    print("\n=== Help ===")
    result = run_raw(sb, "--help")
    check("help exits 0", result.exit_code == 0)
    check("help mentions commands", "Commands:" in result.stdout)


def test_errors_not_running(sb):
    print("\n=== Errors (Brave not running) ===")
    for cmd in ["tabs", "url", "title"]:
        data = run(sb, cmd)
        is_err = ("error" in data) if isinstance(data, dict) else ("error" in data[0] if data else True)
        check(f"{cmd} returns error when Brave down", is_err, str(data)[:100])


def test_errors_bad_args(sb):
    print("\n=== Errors (bad args) ===")
    result = run_raw(sb, "check-url-visited")
    check("missing arg exits 1", result.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(result.stdout))

    result = run_raw(sb, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout))


def test_cdp_tabs(sb):
    print("\n=== CDP Tabs ===")
    data = run(sb, "tabs")
    if isinstance(data, list) and data and "error" not in data[0]:
        check("tabs returns list", len(data) > 0)
        check("tab has url", "url" in data[0])
        check("tab has title", "title" in data[0])
    else:
        check("tabs returns list", False, str(data)[:100])


def test_cdp_eval(sb):
    print("\n=== CDP JS Eval ===")
    data = run(sb, 'eval "document.title"')
    check("eval document.title works", "value" in data and "error" not in data, str(data)[:100])

    data = run(sb, 'eval "1 + 1"')
    check("eval 1+1 = 2", data.get("value") == 2, f"value={data.get('value')}")


def test_cdp_navigate(sb):
    print("\n=== CDP Navigate ===")
    data = run(sb, 'navigate "brave://version"', timeout=15)
    check("navigate works", "error" not in data, str(data)[:100])

    data = run(sb, "title")
    check("title after navigate", "value" in data and "error" not in data, str(data)[:100])


def test_checks_positive(sb):
    print("\n=== Checks (positive) ===")
    run(sb, 'navigate "brave://version"', timeout=10)
    time.sleep(2)

    data = run(sb, "check-tab-open brave://version")
    check("check-tab-open brave://version", data.get("found") is True, str(data)[:100])

    data = run(sb, 'check-page-contains "Brave"')
    check("check-page-contains Brave", data.get("contains") is True, str(data)[:100])


def test_checks_negative(sb):
    print("\n=== Checks (negative) ===")
    data = run(sb, "check-tab-open nonexistent-site-12345.com")
    check("check-tab-open nonexistent=false", data.get("found") is False, str(data)[:100])

    data = run(sb, 'check-page-contains "XYZZY_NONEXISTENT_12345"')
    check("check-page-contains nonexistent=false", data.get("contains") is False, str(data)[:100])

    data = run(sb, "check-download nonexistent_12345.pdf")
    check("check-download nonexistent=false", data.get("downloaded") is False, str(data)[:100])


def test_all_json(sb):
    print("\n=== JSON validity ===")
    cmds = ["tabs", "url", "title", "text", "html", "screenshot",
            "history", "downloads", "bookmarks", "extensions", "prefs"]
    for cmd in cmds:
        result = run_raw(sb, cmd)
        check(f"{cmd} valid JSON", is_valid_json(result.stdout),
              f"stdout={result.stdout[:80]}" if not is_valid_json(result.stdout) else "")


def launch_brave(sb):
    try:
        sb.commands.run("pkill -9 brave", timeout=5)
    except (CommandExitException, Exception):
        pass
    time.sleep(2)

    sb.commands.run("pip install websocket-client -q", timeout=120)

    launch_script = '#!/bin/bash\nbrave-browser --remote-debugging-port=9222 --remote-allow-origins=* --no-sandbox --disable-gpu > /tmp/brave.log 2>&1\n'
    sb.files.write("/tmp/launch_brave.sh", launch_script)
    sb.commands.run("chmod +x /tmp/launch_brave.sh", timeout=3)
    sb.commands.run("/tmp/launch_brave.sh", background=True)

    for i in range(30):
        try:
            r = sb.commands.run("curl -s http://127.0.0.1:9222/json", timeout=5)
            if r.exit_code == 0 and "[" in r.stdout:
                print(f"  Brave CDP ready (attempt {i+1})")
                return True
        except (CommandExitException, Exception):
            pass
        time.sleep(2)

    try:
        r = sb.commands.run("tail -20 /tmp/brave.log", timeout=3)
        print(f"  [brave log] {r.stdout[-300:]}")
    except (CommandExitException, Exception):
        pass
    return False


def main():
    global passed, failed
    print("=" * 60)
    print("Brave Browser Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sb = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sb.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sb.files.write(VERIFIER_REMOTE, f.read())

        test_help(sb)
        test_errors_not_running(sb)
        test_errors_bad_args(sb)

        print("\nLaunching Brave with CDP...")
        if not launch_brave(sb):
            print("  WARNING: Brave CDP not ready")

        test_cdp_tabs(sb)
        test_cdp_eval(sb)
        test_cdp_navigate(sb)
        test_checks_positive(sb)
        test_checks_negative(sb)
        test_all_json(sb)

    except Exception:
        traceback.print_exc()
        failed += 1
        errors.append(f"Unhandled: {traceback.format_exc()}")
    finally:
        sb.kill()
        print("\nSandbox killed.")

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
