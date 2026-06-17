# Zoom Verifier

Programmatic state inspection for the Zoom desktop client in E2B desktop
sandboxes. Used by a check agent to generate reward signals for RL/evaluation.

## Verification Channels

| Channel | Requires Zoom Running | Description |
|---------|------------------------|-------------|
| **File-based — INI parsing** | No | Parse `~/.config/zoomus.conf` via Python `configparser` |
| **File-based — data scan**   | No | Enumerate files in `~/.zoom/data/` and `~/.zoom/logs/` |
| **Filesystem checks**        | No | Recording directory existence / file counts |

Zoom's verifiable surface in a headless, logged-out sandbox is **thin** —
most meaningful state (meetings, contacts, calendar, chat, participants)
requires sign-in with a real account. This verifier therefore focuses on
local preferences and on-disk artifacts which are deterministic.

## Skipped Categories (not verifiable here)

These categories were deliberately **not** implemented because no reliable
file/API channel is available in a headless, logged-out sandbox:

| Category | Reason |
|---------|-------|
| Meeting state (in meeting, host, participants, raised hand) | Requires live Zoom session with an account |
| Contacts / directory | Loaded from Zoom servers at runtime |
| Calendar events / scheduled meetings | Fetched from Zoom/Google/Outlook backends |
| Chat messages / IM history | Encrypted store populated only while signed in |
| Audio / video levels, active speaker | Requires live media pipeline |
| Screen sharing / whiteboard / reactions | Live in-meeting state |
| Breakout rooms | Live in-meeting state |
| Cloud recording state | Server-side, needs account |
| Sign-in / SSO / profile picture | Requires account |
| Extensions / marketplace apps | Server-managed, login required |
| Keybindings for in-meeting shortcuts | Not exposed in a readable format on Linux |
| UI layout (window positions) | Not persisted to a parseable file |

Do not generate tasks that rely on any of the above.

## File Locations

| Path | Contents |
|------|----------|
| `~/.config/zoomus.conf` | Main INI config — sections like `[General]`, `[Audio]`, `[Video]`, `[chat.client]`, `[General.Meetings]`, etc. |
| `~/.zoom/data/` | Recent meeting IDs, local cache |
| `~/.zoom/logs/` | Client log files |

## CLI Usage

```bash
# Outside the sandbox (via sandbox.commands.run):
sandbox.commands.run("python3 /home/user/verifiers/zoom.py config")
sandbox.commands.run("python3 /home/user/verifiers/zoom.py check-config General autoMuteMic true")

# Direct CLI:
python3 zoom.py sections
python3 zoom.py section General
python3 zoom.py value General autoMuteMic
python3 zoom.py check-config General autoMuteMic true
python3 zoom.py check-recording-path /home/user/ZoomRecordings
```

All output is JSON to stdout. Errors return `{"error": "..."}`.

## Commands

### Config introspection

| Command | Args | Description |
|---------|------|-------------|
| `config-path` | | Show resolved `zoomus.conf` path + existence |
| `sections` | | List all sections in `zoomus.conf` |
| `section` | `<section>` | Dump key/values for a single section |
| `config` | | Dump entire `zoomus.conf` as nested dict |
| `value` | `<section> <key>` | Read a single config value |

### Data / recordings / logs

| Command | Args | Description |
|---------|------|-------------|
| `data-files` | | List files under `~/.zoom/data/` |
| `log-files` | | List files under `~/.zoom/logs/` |
| `recording-path` | | Return configured local recording directory |
| `list-recordings` | `[path]` | List files under the (configured or given) recording dir |
| `recent-meeting-ids` | | Scan data dir for 9–11 digit meeting IDs |

### Checks (primary boolean key shown in **bold**)

| Command | Primary Key | Args | Description |
|---------|-------------|------|-------------|
| `check-config-exists` | **exists** | | `zoomus.conf` is on disk |
| `check-section-exists` | **exists** | `<section>` | Section exists in config |
| `check-config` | **match** | `<section> <key> <expected>` | `[section]key` equals `expected` (bool-aware) |
| `check-config-contains` | **match** | `<section> <key> <needle>` | `[section]key` contains substring |
| `check-bool` | **match** | `<section> <key> <true\|false>` | `[section]key` parses as expected bool |
| `check-language` | **match** | `<lang>` | UI language matches (`en-US`, `zh-CN`, ...) |
| `check-recording-path` | **match** | `<path>` | Configured recording path == expected |
| `check-file-exists` | **exists** | `<path>` | File exists on disk |
| `check-directory-exists` | **exists** | `<path>` | Directory exists on disk |
| `check-recording-count` | **match** | `<N> [path]` | Recording dir has at least N files |

`check-bool` accepts `true` / `false` / `1` / `0` / `yes` / `no` for the expected
value, and compares after normalizing the stored config value the same way
(Zoom stores some prefs as `true`/`false`, others as `1`/`0`).

## Common Verification Patterns

```python
# Was the default mic mute on join enabled?
check-config General autoMuteMic true

# Was the recording path changed?
check-recording-path /home/user/ZoomRecordings

# Is the UI in German?
check-language de-DE

# Did the user change the default video off on join?
check-bool General autoTurnOffVideo true

# Did they enable HD video?
check-bool Video HDVideo true
```

## Example zoomus.conf Keys

Representative keys the verifier can inspect (exact set depends on Zoom version):

```
[General]
autoMuteMic=true
autoTurnOffVideo=false
language=en-US
localRecordingPath=/home/user/Documents/Zoom
autoStart=false
HowlingDetection=true
Theme=1

[Audio]
AudioDevice=default
MicrophoneLevel=80
SpeakerLevel=75
SuppressBackgroundNoise=2

[Video]
HDVideo=false
mirrorMyVideo=true
VideoDevice=Integrated Webcam
TouchUpMyAppearance=false

[chat.client]
Theme=dark
```

The verifier does not care which keys exist — `check-config` returns an error
with `match=false` if the requested section/key is missing, so tasks should
request keys the fixture (or agent action) is known to create.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ZOOM_CONFIG_PATH` | `~/.config/zoomus.conf` | Override config path |
| `ZOOM_DATA_DIR` | `~/.zoom/data` | Override data dir |
| `ZOOM_LOGS_DIR` | `~/.zoom/logs` | Override logs dir |

## Running Tests

```bash
python verifiers/zoom/test_zoom.py
```

Tests create fixture `zoomus.conf` files inside the sandbox and exercise all
file-based endpoints plus error handling. Zoom is **not** launched — verifying
the client's live state is impossible without logging in.
