# VS Code Verifier

Programmatic state inspection for Visual Studio Code running in an E2B desktop sandbox. Designed for RL/evaluation reward signal generation.

## Verification Channels

| Priority | Channel | What it covers |
|----------|---------|---------------|
| 1 | JSON config files | `settings.json`, `keybindings.json` |
| 2 | SQLite state DB | `state.vscdb` — global state, recent files |
| 3 | CLI commands | `code --list-extensions`, etc. |
| 4 | File system | Extensions directory, workspace `.vscode/`, snippets |

## Key Paths

| Item | Path |
|------|------|
| Settings | `~/.config/Code/User/settings.json` |
| Keybindings | `~/.config/Code/User/keybindings.json` |
| Global state | `~/.config/Code/User/globalStorage/state.vscdb` |
| Extensions | `~/.vscode/extensions/` |
| Snippets | `~/.config/Code/User/snippets/` |
| Workspace config | `<project>/.vscode/` |

## CLI Usage

```bash
# From sandbox
python3 /home/user/verifiers/vscode.py <command> [args...]

# Help
python3 /home/user/verifiers/vscode.py --help
```

## Commands

### Query Commands

| Command | Args | Description |
|---------|------|-------------|
| `settings` | `[key]` | Read settings.json, optionally a specific key |
| `keybindings` | | Read keybindings.json |
| `extensions` | | List installed extensions |
| `workspace-settings` | `<workspace_path>` | Read .vscode/settings.json |
| `workspace-extensions` | `<workspace_path>` | Read .vscode/extensions.json recommendations |
| `workspace-tasks` | `<workspace_path>` | Read .vscode/tasks.json |
| `workspace-launch` | `<workspace_path>` | Read .vscode/launch.json |
| `recent-files` | | Read recent files from state.vscdb |
| `global-state` | `[key]` | Read from state.vscdb |
| `snippets` | `[language]` | List snippet files, or read a specific language's snippets |

### Check Commands

| Command | Args | Primary Key | Description |
|---------|------|-------------|-------------|
| `check-file-exists` | `<path>` | `exists` | Check if a file exists |
| `check-file-contains` | `<path> <substring>` | `contains` | Check if file contains a substring |
| `check-setting` | `<key> <value>` | `match` | Check setting matches value |
| `check-extension-installed` | `<extension_id>` | `installed` | Check extension is installed |
| `check-keybinding-exists` | `<key_combo>` | `exists` | Check keybinding for key combo exists |
| `check-keybinding-command` | `<command>` | `exists` | Check a command has a keybinding |
| `check-workspace-setting` | `<workspace_path> <key> <value>` | `match` | Check workspace setting |
| `check-workspace-has-file` | `<workspace_path> <relative_path>` | `exists` | Check file in workspace |
| `check-tasks-defined` | `<workspace_path>` | `defined` | Check tasks.json has tasks |
| `check-task-exists` | `<workspace_path> <label>` | `exists` | Check specific task by label |
| `check-launch-config-exists` | `<workspace_path> <config_name>` | `exists` | Check launch config exists |
| `check-workspace-extension-recommended` | `<workspace_path> <ext_id>` | `recommended` | Check extension in workspace recommendations |
| `check-snippet-exists` | `<language> <prefix>` | `exists` | Check snippet with prefix exists |

## Examples

```bash
# Read all settings
python3 vscode.py settings
# => {"editor.fontSize": 14, "editor.tabSize": 2, ...}

# Check a specific setting
python3 vscode.py check-setting editor.fontSize 14
# => {"match": true, "key": "editor.fontSize", "expected": 14, "actual": 14}

# List extensions
python3 vscode.py extensions
# => [{"id": "ms-python.python", "name": "Python", "version": "2024.1.0"}, ...]

# Check if an extension is installed
python3 vscode.py check-extension-installed ms-python.python
# => {"installed": true, "extension": {...}}

# Check if a file contains text
python3 vscode.py check-file-contains /home/user/app.js calculateSum
# => {"contains": true, "path": "/home/user/app.js", "substring": "calculateSum"}

# Check workspace launch config
python3 vscode.py check-launch-config-exists /home/user/project Python: Current File
# => {"exists": true, "config": {"name": "Python: Current File", ...}}

# Check a specific task exists
python3 vscode.py check-task-exists /home/user/project Build
# => {"exists": true, "task": {"label": "Build", "type": "shell", ...}}

# Check keybinding maps to command
python3 vscode.py check-keybinding-command editor.action.duplicateSelection
# => {"exists": true, "binding": {"key": "ctrl+shift+d", "command": "..."}}

# Check extension recommended in workspace
python3 vscode.py check-workspace-extension-recommended /home/user/project ms-python.python
# => {"recommended": true, "extension_id": "ms-python.python"}

# Check snippet exists
python3 vscode.py check-snippet-exists python pp
# => {"exists": true, "snippet_name": "Print statement", "prefix": "pp"}
```

## Python API

```python
from verifiers.vscode import VSCodeVerifier

v = VSCodeVerifier()

# Query
settings = v.get_settings()
font_size = v.get_settings("editor.fontSize")
extensions = v.get_extensions()
keybindings = v.get_keybindings()
snippets = v.get_snippets("python")

# Check
v.check_setting("editor.fontSize", "14")
v.check_extension_installed("ms-python.python")
v.check_keybinding_exists("ctrl+shift+p")
v.check_keybinding_command("editor.action.duplicateSelection")
v.check_file_contains("/home/user/app.js", "calculateSum")
v.check_tasks_defined("/home/user/project")
v.check_task_exists("/home/user/project", "Build")
v.check_launch_config_exists("/home/user/project", "Python: Current File")
v.check_workspace_extension_recommended("/home/user/project", "ms-python.python")
v.check_snippet_exists("python", "pp")
```

## SQLite State DB

The `state.vscdb` file uses a simple key-value schema (`ItemTable`). The verifier copies the database before reading to avoid WAL lock contention with a running VS Code instance.

Common keys:
- `history.recentlyOpenedPathsList` — recently opened files/folders
- `workbench.activity.pinnedViewlets2` — pinned sidebar items
- `workbench.panel.pinnedPanels` — pinned bottom panel items

## Testing

```bash
python verifiers/vscode/test_vscode.py
```

Requires `e2b_desktop` and a sandbox template with VS Code installed.
