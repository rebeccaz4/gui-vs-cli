# Zoom Verifier — Test Plan

## Module Overview

The Zoom verifier reads `~/.config/zoomus.conf` (INI) via `configparser` and
enumerates files under `~/.zoom/data/` and `~/.zoom/logs/`. It also performs
filesystem checks against the configured recording directory. Zoom is never
launched — the verifier never talks to a live Zoom process, so all tests
exercise the file-based channels.

Prerequisites: none. The test uploads fixtures directly to the sandbox.

## Test Groups

### Group 1: Help / usage
- `--help` returns usage banner and exit 0.
- 3 assertions.

### Group 2: Error handling (no config yet)
- Before writing any fixture, `check-config-exists` should return `exists=false`.
- `sections`, `config`, `section General` should return error JSON.
- 4 assertions.

### Group 3: Error handling (bad args)
- Missing required arg (`section` with no section name) -> exit 1 + JSON.
- Missing required arg for `check-config` (needs 3 args).
- Unknown subcommand -> exit 1 + JSON.
- `check-recording-count` with non-integer.
- 8 assertions.

### Group 4: Config introspection
- `sections` returns list containing `General`, `Audio`, `Video`, `chat.client`.
- `section General` dumps keys, including `autoMuteMic`, `language`, `localRecordingPath`.
- `config` returns nested dict with >= 4 sections.
- `value General language` returns `en-US`.
- `value General missingKey` returns error.
- `section NoSuchSection` returns error.
- 10 assertions.

### Group 5: check-config positive
- `check-config General autoMuteMic true` -> match=true
- `check-config General language en-US` -> match=true
- `check-config Audio MicrophoneLevel 80` -> match=true
- `check-config Video HDVideo false` -> match=true
- `check-config General Theme 2` -> match=true (int-as-string)
- 5 assertions.

### Group 6: check-config negative
- `check-config General autoMuteMic false` -> match=false
- `check-config General language de-DE` -> match=false
- `check-config NoSection key value` -> match=false with error
- `check-config General noSuchKey value` -> match=false with error
- 4 assertions.

### Group 7: check-bool
- `check-bool General autoMuteMic true` -> match=true
- `check-bool General autoMuteMic false` -> match=false
- `check-bool Video HDVideo false` -> match=true
- `check-bool Video HDVideo true` -> match=false
- Value stored as `1`/`0` also matches (add a numeric-bool key to fixture and verify).
- 5 assertions.

### Group 8: check-language
- `check-language en-US` -> match=true
- `check-language de-DE` -> match=false
- 2 assertions.

### Group 9: check-recording-path
- `check-recording-path /home/user/Documents/Zoom` -> match=true
- `check-recording-path /tmp/other` -> match=false
- `recording-path` returns the value directly.
- 3 assertions.

### Group 10: data / logs / recordings
- `data-files` lists 2 fixture data files.
- `log-files` lists 1 fixture log file.
- `list-recordings` lists 2 fake mp4 files inside the recording directory.
- `recent-meeting-ids` returns `["1234567890"]` after fixture puts this id in a data file.
- `check-recording-count 2` -> match=true
- `check-recording-count 5` -> match=false
- 6 assertions.

### Group 11: check-config-contains
- `check-config-contains General localRecordingPath Documents` -> match=true
- `check-config-contains General localRecordingPath elsewhere` -> match=false
- 2 assertions.

### Group 12: check-file-exists / check-directory-exists
- File exists -> exists=true
- File missing -> exists=false
- Directory exists -> exists=true
- Not a directory (point at a file) -> exists=false
- 4 assertions.

### Group 13: check-section-exists
- Positive: `General`
- Negative: `NoSuchSection`
- 2 assertions.

### Group 14: JSON validity sweep
- Every command (with minimally valid args) returns parseable JSON.
- ~15 assertions.

## Test Fixtures

### Fixture A — `~/.config/zoomus.conf`
Representative INI with **many sections / keys** so most endpoints have data
to work with. Includes a mix of bool-as-string (`true`/`false`), bool-as-int
(`1`/`0`), strings, integers, paths.

```ini
[General]
autoMuteMic=true
autoTurnOffVideo=false
language=en-US
localRecordingPath=/home/user/Documents/Zoom
autoStart=false
HowlingDetection=true
Theme=2
enableMirrorEffect=1

[Audio]
AudioDevice=default
MicrophoneLevel=80
SpeakerLevel=75
SuppressBackgroundNoise=2
EnableOriginalSound=false

[Video]
HDVideo=false
mirrorMyVideo=true
VideoDevice=Integrated Webcam
TouchUpMyAppearance=false

[chat.client]
Theme=dark
EnableSpellCheck=true

[General.Meetings]
ShowTimer=true
ConfirmLeaveMeeting=true
```

Used by: groups 2, 4, 5, 6, 7, 8, 9, 11, 13, 14.

### Fixture B — `~/.zoom/data/history.txt`
```
meetingID=1234567890
lastJoined=2026-04-10
```
Used by: group 10 (data-files, recent-meeting-ids).

### Fixture C — `~/.zoom/data/cache.json`
```json
{"recent": [{"id": "9876543210"}]}
```
Used by: group 10.

### Fixture D — `~/.zoom/logs/zoom.log`
A few lines of plain text log.
Used by: group 10 (log-files).

### Fixture E — recording directory `~/Documents/Zoom/`
Contains two empty files named `2026-04-01 meeting.mp4` and
`2026-04-05 meeting.mp4`.
Used by: group 10 (list-recordings, check-recording-count).

### Fixture F — generic file `/home/user/existing_file.txt`
Used by: group 12 (check-file-exists positive).

## Edge Cases & Error Handling Matrix

| Scenario | Endpoint(s) | Expected |
|---|---|---|
| Missing config file | all file-based endpoints except `config-path`/`check-config-exists` | `{"error": "..."}` |
| Section missing | `section`, `check-config`, `value` | `{"error": "..."}` or `{"match": false, "error": ...}` |
| Key missing | `value`, `check-config`, `check-bool` | same as above |
| Unknown subcommand | any | exit 1 + valid JSON error |
| Missing required arg | `section`, `value`, `check-config`, ... | exit 1 + valid JSON error |
| Wrong type for count | `check-recording-count` | exit 1 + valid JSON error |
| Path doesn't exist | `check-file-exists`, `check-directory-exists`, `list-recordings` | `exists=false` or error |

## Positive / Negative Case Pairs

| Endpoint | Positive | Negative |
|---|---|---|
| `check-config-exists` | fixture written | no fixture (ran first) |
| `check-section-exists` | `General` | `NoSuchSection` |
| `check-config` | `General autoMuteMic true` | `General autoMuteMic false` |
| `check-config-contains` | `General localRecordingPath Documents` | `General localRecordingPath elsewhere` |
| `check-bool` | `General autoMuteMic true` | `General autoMuteMic false` |
| `check-language` | `en-US` | `de-DE` |
| `check-recording-path` | `/home/user/Documents/Zoom` | `/tmp/other` |
| `check-file-exists` | existing file | missing file |
| `check-directory-exists` | recording dir | missing dir |
| `check-recording-count` | `2` | `5` |

## JSON Validity Sweep

All of:
- `sections`, `section General`, `config`, `value General language`, `config-path`
- `data-files`, `log-files`, `recording-path`, `list-recordings`, `recent-meeting-ids`
- `check-config-exists`, `check-section-exists General`,
  `check-config General language en-US`, `check-config-contains General localRecordingPath Documents`,
  `check-bool General autoMuteMic true`, `check-language en-US`,
  `check-recording-path /home/user/Documents/Zoom`,
  `check-file-exists /tmp`, `check-directory-exists /tmp`,
  `check-recording-count 1`.

## Summary

| Metric | Count |
|---|---|
| Test groups | 14 |
| Total assertions | ~65 |
| Fixture files | 6 |
| `check-*` endpoints with pos+neg pairs | 10 |
| Error scenarios covered | 8 |
