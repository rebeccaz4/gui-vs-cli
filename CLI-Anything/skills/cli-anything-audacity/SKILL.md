---
name: cli-anything-audacity
description: Command-line interface for Audacity-style project editing, tracks, clips, labels, effects, preferences, media analysis, and export.
---

# cli-anything-audacity

A stateful command-line interface for audio project editing, Audacity `.aup` import/export, preference files, media analysis, and rendered audio export.

## Usage

```bash
cli-anything-audacity --help
cli-anything-audacity --json <command-group> <command> [args/options]
cli-anything-audacity --project project.json <command-group> <command> [args/options]
```

Use `--json` for machine-readable output.

## Command Groups

### Project

Project management commands.

| Command | Description |
|---------|-------------|
| `new` | Create a new project |
| `open` | Open an existing project |
| `save` | Save the current project |
| `info` | Show project information |
| `settings` | View or update project settings |
| `json` | Print raw project JSON |
| `import-aup` | Import an Audacity `.aup` project |

### Track

Track management commands.

| Command | Description |
|---------|-------------|
| `add` | Add a new track |
| `remove` | Remove a track by index |
| `list` | List all tracks |
| `set` | Set a track property |

### Clip

Clip management commands.

| Command | Description |
|---------|-------------|
| `import` | Probe/import an audio file |
| `add` | Add an audio clip to a track |
| `remove` | Remove a clip from a track |
| `trim` | Trim a clip |
| `split` | Split a clip |
| `move` | Move a clip |
| `list` | List clips on a track |

### Effect

Effect management commands.

| Command | Description |
|---------|-------------|
| `list-available` | List available effects |
| `info` | Show effect details |
| `add` | Add an effect to a track |
| `remove` | Remove an effect |
| `set` | Set an effect parameter |
| `list` | List effects on a track |

### Selection

Selection management commands.

| Command | Description |
|---------|-------------|
| `set` | Set selection range |
| `all` | Select all |
| `none` | Clear selection |
| `info` | Show current selection |

### Label

Label and marker commands.

| Command | Description |
|---------|-------------|
| `add` | Add a label |
| `remove` | Remove a label |
| `list` | List labels |

### Media

Media file operations.

| Command | Description |
|---------|-------------|
| `probe` | Analyze an audio file |
| `check` | Check referenced media files |
| `analyze` | Analyze WAV level and frequency content |

### Export

Export and render commands.

| Command | Description |
|---------|-------------|
| `presets` | List export presets |
| `preset-info` | Show preset details |
| `render` | Render the project to audio |
| `aup` | Export the project to Audacity `.aup` XML |

### Preference

Audacity preference file commands.

| Command | Description |
|---------|-------------|
| `get` | Get a preference value |
| `list` | List preferences |
| `set` | Set a preference value |
| `list-sections` | List preference sections |
| `create-default` | Create a default `audacity.cfg` |
| `exists` | Check whether a preference exists |
| `delete` | Delete a preference value |

### Session

Session management commands.

| Command | Description |
|---------|-------------|
| `status` | Show session status |
| `undo` | Undo the last operation |
| `redo` | Redo the last undone operation |
| `history` | Show undo history |

### Eval

Evaluation command.

| Command | Description |
|---------|-------------|
| `eval` | Run evaluation tasks and generate reports |

### Repl

Interactive mode.

| Command | Description |
|---------|-------------|
| `repl` | Start interactive REPL session |

## Examples

```bash
cli-anything-audacity --json project new --name Podcast -o project.json

cli-anything-audacity media analyze output.wav
```

## Notes

- `export aup` writes Audacity `.aup` XML and matching `_data` directory.
- `project import-aup` supports editing an existing `.aup` by importing it to project JSON, changing it, then exporting it again.
- `preference` commands read and write Audacity `audacity.cfg`.

## Version

2.0.0
