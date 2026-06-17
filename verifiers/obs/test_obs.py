"""
Test OBS Studio verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (missing files, bad args, unknown commands)
  - File-based endpoints with fixture scene collections
  - Check-* endpoints (positive and negative cases)
  - JSON validity for all commands
  - Live WebSocket endpoints (expected to error without OBS running)

Usage:
    python verifiers/obs/test_obs.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "obs.py"
VERIFIER_REMOTE = "/home/user/verifiers/obs.py"
V = f"python3 {VERIFIER_REMOTE}"

# ---------------------------------------------------------------------------
# Fixture data — a realistic OBS scene collection JSON
# ---------------------------------------------------------------------------

FIXTURE_COLLECTION = json.dumps({
    "name": "TestCollection",
    "current_scene": "Main Scene",
    "current_program_scene": "Main Scene",
    "preview_scene": "Webcam Only",
    "current_transition": "Fade",
    "transition_duration": 300,
    "preview_locked": False,
    "scaling_enabled": False,
    "virtual-cam": {"type": 3, "internal": {"name": "Main Scene"}},
    "replay_buffer": {"buffer_seconds": 20},
    "modules": {"auto-scene-switcher": {"active": False}},
    "quick_transitions": [
        {"name": "Cut", "duration": 300, "hotkeys": []},
    ],
    "transitions": [
        {"name": "Fade", "id": "fade_transition", "settings": {}},
        {"name": "Stinger", "id": "obs_stinger_transition",
         "settings": {"path": "/home/user/stinger.webm", "transition_point": 500}},
        {"name": "Cut", "id": "cut_transition", "settings": {}},
    ],
    "hotkeys": {
        "OBSBasic.StartRecording": [{"key": "OBS_KEY_F9"}],
        "OBSBasic.StopRecording": [{"key": "OBS_KEY_F10"}],
    },
    "scene_order": [
        {"name": "Main Scene"},
        {"name": "Webcam Only"},
        {"name": "BRB"},
    ],
    "sources": [
        {
            "name": "Main Scene",
            "versioned_id": "scene",
            "enabled": True,
            "settings": {
                "items": [
                    {"name": "Desktop Capture", "visible": True, "locked": False,
                     "pos": {"x": 0, "y": 0}},
                    {"name": "Webcam", "visible": True, "locked": False,
                     "pos": {"x": 1280, "y": 720}},
                    {"name": "Mic Audio", "visible": True, "locked": True,
                     "pos": {"x": 0, "y": 0}},
                    {"name": "Hidden Overlay", "visible": False, "locked": False,
                     "pos": {"x": 100, "y": 100}},
                ]
            },
            "hotkeys": {
                "OBSBasic.SelectScene": [{"key": "OBS_KEY_1"}],
            },
        },
        {
            "name": "Webcam Only",
            "versioned_id": "scene",
            "enabled": True,
            "settings": {
                "items": [
                    {"name": "Webcam", "visible": True, "locked": False,
                     "pos": {"x": 0, "y": 0}},
                ]
            }
        },
        {
            "name": "BRB",
            "versioned_id": "scene",
            "enabled": True,
            "settings": {
                "items": [
                    {"name": "BRB Image", "visible": True, "locked": True,
                     "pos": {"x": 0, "y": 0}},
                ]
            }
        },
        {
            "name": "Desktop Capture",
            "versioned_id": "xshm_input",
            "enabled": True,
            "mute": False,
            "settings": {"screen": 0},
            "filters": [
                {"versioned_id": "color_filter_v2", "id": "color_filter",
                 "name": "Color Correction",
                 "settings": {"brightness": 0.1, "contrast": 0.05, "saturation": 1.2},
                 "enabled": True},
                {"versioned_id": "crop_filter", "id": "crop_filter",
                 "name": "Crop/Pad",
                 "settings": {"left": 10, "top": 10, "right": 10, "bottom": 10},
                 "enabled": True},
            ],
        },
        {
            "name": "Webcam",
            "versioned_id": "v4l2_input",
            "enabled": True,
            "mute": False,
            "settings": {"device_id": "/dev/video0", "resolution": "1920x1080"},
            "volume": 1.0,
            "filters": [],
            "monitoring_type": 1,
            "sync": 250,
            "balance": 0.5,
            "flags": 0,
        },
        {
            "name": "Mic Audio",
            "versioned_id": "pulse_input_capture",
            "enabled": True,
            "mute": True,
            "settings": {"device_id": "default"},
            "volume": 0.8,
            "monitoring_type": 2,
            "sync": -100,
            "balance": 0.75,
            "flags": 4,
            "hotkeys": {
                "libobs.mute": [{"key": "OBS_KEY_M"}],
                "libobs.unmute": [{"key": "OBS_KEY_U"}],
                "libobs.push-to-mute": [],
                "libobs.push-to-talk": [{"key": "OBS_KEY_SPACE"}],
            },
            "filters": [
                {"versioned_id": "noise_suppress_filter_v2",
                 "id": "noise_suppress_filter",
                 "name": "Noise Suppression",
                 "settings": {"method": "rnnoise"},
                 "enabled": True},
            ],
        },
        {
            "name": "Hidden Overlay",
            "versioned_id": "image_source",
            "enabled": True,
            "settings": {"file": "/home/user/overlay.png"},
        },
        {
            "name": "BRB Image",
            "versioned_id": "image_source",
            "enabled": True,
            "settings": {"file": "/home/user/brb.png"},
        },
    ],
}, indent=2)

FIXTURE_PROFILE_INI = """\
[SimpleOutput]
FilePath=/home/user/Videos
RecFormat=mkv
RecEncoder=x264
RecQuality=Stream

[Video]
BaseCX=1920
BaseCY=1080
OutputCX=1920
OutputCY=1080
FPSCommon=30
"""

FIXTURE_EMPTY_COLLECTION = json.dumps({
    "scene_order": [],
    "sources": [],
})

FIXTURE_SERVICE_JSON = json.dumps({
    "type": "rtmp_common",
    "settings": {
        "service": "Twitch",
        "server": "auto",
        "key": "live_123456_abcdefghijklmn",
        "bwtest": False,
    },
}, indent=2)

FIXTURE_GLOBAL_INI = """\
[General]
FirstRun=true
LastVersion=503316483
ProfileDir=Default
SceneCollection=TestCollection

[BasicWindow]
PreviewEnabled=true
StudioModeEnabled=false
geometry=AdnQywADAAAAAAAA

[Audio]
MonitoringDeviceName=Default
MonitoringDeviceId=default
"""

# Paths in sandbox
CONFIG_DIR = "/home/user/.config/obs-studio"
SCENES_DIR = f"{CONFIG_DIR}/basic/scenes"
PROFILES_DIR = f"{CONFIG_DIR}/basic/profiles"
COLLECTION_FILE = f"{SCENES_DIR}/TestCollection.json"
EMPTY_COLLECTION = f"{SCENES_DIR}/Empty.json"
PROFILE_INI = f"{PROFILES_DIR}/Default/basic.ini"
SERVICE_JSON = f"{PROFILES_DIR}/Default/service.json"
GLOBAL_INI = f"{CONFIG_DIR}/global.ini"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

passed = 0
failed = 0
errors: list[str] = []


class CmdResult:
    """Minimal wrapper to normalize both success and CommandExitException results."""
    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def run(sandbox: Sandbox, cmd: str, timeout: int = 30) -> dict | list:
    """Run a verifier CLI command, parse JSON output."""
    r = run_raw(sandbox, cmd, timeout)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


def run_raw(sandbox: Sandbox, cmd: str, timeout: int = 30) -> CmdResult:
    """Run a command and return a CmdResult (never throws on non-zero exit)."""
    try:
        result = sandbox.commands.run(f"{V} {cmd}", timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def check(name: str, condition: bool, detail: str = ""):
    """Record a test result."""
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f"  — {detail}"
        print(msg)
        errors.append(f"{name}: {detail}")


def is_valid_json(stdout: str) -> bool:
    try:
        json.loads(stdout)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    """--help should print usage and exit 0."""
    print("\n=== Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
    check("help mentions commands", "Commands:" in result.stdout, result.stdout[:200])
    check("help mentions OBS", "OBS" in result.stdout, result.stdout[:200])


def test_errors_no_config(sandbox: Sandbox):
    """File-based endpoints should return error JSON when no OBS config exists."""
    print("\n=== Errors (no OBS config) ===")

    # Temporarily test before fixture setup — scenes dir doesn't exist yet
    # Actually we set up fixtures first, so test with a nonexistent collection
    data = run(sandbox, "scenes /nonexistent/path/collection.json")
    if isinstance(data, list):
        data = data[0]
    check("scenes with bad path returns error", "error" in data, str(data)[:100])

    data = run(sandbox, "source-info SomeSource /nonexistent/path.json")
    check("source-info with bad path returns error", "error" in data, str(data)[:100])


def test_errors_bad_args(sandbox: Sandbox):
    """Missing/invalid arguments should return error JSON, not crash."""
    print("\n=== Errors (bad args) ===")

    # Missing required arg for scene-sources
    result = run_raw(sandbox, "scene-sources")
    check("missing arg exits 1", result.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Missing required arg for check-source-in-scene
    result = run_raw(sandbox, "check-source-in-scene OnlyOneArg")
    check("check-source-in-scene missing arg exits 1", result.exit_code == 1)
    check("check-source-in-scene missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Unknown command
    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # check-scene-count with non-integer
    result = run_raw(sandbox, "check-scene-count notanumber")
    check("non-integer count exits 1", result.exit_code == 1)
    check("non-integer count valid JSON", is_valid_json(result.stdout), result.stdout[:100])


def test_scenes(sandbox: Sandbox):
    """Test scene listing from fixture collection."""
    print("\n=== Scenes ===")

    data = run(sandbox, f"scenes {COLLECTION_FILE}")
    check("scenes returns list", isinstance(data, list), str(type(data)))
    check("scenes has 3 entries", len(data) == 3, f"got {len(data)}")

    names = [s.get("name") for s in data]
    check("scenes has Main Scene", "Main Scene" in names, str(names))
    check("scenes has Webcam Only", "Webcam Only" in names, str(names))
    check("scenes has BRB", "BRB" in names, str(names))

    # Check source counts
    main = next(s for s in data if s["name"] == "Main Scene")
    check("Main Scene has 4 sources", main.get("source_count") == 4, f"got {main.get('source_count')}")


def test_scene_sources(sandbox: Sandbox):
    """Test scene-sources listing."""
    print("\n=== Scene Sources ===")

    data = run(sandbox, f"scene-sources 'Main Scene' {COLLECTION_FILE}")
    check("scene-sources returns list", isinstance(data, list), str(type(data)))
    check("scene-sources has 4 items", len(data) == 4, f"got {len(data)}")

    names = [s.get("name") for s in data]
    check("has Desktop Capture", "Desktop Capture" in names, str(names))
    check("has Webcam", "Webcam" in names, str(names))
    check("has Mic Audio", "Mic Audio" in names, str(names))
    check("has Hidden Overlay", "Hidden Overlay" in names, str(names))

    # Check visibility
    hidden = next(s for s in data if s["name"] == "Hidden Overlay")
    check("Hidden Overlay visible=false", hidden.get("visible") is False, str(hidden))

    # Nonexistent scene
    data = run(sandbox, f"scene-sources 'No Such Scene' {COLLECTION_FILE}")
    if isinstance(data, list):
        data = data[0]
    check("nonexistent scene returns error", "error" in data, str(data)[:100])


def test_sources(sandbox: Sandbox):
    """Test listing all sources."""
    print("\n=== Sources ===")

    data = run(sandbox, f"sources {COLLECTION_FILE}")
    check("sources returns list", isinstance(data, list), str(type(data)))
    check("sources has entries", len(data) > 0, f"got {len(data)}")

    names = [s.get("name") for s in data]
    check("sources has Webcam", "Webcam" in names, str(names))
    check("sources has Desktop Capture", "Desktop Capture" in names, str(names))
    check("sources has Mic Audio", "Mic Audio" in names, str(names))


def test_source_info(sandbox: Sandbox):
    """Test detailed source info."""
    print("\n=== Source Info ===")

    data = run(sandbox, f"source-info Webcam {COLLECTION_FILE}")
    check("source-info returns dict", isinstance(data, dict), str(type(data)))
    check("source-info has name", data.get("name") == "Webcam", str(data.get("name")))
    check("source-info has type", "v4l2" in data.get("type", ""), str(data.get("type")))
    check("source-info has settings", isinstance(data.get("settings"), dict), str(type(data.get("settings"))))
    check("source-info device_id", data.get("settings", {}).get("device_id") == "/dev/video0",
          str(data.get("settings")))

    # Mic Audio should be muted
    data = run(sandbox, f"source-info 'Mic Audio' {COLLECTION_FILE}")
    check("Mic Audio muted=true", data.get("muted") is True, str(data.get("muted")))
    # New audio fields added to get_source_info
    check("Mic Audio monitoring_type=2", data.get("monitoring_type") == 2, str(data.get("monitoring_type")))
    check("Mic Audio sync=-100", data.get("sync") == -100, str(data.get("sync")))
    check("Mic Audio balance=0.75", data.get("balance") == 0.75, str(data.get("balance")))
    check("Mic Audio flags=4", data.get("flags") == 4, str(data.get("flags")))

    # Webcam defaults
    data = run(sandbox, f"source-info Webcam {COLLECTION_FILE}")
    check("Webcam monitoring_type=1", data.get("monitoring_type") == 1, str(data.get("monitoring_type")))
    check("Webcam sync=250", data.get("sync") == 250, str(data.get("sync")))
    check("Webcam balance=0.5", data.get("balance") == 0.5, str(data.get("balance")))

    # Source lacking audio fields should default to 0 / 0.5 / 0
    data = run(sandbox, f"source-info 'Hidden Overlay' {COLLECTION_FILE}")
    check("image source default monitoring_type=0", data.get("monitoring_type") == 0, str(data.get("monitoring_type")))
    check("image source default sync=0", data.get("sync") == 0, str(data.get("sync")))
    check("image source default balance=0.5", data.get("balance") == 0.5, str(data.get("balance")))
    check("image source default flags=0", data.get("flags") == 0, str(data.get("flags")))

    # Nonexistent source
    data = run(sandbox, f"source-info 'NoSuchSource' {COLLECTION_FILE}")
    check("nonexistent source returns error", "error" in data, str(data)[:100])


def test_profiles(sandbox: Sandbox):
    """Test profile listing."""
    print("\n=== Profiles ===")

    data = run(sandbox, "profiles")
    check("profiles returns list", isinstance(data, list), str(type(data)))
    check("profiles has entries", len(data) > 0, f"got {len(data)}")

    names = [p.get("name") for p in data]
    check("profiles has Default", "Default" in names, str(names))


def test_scene_collections(sandbox: Sandbox):
    """Test scene collection listing."""
    print("\n=== Scene Collections ===")

    data = run(sandbox, "scene-collections")
    check("scene-collections returns list", isinstance(data, list), str(type(data)))
    check("scene-collections has entries", len(data) >= 2, f"got {len(data)}")

    names = [c.get("name") for c in data]
    check("has TestCollection", "TestCollection" in names, str(names))
    check("has Empty", "Empty" in names, str(names))


def test_recording_settings(sandbox: Sandbox):
    """Test reading recording settings from profile."""
    print("\n=== Recording Settings ===")

    data = run(sandbox, "recording-settings Default")
    check("recording-settings returns dict", isinstance(data, dict), str(type(data)))
    check("has filepath", "filepath" in data or "filePath" in str(data).lower(),
          str(list(data.keys())[:10]))
    check("has recformat", "recformat" in data or "RecFormat" in str(data),
          str(list(data.keys())[:10]))


def test_checks_positive(sandbox: Sandbox):
    """Check-* endpoints — positive cases."""
    print("\n=== Checks (positive) ===")

    # check-scene-exists
    data = run(sandbox, f"check-scene-exists 'Main Scene' {COLLECTION_FILE}")
    check("check-scene-exists returns dict", isinstance(data, dict))
    check("check-scene-exists exists=true", data.get("exists") is True, str(data)[:100])
    check("check-scene-exists has source_count", "source_count" in data, str(data)[:100])

    # check-source-exists
    data = run(sandbox, f"check-source-exists Webcam {COLLECTION_FILE}")
    check("check-source-exists exists=true", data.get("exists") is True, str(data)[:100])
    check("check-source-exists has type", "type" in data, str(data)[:100])

    # check-source-in-scene
    data = run(sandbox, f"check-source-in-scene Webcam 'Main Scene' {COLLECTION_FILE}")
    check("check-source-in-scene exists=true", data.get("exists") is True, str(data)[:100])
    check("check-source-in-scene visible=true", data.get("visible") is True, str(data)[:100])

    # check-scene-count
    data = run(sandbox, f"check-scene-count 3 {COLLECTION_FILE}")
    check("check-scene-count match=true", data.get("match") is True, str(data)[:100])

    # check-source-visible (Webcam is visible in Main Scene)
    data = run(sandbox, f"check-source-visible Webcam {COLLECTION_FILE}")
    check("check-source-visible visible=true", data.get("visible") is True, str(data)[:100])

    # check-file-exists (the collection file itself)
    data = run(sandbox, f"check-file-exists {COLLECTION_FILE}")
    check("check-file-exists exists=true", data.get("exists") is True, str(data)[:100])
    check("check-file-exists has size", "size" in data, str(data)[:100])


def test_checks_negative(sandbox: Sandbox):
    """Check-* endpoints — negative cases."""
    print("\n=== Checks (negative) ===")

    # check-scene-exists — nonexistent scene
    data = run(sandbox, f"check-scene-exists 'No Such Scene' {COLLECTION_FILE}")
    check("check-scene-exists exists=false", data.get("exists") is False, str(data)[:100])
    check("check-scene-exists has available_scenes", "available_scenes" in data, str(data)[:100])

    # check-source-exists — nonexistent source
    data = run(sandbox, f"check-source-exists 'NoSuchSource' {COLLECTION_FILE}")
    check("check-source-exists exists=false", data.get("exists") is False, str(data)[:100])

    # check-source-in-scene — source not in scene
    data = run(sandbox, f"check-source-in-scene 'BRB Image' 'Main Scene' {COLLECTION_FILE}")
    check("check-source-in-scene exists=false", data.get("exists") is False, str(data)[:100])

    # check-scene-count — wrong count
    data = run(sandbox, f"check-scene-count 99 {COLLECTION_FILE}")
    check("check-scene-count match=false", data.get("match") is False, str(data)[:100])
    check("check-scene-count actual=3", data.get("actual") == 3, str(data)[:100])

    # check-source-visible — hidden source
    data = run(sandbox, f"check-source-visible 'Hidden Overlay' {COLLECTION_FILE}")
    check("check-source-visible visible=false", data.get("visible") is False, str(data)[:100])

    # check-file-exists — nonexistent file
    data = run(sandbox, "check-file-exists /nonexistent/file.txt")
    check("check-file-exists exists=false", data.get("exists") is False, str(data)[:100])

    # Empty collection
    data = run(sandbox, f"check-scene-count 0 {EMPTY_COLLECTION}")
    check("empty collection count=0", data.get("match") is True, str(data)[:100])


def test_source_filters(sandbox: Sandbox):
    """source-filters endpoint: list filters on a source (positive + negative)."""
    print("\n=== Source Filters ===")

    # Positive: Desktop Capture has 2 filters
    data = run(sandbox, f"source-filters 'Desktop Capture' {COLLECTION_FILE}")
    check("source-filters returns list", isinstance(data, list), str(type(data)))
    check("Desktop Capture has 2 filters", len(data) == 2, f"got {len(data)}")
    names = [f.get("name") for f in data] if isinstance(data, list) else []
    check("filter Color Correction present", "Color Correction" in names, str(names))
    check("filter Crop/Pad present", "Crop/Pad" in names, str(names))
    # Filter dicts include type/settings/enabled
    cc = next((f for f in data if f.get("name") == "Color Correction"), {})
    check("filter type populated", bool(cc.get("type")), str(cc.get("type")))
    check("filter settings is dict", isinstance(cc.get("settings"), dict), str(type(cc.get("settings"))))
    check("filter enabled=true", cc.get("enabled") is True, str(cc.get("enabled")))

    # Positive (empty): Webcam has [] filters
    data = run(sandbox, f"source-filters Webcam {COLLECTION_FILE}")
    check("Webcam has empty filters", isinstance(data, list) and len(data) == 0, str(data)[:100])

    # Negative: nonexistent source
    data = run(sandbox, f"source-filters 'NoSuchSource' {COLLECTION_FILE}")
    first = data[0] if isinstance(data, list) and data else data
    check("source-filters missing source returns error", "error" in first, str(first)[:100])


def test_source_filter_info(sandbox: Sandbox):
    """source-filter-info endpoint: single filter details (positive + negative)."""
    print("\n=== Source Filter Info ===")

    # Positive
    data = run(sandbox, f"source-filter-info 'Desktop Capture' 'Color Correction' {COLLECTION_FILE}")
    check("source-filter-info returns dict", isinstance(data, dict), str(type(data)))
    check("filter name matches", data.get("name") == "Color Correction", str(data)[:100])
    check("filter settings has brightness",
          isinstance(data.get("settings"), dict) and "brightness" in data.get("settings", {}),
          str(data.get("settings"))[:100])

    # Negative: filter missing
    data = run(sandbox, f"source-filter-info 'Desktop Capture' 'NoSuchFilter' {COLLECTION_FILE}")
    check("missing filter returns error", "error" in data, str(data)[:100])
    check("missing filter lists available", "available_filters" in data, str(data)[:100])

    # Negative: source missing
    data = run(sandbox, f"source-filter-info 'NoSuchSource' 'Color Correction' {COLLECTION_FILE}")
    check("missing source returns error", "error" in data, str(data)[:100])


def test_check_source_has_filter(sandbox: Sandbox):
    """check-source-has-filter positive (by name and by type) + negative."""
    print("\n=== check-source-has-filter ===")

    # Positive: by exact filter name
    data = run(sandbox, f"check-source-has-filter 'Desktop Capture' 'Color Correction' {COLLECTION_FILE}")
    check("exists=true by name", data.get("exists") is True, str(data)[:120])
    check("filter_type reported", "filter_type" in data, str(data)[:120])

    # Positive: by type substring
    data = run(sandbox, f"check-source-has-filter 'Mic Audio' 'noise_suppress' {COLLECTION_FILE}")
    check("exists=true by type substring", data.get("exists") is True, str(data)[:120])

    # Negative: filter missing on existing source
    data = run(sandbox, f"check-source-has-filter Webcam 'Color Correction' {COLLECTION_FILE}")
    check("exists=false on source with no filters", data.get("exists") is False, str(data)[:120])
    check("available_filters listed", "available_filters" in data, str(data)[:120])

    # Negative: source missing
    data = run(sandbox, f"check-source-has-filter 'NoSuchSource' 'Color Correction' {COLLECTION_FILE}")
    check("missing source -> exists=false", data.get("exists") is False, str(data)[:120])
    check("missing source -> error field", "error" in data, str(data)[:120])


def test_transitions(sandbox: Sandbox):
    """transitions endpoint: list transitions (positive + empty)."""
    print("\n=== Transitions ===")

    data = run(sandbox, f"transitions {COLLECTION_FILE}")
    check("transitions returns list", isinstance(data, list), str(type(data)))
    check("3 transitions present", len(data) == 3, f"got {len(data)}")
    names = [t.get("name") for t in data] if isinstance(data, list) else []
    check("has Fade", "Fade" in names, str(names))
    check("has Stinger", "Stinger" in names, str(names))
    check("has Cut", "Cut" in names, str(names))
    stinger = next((t for t in data if t.get("name") == "Stinger"), {})
    check("Stinger settings has path",
          isinstance(stinger.get("settings"), dict) and "path" in stinger.get("settings", {}),
          str(stinger.get("settings")))

    # Empty collection -> empty list (not error)
    data = run(sandbox, f"transitions {EMPTY_COLLECTION}")
    check("empty collection transitions=[]", isinstance(data, list) and len(data) == 0, str(data)[:100])


def test_check_transition_exists(sandbox: Sandbox):
    """check-transition-exists positive + negative."""
    print("\n=== check-transition-exists ===")

    data = run(sandbox, f"check-transition-exists Fade {COLLECTION_FILE}")
    check("Fade exists=true", data.get("exists") is True, str(data)[:120])
    check("Fade type reported", bool(data.get("type")), str(data)[:120])

    data = run(sandbox, f"check-transition-exists Stinger {COLLECTION_FILE}")
    check("Stinger exists=true", data.get("exists") is True, str(data)[:120])

    # Negative
    data = run(sandbox, f"check-transition-exists 'NotATransition' {COLLECTION_FILE}")
    check("missing transition exists=false", data.get("exists") is False, str(data)[:120])
    check("available transitions listed", "available" in data, str(data)[:120])

    # Empty collection negative
    data = run(sandbox, f"check-transition-exists Fade {EMPTY_COLLECTION}")
    check("empty collection exists=false", data.get("exists") is False, str(data)[:120])


def test_collection_meta(sandbox: Sandbox):
    """collection-meta endpoint: top-level metadata (populated + default)."""
    print("\n=== collection-meta ===")

    data = run(sandbox, f"collection-meta {COLLECTION_FILE}")
    check("collection-meta dict", isinstance(data, dict), str(type(data)))
    check("name=TestCollection", data.get("name") == "TestCollection", str(data.get("name")))
    check("current_scene=Main Scene", data.get("current_scene") == "Main Scene", str(data.get("current_scene")))
    check("current_transition=Fade", data.get("current_transition") == "Fade", str(data.get("current_transition")))
    check("transition_duration=300", data.get("transition_duration") == 300, str(data.get("transition_duration")))
    check("preview_locked=false", data.get("preview_locked") is False, str(data.get("preview_locked")))
    check("virtual_cam populated", isinstance(data.get("virtual_cam"), dict) and data.get("virtual_cam"),
          str(data.get("virtual_cam"))[:100])
    check("replay_buffer populated",
          isinstance(data.get("replay_buffer"), dict) and data.get("replay_buffer", {}).get("buffer_seconds") == 20,
          str(data.get("replay_buffer"))[:100])
    check("quick_transitions list", isinstance(data.get("quick_transitions"), list), str(type(data.get("quick_transitions"))))

    # Negative/default: empty collection returns defaults (no error)
    data = run(sandbox, f"collection-meta {EMPTY_COLLECTION}")
    check("empty collection meta name=''", data.get("name") == "", str(data.get("name")))
    check("empty collection meta current_scene=''", data.get("current_scene") == "", str(data.get("current_scene")))
    check("empty collection meta replay_buffer={}", data.get("replay_buffer") == {}, str(data.get("replay_buffer")))


def test_hotkey(sandbox: Sandbox):
    """hotkey endpoint: global + per-source + missing."""
    print("\n=== hotkey ===")

    # Positive: global
    data = run(sandbox, f"hotkey OBSBasic.StartRecording {COLLECTION_FILE}")
    check("global hotkey found=true", data.get("found") is True, str(data)[:120])
    check("global hotkey scope=global", data.get("scope") == "global", str(data)[:120])
    check("global hotkey bindings list",
          isinstance(data.get("bindings"), list) and len(data.get("bindings", [])) >= 1,
          str(data.get("bindings"))[:100])

    # Positive: per-source
    data = run(sandbox, f"hotkey libobs.mute {COLLECTION_FILE}")
    check("source hotkey found=true", data.get("found") is True, str(data)[:120])
    check("source hotkey scope=source", data.get("scope") == "source", str(data)[:120])
    check("source hotkey source=Mic Audio", data.get("source") == "Mic Audio", str(data)[:120])

    # Negative: unknown action
    data = run(sandbox, f"hotkey NoSuchAction {COLLECTION_FILE}")
    check("missing hotkey found=false", data.get("found") is False, str(data)[:120])


def test_source_hotkeys(sandbox: Sandbox):
    """source-hotkeys endpoint: per-source hotkey map (positive + negative)."""
    print("\n=== source-hotkeys ===")

    # Positive: Mic Audio has 4 hotkey keys
    data = run(sandbox, f"source-hotkeys 'Mic Audio' {COLLECTION_FILE}")
    check("source-hotkeys returns dict", isinstance(data, dict), str(type(data)))
    check("source field=Mic Audio", data.get("source") == "Mic Audio", str(data)[:120])
    hk = data.get("hotkeys", {})
    check("hotkeys has libobs.mute", "libobs.mute" in hk, str(list(hk.keys()))[:120])
    check("hotkeys has push-to-talk", "libobs.push-to-talk" in hk, str(list(hk.keys()))[:120])
    check("4 hotkey entries", len(hk) == 4, f"got {len(hk)}")

    # Positive (empty): Webcam has no hotkeys
    data = run(sandbox, f"source-hotkeys Webcam {COLLECTION_FILE}")
    check("Webcam empty hotkeys", data.get("hotkeys") == {}, str(data)[:120])

    # Negative: missing source
    data = run(sandbox, f"source-hotkeys 'NoSuchSource' {COLLECTION_FILE}")
    check("missing source returns error", "error" in data, str(data)[:120])


def test_streaming_settings(sandbox: Sandbox):
    """streaming-settings endpoint (positive with service.json + negative profile)."""
    print("\n=== streaming-settings ===")

    # Positive: Default profile has service.json + basic.ini
    data = run(sandbox, "streaming-settings Default")
    check("streaming-settings returns dict", isinstance(data, dict), str(type(data)))
    check("profile=Default", data.get("profile") == "Default", str(data)[:120])
    check("service_type=rtmp_common", data.get("service_type") == "rtmp_common", str(data)[:120])
    check("service=Twitch", data.get("service") == "Twitch", str(data)[:120])
    check("server=auto", data.get("server") == "auto", str(data)[:120])
    check("stream_key_present=true", data.get("stream_key_present") is True, str(data)[:120])
    check("bwtest=false", data.get("bwtest") is False, str(data)[:120])
    check("ini_Video present", "ini_Video" in data, str(list(data.keys()))[:200])

    # Default (no args) selects first profile
    data = run(sandbox, "streaming-settings")
    check("default profile returns dict", isinstance(data, dict), str(type(data)))
    check("default profile has profile field", "profile" in data, str(data)[:120])

    # Negative: nonexistent profile -> service.json missing, ini missing
    data = run(sandbox, "streaming-settings NoSuchProfile")
    check("missing profile service_error", "service_error" in data, str(data)[:200])
    check("missing profile no service field",
          data.get("service", None) in (None, ""),
          str(data)[:200])


def test_global_config(sandbox: Sandbox):
    """global-config endpoint: full tree / single section / single key / missing."""
    print("\n=== global-config ===")

    # Positive: full tree
    data = run(sandbox, "global-config")
    check("global-config returns dict", isinstance(data, dict), str(type(data)))
    check("has path", "path" in data, str(list(data.keys()))[:120])
    check("has sections", "sections" in data, str(list(data.keys()))[:120])
    check("sections has General",
          isinstance(data.get("sections"), dict) and "General" in data.get("sections", {}),
          str(list(data.get("sections", {}).keys()))[:120])
    check("sections has BasicWindow",
          "BasicWindow" in data.get("sections", {}),
          str(list(data.get("sections", {}).keys()))[:120])

    # Positive: single section
    data = run(sandbox, "global-config General")
    check("section=General", data.get("section") == "General", str(data)[:120])
    check("values is dict", isinstance(data.get("values"), dict), str(type(data.get("values"))))
    check("values has profiledir",
          "profiledir" in data.get("values", {}),
          str(list(data.get("values", {}).keys()))[:120])

    # Positive: single key
    data = run(sandbox, "global-config General SceneCollection")
    check("key=SceneCollection", data.get("key") == "SceneCollection", str(data)[:120])
    check("value=TestCollection", data.get("value") == "TestCollection", str(data)[:120])

    # Negative: unknown section
    data = run(sandbox, "global-config NoSection")
    check("missing section values={}", data.get("values") == {}, str(data)[:120])

    # Negative: unknown key
    data = run(sandbox, "global-config General NoSuchKey")
    check("missing key value=null", data.get("value") is None, str(data)[:120])


def test_live_endpoints_without_obs(sandbox: Sandbox):
    """Live WebSocket endpoints should return error when OBS is not running."""
    print("\n=== Live Endpoints (OBS not running) ===")

    for cmd in ("live-scenes", "live-sources", "live-status", "live-scene-current"):
        data = run(sandbox, cmd)
        check(f"{cmd} returns dict", isinstance(data, dict), str(type(data)))
        check(f"{cmd} has error", "error" in data or "recording_error" in data or "streaming_error" in data,
              str(data)[:100])

    # check-recording-active and check-streaming-active
    data = run(sandbox, "check-recording-active")
    check("check-recording-active recording=false", data.get("recording") is False, str(data)[:100])

    data = run(sandbox, "check-streaming-active")
    check("check-streaming-active streaming=false", data.get("streaming") is False, str(data)[:100])


def test_all_commands_return_json(sandbox: Sandbox):
    """Every CLI command should output valid JSON (not crash with a traceback)."""
    print("\n=== JSON validity (all commands) ===")

    # Commands with no required args
    no_arg_cmds = [
        "scenes", "sources", "profiles", "scene-collections",
        "recording-settings",
        "streaming-settings", "global-config",
        "live-scenes", "live-sources", "live-status", "live-scene-current",
        "check-recording-active", "check-streaming-active",
    ]

    for cmd in no_arg_cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        check(f"{cmd} returns valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # Commands that need args
    arg_cmds = [
        ("scene-sources", f"'Main Scene' {COLLECTION_FILE}"),
        ("source-info", f"Webcam {COLLECTION_FILE}"),
        ("check-file-exists", "/tmp"),
        ("check-scene-exists", f"'Main Scene' {COLLECTION_FILE}"),
        ("check-source-exists", f"Webcam {COLLECTION_FILE}"),
        ("check-source-in-scene", f"Webcam 'Main Scene' {COLLECTION_FILE}"),
        ("check-scene-count", f"3 {COLLECTION_FILE}"),
        ("check-source-visible", f"Webcam {COLLECTION_FILE}"),
        ("source-filters", f"'Desktop Capture' {COLLECTION_FILE}"),
        ("source-filter-info", f"'Desktop Capture' 'Color Correction' {COLLECTION_FILE}"),
        ("check-source-has-filter", f"'Desktop Capture' 'Color Correction' {COLLECTION_FILE}"),
        ("transitions", f"{COLLECTION_FILE}"),
        ("check-transition-exists", f"Fade {COLLECTION_FILE}"),
        ("collection-meta", f"{COLLECTION_FILE}"),
        ("hotkey", f"OBSBasic.StartRecording {COLLECTION_FILE}"),
        ("source-hotkeys", f"'Mic Audio' {COLLECTION_FILE}"),
    ]

    for cmd, arg in arg_cmds:
        result = run_raw(sandbox, f"{cmd} {arg}")
        valid = is_valid_json(result.stdout)
        check(f"{cmd} returns valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed

    print("=" * 60)
    print("OBS Studio Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # Create fixture directories and files
        print("Creating OBS config fixtures...")
        sandbox.commands.run(f"mkdir -p {SCENES_DIR}")
        sandbox.commands.run(f"mkdir -p {PROFILES_DIR}/Default")

        sandbox.files.write(COLLECTION_FILE, FIXTURE_COLLECTION)
        sandbox.files.write(EMPTY_COLLECTION, FIXTURE_EMPTY_COLLECTION)
        sandbox.files.write(PROFILE_INI, FIXTURE_PROFILE_INI)
        sandbox.files.write(SERVICE_JSON, FIXTURE_SERVICE_JSON)
        sandbox.files.write(GLOBAL_INI, FIXTURE_GLOBAL_INI)

        # Verify fixtures were created
        r = sandbox.commands.run(f"ls -la {SCENES_DIR}/", timeout=5)
        print(f"  Scenes dir: {r.stdout.strip()}")
        r = sandbox.commands.run(f"ls -la {PROFILES_DIR}/Default/", timeout=5)
        print(f"  Profile dir: {r.stdout.strip()}")

        # Install obsws-python (for live endpoint error handling tests)
        print("Installing obsws-python...")
        try:
            r = sandbox.commands.run("pip install obsws-python 2>&1", timeout=60)
            print(f"  pip: {r.stdout.strip()[-80:]}")
        except CommandExitException as e:
            print(f"  pip install warning: {e.stderr[:100]}")

        # --- Run all tests ---
        test_help(sandbox)
        test_errors_no_config(sandbox)
        test_errors_bad_args(sandbox)
        test_scenes(sandbox)
        test_scene_sources(sandbox)
        test_sources(sandbox)
        test_source_info(sandbox)
        test_profiles(sandbox)
        test_scene_collections(sandbox)
        test_recording_settings(sandbox)
        test_checks_positive(sandbox)
        test_checks_negative(sandbox)
        test_source_filters(sandbox)
        test_source_filter_info(sandbox)
        test_check_source_has_filter(sandbox)
        test_transitions(sandbox)
        test_check_transition_exists(sandbox)
        test_collection_meta(sandbox)
        test_hotkey(sandbox)
        test_source_hotkeys(sandbox)
        test_streaming_settings(sandbox)
        test_global_config(sandbox)
        test_live_endpoints_without_obs(sandbox)
        test_all_commands_return_json(sandbox)

    except Exception:
        traceback.print_exc()
        failed += 1
        errors.append(f"Unhandled exception: {traceback.format_exc()}")

    finally:
        sandbox.kill()
        print("\nSandbox killed.")

    # --- Summary ---
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  - {e}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
