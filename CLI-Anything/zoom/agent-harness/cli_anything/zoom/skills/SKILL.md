---
name: "cli-anything-zoom"
description: >-
  Command-line interface for Zoom meetings, participants, recordings, and local Zoom desktop artifacts.
---

# cli-anything-zoom

A command-line interface for Zoom meeting workflows and local Zoom desktop configuration, data, log, recording, and file artifacts.

## Installation

This CLI is installed as part of the cli-anything-zoom package:

```bash
pip install cli-anything-zoom
```

**Prerequisites:**
- Python 3.10+
- Zoom OAuth credentials are required for REST API meeting, participant, and cloud recording commands

## Usage

### Basic Commands

```bash
# Show help
cli-anything-zoom --help

# Start interactive REPL mode
cli-anything-zoom

# Run with JSON output
cli-anything-zoom --json config set General autoMuteMic true
```

### REPL Mode

When invoked without a subcommand, the CLI enters an interactive REPL session:

```bash
cli-anything-zoom
```

## Command Groups

### Auth

Authentication and OAuth2 setup.

| Command | Description |
|---------|-------------|
| `setup` | Configure OAuth app credentials |
| `login` | Login via OAuth2 browser flow |
| `status` | Check authentication status |
| `logout` | Remove saved tokens |

### Config

Zoom desktop config commands.

| Command | Description |
|---------|-------------|
| `set` | Set a value in `zoomus.conf` |
| `seed-json` | Seed `zoomus.conf` from a JSON object |

### Data

Zoom local data file commands.

| Command | Description |
|---------|-------------|
| `write` | Write a file under the Zoom data directory |

### Log

Zoom local log file commands.

| Command | Description |
|---------|-------------|
| `write` | Write a file under the Zoom logs directory |

### Artifact

Generic local file artifact commands.

| Command | Description |
|---------|-------------|
| `touch-file` | Create or replace a local file |
| `ensure-directory` | Create a local directory |

### Meeting

Meeting management commands.

| Command | Description |
|---------|-------------|
| `create` | Create a new Zoom meeting |
| `list` | List meetings |
| `info` | Get meeting details |
| `update` | Update a meeting |
| `delete` | Delete a meeting |
| `join` | Open meeting join URL in browser |
| `start` | Open meeting start URL in browser |

### Participant

Participant management commands.

| Command | Description |
|---------|-------------|
| `add` | Register a participant for a meeting |
| `add-batch` | Batch register participants from a CSV file |
| `list` | List registered participants |
| `remove` | Cancel a participant's registration |
| `attended` | List participants who attended a past meeting |

### Recording

Recording commands.

| Command | Description |
|---------|-------------|
| `list` | List cloud recordings |
| `files` | List recording files for a meeting |
| `download` | Download a recording file |
| `delete` | Delete all recordings for a meeting |
| `set-path` | Set local recording path in `zoomus.conf` |
| `add-file` | Create a local recording file |

### REPL

Interactive session command.

| Command | Description |
|---------|-------------|
| `repl` | Start interactive REPL session |

## Examples

### Local Zoom Artifacts

```bash
cli-anything-zoom --json config set General autoMuteMic true
cli-anything-zoom --json recording set-path /tmp/zoom-recordings
cli-anything-zoom --json recording add-file meeting.mp4 --content "recording"
```

### Meeting Workflow

```bash
cli-anything-zoom auth setup --client-id "$ZOOM_CLIENT_ID" --client-secret "$ZOOM_CLIENT_SECRET"
cli-anything-zoom --json meeting create --topic "Standup" --duration 30
```

## Output Formats

All commands support dual output modes:

- Human-readable output by default
- Machine-readable JSON with `--json`

## Version

2.0.0
