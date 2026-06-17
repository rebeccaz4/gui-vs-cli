# VLC Verifier

Programmatic state inspection for VLC media player in E2B desktop sandboxes.
Used by a **check agent** to generate reward signals for RL/evaluation.

## Verification Channels

| Channel | Use Case | Requires |
|---------|----------|----------|
| HTTP API | Real-time playback state when VLC was launched with HTTP enabled | VLC with `--intf http --http-port 8080 --http-password secret` |
| D-Bus/MPRIS2 | Playback state, metadata, and volume for normal desktop VLC sessions | VLC running, plus either `playerctl` or `gdbus` |
| File-based | Config parsing, media file analysis | `ffprobe` for media info; vlcrc/qt-interface.conf for config |

## Usage from Check Agent

```python
import json
from e2b_desktop import Sandbox

sandbox = Sandbox.create(template="desktop-all-apps")

# --- Launch VLC with HTTP interface ---
sandbox.commands.run(
    "vlc --intf http --http-port 8080 --http-password secret "
    "/home/user/video.mp4 &",
    timeout=5
)

# --- CLI style (simple, one-off checks) ---
result = sandbox.commands.run("python3 /home/user/verifiers/vlc.py status")
status = json.loads(result.stdout)

result = sandbox.commands.run(
    "python3 /home/user/verifiers/vlc.py check-playing"
)
data = json.loads(result.stdout)
reward = 1.0 if data["playing"] else 0.0

# --- File-based checks (no VLC process needed) ---
result = sandbox.commands.run(
    "python3 /home/user/verifiers/vlc.py media-file-info /home/user/video.mp4"
)
info = json.loads(result.stdout)

result = sandbox.commands.run(
    "python3 /home/user/verifiers/vlc.py check-media-duration /home/user/video.mp4 120 2"
)
data = json.loads(result.stdout)
assert data["match"]
```

## Commands

### Query (HTTP API -- requires VLC running)

| Command | Description | Example |
|---------|-------------|---------|
| `status` | Playback state, position, volume, loop, repeat, random | `vlc.py status` |
| `playlist` | Current playlist items | `vlc.py playlist` |
| `media-info` | Info about currently playing media | `vlc.py media-info` |
| `volume` | Current volume level (raw + percent) | `vlc.py volume` |

### Query (D-Bus/MPRIS2)

| Command | Description | Example |
|---------|-------------|---------|
| `dbus-status` | Playback status via playerctl, or `gdbus` fallback if playerctl is unavailable | `vlc.py dbus-status` |
| `dbus-metadata` | Track metadata via playerctl, or `gdbus` fallback if playerctl is unavailable | `vlc.py dbus-metadata` |
| `dbus-volume` | Volume via playerctl (`0.0`-`1.0`, plus percent/raw conversions), or `gdbus` fallback | `vlc.py dbus-volume` |

### Query (file-based)

| Command | Description | Example |
|---------|-------------|---------|
| `config [key]` | Read vlcrc config | `vlc.py config volume` |
| `recent-media` | Recent media from qt-interface.conf | `vlc.py recent-media` |
| `media-file-info <file>` | Media file info via ffprobe | `vlc.py media-file-info video.mp4` |

### Check (boolean verification for RL)

| Command | Primary Key | Description |
|---------|-------------|-------------|
| `check-file-exists <path>` | `exists` | File exists on disk |
| `check-playing` | `playing` | VLC is currently playing |
| `check-state <state>` | `match` | VLC is in specific state (playing/paused/stopped) |
| `check-media-loaded <name>` | `loaded` | Specific media is loaded (substring match) |
| `check-volume <level>` | `match` | Volume at expected level (0-100% or 0-512 raw) |
| `check-position <sec> [tol]` | `match` | Playback at expected position |
| `check-fullscreen [bool]` | `match` | Fullscreen mode matches expected |
| `check-loop [bool]` | `match` | Loop mode matches expected |
| `check-repeat [bool]` | `match` | Repeat mode matches expected |
| `check-random [bool]` | `match` | Random/shuffle mode matches expected |
| `check-config <key> <value>` | `match` | vlcrc config key matches expected value |
| `check-media-duration <file> <sec> [tol]` | `match` | Media file has expected duration |
| `check-media-format <file> <fmt>` | `match` | Media file is expected format |
| `check-media-codec <file> <codec>` | `match` | Media file uses specific codec |
| `check-media-has-video <file>` | `has_video` | Media file has a video stream |
| `check-media-has-audio <file>` | `has_audio` | Media file has an audio stream |
| `check-media-resolution <file> <w> <h>` | `match` | Video has expected resolution |
| `check-playlist-count <n>` | `match` | Playlist has expected item count |

## HTTP API Authentication

VLC HTTP API uses basic auth with an empty username and the configured password:

```
URL: http://:password@localhost:8080/requests/status.json
Auth header: Basic base64(":password")
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VLC_HTTP_PORT` | `8080` | VLC HTTP API port |
| `VLC_HTTP_PASSWORD` | `secret` | VLC HTTP API password |

## Source Selection

Playback, loaded-media, and volume checks now prefer D-Bus/MPRIS2 whenever it is available and the HTTP endpoint looks stale for the current VLC session, such as when VLC was launched without `--intf http` and an old HTTP listener is still responding on port `8080`. If `playerctl` is missing, the verifier falls back to `gdbus` against `org.mpris.MediaPlayer2.vlc` for `PlaybackStatus`, `Metadata`, and `Volume`.

## Running Tests

```bash
python verifiers/vlc/test_vlc.py
```

Tests create an E2B sandbox, generate test media with ffmpeg, and verify all endpoints.
