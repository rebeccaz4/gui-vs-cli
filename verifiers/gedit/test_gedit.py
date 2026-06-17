"""
Test Gedit verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (missing files, bad args)
  - File system query endpoints (file-content, file-info, file-encoding,
    file-line-count, file-word-count, recent-files)
  - gsettings query endpoints (settings, setting)
  - Check endpoints — positive cases (file exists, contains text, line match, etc.)
  - Check endpoints — negative cases (missing file, wrong content, wrong count, etc.)
  - All commands return valid JSON

Usage:
    python verifiers/gedit/test_gedit.py
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

VERIFIER_LOCAL = Path(__file__).parent / "gedit.py"
VERIFIER_REMOTE = "/home/user/verifiers/gedit.py"
V = f"python3 {VERIFIER_REMOTE}"

# Test file paths inside the sandbox
TEST_FILE = "/tmp/gedit_test.txt"
TEST_FILE_MULTI = "/tmp/gedit_test_multi.txt"
NONEXISTENT_FILE = "/tmp/nonexistent_file_xyz_12345.txt"

# Test file contents
TEST_CONTENT = "Hello world\nThis is line two\nThird line here\n"
TEST_CONTENT_MULTI = "Line one\nLine two\nLine three\nLine four\nLine five\n"

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
    check("help mentions gedit", "Gedit" in result.stdout or "gedit" in result.stdout, result.stdout[:100])


def test_errors_bad_args(sandbox: Sandbox):
    """Missing/invalid arguments should return error JSON, not crash."""
    print("\n=== Errors (bad args) ===")

    # Missing required arg
    result = run_raw(sandbox, "file-content")
    check("missing arg exits 1", result.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Unknown command
    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Nonexistent file
    data = run(sandbox, f"file-content {NONEXISTENT_FILE}")
    check("nonexistent file returns error", "error" in data, str(data)[:100])

    # Bad line number for check-file-line
    data = run(sandbox, f"check-file-line {TEST_FILE} 9999 expected")
    check("bad line num returns error", "error" in data or data.get("matches") is False, str(data)[:100])


def test_errors_nonexistent_files(sandbox: Sandbox):
    """File endpoints should return error for nonexistent files."""
    print("\n=== Errors (nonexistent files) ===")

    for cmd in ("file-content", "file-info", "file-encoding", "file-line-count", "file-word-count"):
        data = run(sandbox, f"{cmd} {NONEXISTENT_FILE}")
        check(f"{cmd} nonexistent returns error", "error" in data, str(data)[:100])

    # check- endpoints should return false/error
    data = run(sandbox, f"check-file-exists {NONEXISTENT_FILE}")
    check("check-file-exists nonexistent=false", data.get("exists") is False, str(data)[:100])

    data = run(sandbox, f"check-file-contains {NONEXISTENT_FILE} hello")
    check("check-file-contains nonexistent=false", data.get("contains") is False, str(data)[:100])

    data = run(sandbox, f"check-file-saved {NONEXISTENT_FILE}")
    check("check-file-saved nonexistent=false", data.get("saved") is False, str(data)[:100])


def test_file_query_endpoints(sandbox: Sandbox):
    """Test file system query endpoints with known test files."""
    print("\n=== File Query Endpoints ===")

    # file-content
    data = run(sandbox, f"file-content {TEST_FILE}")
    check("file-content returns dict", isinstance(data, dict))
    check("file-content has content key", "content" in data, str(data.keys()))
    check("file-content matches", data.get("content") == TEST_CONTENT,
          f"got: {repr(data.get('content', '')[:80])}")
    check("file-content has size", "size" in data, str(data.keys()))

    # file-info
    data = run(sandbox, f"file-info {TEST_FILE}")
    check("file-info returns dict", isinstance(data, dict))
    check("file-info has size", "size" in data, str(data.keys()))
    check("file-info has modified", "modified" in data, str(data.keys()))
    check("file-info has permissions", "permissions" in data, str(data.keys()))
    check("file-info has encoding", "encoding" in data, str(data.keys()))
    check("file-info exists=true", data.get("exists") is True, str(data)[:100])

    # file-encoding
    data = run(sandbox, f"file-encoding {TEST_FILE}")
    check("file-encoding returns dict", isinstance(data, dict))
    check("file-encoding has encoding key", "encoding" in data, str(data.keys()))
    encoding = data.get("encoding", "").lower()
    check("file-encoding is utf-8 or ascii", encoding in ("utf-8", "ascii"),
          f"got encoding={encoding}")

    # file-line-count
    data = run(sandbox, f"file-line-count {TEST_FILE}")
    check("file-line-count returns dict", isinstance(data, dict))
    check("file-line-count has line_count", "line_count" in data, str(data.keys()))
    check("file-line-count = 3", data.get("line_count") == 3,
          f"got line_count={data.get('line_count')}")

    # file-word-count
    data = run(sandbox, f"file-word-count {TEST_FILE}")
    check("file-word-count returns dict", isinstance(data, dict))
    check("file-word-count has word_count", "word_count" in data, str(data.keys()))
    expected_words = len(TEST_CONTENT.split())
    check(f"file-word-count = {expected_words}", data.get("word_count") == expected_words,
          f"got word_count={data.get('word_count')}")

    # file-line-count on multi-line file
    data = run(sandbox, f"file-line-count {TEST_FILE_MULTI}")
    check("multi file-line-count = 5", data.get("line_count") == 5,
          f"got line_count={data.get('line_count')}")


def test_recent_files(sandbox: Sandbox):
    """Test recent-files endpoint (may return empty if gedit hasn't been used)."""
    print("\n=== Recent Files ===")

    data = run(sandbox, "recent-files")
    check("recent-files returns dict", isinstance(data, dict))
    check("recent-files has all_recent_files key",
          "all_recent_files" in data or "error" in data, str(data.keys()))


def test_gsettings_endpoints(sandbox: Sandbox):
    """Test gsettings query endpoints."""
    print("\n=== gsettings Endpoints ===")

    # settings (default schema)
    data = run(sandbox, "settings")
    if isinstance(data, list):
        if data and "error" in data[0]:
            check("settings returns data or error", True, str(data[0])[:100])
        else:
            check("settings returns list", True)
            check("settings has entries", len(data) > 0, f"got {len(data)} entries")
            if data:
                check("settings entry has schema", "schema" in data[0], str(data[0].keys()))
                check("settings entry has key", "key" in data[0], str(data[0].keys()))
                check("settings entry has value", "value" in data[0], str(data[0].keys()))
    else:
        # If gsettings schema not installed, we get an error dict
        check("settings returns list or error", "error" in data, str(data)[:100])

    # setting (specific key)
    data = run(sandbox, "setting tab-size")
    check("setting tab-size returns dict", isinstance(data, dict))
    if "error" not in data:
        check("setting has value", "value" in data, str(data.keys()))
        check("setting value is not empty", len(data.get("value", "")) > 0, str(data)[:100])


def test_checks_positive(sandbox: Sandbox):
    """Check endpoints — positive cases (should pass)."""
    print("\n=== Checks (positive) ===")

    # check-file-exists
    data = run(sandbox, f"check-file-exists {TEST_FILE}")
    check("check-file-exists exists=true", data.get("exists") is True, str(data)[:100])
    check("check-file-exists has size", "size" in data, str(data.keys()))

    # check-file-contains
    data = run(sandbox, f"check-file-contains {TEST_FILE} Hello world")
    check("check-file-contains contains=true", data.get("contains") is True, str(data)[:100])
    check("check-file-contains has occurrences", data.get("occurrences", 0) >= 1,
          f"got occurrences={data.get('occurrences')}")
    check("check-file-contains has snippet", "snippet" in data, str(data.keys()))

    # check-file-contains with partial match
    data = run(sandbox, f"check-file-contains {TEST_FILE} line two")
    check("check-file-contains partial match", data.get("contains") is True, str(data)[:100])

    # check-file-line (1-based)
    data = run(sandbox, f"check-file-line {TEST_FILE} 1 Hello world")
    check("check-file-line matches=true", data.get("matches") is True, str(data)[:100])
    check("check-file-line has actual", "actual" in data, str(data.keys()))

    data = run(sandbox, f"check-file-line {TEST_FILE} 2 This is line two")
    check("check-file-line line 2 matches", data.get("matches") is True, str(data)[:100])

    # check-file-line-count
    data = run(sandbox, f"check-file-line-count {TEST_FILE} 3")
    check("check-file-line-count matches=true", data.get("matches") is True, str(data)[:100])

    # check-file-line-count on multi-line file
    data = run(sandbox, f"check-file-line-count {TEST_FILE_MULTI} 5")
    check("check-file-line-count multi matches=true", data.get("matches") is True, str(data)[:100])

    # check-file-encoding
    data = run(sandbox, f"check-file-encoding {TEST_FILE} utf-8")
    if data.get("matches") is True:
        check("check-file-encoding utf-8 matches", True)
    else:
        # ASCII is a subset of UTF-8, so ASCII detection is also acceptable
        data2 = run(sandbox, f"check-file-encoding {TEST_FILE} ascii")
        check("check-file-encoding ascii or utf-8 matches",
              data.get("matches") is True or data2.get("matches") is True,
              f"utf-8={data}, ascii={data2}")

    # check-file-saved
    data = run(sandbox, f"check-file-saved {TEST_FILE} 0")
    check("check-file-saved saved=true (min 0)", data.get("saved") is True, str(data)[:100])

    data = run(sandbox, f"check-file-saved {TEST_FILE} 10")
    check("check-file-saved saved=true (min 10)", data.get("saved") is True, str(data)[:100])


def test_checks_negative(sandbox: Sandbox):
    """Check endpoints — negative cases (should return false)."""
    print("\n=== Checks (negative) ===")

    # check-file-exists on nonexistent
    data = run(sandbox, f"check-file-exists {NONEXISTENT_FILE}")
    check("check-file-exists exists=false", data.get("exists") is False, str(data)[:100])

    # check-file-contains with text not in file
    data = run(sandbox, f"check-file-contains {TEST_FILE} xyzzy_not_in_file_12345")
    check("check-file-contains contains=false", data.get("contains") is False, str(data)[:100])
    check("check-file-contains occurrences=0", data.get("occurrences") == 0,
          f"got occurrences={data.get('occurrences')}")

    # check-file-line with wrong expected text
    data = run(sandbox, f"check-file-line {TEST_FILE} 1 wrong text here")
    check("check-file-line matches=false", data.get("matches") is False, str(data)[:100])

    # check-file-line-count with wrong count
    data = run(sandbox, f"check-file-line-count {TEST_FILE} 999")
    check("check-file-line-count matches=false", data.get("matches") is False, str(data)[:100])
    check("check-file-line-count has actual", "actual" in data, str(data.keys()))

    # check-file-saved with too-large min_size
    data = run(sandbox, f"check-file-saved {TEST_FILE} 999999")
    check("check-file-saved saved=false (min too large)", data.get("saved") is False, str(data)[:100])

    # check-file-saved on nonexistent file
    data = run(sandbox, f"check-file-saved {NONEXISTENT_FILE} 0")
    check("check-file-saved nonexistent=false", data.get("saved") is False, str(data)[:100])


def test_gsettings_checks(sandbox: Sandbox):
    """Test gsettings-based check endpoints (may skip if schema not installed)."""
    print("\n=== gsettings Checks ===")

    # First read the actual tab-size to know what to test against
    data = run(sandbox, "setting tab-size")
    if "error" in data:
        print(f"  SKIP  gsettings not available: {data.get('error', '')[:80]}")
        return

    raw_value = data.get("value", "")
    try:
        actual_tab_size = int(raw_value.split()[-1])
    except (ValueError, IndexError):
        print(f"  SKIP  Could not parse tab-size: {raw_value}")
        return

    # Positive: check-tab-size with actual value
    data = run(sandbox, f"check-tab-size {actual_tab_size}")
    check("check-tab-size matches=true", data.get("matches") is True, str(data)[:100])

    # Negative: check-tab-size with wrong value
    wrong_size = actual_tab_size + 99
    data = run(sandbox, f"check-tab-size {wrong_size}")
    check("check-tab-size matches=false", data.get("matches") is False, str(data)[:100])

    # check-setting-value positive
    data = run(sandbox, f"check-setting-value 'org.gnome.gedit.preferences.editor tab-size' '{raw_value}'")
    check("check-setting-value matches=true", data.get("matches") is True, str(data)[:100])

    # check-setting-value negative
    data = run(sandbox, "check-setting-value 'org.gnome.gedit.preferences.editor tab-size' 'uint32 999'")
    check("check-setting-value matches=false", data.get("matches") is False, str(data)[:100])


def test_all_commands_return_json(sandbox: Sandbox):
    """Every CLI command should output valid JSON (not crash with a traceback)."""
    print("\n=== JSON validity (all commands) ===")

    # Commands that need no args
    no_arg_cmds = ["recent-files", "settings"]

    for cmd in no_arg_cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        check(f"{cmd} returns valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # Commands that need args (use test file or dummy values)
    arg_cmds = [
        ("file-content", TEST_FILE),
        ("file-info", TEST_FILE),
        ("file-encoding", TEST_FILE),
        ("file-line-count", TEST_FILE),
        ("file-word-count", TEST_FILE),
        ("setting", "tab-size"),
        ("check-file-exists", TEST_FILE),
        ("check-file-contains", f"{TEST_FILE} hello"),
        ("check-file-line", f"{TEST_FILE} 1 Hello"),
        ("check-file-line-count", f"{TEST_FILE} 3"),
        ("check-file-encoding", f"{TEST_FILE} utf-8"),
        ("check-file-saved", f"{TEST_FILE} 0"),
        ("check-tab-size", "4"),
        ("check-setting-value", f"'org.gnome.gedit.preferences.editor tab-size' 'uint32 4'"),
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
    print("Gedit Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # Create test files with known content
        print("Creating test files in sandbox...")
        sandbox.files.write(TEST_FILE, TEST_CONTENT)
        sandbox.files.write(TEST_FILE_MULTI, TEST_CONTENT_MULTI)

        # Verify test files were created
        r = sandbox.commands.run(f"cat {TEST_FILE}")
        print(f"  Test file content: {repr(r.stdout[:60])}")
        r = sandbox.commands.run(f"wc -l {TEST_FILE_MULTI}")
        print(f"  Multi-line file: {r.stdout.strip()}")

        # --- Run all test groups ---
        test_help(sandbox)
        test_errors_bad_args(sandbox)
        test_errors_nonexistent_files(sandbox)
        test_file_query_endpoints(sandbox)
        test_recent_files(sandbox)
        test_gsettings_endpoints(sandbox)
        test_checks_positive(sandbox)
        test_checks_negative(sandbox)
        test_gsettings_checks(sandbox)
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
