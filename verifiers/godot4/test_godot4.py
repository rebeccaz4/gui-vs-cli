"""
Test Godot 4 verifier endpoints in a live E2B sandbox.

Covers all test groups defined in Test.md.

Usage:
    python verifiers/godot4/test_godot4.py
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "godot4.py"
VERIFIER_REMOTE = "/home/user/verifiers/godot4.py"
V = f"python3 {VERIFIER_REMOTE}"

BASE = "/home/user/godot_test"

passed = 0
failed = 0
errors: list[str] = []


class CmdResult:
    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def run(sandbox: Sandbox, cmd: str, timeout: int = 60) -> dict | list:
    r = run_raw(sandbox, cmd, timeout)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


def run_raw(sandbox: Sandbox, cmd: str, timeout: int = 60) -> CmdResult:
    try:
        result = sandbox.commands.run(f"{V} {cmd}", timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f"  -- {detail}"
        print(msg)
        errors.append(f"{name}: {detail}")


def is_valid_json(stdout: str) -> bool:
    try:
        json.loads(stdout)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Fixture contents
# ---------------------------------------------------------------------------

PROJECT_GODOT = """; Engine configuration file.
; It's best edited using the editor UI and not directly,
; since the parameters that go here are not all obvious.

config_version=5

[application]

config/name="Test Game"
run/main_scene="res://main.tscn"
config/features=PackedStringArray("4.2", "Forward Plus")
config/icon="res://icon.svg"

[autoload]

GameManager="*res://scripts/game_manager.gd"

[display]

window/size/viewport_width=1280
window/size/viewport_height=720

[input]

move_left={
"deadzone": 0.5,
"events": [Object(InputEventKey,"device":-1,"keycode":0,"physical_keycode":65,"unicode":97,"echo":false)
]
}
move_right={
"deadzone": 0.5,
"events": [Object(InputEventKey,"device":-1,"keycode":0,"physical_keycode":68,"unicode":100,"echo":false)
]
}

[physics]

2d/default_gravity=980

[rendering]

renderer/rendering_method="gl_compatibility"
"""

MAIN_TSCN = """[gd_scene load_steps=4 format=3 uid="uid://abcdefghij"]

[ext_resource type="Script" path="res://scripts/player.gd" id="1_player"]
[ext_resource type="Texture2D" path="res://icon.svg" id="2_icon"]

[sub_resource type="RectangleShape2D" id="RectangleShape2D_1"]
size = Vector2(64, 64)

[node name="Main" type="Node2D"]

[node name="Player" type="CharacterBody2D" parent="."]
position = Vector2(100, 200)
script = ExtResource("1_player")

[node name="Sprite2D" type="Sprite2D" parent="Player"]
texture = ExtResource("2_icon")
modulate = Color(1, 0.5, 0.5, 1)

[node name="Label" type="Label" parent="."]
text = "Hello World"
offset_left = 20.0
offset_top = 20.0
"""

PLAYER_GD = """class_name Player
extends CharacterBody2D

signal health_changed(amount)

const MAX_SPEED = 300.0
@export var speed: float = 100.0
@export var max_health: int = 100

var current_health: int = 100

func _ready():
\tpass

func _physics_process(delta):
\tvelocity.x = speed
\tmove_and_slide()

func take_damage(amount: int):
\tcurrent_health -= amount
\thealth_changed.emit(current_health)
"""

GAME_MANAGER_GD = """extends Node

var score: int = 0

func add_score(amount: int):
\tscore += amount
"""

MAT_TRES = """[gd_resource type="StandardMaterial3D" format=3 uid="uid://xyzmaterial"]

[resource]
albedo_color = Color(0.2, 0.7, 0.4, 1)
metallic = 0.3
roughness = 0.8
emission_enabled = true
emission = Color(0.1, 0.1, 0.1, 1)
"""

EDITOR_SETTINGS_TRES = """[gd_resource type="EditorSettings" format=3]

[resource]
interface/editor/single_window_mode = true
interface/editor/display_scale = 1
text_editor/appearance/whitespace/draw_tabs = true
text_editor/behavior/indent/size = 4
interface/theme/preset = "Default"
"""

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="16" height="16" fill="#ff00ff"/></svg>
"""


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_fixtures(sandbox: Sandbox):
    print("Setting up fixtures...")
    sandbox.commands.run(f"mkdir -p {BASE}/scripts {BASE}/materials {BASE}/broken")
    sandbox.commands.run("mkdir -p /home/user/.config/godot")

    sandbox.files.write(f"{BASE}/project.godot", PROJECT_GODOT)
    sandbox.files.write(f"{BASE}/main.tscn", MAIN_TSCN)
    sandbox.files.write(f"{BASE}/scripts/player.gd", PLAYER_GD)
    sandbox.files.write(f"{BASE}/scripts/game_manager.gd", GAME_MANAGER_GD)
    sandbox.files.write(f"{BASE}/materials/mat.tres", MAT_TRES)
    sandbox.files.write(f"{BASE}/icon.svg", ICON_SVG)
    sandbox.files.write("/home/user/.config/godot/editor_settings-4.3.tres", EDITOR_SETTINGS_TRES)

    print("  fixtures written")


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

def test_help(sandbox):
    print("\n=== Group 1: Help ===")
    r = run_raw(sandbox, "--help")
    check("help exits 0", r.exit_code == 0, f"got {r.exit_code}")
    check("help mentions Godot", "Godot" in r.stdout, r.stdout[:80])


def test_unknown(sandbox):
    print("\n=== Group 2: Unknown command ===")
    r = run_raw(sandbox, "bogus-command")
    check("unknown exits 1", r.exit_code == 1, f"got {r.exit_code}")
    check("unknown valid JSON", is_valid_json(r.stdout), r.stdout[:80])


def test_missing_args(sandbox):
    print("\n=== Group 3: Missing args ===")
    cmds = [
        "project-sections", "project-section", "project-setting",
        "input-actions", "autoloads", "check-project-parses",
        "check-project-setting", "check-input-action", "check-input-action-key",
        "check-autoload", "scene-nodes", "check-node-exists",
        "script-info", "check-script-class-name", "resource-info",
        "check-resource-type",
    ]
    for cmd in cmds:
        r = run_raw(sandbox, cmd)
        check(f"{cmd} missing arg exits 1", r.exit_code == 1, f"got {r.exit_code}")
        check(f"{cmd} missing arg valid JSON", is_valid_json(r.stdout), r.stdout[:80])


def test_project_parsing(sandbox):
    print("\n=== Group 4: project.godot parsing ===")
    proj = f"{BASE}/project.godot"

    data = run(sandbox, f"project-sections {proj}")
    sections = set(data.get("sections", []))
    check("sections includes application", "application" in sections, str(sections))
    check("sections includes autoload", "autoload" in sections, str(sections))
    check("sections includes input", "input" in sections, str(sections))
    check("sections includes rendering", "rendering" in sections, str(sections))

    data = run(sandbox, f"project-section {proj} application")
    check("application section has config/name",
          "config/name" in data.get("keys", {}), str(data)[:200])

    data = run(sandbox, f'project-setting {proj} application/config/name')
    check("project-setting app name found", data.get("found") is True, str(data)[:200])
    check("project-setting app name value", data.get("value") == "Test Game", str(data)[:200])

    data = run(sandbox, f"project-setting {proj} application/doesnotexist")
    check("missing key found=false", data.get("found") is False, str(data)[:200])

    data = run(sandbox, f"input-actions {proj}")
    check("input-actions has move_left", "move_left" in data.get("actions", {}), str(data)[:200])
    check("input-actions has move_right", "move_right" in data.get("actions", {}), str(data)[:200])

    data = run(sandbox, f"autoloads {proj}")
    check("autoloads has GameManager",
          "GameManager" in data.get("autoloads", {}), str(data)[:200])


def test_project_checks(sandbox):
    print("\n=== Group 5: project.godot check-* ===")
    proj = f"{BASE}/project.godot"

    data = run(sandbox, f'check-project-setting {proj} application/config/name \'"Test Game"\'')
    check("project-setting match true", data.get("match") is True, str(data)[:200])

    data = run(sandbox, f'check-project-setting {proj} application/config/name \'"Other Name"\'')
    check("project-setting match false", data.get("match") is False, str(data)[:200])

    data = run(sandbox, f"check-input-action {proj} move_left")
    check("input-action exists true", data.get("exists") is True, str(data)[:200])

    data = run(sandbox, f"check-input-action {proj} nonexistent_action")
    check("input-action exists false", data.get("exists") is False, str(data)[:200])

    data = run(sandbox, f"check-input-action-key {proj} move_left A")
    check("input-action-key move_left A true", data.get("match") is True, str(data)[:200])

    data = run(sandbox, f"check-input-action-key {proj} move_left Q")
    check("input-action-key move_left Q false", data.get("match") is False, str(data)[:200])

    data = run(sandbox, f"check-autoload {proj} GameManager")
    check("autoload GameManager true", data.get("exists") is True, str(data)[:200])

    data = run(sandbox, f"check-autoload {proj} Bogus")
    check("autoload Bogus false", data.get("exists") is False, str(data)[:200])

    data = run(sandbox, f'check-project-setting {proj} display/window/size/viewport_width 1280')
    check("display viewport width match", data.get("match") is True, str(data)[:200])


def test_project_parses(sandbox):
    print("\n=== Group 6: check-project-parses ===")
    proj = f"{BASE}/project.godot"
    data = run(sandbox, f"check-project-parses {proj}", timeout=90)
    check("valid project parses", data.get("parses") is True,
          f"returncode={data.get('returncode')} stderr={data.get('stderr','')[:200]}")

    data = run(sandbox, f"check-project-parses /nonexistent/path.godot")
    check("missing file parses=false", data.get("parses") is False, str(data)[:200])


def test_scene_parsing(sandbox):
    print("\n=== Group 7: .tscn parsing ===")
    scene = f"{BASE}/main.tscn"

    data = run(sandbox, f"scene-nodes {scene}")
    check("scene has 4 nodes", data.get("count") == 4, str(data.get("count")))
    names = [n.get("name") for n in data.get("nodes", [])]
    check("scene node names", set(names) == {"Main", "Player", "Sprite2D", "Label"}, str(names))

    data = run(sandbox, f"scene-node {scene} Player")
    check("Player found", data.get("found") is True, str(data)[:200])
    check("Player type", data.get("node", {}).get("type") == "CharacterBody2D", str(data)[:200])

    data = run(sandbox, f"scene-node {scene} DoesNotExist")
    check("missing node found=false", data.get("found") is False, str(data)[:200])

    data = run(sandbox, f"scene-ext-resources {scene}")
    check("scene has 2 ext_resources", data.get("count") == 2, str(data)[:200])
    types = {r.get("type") for r in data.get("ext_resources", [])}
    check("ext_resources has Script", "Script" in types, str(types))
    check("ext_resources has Texture2D", "Texture2D" in types, str(types))

    data = run(sandbox, f"scene-sub-resources {scene}")
    check("scene has 1 sub_resource", data.get("count") == 1, str(data)[:200])


def test_scene_checks(sandbox):
    print("\n=== Group 8: .tscn check-* ===")
    scene = f"{BASE}/main.tscn"

    check("exist Player", run(sandbox, f"check-node-exists {scene} Player").get("exists") is True)
    check("exist NotThere false",
          run(sandbox, f"check-node-exists {scene} NotThere").get("exists") is False)

    check("type Sprite2D match",
          run(sandbox, f"check-node-type {scene} Sprite2D Sprite2D").get("match") is True)
    check("type Sprite2D wrong",
          run(sandbox, f"check-node-type {scene} Sprite2D Node3D").get("match") is False)

    check("parent Sprite2D Player",
          run(sandbox, f"check-node-parent {scene} Sprite2D Player").get("match") is True)
    check("parent Sprite2D wrong",
          run(sandbox, f"check-node-parent {scene} Sprite2D Main").get("match") is False)

    check("prop Label text true",
          run(sandbox, f'check-node-property {scene} Label text \'"Hello World"\'').get("match") is True)
    check("prop Label text false",
          run(sandbox, f'check-node-property {scene} Label text \'"Goodbye"\'').get("match") is False)

    check("count 4 true",
          run(sandbox, f"check-node-count {scene} 4").get("match") is True)
    check("count 5 false",
          run(sandbox, f"check-node-count {scene} 5").get("match") is False)

    check("has-script player.gd true",
          run(sandbox, f"check-scene-has-script {scene} player.gd").get("found") is True)
    check("has-script missing false",
          run(sandbox, f"check-scene-has-script {scene} nothere.gd").get("found") is False)


def test_script_parsing(sandbox):
    print("\n=== Group 9: .gd parsing ===")
    gd = f"{BASE}/scripts/player.gd"
    data = run(sandbox, f"script-info {gd}")
    check("class_name Player", data.get("class_name") == "Player", str(data)[:200])
    check("extends CharacterBody2D", data.get("extends") == "CharacterBody2D", str(data)[:200])
    check("func_count >= 3", data.get("func_count", 0) >= 3, str(data.get("func_count")))
    check("export_count >= 2", data.get("export_count", 0) >= 2, str(data.get("export_count")))
    check("has health_changed signal",
          "health_changed" in data.get("signals", []), str(data.get("signals")))
    check("has MAX_SPEED const",
          "MAX_SPEED" in data.get("const_names", []), str(data.get("const_names")))


def test_script_checks(sandbox):
    print("\n=== Group 10: .gd check-* ===")
    gd = f"{BASE}/scripts/player.gd"

    check("class_name true",
          run(sandbox, f"check-script-class-name {gd} Player").get("match") is True)
    check("class_name false",
          run(sandbox, f"check-script-class-name {gd} Other").get("match") is False)

    check("extends true",
          run(sandbox, f"check-script-extends {gd} CharacterBody2D").get("match") is True)
    check("extends false",
          run(sandbox, f"check-script-extends {gd} Node3D").get("match") is False)

    check("func take_damage true",
          run(sandbox, f"check-script-func {gd} take_damage").get("exists") is True)
    check("func nothere false",
          run(sandbox, f"check-script-func {gd} nothere").get("exists") is False)

    check("export speed true",
          run(sandbox, f"check-script-export {gd} speed").get("exists") is True)
    check("export missing false",
          run(sandbox, f"check-script-export {gd} nothere").get("exists") is False)

    check("signal health_changed true",
          run(sandbox, f"check-script-signal {gd} health_changed").get("exists") is True)
    check("signal missing false",
          run(sandbox, f"check-script-signal {gd} none").get("exists") is False)


def test_resource_parsing(sandbox):
    print("\n=== Group 11: .tres parsing ===")
    tres = f"{BASE}/materials/mat.tres"

    data = run(sandbox, f"resource-info {tres}")
    check("resource type", data.get("type") == "StandardMaterial3D", str(data)[:200])
    check("resource has metallic",
          "metallic" in data.get("properties", {}), str(data)[:200])

    check("check type true",
          run(sandbox, f"check-resource-type {tres} StandardMaterial3D").get("match") is True)
    check("check type false",
          run(sandbox, f"check-resource-type {tres} Texture2D").get("match") is False)

    check("check property metallic 0.3 true",
          run(sandbox, f"check-resource-property {tres} metallic 0.3").get("match") is True)
    check("check property metallic 0.9 false",
          run(sandbox, f"check-resource-property {tres} metallic 0.9").get("match") is False)


def test_editor_settings(sandbox):
    print("\n=== Group 12: editor settings ===")
    data = run(sandbox, "editor-settings")
    keys = data.get("keys", {}) if isinstance(data, dict) else {}
    check("editor-settings has keys",
          "interface/editor/single_window_mode" in keys, str(keys)[:200])

    data = run(sandbox, "check-editor-setting interface/editor/single_window_mode true")
    check("editor-setting match true", data.get("match") is True, str(data)[:200])


def test_file_helpers(sandbox):
    print("\n=== Group 13: file helpers ===")
    scene = f"{BASE}/main.tscn"

    check("file-exists true",
          run(sandbox, f"file-exists {scene}").get("exists") is True)
    check("file-exists false",
          run(sandbox, "file-exists /no/such/file.tscn").get("exists") is False)

    check("check-file-contains true",
          run(sandbox, f'check-file-contains {scene} CharacterBody2D').get("contains") is True)
    check("check-file-contains false",
          run(sandbox, f'check-file-contains {scene} ZZZ_MISSING').get("contains") is False)

    data = run(sandbox, f"list-files {BASE} gd")
    check("list-files gd >=2", data.get("count", 0) >= 2, str(data)[:200])
    data = run(sandbox, f"list-files {BASE} tscn")
    check("list-files tscn >=1", data.get("count", 0) >= 1, str(data)[:200])


def test_json_sweep(sandbox):
    print("\n=== Group 14: JSON validity sweep ===")
    proj = f"{BASE}/project.godot"
    scene = f"{BASE}/main.tscn"
    gd = f"{BASE}/scripts/player.gd"
    tres = f"{BASE}/materials/mat.tres"

    cmds = [
        f"project-sections {proj}",
        f"project-section {proj} application",
        f"project-setting {proj} application/config/name",
        f"input-actions {proj}",
        f"autoloads {proj}",
        f"check-project-setting {proj} application/config/name \'\"Test Game\"\'",
        f"check-input-action {proj} move_left",
        f"check-input-action-key {proj} move_left A",
        f"check-autoload {proj} GameManager",
        f"scene-nodes {scene}",
        f"scene-node {scene} Player",
        f"scene-ext-resources {scene}",
        f"scene-sub-resources {scene}",
        f"check-node-exists {scene} Player",
        f"check-node-type {scene} Player CharacterBody2D",
        f"check-node-parent {scene} Sprite2D Player",
        f"check-node-count {scene} 4",
        f"check-scene-has-script {scene} player.gd",
        f"script-info {gd}",
        f"check-script-class-name {gd} Player",
        f"check-script-extends {gd} CharacterBody2D",
        f"check-script-func {gd} take_damage",
        f"check-script-export {gd} speed",
        f"check-script-signal {gd} health_changed",
        f"resource-info {tres}",
        f"check-resource-type {tres} StandardMaterial3D",
        f"check-resource-property {tres} metallic 0.3",
        "editor-settings",
        "check-editor-setting interface/editor/single_window_mode true",
        f"file-exists {scene}",
        f"list-files {BASE} gd",
    ]
    for cmd in cmds:
        r = run_raw(sandbox, cmd)
        check(f"JSON: {cmd[:50]}", is_valid_json(r.stdout),
              f"exit={r.exit_code} stdout={r.stdout[:80]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed
    print("=" * 60)
    print("Godot 4 Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=900)

    try:
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        setup_fixtures(sandbox)

        test_help(sandbox)
        test_unknown(sandbox)
        test_missing_args(sandbox)
        test_project_parsing(sandbox)
        test_project_checks(sandbox)
        test_project_parses(sandbox)
        test_scene_parsing(sandbox)
        test_scene_checks(sandbox)
        test_script_parsing(sandbox)
        test_script_checks(sandbox)
        test_resource_parsing(sandbox)
        test_editor_settings(sandbox)
        test_file_helpers(sandbox)
        test_json_sweep(sandbox)

    except Exception:
        traceback.print_exc()
        failed += 1
        errors.append(f"Unhandled exception: {traceback.format_exc()}")

    finally:
        sandbox.kill()
        print("\nSandbox killed.")

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    if errors:
        print("\nFailures:")
        for e in errors[:50]:
            print(f"  - {e}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
