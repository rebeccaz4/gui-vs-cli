# Zotero Verifier

Programmatic state inspection for Zotero — the Mozilla XULRunner-based reference
manager. The verifier runs inside the E2B sandbox and returns JSON describing
items, collections, tags, creators, attachments, notes, and preferences, so RL
tasks can be checked deterministically.

## Verification channels

| Channel | What it covers |
|---|---|
| `~/Zotero/zotero.sqlite` | Main library: items, collections, tags, creators, attachments metadata, notes, trash |
| `~/Zotero/storage/<key>/` | File attachments on disk (PDFs etc.) |
| `~/.zotero/zotero/*.default*/prefs.js` | Zotero Mozilla-style user preferences |
| BibTeX file parsing | Post-export verification of BibTeX files the agent saves |

Zotero holds its SQLite DB open while running, so every query copies the file
first (`zotero.sqlite` + optional `-wal`/`-shm`) before reading.

### Skipped categories

These are documented so task generators know not to write tasks that depend on
them:

- **UI layout / window state** — stored in Mozilla `xulstore.json` with opaque
  schema; no reliable way to read it back.
- **Sync / network state** — only the configured sync username is visible in
  prefs; there is no endpoint for live sync status.
- **History / undo history** — Zotero has no persistent action history.
- **Keybindings** — Zotero has no user-customizable keybinding file.

## Prerequisites

- Zotero data directory at `~/Zotero/` (default) containing `zotero.sqlite`.
  Override with `ZOTERO_DATA_DIR=/path/to/data`.
- Optional: Mozilla profile at `~/.zotero/zotero/<rand>.default*/prefs.js`.
  Override with `ZOTERO_PROFILE_DIR=/path/to/profile`.
- Zotero does **not** need to be running for verification — the verifier reads
  the SQLite file directly.

## CLI

```
python3 /home/user/verifiers/zotero.py <command> [args...]
```

All commands return JSON on stdout. Errors are returned as `{"error": "..."}`
with a non-zero exit code for dispatch errors (missing args, unknown command).

### Library / profile

| Command | Returns |
|---|---|
| `data-dir` | `{path, exists, has_sqlite, has_storage}` |
| `library-stats` | `{items, attachments, notes, collections, tags, deleted_items}` |

### Collections

| Command | Args | Returns |
|---|---|---|
| `collections` | — | list of `{collectionID, collectionName, parentCollectionID, item_count, ...}` |
| `collection-items` | `<name>` | list of items in collection (by name) |
| `check-collection-exists` | `<name>` | `{exists, matches}` |
| `check-collection-count` | `<name> <expected>` | `{match, expected, actual}` |
| `check-collection-contains` | `<collection> <title_substr>` | `{contains, match_count, matches}` |
| `check-subcollection` | `<parent> <child>` | `{is_subcollection, matches}` |

### Items

| Command | Args | Returns |
|---|---|---|
| `items` | `[limit]` | list of items: `{itemID, key, typeName, title, dateAdded, ...}` |
| `item-count` | — | `{count}` |
| `item-fields` | `<title_substr>` | `{itemID, key, typeName, title, fields}` |
| `check-item-exists` | `<title_substr>` | `{exists, match_count, matches}` |
| `check-item-field` | `<title_substr> <field> <expected>` | `{match, expected, actual}` |
| `check-item-type` | `<title_substr> <type>` | `{match, expected, actual}` |
| `check-item-count` | `<expected>` | `{match, expected, actual}` |

Common Zotero fields: `title`, `date`, `DOI`, `publicationTitle`, `url`,
`abstractNote`, `pages`, `volume`, `issue`, `publisher`, `place`, `ISBN`,
`ISSN`, `language`, `edition`, `shortTitle`. Common types: `book`,
`journalArticle`, `webpage`, `conferencePaper`, `thesis`, `report`, `document`.

### Creators

| Command | Args | Returns |
|---|---|---|
| `item-creators` | `<title_substr>` | list of creators (author/editor/etc.) |
| `check-item-creator` | `<title_substr> <last_name>` | `{has_creator, match_count, creators}` |
| `check-item-creator-count` | `<title_substr> <expected>` | `{match, expected, actual}` |

### Tags

| Command | Args | Returns |
|---|---|---|
| `tags` | — | list of `{tagID, name, item_count}` |
| `check-tag-exists` | `<name>` | `{exists, matches}` |
| `item-tags` | `<title_substr>` | list of `{name, type}` |
| `check-item-tag` | `<title_substr> <tag>` | `{has_tag, tag_count, all_tags}` |

### Attachments

| Command | Args | Returns |
|---|---|---|
| `attachments` | `[limit]` | list of attachment items + parent titles |
| `check-item-attachment` | `<title_substr>` | `{has_attachment, count, itemID}` |
| `check-attachment-file` | `<attachment_key>` | `{exists, path, files, file_count}` |

### Notes

| Command | Args | Returns |
|---|---|---|
| `notes` | `[limit]` | list of notes with parent title |
| `check-note-contains` | `<text>` | `{contains, match_count, matches}` |
| `check-item-note` | `<title_substr>` | `{has_note, count}` |

### Trash

| Command | Args | Returns |
|---|---|---|
| `trash` | `[limit]` | list of items in trash |
| `check-item-in-trash` | `<title_substr>` | `{in_trash, match_count, matches}` |

### Preferences

| Command | Args | Returns |
|---|---|---|
| `prefs` | `[key]` | all keys (overview) or `{key, value}` |
| `prefs-matching` | `<substring>` | `{pattern, count, matches}` |
| `check-pref-value` | `<key> <expected>` | `{match, expected, actual}` |

Common keys:
- `extensions.zotero.export.quickCopy.setting` — default quick copy style.
- `extensions.zotero.export.bibliographyLocale` — citation locale (e.g. `en-US`).
- `extensions.zotero.note.fontSize` — note font size.
- `extensions.zotero.recursiveCollections` — include subcollection items.

### BibTeX / file I/O

| Command | Args | Returns |
|---|---|---|
| `parse-bibtex` | `<path>` | `{count, entries, path}` |
| `check-bibtex-count` | `<path> <expected>` | `{match, expected, actual}` |
| `check-bibtex-title` | `<path> <title_substr>` | `{contains, match_count, entries}` |
| `check-file-exists` | `<path>` | `{exists, path, size_bytes, is_file, is_dir}` |

## Common verification patterns

Check that the agent added a new collection named "Machine Learning":

```python
{"command": "check-collection-exists 'Machine Learning'", "key": "exists", "expected": true}
```

Check that an item was tagged with "important":

```python
{"command": "check-item-tag 'Attention Is All You Need' important", "key": "has_tag", "expected": true}
```

Check that a BibTeX export contains three entries and a specific title:

```python
[
  {"command": "check-file-exists /home/user/export.bib", "key": "exists", "expected": true},
  {"command": "check-bibtex-count /home/user/export.bib 3", "key": "match", "expected": true},
  {"command": "check-bibtex-title /home/user/export.bib Transformer", "key": "contains", "expected": true}
]
```
