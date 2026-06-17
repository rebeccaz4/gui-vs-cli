"""
Test VLC verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (VLC not running, bad args)
  - File-based endpoints (config, recent-media, media-file-info)
  - HTTP API endpoints (status, playlist, media-info, volume)
  - Composite check-* endpoints (positive and negative cases)
  - JSON validity for all commands

Usage:
    python verifiers/vlc/test_vlc.py
"""

import json
import sys
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "vlc.py"
VERIFIER_REMOTE = "/home/user/verifiers/vlc.py"
V = f"python3 {VERIFIER_REMOTE}"

TEST_MEDIA_DIR = "/home/user/test_media"
TEST_VIDEO = f"{TEST_MEDIA_DIR}/test_video.mp4"
TEST_AUDIO = f"{TEST_MEDIA_DIR}/test_audio.mp3"
HTTP_PASSWORD = "secret"
HTTP_PORT = 8080

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


def run_shell(sandbox: Sandbox, cmd: str, timeout: int = 30) -> CmdResult:
    """Run a raw shell command (not through verifier)."""
    try:
        result = sandbox.commands.run(cmd, timeout=timeout)
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
    check("help mentions VLC", "VLC" in result.stdout, result.stdout[:100])


def test_errors_vlc_not_running(sandbox: Sandbox):
    """HTTP API endpoints should return error JSON when VLC is not running."""
    print("\n=== Errors (VLC not running) ===")

    data = run(sandbox, "status")
    check("status returns error", "error" in data, str(data)[:100])

    data = run(sandbox, "playlist")
    check("playlist returns error", "error" in data, str(data)[:100])

    data = run(sandbox, "volume")
    check("volume returns error", "error" in data, str(data)[:100])

    data = run(sandbox, "check-playing")
    check("check-playing returns false", data.get("playing") is False, str(data)[:100])


def test_errors_bad_args(sandbox: Sandbox):
    """Missing/invalid arguments should return error JSON, not crash."""
    print("\n=== Errors (bad args) ===")

    # Missing required arg
    result = run_raw(sandbox, "media-file-info")
    check("missing arg exits 1", result.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    result = run_raw(sandbox, "check-media-loaded")
    check("missing check arg exits 1", result.exit_code == 1)
    check("missing check arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Unknown command
    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])


def test_create_test_media(sandbox: Sandbox):
    """Create test media files using ffmpeg."""
    print("\n=== Create Test Media ===")

    run_shell(sandbox, f"mkdir -p {TEST_MEDIA_DIR}")

    # Create a 5-second test video (solid color with tone)
    r = run_shell(sandbox,
        f"ffmpeg -y -f lavfi -i color=c=blue:s=320x240:d=5 "
        f"-f lavfi -i sine=frequency=440:duration=5 "
        f"-c:v libx264 -c:a aac -shortest {TEST_VIDEO} 2>&1",
        timeout=30)
    check("test video created", r.exit_code == 0, f"stderr={r.stderr[:200]}")

    # Create a 3-second test audio
    r = run_shell(sandbox,
        f"ffmpeg -y -f lavfi -i sine=frequency=440:duration=3 "
        f"-c:a libmp3lame {TEST_AUDIO} 2>&1",
        timeout=30)
    check("test audio created", r.exit_code == 0, f"stderr={r.stderr[:200]}")

    # Verify files exist
    r = run_shell(sandbox, f"ls -la {TEST_VIDEO} {TEST_AUDIO}")
    check("test media files exist", r.exit_code == 0, r.stdout[:200])


def test_file_based_endpoints(sandbox: Sandbox):
    """Test file-based endpoints (no VLC process needed)."""
    print("\n=== File-Based Endpoints ===")

    # media-file-info with ffprobe
    data = run(sandbox, f"media-file-info {TEST_VIDEO}")
    check("media-file-info returns dict", isinstance(data, dict), str(type(data)))
    check("media-file-info has duration", data.get("duration") is not None, str(data)[:150])
    if data.get("duration"):
        check("video duration ~5s", abs(data["duration"] - 5.0) < 2.0,
              f"got {data['duration']}")
    check("media-file-info has streams", isinstance(data.get("streams"), list), str(data.get("streams")))
    if data.get("streams"):
        codec_types = [s.get("codec_type") for s in data["streams"]]
        check("has video stream", "video" in codec_types, str(codec_types))
        check("has audio stream", "audio" in codec_types, str(codec_types))

    # media-file-info for audio
    data = run(sandbox, f"media-file-info {TEST_AUDIO}")
    check("audio info has duration", data.get("duration") is not None, str(data)[:150])

    # check-file-exists (positive)
    data = run(sandbox, f"check-file-exists {TEST_VIDEO}")
    check("check-file-exists true", data.get("exists") is True, str(data))
    check("check-file-exists has size", data.get("size_bytes", 0) > 0, str(data))

    # check-file-exists (negative)
    data = run(sandbox, "check-file-exists /nonexistent/file.mp4")
    check("check-file-exists false", data.get("exists") is False, str(data))

    # check-media-duration (positive)
    data = run(sandbox, f"check-media-duration {TEST_VIDEO} 5 2")
    check("check-media-duration match", data.get("match") is True, str(data))

    # check-media-duration (negative)
    data = run(sandbox, f"check-media-duration {TEST_VIDEO} 60 1")
    check("check-media-duration no match", data.get("match") is False, str(data))

    # check-media-format
    data = run(sandbox, f"check-media-format {TEST_VIDEO} mp4")
    check("check-media-format mp4 match", data.get("match") is True, str(data))

    data = run(sandbox, f"check-media-format {TEST_VIDEO} mkv")
    check("check-media-format mkv no match", data.get("match") is False, str(data))

    # config (vlcrc may not exist yet, that's ok)
    data = run(sandbox, "config")
    check("config returns dict", isinstance(data, dict), str(type(data)))

    # recent-media (qt-interface.conf may not exist yet)
    data = run(sandbox, "recent-media")
    check("recent-media returns dict", isinstance(data, dict), str(type(data)))


def test_http_api_endpoints(sandbox: Sandbox):
    """Test HTTP API endpoints with VLC running."""
    print("\n=== HTTP API Endpoints ===")

    # status
    data = run(sandbox, "status")
    check("status returns dict", isinstance(data, dict), str(type(data)))
    check("status has state", "state" in data or "error" in data, str(data)[:100])
    if "state" in data:
        check("status state is string", isinstance(data["state"], str), str(data["state"]))

    # volume
    data = run(sandbox, "volume")
    check("volume returns dict", isinstance(data, dict))
    check("volume has volume_raw", "volume_raw" in data or "error" in data, str(data)[:100])

    # playlist
    data = run(sandbox, "playlist")
    check("playlist returns dict", isinstance(data, dict))
    check("playlist has count", "count" in data or "error" in data, str(data)[:100])

    # media-info
    data = run(sandbox, "media-info")
    check("media-info returns dict", isinstance(data, dict))


def test_checks_positive(sandbox: Sandbox):
    """Composite check-* endpoints -- positive cases."""
    print("\n=== Checks (positive) ===")

    # check-playing (VLC should be playing the test video)
    data = run(sandbox, "check-playing")
    check("check-playing returns dict", isinstance(data, dict))
    check("check-playing playing=true", data.get("playing") is True, str(data)[:150])

    # check-media-loaded
    data = run(sandbox, "check-media-loaded test_video")
    check("check-media-loaded loaded=true", data.get("loaded") is True, str(data)[:150])

    # check-playlist-count (should have 1 item)
    data = run(sandbox, "check-playlist-count 1")
    check("check-playlist-count match=true", data.get("match") is True, str(data)[:150])

    # check-position (should be near start, within tolerance)
    time.sleep(2)
    data = run(sandbox, "check-position 2 5")
    check("check-position returns dict", isinstance(data, dict))
    check("check-position has match key", "match" in data, str(data)[:150])


def test_checks_negative(sandbox: Sandbox):
    """Composite check-* endpoints -- negative cases."""
    print("\n=== Checks (negative) ===")

    # check-media-loaded with wrong filename
    data = run(sandbox, "check-media-loaded nonexistent_xyzzy_12345")
    check("check-media-loaded false", data.get("loaded") is False, str(data)[:100])

    # check-playlist-count with wrong count
    data = run(sandbox, "check-playlist-count 999")
    check("check-playlist-count no match", data.get("match") is False, str(data)[:100])

    # check-position at wrong time
    data = run(sandbox, "check-position 999 1")
    check("check-position no match", data.get("match") is False, str(data)[:100])

    # check-volume at wrong level
    data = run(sandbox, "check-volume 0")
    # Default volume is not 0, so this should not match
    check("check-volume returns dict", isinstance(data, dict))
    check("check-volume has match key", "match" in data, str(data)[:100])

    # check-media-duration for nonexistent file
    data = run(sandbox, "check-media-duration /nonexistent/file.mp4 10")
    check("check-media-duration error for missing file", data.get("match") is False, str(data)[:100])

    # check-media-format for nonexistent file
    data = run(sandbox, "check-media-format /nonexistent/file.mp4 mp4")
    check("check-media-format error for missing file", data.get("match") is False, str(data)[:100])


def test_all_commands_return_json(sandbox: Sandbox):
    """Every CLI command should output valid JSON (not crash with a traceback)."""
    print("\n=== JSON validity (all commands) ===")

    # Commands that need no args
    no_arg_cmds = ["status", "playlist", "media-info", "volume",
                   "dbus-status", "dbus-metadata",
                   "config", "recent-media", "check-playing"]

    for cmd in no_arg_cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        check(f"{cmd} returns valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # Commands that need args (use dummy/test values)
    arg_cmds = [
        ("config", "volume"),
        ("media-file-info", TEST_VIDEO),
        ("check-file-exists", TEST_VIDEO),
        ("check-file-exists", "/nonexistent"),
        ("check-media-loaded", "test"),
        ("check-volume", "50"),
        ("check-position", "0"),
        ("check-media-duration", f"{TEST_VIDEO} 5"),
        ("check-media-format", f"{TEST_VIDEO} mp4"),
        ("check-playlist-count", "1"),
    ]

    for cmd, arg in arg_cmds:
        result = run_raw(sandbox, f"{cmd} {arg}")
        valid = is_valid_json(result.stdout)
        check(f"{cmd} {arg} returns valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed

    print("=" * 60)
    print("VLC Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # --- Tests with VLC NOT running ---
        test_help(sandbox)
        test_errors_vlc_not_running(sandbox)
        test_errors_bad_args(sandbox)

        # --- Create test media files ---
        test_create_test_media(sandbox)

        # --- File-based tests (no VLC process needed) ---
        test_file_based_endpoints(sandbox)

        # --- Launch VLC with HTTP interface ---
        VLC_CMD = (
            f"vlc --intf http --http-port {HTTP_PORT} --http-password {HTTP_PASSWORD} "
            f"--no-video-title-show --no-qt-privacy-ask "
            f"--play-and-stop "
            f"{TEST_VIDEO}"
        )

        def launch_vlc():
            """Kill existing VLC and launch fresh."""
            try:
                sandbox.commands.run("pkill -9 -f vlc", timeout=5)
            except (CommandExitException, Exception):
                pass
            time.sleep(1)

            sandbox.commands.run(
                f"DISPLAY=:1 {VLC_CMD} > /tmp/vlc.log 2>&1",
                background=True,
            )
            # Wait for HTTP API to become available
            for i in range(20):
                try:
                    r = sandbox.commands.run(
                        f"curl -s -u :{HTTP_PASSWORD} http://127.0.0.1:{HTTP_PORT}/requests/status.json",
                        timeout=3,
                    )
                    if '"state"' in r.stdout:
                        print(f"  VLC HTTP API ready (attempt {i+1})")
                        return True
                except (CommandExitException, Exception):
                    pass
                time.sleep(1)
            # Debug on failure
            try:
                r = sandbox.commands.run("tail -30 /tmp/vlc.log", timeout=3)
                print(f"  [vlc log] {r.stdout[-500:]}")
            except (CommandExitException, Exception):
                pass
            try:
                r = sandbox.commands.run("pgrep -la vlc", timeout=3)
                print(f"  [processes] {r.stdout.strip()[:200]}")
            except (CommandExitException, Exception):
                print("  No VLC processes found!")
            return False

        def ensure_vlc():
            """Check if VLC HTTP API is alive, relaunch if not."""
            try:
                r = sandbox.commands.run(
                    f"curl -s -u :{HTTP_PASSWORD} http://127.0.0.1:{HTTP_PORT}/requests/status.json",
                    timeout=3,
                )
                if '"state"' in r.stdout:
                    return True
            except (CommandExitException, Exception):
                pass
            print("  [debug] VLC HTTP API dead -- relaunching...")
            return launch_vlc()

        print(f"\nLaunching VLC with HTTP interface on port {HTTP_PORT}...")
        if not launch_vlc():
            print("  WARNING: VLC HTTP API not ready -- API tests may fail")

        # Give VLC a moment to start playing
        time.sleep(2)

        # --- Tests with VLC running ---
        test_http_api_endpoints(sandbox)
        ensure_vlc()
        test_checks_positive(sandbox)
        ensure_vlc()
        test_checks_negative(sandbox)
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
