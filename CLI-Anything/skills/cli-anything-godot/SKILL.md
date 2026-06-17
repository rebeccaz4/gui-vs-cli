---
name: "cli-anything-godot"
description: >-
  Command-line interface for Godot 4 project files, scenes, scripts, resources, exports, editor settings, and engine checks.
---

# cli-anything-godot

A command-line interface for creating and editing Godot 4 projects through verifier-readable text artifacts such as `project.godot`, `.tscn`, `.gd`, `.tres`, and editor settings files.

## Installation

```bash
pip install git+https://github.com/HKUDS/CLI-Anything.git#subdirectory=godot/agent-harness
```

## Requirements

- Godot 4.x on PATH, or `GODOT_BIN` set, for engine-backed commands.

## Usage

```bash
cli-anything-godot --help
cli-anything-godot --json -p <project> <command-group> <command> [args/options]
cli-anything-godot -p <project> session
```

## Command Groups

### Project

Project file commands.

| Command | Description |
|---------|-------------|
| `create` | Create a Godot project |
| `info` | Show `project.godot` metadata |
| `scenes` | List scene files |
| `scripts` | List GDScript files |
| `resources` | List resource files |
| `reimport` | Re-import project resources through Godot |
| `set` | Set a `project.godot` value by `section/subkey` |
| `files` | List project files by extension |

### Input

Input action commands.

| Command | Description |
|---------|-------------|
| `add-action` | Create or replace an input action |

### Autoload

Autoload singleton commands.

| Command | Description |
|---------|-------------|
| `add` | Add an autoload entry |

### Scene

Scene file commands.

| Command | Description |
|---------|-------------|
| `create` | Create a `.tscn` scene |
| `read` | Read scene structure |
| `add-node` | Add a child node |
| `set-node-property` | Set a node property |
| `add-ext-resource` | Add an external resource header |
| `add-sub-resource` | Add a sub-resource block |
| `attach-script` | Attach a script to a node |

### Script

GDScript commands.

| Command | Description |
|---------|-------------|
| `run` | Run a GDScript file through Godot |
| `inline` | Run inline GDScript through Godot |
| `validate` | Validate GDScript syntax |
| `create` | Create a persistent GDScript file |
| `add-func` | Add or replace a function |
| `add-export` | Add or replace an exported variable |
| `add-signal` | Add or replace a signal |
| `add-var` | Add or replace a variable or constant |

### Resource

Resource file commands.

| Command | Description |
|---------|-------------|
| `create` | Create a `.tres` resource |
| `set-property` | Set a resource property |

### Editor

Editor settings commands.

| Command | Description |
|---------|-------------|
| `set` | Set an editor setting |

### Export

Export commands.

| Command | Description |
|---------|-------------|
| `build` | Export the project |
| `presets` | List configured export presets |

### Engine

Engine commands.

| Command | Description |
|---------|-------------|
| `version` | Show Godot version |
| `status` | Check Godot availability |

### Top-Level

Top-level commands.

| Command | Description |
|---------|-------------|
| `session` | Start interactive REPL mode |

## Examples

```bash
cli-anything-godot project create ./game --name "My Game"
cli-anything-godot --json -p ./game project set application/run/main_scene res://main.tscn
```

## Notes

- Use `--json` for structured output.
- Use `--raw` for Godot syntax values such as numbers, booleans, `Vector2(...)`, and `ExtResource(...)`.
