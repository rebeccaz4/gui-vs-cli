---
name: cli-anything-obs-studio
description: Command-line interface for OBS Studio scene collection, source, audio, output, native config artifact, and live websocket control.
---

# cli-anything-obs-studio

A command-line interface for OBS Studio project JSON editing, OBS-native scene/profile/config artifact generation, and live OBS websocket control.

## Usage

```bash
cli-anything-obs-studio --help
cli-anything-obs-studio --json <command-group> <command> [args/options]
cli-anything-obs-studio --project project.json <command-group> <command> [args/options]
```

Use `--json` for machine-readable output.

## Command Groups

### Project

Project management commands.

| Command | Description |
|---------|-------------|
| `new` | Create a new project JSON |
| `open` | Open an existing project |
| `save` | Save the current project |
| `info` | Show project information |
| `json` | Print raw project JSON |

### Scene

Scene management commands.

| Command | Description |
|---------|-------------|
| `add` | Add a new scene |
| `remove` | Remove a scene by index |
| `duplicate` | Duplicate a scene |
| `set-active` | Set the active scene |
| `list` | List all scenes |

### Source

Source management commands.

| Command | Description |
|---------|-------------|
| `add` | Add a source to a scene |
| `remove` | Remove a source by index |
| `duplicate` | Duplicate a source |
| `set` | Set a source property |
| `transform` | Transform a source |
| `list` | List sources in a scene |

### Filter

Filter management commands.

| Command | Description |
|---------|-------------|
| `add` | Add a filter to a source |
| `remove` | Remove a filter from a source |
| `set` | Set a filter parameter |
| `list` | List filters on a source |
| `list-available` | List available filter types |

### Audio

Audio source commands.

| Command | Description |
|---------|-------------|
| `add` | Add a global audio source |
| `remove` | Remove a global audio source |
| `volume` | Set audio volume |
| `mute` | Mute an audio source |
| `unmute` | Unmute an audio source |
| `monitor` | Set audio monitoring |
| `list` | List audio sources |

### Transition

Transition management commands.

| Command | Description |
|---------|-------------|
| `add` | Add a transition |
| `remove` | Remove a transition |
| `set-active` | Set the active transition |
| `duration` | Set transition duration |
| `list` | List transitions |

### Output

Output, streaming, and recording configuration commands.

| Command | Description |
|---------|-------------|
| `streaming` | Configure streaming settings |
| `recording` | Configure recording settings |
| `settings` | Configure output settings |
| `info` | Show output configuration |
| `presets` | List encoding presets |

### Session

Session management commands.

| Command | Description |
|---------|-------------|
| `status` | Show session status |
| `undo` | Undo the last operation |
| `redo` | Redo the last undone operation |
| `history` | Show undo history |

### Artifact

OBS-native scene collection, profile, and config artifact commands.

| Command | Description |
|---------|-------------|
| `create-collection` | Create an OBS scene collection JSON |
| `add-scene` | Add a scene to a collection |
| `add-source` | Add or update a source definition |
| `add-scene-item` | Attach a source to a scene |
| `set-scene-item` | Update scene item flags |
| `add-filter` | Add or update a source filter |
| `add-transition` | Add or update a transition |
| `set-meta` | Set collection metadata |
| `set-hotkey` | Set a global hotkey |
| `set-source-hotkey` | Set a source hotkey |
| `create-profile` | Create an OBS profile |
| `profile-set` | Set a profile `basic.ini` value |
| `service-set` | Write profile `service.json` |
| `global-set` | Set `user.ini` or `global.ini` value |

### Live

Live OBS websocket commands.

| Command | Description |
|---------|-------------|
| `scenes` | List live scenes |
| `sources` | List live sources |
| `status` | Show recording and streaming status |
| `current-scene` | Show current program scene |
| `set-current-scene` | Set current program scene |
| `start-recording` | Start recording |
| `stop-recording` | Stop recording |
| `start-streaming` | Start streaming |
| `stop-streaming` | Stop streaming |

## Examples

```bash
cli-anything-obs-studio artifact create-collection Main --config-dir /tmp/obs-config

cli-anything-obs-studio --json --project project.json source add browser --name Chat -S url=https://example.com
```

## Notes

- `artifact` commands write OBS-native files that OBS and verifiers can read.
- `live` commands require OBS running with websocket enabled.

## Version

2.0.0
