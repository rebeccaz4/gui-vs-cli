"""
Test PCManFM verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (unknown commands, missing args, nonexistent paths)
  - Filesystem query endpoints (list-directory, file-info, file-content, tree, disk-usage)
  - Config endpoints (get-config, get-config-key, get-sort-settings, get-view-mode)
  - Bookmark endpoints (get-bookmarks, check-bookmark-exists)
  - Recent files endpoints (get-recent-files, check-recent-file)
  - Process status (status)
  - Check endpoints — positive and negative cases
  - All commands return valid JSON

Usage:
    python verifiers/pcmanfm/test_pcmanfm.py
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

VERIFIER_LOCAL = Path(__file__).parent / "pcmanfm.py"
VERIFIER_REMOTE = "/home/user/verifiers/pcmanfm.py"
V = f"python3 {VERIFIER_REMOTE}"

# Test paths
TEST_DIR = "/home/user/test_pcmanfm"
TEST_FILE = f"{TEST_DIR}/file1.txt"
TEST_FILE2 = f"{TEST_DIR}/file2.txt"
HIDDEN_FILE = f"{TEST_DIR}/.hidden_file"
SCRIPT_FILE = f"{TEST_DIR}/script.sh"
READONLY_FILE = f"{TEST_DIR}/readonly.txt"
SUBDIR = f"{TEST_DIR}/subdir"
NESTED_FILE = f"{SUBDIR}/nested.txt"
DEEP_DIR = f"{SUBDIR}/deep"
BOTTOM_FILE = f"{DEEP_DIR}/bottom.txt"
IMAGES_DIR = f"{TEST_DIR}/images"
MIXED_DIR = f"{TEST_DIR}/mixed"
SYMLINK_FILE = f"{TEST_DIR}/link_to_file1.txt"
BROKEN_LINK = f"{TEST_DIR}/broken_link"
NONEXISTENT = "/home/user/test_pcmanfm/NONEXISTENT_xyz_12345"

# Test content
TEST_CONTENT = "Hello World\nTest content line 2\n"
TEST_CONTENT2 = "Another file for testing\n"

# Config
PCMANFM_CONF_DIR = "/home/user/.config/pcmanfm/default"
PCMANFM_CONF = f"{PCMANFM_CONF_DIR}/pcmanfm.conf"
GTK_BOOKMARKS_DIR = "/home/user/.config/gtk-3.0"
GTK_BOOKMARKS = f"{GTK_BOOKMARKS_DIR}/bookmarks"

PCMANFM_CONF_CONTENT = """[ui]
view_mode=list
show_hidden=0
sort_type=name
sort_order=ascending
sort_folder_first=1

[volume]
mount_on_startup=1
mount_removable=1
autorun=1
"""

GTK_BOOKMARKS_CONTENT = """file:///home/user/Documents Documents
file:///home/user/test_pcmanfm TestDir
file:///tmp Temp
"""

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


def shell(sandbox: Sandbox, cmd: str, timeout: int = 30) -> str:
    """Run a raw shell command (not the verifier)."""
    try:
        result = sandbox.commands.run(cmd, timeout=timeout)
        return result.stdout
    except CommandExitException as e:
        return e.stdout


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
# Fixture setup
# ---------------------------------------------------------------------------

def setup_fixtures(sandbox: Sandbox):
    """Create test files, config, and bookmarks in the sandbox."""
    print("Setting up test fixtures...")

    # Create test directory structure
    shell(sandbox, f"mkdir -p {TEST_DIR} {SUBDIR} {DEEP_DIR} {IMAGES_DIR} {MIXED_DIR}")

    # Create test files
    shell(sandbox, f"printf 'Hello World\\nTest content line 2\\n' > {TEST_FILE}")
    shell(sandbox, f"printf 'Another file for testing\\n' > {TEST_FILE2}")
    shell(sandbox, f"printf 'secret' > {HIDDEN_FILE}")
    shell(sandbox, f"printf '#!/bin/bash\\necho test\\n' > {SCRIPT_FILE}")
    shell(sandbox, f"chmod 755 {SCRIPT_FILE}")
    shell(sandbox, f"printf 'read only content' > {READONLY_FILE}")
    shell(sandbox, f"chmod 444 {READONLY_FILE}")
    shell(sandbox, f"printf 'nested file content' > {NESTED_FILE}")
    shell(sandbox, f"printf 'deepest file' > {BOTTOM_FILE}")

    # Create image files (uniform extension)
    for name in ("photo1.png", "photo2.png", "photo3.png"):
        shell(sandbox, f"touch {IMAGES_DIR}/{name}")

    # Create mixed extension files
    for name in ("doc.txt", "pic.png", "data.csv"):
        shell(sandbox, f"touch {MIXED_DIR}/{name}")

    # Create symlinks
    shell(sandbox, f"ln -sf file1.txt {SYMLINK_FILE}")
    shell(sandbox, f"ln -sf /nonexistent/path {BROKEN_LINK}")

    # Create PCManFM config
    shell(sandbox, f"mkdir -p {PCMANFM_CONF_DIR}")
    sandbox.files.write(PCMANFM_CONF, PCMANFM_CONF_CONTENT)

    # Create GTK bookmarks
    shell(sandbox, f"mkdir -p {GTK_BOOKMARKS_DIR}")
    sandbox.files.write(GTK_BOOKMARKS, GTK_BOOKMARKS_CONTENT)

    # Ensure Documents dir exists for bookmarks test
    shell(sandbox, "mkdir -p /home/user/Documents")

    print("Fixtures ready.\n")


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    """Group 1: --help should print usage and exit 0."""
    print("\n=== Group 1: Help / Usage ===")
    for flag in ("--help", "help", "-h"):
        result = run_raw(sandbox, flag)
        check(f"'{flag}' exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
        check(f"'{flag}' mentions Commands", "Commands:" in result.stdout, result.stdout[:100])

    # No args
    result = run_raw(sandbox, "")
    check("no args exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")


def test_errors_unknown_command(sandbox: Sandbox):
    """Group 2: Unknown subcommands return error JSON and exit 1."""
    print("\n=== Group 2: Error — Unknown Commands ===")

    result = run_raw(sandbox, "nonexistent-command-xyz")
    check("unknown cmd exits 1", result.exit_code == 1, f"got {result.exit_code}")
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])


def test_errors_missing_args(sandbox: Sandbox):
    """Group 3: Missing required arguments return error JSON and exit 1."""
    print("\n=== Group 3: Error — Missing Arguments ===")

    for cmd in ("check-file-exists", "check-permissions", "check-file-contains", "get-config-key"):
        result = run_raw(sandbox, cmd)
        check(f"'{cmd}' no args exits 1", result.exit_code == 1, f"got {result.exit_code}")
        check(f"'{cmd}' no args valid JSON", is_valid_json(result.stdout), result.stdout[:100])


def test_filesystem_queries(sandbox: Sandbox):
    """Group 4: Filesystem query endpoints."""
    print("\n=== Group 4: Filesystem Query Endpoints ===")

    # list-directory — valid dir
    data = run(sandbox, f"list-directory {TEST_DIR}")
    check("list-dir has entries", "entries" in data, str(data.keys()))
    # Should have: file1.txt, file2.txt, script.sh, readonly.txt, subdir, images, mixed, link_to_file1.txt, broken_link
    # (hidden files excluded by default)
    count = data.get("count", 0)
    check("list-dir count >= 7", count >= 7, f"got count={count}")

    # list-directory with --hidden
    data = run(sandbox, f"list-directory {TEST_DIR} --hidden")
    count_hidden = data.get("count", 0)
    check("list-dir --hidden has more entries", count_hidden > count,
          f"hidden={count_hidden} vs normal={count}")

    # list-directory — nonexistent
    data = run(sandbox, f"list-directory {NONEXISTENT}")
    check("list-dir nonexistent has error", "error" in data, str(data)[:100])

    # list-directory — on a file
    data = run(sandbox, f"list-directory {TEST_FILE}")
    check("list-dir on file has error", "error" in data, str(data)[:100])

    # file-info — file
    data = run(sandbox, f"file-info {TEST_FILE}")
    check("file-info has type", data.get("type") == "file", f"type={data.get('type')}")
    check("file-info has size", isinstance(data.get("size"), int), str(data.get("size")))
    check("file-info has permissions", "permissions" in data, str(data.keys()))

    # file-info — directory
    data = run(sandbox, f"file-info {SUBDIR}")
    check("file-info dir type", data.get("type") == "directory", f"type={data.get('type')}")

    # file-info — symlink
    data = run(sandbox, f"file-info {SYMLINK_FILE}")
    check("file-info symlink type", data.get("type") == "symlink", f"type={data.get('type')}")
    check("file-info symlink has target", "link_target" in data, str(data.keys()))

    # file-info — nonexistent
    data = run(sandbox, f"file-info {NONEXISTENT}")
    check("file-info nonexistent has error", "error" in data, str(data)[:100])

    # file-content — valid
    data = run(sandbox, f"file-content {TEST_FILE}")
    check("file-content has content", "content" in data, str(data.keys()))
    check("file-content matches", data.get("content") == TEST_CONTENT,
          f"got: {repr(data.get('content', '')[:80])}")

    # file-content — nonexistent
    data = run(sandbox, f"file-content {NONEXISTENT}")
    check("file-content nonexistent has error", "error" in data, str(data)[:100])

    # file-content — on directory
    data = run(sandbox, f"file-content {TEST_DIR}")
    check("file-content on dir has error", "error" in data, str(data)[:100])

    # tree
    data = run(sandbox, f"tree {TEST_DIR}")
    check("tree has tree key", "tree" in data, str(data.keys()))
    tree = data.get("tree", {})
    check("tree has children", "children" in tree, str(tree.keys()))

    # tree — nonexistent
    data = run(sandbox, f"tree {NONEXISTENT}")
    check("tree nonexistent has error", "error" in data, str(data)[:100])

    # disk-usage
    data = run(sandbox, f"disk-usage {TEST_DIR}")
    check("disk-usage has size_bytes", isinstance(data.get("size_bytes"), int), str(data))
    check("disk-usage > 0", data.get("size_bytes", 0) > 0, str(data.get("size_bytes")))

    # disk-usage — nonexistent
    data = run(sandbox, f"disk-usage {NONEXISTENT}")
    check("disk-usage nonexistent has error", "error" in data, str(data)[:100])


def test_config_endpoints(sandbox: Sandbox):
    """Group 5: Config endpoints."""
    print("\n=== Group 5: Config Endpoints ===")

    # get-config
    data = run(sandbox, "get-config")
    check("get-config has sections", "sections" in data, str(data.keys()))
    sections = data.get("sections", {})
    check("get-config has ui section", "ui" in sections, str(sections.keys()))

    # get-config-key — valid
    data = run(sandbox, "get-config-key ui view_mode")
    check("get-config-key returns value", data.get("value") == "list",
          f"got value={data.get('value')}")

    # get-config-key — bad section
    data = run(sandbox, "get-config-key nonexistent_section key")
    check("get-config-key bad section has error", "error" in data, str(data)[:100])

    # get-config-key — bad key
    data = run(sandbox, "get-config-key ui nonexistent_key_xyz")
    check("get-config-key bad key has error", "error" in data, str(data)[:100])

    # get-sort-settings
    data = run(sandbox, "get-sort-settings")
    check("sort has sort_by", "sort_by" in data, str(data.keys()))
    check("sort has sort_order", "sort_order" in data, str(data.keys()))

    # get-view-mode
    data = run(sandbox, "get-view-mode")
    check("view_mode present", "view_mode" in data, str(data.keys()))


def test_bookmark_endpoints(sandbox: Sandbox):
    """Group 6: Bookmark endpoints."""
    print("\n=== Group 6: Bookmark Endpoints ===")

    # get-bookmarks
    data = run(sandbox, "get-bookmarks")
    check("get-bookmarks has count", "count" in data, str(data.keys()))
    check("get-bookmarks count > 0", data.get("count", 0) > 0, f"count={data.get('count')}")
    bookmarks = data.get("bookmarks", [])
    check("get-bookmarks has bookmarks list", isinstance(bookmarks, list) and len(bookmarks) > 0,
          str(len(bookmarks)))

    # Check bookmark with label
    has_label = any(b.get("label") is not None for b in bookmarks)
    check("bookmarks have labels", has_label, str([b.get("label") for b in bookmarks[:5]]))


def test_recent_files(sandbox: Sandbox):
    """Group 7: Recent files endpoints."""
    print("\n=== Group 7: Recent Files Endpoints ===")

    # get-recent-files (may be empty, just check structure)
    data = run(sandbox, "get-recent-files")
    check("get-recent-files has count", "count" in data, str(data.keys()))
    check("get-recent-files has files", "files" in data, str(data.keys()))

    # check-recent-file — negative (random string)
    data = run(sandbox, "check-recent-file NONEXISTENT_RANDOM_STRING_12345")
    check("check-recent-file negative", data.get("found") is False, str(data)[:100])

    # get-recent-files with limit
    data = run(sandbox, "get-recent-files 5")
    check("get-recent-files limit returns list", "files" in data, str(data.keys()))


def test_process_status(sandbox: Sandbox):
    """Group 8: Process status."""
    print("\n=== Group 8: Process Status ===")

    # Status when not running (kill any existing instance first)
    shell(sandbox, "killall pcmanfm 2>/dev/null || true")
    time.sleep(1)
    data = run(sandbox, "status")
    check("status not running", data.get("running") is False, str(data)[:100])

    # Start PCManFM and check status
    sandbox.commands.run("pcmanfm /home/user", background=True)
    time.sleep(3)
    data = run(sandbox, "status")
    check("status running", data.get("running") is True, str(data)[:100])

    # Clean up
    try:
        sandbox.commands.run("killall pcmanfm", timeout=5)
    except Exception:
        pass
    time.sleep(1)


def test_check_positive(sandbox: Sandbox):
    """Group 9: Check endpoints — positive cases."""
    print("\n=== Group 9: Check Endpoints — Positive ===")

    # check-file-exists
    data = run(sandbox, f"check-file-exists {TEST_FILE}")
    check("check-file-exists pos", data.get("exists") is True, str(data)[:100])

    # check-dir-exists
    data = run(sandbox, f"check-dir-exists {SUBDIR}")
    check("check-dir-exists pos", data.get("exists") is True and data.get("is_directory") is True,
          str(data)[:100])

    # check-file-contains
    data = run(sandbox, f'check-file-contains {TEST_FILE} "Hello World"')
    check("check-file-contains pos", data.get("contains") is True, str(data)[:100])

    # check-permissions (script.sh should be 755)
    data = run(sandbox, f"check-permissions {SCRIPT_FILE} 755")
    check("check-permissions pos", data.get("match") is True, str(data)[:100])

    # check-symlink
    data = run(sandbox, f"check-symlink {SYMLINK_FILE}")
    check("check-symlink pos", data.get("is_symlink") is True, str(data)[:100])

    # check-symlink with correct target
    data = run(sandbox, f"check-symlink {SYMLINK_FILE} file1.txt")
    check("check-symlink target pos", data.get("is_symlink") is True and data.get("target_matches") is True,
          str(data)[:150])

    # check-owner
    data = run(sandbox, f"check-owner {TEST_FILE} user")
    check("check-owner pos", data.get("match") is True, str(data)[:100])

    # check-file-count (images dir has 3 files)
    data = run(sandbox, f"check-file-count {IMAGES_DIR} 3")
    check("check-file-count pos", data.get("match") is True,
          f"expected=3, actual={data.get('actual')}")

    # check-extension-match (images dir all .png)
    data = run(sandbox, f"check-extension-match {IMAGES_DIR} .png")
    check("check-extension-match pos", data.get("all_match") is True, str(data)[:100])

    # check-bookmark-exists
    data = run(sandbox, "check-bookmark-exists /home/user/Documents")
    check("check-bookmark-exists pos", data.get("exists") is True, str(data)[:100])

    # check-config-value
    data = run(sandbox, "check-config-value ui view_mode list")
    check("check-config-value pos", data.get("match") is True, str(data)[:100])


def test_check_negative(sandbox: Sandbox):
    """Group 10: Check endpoints — negative cases."""
    print("\n=== Group 10: Check Endpoints — Negative ===")

    # check-file-exists — nonexistent
    data = run(sandbox, f"check-file-exists {NONEXISTENT}")
    check("check-file-exists neg", data.get("exists") is False, str(data)[:100])

    # check-dir-exists — file is not a dir
    data = run(sandbox, f"check-dir-exists {TEST_FILE}")
    check("check-dir-exists neg (is file)", data.get("is_directory") is False, str(data)[:100])

    # check-file-contains — text not in file
    data = run(sandbox, f'check-file-contains {TEST_FILE} "NONEXISTENT_STRING_xyz_99999"')
    check("check-file-contains neg", data.get("contains") is False, str(data)[:100])

    # check-permissions — wrong permissions
    data = run(sandbox, f"check-permissions {SCRIPT_FILE} 644")
    check("check-permissions neg", data.get("match") is False, str(data)[:100])

    # check-symlink — regular file
    data = run(sandbox, f"check-symlink {TEST_FILE}")
    check("check-symlink neg (regular file)", data.get("is_symlink") is False, str(data)[:100])

    # check-symlink — wrong target
    data = run(sandbox, f"check-symlink {SYMLINK_FILE} /wrong/target")
    check("check-symlink target neg", data.get("target_matches") is False, str(data)[:150])

    # check-owner — wrong owner
    data = run(sandbox, f"check-owner {TEST_FILE} root")
    check("check-owner neg", data.get("match") is False, str(data)[:100])

    # check-file-count — wrong count
    data = run(sandbox, f"check-file-count {IMAGES_DIR} 99")
    check("check-file-count neg", data.get("match") is False,
          f"expected=99, actual={data.get('actual')}")

    # check-extension-match — mixed dir
    data = run(sandbox, f"check-extension-match {MIXED_DIR} .png")
    check("check-extension-match neg", data.get("all_match") is False, str(data)[:100])

    # check-bookmark-exists — not bookmarked
    data = run(sandbox, "check-bookmark-exists /nonexistent/bookmark/dir")
    check("check-bookmark-exists neg", data.get("exists") is False, str(data)[:100])

    # check-config-value — wrong value
    data = run(sandbox, "check-config-value ui view_mode icon")
    check("check-config-value neg", data.get("match") is False, str(data)[:100])


def test_json_validity(sandbox: Sandbox):
    """Group 11: All CLI subcommands produce valid JSON."""
    print("\n=== Group 11: JSON Validity Sweep ===")

    cmds = [
        f"list-directory {TEST_DIR}",
        f"list-directory {TEST_DIR} --hidden",
        f"file-info {TEST_FILE}",
        f"file-content {TEST_FILE}",
        f"tree {TEST_DIR}",
        f"disk-usage {TEST_DIR}",
        "get-config",
        "get-config-key ui view_mode",
        "get-sort-settings",
        "get-view-mode",
        "get-bookmarks",
        "get-recent-files",
        "status",
        f"check-file-exists {TEST_FILE}",
        f"check-dir-exists {SUBDIR}",
        f'check-file-contains {TEST_FILE} "Hello"',
        f"check-permissions {TEST_FILE} 644",
        f"check-symlink {SYMLINK_FILE}",
        f"check-owner {TEST_FILE} user",
        "check-bookmark-exists /home/user/Documents",
        "check-recent-file test",
        f"check-file-count {IMAGES_DIR} 3",
        f"check-extension-match {IMAGES_DIR} .png",
        "check-config-value ui view_mode list",
    ]

    for cmd in cmds:
        result = run_raw(sandbox, cmd)
        label = cmd.split()[0]  # Use just the command name
        check(f"JSON valid: {label}", is_valid_json(result.stdout),
              f"stdout={result.stdout[:80]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("PCManFM Verifier — E2B Sandbox Tests")
    print("=" * 60)

    # Read verifier source
    verifier_code = VERIFIER_LOCAL.read_text()

    # Create sandbox
    print("\nCreating E2B sandbox...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)
    print(f"Sandbox created: {sandbox.sandbox_id}")

    try:
        # Upload verifier
        shell(sandbox, "mkdir -p /home/user/verifiers")
        sandbox.files.write(VERIFIER_REMOTE, verifier_code)
        print("Verifier uploaded.")

        # Setup fixtures
        setup_fixtures(sandbox)

        # Run all test groups
        test_help(sandbox)
        test_errors_unknown_command(sandbox)
        test_errors_missing_args(sandbox)
        test_filesystem_queries(sandbox)
        test_config_endpoints(sandbox)
        test_bookmark_endpoints(sandbox)
        test_recent_files(sandbox)
        test_process_status(sandbox)
        test_check_positive(sandbox)
        test_check_negative(sandbox)
        test_json_validity(sandbox)

    except Exception:
        print(f"\nFATAL ERROR:\n{traceback.format_exc()}")
    finally:
        sandbox.kill()
        print(f"\nSandbox {sandbox.sandbox_id} killed.")

    # Summary
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
