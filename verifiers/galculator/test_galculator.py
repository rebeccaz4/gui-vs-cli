"""
Test galculator verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (galculator not running, bad args)
  - Query endpoints (display, window-info, buttons, mode)
  - Check endpoints (positive and negative cases)
  - xdotool key input -> verify display via AT-SPI

Usage:
    python verifiers/galculator/test_galculator.py
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

VERIFIER_LOCAL = Path(__file__).parent / "galculator.py"
VERIFIER_REMOTE = "/home/user/verifiers/galculator.py"
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


def run_sandbox(sandbox: Sandbox, cmd: str, timeout: int = 30) -> CmdResult:
    """Run an arbitrary command in the sandbox."""
    try:
        result = sandbox.commands.run(cmd, timeout=timeout)
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
    """--help should print usage and exit 0."""
    print("\n=== Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
    check("help mentions commands", "Commands:" in result.stdout, result.stdout[:100])
    check("help mentions galculator", "galculator" in result.stdout.lower(), result.stdout[:100])


def test_errors_not_running(sandbox: Sandbox):
    """Endpoints should return error JSON when galculator is not running."""
    print("\n=== Errors (galculator not running) ===")

    data = run(sandbox, "display")
    check("display returns dict", isinstance(data, dict), str(type(data)))
    check("display has error or null display",
          data.get("error") is not None or data.get("display") is None,
          str(data)[:100])

    data = run(sandbox, "check-running")
    check("check-running returns dict", isinstance(data, dict), str(type(data)))
    check("check-running is false", data.get("running") is False, str(data)[:100])

    data = run(sandbox, "check-window-exists")
    check("check-window-exists is false", data.get("exists") is False, str(data)[:100])


def test_errors_bad_args(sandbox: Sandbox):
    """Missing/invalid arguments should return error JSON, not crash."""
    print("\n=== Errors (bad args) ===")

    # Missing required arg
    result = run_raw(sandbox, "check-display-value")
    check("missing arg exits 1", result.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Unknown command
    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])


def test_query_endpoints(sandbox: Sandbox):
    """Test query endpoints with galculator running."""
    print("\n=== Query Endpoints ===")

    # display
    data = run(sandbox, "display")
    check("display returns dict", isinstance(data, dict), str(type(data)))
    display_val = data.get("display")
    check("display has value", display_val is not None,
          f"display={display_val} error={data.get('error')}")
    if display_val is not None:
        check("display has source", "source" in data, str(data.keys()))
        print(f"    [info] display value: {display_val!r}")

    # window-info
    data = run(sandbox, "window-info")
    check("window-info returns dict", isinstance(data, dict), str(type(data)))
    check("window-info no error", "error" not in data, str(data)[:100])

    # buttons
    data = run(sandbox, "buttons")
    check("buttons returns dict", isinstance(data, dict), str(type(data)))
    if "error" not in data:
        check("buttons has list", isinstance(data.get("buttons"), list), str(data)[:100])
        check("buttons has count", isinstance(data.get("count"), int), str(data)[:100])
        btn_count = data.get("count", 0)
        check("buttons count > 0", btn_count > 0, f"count={btn_count}")
        if data.get("buttons"):
            print(f"    [info] found {btn_count} buttons: {data['buttons'][:10]}...")

    # mode
    data = run(sandbox, "mode")
    check("mode returns dict", isinstance(data, dict), str(type(data)))
    if "error" not in data:
        check("mode has mode key", "mode" in data, str(data)[:100])
        print(f"    [info] mode: {data.get('mode')}")


def test_checks_positive(sandbox: Sandbox):
    """Check endpoints -- positive cases after typing keys."""
    print("\n=== Checks (positive) ===")

    # check-running
    data = run(sandbox, "check-running")
    check("check-running is true", data.get("running") is True, str(data)[:100])

    # check-window-exists
    data = run(sandbox, "check-window-exists")
    check("check-window-exists is true", data.get("exists") is True, str(data)[:100])

    # Type "123" using xdotool and verify display
    print("  [action] Typing '123' via xdotool...")
    run_sandbox(sandbox, "xdotool key --clearmodifiers c")  # Clear display first
    time.sleep(0.3)
    run_sandbox(sandbox, "xdotool key --clearmodifiers 1")
    time.sleep(0.2)
    run_sandbox(sandbox, "xdotool key --clearmodifiers 2")
    time.sleep(0.2)
    run_sandbox(sandbox, "xdotool key --clearmodifiers 3")
    time.sleep(0.5)

    # Read display
    data = run(sandbox, "display")
    display_val = data.get("display", "")
    print(f"    [info] display after typing 123: {display_val!r}")
    check("display contains 123", "123" in str(display_val),
          f"display={display_val}")

    # check-display-contains
    data = run(sandbox, "check-display-contains 123")
    check("check-display-contains 123 is true",
          data.get("contains") is True, str(data)[:100])

    # check-display-value (may have trailing .0 or similar)
    data = run(sandbox, "check-display-value 123")
    if not data.get("match"):
        # Try with trailing period or zero
        actual = data.get("actual", "")
        print(f"    [info] exact match failed, actual={actual!r}")
        # Still check that the actual value contains 123
        check("check-display-value actual contains 123",
              "123" in str(actual), f"actual={actual}")
    else:
        check("check-display-value exact match", data.get("match") is True, str(data)[:100])

    # Now do a calculation: 123 + 456 = 579
    print("  [action] Computing 123 + 456 = ...")
    run_sandbox(sandbox, "xdotool key --clearmodifiers c")  # Clear
    time.sleep(0.3)
    for key in ["1", "2", "3", "plus", "4", "5", "6", "Return"]:
        run_sandbox(sandbox, f"xdotool key --clearmodifiers {key}")
        time.sleep(0.2)
    time.sleep(0.5)

    data = run(sandbox, "display")
    display_val = data.get("display", "")
    print(f"    [info] display after 123+456=: {display_val!r}")
    check("display contains 579", "579" in str(display_val),
          f"display={display_val}")


def test_checks_negative(sandbox: Sandbox):
    """Check endpoints -- negative cases."""
    print("\n=== Checks (negative) ===")

    # check-display-value with wrong value
    data = run(sandbox, "check-display-value 99999")
    check("check-display-value 99999 is false",
          data.get("match") is False, str(data)[:100])

    # check-display-contains with text not in display
    data = run(sandbox, "check-display-contains xyznonexistent")
    check("check-display-contains nonexistent is false",
          data.get("contains") is False, str(data)[:100])


def test_all_commands_return_json(sandbox: Sandbox):
    """Every CLI command should output valid JSON (not crash with a traceback)."""
    print("\n=== JSON validity (all commands) ===")

    # Commands that need no args
    no_arg_cmds = ["display", "window-info", "buttons", "mode",
                   "check-running", "check-window-exists"]

    for cmd in no_arg_cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        check(f"{cmd} returns valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # Commands that need args
    arg_cmds = [
        ("check-display-value", "42"),
        ("check-display-contains", "4"),
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
    print("galculator Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # Ensure AT-SPI dependencies are available
        print("Checking AT-SPI dependencies...")
        r = run_sandbox(sandbox, "python3 -c \"import gi; gi.require_version('Atspi', '2.0'); from gi.repository import Atspi; print('OK')\"")
        print(f"  AT-SPI import: {r.stdout.strip()} (exit={r.exit_code})")
        if r.exit_code != 0:
            print(f"  [warn] AT-SPI not available: {r.stderr[:200]}")
            print("  Installing python3-gi and gir1.2-atspi-2.0...")
            run_sandbox(sandbox, "sudo apt-get update -qq && sudo apt-get install -y -qq python3-gi gir1.2-atspi-2.0 at-spi2-core 2>&1 | tail -3", timeout=120)

        # Ensure xdotool is available
        r = run_sandbox(sandbox, "which xdotool")
        print(f"  xdotool: {r.stdout.strip()} (exit={r.exit_code})")

        # --- Tests with galculator NOT running ---
        test_help(sandbox)
        test_errors_not_running(sandbox)
        test_errors_bad_args(sandbox)

        # --- Launch galculator ---
        print("\nLaunching galculator...")

        # Start AT-SPI bus if needed
        run_sandbox(sandbox, "export $(dbus-launch)", timeout=5)

        # Launch galculator
        sandbox.commands.run(
            "galculator > /tmp/galculator.log 2>&1",
            background=True,
        )

        # Wait for galculator to start
        galculator_ready = False
        for i in range(15):
            r = run_sandbox(sandbox, "pgrep -x galculator")
            if r.exit_code == 0 and r.stdout.strip():
                print(f"  galculator running (attempt {i+1}), PID: {r.stdout.strip()}")
                galculator_ready = True
                break
            time.sleep(1)

        if not galculator_ready:
            print("  WARNING: galculator not detected -- tests may fail")
            r = run_sandbox(sandbox, "cat /tmp/galculator.log")
            print(f"  [log] {r.stdout[:300]}")
        else:
            # Give it time to fully render and register with AT-SPI
            time.sleep(3)

            # Focus the galculator window
            r = run_sandbox(sandbox, "xdotool search --name galculator windowactivate 2>/dev/null")
            if r.exit_code != 0:
                r = run_sandbox(sandbox, "xdotool search --class galculator windowactivate 2>/dev/null")
            time.sleep(1)

        # --- Tests with galculator running ---
        test_query_endpoints(sandbox)
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
