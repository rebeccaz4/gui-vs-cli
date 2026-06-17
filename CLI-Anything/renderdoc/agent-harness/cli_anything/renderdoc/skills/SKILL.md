---
name: "cli-anything-renderdoc"
description: >-
  Command-line interface for RenderDoc capture analysis, qrenderdoc config files, capture settings, synthetic RDC artifacts, and renderdoccmd verifier scaffolding.
version: 0.1.0
command: cli-anything-renderdoc
install: pip install cli-anything-renderdoc
requires:
  - Python 3.11+
  - RenderDoc Python bindings for real capture replay/inspection commands
  - No RenderDoc GUI required for config, cap, rdc, or rdcmd artifact commands
categories:
  - graphics
  - debugging
  - gpu
  - rendering
---

# cli-anything-renderdoc

Headless command-line operations for RenderDoc `.rdc` captures, qrenderdoc `UI.config`, `.cap` capture settings, synthetic verifier-readable RDC files, and deterministic `renderdoccmd` scaffolding.

## Installation

This CLI is installed as part of the cli-anything-renderdoc package:

```bash
pip install cli-anything-renderdoc
```

## Usage

### Basic Commands

```bash
cli-anything-renderdoc --help
cli-anything-renderdoc
cli-anything-renderdoc --json config set UIStyle '"Dark"' --path UI.config
cli-anything-renderdoc -c frame.rdc --json actions summary
```

### REPL Mode

When invoked without a subcommand, the CLI enters an interactive REPL session:

```bash
cli-anything-renderdoc
```

## Command Groups

### Config

qrenderdoc `UI.config` commands.

| Command | Description |
|---------|-------------|
| `get` | Read `UI.config` or one key |
| `set` | Set a key to a JSON-parsed value |
| `append` | Append a value to a list-valued key |
| `keys` | List config keys |

### RDC

Direct `.rdc` artifact commands.

| Command | Description |
|---------|-------------|
| `create` | Create a minimal verifier-readable `.rdc` file |

### Cap

qrenderdoc `.cap` capture settings commands.

| Command | Description |
|---------|-------------|
| `create` | Create a qrenderdoc-compatible `.cap` file |
| `set-option` | Set one `.cap` option value |
| `add-env` | Append one environment variable |

### Rdcmd

`renderdoccmd` install-state helper commands.

| Command | Description |
|---------|-------------|
| `scaffold` | Create a deterministic `renderdoccmd` wrapper plus plugin/layer metadata |

### Capture

Capture file operations.

| Command | Description |
|---------|-------------|
| `info` | Show capture metadata and sections |
| `thumb` | Extract a capture thumbnail |
| `convert` | Convert a capture to a different format |

### Actions

Draw call and action inspection.

| Command | Description |
|---------|-------------|
| `list` | List actions in the capture |
| `summary` | Show action counts by type |
| `find` | Find actions by name pattern |
| `get` | Get one action by event ID |

### Textures

Texture inspection and export.

| Command | Description |
|---------|-------------|
| `list` | List textures |
| `get` | Get one texture by resource ID |
| `save` | Save a texture to an image file |
| `save-outputs` | Save render target outputs for an event |
| `pick` | Pick a pixel value |

### Pipeline

Pipeline state inspection.

| Command | Description |
|---------|-------------|
| `state` | Show pipeline state at an event |
| `shader-export` | Export shader source or disassembly |
| `cbuffer` | Get constant buffer contents |
| `diff` | Compare pipeline state between two events |

### Resources

Resource listing and buffer reading.

| Command | Description |
|---------|-------------|
| `list` | List resources |
| `buffers` | List buffer resources |
| `read-buffer` | Read raw buffer data |

### Mesh

Mesh data inspection.

| Command | Description |
|---------|-------------|
| `inputs` | Get vertex shader inputs |
| `outputs` | Get post-vertex-shader outputs |

### Counters

GPU performance counter commands.

| Command | Description |
|---------|-------------|
| `list` | List available counters |
| `fetch` | Fetch counter results |

### Repl

Interactive session command.

| Command | Description |
|---------|-------------|
| `repl` | Start interactive REPL session |

## Examples

```bash
cli-anything-renderdoc --json rdc create -o frame.rdc --serialise-version 258 --prog-version 1.36
cli-anything-renderdoc --json config set UIStyle '"Dark"' --path UI.config
```

## Output Modes

- Human-readable output by default
- JSON output with `--json`

## Environment Variables

| Variable | Description |
|----------|-------------|
| `RENDERDOC_CAPTURE` | Default `.rdc` capture path |
| `RENDERDOCCMD` | `renderdoccmd` path used by verifier-compatible workflows |
| `QRENDERDOC_DATA_DIR` | Directory containing `UI.config` |
| `PYTHONPATH` | Must include RenderDoc bindings for real capture replay |
