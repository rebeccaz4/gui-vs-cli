# Godot 4 Verifier

Programmatic state inspection for Godot 4 projects in the `desktop-all-apps`
E2B sandbox. Godot stores its entire project as human-readable text files
(`project.godot`, `.tscn` scenes, `.gd` scripts, `.tres` resources) so
verification is done by parsing those files directly. A single live endpoint
uses `godot4 --headless --check-only` to confirm the project is syntactically
valid.

## Prerequisites

- `/usr/local/bin/godot4` (already installed in the sandbox).
- No special flags — all endpoints read files from disk.
- Upload this file to `/home/user/verifiers/godot4.py`.

## Verification channels

| Channel | Covered state |
|---|---|
| `project.godot` parser (INI-like) | app name, main scene, display size, renderer, autoloads, input map, physics, feature tags, arbitrary section/subkey lookups |
| `.tscn` scene parser | node tree (name/type/parent), node properties, `ext_resource` references, `sub_resource` blocks, script attachments |
| `.gd` script parser | `class_name`, `extends`, `func` list (name + arg count), `@export` variables, `signal` declarations, `const` / `var` names |
| `.tres` resource parser | resource type (`gd_resource type="..."`), top-level `[resource]` properties |
| `editor_settings-4.X.tres` | global editor preferences (font size, theme, tab size, etc.) when present |
| `godot4 --headless --check-only` | live check that the project still parses/loads |

### Skipped categories

- **Bookmarks / favorites / history** — Godot stores none of these in a machine-
  readable format accessible to the sandbox.
- **UI layout of the editor (panel sizes, docks)** — not exposed in any file the
  verifier can read; would require running the GUI editor.
- **Runtime game state** — this verifier inspects project files, not a running
  game. Use live `godot4 --headless --script` invocations if you need that.

## Running

Every endpoint returns JSON to stdout. `check-*` endpoints return a primary
boolean key that is suitable as a reward signal.

```bash
python3 /home/user/verifiers/godot4.py <command> [args...]
```

## Endpoint reference

### project.godot

- `project-sections <project.godot>` — list all `[section]` names.
- `project-section <project.godot> <section>` — all key/value pairs in a section.
- `project-setting <project.godot> <section/subkey>` — specific value, e.g.
  `application/config/name` or `rendering/renderer/rendering_method`.
- `input-actions <project.godot>` — input action map as `{name: {events: [...], raw}}`.
- `autoloads <project.godot>` — autoload singletons as `{name: path}`.
- `check-project-parses <project.godot>` — runs `godot4 --headless --check-only --path <dir>`. Returns `{"parses": true}` on success.
- `check-project-setting <project.godot> <section/subkey> <value>` — compares
  parsed value to the expected value. `value` is parsed as JSON when possible
  (e.g. numbers, booleans, quoted strings).
- `check-input-action <project.godot> <action>` — action exists.
- `check-input-action-key <project.godot> <action> <KEYCODE>` — action has a
  binding to a given key (by name `A`, `SPACE`, `ESCAPE`, or decimal keycode).
- `check-autoload <project.godot> <name>` — autoload by name exists.

### .tscn scenes

- `scene-nodes <scene.tscn>` — list nodes with `{name, type, parent, properties}`.
- `scene-node <scene.tscn> <name>` — full record for one node.
- `scene-ext-resources <scene.tscn>` — all `[ext_resource]` headers.
- `scene-sub-resources <scene.tscn>` — all `[sub_resource]` blocks.
- `check-node-exists <scene.tscn> <name>`
- `check-node-type <scene.tscn> <name> <Type>`
- `check-node-parent <scene.tscn> <name> <parent_path>` — `.`, `Player`, etc.
- `check-node-property <scene.tscn> <name> <prop> <value>` — value JSON-parsed.
  Substring match is allowed for string properties.
- `check-node-count <scene.tscn> <N>`
- `check-scene-has-script <scene.tscn> <path_substring>` — substring match on an
  `ext_resource` of `type="Script"`.

### .gd scripts

- `script-info <script.gd>` — structural summary.
- `check-script-class-name <script.gd> <name>`
- `check-script-extends <script.gd> <TypeSubstring>`
- `check-script-func <script.gd> <func_name>`
- `check-script-export <script.gd> <var_name>` — `@export var var_name` exists.
- `check-script-signal <script.gd> <signal_name>`

### .tres resources

- `resource-info <resource.tres>` — returns `{type, properties}`.
- `check-resource-type <resource.tres> <TypeName>`
- `check-resource-property <resource.tres> <prop> <value>`

### Editor settings

- `editor-settings [key]` — read `~/.config/godot/editor_settings-4.*.tres`.
- `check-editor-setting <key> <value>`

### Generic file helpers

- `file-exists <path>` — presence/size/is_file/is_dir.
- `check-file-contains <path> <text>` — substring match.
- `list-files <project_dir> <extension>` — recursive list of files by extension
  (e.g. `list-files /home/user/game tscn`).

## Common verification patterns

### Check that the project was created and parses

```json
{"command": "file-exists /home/user/game/project.godot", "key": "exists", "expected": true},
{"command": "check-project-parses /home/user/game/project.godot", "key": "parses", "expected": true}
```

### Check that the project name and main scene were set

```json
{"command": "check-project-setting /home/user/game/project.godot application/config/name \"My Game\"", "key": "match", "expected": true},
{"command": "check-project-setting /home/user/game/project.godot application/run/main_scene \"res://main.tscn\"", "key": "match", "expected": true}
```

### Check that a scene was built with specific nodes

```json
{"command": "check-node-exists /home/user/game/main.tscn Player", "key": "exists", "expected": true},
{"command": "check-node-type /home/user/game/main.tscn Player CharacterBody2D", "key": "match", "expected": true},
{"command": "check-node-parent /home/user/game/main.tscn Sprite2D Player", "key": "match", "expected": true}
```

### Check that a GDScript has required structure

```json
{"command": "check-script-class-name /home/user/game/scripts/player.gd Player", "key": "match", "expected": true},
{"command": "check-script-func /home/user/game/scripts/player.gd take_damage", "key": "exists", "expected": true},
{"command": "check-script-export /home/user/game/scripts/player.gd speed", "key": "exists", "expected": true}
```
