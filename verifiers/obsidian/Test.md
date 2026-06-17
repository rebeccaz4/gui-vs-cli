# Obsidian Verifier Test Plan

## Module Overview

The Obsidian verifier inspects vault state through:
1. **Markdown file parsing** — note content, frontmatter, tags, links, headings
2. **JSON config file reading** — app.json, appearance.json, hotkeys.json, workspace.json, community-plugins.json, core-plugins.json, bookmarks.json
3. **File system inspection** — note/folder existence, vault structure

No app launch flags are needed — all verification is file-based.

## Test Groups

### Group 1: Help/Usage
- **What is being tested**: `--help` flag prints usage and exits 0
- **Edge cases**: None
- **Expected test count**: 3

### Group 2: Error Handling (bad arguments)
- **What is being tested**: Missing/invalid args, unknown commands
- **Edge cases**: Missing vault path, missing note name, unknown subcommand, missing required args for check-* endpoints
- **Expected test count**: 8

### Group 3: Error Handling (missing vault/files)
- **What is being tested**: Vault not found, note not found, config files missing
- **Edge cases**: Non-existent vault path, non-existent note, vault is a file not dir
- **Expected test count**: 5

### Group 4: Core Content — Notes
- **What is being tested**: `get-note`, `list-notes`, `search-notes`
- **Edge cases**: Note in subfolder, note with special chars in name, empty vault, note without .md extension, note with frontmatter
- **Expected test count**: 12

### Group 5: Frontmatter Parsing
- **What is being tested**: `get-note-frontmatter`
- **Edge cases**: No frontmatter, frontmatter with lists, boolean values, numeric values, empty frontmatter block, frontmatter with tags field
- **Expected test count**: 6

### Group 6: Tags
- **What is being tested**: `get-note-tags`, `get-vault-tags`
- **Edge cases**: Inline tags, frontmatter tags, tags in code blocks (should be excluded), mixed tag sources, no tags, nested/hierarchical tags (tag/subtag)
- **Expected test count**: 8

### Group 7: Links and Backlinks
- **What is being tested**: `get-note-links`, `get-backlinks`
- **Edge cases**: Wikilinks with aliases, wikilinks with headings, links in code blocks (should be excluded), no links, multiple links to same target, self-referencing link
- **Expected test count**: 10

### Group 8: Headings
- **What is being tested**: `get-note-headings`
- **Edge cases**: Multiple heading levels (h1-h6), no headings, headings in code blocks (should be excluded)
- **Expected test count**: 5

### Group 9: Settings and Appearance
- **What is being tested**: `app-settings`, `appearance`
- **Edge cases**: Specific key lookup, non-existent key, full settings dump
- **Expected test count**: 8

### Group 10: Hotkeys
- **What is being tested**: `hotkeys`
- **Edge cases**: Custom hotkey overrides, empty hotkeys file
- **Expected test count**: 3

### Group 11: Plugins
- **What is being tested**: `community-plugins`, `core-plugins`, `plugin-settings`
- **Edge cases**: No community plugins, non-existent plugin settings, core plugins as list vs dict
- **Expected test count**: 7

### Group 12: Workspace
- **What is being tested**: `workspace`
- **Edge cases**: workspace.json vs workspace-v2.json, missing workspace file
- **Expected test count**: 3

### Group 13: Bookmarks
- **What is being tested**: `bookmarks`
- **Edge cases**: Empty bookmarks, bookmarks.json vs starred.json (legacy), missing file
- **Expected test count**: 3

### Group 14: Vault Structure
- **What is being tested**: `list-folders`
- **Edge cases**: Nested folders, .obsidian excluded, empty vault
- **Expected test count**: 4

### Group 15: Check-* Positive Cases
- **What is being tested**: All check-* endpoints returning true/positive
- **Edge cases**: Various matching conditions
- **Expected test count**: 15

### Group 16: Check-* Negative Cases
- **What is being tested**: All check-* endpoints returning false/negative
- **Edge cases**: Close-but-not-matching values, wrong types, non-existent targets
- **Expected test count**: 15

### Group 17: JSON Validity Sweep
- **What is being tested**: Every CLI command outputs valid JSON
- **Expected test count**: 30+

## Test Fixtures

### Vault: `/home/user/test-vault/`

#### Notes
| File | Contents | Used by |
|------|----------|---------|
| `Welcome.md` | Frontmatter (title, tags, date), H1, H2, inline tags, wikilinks | Groups 4-8, 15-16 |
| `Projects/Project Alpha.md` | Frontmatter (status, priority), links to team notes, multiple headings | Groups 4-8, 15-16 |
| `Projects/Project Beta.md` | Minimal note, link to Project Alpha | Groups 7, 15-16 |
| `Daily/2024-01-15.md` | Frontmatter (date, tags), links to projects, inline tags | Groups 4-8, 15-16 |
| `Templates/Meeting.md` | Template with placeholders, no frontmatter | Groups 4-5, 15-16 |
| `Empty Note.md` | Empty file | Groups 4, 15-16 |
| `Code Examples.md` | Tags and links inside code blocks (should be excluded) | Groups 6-7 |

#### Folders
| Folder | Purpose |
|--------|---------|
| `Projects/` | Subfolder with notes |
| `Projects/Active/` | Nested subfolder |
| `Daily/` | Daily notes folder |
| `Templates/` | Template notes |

#### Config files (`.obsidian/`)
| File | Contents | Used by |
|------|----------|---------|
| `app.json` | `{"spellcheck": true, "readableLineLength": true, "strictLineBreaks": false, "foldHeading": true}` | Groups 9, 15-16 |
| `appearance.json` | `{"baseFontSize": 16, "theme": "obsidian", "cssTheme": "Minimal", "accentColor": "#7C3AED"}` | Groups 9, 15-16 |
| `hotkeys.json` | `{"editor:toggle-bold": [{"modifiers": ["Mod"], "key": "B"}], "app:go-back": [{"modifiers": ["Alt"], "key": "ArrowLeft"}]}` | Groups 10, 15-16 |
| `community-plugins.json` | `["dataview", "templater-obsidian", "calendar"]` | Groups 11, 15-16 |
| `core-plugins.json` | `{"file-explorer": true, "graph": true, "search": true, "tag-pane": false}` | Groups 11, 15-16 |
| `workspace.json` | `{"main": {"type": "split"}, "left": {"collapsed": false}, "active": "Welcome.md"}` | Group 12 |
| `bookmarks.json` | `{"items": [{"type": "file", "path": "Welcome.md"}, {"type": "file", "path": "Projects/Project Alpha.md"}]}` | Group 13 |
| `plugins/dataview/data.json` | `{"refreshInterval": 1000, "renderNullAs": "\\-"}` | Group 11 |

## Edge Cases & Error Handling Matrix

| Scenario | Endpoint(s) | Expected behavior |
|---|---|---|
| Vault path doesn't exist | all vault endpoints | `{"error": "Vault not found: ..."}` |
| Note doesn't exist | get-note, check-note-* | `{"error": "Note not found: ..."}` |
| Missing required argument | check-* endpoints | exit 1 + `{"error": "Missing required argument..."}` |
| Unknown subcommand | any | exit 1 + `{"error": "Unknown command: ..."}` |
| Missing vault_path arg | all except global-config | exit 1 + `{"error": "Missing vault_path..."}` |
| Empty note file | get-note, frontmatter, tags | Empty content, no frontmatter, no tags |
| Config file missing | app-settings, appearance, etc. | `{"error": "File not found: ..."}` |
| Tags in code blocks | get-note-tags | Tags inside ``` blocks excluded |
| Links in code blocks | get-note-links | Links inside ``` blocks excluded |
| Note name with spaces | get-note, check-note-* | Resolved correctly |
| Note in subfolder | get-note, check-note-* | Resolved by recursive search |

## Positive / Negative Case Pairs

| Endpoint | Positive fixture | Negative fixture |
|---|---|---|
| `check-note-exists` | "Welcome" (exists) | "Nonexistent Note 12345" |
| `check-note-contains` | "Welcome" + text that's in it | "Welcome" + text that's not in it |
| `check-note-has-tag` | "Welcome" + tag it has | "Welcome" + tag it doesn't have |
| `check-note-has-frontmatter` | "Welcome" + "title" key | "Welcome" + "nonexistent_key" |
| `check-note-links-to` | "Welcome" + linked target | "Welcome" + unlinked target |
| `check-note-has-heading` | "Welcome" + existing heading | "Welcome" + non-existing heading |
| `check-folder-exists` | "Projects" (exists) | "Nonexistent Folder 12345" |
| `check-plugin-enabled` | "dataview" (enabled) | "nonexistent-plugin-12345" |
| `check-setting` | "spellcheck" + "true" | "spellcheck" + "false" |
| `check-hotkey` | "editor:toggle-bold" (has binding) | "nonexistent:command-12345" |
| `check-theme` | "Minimal" (matches cssTheme) | "Nonexistent Theme 12345" |

## JSON Validity Sweep

Commands tested for valid JSON output:

**No-arg commands (just vault path):**
- `list-notes`, `get-vault-tags`, `app-settings`, `appearance`, `hotkeys`, `community-plugins`, `core-plugins`, `workspace`, `bookmarks`, `list-folders`, `global-config`

**Commands with note arg:**
- `get-note Welcome`, `get-note-frontmatter Welcome`, `get-note-tags Welcome`, `get-note-links Welcome`, `get-note-headings Welcome`, `get-backlinks Welcome`, `search-notes meeting`

**Commands with key arg:**
- `app-settings spellcheck`, `appearance baseFontSize`, `plugin-settings dataview`

**Check commands:**
- `check-note-exists Welcome`, `check-note-contains Welcome hello`, `check-note-has-tag Welcome project`, `check-note-has-frontmatter Welcome title`, `check-note-links-to Welcome "Project Alpha"`, `check-note-has-heading Welcome "Welcome"`, `check-folder-exists Projects`, `check-plugin-enabled dataview`, `check-setting spellcheck true`, `check-hotkey editor:toggle-bold`, `check-theme Minimal`, `check-file-exists /home/user/test-vault/Welcome.md`

## Summary

| Metric | Count |
|---|---|
| Test groups | 17 |
| Total assertions | ~135 |
| Test fixtures (files generated) | 7 notes + 8 config files + 4 folders |
| `check-*` endpoints with pos+neg pairs | 11 |
| Error scenarios covered | 11 |
