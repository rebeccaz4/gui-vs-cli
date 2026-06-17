---
name: "cli-anything-gimp"
description: >-
  Command-line interface for GIMP-style image projects, layered rendering, exported image inspection workflows, gimprc preferences, and Script-Fu-compatible live verifier state.
---

# cli-anything-gimp

A stateful command-line interface for image editing. It stores projects as JSON, renders images through GIMP or Pillow, manages layers/canvas/filter/draw operations, writes `gimprc` preferences, and can serve deterministic Script-Fu-compatible live state.

## Installation

This CLI is installed as part of the cli-anything-gimp package:

```bash
pip install cli-anything-gimp
```

**Prerequisites:**
- Python 3.10+
- Pillow or GIMP for image export
- No GIMP GUI is required for JSON project editing, Pillow rendering, `preferences`, or `live` state commands

## Usage

### Basic Commands

```bash
cli-anything-gimp --help
cli-anything-gimp
cli-anything-gimp project new -o project.json
cli-anything-gimp --json --project project.json project info
```

### REPL Mode

When invoked without a subcommand, the CLI enters an interactive REPL session:

```bash
cli-anything-gimp
```

## Command Groups

### Project

Project management commands.

| Command | Description |
|---------|-------------|
| `new` | Create a new project |
| `open` | Open an existing project |
| `save` | Save the current project |
| `info` | Show project information |
| `profiles` | List available canvas profiles |
| `json` | Print raw project JSON |

### Layer

Layer management commands.

| Command | Description |
|---------|-------------|
| `new` | Create a new blank layer |
| `add-from-file` | Add a layer from an image file |
| `list` | List layers |
| `remove` | Remove a layer by index |
| `duplicate` | Duplicate a layer |
| `move` | Move a layer to a new position |
| `set` | Set a layer property |
| `flatten` | Flatten visible layers at export time |
| `merge-down` | Merge a layer down at export time |

### Canvas

Canvas operations.

| Command | Description |
|---------|-------------|
| `info` | Show canvas information |
| `resize` | Resize the canvas without scaling content |
| `scale` | Scale the canvas and content |
| `crop` | Crop the canvas |
| `mode` | Set the canvas color mode |
| `dpi` | Set the canvas DPI |

### Filter

Filter management commands.

| Command | Description |
|---------|-------------|
| `list-available` | List available filters |
| `info` | Show details about a filter |
| `add` | Add a filter to a layer |
| `remove` | Remove a filter by index |
| `set` | Set a filter parameter |
| `list` | List filters on a layer |

### Media

Media file operations.

| Command | Description |
|---------|-------------|
| `probe` | Analyze an image file |
| `list` | List media files referenced in the project |
| `check` | Check referenced media files |
| `histogram` | Show image histogram data |

### Export

Export/render commands.

| Command | Description |
|---------|-------------|
| `presets` | List export presets |
| `preset-info` | Show preset details |
| `render` | Render the project to an image file |

### Draw

Drawing operations applied at render time.

| Command | Description |
|---------|-------------|
| `text` | Add persisted text drawing to a layer |
| `rect` | Add persisted rectangle drawing to a layer |

### Preferences

GIMP `gimprc` preference commands.

| Command | Description |
|---------|-------------|
| `set` | Set a `gimprc` preference value |

### Live

Script-Fu-compatible live state commands.

| Command | Description |
|---------|-------------|
| `create-state` | Create a live-state JSON file |
| `serve` | Serve live state over the Script-Fu TCP protocol |

### Session

Session management commands.

| Command | Description |
|---------|-------------|
| `status` | Show session status |
| `undo` | Undo the last operation |
| `redo` | Redo the last undone operation |
| `history` | Show undo history |

### Repl

Interactive session command.

| Command | Description |
|---------|-------------|
| `repl` | Start interactive REPL session |

## Examples

```bash
cli-anything-gimp --json project new -o project.json --width 640 --height 480 --background "#ff0000"
cli-anything-gimp --json live create-state -o live_state.json --name photo.png --width 640 --height 480 --mode RGBA --layer-name Background --pixel 255,0,0,255
```

## State Management

- Project state is stored in `.gimp-cli.json` files.
- One-shot commands auto-save modified project state when `--project` is provided.
- `live serve` reads a generated state file and exposes it over Script-Fu-compatible TCP.

## Output Modes

- Human-readable output by default
- JSON output with `--json`
