# Shotcut Verifier

Programmatic state inspection for Shotcut video editing projects in E2B desktop sandboxes.

Shotcut is a free open-source video editor whose native project files are `.mlt`
(Media Lovin' Toolkit XML — the same underlying format that Kdenlive uses, with a
few Shotcut-specific property names). User configuration lives in a Qt-style INI
file at `~/.config/Meltytech/Shotcut.conf`. Exports go through ffmpeg, so export
files can be verified with `ffprobe`.

## Verification Channels

1. **XML parsing** (primary) — `.mlt` project files contain the full timeline
   state: clips (`<producer>` / `<chain>`), tracks (`<playlist>` + `<tractor>`),
   effects (`<filter>`), transitions (`<transition>`), and video profile.
2. **INI parsing** — `~/.config/Meltytech/Shotcut.conf` for preferences,
   recent files, theme, and default export/profile settings.
3. **ffprobe** — verify exported media files: codec, resolution, duration, fps,
   audio tracks.

## Skipped Categories

The verifier does not try to read categories that Shotcut cannot expose reliably:

- **Keybindings / shortcuts** — Shotcut stores shortcuts in the application binary;
  no user-editable keybinding file is available, so this category is skipped.
- **Extensions / plugins** — Shotcut does not have a plugin system.
- **Live IPC** — Shotcut has no D-Bus, WebSocket, or AT-SPI state interface. All
  verification is file-based; the app may be running or closed.

## `.mlt` XML Structure

Shotcut MLT files share the root structure used by the MLT framework:

- `<mlt>` — root element (attributes: `LC_NUMERIC`, `version`, `producer`, `root`)
- `<profile>` — resolution, frame rate, colorspace, display aspect ratio
- `<producer>` / `<chain>` — media clips. Modern Shotcut writes clips as `<chain>`
  elements; the verifier searches both tags.
- `<playlist>` — tracks (and the project bin is also a playlist with id `main_bin`).
  Contains `<entry>` and `<blank>` children.
- `<tractor>` — the assembled timeline. Lists tracks via `<track producer="..."/>`.
- `<filter>` — effects applied to clips or tracks.
- `<transition>` — transitions between tracks.

Shotcut-specific properties include `shotcut:caption`, `shotcut:name`,
`shotcut:hash`, and `shotcut:filter`.

## CLI Usage

```bash
# === Query endpoints (JSON output) ===
python3 shotcut.py project-info /path/to/project.mlt
python3 shotcut.py clips /path/to/project.mlt
python3 shotcut.py playlists /path/to/project.mlt
python3 shotcut.py tracks /path/to/project.mlt
python3 shotcut.py filters /path/to/project.mlt
python3 shotcut.py transitions /path/to/project.mlt
python3 shotcut.py clip-info /path/to/project.mlt producer0
python3 shotcut.py profile /path/to/project.mlt
python3 shotcut.py export-info /path/to/output.mp4
python3 shotcut.py config                         # dumps ~/.config/Meltytech/Shotcut.conf
python3 shotcut.py config-value General theme
python3 shotcut.py recent-files

# === Check endpoints (return a primary boolean key) ===
python3 shotcut.py check-file-exists /path/to/file.mp4                           # -> exists
python3 shotcut.py check-clip-exists /path/to/project.mlt intro.mp4              # -> exists
python3 shotcut.py check-clip-count /path/to/project.mlt 3                       # -> match
python3 shotcut.py check-playlist-count /path/to/project.mlt 4                   # -> match
python3 shotcut.py check-track-count /path/to/project.mlt 2                      # -> match
python3 shotcut.py check-filter-exists /path/to/project.mlt brightness           # -> exists
python3 shotcut.py check-filter-count /path/to/project.mlt 2                     # -> match
python3 shotcut.py check-transition-exists /path/to/project.mlt luma             # -> exists
python3 shotcut.py check-transition-count /path/to/project.mlt 1                 # -> match
python3 shotcut.py check-resolution /path/to/project.mlt 1920 1080               # -> match
python3 shotcut.py check-fps /path/to/project.mlt 30                             # -> match
python3 shotcut.py check-clip-resource /path/to/project.mlt producer0 intro.mp4  # -> match
python3 shotcut.py check-playlist-entry-count /path/to/project.mlt playlist0 2   # -> match
python3 shotcut.py check-config-value General theme dark                         # -> match
python3 shotcut.py check-export-output /path/to/output.mp4                       # -> valid
python3 shotcut.py check-export-resolution /path/to/output.mp4 1920 1080         # -> match
python3 shotcut.py check-export-codec /path/to/output.mp4 h264 video             # -> match
```

Every `check-*` command returns a dict with exactly one primary boolean key:

| Command                       | Primary key |
|-------------------------------|-------------|
| `check-file-exists`           | `exists`    |
| `check-clip-exists`           | `exists`    |
| `check-clip-count`            | `match`     |
| `check-playlist-count`        | `match`     |
| `check-track-count`           | `match`     |
| `check-filter-exists`         | `exists`    |
| `check-filter-count`          | `match`     |
| `check-transition-exists`     | `exists`    |
| `check-transition-count`      | `match`     |
| `check-resolution`            | `match`     |
| `check-fps`                   | `match`     |
| `check-clip-resource`         | `match`     |
| `check-playlist-entry-count`  | `match`     |
| `check-config-value`          | `match`     |
| `check-export-output`         | `valid`     |
| `check-export-resolution`     | `match`     |
| `check-export-codec`          | `match`     |

Errors are always returned as `{"error": "..."}` — no crashes.

## Python Usage

```python
from verifiers.shotcut.shotcut import ShotcutVerifier

v = ShotcutVerifier()
info = v.get_project_info("/path/to/project.mlt")
v.check_resolution("/path/to/project.mlt", 1920, 1080)
v.check_filter_exists("/path/to/project.mlt", "brightness")
```

## Sandbox Integration

```python
from e2b_desktop import Sandbox

sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)
sandbox.commands.run("mkdir -p /home/user/verifiers")
sandbox.files.write("/home/user/verifiers/shotcut.py", open("shotcut.py").read())

result = sandbox.commands.run(
    "python3 /home/user/verifiers/shotcut.py project-info /home/user/Videos/project.mlt"
)
data = json.loads(result.stdout)
```

## Dependencies

- Python 3.10+ (standard library only: `xml.etree.ElementTree`, `configparser`,
  `json`, `subprocess`)
- `ffprobe` (from ffmpeg) for `export-info` / `check-export-*` commands
