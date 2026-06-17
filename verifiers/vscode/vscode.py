"""
VS Code Verifier — programmatic state inspection for Visual Studio Code in E2B sandbox.

Verification channels (in order of preference):
  1. JSON config files — settings.json, keybindings.json
  2. SQLite state DB — state.vscdb (global state, recent files)
  3. CLI commands — code --list-extensions, etc.
  4. File system — extensions directory, workspace .vscode/

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/vscode.py settings")
    sandbox.commands.run("python3 /home/user/verifiers/vscode.py extensions")
    sandbox.commands.run("python3 /home/user/verifiers/vscode.py check-setting editor.fontSize 14")

Usage from Python (inside sandbox or via E2B):
    from verifiers.vscode import VSCodeVerifier
    v = VSCodeVerifier()
    settings = v.get_settings()
    exts = v.get_extensions()

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - VS Code installed with `code` on PATH
  - sqlite3 (standard library)
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VSCODE_CONFIG_DIR = Path.home() / ".config" / "Code" / "User"
VSCODE_EXTENSIONS_DIR = Path.home() / ".vscode" / "extensions"

SETTINGS_PATH = VSCODE_CONFIG_DIR / "settings.json"
KEYBINDINGS_PATH = VSCODE_CONFIG_DIR / "keybindings.json"
STATE_DB_PATH = VSCODE_CONFIG_DIR / "globalStorage" / "state.vscdb"


def _find_config_dir() -> Path | None:
    """Find the VS Code config directory."""
    env_dir = os.environ.get("VSCODE_CONFIG_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.exists():
            return p

    candidates = [
        Path.home() / ".config" / "Code" / "User",
        Path.home() / ".config" / "Code - OSS" / "User",
        Path.home() / ".config" / "Code - Insiders" / "User",
    ]
    for d in candidates:
        if d.exists():
            return d
    return None


def _find_extensions_dir() -> Path | None:
    """Find the VS Code extensions directory."""
    env_dir = os.environ.get("VSCODE_EXTENSIONS_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.exists():
            return p

    candidates = [
        Path.home() / ".vscode" / "extensions",
        Path.home() / ".vscode-oss" / "extensions",
        Path.home() / ".vscode-insiders" / "extensions",
    ]
    for d in candidates:
        if d.exists():
            return d
    return None


# ---------------------------------------------------------------------------
# JSON file helpers
# ---------------------------------------------------------------------------

def _read_json_file(path: Path) -> dict | list:
    """Read and parse a JSON file, returning error dict on failure."""
    if not path.exists():
        return {"error": f"File not found: {path}"}
    try:
        with open(path) as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON in {path}: {e}"}
    except OSError as e:
        return {"error": f"Cannot read {path}: {e}"}


def _navigate_key(data: dict, key_path: str) -> Any:
    """Navigate a dotted key path in a nested dict. Returns the value or error dict."""
    obj = data
    for part in key_path.split("."):
        if isinstance(obj, dict):
            if part in obj:
                obj = obj[part]
            else:
                return {"error": f"Key '{key_path}' not found (no '{part}')"}
        else:
            return {"error": f"Key '{key_path}' not found ('{part}' parent is not a dict)"}
    return obj


# ---------------------------------------------------------------------------
# SQLite helpers (copy-before-read to avoid locking)
# ---------------------------------------------------------------------------

def _query_state_db(query: str, params: tuple = ()) -> list[dict]:
    """Query state.vscdb safely by copying it first."""
    config_dir = _find_config_dir()
    if not config_dir:
        return [{"error": "VS Code config directory not found"}]

    db_path = config_dir / "globalStorage" / "state.vscdb"
    if not db_path.exists():
        return [{"error": f"state.vscdb not found at {db_path}"}]

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        shutil.copy2(db_path, tmp.name)
        for ext in ("-wal", "-shm"):
            wal = Path(str(db_path) + ext)
            if wal.exists():
                shutil.copy2(wal, tmp.name + ext)

        conn = sqlite3.connect(tmp.name)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except sqlite3.Error as e:
        return [{"error": f"SQLite error: {e}"}]
    finally:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _run_code_cli(args: list[str], timeout: float = 15.0) -> dict:
    """Run a `code` CLI command and return stdout/stderr."""
    try:
        result = subprocess.run(
            ["code"] + args,
            capture_output=True, text=True, timeout=timeout
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except FileNotFoundError:
        return {"error": "'code' command not found. Is VS Code installed and on PATH?"}
    except subprocess.TimeoutExpired:
        return {"error": f"'code {' '.join(args)}' timed out after {timeout}s"}


# ---------------------------------------------------------------------------
# VSCodeVerifier class
# ---------------------------------------------------------------------------

class VSCodeVerifier:
    """Stateless verifier -- each method call is independent."""

    # === JSON config files ===

    def get_settings(self, key: str | None = None) -> Any:
        """Read user settings.json. Optionally extract a specific key.

        Example:
            v.get_settings()
            => {"editor.fontSize": 14, "editor.tabSize": 2, ...}

            v.get_settings("editor.fontSize")
            => 14
        """
        config_dir = _find_config_dir()
        settings_path = (config_dir / "settings.json") if config_dir else SETTINGS_PATH

        data = _read_json_file(settings_path)
        if isinstance(data, dict) and "error" in data:
            return data

        if key is None:
            return data

        # VS Code settings use dotted keys at the top level, e.g. "editor.fontSize"
        # Try exact match first, then navigate nested
        if key in data:
            return {"key": key, "value": data[key]}
        # Try nested navigation
        result = _navigate_key(data, key)
        if isinstance(result, dict) and "error" in result:
            return result
        return {"key": key, "value": result}

    def get_keybindings(self) -> list | dict:
        """Read keybindings.json.

        Example:
            v.get_keybindings()
            => [{"key": "ctrl+shift+p", "command": "workbench.action.showCommands"}, ...]
        """
        config_dir = _find_config_dir()
        kb_path = (config_dir / "keybindings.json") if config_dir else KEYBINDINGS_PATH
        return _read_json_file(kb_path)

    # === Extensions ===

    def get_extensions(self) -> list[dict]:
        """List installed extensions by scanning the extensions directory.

        Falls back to `code --list-extensions` if directory not found.

        Example:
            v.get_extensions()
            => [{"id": "ms-python.python", "name": "Python", "version": "2024.1.0", ...}]
        """
        ext_dir = _find_extensions_dir()
        if ext_dir and ext_dir.exists():
            return self._scan_extensions_dir(ext_dir)

        # Fallback: CLI
        result = _run_code_cli(["--list-extensions", "--show-versions"])
        if "error" in result:
            return [result]

        extensions = []
        for line in result["stdout"].splitlines():
            line = line.strip()
            if not line:
                continue
            if "@" in line:
                ext_id, version = line.rsplit("@", 1)
                extensions.append({"id": ext_id.lower(), "version": version})
            else:
                extensions.append({"id": line.lower(), "version": None})
        return extensions

    def _scan_extensions_dir(self, ext_dir: Path) -> list[dict]:
        """Scan extensions directory for package.json files."""
        extensions = []
        if not ext_dir.exists():
            return extensions

        for entry in ext_dir.iterdir():
            if not entry.is_dir():
                continue
            pkg_path = entry / "package.json"
            if not pkg_path.exists():
                continue
            try:
                with open(pkg_path) as f:
                    pkg = json.load(f)
                publisher = pkg.get("publisher", "")
                name = pkg.get("name", "")
                ext_id = f"{publisher}.{name}".lower() if publisher else name.lower()
                extensions.append({
                    "id": ext_id,
                    "name": pkg.get("displayName", name),
                    "version": pkg.get("version", ""),
                    "description": (pkg.get("description") or "")[:200],
                    "dir": entry.name,
                })
            except (json.JSONDecodeError, OSError):
                extensions.append({
                    "id": entry.name,
                    "name": entry.name,
                    "version": "",
                    "description": "",
                    "dir": entry.name,
                    "parse_error": True,
                })
        return extensions

    # === Workspace files ===

    def get_workspace_settings(self, workspace_path: str) -> Any:
        """Read .vscode/settings.json from a workspace.

        Example:
            v.get_workspace_settings("/home/user/project")
            => {"python.defaultInterpreterPath": "/usr/bin/python3", ...}
        """
        p = Path(workspace_path) / ".vscode" / "settings.json"
        return _read_json_file(p)

    def get_workspace_extensions(self, workspace_path: str) -> Any:
        """Read .vscode/extensions.json recommendations from a workspace.

        Example:
            v.get_workspace_extensions("/home/user/project")
            => {"recommendations": ["ms-python.python", ...]}
        """
        p = Path(workspace_path) / ".vscode" / "extensions.json"
        return _read_json_file(p)

    def get_workspace_tasks(self, workspace_path: str) -> Any:
        """Read .vscode/tasks.json from a workspace.

        Example:
            v.get_workspace_tasks("/home/user/project")
            => {"version": "2.0.0", "tasks": [...]}
        """
        p = Path(workspace_path) / ".vscode" / "tasks.json"
        return _read_json_file(p)

    def get_workspace_launch(self, workspace_path: str) -> Any:
        """Read .vscode/launch.json from a workspace.

        Example:
            v.get_workspace_launch("/home/user/project")
            => {"version": "0.2.0", "configurations": [...]}
        """
        p = Path(workspace_path) / ".vscode" / "launch.json"
        return _read_json_file(p)

    # === SQLite state DB ===

    def get_recent_files(self) -> list[dict]:
        """Read recent files from state.vscdb.

        Example:
            v.get_recent_files()
            => [{"key": "history.recentlyOpenedPathsList", "value": {...}}]
        """
        rows = _query_state_db(
            "SELECT key, value FROM ItemTable WHERE key LIKE ?",
            ("%recently%",)
        )
        if rows and "error" in rows[0]:
            return rows

        # Try to parse JSON values
        parsed = []
        for row in rows:
            val = row.get("value", "")
            try:
                row["value"] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
            parsed.append(row)
        return parsed

    def get_global_state(self, key: str | None = None) -> list[dict] | dict:
        """Read from state.vscdb ItemTable.

        Example:
            v.get_global_state("workbench.activity.pinnedViewlets2")
            => {"key": "workbench.activity.pinnedViewlets2", "value": [...]}
        """
        if key:
            rows = _query_state_db(
                "SELECT key, value FROM ItemTable WHERE key = ?",
                (key,)
            )
            if rows and "error" in rows[0]:
                return rows[0]
            if not rows:
                return {"error": f"Key '{key}' not found in state.vscdb"}
            row = rows[0]
            val = row.get("value", "")
            try:
                row["value"] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
            return row
        else:
            rows = _query_state_db(
                "SELECT key, LENGTH(value) as value_length FROM ItemTable ORDER BY key"
            )
            return rows

    # === Composite checks ===

    def check_file_exists(self, path: str) -> dict:
        """Check if a file exists.

        Example:
            v.check_file_exists("/home/user/.config/Code/User/settings.json")
            => {"exists": true, "path": "/home/user/.config/Code/User/settings.json", "size": 234}
        """
        p = Path(path)
        exists = p.exists()
        result = {"exists": exists, "path": str(p)}
        if exists:
            try:
                result["size"] = p.stat().st_size
                result["is_file"] = p.is_file()
                result["is_dir"] = p.is_dir()
            except OSError:
                pass
        return result

    def check_setting(self, key: str, expected: str) -> dict:
        """Check if a user setting matches an expected value.

        The expected value is parsed as JSON if possible, otherwise compared as string.

        Example:
            v.check_setting("editor.fontSize", "14")
            => {"match": true, "key": "editor.fontSize", "expected": 14, "actual": 14}
        """
        # Parse expected value
        try:
            expected_val = json.loads(expected)
        except (json.JSONDecodeError, TypeError):
            expected_val = expected

        result = self.get_settings(key)
        if isinstance(result, dict) and "error" in result:
            return {**result, "match": False, "key": key, "expected": expected_val}

        if isinstance(result, dict) and "value" in result:
            actual = result["value"]
        else:
            actual = result

        match = actual == expected_val
        return {"match": match, "key": key, "expected": expected_val, "actual": actual}

    def check_extension_installed(self, extension_id: str) -> dict:
        """Check if a specific extension is installed.

        Example:
            v.check_extension_installed("ms-python.python")
            => {"installed": true, "extension": {"id": "ms-python.python", ...}}
        """
        extensions = self.get_extensions()
        if extensions and isinstance(extensions[0], dict) and "error" in extensions[0]:
            return {**extensions[0], "installed": False}

        ext_lower = extension_id.lower()
        for ext in extensions:
            if ext.get("id", "").lower() == ext_lower:
                return {"installed": True, "extension": ext}
            # Also check if extension_id matches the dir name pattern
            if ext.get("dir", "").lower().startswith(ext_lower):
                return {"installed": True, "extension": ext}
        return {"installed": False, "extension_id": extension_id, "installed_count": len(extensions)}

    def check_keybinding_exists(self, key_combo: str) -> dict:
        """Check if a keybinding for a key combination exists.

        Example:
            v.check_keybinding_exists("ctrl+shift+p")
            => {"exists": true, "binding": {"key": "ctrl+shift+p", "command": "..."}}
        """
        keybindings = self.get_keybindings()
        if isinstance(keybindings, dict) and "error" in keybindings:
            return {**keybindings, "exists": False}
        if not isinstance(keybindings, list):
            return {"exists": False, "error": "keybindings.json is not a list"}

        key_lower = key_combo.lower()
        for binding in keybindings:
            if isinstance(binding, dict) and binding.get("key", "").lower() == key_lower:
                return {"exists": True, "binding": binding}
        return {"exists": False, "key_combo": key_combo, "bindings_count": len(keybindings)}

    def check_workspace_setting(self, workspace_path: str, key: str, expected: str) -> dict:
        """Check if a workspace setting matches an expected value.

        Example:
            v.check_workspace_setting("/home/user/project", "python.defaultInterpreterPath", '"/usr/bin/python3"')
            => {"match": true, "key": "python.defaultInterpreterPath", ...}
        """
        try:
            expected_val = json.loads(expected)
        except (json.JSONDecodeError, TypeError):
            expected_val = expected

        data = self.get_workspace_settings(workspace_path)
        if isinstance(data, dict) and "error" in data:
            return {**data, "match": False, "key": key, "expected": expected_val}

        if key in data:
            actual = data[key]
        else:
            result = _navigate_key(data, key)
            if isinstance(result, dict) and "error" in result:
                return {**result, "match": False, "key": key, "expected": expected_val}
            actual = result

        match = actual == expected_val
        return {"match": match, "key": key, "expected": expected_val, "actual": actual}

    def check_workspace_has_file(self, workspace_path: str, relative_path: str) -> dict:
        """Check if a file exists within a workspace.

        Example:
            v.check_workspace_has_file("/home/user/project", "src/main.py")
            => {"exists": true, "path": "/home/user/project/src/main.py"}
        """
        p = Path(workspace_path) / relative_path
        return self.check_file_exists(str(p))

    def check_tasks_defined(self, workspace_path: str) -> dict:
        """Check if tasks.json exists and contains tasks.

        Example:
            v.check_tasks_defined("/home/user/project")
            => {"defined": true, "task_count": 2, "tasks": [...]}
        """
        data = self.get_workspace_tasks(workspace_path)
        if isinstance(data, dict) and "error" in data:
            return {**data, "defined": False}

        tasks = data.get("tasks", []) if isinstance(data, dict) else []
        return {
            "defined": len(tasks) > 0,
            "task_count": len(tasks),
            "tasks": [
                {"label": t.get("label", ""), "type": t.get("type", "")}
                for t in tasks
                if isinstance(t, dict)
            ],
        }

    def check_launch_config_exists(self, workspace_path: str, config_name: str) -> dict:
        """Check if a specific launch configuration exists.

        Example:
            v.check_launch_config_exists("/home/user/project", "Python: Current File")
            => {"exists": true, "config": {"name": "Python: Current File", "type": "python", ...}}
        """
        data = self.get_workspace_launch(workspace_path)
        if isinstance(data, dict) and "error" in data:
            return {**data, "exists": False}

        configs = data.get("configurations", []) if isinstance(data, dict) else []
        name_lower = config_name.lower()
        for config in configs:
            if isinstance(config, dict) and config.get("name", "").lower() == name_lower:
                return {"exists": True, "config": config}
        return {
            "exists": False,
            "config_name": config_name,
            "available_configs": [
                c.get("name", "") for c in configs if isinstance(c, dict)
            ],
        }

    def check_file_contains(self, path: str, substring: str) -> dict:
        """Check if a file contains a substring.

        Example:
            v.check_file_contains("/home/user/app.js", "calculateSum")
            => {"contains": true, "path": "/home/user/app.js", "substring": "calculateSum"}
        """
        p = Path(path)
        if not p.exists():
            return {"contains": False, "error": f"File not found: {path}"}
        if not p.is_file():
            return {"contains": False, "error": f"Not a file: {path}"}
        try:
            content = p.read_text(errors="replace")
            found = substring in content
            return {"contains": found, "path": str(p), "substring": substring}
        except OSError as e:
            return {"contains": False, "error": f"Cannot read {path}: {e}"}

    def check_keybinding_command(self, command: str) -> dict:
        """Check if a keybinding exists for a specific command.

        Example:
            v.check_keybinding_command("editor.action.duplicateSelection")
            => {"exists": true, "binding": {"key": "ctrl+shift+d", "command": "editor.action.duplicateSelection"}}
        """
        keybindings = self.get_keybindings()
        if isinstance(keybindings, dict) and "error" in keybindings:
            return {**keybindings, "exists": False}
        if not isinstance(keybindings, list):
            return {"exists": False, "error": "keybindings.json is not a list"}

        cmd_lower = command.lower()
        for binding in keybindings:
            if isinstance(binding, dict) and binding.get("command", "").lower() == cmd_lower:
                return {"exists": True, "binding": binding}
        return {"exists": False, "command": command, "bindings_count": len(keybindings)}

    def check_task_exists(self, workspace_path: str, label: str) -> dict:
        """Check if a specific task exists in tasks.json by label.

        Example:
            v.check_task_exists("/home/user/project", "Build")
            => {"exists": true, "task": {"label": "Build", "type": "shell", ...}}
        """
        data = self.get_workspace_tasks(workspace_path)
        if isinstance(data, dict) and "error" in data:
            return {**data, "exists": False}

        tasks = data.get("tasks", []) if isinstance(data, dict) else []
        label_lower = label.lower()
        for task in tasks:
            if isinstance(task, dict) and task.get("label", "").lower() == label_lower:
                return {"exists": True, "task": task}
        return {
            "exists": False,
            "label": label,
            "available_tasks": [t.get("label", "") for t in tasks if isinstance(t, dict)],
        }

    def check_workspace_extension_recommended(self, workspace_path: str, extension_id: str) -> dict:
        """Check if an extension is in the workspace recommendations.

        Example:
            v.check_workspace_extension_recommended("/home/user/project", "ms-python.python")
            => {"recommended": true, "extension_id": "ms-python.python"}
        """
        data = self.get_workspace_extensions(workspace_path)
        if isinstance(data, dict) and "error" in data:
            return {**data, "recommended": False}

        recs = data.get("recommendations", []) if isinstance(data, dict) else []
        ext_lower = extension_id.lower()
        for rec in recs:
            if isinstance(rec, str) and rec.lower() == ext_lower:
                return {"recommended": True, "extension_id": extension_id}
        return {"recommended": False, "extension_id": extension_id, "recommendations": recs}

    def get_snippets(self, language: str | None = None) -> dict | list:
        """Read user snippet files.

        If language is given, read that specific snippet file.
        Otherwise list available snippet files.

        Example:
            v.get_snippets("python")
            => {"Print statement": {"prefix": "pp", "body": ["print($1)"], "description": "Print"}}
        """
        config_dir = _find_config_dir()
        snippets_dir = (config_dir / "snippets") if config_dir else VSCODE_CONFIG_DIR / "snippets"

        if not snippets_dir.exists():
            return {"error": f"Snippets directory not found: {snippets_dir}"}

        if language:
            # Try <language>.json
            snippet_file = snippets_dir / f"{language}.json"
            if not snippet_file.exists():
                # Try <language>.code-snippets
                snippet_file = snippets_dir / f"{language}.code-snippets"
            if not snippet_file.exists():
                return {"error": f"No snippet file found for '{language}'"}
            return _read_json_file(snippet_file)

        # List all snippet files
        files = []
        for f in snippets_dir.iterdir():
            if f.suffix in (".json", ) or f.name.endswith(".code-snippets"):
                files.append({"name": f.stem, "path": str(f)})
        return files

    def check_snippet_exists(self, language: str, prefix: str) -> dict:
        """Check if a snippet with a given prefix exists for a language.

        Example:
            v.check_snippet_exists("python", "pp")
            => {"exists": true, "snippet_name": "Print statement", "prefix": "pp"}
        """
        data = self.get_snippets(language)
        if isinstance(data, dict) and "error" in data:
            return {**data, "exists": False}
        if not isinstance(data, dict):
            return {"exists": False, "error": "Unexpected snippet file format"}

        prefix_lower = prefix.lower()
        for name, snippet in data.items():
            if isinstance(snippet, dict):
                snip_prefix = snippet.get("prefix", "")
                if isinstance(snip_prefix, str) and snip_prefix.lower() == prefix_lower:
                    return {"exists": True, "snippet_name": name, "prefix": snip_prefix}
                if isinstance(snip_prefix, list):
                    for sp in snip_prefix:
                        if isinstance(sp, str) and sp.lower() == prefix_lower:
                            return {"exists": True, "snippet_name": name, "prefix": sp}
        return {"exists": False, "language": language, "prefix": prefix}


# ---------------------------------------------------------------------------
# CLI interface -- for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

COMMANDS = {
    # Query: JSON config
    "settings": ("Read settings.json (optional key)", lambda v, args: v.get_settings(args[0] if args else None)),
    "keybindings": ("Read keybindings.json", lambda v, args: v.get_keybindings()),

    # Query: Extensions
    "extensions": ("List installed extensions", lambda v, args: v.get_extensions()),

    # Query: Workspace
    "workspace-settings": ("Read workspace .vscode/settings.json", lambda v, args: v.get_workspace_settings(args[0])),
    "workspace-extensions": ("Read workspace .vscode/extensions.json", lambda v, args: v.get_workspace_extensions(args[0])),
    "workspace-tasks": ("Read workspace .vscode/tasks.json", lambda v, args: v.get_workspace_tasks(args[0])),
    "workspace-launch": ("Read workspace .vscode/launch.json", lambda v, args: v.get_workspace_launch(args[0])),

    # Query: SQLite state
    "recent-files": ("Read recent files from state.vscdb", lambda v, args: v.get_recent_files()),
    "global-state": ("Read from state.vscdb (optional key)", lambda v, args: v.get_global_state(args[0] if args else None)),

    # Query: Snippets
    "snippets": ("Read user snippets (optional language)", lambda v, args: v.get_snippets(args[0] if args else None)),

    # Check: File
    "check-file-exists": ("Check if file exists", lambda v, args: v.check_file_exists(args[0])),
    "check-file-contains": ("Check file contains substring", lambda v, args: v.check_file_contains(args[0], " ".join(args[1:]))),

    # Check: Settings
    "check-setting": ("Check setting matches value", lambda v, args: v.check_setting(args[0], args[1])),

    # Check: Extensions
    "check-extension-installed": ("Check extension is installed", lambda v, args: v.check_extension_installed(args[0])),

    # Check: Keybindings
    "check-keybinding-exists": ("Check keybinding exists", lambda v, args: v.check_keybinding_exists(args[0])),
    "check-keybinding-command": ("Check command has keybinding", lambda v, args: v.check_keybinding_command(args[0])),

    # Check: Workspace
    "check-workspace-setting": ("Check workspace setting", lambda v, args: v.check_workspace_setting(args[0], args[1], args[2])),
    "check-workspace-has-file": ("Check file in workspace", lambda v, args: v.check_workspace_has_file(args[0], args[1])),
    "check-tasks-defined": ("Check tasks.json has tasks", lambda v, args: v.check_tasks_defined(args[0])),
    "check-task-exists": ("Check specific task by label", lambda v, args: v.check_task_exists(args[0], " ".join(args[1:]))),
    "check-launch-config-exists": ("Check launch config exists", lambda v, args: v.check_launch_config_exists(args[0], " ".join(args[1:]))),
    "check-workspace-extension-recommended": ("Check extension in recommendations", lambda v, args: v.check_workspace_extension_recommended(args[0], args[1])),

    # Check: Snippets
    "check-snippet-exists": ("Check snippet with prefix exists", lambda v, args: v.check_snippet_exists(args[0], args[1])),
}


def _print_usage():
    print("VS Code Verifier — query VS Code state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nConfig dir: {VSCODE_CONFIG_DIR}")
    print(f"Extensions dir: {VSCODE_EXTENSIONS_DIR}")
    print("\nAll output is JSON.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = VSCodeVerifier()
    _, handler = COMMANDS[cmd]

    try:
        result = handler(v, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))
