# Shotcut Verifier Test Plan

## Module Overview

The Shotcut verifier inspects `.mlt` project files (MLT XML) and the
`~/.config/Meltytech/Shotcut.conf` Qt-INI file, and uses `ffprobe` to
verify exported media files. All verification is file-based; no live IPC
is used.

Prerequisites:
- `ffprobe` installed (present in the `desktop-all-apps` template)
- Python 3.10+ stdlib only

## Test Groups

### 1. Help / Usage
- `--help` exits 0, mentions "Shotcut" and "Commands:"
- No arguments prints usage too

Expected assertions: ~3

### 2. Error Handling
- Unknown command exits 1, returns valid JSON error
- Missing required arg exits 1, returns valid JSON error
- Non-existent .mlt file returns `{"error": ...}`
- Wrong file extension returns error
- `config` with a path that doesn't exist returns error
- `config-value` for missing section returns error

Expected assertions: ~8

### 3. Query Endpoints on main fixture (`project-info`, `clips`, `playlists`, `tracks`, `filters`, `transitions`, `clip-info`, `profile`)
- Counts match known fixture state
- clip-info returns properties for a known id
- Bad id returns error

Expected assertions: ~20

### 4. Check Endpoints — Positive
- `check-file-exists` on a real file
- `check-clip-exists` by resource substring AND by caption substring
- `check-clip-count`, `check-playlist-count`, `check-track-count`,
  `check-filter-count`, `check-transition-count` matching known fixtures
- `check-filter-exists` by mlt_service
- `check-transition-exists` by mlt_service
- `check-resolution` and `check-fps`
- `check-clip-resource` containing substring
- `check-playlist-entry-count` for a specific playlist

Expected assertions: ~14

### 5. Check Endpoints — Negative
- `check-file-exists` on nonexistent file
- `check-clip-exists` with a string not present
- `check-clip-count` wrong number
- `check-filter-exists` with missing filter
- `check-transition-exists` with missing transition
- `check-resolution` wrong dimensions
- `check-fps` wrong fps
- `check-clip-resource` not containing substring
- `check-playlist-entry-count` wrong count

Expected assertions: ~10

### 6. 720p Secondary Fixture
- Different profile values verify the endpoints against a second file
- check-resolution / check-fps / check-clip-count pass on it

Expected assertions: ~6

### 7. Config (Shotcut.conf) Endpoints
- `config` dumps a known-generated INI to structured dict
- `config-value` retrieves a known setting
- `check-config-value` positive and negative
- `recent-files` returns entries

Expected assertions: ~8

### 8. Export File (ffprobe) Endpoints
- Generate a tiny sample mp4 with ffmpeg (color source) in-sandbox
- `export-info` returns stream/format info
- `check-export-output` returns valid true
- `check-export-resolution` positive and negative
- `check-export-codec` positive (h264 or mpeg4) and negative
- `check-export-output` on empty file returns valid false
- `check-export-output` on missing file returns valid false

Expected assertions: ~8

### 9. JSON Validity Sweep
- Every CLI command produces valid JSON (or explicit error JSON, never tracebacks)

Expected assertions: ~20

## Test Fixtures

1. **`/home/user/test_shotcut.mlt`** — A rich MLT fixture hand-crafted in the test:
   - 1920x1080 @ 30fps profile
   - 3 `<chain>` clips (modern Shotcut format) with shotcut:caption, resource,
     mlt_service, length
   - Main bin playlist + 2 timeline playlists (video + audio)
   - `<tractor>` referencing the bin and both tracks
   - 2 filters (brightness, volume)
   - 1 transition (luma)

2. **`/home/user/test_shotcut_720p.mlt`** — A minimal 1280x720 @ 25fps project with
   1 clip + 1 playlist + 1 tractor track.

3. **`/home/user/.config/Meltytech/Shotcut.conf`** — A hand-crafted INI containing:
   - `[General]` with `theme = dark`, `timeFormat = HH:mm:ss`
   - `[Settings]` with `playerGpu = false`, `defaultProfile = atsc_1080p_30`
   - `[RecentFiles]` entries

4. **`/home/user/test_export.mp4`** — Generated with ffmpeg via
   `ffmpeg -f lavfi -i color=c=blue:s=320x240:d=1 -y out.mp4`. Small 1-second
   clip used for export-* check tests.

5. **`/home/user/empty.mp4`** — Zero-byte file for negative export check.

## Edge Cases & Error Handling Matrix

| Scenario                             | Endpoints                         | Expected                 |
|--------------------------------------|-----------------------------------|--------------------------|
| Missing .mlt                         | all project endpoints             | `{"error": "..."}`       |
| Wrong extension                      | project-info, etc.                | `{"error": "..."}`       |
| Unknown command                      | any                               | exit 1 + JSON error      |
| Missing required arg                 | `clips`, `check-*`                | exit 1 + JSON error      |
| Nonexistent config path              | `config`, `config-value`          | `{"error": "..."}`       |
| Non-existent export file             | `check-export-*`                  | `valid=false` or error   |
| Empty export file                    | `check-export-output`             | `valid=false`            |
| Unknown clip id                      | `clip-info`                       | `{"error": "..."}`       |
| Unknown playlist id                  | `check-playlist-entry-count`      | `{"error": "..."}`       |

## Positive / Negative Pairs

| check-* endpoint                | Positive case                        | Negative case                      |
|---------------------------------|--------------------------------------|------------------------------------|
| check-file-exists               | /home/user/test_shotcut.mlt          | /nonexistent/foo.mlt               |
| check-clip-exists               | "intro" (in caption)                 | "nothing_here.avi"                 |
| check-clip-count                | 3                                    | 99                                 |
| check-playlist-count            | 3                                    | 10                                 |
| check-track-count               | 3                                    | 99                                 |
| check-filter-exists             | "brightness"                         | "missing_effect"                   |
| check-filter-count              | 2                                    | 99                                 |
| check-transition-exists         | "luma"                               | "wipe_nonexistent"                 |
| check-transition-count          | 1                                    | 5                                  |
| check-resolution                | 1920 1080                            | 3840 2160                          |
| check-fps                       | 30                                   | 60                                 |
| check-clip-resource             | clip1 "intro"                        | clip1 "absent_substring"           |
| check-playlist-entry-count      | playlist0 → 2                        | playlist0 → 99                     |
| check-config-value              | General theme dark                   | General theme light                |
| check-export-output             | test_export.mp4                      | empty.mp4                          |
| check-export-resolution         | 320 240                              | 1920 1080                          |
| check-export-codec              | h264 video (ffmpeg default)          | prores video                       |

## JSON Validity Sweep

Every CLI subcommand with its happy-path args is run and parsed via json.loads.
Error paths are also parsed to verify they still emit valid JSON.

## Summary

| Metric                              | Count |
|-------------------------------------|-------|
| Test groups                         | 9     |
| Total assertions (approx)           | ~95   |
| Test fixtures                       | 5     |
| `check-*` endpoints w/ pos+neg      | 17    |
| Error scenarios                     | 9     |
