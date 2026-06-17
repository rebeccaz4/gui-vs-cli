# MuseScore 3 Verifier — Test Plan

## Module Overview

The `musescore3` verifier inspects MuseScore 3 score files (`.mscz` ZIP, `.mscx`
XML), the `~/.config/MuseScore/MuseScore3.ini` preference file, and exported
artifacts (MIDI, MusicXML, WAV, PDF, PNG). All parsing is stdlib-only. The tests
run in a live E2B sandbox from template `desktop-all-apps` where MuseScore 3 is
preinstalled. We build fixtures inside the sandbox (stdlib only) and also write
fake exported files to exercise the MIDI/MusicXML/WAV/PDF/PNG endpoints without
actually running mscore3.

## Test Groups

### G1. Help / Usage
- `--help` prints the command list, mentions MuseScore and `.mscz`, exits 0.
- Expected assertions: 3.

### G2. Error handling
- Unknown command → exit 1 + valid JSON with `error`.
- Missing required arg → exit 1 + valid JSON.
- Nonexistent file on score query → `{"error": ...}`.
- Invalid `.mscz` (not a ZIP) → `{"error": ...}`.
- Expected assertions: ~6.

### G3. Score queries (G3.1 on rich file, G3.2 on alt file)
- `score-info` → version, division.
- `metadata` → multiple metaTag entries.
- `parts` → 2 parts with longName/trackName.
- `staves` → 2 staves with correct measure counts.
- `time-signature` → 3/4 for rich file, 4/4 for alt.
- `key-signature` → 2 sharps for rich file.
- `tempo` → 120 BPM for rich file.
- `measure-count` → first staff has 4 measures.
- `note-count` → total note count matches.
- `lyrics` → two lyric syllables.
- `instruments` → list contains "Piano" and "Violin".
- Expected assertions: ~15.

### G4. Preference queries
- `preferences` (with `ini_path` arg) returns a dict containing the `application`
  and `ui` sections from our crafted INI.
- `preference application.firstStart` → value `false`.
- Case-insensitive, slash/backslash folding lookup works
  (`application.startup/showSplashScreen`).
- Missing section → error.
- Expected assertions: ~6.

### G5. Score checks — positive
- `check-file-exists` on existing file → `exists: true`.
- `check-meta-tag workTitle Sonatina` → `match: true`.
- `check-has-meta-tag composer` → `exists: true`.
- `check-time-signature 3 4` → true.
- `check-key-signature 2` → true.
- `check-tempo 120` → true.
- `check-measure-count 4` → true.
- `check-note-count` (exact) → true.
- `check-note-count-at-least 3` → true.
- `check-part-count 2` → true.
- `check-instrument Piano` → true.
- `check-has-lyrics` → true.
- `check-lyric-text hel` → true.
- Expected assertions: ~13.

### G6. Score checks — negative
- `check-file-exists` on missing file → false.
- `check-meta-tag workTitle Wrong` → false.
- `check-has-meta-tag nonexistent_tag` → false.
- `check-time-signature 6 8` → false.
- `check-key-signature 0` → false.
- `check-tempo 90` → false.
- `check-measure-count 99` → false.
- `check-note-count 999` → false.
- `check-part-count 5` → false.
- `check-instrument Trombone` → false.
- `check-lyric-text zzz_never` → false.
- Expected assertions: ~11.

### G7. Preference checks
- `check-preference application.firstStart false` → true.
- `check-preference-exists application.firstStart` → true.
- `check-preference application.firstStart true` (wrong value) → false.
- `check-preference-exists application.nonexistent_key` → false.
- Expected assertions: 4.

### G8. Export format checks
- **MIDI**: craft a minimal valid SMF (Format 1, 1 track, 2 note-on events),
  `midi-info` returns correct values, `check-midi-track-count 1` true,
  `check-midi-has-notes 2` true, negative case false.
- **MusicXML**: write a minimal MusicXML with 1 part / 2 measures / 3 notes,
  `musicxml-info` returns correct counts, `check-musicxml-parts 1` true,
  negative case false.
- **WAV**: write a 0.5-second silent mono WAV via stdlib `wave`, `wav-info`
  returns duration, `check-wav-duration 0.1` true, negative case false.
- **PDF**: write file starting with `%PDF-1.4`, `check-pdf-exists` true;
  non-PDF file → `match: false`.
- **PNG**: write file with PNG signature, `check-png-exists` true; non-PNG →
  `match: false`.
- Expected assertions: ~13.

### G9. JSON validity sweep
Call every endpoint once with reasonable arguments against the rich fixture and
assert each stdout is valid JSON.
- Expected assertions: ~65 (now includes every extension query + check-*).

### G10. Extension endpoints (new in verifier extension)

**G10a — Query families.** On the feature-rich fixture (`test_feat.mscz`),
`articulations`, `dynamics`, `hairpins`, `chord-symbols`, `voltas`, `repeats`,
`jumps-markers`, `layout-breaks`, `style`, `instrument-changes`, `pedals`,
`fingerings`, `ornaments` all return the expected populated structures. On the
bare fixture (`test_bare.mscz`) the families that return lists return `[]`.

**G10b — Positive + negative check-\* pairs for every new endpoint:**

| Endpoint | Positive | Negative |
|---|---|---|
| `check-articulation-in-measure` | staccato@1 on FEAT | fermata@1 on FEAT; staccato@1 on BARE |
| `check-articulation-count` | staccato==1 on FEAT | staccato==99 on FEAT |
| `check-dynamic-in-measure` | mf@1, ff@2 on FEAT | pp@1 on FEAT |
| `check-has-hairpin` | crescendo on FEAT | decrescendo on FEAT; crescendo on BARE |
| `check-chord-symbol-in-measure` | Cmaj7@1 on FEAT | Dm7@1 on FEAT |
| `check-has-volta-at` | m=2 on FEAT | m=1 on FEAT |
| `check-start-repeat-at` | m=1 on FEAT | m=3 on FEAT |
| `check-end-repeat-at` | m=2 on FEAT | m=1 on FEAT |
| `check-marker-text` | "Segno" on FEAT | "Coda" on FEAT |
| `check-jump-text` | "D.C." on FEAT | "Coda" on FEAT |
| `check-layout-break-at` | line@1, page@3 on FEAT | page@1 (wrong subtype), line@4 |
| `check-style-value` | pageWidth=8.5, concertPitch=0 on FEAT; concertPitch=1 on BARE | pageWidth=12, concertPitch=0 on BARE |
| `check-instrument-change-at` | Flute@3 on FEAT | Trombone@3; Flute@1 (wrong measure) |
| `check-has-pedal` | FEAT | BARE |
| `check-fingering-count-in-measure` | m=1,count>=1 on FEAT | count>=5 on FEAT; FEAT@bare |
| `check-has-ornament` | trill@1, mordent@2 on FEAT | turn@1 on FEAT; trill@1 on BARE |

Expected assertions (G10a + G10b): ~62.

**Fixtures added:**
- `/home/user/test_feat.mscz` — feature-rich score containing staccato, accent,
  tenuto articulations; trill + mordent ornaments; mf/ff dynamics; crescendo
  hairpin; Cmaj7 chord symbol; Volta at m=2; startRepeat @1 and endRepeat @2;
  Segno marker; D.C. al Fine jump; line break @1 and page break @3; `<Style>`
  overrides (pageWidth, pageHeight, concertPitch=0); InstrumentChange to Flute
  @3; Pedal spanner @2; fingerings in measures 1 and 2.
- `/home/user/test_bare.mscz` — score containing none of the above; used as
  universal negative baseline.

## Test Fixtures (generated inside the sandbox)

| Path | Description | Used by |
|---|---|---|
| `/home/user/test_rich.mscz` | Rich score: 2 parts (Piano, Violin), 2 staves, 4 measures each, tempo 120, time 3/4, key 2 sharps, lyrics on first two notes, metaTags workTitle/composer/copyright/arranger, several notes across measures | G3.1, G5, G6, G9 |
| `/home/user/test_alt.mscz` | Alt score: 1 part (Flute), 1 staff, 3 measures, 4/4 time, key 0, tempo 80, no lyrics, metaTag workTitle=Etude | G3.2 |
| `/home/user/test_invalid.mscz` | Not a valid ZIP | G2 |
| `/home/user/test_prefs.ini` | Fake MuseScore3.ini with `[application]`/`[ui]` sections | G4, G7 |
| `/home/user/test_fake.mid` | Hand-crafted SMF Format 1 with 1 track and 2 note-on events, tempo set | G8 |
| `/home/user/test_fake.musicxml` | 1 score-part, 2 measures, 3 notes | G8 |
| `/home/user/test_fake.wav` | 0.5s mono 22050 Hz silent WAV via stdlib `wave` | G8 |
| `/home/user/test_fake.pdf` | File starting with `%PDF-1.4\n` | G8 |
| `/home/user/test_fake.png` | File with PNG signature `\x89PNG\r\n\x1a\n` | G8 |
| `/home/user/not_a_pdf.bin` | File starting with `NOPE` — negative for `check-pdf-exists` | G8 |

All fixtures are created by a setup script uploaded to the sandbox and run via
`sandbox.commands.run`. No third-party deps are required.

## Edge Cases & Error Handling Matrix

| Scenario | Endpoint | Expected |
|---|---|---|
| Unknown subcommand | any | exit 1, `{"error": ...}` |
| Missing required arg | `score-info`, `check-*` | exit 1, `{"error": ...}` |
| File not found | `score-info`, `metadata`, `tempo`, etc. | `{"error": "File not found: ..."}` |
| Not a ZIP (bad `.mscz`) | any score query | `{"error": "Cannot parse ..."}` |
| Missing metaTag | `metadata` / `check-has-meta-tag` | empty dict / `exists: false` |
| Missing Tempo element | `tempo` / `check-tempo` | `{"error": "No Tempo element found"}` |
| Missing INI file | `preferences` | `{"error": "INI file not found: ..."}` |
| Missing section | `preference` | `{"error": "Section not found", "available_sections": [...]}` |
| Non-MIDI file → `midi-info` | `midi-info` | `{"error": "Not a Standard MIDI File"}` |
| WAV parse error on non-WAV | `wav-info` | `{"error": "WAV parse error: ..."}` |

## Positive / Negative Pairs Summary

Every `check-*` endpoint is covered in both G5 (positive) and G6 (negative) for
score checks, G7 (positive+negative) for preferences, and G8 (positive+negative)
for exports.

## JSON Validity Sweep (G9)

All CLI subcommands are executed against the rich fixture and their stdout
parsed as JSON.

## Summary

| Metric | Count |
|---|---|
| Test groups | 10 |
| Total assertions | 215 |
| Test fixtures (files generated) | 12 |
| `check-*` endpoints with pos+neg pairs | 36 |
| Error scenarios covered | 10 |
