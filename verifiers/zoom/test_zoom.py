"""
Test Zoom verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage
  - Error cases before any config exists
  - Error cases with bad args
  - File-based endpoints with fixture zoomus.conf
  - check-* endpoints (positive + negative)
  - Data/logs/recordings directory scanning
  - JSON validity for all commands

Usage:
    python verifiers/zoom/test_zoom.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "zoom.py"
VERIFIER_REMOTE = "/home/user/verifiers/zoom.py"
V = f"python3 {VERIFIER_REMOTE}"

# ---------------------------------------------------------------------------
# Fixture content
# ---------------------------------------------------------------------------

FIXTURE_ZOOMUS_CONF = """\
[General]
autoMuteMic=true
autoTurnOffVideo=false
language=en-US
localRecordingPath=/home/user/Documents/Zoom
autoStart=false
HowlingDetection=true
Theme=2
enableMirrorEffect=1

[Audio]
AudioDevice=default
MicrophoneLevel=80
SpeakerLevel=75
SuppressBackgroundNoise=2
EnableOriginalSound=false

[Video]
HDVideo=false
mirrorMyVideo=true
VideoDevice=Integrated Webcam
TouchUpMyAppearance=false

[chat.client]
Theme=dark
EnableSpellCheck=true

[General.Meetings]
ShowTimer=true
ConfirmLeaveMeeting=true
"""

FIXTURE_HISTORY_TXT = """\
meetingID=1234567890
lastJoined=2026-04-10
"""

FIXTURE_CACHE_JSON = '{"recent": [{"id": "9876543210"}]}'

FIXTURE_LOG = "INFO Zoom client started\nINFO config loaded\n"

CONFIG_PATH = "/home/user/.config/zoomus.conf"
DATA_DIR = "/home/user/.zoom/data"
LOGS_DIR = "/home/user/.zoom/logs"
RECORDING_DIR = "/home/user/Documents/Zoom"
EXISTING_FILE = "/home/user/existing_file.txt"

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


def run(sandbox: Sandbox, cmd: str, timeout: int = 30):
    r = run_raw(sandbox, cmd, timeout)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


def run_raw(sandbox: Sandbox, cmd: str, timeout: int = 30) -> CmdResult:
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
    print("\n=== Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"exit={result.exit_code}")
    check("help mentions commands", "Commands:" in result.stdout, result.stdout[:200])
    check("help mentions Zoom", "Zoom" in result.stdout, result.stdout[:200])


def test_errors_no_config(sandbox: Sandbox):
    """Before any fixture is written, file-based endpoints should return errors."""
    print("\n=== Errors (no config) ===")

    data = run(sandbox, "check-config-exists")
    check("check-config-exists false before fixture", data.get("exists") is False,
          str(data)[:100])

    data = run(sandbox, "sections")
    if isinstance(data, list):
        first = data[0] if data else {}
    else:
        first = data
    check("sections returns error without fixture",
          isinstance(first, dict) and "error" in first,
          str(data)[:100])

    data = run(sandbox, "config")
    check("config returns error without fixture",
          isinstance(data, dict) and "error" in data,
          str(data)[:100])

    data = run(sandbox, "section General")
    check("section returns error without fixture",
          isinstance(data, dict) and "error" in data,
          str(data)[:100])


def test_errors_bad_args(sandbox: Sandbox):
    print("\n=== Errors (bad args) ===")

    # Missing arg for `section`
    result = run_raw(sandbox, "section")
    check("section missing arg exits 1", result.exit_code == 1)
    check("section missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Missing args for check-config (needs 3)
    result = run_raw(sandbox, "check-config General")
    check("check-config missing args exits 1", result.exit_code == 1)
    check("check-config missing args valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Unknown command
    result = run_raw(sandbox, "not-a-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Bad integer for check-recording-count
    result = run_raw(sandbox, "check-recording-count notanumber")
    check("bad int exits 1", result.exit_code == 1)
    check("bad int valid JSON", is_valid_json(result.stdout), result.stdout[:100])


def test_config_introspection(sandbox: Sandbox):
    print("\n=== Config introspection ===")

    data = run(sandbox, "check-config-exists")
    check("check-config-exists true after fixture", data.get("exists") is True, str(data)[:100])

    data = run(sandbox, "sections")
    check("sections returns list", isinstance(data, list), str(type(data)))
    check("sections contains General", "General" in data, str(data))
    check("sections contains Audio", "Audio" in data, str(data))
    check("sections contains Video", "Video" in data, str(data))
    check("sections contains chat.client", "chat.client" in data, str(data))

    data = run(sandbox, "section General")
    check("section General has autoMuteMic", data.get("autoMuteMic") == "true", str(data)[:200])
    check("section General has language", data.get("language") == "en-US", str(data)[:200])
    check("section General has localRecordingPath",
          data.get("localRecordingPath") == "/home/user/Documents/Zoom", str(data)[:200])

    data = run(sandbox, "config")
    check("config returns dict with >=4 sections",
          isinstance(data, dict) and len(data) >= 4, str(list(data.keys()) if isinstance(data, dict) else data))

    data = run(sandbox, "value General language")
    check("value General language = en-US", data.get("value") == "en-US", str(data))

    data = run(sandbox, "value General missingKey")
    check("value missing key returns error", "error" in data, str(data))

    data = run(sandbox, "section NoSuchSection")
    check("section missing returns error", "error" in data, str(data))


def test_check_config_positive(sandbox: Sandbox):
    print("\n=== check-config (positive) ===")

    cases = [
        ("General autoMuteMic true", True),
        ("General language en-US", True),
        ("Audio MicrophoneLevel 80", True),
        ("Video HDVideo false", True),
        ("General Theme 2", True),
    ]
    for args, expected in cases:
        data = run(sandbox, f"check-config {args}")
        check(f"check-config {args}", data.get("match") is expected, str(data)[:120])


def test_check_config_negative(sandbox: Sandbox):
    print("\n=== check-config (negative) ===")

    cases = [
        ("General autoMuteMic false", False),
        ("General language de-DE", False),
    ]
    for args, expected in cases:
        data = run(sandbox, f"check-config {args}")
        check(f"check-config {args}", data.get("match") is expected, str(data)[:120])

    data = run(sandbox, "check-config NoSection key value")
    check("check-config missing section match=false",
          data.get("match") is False, str(data)[:100])
    check("check-config missing section has error",
          "error" in data, str(data)[:100])

    data = run(sandbox, "check-config General noSuchKey value")
    check("check-config missing key match=false",
          data.get("match") is False, str(data)[:100])


def test_check_bool(sandbox: Sandbox):
    print("\n=== check-bool ===")

    cases = [
        ("General autoMuteMic true", True),
        ("General autoMuteMic false", False),
        ("Video HDVideo false", True),
        ("Video HDVideo true", False),
        # enableMirrorEffect=1 should match "true"
        ("General enableMirrorEffect true", True),
        ("General enableMirrorEffect false", False),
    ]
    for args, expected in cases:
        data = run(sandbox, f"check-bool {args}")
        check(f"check-bool {args}", data.get("match") is expected, str(data)[:120])


def test_check_language(sandbox: Sandbox):
    print("\n=== check-language ===")
    data = run(sandbox, "check-language en-US")
    check("check-language en-US match=true", data.get("match") is True, str(data)[:100])
    data = run(sandbox, "check-language de-DE")
    check("check-language de-DE match=false", data.get("match") is False, str(data)[:100])


def test_check_recording_path(sandbox: Sandbox):
    print("\n=== check-recording-path ===")
    data = run(sandbox, f"check-recording-path {RECORDING_DIR}")
    check("recording-path match=true", data.get("match") is True, str(data)[:100])
    data = run(sandbox, "check-recording-path /tmp/other")
    check("recording-path match=false", data.get("match") is False, str(data)[:100])
    data = run(sandbox, "recording-path")
    check("recording-path value correct", data.get("value") == RECORDING_DIR, str(data)[:120])


def test_data_logs_recordings(sandbox: Sandbox):
    print("\n=== data/logs/recordings ===")

    data = run(sandbox, "data-files")
    check("data-files returns list", isinstance(data, list), str(type(data)))
    if isinstance(data, list):
        names = [f.get("name") for f in data if isinstance(f, dict)]
        check("data-files has history.txt", "history.txt" in names, str(names))
        check("data-files has cache.json", "cache.json" in names, str(names))

    data = run(sandbox, "log-files")
    check("log-files returns list", isinstance(data, list), str(type(data)))
    if isinstance(data, list):
        names = [f.get("name") for f in data if isinstance(f, dict)]
        check("log-files has zoom.log", "zoom.log" in names, str(names))

    data = run(sandbox, "list-recordings")
    check("list-recordings returns list", isinstance(data, list), str(type(data)))
    if isinstance(data, list):
        check("list-recordings has >= 2 files", len(data) >= 2, str(data)[:200])

    data = run(sandbox, "recent-meeting-ids")
    check("recent-meeting-ids returns list", isinstance(data, list), str(type(data)))
    if isinstance(data, list):
        check("recent-meeting-ids has 1234567890",
              "1234567890" in data, str(data))
        check("recent-meeting-ids has 9876543210",
              "9876543210" in data, str(data))

    data = run(sandbox, "check-recording-count 2")
    check("check-recording-count 2 match=true", data.get("match") is True, str(data)[:120])

    data = run(sandbox, "check-recording-count 5")
    check("check-recording-count 5 match=false", data.get("match") is False, str(data)[:120])


def test_check_config_contains(sandbox: Sandbox):
    print("\n=== check-config-contains ===")
    data = run(sandbox, "check-config-contains General localRecordingPath Documents")
    check("contains Documents match=true", data.get("match") is True, str(data)[:120])
    data = run(sandbox, "check-config-contains General localRecordingPath elsewhere")
    check("contains elsewhere match=false", data.get("match") is False, str(data)[:120])


def test_file_dir_exists(sandbox: Sandbox):
    print("\n=== check-file-exists / check-directory-exists ===")
    data = run(sandbox, f"check-file-exists {EXISTING_FILE}")
    check("existing file exists=true", data.get("exists") is True, str(data)[:100])
    data = run(sandbox, "check-file-exists /nonexistent/xyz.txt")
    check("missing file exists=false", data.get("exists") is False, str(data)[:100])
    data = run(sandbox, f"check-directory-exists {RECORDING_DIR}")
    check("dir exists=true", data.get("exists") is True, str(data)[:100])
    # Using file path as dir
    data = run(sandbox, f"check-directory-exists {EXISTING_FILE}")
    check("file-as-dir exists=false", data.get("exists") is False, str(data)[:100])


def test_check_section_exists(sandbox: Sandbox):
    print("\n=== check-section-exists ===")
    data = run(sandbox, "check-section-exists General")
    check("General exists=true", data.get("exists") is True, str(data)[:100])
    data = run(sandbox, "check-section-exists NoSuchSection")
    check("NoSuchSection exists=false", data.get("exists") is False, str(data)[:100])


def test_json_validity_sweep(sandbox: Sandbox):
    print("\n=== JSON validity sweep ===")

    no_arg_cmds = [
        "config-path", "sections", "config",
        "data-files", "log-files", "recording-path",
        "list-recordings", "recent-meeting-ids",
        "check-config-exists",
    ]
    for cmd in no_arg_cmds:
        r = run_raw(sandbox, cmd)
        check(f"{cmd} valid JSON", is_valid_json(r.stdout), r.stdout[:100])

    arg_cmds = [
        ("section", "General"),
        ("value", "General language"),
        ("check-section-exists", "General"),
        ("check-config", "General language en-US"),
        ("check-config-contains", "General localRecordingPath Documents"),
        ("check-bool", "General autoMuteMic true"),
        ("check-language", "en-US"),
        ("check-recording-path", RECORDING_DIR),
        ("check-file-exists", "/tmp"),
        ("check-directory-exists", "/tmp"),
        ("check-recording-count", "1"),
    ]
    for cmd, arg in arg_cmds:
        r = run_raw(sandbox, f"{cmd} {arg}")
        check(f"{cmd} valid JSON", is_valid_json(r.stdout), r.stdout[:100])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed

    print("=" * 60)
    print("Zoom Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # === Phase 1: tests that run BEFORE the fixture exists ===
        # Make sure config does not exist yet
        sandbox.commands.run("rm -f /home/user/.config/zoomus.conf")
        sandbox.commands.run("rm -rf /home/user/.zoom")

        test_help(sandbox)
        test_errors_no_config(sandbox)
        test_errors_bad_args(sandbox)

        # === Phase 2: write fixtures ===
        print("\nWriting Zoom fixtures...")
        sandbox.commands.run("mkdir -p /home/user/.config")
        sandbox.commands.run(f"mkdir -p {DATA_DIR}")
        sandbox.commands.run(f"mkdir -p {LOGS_DIR}")
        sandbox.commands.run(f"mkdir -p {RECORDING_DIR}")

        sandbox.files.write(CONFIG_PATH, FIXTURE_ZOOMUS_CONF)
        sandbox.files.write(f"{DATA_DIR}/history.txt", FIXTURE_HISTORY_TXT)
        sandbox.files.write(f"{DATA_DIR}/cache.json", FIXTURE_CACHE_JSON)
        sandbox.files.write(f"{LOGS_DIR}/zoom.log", FIXTURE_LOG)
        sandbox.files.write(f"{RECORDING_DIR}/2026-04-01 meeting.mp4", "")
        sandbox.files.write(f"{RECORDING_DIR}/2026-04-05 meeting.mp4", "")
        sandbox.files.write(EXISTING_FILE, "hello\n")

        r = sandbox.commands.run(f"ls -la {RECORDING_DIR}", timeout=5)
        print(f"  Recording dir: {r.stdout.strip()}")
        r = sandbox.commands.run(f"ls -la {DATA_DIR}", timeout=5)
        print(f"  Data dir: {r.stdout.strip()}")

        # === Phase 3: tests that depend on fixtures ===
        test_config_introspection(sandbox)
        test_check_config_positive(sandbox)
        test_check_config_negative(sandbox)
        test_check_bool(sandbox)
        test_check_language(sandbox)
        test_check_recording_path(sandbox)
        test_data_logs_recordings(sandbox)
        test_check_config_contains(sandbox)
        test_file_dir_exists(sandbox)
        test_check_section_exists(sandbox)
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
