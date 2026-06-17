# Obsidian Verifier

Programmatic state inspection for Obsidian vaults in E2B sandbox.

## Verification Channels

1. **Markdown files on disk** (primary) — notes are plain `.md` files, trivially readable
2. **JSON config files** — `.obsidian/app.json`, `appearance.json`, `hotkeys.json`, `workspace.json`, `community-plugins.json`, `core-plugins.json`, `bookmarks.json`
3. **Global config** — `~/.config/obsidian/obsidian.json`

## Prerequisites

- Obsidian vault directory must exist on disk
- No special launch flags needed — all verification is file-based
- No external dependencies (stdlib only)

## Usage

```python
# From check agent (outside sandbox)
result = sandbox.commands.run(
    "python3 /home/user/verifiers/obsidian.py list-notes /home/user/vault"
)
data = json.loads(result.stdout)

result = sandbox.commands.run(
    "python3 /home/user/verifiers/obsidian.py check-note-contains /home/user/vault 'My Note' 'meeting'"
)
data = json.loads(result.stdout)
reward = 1.0 if data["contains"] else 0.0
```

## CLI Format

```
python3 obsidian.py <command> <vault_path> [args...]
```

The `<vault_path>` is always the first argument after the command (except `global-config`). Notes can be referenced by:
- Name without extension: `"My Note"`
- Name with extension: `"My Note.md"`
- Relative path: `"folder/My Note.md"`

## Endpoint Reference

### Core Content

#### `get-note <vault> <note_name>`
Read a note's full content.
```json
{"path": "My Note.md", "content": "# My Note\n...", "size": 234}
```

#### `get-note-frontmatter <vault> <note_name>`
Parse YAML frontmatter from a note.
```json
{"path": "My Note.md", "frontmatter": {"title": "My Note", "tags": ["work"]}, "has_frontmatter": true}
```

#### `list-notes <vault> [folder]`
List all notes in vault or a subfolder.
```json
{"count": 5, "notes": [{"path": "Note1.md", "size": 123}, ...]}
```

#### `search-notes <vault> <query>`
Search notes for text content.
```json
{"count": 2, "matches": [{"path": "Meetings/Mon.md", "snippets": ["...meeting agenda..."]}]}
```

#### `get-note-tags <vault> <note_name>`
Get all tags from a note (inline + frontmatter).
```json
{"path": "Note.md", "tags": ["project", "work"], "count": 2, "inline_tags": ["work"], "frontmatter_tags": ["project"]}
```

#### `get-note-links <vault> <note_name>`
Get all `[[wikilinks]]` from a note.
```json
{"path": "Note.md", "links": [{"target": "Other Note", "alias": null, "heading": null}], "count": 1}
```

#### `get-note-headings <vault> <note_name>`
Get all Markdown headings from a note.
```json
{"path": "Note.md", "headings": [{"level": 1, "text": "Title"}, {"level": 2, "text": "Section"}], "count": 2}
```

#### `get-backlinks <vault> <note_name>`
Find all notes that link to a given note.
```json
{"target": "My Note", "backlinks": [{"path": "Other.md", "link_count": 2}], "count": 1}
```

#### `get-vault-tags <vault>`
List all unique tags across the entire vault with counts.
```json
{"tags": {"project": 3, "work": 5}, "count": 2}
```

### Settings & Configuration

#### `app-settings <vault> [key]`
Read `.obsidian/app.json`. Optional key for specific setting.
```json
// No key: returns full settings dict
{"spellcheck": true, "readableLineLength": true, ...}
// With key:
{"key": "spellcheck", "value": true}
```

#### `appearance <vault> [key]`
Read `.obsidian/appearance.json`.
```json
{"baseFontSize": 16, "theme": "obsidian", "cssTheme": "", ...}
```

#### `hotkeys <vault>`
Read `.obsidian/hotkeys.json` — custom hotkey overrides.
```json
{"editor:toggle-bold": [{"modifiers": ["Mod"], "key": "B"}], ...}
```

### Plugins

#### `community-plugins <vault>`
List enabled community plugins.
```json
{"plugins": ["dataview", "templater-obsidian"], "count": 2}
```

#### `core-plugins <vault>`
Get core plugin enable/disable state.
```json
{"plugins": {"file-explorer": true, "graph": true, ...}, "count": 15}
```

#### `plugin-settings <vault> <plugin_id>`
Read settings for a specific plugin.
```json
{"refreshInterval": 1000, ...}
```

### Workspace / UI Layout

#### `workspace <vault>`
Read `.obsidian/workspace.json` — open tabs, active file, sidebar.
```json
{"main": {...}, "left": {...}, "right": {...}, "active": "..."}
```

### Bookmarks

#### `bookmarks <vault>`
Read `.obsidian/bookmarks.json`.
```json
{"items": [{"type": "file", "path": "Note.md"}, ...]}
```

### Vault Structure

#### `list-folders <vault>`
List all folders in vault (excluding `.obsidian`).
```json
{"count": 3, "folders": ["Daily Notes", "Projects", "Projects/Active"]}
```

### Global Config

#### `global-config`
Read `~/.config/obsidian/obsidian.json`. No vault path needed.
```json
{"vaults": {"abc123": {"path": "/home/user/vault", "open": true}}}
```

### File I/O

#### `check-file-exists <vault> <path>`
Check if a file exists on disk.
```json
{"exists": true, "path": "/home/user/vault/Note.md", "size": 234}
```

### Composite Checks

All `check-*` endpoints return a dict with one primary boolean key.

#### `check-note-exists <vault> <note_name>`
```json
{"exists": true, "path": "My Note.md"}
```

#### `check-note-contains <vault> <note_name> <text>`
```json
{"contains": true, "path": "My Note.md", "snippet": "...meeting agenda..."}
```

#### `check-note-has-tag <vault> <note_name> <tag>`
```json
{"has_tag": true, "tag": "project", "path": "Note.md", "all_tags": ["project", "work"]}
```

#### `check-note-has-frontmatter <vault> <note_name> <key> [expected_value]`
```json
{"has_key": true, "match": true, "key": "status", "actual": "done", "path": "Note.md"}
```

#### `check-note-links-to <vault> <note_name> <target>`
```json
{"links_to": true, "target": "Other Note", "path": "Note.md", "link_count": 1}
```

#### `check-note-has-heading <vault> <note_name> <heading_text> [level]`
```json
{"has_heading": true, "heading": {"level": 2, "text": "Introduction"}, "path": "Note.md"}
```

#### `check-folder-exists <vault> <folder_name>`
```json
{"exists": true, "path": "Daily Notes"}
```

#### `check-plugin-enabled <vault> <plugin_id> [community|core]`
```json
{"enabled": true, "plugin_id": "dataview", "type": "community"}
```

#### `check-setting <vault> <key> <expected_value>`
```json
{"match": true, "key": "spellcheck", "expected": true, "actual": true}
```

#### `check-hotkey <vault> <command_id>`
```json
{"has_hotkey": true, "command": "editor:toggle-bold", "bindings": [...]}
```

#### `check-theme <vault> <expected_theme>`
```json
{"match": true, "expected": "obsidian", "actual": "obsidian"}
```

## Common Verification Patterns

### Check if a note was created with specific content
```python
result = run("check-note-exists /home/user/vault 'Meeting Notes'")
assert result["exists"]

result = run("check-note-contains /home/user/vault 'Meeting Notes' 'Action Items'")
assert result["contains"]
```

### Check vault organization
```python
result = run("check-folder-exists /home/user/vault 'Daily Notes'")
assert result["exists"]

result = run("list-notes /home/user/vault 'Daily Notes'")
assert result["count"] > 0
```

### Verify note linking
```python
result = run("check-note-links-to /home/user/vault 'Index' 'Project A'")
assert result["links_to"]

result = run("get-backlinks /home/user/vault 'Project A'")
assert result["count"] > 0
```

### Check settings were changed
```python
result = run("check-setting /home/user/vault spellcheck true")
assert result["match"]

result = run("check-theme /home/user/vault 'Minimal'")
assert result["match"]
```

## Skipped Categories

- **Navigation/history**: Obsidian does not persist browsing history in an accessible file format
- **Network/connection state**: Not applicable (local-first app)
- **Media/playback state**: Not applicable
- **Visual/graphical state**: Obsidian does not expose rendered visual state via files
