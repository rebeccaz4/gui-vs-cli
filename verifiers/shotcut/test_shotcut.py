"""
Test Shotcut verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (missing file, bad args, unknown command, bad extension)
  - XML query endpoints on MLT fixtures
  - Config (Shotcut.conf) endpoints
  - Export media (ffprobe) endpoints using a real ffmpeg-generated clip
  - check-* positive and negative cases for every check endpoint

Usage:
    python verifiers/shotcut/test_shotcut.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "shotcut.py"
VERIFIER_REMOTE = "/home/user/verifiers/shotcut.py"
V = f"python3 {VERIFIER_REMOTE}"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PROJECT_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<mlt LC_NUMERIC="C" version="7.14.0" producer="main_bin" root="/home/user/Videos">
  <profile description="HD 1080p 30fps" width="1920" height="1080"
           progressive="1" sample_aspect_num="1" sample_aspect_den="1"
           display_aspect_num="16" display_aspect_den="9"
           frame_rate_num="30" frame_rate_den="1" colorspace="709"/>

  <chain id="chain0" in="00:00:00.000" out="00:00:10.000">
    <property name="resource">/home/user/Videos/intro.mp4</property>
    <property name="mlt_service">avformat</property>
    <property name="shotcut:caption">Intro Clip</property>
    <property name="shotcut:hash">aabbccdd</property>
    <property name="length">00:00:10.000</property>
    <property name="audio_index">1</property>
    <property name="video_index">0</property>
  </chain>

  <chain id="chain1" in="00:00:00.000" out="00:00:05.000">
    <property name="resource">/home/user/Videos/main_footage.mp4</property>
    <property name="mlt_service">avformat</property>
    <property name="shotcut:caption">Main Footage</property>
    <property name="shotcut:hash">eeff0011</property>
    <property name="length">00:00:05.000</property>
    <property name="audio_index">1</property>
    <property name="video_index">0</property>
  </chain>

  <chain id="chain2" in="00:00:00.000" out="00:00:03.000">
    <property name="resource">/home/user/Music/background.mp3</property>
    <property name="mlt_service">avformat</property>
    <property name="shotcut:caption">Background Music</property>
    <property name="length">00:00:03.000</property>
    <property name="audio_index">0</property>
  </chain>

  <playlist id="main_bin">
    <property name="shotcut:name">Playlist</property>
    <entry producer="chain0" in="00:00:00.000" out="00:00:10.000"/>
    <entry producer="chain1" in="00:00:00.000" out="00:00:05.000"/>
    <entry producer="chain2" in="00:00:00.000" out="00:00:03.000"/>
  </playlist>

  <playlist id="playlist0">
    <property name="shotcut:name">V1</property>
    <property name="shotcut:video">1</property>
    <entry producer="chain0" in="00:00:00.000" out="00:00:10.000"/>
    <blank length="00:00:01.000"/>
    <entry producer="chain1" in="00:00:00.000" out="00:00:05.000"/>
  </playlist>

  <playlist id="playlist1">
    <property name="shotcut:name">A1</property>
    <property name="shotcut:audio">1</property>
    <entry producer="chain2" in="00:00:00.000" out="00:00:03.000"/>
  </playlist>

  <tractor id="tractor0" in="00:00:00.000" out="00:00:16.000">
    <track producer="main_bin" hide="both"/>
    <track producer="playlist0"/>
    <track producer="playlist1" hide="video"/>

    <transition id="transition0" in="00:00:09.000" out="00:00:11.000">
      <property name="mlt_service">luma</property>
      <property name="a_track">0</property>
      <property name="b_track">1</property>
    </transition>

    <filter id="filter0" in="00:00:00.000" out="00:00:10.000">
      <property name="mlt_service">brightness</property>
      <property name="shotcut:filter">brightness</property>
      <property name="shotcut:name">Brightness</property>
    </filter>

    <filter id="filter1" in="00:00:00.000" out="00:00:16.000">
      <property name="mlt_service">volume</property>
      <property name="shotcut:filter">volume</property>
      <property name="shotcut:name">Volume</property>
    </filter>
  </tractor>
</mlt>
"""

SAMPLE_720P_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<mlt LC_NUMERIC="C" version="7.14.0" producer="main_bin" root="/home/user/Videos">
  <profile description="HD 720p 25fps" width="1280" height="720"
           progressive="1" sample_aspect_num="1" sample_aspect_den="1"
           display_aspect_num="16" display_aspect_den="9"
           frame_rate_num="25" frame_rate_den="1" colorspace="709"/>

  <chain id="chain0" in="00:00:00.000" out="00:00:05.000">
    <property name="resource">/home/user/Videos/only.mp4</property>
    <property name="mlt_service">avformat</property>
    <property name="shotcut:caption">Only Clip</property>
  </chain>

  <playlist id="playlist0">
    <property name="shotcut:name">V1</property>
    <entry producer="chain0" in="00:00:00.000" out="00:00:05.000"/>
  </playlist>

  <tractor id="tractor0" in="00:00:00.000" out="00:00:05.000">
    <track producer="playlist0"/>
  </tractor>
</mlt>
"""

# Qt INI format. Section names in square brackets; Qt often uses % encoding and
# backslash-escaped keys but configparser handles the plain form.
SAMPLE_CONFIG_INI = """\
[General]
theme=dark
timeFormat=HH:mm:ss
language=en_US

[Settings]
playerGpu=false
defaultProfile=atsc_1080p_30
askUpgrade=false

[RecentFiles]
1\\Path=/home/user/Videos/project_one.mlt
2\\Path=/home/user/Videos/project_two.mlt
size=2
"""

SAMPLE_PROJECT_PATH = "/home/user/test_shotcut.mlt"
SAMPLE_720P_PATH = "/home/user/test_shotcut_720p.mlt"
SAMPLE_CONFIG_PATH = "/home/user/.config/Meltytech/Shotcut.conf"
SAMPLE_EXPORT_PATH = "/home/user/test_export.mp4"
EMPTY_EXPORT_PATH = "/home/user/test_empty.mp4"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

passed = 0
failed = 0
errors: list[str] = []


class CmdResult:
    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def run_raw(sandbox: Sandbox, cmd: str, timeout: int = 30) -> CmdResult:
    try:
        result = sandbox.commands.run(f"{V} {cmd}", timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def run(sandbox: Sandbox, cmd: str, timeout: int = 30):
    r = run_raw(sandbox, cmd, timeout)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


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
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    print("\n=== Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"exit={result.exit_code}")
    check("help mentions Shotcut", "Shotcut" in result.stdout, result.stdout[:100])
    check("help lists commands", "Commands:" in result.stdout, result.stdout[:100])


def test_errors(sandbox: Sandbox):
    print("\n=== Errors ===")

    r = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", r.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(r.stdout), r.stdout[:100])

    r = run_raw(sandbox, "clips")
    check("missing arg exits 1", r.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(r.stdout), r.stdout[:100])

    data = run(sandbox, "project-info /nonexistent/path.mlt")
    check("missing file returns error", "error" in data, str(data)[:100])

    # Wrong extension
    sandbox.commands.run("echo '<mlt/>' > /tmp/test.txt")
    data = run(sandbox, "project-info /tmp/test.txt")
    check("wrong extension returns error", "error" in data, str(data)[:100])

    # Bad clip id
    data = run(sandbox, f"clip-info {SAMPLE_PROJECT_PATH} nonexistent_id")
    check("bad clip id returns error", "error" in data, str(data)[:100])

    # Missing config file
    data = run(sandbox, "config /tmp/does_not_exist.conf")
    check("missing config returns error", "error" in data, str(data)[:100])


def test_project_info(sandbox: Sandbox):
    print("\n=== project-info ===")
    data = run(sandbox, f"project-info {SAMPLE_PROJECT_PATH}")
    check("project-info returns dict", isinstance(data, dict))
    check("project-info producer_count", data.get("producer_count") == 3,
          f"got {data.get('producer_count')}")
    check("project-info playlist_count", data.get("playlist_count") == 3,
          f"got {data.get('playlist_count')}")
    check("project-info tractor_track_count", data.get("tractor_track_count") == 3,
          f"got {data.get('tractor_track_count')}")
    check("project-info filter_count", data.get("filter_count") == 2,
          f"got {data.get('filter_count')}")
    check("project-info transition_count", data.get("transition_count") == 1,
          f"got {data.get('transition_count')}")
    prof = data.get("profile") or {}
    check("project-info profile width", prof.get("width") == "1920", str(prof)[:100])


def test_clips(sandbox: Sandbox):
    print("\n=== clips ===")
    data = run(sandbox, f"clips {SAMPLE_PROJECT_PATH}")
    check("clips returns list", isinstance(data, list))
    check("clips count is 3", len(data) == 3, f"got {len(data)}")
    if len(data) >= 1:
        c0 = data[0]
        check("chain0 id", c0.get("id") == "chain0", c0.get("id", ""))
        check("chain0 resource", "intro.mp4" in c0.get("resource", ""),
              c0.get("resource", ""))
        check("chain0 caption", c0.get("shotcut:caption") == "Intro Clip",
              c0.get("shotcut:caption", ""))


def test_playlists_and_tracks(sandbox: Sandbox):
    print("\n=== playlists + tracks ===")
    data = run(sandbox, f"playlists {SAMPLE_PROJECT_PATH}")
    check("playlists returns list", isinstance(data, list))
    check("playlists count", len(data) == 3, f"got {len(data)}")

    data = run(sandbox, f"tracks {SAMPLE_PROJECT_PATH}")
    check("tracks returns list", isinstance(data, list))
    check("tractor track count", len(data) == 3, f"got {len(data)}")


def test_filters_transitions(sandbox: Sandbox):
    print("\n=== filters + transitions ===")
    data = run(sandbox, f"filters {SAMPLE_PROJECT_PATH}")
    check("filters returns list", isinstance(data, list))
    check("filters count 2", len(data) == 2, f"got {len(data)}")
    if len(data) >= 1:
        check("filter0 mlt_service", data[0].get("mlt_service") == "brightness",
              data[0].get("mlt_service", ""))

    data = run(sandbox, f"transitions {SAMPLE_PROJECT_PATH}")
    check("transitions returns list", isinstance(data, list))
    check("transitions count 1", len(data) == 1, f"got {len(data)}")
    if len(data) >= 1:
        check("transition0 mlt_service", data[0].get("mlt_service") == "luma",
              data[0].get("mlt_service", ""))


def test_clip_info_and_profile(sandbox: Sandbox):
    print("\n=== clip-info + profile ===")
    data = run(sandbox, f"clip-info {SAMPLE_PROJECT_PATH} chain1")
    check("clip-info id", data.get("id") == "chain1")
    check("clip-info resource", "main_footage.mp4" in data.get("resource", ""))
    check("clip-info caption", data.get("shotcut:caption") == "Main Footage")

    data = run(sandbox, f"profile {SAMPLE_PROJECT_PATH}")
    check("profile width", data.get("width") == "1920")
    check("profile height", data.get("height") == "1080")
    check("profile fps num", data.get("frame_rate_num") == "30")
    check("profile colorspace", data.get("colorspace") == "709")


def test_checks_positive(sandbox: Sandbox):
    print("\n=== check-* positive ===")

    data = run(sandbox, f"check-file-exists {SAMPLE_PROJECT_PATH}")
    check("check-file-exists true", data.get("exists") is True, str(data)[:100])

    data = run(sandbox, f"check-clip-exists {SAMPLE_PROJECT_PATH} intro")
    check("check-clip-exists found by caption/resource", data.get("exists") is True,
          str(data)[:100])

    data = run(sandbox, f"check-clip-exists {SAMPLE_PROJECT_PATH} background.mp3")
    check("check-clip-exists by mp3 filename", data.get("exists") is True,
          str(data)[:100])

    data = run(sandbox, f"check-clip-count {SAMPLE_PROJECT_PATH} 3")
    check("check-clip-count match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-playlist-count {SAMPLE_PROJECT_PATH} 3")
    check("check-playlist-count match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-track-count {SAMPLE_PROJECT_PATH} 3")
    check("check-track-count match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-filter-exists {SAMPLE_PROJECT_PATH} brightness")
    check("check-filter-exists brightness", data.get("exists") is True, str(data)[:100])

    data = run(sandbox, f"check-filter-exists {SAMPLE_PROJECT_PATH} volume")
    check("check-filter-exists volume", data.get("exists") is True, str(data)[:100])

    data = run(sandbox, f"check-filter-count {SAMPLE_PROJECT_PATH} 2")
    check("check-filter-count match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-transition-exists {SAMPLE_PROJECT_PATH} luma")
    check("check-transition-exists luma", data.get("exists") is True, str(data)[:100])

    data = run(sandbox, f"check-transition-count {SAMPLE_PROJECT_PATH} 1")
    check("check-transition-count match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-resolution {SAMPLE_PROJECT_PATH} 1920 1080")
    check("check-resolution match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-fps {SAMPLE_PROJECT_PATH} 30")
    check("check-fps match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-clip-resource {SAMPLE_PROJECT_PATH} chain0 intro")
    check("check-clip-resource match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-playlist-entry-count {SAMPLE_PROJECT_PATH} playlist0 2")
    check("check-playlist-entry-count match", data.get("match") is True, str(data)[:100])


def test_checks_negative(sandbox: Sandbox):
    print("\n=== check-* negative ===")

    data = run(sandbox, "check-file-exists /nonexistent/file.mp4")
    check("check-file-exists false", data.get("exists") is False, str(data)[:100])

    data = run(sandbox, f"check-clip-exists {SAMPLE_PROJECT_PATH} nonexistent_clip.avi")
    check("check-clip-exists missing", data.get("exists") is False, str(data)[:100])

    data = run(sandbox, f"check-clip-count {SAMPLE_PROJECT_PATH} 99")
    check("check-clip-count mismatch", data.get("match") is False, str(data)[:100])

    data = run(sandbox, f"check-playlist-count {SAMPLE_PROJECT_PATH} 10")
    check("check-playlist-count mismatch", data.get("match") is False, str(data)[:100])

    data = run(sandbox, f"check-track-count {SAMPLE_PROJECT_PATH} 99")
    check("check-track-count mismatch", data.get("match") is False, str(data)[:100])

    data = run(sandbox, f"check-filter-exists {SAMPLE_PROJECT_PATH} missing_effect")
    check("check-filter-exists missing", data.get("exists") is False, str(data)[:100])

    data = run(sandbox, f"check-filter-count {SAMPLE_PROJECT_PATH} 99")
    check("check-filter-count mismatch", data.get("match") is False, str(data)[:100])

    data = run(sandbox, f"check-transition-exists {SAMPLE_PROJECT_PATH} wipe_nonexistent")
    check("check-transition-exists missing", data.get("exists") is False, str(data)[:100])

    data = run(sandbox, f"check-transition-count {SAMPLE_PROJECT_PATH} 5")
    check("check-transition-count mismatch", data.get("match") is False, str(data)[:100])

    data = run(sandbox, f"check-resolution {SAMPLE_PROJECT_PATH} 3840 2160")
    check("check-resolution mismatch", data.get("match") is False, str(data)[:100])

    data = run(sandbox, f"check-fps {SAMPLE_PROJECT_PATH} 60")
    check("check-fps mismatch", data.get("match") is False, str(data)[:100])

    data = run(sandbox, f"check-clip-resource {SAMPLE_PROJECT_PATH} chain0 absent_substring")
    check("check-clip-resource mismatch", data.get("match") is False, str(data)[:100])

    data = run(sandbox, f"check-playlist-entry-count {SAMPLE_PROJECT_PATH} playlist0 99")
    check("check-playlist-entry-count mismatch", data.get("match") is False, str(data)[:100])


def test_720p_fixture(sandbox: Sandbox):
    print("\n=== 720p fixture ===")
    data = run(sandbox, f"profile {SAMPLE_720P_PATH}")
    check("720p width", data.get("width") == "1280")
    check("720p height", data.get("height") == "720")
    check("720p fps num", data.get("frame_rate_num") == "25")

    data = run(sandbox, f"check-resolution {SAMPLE_720P_PATH} 1280 720")
    check("720p check-resolution match", data.get("match") is True)

    data = run(sandbox, f"check-fps {SAMPLE_720P_PATH} 25")
    check("720p check-fps match", data.get("match") is True)

    data = run(sandbox, f"check-clip-count {SAMPLE_720P_PATH} 1")
    check("720p clip count", data.get("match") is True)

    data = run(sandbox, f"check-track-count {SAMPLE_720P_PATH} 1")
    check("720p track count", data.get("match") is True)


def test_config(sandbox: Sandbox):
    print("\n=== config endpoints ===")

    data = run(sandbox, "config")
    check("config returns dict", isinstance(data, dict))
    check("config has General section", "General" in data, str(list(data.keys()))[:100])
    if isinstance(data, dict):
        general = data.get("General", {})
        check("config General.theme", general.get("theme") == "dark",
              str(general)[:100])

    data = run(sandbox, "config-value General theme")
    check("config-value returns theme", data.get("value") == "dark",
          str(data)[:100])

    data = run(sandbox, "config-value General nonexistent_key")
    check("config-value missing key returns error", "error" in data,
          str(data)[:100])

    data = run(sandbox, "check-config-value General theme dark")
    check("check-config-value positive", data.get("match") is True,
          str(data)[:100])

    data = run(sandbox, "check-config-value General theme light")
    check("check-config-value negative", data.get("match") is False,
          str(data)[:100])

    data = run(sandbox, "check-config-value Settings defaultProfile atsc_1080p_30")
    check("check-config-value Settings", data.get("match") is True,
          str(data)[:100])

    data = run(sandbox, "recent-files")
    check("recent-files has entries", isinstance(data, dict) and "recent_files" in data,
          str(data)[:100])


def test_export(sandbox: Sandbox):
    print("\n=== export (ffprobe) ===")

    # Create sample export file via ffmpeg (color source, tiny).
    gen = sandbox.commands.run(
        f"ffmpeg -y -f lavfi -i color=c=blue:s=320x240:d=1 "
        f"-c:v libx264 -pix_fmt yuv420p -t 1 {SAMPLE_EXPORT_PATH} 2>&1",
        timeout=60,
    )
    # Verify file exists and has size
    r = sandbox.commands.run(f"test -s {SAMPLE_EXPORT_PATH} && echo OK", timeout=5)
    check("ffmpeg created export file", "OK" in r.stdout,
          f"gen_out={gen.stdout[-200:] if gen and gen.stdout else ''} "
          f"exists_stdout={r.stdout}")

    # Create empty file
    sandbox.commands.run(f"touch {EMPTY_EXPORT_PATH}")

    data = run(sandbox, f"export-info {SAMPLE_EXPORT_PATH}")
    check("export-info has streams", isinstance(data, dict) and "streams" in data,
          str(data)[:100])

    data = run(sandbox, f"check-export-output {SAMPLE_EXPORT_PATH}")
    check("check-export-output valid", data.get("valid") is True, str(data)[:100])

    data = run(sandbox, f"check-export-output {EMPTY_EXPORT_PATH}")
    check("check-export-output empty false", data.get("valid") is False,
          str(data)[:100])

    data = run(sandbox, f"check-export-output /nonexistent/file.mp4")
    check("check-export-output missing false", data.get("valid") is False,
          str(data)[:100])

    data = run(sandbox, f"check-export-resolution {SAMPLE_EXPORT_PATH} 320 240")
    check("check-export-resolution match", data.get("match") is True,
          str(data)[:100])

    data = run(sandbox, f"check-export-resolution {SAMPLE_EXPORT_PATH} 1920 1080")
    check("check-export-resolution mismatch", data.get("match") is False,
          str(data)[:100])

    data = run(sandbox, f"check-export-codec {SAMPLE_EXPORT_PATH} h264 video")
    check("check-export-codec h264", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-export-codec {SAMPLE_EXPORT_PATH} prores video")
    check("check-export-codec mismatch", data.get("match") is False, str(data)[:100])


def test_json_validity_sweep(sandbox: Sandbox):
    print("\n=== JSON validity sweep ===")
    cmds = [
        f"project-info {SAMPLE_PROJECT_PATH}",
        f"clips {SAMPLE_PROJECT_PATH}",
        f"playlists {SAMPLE_PROJECT_PATH}",
        f"tracks {SAMPLE_PROJECT_PATH}",
        f"filters {SAMPLE_PROJECT_PATH}",
        f"transitions {SAMPLE_PROJECT_PATH}",
        f"clip-info {SAMPLE_PROJECT_PATH} chain0",
        f"profile {SAMPLE_PROJECT_PATH}",
        f"check-file-exists {SAMPLE_PROJECT_PATH}",
        f"check-clip-exists {SAMPLE_PROJECT_PATH} intro",
        f"check-clip-count {SAMPLE_PROJECT_PATH} 3",
        f"check-playlist-count {SAMPLE_PROJECT_PATH} 3",
        f"check-track-count {SAMPLE_PROJECT_PATH} 3",
        f"check-filter-exists {SAMPLE_PROJECT_PATH} brightness",
        f"check-filter-count {SAMPLE_PROJECT_PATH} 2",
        f"check-transition-exists {SAMPLE_PROJECT_PATH} luma",
        f"check-transition-count {SAMPLE_PROJECT_PATH} 1",
        f"check-resolution {SAMPLE_PROJECT_PATH} 1920 1080",
        f"check-fps {SAMPLE_PROJECT_PATH} 30",
        f"check-clip-resource {SAMPLE_PROJECT_PATH} chain0 intro",
        f"check-playlist-entry-count {SAMPLE_PROJECT_PATH} playlist0 2",
        "config",
        "config-value General theme",
        "recent-files",
        "check-config-value General theme dark",
        f"export-info {SAMPLE_EXPORT_PATH}",
        f"check-export-output {SAMPLE_EXPORT_PATH}",
        "check-export-output /nonexistent/file.mp4",
    ]
    for c in cmds:
        r = run_raw(sandbox, c)
        valid = is_valid_json(r.stdout)
        check(f"JSON: {c.split()[0]}", valid,
              f"exit={r.exit_code} stdout={r.stdout[:80]}" if not valid else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed

    print("=" * 60)
    print("Shotcut Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # Write fixtures
        print(f"Writing {SAMPLE_PROJECT_PATH}")
        sandbox.files.write(SAMPLE_PROJECT_PATH, SAMPLE_PROJECT_XML)

        print(f"Writing {SAMPLE_720P_PATH}")
        sandbox.files.write(SAMPLE_720P_PATH, SAMPLE_720P_XML)

        print(f"Writing {SAMPLE_CONFIG_PATH}")
        sandbox.commands.run("mkdir -p /home/user/.config/Meltytech")
        sandbox.files.write(SAMPLE_CONFIG_PATH, SAMPLE_CONFIG_INI)

        # Run tests
        test_help(sandbox)
        test_errors(sandbox)
        test_project_info(sandbox)
        test_clips(sandbox)
        test_playlists_and_tracks(sandbox)
        test_filters_transitions(sandbox)
        test_clip_info_and_profile(sandbox)
        test_checks_positive(sandbox)
        test_checks_negative(sandbox)
        test_720p_fixture(sandbox)
        test_config(sandbox)
        test_export(sandbox)
        test_json_validity_sweep(sandbox)

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
        for e in errors:
            print(f"  - {e}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
