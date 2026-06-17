# Audacity Verifier

Programmatic state inspection for **Audacity 2.x** audio editing projects in E2B
desktop sandboxes.

> The `desktop-all-apps` template ships **Audacity 2.4.2** (Ubuntu jammy), which
> writes projects as an **XML `.aup` file** plus a sibling `<name>_data/`
> directory of audio blockfiles. The verifier parses the `.aup` XML directly.
> It does **not** support Audacity 3.x `.aup3` (SQLite) files because they are
> not produced by the installed version.

## Verification Channels

1. **XML parsing of `.aup`** (primary) - extracts the `<project>` element's
   attributes (`rate`, `snapto`, `selectionformat`, `audacityversion`, ...),
   every `<wavetrack>`, `<labeltrack>`, `<notetrack>`, `<timetrack>` and their
   attributes (`name`, `channel`, `linked`, `mute`, `solo`, `rate`, `height`,
   `gain`, `pan`, ...), clip counts, block-file references, and `<tags>` metadata
   (title/artist/album/year/genre/comments).
2. **INI parsing of `~/.audacity-data/audacity.cfg`** - user preferences
   (theme, default sample rate, warnings, import/export defaults, etc.). The
   plugin registry at `~/.audacity-data/pluginregistry.cfg` is parsed the same
   way.
3. **`ffprobe`** - verifies exported audio files (WAV / MP3 / OGG / FLAC) for
   codec, sample rate, channel count, duration, bit rate.
4. **File-system checks** - plain file/size checks, plus the companion
   `<name>_data/` directory audacity writes beside each `.aup` file.

## Skipped Categories

- **UI window layout** - Audacity 2.x does not persist toolbar / panel / track
  panel layout in a reliably parseable format across sessions.
- **Keybindings** - stored in `audacity.cfg` but are flat string keys best
  treated as generic preferences (use `preference` / `check-preference`).
- **Plugin deep introspection** - the plugin registry is enumerable via
  `plugins`, but we do not evaluate plugin internals.
- **Live app state** - Audacity 2.x has no stable IPC/API we can rely on in the
  sandbox (mod-script-pipe is compiled but disabled by default and fragile);
  all verification is file-based.

## `.aup` XML Structure

```xml
<?xml version="1.0" standalone="no" ?>
<project xmlns="http://audacity.sourceforge.net/xml/"
         projname="song_data"
         audacityversion="2.4.2"
         sel0="0.0" sel1="2.0"
         selectionformat="hh:mm:ss"
         vpos="0" h="0.0" zoom="86.1328125"
         rate="44100.0" snapto="Off">
  <tags>
    <tag name="TITLE" value="Sunset"/>
    <tag name="ARTIST" value="Demo"/>
    <tag name="YEAR" value="2024"/>
  </tags>
  <wavetrack name="Vocal" channel="0" linked="0" mute="0" solo="0"
             rate="44100" gain="1.0" pan="0.0">
    <waveclip offset="0.0" colorindex="0">
      <sequence maxsamples="262144" sampleformat="262159" numsamples="88200">
        <waveblock start="0">
          <simpleblockfile filename="e000001.au" len="88200" min="-0.8" max="0.8" rms="0.5"/>
        </waveblock>
      </sequence>
      <envelope numpoints="0"/>
    </waveclip>
  </wavetrack>
  <labeltrack name="Markers" numlabels="2">
    <label t="0.5" t1="0.5" title="Intro"/>
    <label t="1.5" t1="1.5" title="Chorus"/>
  </labeltrack>
</project>
```

Audio sample data lives in the sibling `song_data/` directory; the `.aup`
only references block files by name. The verifier does not need the block
files to exist in order to parse the project.

## CLI Usage

```bash
# Query endpoints
python3 audacity.py project-info /path/to/song.aup
python3 audacity.py project-attrs /path/to/song.aup
python3 audacity.py tracks /path/to/song.aup
python3 audacity.py track /path/to/song.aup 0        # by index
python3 audacity.py track /path/to/song.aup Drums    # by name
python3 audacity.py label-tracks /path/to/song.aup
python3 audacity.py labels /path/to/song.aup
python3 audacity.py note-tracks /path/to/song.aup
python3 audacity.py time-tracks /path/to/song.aup
python3 audacity.py tags /path/to/song.aup
python3 audacity.py blockfile-count /path/to/song.aup
python3 audacity.py data-dir-info /path/to/song.aup

# Preferences (audacity.cfg)
python3 audacity.py preferences             # all sections
python3 audacity.py preferences AudioIO     # one section
python3 audacity.py preference AudioIO PlaybackDevice
python3 audacity.py preference-sections
python3 audacity.py plugins                 # pluginregistry.cfg

# Exports (ffprobe)
python3 audacity.py export-info /path/to/out.wav

# File checks
python3 audacity.py check-file-exists /path/to/song.aup
python3 audacity.py check-file-size-min /path/to/out.wav 1000

# .aup checks (return {"match": true/false, ...} or {"exists"/"valid": ...})
python3 audacity.py check-valid-aup /path/to/song.aup
python3 audacity.py check-track-count /path/to/song.aup 2
python3 audacity.py check-labeltrack-count /path/to/song.aup 1
python3 audacity.py check-track-name /path/to/song.aup Vocal
python3 audacity.py check-track-rate /path/to/song.aup 44100
python3 audacity.py check-project-rate /path/to/song.aup 44100
python3 audacity.py check-track-mute /path/to/song.aup 0 false
python3 audacity.py check-track-solo /path/to/song.aup 1 true
python3 audacity.py check-track-gain /path/to/song.aup 0 1.0
python3 audacity.py check-track-pan  /path/to/song.aup 0 0.0
python3 audacity.py check-snapto /path/to/song.aup Off
python3 audacity.py check-selection-format /path/to/song.aup hh:mm:ss
python3 audacity.py check-blockfile-count-min /path/to/song.aup 1
python3 audacity.py check-label-exists /path/to/song.aup Chorus
python3 audacity.py check-label-count /path/to/song.aup 2
python3 audacity.py check-data-dir-exists /path/to/song.aup

# Tag / metadata checks
python3 audacity.py check-tag-value /path/to/song.aup TITLE "Sunset Melody"
python3 audacity.py check-tag-contains /path/to/song.aup COMMENTS project

# Preference checks
python3 audacity.py check-preference QualityInternal SampleRate 48000
python3 audacity.py check-preference-exists Warnings FirstProjectSave

# Export checks
python3 audacity.py check-export-exists /path/to/out.wav
python3 audacity.py check-export-codec /path/to/out.wav pcm_s16le
python3 audacity.py check-export-sample-rate /path/to/out.wav 44100
python3 audacity.py check-export-channels /path/to/out.wav 2
python3 audacity.py check-export-duration-min /path/to/out.wav 1.0
python3 audacity.py check-export-format /path/to/out.wav wav
```

## Endpoint Reference

### Query endpoints

| Command | Args | Returns |
|---|---|---|
| `project-info` | `aup_path` | dict with `attributes`, `wavetrack_count`, `labeltrack_count`, `notetrack_count`, `timetrack_count`, `track_names`, `blockfile_count`, `tag_count`, `data_dir`, `data_dir_exists` |
| `project-attrs` | `aup_path` | flat `<project>` attribute dict |
| `tracks` | `aup_path` | list of wavetrack dicts (each has `name`, `channel`, `mute`, `solo`, `rate`, `gain`, `pan`, `_clip_count`, `_sequence_count`, `_total_numsamples`) |
| `track` | `aup_path`, `index_or_name` | single wavetrack dict or `{"error": ...}` |
| `label-tracks` | `aup_path` | list of label-track dicts with `_labels` |
| `labels` | `aup_path` | flat list of `{"track","title","t","t1"}` |
| `note-tracks` | `aup_path` | list of note-track dicts |
| `time-tracks` | `aup_path` | list of time-track dicts |
| `tags` | `aup_path` | dict of `{tag_name: value}` |
| `blockfile-count` | `aup_path` | `{"count": N}` |
| `data-dir-info` | `aup_path` | `{"data_dir","exists","file_count","total_bytes"}` |
| `preferences` | `[section]` | all sections or one as `{key:value}` |
| `preference` | `section`, `key` | `{"section","key","value"}` |
| `preference-sections` | - | list of section names |
| `plugins` | - | parsed `pluginregistry.cfg` |
| `export-info` | `path` | raw ffprobe JSON |

### Check endpoints

All `check-*` endpoints return a JSON dict whose primary key
(`match`/`exists`/`valid`) is a boolean the verification agent reads as the
reward signal. Additional context (expected, actual, etc.) is included for
debugging.

| Command | Args | Primary key |
|---|---|---|
| `check-file-exists` | `path` | `exists` |
| `check-file-size-min` | `path`, `min_bytes` | `match` |
| `check-valid-aup` | `aup_path` | `valid` |
| `check-track-count` | `aup_path`, `N` | `match` |
| `check-labeltrack-count` | `aup_path`, `N` | `match` |
| `check-track-name` | `aup_path`, `name` | `match` |
| `check-track-rate` | `aup_path`, `rate` | `match` |
| `check-project-rate` | `aup_path`, `rate` | `match` |
| `check-track-mute` | `aup_path`, `idx`, `true/false` | `match` |
| `check-track-solo` | `aup_path`, `idx`, `true/false` | `match` |
| `check-track-gain` | `aup_path`, `idx`, `float` | `match` |
| `check-track-pan`  | `aup_path`, `idx`, `float` | `match` |
| `check-snapto` | `aup_path`, `value` | `match` |
| `check-selection-format` | `aup_path`, `value` | `match` |
| `check-blockfile-count-min` | `aup_path`, `N` | `match` |
| `check-label-exists` | `aup_path`, `title` | `match` |
| `check-label-count` | `aup_path`, `N` | `match` |
| `check-data-dir-exists` | `aup_path` | `exists` |
| `check-tag-value` | `aup_path`, `name`, `value` | `match` |
| `check-tag-contains` | `aup_path`, `name`, `substring` | `match` |
| `check-preference` | `section`, `key`, `value` | `match` |
| `check-preference-exists` | `section`, `key` | `exists` |
| `check-export-exists` | `path` | `valid` |
| `check-export-codec` | `path`, `codec` | `match` |
| `check-export-sample-rate` | `path`, `rate` | `match` |
| `check-export-channels` | `path`, `N` | `match` |
| `check-export-duration-min` | `path`, `seconds` | `match` |
| `check-export-format` | `path`, `format` | `match` |
| `check-export-peak-db` | `path`, `min_db`, `max_db` | `match` |
| `check-export-region-silent` | `path`, `start`, `end`, `max_rms_db` | `match` |
| `check-export-region-rms-db` | `path`, `start`, `end`, `min_db`, `max_db` | `match` |
| `check-export-dominant-freq` | `path`, `start`, `end`, `expected_hz`, `tolerance_pct` | `match` |
| `check-export-band-energy-ratio-max` | `path`, `cutoff_hz`, `max_ratio` | `match` |

## Sandbox Integration

```python
from e2b_desktop import Sandbox
sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)
sandbox.commands.run("mkdir -p /home/user/verifiers")
sandbox.files.write(
    "/home/user/verifiers/audacity.py",
    open("verifiers/audacity/audacity.py").read(),
)
r = sandbox.commands.run(
    "python3 /home/user/verifiers/audacity.py project-info /home/user/song.aup"
)
import json
data = json.loads(r.stdout)
```

## Common Verification Patterns

**Task "Save the project to /home/user/song.aup":**
```json
{"command": "check-file-exists /home/user/song.aup", "key": "exists", "expected": true}
```

**Task "Add two audio tracks":**
```json
{"command": "check-track-count /home/user/song.aup 2", "key": "match", "expected": true}
```

**Task "Set the project rate to 48000 Hz":**
```json
{"command": "check-project-rate /home/user/song.aup 48000", "key": "match", "expected": true}
```

**Task "Set ARTIST metadata to 'The Demo Band'":**
```json
{"command": "check-tag-value /home/user/song.aup ARTIST \"The Demo Band\"", "key": "match", "expected": true}
```

**Task "Export to WAV":**
```json
{"command": "check-export-codec /home/user/out.wav pcm_s16le", "key": "match", "expected": true}
```

## Dependencies

- Python 3.10+ standard library only (`xml.etree.ElementTree`, `configparser`,
  `subprocess`, `json`, `pathlib`).
- `ffprobe` (from `ffmpeg`) for any `check-export-*` or `export-info` call.
  Pre-installed in `desktop-all-apps`.
