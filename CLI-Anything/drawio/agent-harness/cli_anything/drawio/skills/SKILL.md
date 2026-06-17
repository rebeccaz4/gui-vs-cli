---
name: "cli-anything-drawio"
description: >-
  Command-line interface for Draw.io diagram creation, editing, page management, connector styling, and export.
---

# cli-anything-drawio

A CLI harness for Draw.io `.drawio` files. It creates and edits verifier-readable XML diagrams from the command line, including pages, shapes, connectors, labels, geometry, and styles.

## Installation

This CLI is installed as part of the cli-anything-drawio package:

```bash
pip install cli-anything-drawio
```

**Prerequisites:**
- Python 3.10+
- No Draw.io GUI is required for `.drawio` XML creation and editing
- Draw.io desktop may be required for non-XML render/export formats, depending on environment

## Usage

### Basic Commands

```bash
# Show help
cli-anything-drawio --help

# Start interactive REPL mode
cli-anything-drawio

# Create a new .drawio file
cli-anything-drawio project new -o diagram.drawio

# Run with JSON output and open an existing project
cli-anything-drawio --json --project diagram.drawio project info
```

### REPL Mode

When invoked without a subcommand, the CLI enters an interactive REPL session:

```bash
cli-anything-drawio
# Enter commands interactively with tab-completion and history
```

## Command Groups

### Project

Project management commands.

| Command | Description |
|---------|-------------|
| `new` | Create a new blank diagram |
| `open` | Open an existing `.drawio` file |
| `save` | Save the current project |
| `info` | Show project information |
| `xml` | Print the raw `.drawio` XML |
| `presets` | List available page size presets |

### Shape

Shape and vertex commands.

| Command | Description |
|---------|-------------|
| `add` | Add a shape to a page |
| `remove` | Remove a shape by ID |
| `list` | List shapes on a page |
| `label` | Update a shape label |
| `move` | Move a shape |
| `resize` | Resize a shape |
| `style` | Set a shape style property |
| `info` | Show shape information |
| `types` | List available shape types |

### Connect

Connector and edge commands.

| Command | Description |
|---------|-------------|
| `add` | Add a connector between two shapes |
| `remove` | Remove a connector by ID |
| `label` | Update a connector label |
| `style` | Set a connector style property |
| `list` | List connectors on a page |
| `styles` | List available connector styles |

### Page

Page commands.

| Command | Description |
|---------|-------------|
| `add` | Add a new page |
| `remove` | Remove a page by index |
| `rename` | Rename a page |
| `list` | List pages |

### Export

Export commands.

| Command | Description |
|---------|-------------|
| `render` | Export the diagram to a file |
| `formats` | List available export formats |

### Session

Session management commands.

| Command | Description |
|---------|-------------|
| `status` | Show session status |
| `undo` | Undo the last operation |
| `redo` | Redo the last undone operation |
| `save-state` | Save session state to disk |
| `list` | List saved sessions |

## Examples


```bash
cli-anything-drawio --json --project flow.drawio page list

cli-anything-drawio --project flow.drawio export render flow.xml --format xml --overwrite
```

## State Management

The CLI maintains session state with:

- **Project persistence**: save/load `.drawio` XML files
- **Session tracking**: save and list session state

## Output Formats

All commands support dual output modes:

- **Human-readable** output by default
- **Machine-readable** JSON with `--json`

## Version

1.0.0
