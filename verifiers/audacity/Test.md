# Audacity Verifier Test Plan

## Module Overview

Verifier target: **Audacity 2.4.2** (the version shipped in `desktop-all-apps`).

Channels:
- `.aup` XML parsing (`xml.etree.ElementTree`)
- `audacity.cfg` / `pluginregistry.cfg` INI parsing (`configparser`)
- `ffprobe` JSON for audio exports
- File-system existence / size checks

Prerequisites: none. The verifier runs inside the sandbox against pre-generated
fixture files (no live Audacity instance required).

## Test Groups

### 1. Help / Usage
- `python3 audacity.py --help` exits 0 and lists commands.
- `python3 audacity.py` (no args) prints usage and exits 0.
- 3 assertions.

### 2. Error handling
- Unknown subcommand -> exit 1 + valid JSON error.
- Missing required arg -> exit 1 + valid JSON error.
- Non-existent file -> JSON error, no crash.
- Wrong extension (`.txt` passed where `.aup` expected) -> JSON error.
- Malformed XML file -> JSON error.
- 6 assertions.

### 3. Query endpoints - core project
Using the rich fixture `/home/user/rich.aup`:
- `project-info` returns dict with correct counts (2 wavetracks, 1 labeltrack,
  1 notetrack, 1 timetrack, 6 tags, 3 blockfiles).
- `project-attrs` returns expected `rate`, `snapto`, `selectionformat`,
  `audacityversion`.
- `tracks` returns list with 2 items; first track name is "Vocal", mute=0,
  gain=1.0.
- `track` by index (0) returns Vocal; by name (`Drums`) returns the second
  track; missing name returns `{"error": ...}`.
- `label-tracks` returns 1 item with 2 labels.
- `labels` returns flat list of 2 labels with titles "Intro" and "Chorus".
- `note-tracks` returns 1 item.
- `time-tracks` returns 1 item.
- `tags` returns dict with `TITLE="Sunset Melody"`, `ARTIST="Demo Artist"`, ...
- `blockfile-count` returns 3.
- `data-dir-info` with a pre-created `rich_data/` directory returns
  `exists=True`, `file_count>=1`.
- ~22 assertions.

### 4. Query endpoints - preferences
Fixtures: pre-seeded `~/.audacity-data/audacity.cfg` with known sections.
- `preferences` returns dict with expected sections.
- `preferences AudioIO` returns only the AudioIO section's keys.
- `preference AudioIO PlaybackDevice` returns `{"value": ...}`.
- `preference-sections` returns list including "AudioIO", "Quality".
- Non-existent section -> error JSON.
- Non-existent key -> error JSON.
- ~7 assertions.

### 5. Query endpoints - plugin registry
Fixture: pre-seeded `pluginregistry.cfg` with one plugin section.
- `plugins` returns dict containing the seeded plugin id.
- Missing plugin registry -> error JSON (handled via temporary absence).
- 2 assertions.

### 6. Check endpoints - positive cases
Using `rich.aup`:
- `check-valid-aup` -> `valid=True`.
- `check-track-count 2` -> `match=True`.
- `check-labeltrack-count 1` -> `match=True`.
- `check-track-name Vocal` -> `match=True`.
- `check-track-rate 44100` -> `match=True`.
- `check-project-rate 44100` -> `match=True`.
- `check-track-mute 1 true` -> `match=True` (Drums is muted).
- `check-track-solo 0 false` -> `match=True`.
- `check-track-gain 0 1.0` -> `match=True`.
- `check-track-pan 1 0.25` -> `match=True`.
- `check-snapto Off` -> `match=True`.
- `check-selection-format hh:mm:ss` -> `match=True`.
- `check-blockfile-count-min 1` -> `match=True`.
- `check-label-exists Chorus` -> `match=True`.
- `check-label-count 2` -> `match=True`.
- `check-data-dir-exists` -> `exists=True` (fixture creates `rich_data/`).
- `check-tag-value TITLE "Sunset Melody"` -> `match=True`.
- `check-tag-contains COMMENTS project` -> `match=True`.
- `check-preference AudioIO PlaybackDevice default` -> `match=True`.
- `check-preference-exists Quality DefaultSampleRate` -> `exists=True`.
- ~20 assertions.

### 7. Check endpoints - negative cases
- `check-track-count 99` -> `match=False`.
- `check-track-name NonExistent` -> `match=False`.
- `check-track-rate 1000` -> `match=False`.
- `check-project-rate 48000` -> `match=False`.
- `check-track-mute 0 true` (Vocal is not muted) -> `match=False`.
- `check-track-solo 1 true` -> `match=False`.
- `check-track-gain 1 2.0` -> `match=False`.
- `check-snapto On` -> `match=False`.
- `check-label-exists Bridge` -> `match=False`.
- `check-tag-value TITLE "Other"` -> `match=False`.
- `check-preference AudioIO PlaybackDevice other` -> `match=False`.
- `check-preference-exists Foo Bar` -> `exists=False`.
- `check-file-exists /no/such/file` -> `exists=False`.
- `check-file-size-min /tmp/tiny.txt 10000` (a small file) -> `match=False`.
- ~14 assertions.

### 8. Minimal fixture tests
Using `/home/user/min.aup` (single track, no clips, no tags):
- `project-info` returns wavetrack_count=1, tag_count=0.
- `check-track-count 1` -> `match=True`.
- `check-blockfile-count-min 1` -> `match=False` (no clips).
- `tags` returns empty dict.
- ~4 assertions.

### 9. Export (ffprobe) tests
Fixtures generated via `ffmpeg` inside the sandbox at
`/home/user/out.wav` (mono 44.1 kHz PCM, 2 s) and `/home/user/out.mp3`
(stereo 44.1 kHz MP3, 2 s).
- `export-info out.wav` returns streams with audio codec.
- `check-export-exists out.wav` -> `valid=True`.
- `check-export-codec out.wav pcm_s16le` -> `match=True`.
- `check-export-sample-rate out.wav 44100` -> `match=True`.
- `check-export-channels out.wav 1` -> `match=True`.
- `check-export-duration-min out.wav 1.5` -> `match=True`.
- `check-export-format out.wav wav` -> `match=True`.
- Negative: `check-export-codec out.wav mp3` -> `match=False`.
- Negative: `check-export-sample-rate out.wav 48000` -> `match=False`.
- Negative: `check-export-channels out.wav 2` -> `match=False` (mono fixture).
- Negative: `check-export-duration-min out.wav 100` -> `match=False`.
- Positive on the MP3 fixture: `check-export-codec out.mp3 mp3` -> `match=True`.
- Positive: `check-export-channels out.mp3 2` -> `match=True`.
- `check-export-exists /no/file.wav` -> `valid=False`.
- ~14 assertions.

### 10. Audio content checks (PCM decode + analysis)
Fixtures generated in-sandbox via stdlib `wave`+`math` (44.1 kHz mono PCM16):
- `sine440_loud.wav` - 440Hz sine, amp=0.8, 2s (peak ~ -1.94 dBFS, RMS ~ -4.94 dB)
- `sine440_quiet.wav` - 440Hz sine, amp=0.05, 2s (peak ~ -26 dBFS, RMS ~ -29 dB)
- `sine880.wav` - 880Hz sine, amp=0.6, 2s
- `silence.wav` - 2s of silence
- `mixed.wav` - 0-1s silent, 1-2s 440Hz sine @ 0.5
- `lowfreq.wav` - 200Hz sine, amp=0.5, 2s
- `highfreq.wav` - 8000Hz sine, amp=0.5, 2s

Assertions:
- `check-export-peak-db sine440_loud.wav -3 0` -> True (positive)
- `check-export-peak-db sine440_loud.wav -40 -20` -> False (negative)
- `check-export-peak-db sine440_quiet.wav -30 -20` -> True (positive)
- `check-export-peak-db sine440_quiet.wav -3 0` -> False (negative)
- `check-export-region-silent silence.wav 0 2 -60` -> True (positive)
- `check-export-region-silent mixed.wav 0 1 -60` -> True (positive on silent region)
- `check-export-region-silent mixed.wav 1 2 -60` -> False (negative on loud region)
- `check-export-region-silent sine440_loud.wav 0 2 -60` -> False (negative)
- `check-export-region-rms-db sine440_loud.wav 0 2 -7 -3` -> True (positive)
- `check-export-region-rms-db sine440_loud.wav 0 2 -40 -20` -> False (negative)
- `check-export-region-rms-db sine440_quiet.wav 0 2 -32 -26` -> True (positive)
- `check-export-dominant-freq sine440_loud.wav 0 2 440 2` -> True (Goertzel positive)
- `check-export-dominant-freq sine880.wav 0 2 880 2` -> True (Goertzel positive)
- `check-export-dominant-freq sine440_loud.wav 0 2 1000 2` -> False (Goertzel negative)
- `check-export-dominant-freq sine880.wav 0 2 440 2` -> False (Goertzel negative)
- `check-export-band-energy-ratio-max lowfreq.wav 2000 0.1` -> True (HP positive)
- `check-export-band-energy-ratio-max highfreq.wav 2000 0.1` -> False (HP negative)
- `check-export-band-energy-ratio-max highfreq.wav 2000 1.0` -> True (trivial positive)
- `check-export-band-energy-ratio-max /no/file.wav 2000 0.5` -> match=False (missing file)
- ~20 assertions.

### 11. JSON validity sweep
Every CLI command exercised in the suite must produce valid JSON on stdout
(even in error cases). ~30 assertions.

## Test Fixtures

| Path | Contents | Used by |
|---|---|---|
| `/home/user/rich.aup` | Rich 2-track XML with tags, label track, note track, time track, 3 blockfile refs | groups 3, 6, 7, 10 |
| `/home/user/rich_data/` | Empty dir for data-dir-exists check | group 6 |
| `/home/user/min.aup` | Minimal single-track project | group 8 |
| `/home/user/malformed.aup` | `<project` missing close bracket | group 2 |
| `/home/user/notproject.aup` | Valid XML but root element is `<foo/>` | group 2 |
| `/tmp/tiny.txt` | 2-byte text file (for wrong-extension / size tests) | group 2, 7 |
| `/home/user/.audacity-data/audacity.cfg` | Pre-seeded INI with `[AudioIO]`, `[Quality]`, `[Warnings]` sections | groups 4, 6, 7 |
| `/home/user/.audacity-data/pluginregistry.cfg` | Pre-seeded INI with one plugin section | group 5 |
| `/home/user/out.wav` | Mono 44.1 kHz WAV, 2 s sine tone (ffmpeg) | group 9 |
| `/home/user/out.mp3` | Stereo 44.1 kHz MP3, 2 s sine tone (ffmpeg) | group 9 |
| `/home/user/sine440_loud.wav` | 2s mono PCM16 sine 440Hz amp=0.8 | group 10 |
| `/home/user/sine440_quiet.wav` | 2s mono PCM16 sine 440Hz amp=0.05 | group 10 |
| `/home/user/sine880.wav` | 2s mono PCM16 sine 880Hz amp=0.6 | group 10 |
| `/home/user/silence.wav` | 2s silence PCM16 | group 10 |
| `/home/user/mixed.wav` | 0-1s silent, 1-2s 440Hz sine @ 0.5 | group 10 |
| `/home/user/lowfreq.wav` | 2s 200Hz sine | group 10 |
| `/home/user/highfreq.wav` | 2s 8000Hz sine | group 10 |

## Edge Cases & Error Handling Matrix

| Scenario | Endpoints | Expected |
|---|---|---|
| Unknown subcommand | dispatcher | exit 1 + JSON error |
| Missing required arg | every check-* | exit 1 + JSON error |
| Non-existent .aup | every .aup endpoint | JSON error |
| Wrong extension | `project-info` | JSON error |
| Malformed XML | `project-info` | JSON error |
| Wrong root element | `project-info` | JSON error |
| Empty section list in cfg | `preferences` | empty dict, no crash |
| Missing cfg file | `preferences`, `preference` | JSON error |
| Missing pluginregistry.cfg | `plugins` | JSON error |
| ffprobe on missing file | every export-* | match=False with error |
| ffprobe on 0-byte file | `check-export-exists` | valid=False |

## Positive / Negative Pairs

| check-* | Positive fixture | Negative case |
|---|---|---|
| `check-valid-aup` | `rich.aup` | `malformed.aup` / `tiny.txt` |
| `check-track-count` | 2 on `rich.aup` | 99 on `rich.aup` |
| `check-track-name` | `Vocal` | `NonExistent` |
| `check-track-rate` | 44100 | 1000 |
| `check-project-rate` | 44100 | 48000 |
| `check-track-mute` | idx=1 true | idx=0 true |
| `check-track-solo` | idx=0 false | idx=1 true |
| `check-track-gain` | idx=0 1.0 | idx=1 2.0 |
| `check-track-pan` | idx=1 0.25 | idx=0 0.5 |
| `check-snapto` | Off | On |
| `check-selection-format` | hh:mm:ss | samples |
| `check-label-exists` | Chorus | Bridge |
| `check-label-count` | 2 | 99 |
| `check-tag-value` | TITLE "Sunset Melody" | TITLE "Other" |
| `check-tag-contains` | COMMENTS project | COMMENTS absent-word |
| `check-preference` | AudioIO PlaybackDevice default | AudioIO PlaybackDevice other |
| `check-preference-exists` | Quality DefaultSampleRate | Foo Bar |
| `check-export-codec` | out.wav pcm_s16le | out.wav mp3 |
| `check-export-sample-rate` | out.wav 44100 | out.wav 48000 |
| `check-export-channels` | out.mp3 2 | out.wav 2 |
| `check-export-duration-min` | 1.5 | 100 |
| `check-export-format` | out.wav wav | out.wav mp3 |
| `check-data-dir-exists` | rich_data/ exists | min_data/ missing |
| `check-export-peak-db` | sine440_loud.wav [-3,0] | sine440_loud.wav [-40,-20] |
| `check-export-region-silent` | silence.wav 0..2 -60 | sine440_loud.wav 0..2 -60 |
| `check-export-region-rms-db` | sine440_loud.wav 0..2 [-7,-3] | sine440_loud.wav 0..2 [-40,-20] |
| `check-export-dominant-freq` | sine440_loud.wav exp=440 tol=2% | sine440_loud.wav exp=1000 tol=2% |
| `check-export-band-energy-ratio-max` | lowfreq.wav cutoff=2000 max=0.1 | highfreq.wav cutoff=2000 max=0.1 |

## JSON Validity Sweep

Each of these commands is exercised in the suite and must produce valid JSON:
`--help` (stderr is allowed, stdout is text), `project-info`, `project-attrs`,
`tracks`, `track`, `label-tracks`, `labels`, `note-tracks`, `time-tracks`,
`tags`, `blockfile-count`, `data-dir-info`, `preferences`, `preference`,
`preference-sections`, `plugins`, `export-info`, and every `check-*` endpoint.

## Summary

| Metric | Count |
|---|---|
| Test groups | 11 |
| Total assertions | ~194 |
| Test fixtures | 17 |
| `check-*` endpoints with pos+neg pairs | 27 |
| Error scenarios covered | 11 |
