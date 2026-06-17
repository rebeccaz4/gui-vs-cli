# PCManFM Verifier

Programmatic state inspection for **PCManFM** (lightweight GTK file manager) running in an E2B desktop sandbox.

## Verification Channels

| Channel | What it reads | Reliability |
|---|---|---|
| **Filesystem** (primary) | `ls`, `stat`, `readlink`, file content | Ground truth |
| **Config files** | `~/.config/pcmanfm/default/pcmanfm.conf` (INI) | High — persisted on change |
| **GTK Bookmarks** | `~/.config/gtk-3.0/bookmarks` (text, one URI per line) | High |
| **Recent files** | `~/.local/share/recently-used.xbel` (XML) | Medium — shared across GTK apps |
| **Process state** | `pgrep` | High |

## Prerequisites

No special launch flags required. The filesystem is the primary verification channel.

```bash
# Launch PCManFM (already in sandbox)
pcmanfm &
```

## Usage

```python
# From outside the sandbox (via sandbox.commands.run)
result = sandbox.commands.run("python3 /home/user/verifiers/pcmanfm.py list-directory /home/user")
data = json.loads(result.stdout)

result = sandbox.commands.run("python3 /home/user/verifiers/pcmanfm.py check-file-exists /home/user/test.txt")
data = json.loads(result.stdout)
reward = 1.0 if data["exists"] else 0.0
```

## Endpoint Reference

### Filesystem — Core Content

| Command | Args | Description | Primary Return Key |
|---|---|---|---|
| `list-directory` | `<path> [--hidden]` | List files in a directory | `entries` (list) |
| `file-info` | `<path>` | Detailed stat info (size, perms, owner, timestamps) | full dict |
| `file-content` | `<path> [max_bytes]` | Read text file contents | `content` |
| `tree` | `<path> [max_depth]` | Recursive directory tree | `tree` |
| `disk-usage` | `<path>` | Disk usage (du) | `size_bytes` |

### Settings & Preferences

| Command | Args | Description | Primary Return Key |
|---|---|---|---|
| `get-config` | — | Full pcmanfm.conf as dict | `sections` |
| `get-config-key` | `<section> <key>` | Specific config value | `value` |
| `get-sort-settings` | — | Sort column and order | `sort_by`, `sort_order` |
| `get-view-mode` | — | Icon/list/compact/thumbnail | `view_mode` |

### Bookmarks & Recent Files

| Command | Args | Description | Primary Return Key |
|---|---|---|---|
| `get-bookmarks` | — | List GTK bookmarks | `bookmarks` (list) |
| `get-recent-files` | `[limit]` | Recently accessed files | `files` (list) |

### Process State

| Command | Args | Description | Primary Return Key |
|---|---|---|---|
| `status` | — | Check if PCManFM is running | `running` (bool) |

### Check Endpoints (Reward Signals)

| Command | Args | Description | Primary Bool Key |
|---|---|---|---|
| `check-file-exists` | `<path>` | File exists? | `exists` |
| `check-dir-exists` | `<path>` | Directory exists? | `exists` |
| `check-file-contains` | `<path> <text>` | File contains text? | `contains` |
| `check-permissions` | `<path> <octal>` | Permissions match? (e.g. `755`) | `match` |
| `check-symlink` | `<path> [target]` | Is symlink? Target matches? | `is_symlink` |
| `check-owner` | `<path> <user>` | Owned by user? | `match` |
| `check-bookmark-exists` | `<path_or_label>` | Path is bookmarked? | `exists` |
| `check-recent-file` | `<substring>` | File in recent list? | `found` |
| `check-file-count` | `<path> <count> [--hidden]` | Directory has N entries? | `match` |
| `check-extension-match` | `<path> <ext>` | All files have extension? | `all_match` |
| `check-config-value` | `<section> <key> <value>` | Config key matches? | `match` |

## Common Verification Patterns

### Check if agent created a file

```python
result = run("python3 /home/user/verifiers/pcmanfm.py check-file-exists /home/user/Documents/report.txt")
data = json.loads(result.stdout)
reward = 1.0 if data["exists"] else 0.0
```

### Check if agent set correct permissions

```python
result = run("python3 /home/user/verifiers/pcmanfm.py check-permissions /home/user/script.sh 755")
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

### Check if agent created a symlink to the right target

```python
result = run("python3 /home/user/verifiers/pcmanfm.py check-symlink /home/user/link.txt /home/user/real.txt")
data = json.loads(result.stdout)
reward = 1.0 if data["is_symlink"] and data.get("target_matches") else 0.0
```

### Check if agent organized files by extension

```python
result = run("python3 /home/user/verifiers/pcmanfm.py check-extension-match /home/user/images .png")
data = json.loads(result.stdout)
reward = 1.0 if data["all_match"] else 0.0
```

### Check if agent bookmarked a directory

```python
result = run("python3 /home/user/verifiers/pcmanfm.py check-bookmark-exists /home/user/Projects")
data = json.loads(result.stdout)
reward = 1.0 if data["exists"] else 0.0
```

### Check if agent changed a config setting

```python
result = run("python3 /home/user/verifiers/pcmanfm.py check-config-value ui view_mode list")
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

## Skipped Categories

| Category | Reason |
|---|---|
| **UI layout / window state** | No session file or API exposes sidebar/panel state at rest |
| **Navigation history** | PCManFM has no persistent navigation history database |
| **Extensions / plugins** | PCManFM has no plugin system |
| **Network / connection state** | PCManFM is a local file manager with no network features |
| **Keybindings** | PCManFM keybindings are not user-configurable via config files |

## Dependencies

- Python 3.10+ (stdlib only — no pip packages needed)
- `pcmanfm` installed in sandbox
