"""
Test Kdenlive verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (missing file, bad args, unknown command)
  - XML query endpoints (project-info, clips, tracks, effects, transitions, clip-info, profile)
  - Check endpoints (check-clip-count, check-track-count, check-resolution, check-fps, etc.)
  - Negative check cases (wrong counts, missing clips, wrong resolution)

Test .kdenlive XML files are created in-sandbox with known structure for deterministic assertions.

Usage:
    python verifiers/kdenlive/test_kdenlive.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "kdenlive.py"
VERIFIER_REMOTE = "/home/user/verifiers/kdenlive.py"
V = f"python3 {VERIFIER_REMOTE}"

# ---------------------------------------------------------------------------
# Test .kdenlive project XML fixtures
# ---------------------------------------------------------------------------

# A minimal but realistic .kdenlive project file with known structure
SAMPLE_PROJECT_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<mlt LC_NUMERIC="C" producer="main_bin" version="7.14.0" root="/home/user/Videos">
  <profile description="HD 1080p 25fps" width="1920" height="1080"
           progressive="1" sample_aspect_num="1" sample_aspect_den="1"
           display_aspect_num="16" display_aspect_den="9"
           frame_rate_num="25" frame_rate_den="1" colorspace="709"/>

  <producer id="producer0" in="00:00:00.000" out="00:00:10.000">
    <property name="resource">/home/user/Videos/intro.mp4</property>
    <property name="kdenlive:clipname">Intro Clip</property>
    <property name="length">250</property>
    <property name="mlt_service">avformat</property>
    <property name="kdenlive:clip_type">2</property>
    <property name="kdenlive:id">1</property>
    <property name="video_index">0</property>
    <property name="audio_index">1</property>
  </producer>

  <producer id="producer1" in="00:00:00.000" out="00:00:05.000">
    <property name="resource">/home/user/Videos/main_footage.mp4</property>
    <property name="kdenlive:clipname">Main Footage</property>
    <property name="length">125</property>
    <property name="mlt_service">avformat</property>
    <property name="kdenlive:clip_type">2</property>
    <property name="kdenlive:id">2</property>
    <property name="video_index">0</property>
    <property name="audio_index">1</property>
  </producer>

  <producer id="producer2" in="00:00:00.000" out="00:00:03.000">
    <property name="resource">/home/user/Music/background.mp3</property>
    <property name="kdenlive:clipname">Background Music</property>
    <property name="length">75</property>
    <property name="mlt_service">avformat</property>
    <property name="kdenlive:clip_type">1</property>
    <property name="kdenlive:id">3</property>
    <property name="audio_index">0</property>
  </producer>

  <playlist id="playlist0">
    <property name="kdenlive:track_name">Video 1</property>
    <entry producer="producer0" in="00:00:00.000" out="00:00:10.000"/>
    <blank length="00:00:01.000"/>
    <entry producer="producer1" in="00:00:00.000" out="00:00:05.000"/>
  </playlist>

  <playlist id="playlist1">
    <property name="kdenlive:track_name">Video 2</property>
  </playlist>

  <playlist id="playlist2">
    <property name="kdenlive:track_name">Audio 1</property>
    <property name="kdenlive:audio_track">1</property>
    <entry producer="producer2" in="00:00:00.000" out="00:00:03.000"/>
  </playlist>

  <tractor id="tractor0" in="00:00:00.000" out="00:00:16.000">
    <track producer="playlist0"/>
    <track producer="playlist1"/>
    <track producer="playlist2"/>

    <transition id="transition0" in="00:00:09.000" out="00:00:11.000">
      <property name="mlt_service">luma</property>
      <property name="kdenlive_id">luma</property>
      <property name="a_track">0</property>
      <property name="b_track">1</property>
    </transition>

    <transition id="transition1" in="00:00:00.000" out="00:00:16.000">
      <property name="mlt_service">mix</property>
      <property name="kdenlive_id">mix</property>
      <property name="a_track">0</property>
      <property name="b_track">2</property>
      <property name="always_active">1</property>
    </transition>

    <filter id="filter0" in="00:00:00.000" out="00:00:10.000" track="0">
      <property name="mlt_service">frei0r.glow</property>
      <property name="kdenlive_id">glow</property>
      <property name="kdenlive:filter_name">Glow</property>
    </filter>

    <filter id="filter1" in="00:00:00.000" out="00:00:16.000" track="2">
      <property name="mlt_service">volume</property>
      <property name="kdenlive_id">volume</property>
      <property name="kdenlive:filter_name">Volume</property>
    </filter>
  </tractor>
</mlt>
"""

# A 720p 30fps project for testing different profile values
SAMPLE_720P_PROJECT_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<mlt LC_NUMERIC="C" producer="main_bin" version="7.14.0" root="/home/user/Videos">
  <profile description="HD 720p 30fps" width="1280" height="720"
           progressive="1" sample_aspect_num="1" sample_aspect_den="1"
           display_aspect_num="16" display_aspect_den="9"
           frame_rate_num="30" frame_rate_den="1" colorspace="709"/>

  <producer id="producer0" in="00:00:00.000" out="00:00:05.000">
    <property name="resource">/home/user/Videos/only_clip.mp4</property>
    <property name="kdenlive:clipname">Only Clip</property>
    <property name="length">150</property>
    <property name="mlt_service">avformat</property>
  </producer>

  <playlist id="playlist0">
    <property name="kdenlive:track_name">Video 1</property>
    <entry producer="producer0" in="00:00:00.000" out="00:00:05.000"/>
  </playlist>

  <tractor id="tractor0" in="00:00:00.000" out="00:00:05.000">
    <track producer="playlist0"/>
  </tractor>
</mlt>
"""

SAMPLE_PROJECT_PATH = "/home/user/test_project.kdenlive"
SAMPLE_720P_PATH = "/home/user/test_720p.kdenlive"

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
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    """--help should print usage and exit 0."""
    print("\n=== Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
    check("help mentions commands", "Commands:" in result.stdout, result.stdout[:100])
    check("help mentions kdenlive", "Kdenlive" in result.stdout or "kdenlive" in result.stdout,
          result.stdout[:100])


def test_errors(sandbox: Sandbox):
    """Error cases: missing file, bad args, unknown command."""
    print("\n=== Errors ===")

    # Unknown command
    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Missing required arg
    result = run_raw(sandbox, "clips")
    check("missing arg exits 1", result.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Non-existent file
    data = run(sandbox, "project-info /nonexistent/path.kdenlive")
    check("missing file returns error", "error" in data, str(data)[:100])

    # Wrong file extension
    sandbox.commands.run("echo '<mlt/>' > /tmp/test.txt")
    data = run(sandbox, "project-info /tmp/test.txt")
    check("wrong extension returns error", "error" in data, str(data)[:100])


def test_project_info(sandbox: Sandbox):
    """project-info should return profile and counts."""
    print("\n=== project-info ===")
    data = run(sandbox, f"project-info {SAMPLE_PROJECT_PATH}")
    check("project-info returns dict", isinstance(data, dict), str(type(data)))
    check("project-info has profile", "profile" in data, str(data.keys()))
    check("project-info producer count", data.get("producer_count") == 3,
          f"expected 3, got {data.get('producer_count')}")
    check("project-info track count", data.get("track_count") == 3,
          f"expected 3, got {data.get('track_count')}")
    check("project-info filter count", data.get("filter_count") == 2,
          f"expected 2, got {data.get('filter_count')}")
    check("project-info transition count", data.get("transition_count") == 2,
          f"expected 2, got {data.get('transition_count')}")


def test_clips(sandbox: Sandbox):
    """clips should list all producers."""
    print("\n=== clips ===")
    data = run(sandbox, f"clips {SAMPLE_PROJECT_PATH}")
    check("clips returns list", isinstance(data, list), str(type(data)))
    check("clips count is 3", len(data) == 3, f"got {len(data)}")

    # Check first clip details
    if len(data) >= 1:
        clip0 = data[0]
        check("clip0 id is producer0", clip0.get("id") == "producer0",
              f"got {clip0.get('id')}")
        check("clip0 has resource", "intro.mp4" in clip0.get("resource", ""),
              clip0.get("resource", ""))
        check("clip0 has clipname", clip0.get("kdenlive:clipname") == "Intro Clip",
              clip0.get("kdenlive:clipname", ""))


def test_tracks(sandbox: Sandbox):
    """tracks should list all playlists."""
    print("\n=== tracks ===")
    data = run(sandbox, f"tracks {SAMPLE_PROJECT_PATH}")
    check("tracks returns list", isinstance(data, list), str(type(data)))
    check("tracks count is 3", len(data) == 3, f"got {len(data)}")

    # Check playlist0 has entries
    if len(data) >= 1:
        pl0 = data[0]
        check("playlist0 has entries", len(pl0.get("entries", [])) == 2,
              f"got {len(pl0.get('entries', []))} entries")
        check("playlist0 has blanks", len(pl0.get("blanks", [])) == 1,
              f"got {len(pl0.get('blanks', []))} blanks")
        check("playlist0 track name", pl0.get("kdenlive:track_name") == "Video 1",
              pl0.get("kdenlive:track_name", ""))


def test_effects(sandbox: Sandbox):
    """effects should list all filters."""
    print("\n=== effects ===")
    data = run(sandbox, f"effects {SAMPLE_PROJECT_PATH}")
    check("effects returns list", isinstance(data, list), str(type(data)))
    check("effects count is 2", len(data) == 2, f"got {len(data)}")

    if len(data) >= 1:
        f0 = data[0]
        check("filter0 mlt_service", f0.get("mlt_service") == "frei0r.glow",
              f0.get("mlt_service", ""))
        check("filter0 kdenlive_id", f0.get("kdenlive_id") == "glow",
              f0.get("kdenlive_id", ""))


def test_transitions(sandbox: Sandbox):
    """transitions should list all transition elements."""
    print("\n=== transitions ===")
    data = run(sandbox, f"transitions {SAMPLE_PROJECT_PATH}")
    check("transitions returns list", isinstance(data, list), str(type(data)))
    check("transitions count is 2", len(data) == 2, f"got {len(data)}")

    if len(data) >= 1:
        t0 = data[0]
        check("transition0 mlt_service", t0.get("mlt_service") == "luma",
              t0.get("mlt_service", ""))
        check("transition0 a_track", t0.get("a_track") == "0",
              t0.get("a_track", ""))


def test_clip_info(sandbox: Sandbox):
    """clip-info should return detailed info for a specific producer."""
    print("\n=== clip-info ===")
    data = run(sandbox, f"clip-info {SAMPLE_PROJECT_PATH} producer1")
    check("clip-info returns dict", isinstance(data, dict), str(type(data)))
    check("clip-info id", data.get("id") == "producer1", data.get("id", ""))
    check("clip-info resource", "main_footage.mp4" in data.get("resource", ""),
          data.get("resource", ""))
    check("clip-info clipname", data.get("kdenlive:clipname") == "Main Footage",
          data.get("kdenlive:clipname", ""))

    # Non-existent producer
    data = run(sandbox, f"clip-info {SAMPLE_PROJECT_PATH} nonexistent_producer")
    check("clip-info missing returns error", "error" in data, str(data)[:100])


def test_profile(sandbox: Sandbox):
    """profile should return video profile attributes."""
    print("\n=== profile ===")
    data = run(sandbox, f"profile {SAMPLE_PROJECT_PATH}")
    check("profile returns dict", isinstance(data, dict), str(type(data)))
    check("profile width", data.get("width") == "1920", data.get("width", ""))
    check("profile height", data.get("height") == "1080", data.get("height", ""))
    check("profile fps num", data.get("frame_rate_num") == "25", data.get("frame_rate_num", ""))
    check("profile colorspace", data.get("colorspace") == "709", data.get("colorspace", ""))


def test_checks_positive(sandbox: Sandbox):
    """Check endpoints -- positive cases that should pass."""
    print("\n=== Checks (positive) ===")

    # check-file-exists
    data = run(sandbox, f"check-file-exists {SAMPLE_PROJECT_PATH}")
    check("check-file-exists true", data.get("exists") is True, str(data)[:100])
    check("check-file-exists has size", "size" in data, str(data.keys()))

    # check-clip-exists
    data = run(sandbox, f"check-clip-exists {SAMPLE_PROJECT_PATH} intro.mp4")
    check("check-clip-exists found", data.get("exists") is True, str(data)[:100])
    check("check-clip-exists match count", data.get("match_count", 0) >= 1,
          f"got {data.get('match_count')}")

    # check-clip-exists by name
    data = run(sandbox, f'check-clip-exists {SAMPLE_PROJECT_PATH} "Main Footage"')
    check("check-clip-exists by name", data.get("exists") is True, str(data)[:100])

    # check-clip-count
    data = run(sandbox, f"check-clip-count {SAMPLE_PROJECT_PATH} 3")
    check("check-clip-count match", data.get("match") is True,
          f"expected=3 actual={data.get('actual')}")

    # check-track-count
    data = run(sandbox, f"check-track-count {SAMPLE_PROJECT_PATH} 3")
    check("check-track-count match", data.get("match") is True,
          f"expected=3 actual={data.get('actual')}")

    # check-effect-exists
    data = run(sandbox, f"check-effect-exists {SAMPLE_PROJECT_PATH} frei0r.glow")
    check("check-effect-exists found", data.get("exists") is True, str(data)[:100])

    data = run(sandbox, f"check-effect-exists {SAMPLE_PROJECT_PATH} volume")
    check("check-effect-exists volume", data.get("exists") is True, str(data)[:100])

    # check-transition-exists
    data = run(sandbox, f"check-transition-exists {SAMPLE_PROJECT_PATH} luma")
    check("check-transition-exists found", data.get("exists") is True, str(data)[:100])

    data = run(sandbox, f"check-transition-exists {SAMPLE_PROJECT_PATH} mix")
    check("check-transition-exists mix", data.get("exists") is True, str(data)[:100])

    # check-resolution
    data = run(sandbox, f"check-resolution {SAMPLE_PROJECT_PATH} 1920 1080")
    check("check-resolution match", data.get("match") is True,
          f"expected=1920x1080 actual={data.get('actual')}")

    # check-fps
    data = run(sandbox, f"check-fps {SAMPLE_PROJECT_PATH} 25")
    check("check-fps match", data.get("match") is True,
          f"expected=25 actual={data.get('actual')}")


def test_checks_negative(sandbox: Sandbox):
    """Check endpoints -- negative cases that should not pass."""
    print("\n=== Checks (negative) ===")

    # check-file-exists on nonexistent file
    data = run(sandbox, "check-file-exists /nonexistent/file.mp4")
    check("check-file-exists false", data.get("exists") is False, str(data)[:100])

    # check-clip-exists for missing clip
    data = run(sandbox, f"check-clip-exists {SAMPLE_PROJECT_PATH} nonexistent_clip.avi")
    check("check-clip-exists not found", data.get("exists") is False, str(data)[:100])

    # check-clip-count wrong
    data = run(sandbox, f"check-clip-count {SAMPLE_PROJECT_PATH} 99")
    check("check-clip-count mismatch", data.get("match") is False,
          f"expected=99 actual={data.get('actual')}")

    # check-track-count wrong
    data = run(sandbox, f"check-track-count {SAMPLE_PROJECT_PATH} 10")
    check("check-track-count mismatch", data.get("match") is False,
          f"expected=10 actual={data.get('actual')}")

    # check-effect-exists for missing effect
    data = run(sandbox, f"check-effect-exists {SAMPLE_PROJECT_PATH} nonexistent_effect")
    check("check-effect-exists not found", data.get("exists") is False, str(data)[:100])

    # check-transition-exists for missing transition
    data = run(sandbox, f"check-transition-exists {SAMPLE_PROJECT_PATH} wipe_nonexistent")
    check("check-transition-exists not found", data.get("exists") is False, str(data)[:100])

    # check-resolution wrong
    data = run(sandbox, f"check-resolution {SAMPLE_PROJECT_PATH} 3840 2160")
    check("check-resolution mismatch", data.get("match") is False,
          f"expected=3840x2160 actual={data.get('actual')}")

    # check-fps wrong
    data = run(sandbox, f"check-fps {SAMPLE_PROJECT_PATH} 60")
    check("check-fps mismatch", data.get("match") is False,
          f"expected=60 actual={data.get('actual')}")


def test_720p_project(sandbox: Sandbox):
    """Test with the 720p/30fps project to verify different profile values."""
    print("\n=== 720p Project ===")

    data = run(sandbox, f"profile {SAMPLE_720P_PATH}")
    check("720p width", data.get("width") == "1280", data.get("width", ""))
    check("720p height", data.get("height") == "720", data.get("height", ""))
    check("720p fps num", data.get("frame_rate_num") == "30", data.get("frame_rate_num", ""))

    data = run(sandbox, f"check-resolution {SAMPLE_720P_PATH} 1280 720")
    check("720p check-resolution match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-fps {SAMPLE_720P_PATH} 30")
    check("720p check-fps match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-clip-count {SAMPLE_720P_PATH} 1")
    check("720p clip count", data.get("match") is True,
          f"expected=1 actual={data.get('actual')}")

    data = run(sandbox, f"check-track-count {SAMPLE_720P_PATH} 1")
    check("720p track count", data.get("match") is True,
          f"expected=1 actual={data.get('actual')}")


def test_all_commands_return_json(sandbox: Sandbox):
    """Every CLI command should output valid JSON (not crash with a traceback)."""
    print("\n=== JSON validity (all commands) ===")

    # Commands with the sample project file
    project_cmds = [
        f"project-info {SAMPLE_PROJECT_PATH}",
        f"clips {SAMPLE_PROJECT_PATH}",
        f"tracks {SAMPLE_PROJECT_PATH}",
        f"effects {SAMPLE_PROJECT_PATH}",
        f"transitions {SAMPLE_PROJECT_PATH}",
        f"clip-info {SAMPLE_PROJECT_PATH} producer0",
        f"profile {SAMPLE_PROJECT_PATH}",
        f"check-file-exists {SAMPLE_PROJECT_PATH}",
        f"check-clip-exists {SAMPLE_PROJECT_PATH} intro.mp4",
        f"check-clip-count {SAMPLE_PROJECT_PATH} 3",
        f"check-track-count {SAMPLE_PROJECT_PATH} 3",
        f"check-effect-exists {SAMPLE_PROJECT_PATH} glow",
        f"check-transition-exists {SAMPLE_PROJECT_PATH} luma",
        f"check-resolution {SAMPLE_PROJECT_PATH} 1920 1080",
        f"check-fps {SAMPLE_PROJECT_PATH} 25",
    ]

    for cmd in project_cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        check(f"JSON: {cmd.split()[0]}", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # Commands that should return error JSON (missing files)
    error_cmds = [
        "render-info /nonexistent/output.mp4",
        "check-render-output /nonexistent/output.mp4",
    ]

    for cmd in error_cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        check(f"JSON: {cmd.split()[0]} (error)", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed

    print("=" * 60)
    print("Kdenlive Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # Upload test .kdenlive project files
        print(f"Writing test project -> {SAMPLE_PROJECT_PATH}")
        sandbox.files.write(SAMPLE_PROJECT_PATH, SAMPLE_PROJECT_XML)

        print(f"Writing 720p test project -> {SAMPLE_720P_PATH}")
        sandbox.files.write(SAMPLE_720P_PATH, SAMPLE_720P_PROJECT_XML)

        # --- Run tests ---
        test_help(sandbox)
        test_errors(sandbox)
        test_project_info(sandbox)
        test_clips(sandbox)
        test_tracks(sandbox)
        test_effects(sandbox)
        test_transitions(sandbox)
        test_clip_info(sandbox)
        test_profile(sandbox)
        test_checks_positive(sandbox)
        test_checks_negative(sandbox)
        test_720p_project(sandbox)
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
