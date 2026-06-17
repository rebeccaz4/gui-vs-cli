---
name: "cli-anything-krita"
description: >-
  Command-line interface for Krita project state, layers, metadata, animation, config, and verifier-readable .kra export.
---

# cli-anything-krita

A command-line interface for creating Krita project state and exporting verifier-readable `.kra` files and `kritarc` config values.

## Installation

```bash
cd krita/agent-harness && pip install -e .
```

## Requirements

- Python 3.10+
- Krita installed for backend image export commands.

## Usage

```bash
cli-anything-krita --help
cli-anything-krita --json -p <project.json> <command-group> <command> [args/options]
```

## Command Groups

### Project

Project management commands.

| Command | Description |
|---------|-------------|
| `new` | Create a new project |
| `open` | Open an existing project JSON |
| `save` | Save the current project |
| `info` | Show project information |

### Layer

Layer commands.

| Command | Description |
|---------|-------------|
| `add` | Add a layer |
| `remove` | Remove a layer |
| `list` | List layers |
| `set` | Set a layer property |
| `add-mask` | Add a mask under a layer |
| `timeline` | Set layer timeline flags |
| `keyframes` | Set layer keyframe count |

### Filter

Filter commands.

| Command | Description |
|---------|-------------|
| `apply` | Apply a filter to a layer |
| `list` | List available filters |

### Canvas

Canvas commands.

| Command | Description |
|---------|-------------|
| `resize` | Resize canvas or resolution |
| `info` | Show canvas information |
| `background` | Set projection background color |

### Metadata

Document metadata commands.

| Command | Description |
|---------|-------------|
| `set` | Set document metadata |

### Animation

Animation metadata commands.

| Command | Description |
|---------|-------------|
| `set` | Set animation metadata |

### Proofing

Soft-proofing commands.

| Command | Description |
|---------|-------------|
| `set` | Set soft-proofing state |

### Export

Export commands.

| Command | Description |
|---------|-------------|
| `render` | Export/render through Krita backend |
| `animation` | Export animation frames |
| `kra` | Export verifier-readable `.kra` |
| `presets` | List export presets |
| `formats` | List supported formats |

### Config

Krita config commands.

| Command | Description |
|---------|-------------|
| `set` | Set a `kritarc` value |

### Session

Session commands.

| Command | Description |
|---------|-------------|
| `undo` | Undo the last operation |
| `redo` | Redo the last undone operation |
| `history` | Show session history |

### Top-Level

Top-level commands.

| Command | Description |
|---------|-------------|
| `status` | Show current status |

## Examples

```bash
cli-anything-krita --json project new -n "Painting" -w 640 -h 480 -o painting.json
cli-anything-krita --json -p painting.json export kra painting.kra --overwrite
```

## Notes

- Use `--json` for structured output.
- Use `export kra` when the final artifact must be a `.kra` file.
