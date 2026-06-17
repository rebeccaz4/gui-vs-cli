"""
Test VS Code verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (VS Code not configured, bad args)
  - JSON config endpoints (settings, keybindings)
  - Extensions listing
  - Workspace endpoints (settings, tasks, launch, extensions.json)
  - SQLite state DB endpoints (recent-files, global-state)
  - Composite check-* endpoints (positive and negative cases)

Setup:
  Creates mock VS Code config files, workspace with .vscode/, and
  extensions directory with mock extensions inside the sandbox.

Usage:
    python verifiers/vscode/test_vscode.py
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

VERIFIER_LOCAL = Path(__file__).parent / "vscode.py"
VERIFIER_REMOTE = "/home/user/verifiers/vscode.py"
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
# Sandbox setup: create mock VS Code files
# ---------------------------------------------------------------------------

MOCK_SETTINGS = json.dumps({
    "editor.fontSize": 14,
    "editor.tabSize": 2,
    "editor.wordWrap": "on",
    "workbench.colorTheme": "Default Dark+",
    "python.defaultInterpreterPath": "/usr/bin/python3",
    "files.autoSave": "afterDelay",
}, indent=2)

MOCK_KEYBINDINGS = json.dumps([
    {"key": "ctrl+shift+p", "command": "workbench.action.showCommands"},
    {"key": "ctrl+b", "command": "workbench.action.toggleSidebarVisibility"},
    {"key": "ctrl+`", "command": "workbench.action.terminal.toggleTerminal"},
    {"key": "ctrl+shift+f", "command": "workbench.action.findInFiles"},
], indent=2)

MOCK_EXT_PACKAGE_JSON_PYTHON = json.dumps({
    "publisher": "ms-python",
    "name": "python",
    "displayName": "Python",
    "version": "2024.1.0",
    "description": "IntelliSense, linting, debugging for Python",
}, indent=2)

MOCK_EXT_PACKAGE_JSON_PRETTIER = json.dumps({
    "publisher": "esbenp",
    "name": "prettier-vscode",
    "displayName": "Prettier - Code formatter",
    "version": "10.4.0",
    "description": "Code formatter using prettier",
}, indent=2)

MOCK_WORKSPACE_SETTINGS = json.dumps({
    "python.defaultInterpreterPath": "/home/user/venv/bin/python",
    "editor.formatOnSave": True,
}, indent=2)

MOCK_WORKSPACE_TASKS = json.dumps({
    "version": "2.0.0",
    "tasks": [
        {
            "label": "build",
            "type": "shell",
            "command": "make build",
            "group": "build",
        },
        {
            "label": "test",
            "type": "shell",
            "command": "pytest",
            "group": "test",
        },
    ],
}, indent=2)

MOCK_WORKSPACE_LAUNCH = json.dumps({
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: Current File",
            "type": "python",
            "request": "launch",
            "program": "${file}",
        },
        {
            "name": "Node: Debug",
            "type": "node",
            "request": "launch",
            "program": "${workspaceFolder}/index.js",
        },
    ],
}, indent=2)

MOCK_WORKSPACE_EXTENSIONS = json.dumps({
    "recommendations": [
        "ms-python.python",
        "esbenp.prettier-vscode",
    ],
}, indent=2)


def setup_mock_files(sandbox: Sandbox):
    """Create mock VS Code config, extensions, and workspace in the sandbox."""
    print("Setting up mock VS Code files...")

    config_dir = "/home/user/.config/Code/User"
    ext_dir = "/home/user/.vscode/extensions"
    workspace = "/home/user/test-project"

    # Config dir
    sandbox.commands.run(f"mkdir -p {config_dir}/globalStorage")
    sandbox.files.write(f"{config_dir}/settings.json", MOCK_SETTINGS)
    sandbox.files.write(f"{config_dir}/keybindings.json", MOCK_KEYBINDINGS)

    # Extensions directory with mock extensions
    sandbox.commands.run(f"mkdir -p {ext_dir}/ms-python.python-2024.1.0")
    sandbox.commands.run(f"mkdir -p {ext_dir}/esbenp.prettier-vscode-10.4.0")
    sandbox.files.write(
        f"{ext_dir}/ms-python.python-2024.1.0/package.json",
        MOCK_EXT_PACKAGE_JSON_PYTHON,
    )
    sandbox.files.write(
        f"{ext_dir}/esbenp.prettier-vscode-10.4.0/package.json",
        MOCK_EXT_PACKAGE_JSON_PRETTIER,
    )

    # Workspace with .vscode/
    sandbox.commands.run(f"mkdir -p {workspace}/.vscode")
    sandbox.commands.run(f"mkdir -p {workspace}/src")
    sandbox.files.write(f"{workspace}/.vscode/settings.json", MOCK_WORKSPACE_SETTINGS)
    sandbox.files.write(f"{workspace}/.vscode/tasks.json", MOCK_WORKSPACE_TASKS)
    sandbox.files.write(f"{workspace}/.vscode/launch.json", MOCK_WORKSPACE_LAUNCH)
    sandbox.files.write(f"{workspace}/.vscode/extensions.json", MOCK_WORKSPACE_EXTENSIONS)
    sandbox.files.write(f"{workspace}/src/main.py", 'print("hello")\n')
    sandbox.files.write(f"{workspace}/README.md", "# Test Project\n")

    # Create state.vscdb with some mock data
    sandbox.commands.run(
        f"python3 -c \"\n"
        f"import sqlite3, json\n"
        f"conn = sqlite3.connect('{config_dir}/globalStorage/state.vscdb')\n"
        f"conn.execute('CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)')\n"
        f"conn.execute('INSERT OR REPLACE INTO ItemTable VALUES (?, ?)', "
        f"('history.recentlyOpenedPathsList', json.dumps({{'entries2': [{{'folderUri': 'file:///home/user/test-project'}}, {{'fileUri': 'file:///home/user/test-project/src/main.py'}}]}}))"
        f")\n"
        f"conn.execute('INSERT OR REPLACE INTO ItemTable VALUES (?, ?)', "
        f"('workbench.colorTheme', '\\\"Default Dark+\\\"'))\n"
        f"conn.commit()\n"
        f"conn.close()\n"
        f"\"",
        timeout=10,
    )

    print("  Mock files created.")


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    """--help should print usage and exit 0."""
    print("\n=== Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
    check("help mentions commands", "Commands:" in result.stdout, result.stdout[:100])
    check("help mentions VS Code", "VS Code" in result.stdout, result.stdout[:100])


def test_errors_bad_args(sandbox: Sandbox):
    """Missing/invalid arguments should return error JSON, not crash."""
    print("\n=== Errors (bad args) ===")

    # Missing required arg
    result = run_raw(sandbox, "check-setting")
    check("missing arg exits 1", result.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    result = run_raw(sandbox, "workspace-settings")
    check("missing workspace arg exits 1", result.exit_code == 1)
    check("missing workspace arg JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Unknown command
    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])


def test_settings(sandbox: Sandbox):
    """Test settings query endpoint."""
    print("\n=== Settings ===")

    # All settings
    data = run(sandbox, "settings")
    check("settings returns dict", isinstance(data, dict), str(type(data)))
    check("settings has editor.fontSize", "editor.fontSize" in data, str(data)[:100])
    check("settings fontSize is 14", data.get("editor.fontSize") == 14, str(data.get("editor.fontSize")))

    # Specific key
    data = run(sandbox, "settings editor.fontSize")
    check("settings key returns dict", isinstance(data, dict))
    check("settings key has value", "value" in data, str(data)[:100])
    check("settings key value is 14", data.get("value") == 14, str(data.get("value")))

    # Non-existent key
    data = run(sandbox, "settings nonexistent.key.12345")
    check("missing key returns error", "error" in data, str(data)[:100])


def test_keybindings(sandbox: Sandbox):
    """Test keybindings query endpoint."""
    print("\n=== Keybindings ===")

    data = run(sandbox, "keybindings")
    check("keybindings returns list", isinstance(data, list), str(type(data)))
    check("keybindings has entries", len(data) > 0, f"got {len(data)}")
    if data:
        check("binding has key", "key" in data[0], str(data[0]))
        check("binding has command", "command" in data[0], str(data[0]))


def test_extensions(sandbox: Sandbox):
    """Test extensions listing."""
    print("\n=== Extensions ===")

    data = run(sandbox, "extensions")
    check("extensions returns list", isinstance(data, list), str(type(data)))
    check("extensions has entries", len(data) >= 2, f"got {len(data)}")

    # Check for our mock extensions
    ext_ids = [e.get("id", "") for e in data if isinstance(e, dict)]
    check("has ms-python.python", "ms-python.python" in ext_ids, str(ext_ids))
    check("has esbenp.prettier-vscode", "esbenp.prettier-vscode" in ext_ids, str(ext_ids))


def test_workspace_endpoints(sandbox: Sandbox):
    """Test workspace .vscode/ file reading."""
    print("\n=== Workspace Endpoints ===")

    ws = "/home/user/test-project"

    # workspace-settings
    data = run(sandbox, f"workspace-settings {ws}")
    check("ws settings returns dict", isinstance(data, dict), str(type(data)))
    check("ws settings has formatOnSave", data.get("editor.formatOnSave") is True, str(data)[:100])

    # workspace-tasks
    data = run(sandbox, f"workspace-tasks {ws}")
    check("ws tasks returns dict", isinstance(data, dict))
    check("ws tasks has tasks key", "tasks" in data, str(data.keys()))
    check("ws tasks has 2 tasks", len(data.get("tasks", [])) == 2, str(data)[:100])

    # workspace-launch
    data = run(sandbox, f"workspace-launch {ws}")
    check("ws launch returns dict", isinstance(data, dict))
    check("ws launch has configurations", "configurations" in data, str(data.keys()))
    check("ws launch has 2 configs", len(data.get("configurations", [])) == 2, str(data)[:100])

    # workspace-extensions
    data = run(sandbox, f"workspace-extensions {ws}")
    check("ws extensions returns dict", isinstance(data, dict))
    check("ws extensions has recommendations", "recommendations" in data, str(data.keys()))

    # Non-existent workspace
    data = run(sandbox, "workspace-settings /nonexistent/path")
    check("missing ws returns error", "error" in data, str(data)[:100])


def test_state_db(sandbox: Sandbox):
    """Test SQLite state.vscdb endpoints."""
    print("\n=== State DB ===")

    # recent-files
    data = run(sandbox, "recent-files")
    check("recent-files returns list", isinstance(data, list), str(type(data)))
    if data and "error" not in data[0]:
        check("recent-files has entries", len(data) > 0, f"got {len(data)}")

    # global-state (list all keys)
    data = run(sandbox, "global-state")
    check("global-state list returns list", isinstance(data, list), str(type(data)))
    if data and "error" not in data[0]:
        check("global-state has keys", len(data) > 0, f"got {len(data)}")

    # global-state with specific key
    data = run(sandbox, "global-state workbench.colorTheme")
    check("global-state key returns dict", isinstance(data, dict), str(type(data)))
    check("global-state has value", "value" in data or "error" in data, str(data)[:100])

    # global-state missing key
    data = run(sandbox, "global-state nonexistent.key.12345")
    check("missing state key returns error", "error" in data, str(data)[:100])


def test_checks_positive(sandbox: Sandbox):
    """Composite check-* endpoints -- positive cases."""
    print("\n=== Checks (positive) ===")

    ws = "/home/user/test-project"

    # check-file-exists
    data = run(sandbox, "check-file-exists /home/user/.config/Code/User/settings.json")
    check("check-file-exists exists=true", data.get("exists") is True, str(data)[:100])

    # check-setting
    data = run(sandbox, "check-setting editor.fontSize 14")
    check("check-setting match=true", data.get("match") is True, str(data)[:100])
    check("check-setting actual=14", data.get("actual") == 14, str(data.get("actual")))

    data = run(sandbox, 'check-setting editor.wordWrap \'"on"\'')
    check("check-setting string match", data.get("match") is True, str(data)[:100])

    # check-extension-installed
    data = run(sandbox, "check-extension-installed ms-python.python")
    check("check-ext installed=true", data.get("installed") is True, str(data)[:100])
    check("check-ext has extension", "extension" in data, str(data.keys()))

    # check-keybinding-exists
    data = run(sandbox, "check-keybinding-exists ctrl+shift+p")
    check("check-keybinding exists=true", data.get("exists") is True, str(data)[:100])
    check("check-keybinding has binding", "binding" in data, str(data.keys()))

    # check-workspace-setting
    data = run(sandbox, f"check-workspace-setting {ws} editor.formatOnSave true")
    check("check-ws-setting match=true", data.get("match") is True, str(data)[:100])

    # check-workspace-has-file
    data = run(sandbox, f"check-workspace-has-file {ws} src/main.py")
    check("check-ws-has-file exists=true", data.get("exists") is True, str(data)[:100])

    data = run(sandbox, f"check-workspace-has-file {ws} README.md")
    check("check-ws-has-file README exists", data.get("exists") is True, str(data)[:100])

    # check-tasks-defined
    data = run(sandbox, f"check-tasks-defined {ws}")
    check("check-tasks defined=true", data.get("defined") is True, str(data)[:100])
    check("check-tasks count=2", data.get("task_count") == 2, str(data.get("task_count")))

    # check-launch-config-exists
    data = run(sandbox, f'check-launch-config-exists {ws} "Python: Current File"')
    check("check-launch exists=true", data.get("exists") is True, str(data)[:100])
    check("check-launch has config", "config" in data, str(data.keys()))


def test_checks_negative(sandbox: Sandbox):
    """Composite check-* endpoints -- negative cases."""
    print("\n=== Checks (negative) ===")

    ws = "/home/user/test-project"

    # check-file-exists for non-existent file
    data = run(sandbox, "check-file-exists /nonexistent/file.txt")
    check("check-file-exists exists=false", data.get("exists") is False, str(data)[:100])

    # check-setting wrong value
    data = run(sandbox, "check-setting editor.fontSize 16")
    check("check-setting match=false", data.get("match") is False, str(data)[:100])
    check("check-setting shows actual", "actual" in data, str(data)[:100])

    # check-extension-installed for missing ext
    data = run(sandbox, "check-extension-installed nonexistent.extension.12345")
    check("check-ext installed=false", data.get("installed") is False, str(data)[:100])

    # check-keybinding-exists for missing binding
    data = run(sandbox, "check-keybinding-exists ctrl+alt+shift+z")
    check("check-keybinding exists=false", data.get("exists") is False, str(data)[:100])

    # check-workspace-setting wrong value
    data = run(sandbox, f"check-workspace-setting {ws} editor.formatOnSave false")
    check("check-ws-setting match=false", data.get("match") is False, str(data)[:100])

    # check-workspace-has-file missing file
    data = run(sandbox, f"check-workspace-has-file {ws} nonexistent/file.txt")
    check("check-ws-has-file exists=false", data.get("exists") is False, str(data)[:100])

    # check-tasks-defined on workspace without tasks
    data = run(sandbox, "check-tasks-defined /home/user")
    check("check-tasks no tasks", data.get("defined") is False or "error" in data, str(data)[:100])

    # check-launch-config-exists for missing config
    data = run(sandbox, f'check-launch-config-exists {ws} "Nonexistent Config 12345"')
    check("check-launch exists=false", data.get("exists") is False, str(data)[:100])
    check("check-launch shows available", "available_configs" in data, str(data.keys()))


def test_all_commands_return_json(sandbox: Sandbox):
    """Every CLI command should output valid JSON (not crash with a traceback)."""
    print("\n=== JSON validity (all commands) ===")

    ws = "/home/user/test-project"

    # Commands that need no args
    no_arg_cmds = ["settings", "keybindings", "extensions", "recent-files", "global-state"]

    for cmd in no_arg_cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        check(f"{cmd} returns valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # Commands that need args
    arg_cmds = [
        ("settings", "editor.fontSize"),
        ("workspace-settings", ws),
        ("workspace-extensions", ws),
        ("workspace-tasks", ws),
        ("workspace-launch", ws),
        ("global-state", "workbench.colorTheme"),
        ("check-file-exists", "/home/user/.config/Code/User/settings.json"),
        ("check-setting", "editor.fontSize 14"),
        ("check-extension-installed", "ms-python.python"),
        ("check-keybinding-exists", "ctrl+b"),
        ("check-workspace-setting", f"{ws} editor.formatOnSave true"),
        ("check-workspace-has-file", f"{ws} src/main.py"),
        ("check-tasks-defined", ws),
        ("check-launch-config-exists", f'{ws} "Python: Current File"'),
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
    print("VS Code Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # Set up mock VS Code files
        setup_mock_files(sandbox)

        # --- Run tests ---
        test_help(sandbox)
        test_errors_bad_args(sandbox)
        test_settings(sandbox)
        test_keybindings(sandbox)
        test_extensions(sandbox)
        test_workspace_endpoints(sandbox)
        test_state_db(sandbox)
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
