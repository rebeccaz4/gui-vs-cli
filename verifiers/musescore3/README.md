# MuseScore 3 Verifier

Programmatic state inspection for MuseScore 3 score files (`.mscz` / `.mscx`), the
user preference file (`MuseScore3.ini`), and exported artifacts (MIDI, MusicXML,
WAV, PDF, PNG) in an E2B sandbox.

## Verification Channels

1. **`.mscz` ZIP archive parsing.** `.mscz` is a ZIP containing a `.mscx` XML file.
   The verifier unzips and parses the inner `.mscx` with `xml.etree.ElementTree`.
2. **`.mscx` XML parsing** (same format, raw).
3. **`MuseScore3.ini`** — Qt-style INI at `~/.config/MuseScore/MuseScore3.ini`
   holding user preferences (autosave, start-center, language, soundfont, etc.).
4. **Exports:**
   - **MIDI** (`.mid` / `.midi`) — stdlib byte-level parser for format/track/note/tempo.
   - **MusicXML** (`.xml` / `.musicxml`) — ElementTree parser for parts/measures/notes.
   - **WAV** — stdlib `wave` module for duration/channels/sample rate.
   - **PDF** — magic-byte sniff (`%PDF-`).
   - **PNG** — magic-byte sniff (`\x89PNG`).

No third-party dependencies. Python standard library only.

## Usage

```bash
# CLI (inside sandbox)
python3 /home/user/verifiers/musescore3.py score-info /home/user/Documents/song.mscz
python3 /home/user/verifiers/musescore3.py metadata /home/user/Documents/song.mscz
python3 /home/user/verifiers/musescore3.py check-tempo /home/user/Documents/song.mscz 120
python3 /home/user/verifiers/musescore3.py check-preference application.autoSaveInterval 5

# From a verification agent
result = sandbox.commands.run(
    "python3 /home/user/verifiers/musescore3.py check-time-signature "
    "/home/user/Documents/song.mscz 3 4"
)
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

Every endpoint prints JSON to stdout. Errors are reported as `{"error": "..."}`.
`check-*` endpoints return a single primary boolean (`match`, `exists`, or
`has_lyrics`) plus context for debugging.

## Commands

### Score queries

| Command | Args | Description |
|---|---|---|
| `score-info` | `<file>` | MuseScore version, program version, division |
| `metadata` | `<file>` | `metaTag` values as a dict (title, composer, etc.) |
| `parts` | `<file>` | Parts/instruments with longName/shortName/id |
| `staves` | `<file>` | Top-level staves + measure count per staff |
| `time-signature` | `<file>` | First `TimeSig` `sigN`/`sigD` |
| `key-signature` | `<file>` | First `KeySig` accidental count (positive=sharps) |
| `tempo` | `<file>` | First `Tempo` marking, converted to BPM |
| `measure-count` | `<file>` | Number of measures in the first staff |
| `note-count` | `<file>` | Total `<Note>` element count across the score |
| `lyrics` | `<file>` | All lyric syllables with text + syllabic role |
| `instruments` | `<file>` | Simple list of instrument names |

### Preference queries

| Command | Args | Description |
|---|---|---|
| `preferences` | `[ini_path]` | Full parsed `MuseScore3.ini` as nested dict |
| `preference` | `<section.key> [ini_path]` | One preference value |

`ini_path` defaults to `~/.config/MuseScore/MuseScore3.ini`. Keys can be given as
`section.key` and are matched case-insensitively with `/` ↔ `\` folding (Qt
backslash keys like `application\startup\firstStart` are matched by
`application.startup/firstStart`).

### Score checks

| Command | Args | Primary key | Description |
|---|---|---|---|
| `check-file-exists` | `<path>` | `exists` | File exists at path |
| `check-meta-tag` | `<file> <name> <expected>` | `match` | `metaTag[name]` equals expected |
| `check-has-meta-tag` | `<file> <name>` | `exists` | `metaTag[name]` is set and non-empty |
| `check-time-signature` | `<file> <num> <den>` | `match` | First TimeSig equals num/den |
| `check-key-signature` | `<file> <accidental>` | `match` | First KeySig accidental count matches |
| `check-tempo` | `<file> <bpm>` | `match` | First Tempo BPM matches within ±0.5 |
| `check-measure-count` | `<file> <count>` | `match` | First staff has N measures |
| `check-note-count` | `<file> <count>` | `match` | Exact total note count |
| `check-note-count-at-least` | `<file> <count>` | `match` | Total note count ≥ N |
| `check-part-count` | `<file> <count>` | `match` | Number of Parts equals N |
| `check-instrument` | `<file> <name>` | `exists` | Instrument with name exists (matches longName/shortName/trackName/instrumentId) |
| `check-has-lyrics` | `<file>` | `has_lyrics` | Score has at least one lyric syllable |
| `check-lyric-text` | `<file> <text>` | `match` | At least one lyric syllable contains substring |

### Preference checks

| Command | Args | Primary key | Description |
|---|---|---|---|
| `check-preference` | `<section.key> <expected> [ini_path]` | `match` | Value equals expected |
| `check-preference-exists` | `<section.key> [ini_path]` | `exists` | Key exists in INI |

### Export checks

| Command | Args | Primary key | Description |
|---|---|---|---|
| `midi-info` | `<file>` | — | Parse MIDI header/track/note/tempo |
| `check-midi-track-count` | `<file> <count>` | `match` | MIDI track count matches |
| `check-midi-has-notes` | `<file> [min]` | `match` | MIDI note_on count ≥ min (default 1) |
| `musicxml-info` | `<file>` | — | Parse MusicXML parts/measures/notes |
| `check-musicxml-parts` | `<file> <count>` | `match` | MusicXML part count matches |
| `wav-info` | `<file>` | — | WAV duration/channels/rate |
| `check-wav-duration` | `<file> <min_sec>` | `match` | WAV duration ≥ min seconds |
| `check-pdf-exists` | `<file>` | `match` | File exists and has `%PDF-` header |
| `check-png-exists` | `<file>` | `match` | File exists and has PNG header |

## Common verification patterns

```bash
# Did the agent set the time signature to 6/8?
python3 /home/user/verifiers/musescore3.py check-time-signature /home/user/Documents/song.mscz 6 8

# Did the agent set the composer metadata to "J. S. Bach"?
python3 /home/user/verifiers/musescore3.py check-meta-tag /home/user/Documents/song.mscz composer "J. S. Bach"

# Did the agent export MIDI successfully?
python3 /home/user/verifiers/musescore3.py check-midi-has-notes /home/user/Documents/song.mid 10

# Did the agent enable autosave and set the interval to 5 minutes?
python3 /home/user/verifiers/musescore3.py check-preference application.autoSave true
python3 /home/user/verifiers/musescore3.py check-preference application.autoSaveInterval 5
```

## Skipped categories

Some state categories are intentionally not exposed by endpoints because MuseScore 3
does not make them reliably available without a live GUI connection:

- **Window / UI layout** (panel positions, zoom, mixer visibility): only partially
  persisted in `MuseScore3.ini`; accessible via generic `preference` queries but
  not surfaced as dedicated `check-*` endpoints since task outcomes vary.
- **Undo history** and **command history**: not persisted to disk.
- **Extensions / plugins**: MuseScore 3 has a plugin system but installed plugins
  are not reliably listed in a machine-readable file we can parse from outside
  the GUI, so no dedicated endpoint is provided.
- **Live playback state** (transport position, MIDI output): requires a running
  MuseScore instance with IPC, which MuseScore 3 does not expose.

Tasks should avoid targeting these categories. Use the documented `check-*`
endpoints above as the source of truth for what can be verified.

## Config locations

- User preferences: `~/.config/MuseScore/MuseScore3.ini` (Qt-style INI)
- Data / templates: `~/.local/share/data/MuseScore/MuseScore3/`
