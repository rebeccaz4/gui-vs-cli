# Godot 4 Verifier — Test Plan

## Module overview

The verifier parses Godot 4 text-based project files (`project.godot`, `.tscn`,
`.gd`, `.tres`, `editor_settings-4.X.tres`) and exposes one live endpoint that
runs `godot4 --headless --check-only` to confirm the project loads.

Channels used:
1. Custom stdlib INI-like parser (`project.godot`, `.tscn`, `.tres`)
2. Regex-based GDScript parser (`.gd`)
3. Subprocess call to `godot4` for `check-project-parses`

Prerequisites: `/usr/local/bin/godot4` must be installed. All other endpoints
work purely by reading files from disk.

## Test groups

### Group 1 — Help / usage (2 assertions)
- `--help` exits 0 and mentions "Godot".

### Group 2 — Unknown command (2 assertions)
- Unknown subcommand exits 1 with JSON error.

### Group 3 — Missing required args (16 assertions)
Every CLI command that requires positional arguments must exit 1 and return
valid JSON error when run without arguments.

### Group 4 — project.godot parsing (10 assertions)
- `project-sections` returns application/autoload/display/input/rendering.
- `project-section application` contains `config/name`.
- `project-setting application/config/name` finds the correct value.
- `project-setting` on nonexistent key reports `found=false`.
- `input-actions` lists `move_left` and `move_right`.
- `autoloads` lists `GameManager`.

### Group 5 — project.godot check-* (pos + neg, 10 assertions)
- `check-project-setting application/config/name "Test Game"` match=true.
- Same with wrong value → match=false.
- `check-input-action move_left` → exists=true; on unknown action → false.
- `check-input-action-key move_left A` → match=true; with `Z` → false.
- `check-autoload GameManager` → exists=true; with bogus name → false.

### Group 6 — check-project-parses (2 assertions)
- Running on a valid project returns `parses=true`.
- Running on a path to a nonexistent file returns an error with `parses=false`.

### Group 7 — .tscn parsing (10 assertions)
- `scene-nodes` returns 4 nodes (Main, Player, Sprite2D, Label).
- `scene-node Player` found=true, type=CharacterBody2D.
- `scene-ext-resources` includes one Script and one Texture2D.
- `scene-sub-resources` includes RectangleShape2D.
- `scene-node` on missing name → found=false.

### Group 8 — .tscn check-* (pos + neg, 12 assertions)
- `check-node-exists Player` true; `NotThere` false.
- `check-node-type Sprite2D Sprite2D` true; wrong type false.
- `check-node-parent Sprite2D Player` true; wrong parent false.
- `check-node-property Label text "Hello World"` true; wrong value false.
- `check-node-count 4` true; wrong count false.
- `check-scene-has-script player.gd` true; missing substring false.

### Group 9 — .gd parsing (6 assertions)
- `script-info` reports `class_name=Player`, `extends=CharacterBody2D`,
  `func_count>=3`, `export_count>=2`, signals include `health_changed`.

### Group 10 — .gd check-* (pos + neg, 10 assertions)
- `check-script-class-name Player` true; wrong name false.
- `check-script-extends CharacterBody2D` true; wrong type false.
- `check-script-func take_damage` true; missing false.
- `check-script-export speed` true; missing false.
- `check-script-signal health_changed` true; missing false.

### Group 11 — .tres parsing (6 assertions)
- `resource-info` reports `type=StandardMaterial3D`, `metallic=0.3`.
- `check-resource-type` positive/negative.
- `check-resource-property` positive/negative.

### Group 12 — Editor settings (2 assertions)
- `editor-settings` returns the mock editor settings file with
  `interface/editor/single_window_mode` present.
- `check-editor-setting interface/editor/single_window_mode true` match=true.

### Group 13 — File helpers (6 assertions)
- `file-exists` positive/negative.
- `check-file-contains` positive/negative.
- `list-files gd` returns >=1 file.

### Group 14 — JSON validity sweep (all endpoints, ~30 assertions)
Every CLI command with representative arguments returns valid JSON.

## Test fixtures

All fixtures live in `/home/user/godot_test/` inside the sandbox.

| Path | Purpose |
|---|---|
| `/home/user/godot_test/project.godot` | Realistic project file with application, autoload, display, input (2 actions), physics, rendering sections |
| `/home/user/godot_test/main.tscn` | Scene with 4 nodes (Main/Node2D, Player/CharacterBody2D, Sprite2D child of Player, Label child of Main), 2 `ext_resource`, 1 `sub_resource` |
| `/home/user/godot_test/scripts/player.gd` | GDScript with class_name, extends, 3 funcs, 2 `@export` vars, 1 signal, 1 const |
| `/home/user/godot_test/scripts/game_manager.gd` | Autoload script stub |
| `/home/user/godot_test/materials/mat.tres` | StandardMaterial3D resource with 5 properties |
| `/home/user/.config/godot/editor_settings-4.3.tres` | Mock editor settings with a handful of preferences |
| `/home/user/godot_test/broken/project.godot` | Used only as a path for `check-project-parses` negative test; actual project validity is tested on the good project |
| `/home/user/godot_test/icon.svg` | Small SVG referenced by the project |

## Edge case matrix

| Scenario | Endpoint(s) | Expected |
|---|---|---|
| Missing file | `project-*`, `scene-*`, `script-*`, `resource-*` | `{"error": "..."}` |
| Missing required arg | all CLI commands needing args | exit 1 + valid JSON |
| Unknown subcommand | any | exit 1 + valid JSON |
| godot4 binary missing | `check-project-parses` | `{"error": "godot4 not installed", "parses": false}` |
| Nonexistent project.godot key | `project-setting`, `check-project-setting` | `found=false`/`match=false` |
| Node property not set | `check-node-property` | `match=false` |
| Scene without scripts | `check-scene-has-script` | `found=false` |

## Positive/negative pairs

Every `check-*` endpoint has both a positive and a negative case in groups 5,
8, 10, 11 above (see the per-group descriptions).

## Summary

| Metric | Count |
|---|---|
| Test groups | 14 |
| Total assertions | ~125 |
| Test fixtures | 8 |
| `check-*` endpoints with pos+neg pairs | 20 |
| Error scenarios covered | 7 |
