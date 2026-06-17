---
name: >-
  cli-anything-obsidian
description: >-
  Command-line interface for Obsidian vault notes, search, commands, and local vault artifacts.
---

# cli-anything-obsidian

A command-line interface for Obsidian note workflows and local vault files, including Markdown notes, vault config, plugins, workspace, bookmarks, and global config.

## Installation

This CLI is installed as part of the cli-anything-obsidian package:

```bash
pip install cli-anything-obsidian
```

**Prerequisites:**
- Python 3.10+
- Obsidian Local REST API setup is required for REST API commands
- Local vault artifact commands do not require Obsidian to be running

## Usage

### Basic Commands

```bash
# Show help
cli-anything-obsidian --help

# Start interactive REPL mode
cli-anything-obsidian

# Run with JSON output
cli-anything-obsidian --json local write-note /tmp/vault Welcome.md --content "# Welcome"
```

### REPL Mode

When invoked without a subcommand, the CLI enters an interactive REPL session:

```bash
cli-anything-obsidian
```

## Command Groups

### Vault

REST API vault file operations.

| Command | Description |
|---------|-------------|
| `list` | List files and folders in the vault |
| `read` | Read a note's content |
| `create` | Create a new note |
| `update` | Update an existing note |
| `delete` | Delete a note from the vault |
| `append` | Append or prepend content to a note |

### Local

Local vault file and config commands.

| Command | Description |
|---------|-------------|
| `init` | Create a local vault and `.obsidian` directory |
| `write-note` | Create or replace a local note |
| `append-note` | Append or prepend content to a local note |
| `mkdir` | Create a folder under a local vault |
| `write-file` | Create or replace a local file |
| `config-write` | Write an Obsidian config JSON file |
| `config-set` | Set a key in an Obsidian config JSON file |
| `plugin-enable` | Enable or disable a plugin config entry |
| `plugin-setting` | Set a community plugin setting |
| `hotkey-set` | Set a hotkey binding |
| `bookmark-add` | Add a bookmark entry |
| `workspace-set` | Write workspace state |
| `global-config-set` | Set a key in global `obsidian.json` |

### Search

REST API search operations.

| Command | Description |
|---------|-------------|
| `query` | Search using Obsidian query syntax |
| `simple` | Plain text search across the vault |

### Note

REST API active note operations.

| Command | Description |
|---------|-------------|
| `active` | Get the currently active note |
| `open` | Open a note in Obsidian |

### Command

Obsidian command operations.

| Command | Description |
|---------|-------------|
| `list` | List available Obsidian commands |
| `execute` | Execute an Obsidian command by ID |

### Server

REST API server commands.

| Command | Description |
|---------|-------------|
| `status` | Check if the Obsidian REST API is running |

### Session

Session state commands.

| Command | Description |
|---------|-------------|
| `status` | Show current session state |

### REPL

Interactive session command.

| Command | Description |
|---------|-------------|
| `repl` | Start interactive REPL session |

## Examples

```bash
cli-anything-obsidian --json local write-note /tmp/vault Welcome.md --content "# Welcome"

cli-anything-obsidian --api-key "$OBSIDIAN_API_KEY" --json search simple "meeting notes"
```

## Output Formats

All commands support dual output modes:

- Human-readable output by default
- Machine-readable JSON with `--json`

## Version

2.0.0
