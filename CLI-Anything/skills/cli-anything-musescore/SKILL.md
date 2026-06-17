---
name: "cli-anything-musescore"
description: >-
  Command-line interface for MuseScore score creation, existing MSCX/MSCZ patching, preferences, export, transposition, parts, instruments, and score analysis.
---

# cli-anything-musescore

A command-line interface for MuseScore-style notation tasks, including direct `.mscz` / `.mscx` score generation and modification, preference file edits, export/render commands, transposition, part extraction, instrument operations, and score inspection.

## Installation

This CLI is installed as part of the cli-anything-musescore package:

```bash
pip install cli-anything-musescore
```

**Prerequisites:**
- Python 3.11+
- No MuseScore GUI is required for direct `.mscz` / `.mscx` generation, patching, preference edits, or verifier-readable fallback exports
- A MuseScore backend is required for full rendered export, transposition, and part extraction

## Usage

### Basic Commands

```bash
# Show help
cli-anything-musescore --help

# Start interactive REPL mode
cli-anything-musescore

# Create a new score file
cli-anything-musescore score create -o score.mscz

# Run with JSON output
cli-anything-musescore --json score create -o score.mscz
```

### REPL Mode

When invoked without a subcommand, the CLI enters an interactive REPL session:

```bash
cli-anything-musescore
# Enter commands interactively with history support
```

## Command Groups

### Score

Direct MSCX/MSCZ score generation and patching commands.

| Command | Description |
|---------|-------------|
| `create` | Create a verifier-readable `.mscz` or `.mscx` score |
| `set-meta` | Set a score `metaTag` value |
| `set-time` | Set the first time signature |
| `set-key` | Set the first key accidental count |
| `set-tempo` | Set the first tempo in BPM |
| `add-lyric` | Add a lyric to a note in a measure |
| `add` | Add a notation/style element such as dynamic, hairpin, chord symbol, repeat, marker, jump, layout break, pedal, fingering, or ornament |

### Config

MuseScore preference file commands.

| Command | Description |
|---------|-------------|
| `set-preference` | Set a MuseScore3.ini preference value |

### Project

Project management commands.

| Command | Description |
|---------|-------------|
| `info` | Show score information |
| `open` | Open a score file |
| `save` | Save or convert a score to `.mscz` via backend export |

### Transpose

Transposition commands.

| Command | Description |
|---------|-------------|
| `by-key` | Transpose to a target key |
| `by-interval` | Transpose by a chromatic interval |
| `diatonic` | Transpose diatonically |

### Parts

Part extraction and management commands.

| Command | Description |
|---------|-------------|
| `list` | List all parts in a score |
| `extract` | Extract a single part from a score |
| `generate` | Generate all parts as separate files |

### Export

Export/render commands.

| Command | Description |
|---------|-------------|
| `pdf` | Export as PDF document |
| `png` | Export as PNG images |
| `svg` | Export as SVG vector graphics |
| `wav` | Export as WAV audio |
| `mp3` | Export as MP3 audio |
| `flac` | Export as FLAC audio |
| `midi` | Export as MIDI file |
| `musicxml` | Export as MusicXML |
| `braille` | Export as Braille music notation |
| `batch` | Export to multiple formats at once |
| `verify` | Verify an exported file using magic bytes |

### Instruments

Instrument management commands.

| Command | Description |
|---------|-------------|
| `list` | List instruments in a score |
| `add` | Add an instrument to a score |
| `remove` | Remove an instrument from a score |
| `reorder` | Reorder instruments in a score |

### Media

Media analysis commands.

| Command | Description |
|---------|-------------|
| `probe` | Probe score metadata |
| `stats` | Show score statistics |
| `diff` | Diff two scores |

### Session

Session management commands.

| Command | Description |
|---------|-------------|
| `status` | Show session status |
| `undo` | Undo the last operation |
| `redo` | Redo the last undone operation |
| `history` | Show undo history |

## Examples

```bash
cli-anything-musescore --json score create -o score.mscz --title "Etude" --composer "Ada" --instrument "Piano" --instrument-id keyboard.piano --measures 4 --notes-per-measure 2 --key 0 --time 4/4 --tempo 120

cli-anything-musescore --json score set-meta -i existing.mscz --name workTitle --value "Updated Etude"
```

## State Management

The CLI maintains session state with:

- **Undo/Redo**: Session commands expose history navigation
- **Score persistence**: Direct score commands can update existing `.mscz` / `.mscx` files in place or write a separate output with `-o`
- **Backend interoperability**: Backend-backed commands operate on MuseScore-compatible score files

## Output Formats

All commands support dual output modes:

- Human-readable output by default
- JSON output with `--json` for agent consumption
