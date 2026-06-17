---
name: >-
  cli-anything-shotcut
description: >-
  Command-line interface for Shotcut projects, timelines, effects, exports, and deterministic local artifacts.
---

# cli-anything-shotcut

A command-line interface for creating and editing Shotcut/MLT video projects, plus deterministic local artifacts for project, config, and export verification.

## Installation

This CLI is installed as part of the cli-anything-shotcut package:

```bash
pip install cli-anything-shotcut
```

**Prerequisites:**
- Python 3.10+
- `ffmpeg`/`ffprobe` are required for media probing, thumbnails, and export files

## Usage

### Basic Commands

```bash
# Show help
cli-anything-shotcut --help

# Start interactive REPL mode
cli-anything-shotcut

# Run with JSON output
cli-anything-shotcut --json artifact create-mlt /tmp/project.mlt --fps 30
```

### REPL Mode

When invoked without a subcommand, the CLI enters an interactive REPL session:

```bash
cli-anything-shotcut
```

## Command Groups

### Project

Project management commands.

| Command | Description |
|---------|-------------|
| `new` | Create a new blank project |
| `open` | Open an existing `.mlt` project |
| `save` | Save the current project |
| `info` | Show project information |
| `profiles` | List available video profiles |
| `xml` | Print raw MLT XML |

### Timeline

Timeline operations.

| Command | Description |
|---------|-------------|
| `show` | Show timeline overview |
| `tracks` | List all tracks |
| `add-track` | Add a track |
| `remove-track` | Remove a track |
| `add-clip` | Add a media clip to a track |
| `remove-clip` | Remove a clip from a track |
| `move-clip` | Move a clip between tracks or positions |
| `trim` | Trim a clip's in/out points |
| `split` | Split a clip |
| `clips` | List clips on a track |
| `add-blank` | Add a blank gap |
| `set-name` | Set a track name |
| `mute` | Mute or unmute a track |
| `hide` | Hide or unhide a video track |

### Filter

Filter operations.

| Command | Description |
|---------|-------------|
| `list-available` | List available filters |
| `info` | Show filter details |
| `add` | Add a filter |
| `remove` | Remove a filter |
| `set` | Set a filter parameter |
| `list` | List active filters |
| `volume-envelope` | Set a keyframed volume envelope |
| `duck` | Apply a ducking volume envelope |

### Media

Media file operations.

| Command | Description |
|---------|-------------|
| `probe` | Analyze a media file |
| `list` | List project media |
| `check` | Check referenced media files |
| `thumbnail` | Generate a thumbnail |

### Export

Export/render commands.

| Command | Description |
|---------|-------------|
| `presets` | List export presets |
| `preset-info` | Show export preset details |
| `render` | Render the project to a video file |

### Artifact

Deterministic local artifact commands.

| Command | Description |
|---------|-------------|
| `create-mlt` | Create a deterministic MLT project file |
| `add-clip` | Add a deterministic clip to an existing MLT file |
| `config-set` | Set a value in `Shotcut.conf` |
| `recent-add` | Add a recent file entry to `Shotcut.conf` |
| `export-sample` | Create a small valid video export file |

### Transition

Transition operations.

| Command | Description |
|---------|-------------|
| `list-available` | List available transition types |
| `info` | Show transition details |
| `add` | Add a transition |
| `remove` | Remove a transition |
| `set` | Set a transition parameter |
| `list` | List timeline transitions |

### Composite

Compositing operations.

| Command | Description |
|---------|-------------|
| `blend-modes` | List available blend modes |
| `set-blend` | Set a track blend mode |
| `get-blend` | Get a track blend mode |
| `set-opacity` | Set track opacity |
| `pip` | Set picture-in-picture position |

### Session

Session management commands.

| Command | Description |
|---------|-------------|
| `status` | Show session status |
| `undo` | Undo the last operation |
| `redo` | Redo the last undone operation |
| `save` | Save session state |
| `list` | List saved sessions |

### REPL

Interactive session command.

| Command | Description |
|---------|-------------|
| `repl` | Start interactive REPL session |

## Examples

```bash
cli-anything-shotcut --json artifact create-mlt /tmp/project.mlt --width 1920 --height 1080 --fps 30 --clip clip1=/tmp/intro.mp4=Intro --playlist playlist0=clip1 --track playlist0

cli-anything-shotcut --project /tmp/project.mlt -s timeline add-track --type video --name V1
```

## Output Formats

All commands support dual output modes:

- Human-readable output by default
- Machine-readable JSON with `--json`

## Version

2.0.0
