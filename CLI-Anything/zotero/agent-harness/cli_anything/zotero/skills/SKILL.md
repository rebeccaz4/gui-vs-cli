---
name: "cli-anything-zotero"
description: >-
  Manage Zotero libraries, references, collections, notes, attachments,
  preferences, and exports from the command line.
---

# cli-anything-zotero

`cli-anything-zotero` provides command-line access to Zotero library data, live Zotero import APIs, profile preferences, and verifier-readable library artifacts.

## Installation

```bash
pip install -e .
```

## Entry Points

```bash
cli-anything-zotero
python -m cli_anything.zotero
```

## Usage

```bash
cli-anything-zotero [--json] [--data-dir PATH] [--profile-dir PATH] <command-group> <command> [args/options]
```

## Command Groups

### App

Application and runtime inspection commands.

| Command | Description |
|---------|-------------|
| `status` | Show Zotero paths and backend availability |
| `version` | Show CLI and Zotero version information |
| `launch` | Launch Zotero |
| `enable-local-api` | Enable Zotero Local API preference |
| `ping` | Check Connector availability |

### Library

Library import and patch commands.

| Command | Description |
|---------|-------------|
| `seed-json` | Seed or patch verifier-readable Zotero library state from JSON |

### Collection

Collection inspection and selection commands.

| Command | Description |
|---------|-------------|
| `list` | List collections |
| `find` | Find collections by text |
| `tree` | Show collection hierarchy |
| `get` | Show a collection |
| `items` | List items in a collection |
| `use-selected` | Store the collection selected in Zotero |
| `create` | Create a collection with experimental SQLite write mode |

### Item

Item inspection and rendering commands.

| Command | Description |
|---------|-------------|
| `list` | List items |
| `find` | Find items by title |
| `get` | Show an item |
| `children` | List child records |
| `notes` | List child notes |
| `attachments` | List child attachments |
| `file` | Resolve an attachment file path |
| `export` | Export one item through Zotero Local API |
| `citation` | Render one item citation |
| `bibliography` | Render one item bibliography |
| `context` | Build item context text |
| `analyze` | Analyze item context with a model |
| `add-to-collection` | Add an item to a collection with experimental SQLite write mode |
| `move-to-collection` | Move an item between collections with experimental SQLite write mode |

### Import

Official Zotero import and write commands.

| Command | Description |
|---------|-------------|
| `file` | Import RIS/BibTeX-style text through Zotero Connector |
| `json` | Import Zotero Connector item JSON |

### Note

Read and add child notes.

| Command | Description |
|---------|-------------|
| `get` | Show a note |
| `add` | Add a child note to an item |

### Preference

Zotero profile preference commands.

| Command | Description |
|---------|-------------|
| `set` | Write a Zotero `prefs.js` preference |

### Export

Export library content to files.

| Command | Description |
|---------|-------------|
| `bibtex` | Export library, collection, or title-matched items to a BibTeX file |

### Search

Saved-search inspection commands.

| Command | Description |
|---------|-------------|
| `list` | List saved searches |
| `get` | Show a saved search |
| `items` | List saved-search items |

### Tag

Tag inspection commands.

| Command | Description |
|---------|-------------|
| `list` | List tags |
| `items` | List items with a tag |

### Style

Installed CSL style inspection commands.

| Command | Description |
|---------|-------------|
| `list` | List installed CSL styles |

### Session

Session and REPL context commands.

| Command | Description |
|---------|-------------|
| `status` | Show session state |
| `use-library` | Set current library |
| `use-collection` | Set current collection |
| `use-item` | Set current item |
| `use-selected` | Store the collection selected in Zotero |
| `clear-library` | Clear current library |
| `clear-collection` | Clear current collection |
| `clear-item` | Clear current item |
| `history` | Show recent session commands |

## Examples

```bash
cli-anything-zotero --json library seed-json seed.json --clear
cli-anything-zotero --json export bibtex /tmp/library.bib --collection "AI Research"
```

## Version

0.1.0
