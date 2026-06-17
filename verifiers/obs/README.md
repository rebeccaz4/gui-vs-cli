# OBS Studio Verifier

Programmatic state inspection for OBS Studio in E2B desktop sandboxes.

## Verification Channels

| Channel | Requires OBS Running | Description |
|---------|---------------------|-------------|
| **File-based (offline)** | No | Parse scene collection JSON and profile INI files directly |
| **obs-websocket (live)** | Yes (OBS 28+) | Real-time state via WebSocket protocol on port 4455 |

## File Locations

| Path | Contents |
|------|----------|
| `~/.config/obs-studio/basic/scenes/<collection>.json` | Scene collection: full scene tree, sources, settings |
| `~/.config/obs-studio/basic/profiles/<profile>/basic.ini` | Profile config: recording path, format, encoder, video settings |

## Installation

```bash
# For live WebSocket endpoints only (file-based needs no extra deps)
pip install obsws-python
```

## CLI Usage

```bash
# From outside sandbox (via sandbox.commands.run):
sandbox.commands.run("python3 /home/user/verifiers/obs.py scenes")
sandbox.commands.run("python3 /home/user/verifiers/obs.py check-scene-exists 'Game Capture'")

# Direct CLI:
python3 obs.py scenes
python3 obs.py scene-sources "Scene 1"
python3 obs.py check-source-in-scene "Webcam" "Scene 1"
python3 obs.py live-status
```

All output is JSON to stdout.

## Commands

### File-based (no OBS needed)

| Command | Args | Description |
|---------|------|-------------|
| `scenes` | `[collection_file]` | List all scenes |
| `scene-sources` | `<scene_name> [collection_file]` | List sources in a scene |
| `sources` | `[collection_file]` | List all sources across scenes |
| `source-info` | `<source_name> [collection_file]` | Detailed source properties |
| `profiles` | | List available profiles |
| `scene-collections` | | List scene collection files |
| `recording-settings` | `[profile_name]` | Read recording settings from profile |
| `streaming-settings` | `[profile_name]` | Read streaming settings (service.json + basic.ini) |
| `global-config` | `[section] [key]` | Read ~/.config/obs-studio/{user,global}.ini |
| `source-filters` | `<source_name> [collection]` | List all filters attached to a source |
| `source-filter-info` | `<source_name> <filter_name> [collection]` | Single filter details |
| `transitions` | `[collection]` | List all transitions in a scene collection |
| `collection-meta` | `[collection]` | Top-level collection metadata (studio mode, current transition, virtual cam, replay buffer) |
| `hotkey` | `<action_key> [collection]` | Read hotkey bindings for a given action |
| `source-hotkeys` | `<source_name> [collection]` | All hotkeys attached to a source |

### Live (requires OBS running)

| Command | Args | Description |
|---------|------|-------------|
| `live-scenes` | | Get scenes via WebSocket |
| `live-sources` | | Get input sources via WebSocket |
| `live-status` | | Recording/streaming status |
| `live-scene-current` | | Get current active scene |

### Checks (return primary boolean)

| Command | Args | Description |
|---------|------|-------------|
| `check-file-exists` | `<path>` | File exists on disk |
| `check-scene-exists` | `<scene_name> [collection]` | Scene exists in collection |
| `check-source-exists` | `<source_name> [collection]` | Source exists in collection |
| `check-source-in-scene` | `<source_name> <scene_name> [collection]` | Source is in a specific scene |
| `check-scene-count` | `<count> [collection]` | Number of scenes matches |
| `check-source-visible` | `<source_name> [collection]` | Source is visible in any scene |
| `check-source-has-filter` | `<source_name> <filter_name_or_type> [collection]` | Source has named filter (or filter with matching type) |
| `check-transition-exists` | `<transition_name> [collection]` | Transition exists in collection |
| `check-recording-active` | | Live: OBS is recording |
| `check-streaming-active` | | Live: OBS is streaming |

## Python API

```python
from verifiers.obs import OBSVerifier

v = OBSVerifier()

# File-based (offline)
scenes = v.get_scenes()
sources = v.get_scene_sources("Scene 1")
info = v.get_source_info("Webcam")

# Checks
result = v.check_scene_exists("Game Capture")
# => {"exists": True, "scene_name": "Game Capture", "source_count": 5}

result = v.check_source_in_scene("Webcam", "Scene 1")
# => {"exists": True, "source_name": "Webcam", "scene_name": "Scene 1", "visible": True}

# Live (requires OBS running)
status = v.get_live_status()
# => {"recording": True, "streaming": False, "recording_time": "00:05:23"}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OBS_CONFIG_DIR` | `~/.config/obs-studio` | Override OBS config directory |
| `OBS_WS_PASSWORD` | (empty) | WebSocket server password |

## Scene Collection JSON Structure

OBS stores scene collections as JSON with this general structure:

```json
{
  "scene_order": [{"name": "Scene 1"}, {"name": "Scene 2"}],
  "sources": [
    {
      "name": "Scene 1",
      "versioned_id": "scene",
      "settings": {
        "items": [
          {"name": "Webcam", "visible": true, "locked": false, "pos": {"x": 0, "y": 0}},
          {"name": "Desktop", "visible": true}
        ]
      }
    },
    {
      "name": "Webcam",
      "versioned_id": "v4l2_input",
      "settings": {"device_id": "/dev/video0"},
      "enabled": true,
      "mute": false
    }
  ]
}
```

## Running Tests

```bash
python verifiers/obs/test_obs.py
```

Tests create fixture scene collection files inside the E2B sandbox and exercise all file-based endpoints plus error handling. Live WebSocket tests require OBS to be running in the sandbox.
