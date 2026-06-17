"""
Test the RenderDoc verifier in a live E2B sandbox.

Covers:
  - Help / usage output
  - Error cases (unknown command, missing args)
  - UI.config query endpoints (positive + negative)
  - .rdc capture header parsing (positive + negative)
  - Directory listing / capture counting
  - File existence helpers
  - JSON validity sweep for all commands

Setup: writes a synthetic UI.config JSON and a handful of synthetic
.rdc / non-RDC files inside the sandbox. qrenderdoc is NOT launched.

Usage:
    python verifiers/renderdoc/test_renderdoc.py
"""

import json
import re
import struct
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "renderdoc.py"
VERIFIER_REMOTE = "/home/user/verifiers/renderdoc.py"
V = f"python3 {VERIFIER_REMOTE}"


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
# Fixture content
# ---------------------------------------------------------------------------

UI_CONFIG_DIR = "/home/user/.local/share/qrenderdoc"
CAPTURES_DIR = "/home/user/captures"

UI_CONFIG = {
    # Magic identifier required by qrenderdoc for validation.
    "rdocConfigData": 1,
    "Font_GlobalScale": 1.5,
    "Font_Family": "Noto Sans",
    "Font_MonoFamily": "Noto Mono",
    "Font_PreferMonospaced": False,
    "UIStyle": "Dark",
    "TextureViewer_ResetRange": True,
    "TextureViewer_PerTexSettings": True,
    "TextureViewer_PerTexYFlip": False,
    "EventBrowser_AddFake": False,
    "EventBrowser_ApplyColors": True,
    "Comments_ShowOnLoad": True,
    "AllowGlobalHook": False,
    "CheckUpdate_AllowChecks": False,
    "Analytics_TotalOptOut": True,
    "RecentCaptureFiles": [
        "/home/user/captures/triangle.rdc",
        "/home/user/captures/second.rdc",
    ],
    "RecentCaptureSettings": [
        "/home/user/captures/triangle.cap",
    ],
    "DefaultCaptureSaveDirectory": "/home/user/captures",
}


def build_rdc_bytes(prog_version: str = "v1.36 abcdef", total_size: int = 128) -> bytes:
    """Build a synthetic .rdc file with a valid header.

    Matches renderdoc/serialise/rdcfile.cpp FileHeader layout:
      magic (uint64 LE)     -- low 4 bytes = b"RDOC"
      version (uint32 LE)   -- 0x00000102
      headerLength (uint32) -- 32
      progVersion (char[16])
    Remaining bytes are zero padding so list-captures reports a realistic size.
    """
    magic_uint64 = int.from_bytes(b"RDOC" + b"\x00\x00\x00\x00", "little")
    header = struct.pack("<QII", magic_uint64, 0x00000102, 32)
    pv = prog_version.encode("ascii")[:16]
    pv = pv + b"\x00" * (16 - len(pv))
    header += pv
    assert len(header) == 32
    pad = b"\x00" * max(0, total_size - 32)
    return header + pad


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

CAP_PRESET = {
    "rdocCaptureSettings": 1,
    "settings": {
        "executable": "/usr/bin/glxgears",
        "workingDir": "/home/user",
        "commandLine": "--iters 100 --window",
        "environment": [
            {"name": "VK_LAYER_PATH", "value": "/tmp",
             "separator": "Platform", "mod": "Replace"},
            {"name": "RDOC_DEBUG", "value": "1",
             "separator": "Platform", "mod": "Append"},
        ],
        "options": {
            "APIValidation": True,
            "CaptureCallstacks": False,
            "CaptureAllCmdLists": True,
            "DebugOutputMute": False,
            "HookIntoChildren": True,
            "RefAllResources": False,
            "VerifyBufferAccess": False,
        },
        "autoStart": True,
        "queueFrameCap": 0,
        "numQueuedFrames": 0,
    },
}


def setup_mock_files(sandbox: Sandbox):
    print("Setting up mock files in sandbox ...")
    sandbox.commands.run(f"mkdir -p {UI_CONFIG_DIR}")
    sandbox.commands.run(f"mkdir -p {CAPTURES_DIR}")

    # Write UI.config
    sandbox.files.write(f"{UI_CONFIG_DIR}/UI.config", json.dumps(UI_CONFIG, indent=2))

    # Write captures
    sandbox.files.write(
        f"{CAPTURES_DIR}/triangle.rdc",
        build_rdc_bytes("v1.36 abcdef", total_size=128),
    )
    sandbox.files.write(
        f"{CAPTURES_DIR}/second.rdc",
        build_rdc_bytes("v1.36 123456", total_size=96),
    )
    # Wrong extension + wrong magic → excluded from list-captures
    sandbox.files.write(f"{CAPTURES_DIR}/corrupt.bin", b"\xff" * 64)
    # Too-short .rdc → matches extension, fails header parse
    sandbox.files.write(f"{CAPTURES_DIR}/tiny.rdc", b"RDOC")
    # Dummy .cap referenced by UI.config (existence-only fixture)
    sandbox.files.write(f"{CAPTURES_DIR}/triangle.cap", b"\x00" * 8)
    # Full .cap capture-settings JSON
    sandbox.files.write(f"{CAPTURES_DIR}/preset.cap", json.dumps(CAP_PRESET, indent=2))
    print("  Mock files created.")


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    print("\n=== Help ===")
    r = run_raw(sandbox, "--help")
    check("help exits 0", r.exit_code == 0, f"got {r.exit_code}")
    check("help mentions RenderDoc", "RenderDoc" in r.stdout, r.stdout[:100])


def test_unknown_command(sandbox: Sandbox):
    print("\n=== Errors (unknown command) ===")
    r = run_raw(sandbox, "wat-is-this")
    check("unknown cmd exits 1", r.exit_code == 1, f"got {r.exit_code}")
    check("unknown cmd valid JSON", is_valid_json(r.stdout), r.stdout[:120])


def test_missing_args(sandbox: Sandbox):
    print("\n=== Errors (missing args) ===")
    cmds = [
        "check-setting",
        "check-setting-exists",
        "check-theme",
        "check-font-scale",
        "check-recent-capture",
        "rdc-header",
        "check-rdc-valid",
        "check-rdc-version",
        "list-captures",
        "check-capture-count",
        "check-file-exists",
        "file-info",
        "check-rdcmd-version",
        "check-rdcmd-plugin",
        "rdc-sections",
        "check-rdc-has-section",
        "rdc-thumb",
        "check-rdc-has-thumbnail",
        "rdc-convert-xml",
        "check-rdc-api",
        "check-rdc-min-chunks",
        "cap-parse",
        "check-cap-executable",
        "check-cap-working-dir",
        "check-cap-command-line",
        "check-cap-option",
        "check-cap-env",
    ]
    for c in cmds:
        r = run_raw(sandbox, c)
        check(f"{c} missing-arg exits 1", r.exit_code == 1, f"got {r.exit_code}")
        check(f"{c} missing-arg JSON", is_valid_json(r.stdout), r.stdout[:100])


def test_config_endpoints(sandbox: Sandbox):
    print("\n=== UI.config Queries ===")

    data = run(sandbox, "config")
    check("config is dict", isinstance(data, dict), str(type(data)))
    check("config has Font_GlobalScale", "Font_GlobalScale" in data, str(data)[:120])
    check("config has UIStyle", "UIStyle" in data, str(data)[:120])

    data = run(sandbox, "config Font_GlobalScale")
    check("config key returns value",
          isinstance(data, dict) and data.get("value") == 1.5, str(data)[:120])

    data = run(sandbox, "config DefinitelyNotAKey")
    check("missing config key returns error", "error" in data, str(data)[:120])

    data = run(sandbox, "config-keys")
    check("config-keys has count", isinstance(data, dict) and "count" in data, str(data)[:120])
    check("config-keys has >=8", data.get("count", 0) >= 8, f"got {data.get('count')}")

    data = run(sandbox, "theme")
    check("theme is Dark", data.get("theme") == "Dark", str(data)[:120])

    data = run(sandbox, "font-scale")
    check("font-scale is 1.5",
          isinstance(data.get("scale"), (int, float)) and abs(data["scale"] - 1.5) < 1e-6,
          str(data)[:120])

    data = run(sandbox, "recent-captures")
    check("recent-captures count>=2", data.get("count", 0) >= 2, str(data)[:120])
    check("recent-captures has triangle",
          any("triangle.rdc" in f for f in data.get("files", [])),
          str(data)[:120])

    data = run(sandbox, "recent-settings")
    check("recent-settings count>=1", data.get("count", 0) >= 1, str(data)[:120])


def test_check_positive(sandbox: Sandbox):
    print("\n=== Checks (positive) ===")

    d = run(sandbox, "check-setting Font_GlobalScale 1.5")
    check("check-setting float match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, 'check-setting UIStyle "\\"Dark\\""')
    check("check-setting string match",
          d.get("match") is True or d.get("actual") == "Dark",
          str(d)[:120])

    d = run(sandbox, "check-setting TextureViewer_ResetRange true")
    check("check-setting bool true match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, "check-setting EventBrowser_AddFake false")
    check("check-setting bool false match", d.get("match") is True, str(d)[:120])

    d = run(sandbox, "check-setting-exists Font_GlobalScale")
    check("check-setting-exists true", d.get("exists") is True, str(d)[:120])

    d = run(sandbox, "check-theme Dark")
    check("check-theme Dark true", d.get("match") is True, str(d)[:120])

    d = run(sandbox, "check-font-scale 1.5")
    check("check-font-scale 1.5 true", d.get("match") is True, str(d)[:120])

    d = run(sandbox, "check-recent-capture triangle.rdc")
    check("check-recent-capture found", d.get("found") is True, str(d)[:120])


def test_check_negative(sandbox: Sandbox):
    print("\n=== Checks (negative) ===")

    d = run(sandbox, "check-setting Font_GlobalScale 2.0")
    check("check-setting float wrong", d.get("match") is False, str(d)[:120])

    d = run(sandbox, "check-setting TextureViewer_ResetRange false")
    check("check-setting bool wrong", d.get("match") is False, str(d)[:120])

    d = run(sandbox, "check-setting-exists NothingHere")
    check("check-setting-exists false", d.get("exists") is False, str(d)[:120])

    d = run(sandbox, "check-theme Light")
    check("check-theme Light false", d.get("match") is False, str(d)[:120])

    d = run(sandbox, "check-font-scale 2.0")
    check("check-font-scale 2.0 false", d.get("match") is False, str(d)[:120])

    d = run(sandbox, "check-recent-capture xyz_not_here")
    check("check-recent-capture miss", d.get("found") is False, str(d)[:120])


def test_rdc_header(sandbox: Sandbox):
    print("\n=== RDC header parsing ===")

    d = run(sandbox, f"rdc-header {CAPTURES_DIR}/triangle.rdc")
    check("rdc-header valid", d.get("valid") is True, str(d)[:160])
    check("rdc-header magic RDOC", d.get("magic") == "RDOC", str(d)[:160])
    check("rdc-header serialise_version 258",
          d.get("serialise_version") == 258, str(d)[:160])
    check("rdc-header header_length 32",
          d.get("header_length") == 32, str(d)[:160])
    check("rdc-header prog_version has v1.",
          "v1." in (d.get("prog_version") or ""), str(d)[:160])

    d = run(sandbox, f"rdc-header {CAPTURES_DIR}/corrupt.bin")
    check("rdc-header corrupt error", "error" in d, str(d)[:160])

    d = run(sandbox, f"rdc-header {CAPTURES_DIR}/tiny.rdc")
    check("rdc-header tiny too-short error", "error" in d, str(d)[:160])

    d = run(sandbox, "rdc-header /nope/missing.rdc")
    check("rdc-header missing error", "error" in d, str(d)[:160])


def test_check_rdc_valid(sandbox: Sandbox):
    print("\n=== check-rdc-valid ===")

    d = run(sandbox, f"check-rdc-valid {CAPTURES_DIR}/triangle.rdc")
    check("check-rdc-valid positive", d.get("valid") is True, str(d)[:160])

    d = run(sandbox, f"check-rdc-valid {CAPTURES_DIR}/corrupt.bin")
    check("check-rdc-valid corrupt false", d.get("valid") is False, str(d)[:160])

    d = run(sandbox, f"check-rdc-valid {CAPTURES_DIR}/tiny.rdc")
    check("check-rdc-valid tiny false", d.get("valid") is False, str(d)[:160])

    d = run(sandbox, "check-rdc-valid /nope/missing.rdc")
    check("check-rdc-valid missing false", d.get("valid") is False, str(d)[:160])


def test_check_rdc_version(sandbox: Sandbox):
    print("\n=== check-rdc-version ===")

    d = run(sandbox, f"check-rdc-version {CAPTURES_DIR}/triangle.rdc 258")
    check("check-rdc-version 258 true", d.get("match") is True, str(d)[:160])

    d = run(sandbox, f"check-rdc-version {CAPTURES_DIR}/triangle.rdc 0x102")
    check("check-rdc-version hex 0x102 true", d.get("match") is True, str(d)[:160])

    d = run(sandbox, f"check-rdc-version {CAPTURES_DIR}/triangle.rdc 999")
    check("check-rdc-version 999 false", d.get("match") is False, str(d)[:160])

    d = run(sandbox, f"check-rdc-version {CAPTURES_DIR}/triangle.rdc notanumber")
    check("check-rdc-version bad arg false",
          d.get("match") is False and "error" in d, str(d)[:160])


def test_listing(sandbox: Sandbox):
    print("\n=== list-captures / check-capture-count ===")

    d = run(sandbox, f"list-captures {CAPTURES_DIR}")
    check("list-captures has 3 rdc",
          d.get("count") == 3, str(d)[:200])
    names = [c.get("name") for c in d.get("captures", [])]
    check("list-captures contains triangle.rdc", "triangle.rdc" in names, str(names))
    check("list-captures contains second.rdc", "second.rdc" in names, str(names))
    check("list-captures excludes corrupt.bin", "corrupt.bin" not in names, str(names))

    # Validity flags: triangle & second valid, tiny invalid
    valids = {c.get("name"): c.get("valid") for c in d.get("captures", [])}
    check("triangle.rdc valid=true", valids.get("triangle.rdc") is True, str(valids))
    check("second.rdc valid=true", valids.get("second.rdc") is True, str(valids))
    check("tiny.rdc valid=false", valids.get("tiny.rdc") is False, str(valids))

    d = run(sandbox, f"check-capture-count {CAPTURES_DIR} 3")
    check("check-capture-count 3 true", d.get("match") is True, str(d)[:160])

    d = run(sandbox, f"check-capture-count {CAPTURES_DIR} 99")
    check("check-capture-count 99 false", d.get("match") is False, str(d)[:160])

    d = run(sandbox, "check-capture-count /nope/nowhere 0")
    check("check-capture-count missing dir false",
          d.get("match") is False and "error" in d, str(d)[:160])

    d = run(sandbox, "list-captures /nope/nowhere")
    check("list-captures missing dir error", "error" in d, str(d)[:160])


def test_file_exists(sandbox: Sandbox):
    print("\n=== file-exists / file-info ===")

    d = run(sandbox, f"check-file-exists {CAPTURES_DIR}/triangle.rdc")
    check("file-exists true", d.get("exists") is True, str(d)[:120])
    check("file-exists is_file", d.get("is_file") is True, str(d)[:120])

    d = run(sandbox, f"check-file-exists {CAPTURES_DIR}")
    check("dir exists true", d.get("exists") is True, str(d)[:120])
    check("dir is_dir", d.get("is_dir") is True, str(d)[:120])

    d = run(sandbox, "check-file-exists /nope/definitely-not-here")
    check("missing file false", d.get("exists") is False, str(d)[:120])

    d = run(sandbox, f"file-info {CAPTURES_DIR}/triangle.rdc")
    check("file-info size>0", d.get("size", 0) > 0, str(d)[:120])
    check("file-info is_file true", d.get("is_file") is True, str(d)[:120])


def test_rdcmd_install(sandbox: Sandbox):
    print("\n=== renderdoccmd install metadata ===")

    d = run(sandbox, "rdcmd-available")
    check("rdcmd-available shape", isinstance(d, dict) and "available" in d, str(d)[:120])
    # Strong assertion: desktop-all-apps ships renderdoccmd at 1.36
    rdcmd_ok = bool(d.get("available"))
    check("rdcmd-available true", rdcmd_ok, str(d)[:200])

    d = run(sandbox, "rdcmd-version")
    check("rdcmd-version has apis list", isinstance(d.get("apis"), list), str(d)[:200])
    ver = d.get("version") or ""
    check("rdcmd-version parsed version 1.x",
          bool(re.match(r"1\.\d+", ver)), str(d)[:200])

    d = run(sandbox, "check-rdcmd-version 1.")
    check("check-rdcmd-version 1. true", d.get("match") is True, str(d)[:160])

    d = run(sandbox, "check-rdcmd-version 99.9")
    check("check-rdcmd-version 99.9 false", d.get("match") is False, str(d)[:160])

    d = run(sandbox, "rdcmd-plugins")
    check("rdcmd-plugins has count", isinstance(d, dict) and "count" in d, str(d)[:160])

    d = run(sandbox, "check-rdcmd-plugin spirv")
    # Accept either — install layout varies, we just need a valid shape
    check("check-rdcmd-plugin returns present bool",
          isinstance(d.get("present"), bool), str(d)[:160])

    d = run(sandbox, "vulkan-layer-status")
    check("vulkan-layer-status shape",
          isinstance(d, dict) and "registered" in d and isinstance(d.get("layer_files"), list),
          str(d)[:200])


def test_rdc_structured(sandbox: Sandbox):
    print("\n=== .rdc structured inspection (synthetic) ===")

    # Synthetic rdcs can't be decoded by renderdoccmd — every endpoint should
    # return a graceful error or a negative result, never crash.
    d = run(sandbox, f"rdc-sections {CAPTURES_DIR}/triangle.rdc")
    check("rdc-sections returns dict", isinstance(d, dict), str(d)[:160])

    d = run(sandbox, f"rdc-convert-xml {CAPTURES_DIR}/triangle.rdc")
    check("rdc-convert-xml synthetic → error or empty summary",
          ("error" in d) or d.get("chunks", 0) == 0, str(d)[:200])

    d = run(sandbox, f"check-rdc-api {CAPTURES_DIR}/triangle.rdc Vulkan")
    check("check-rdc-api synthetic false", d.get("match") is False, str(d)[:160])

    d = run(sandbox, f"check-rdc-min-chunks {CAPTURES_DIR}/triangle.rdc 1")
    check("check-rdc-min-chunks synthetic false", d.get("match") is False, str(d)[:160])

    d = run(sandbox, f"check-rdc-has-thumbnail {CAPTURES_DIR}/triangle.rdc")
    check("check-rdc-has-thumbnail synthetic false",
          d.get("has_thumbnail") is False, str(d)[:200])

    d = run(sandbox, f"check-rdc-has-section {CAPTURES_DIR}/triangle.rdc Thumbnail")
    check("check-rdc-has-section synthetic shape",
          isinstance(d, dict) and "present" in d, str(d)[:200])

    d = run(sandbox, f"rdc-thumb {CAPTURES_DIR}/triangle.rdc /tmp/_tst_thumb.png")
    check("rdc-thumb synthetic returns dict",
          isinstance(d, dict), str(d)[:200])

    # Missing file paths
    d = run(sandbox, "rdc-sections /nope/missing.rdc")
    check("rdc-sections missing file error", "error" in d, str(d)[:120])

    d = run(sandbox, "rdc-convert-xml /nope/missing.rdc")
    check("rdc-convert-xml missing file error", "error" in d, str(d)[:120])

    d = run(sandbox, "rdc-thumb /nope/missing.rdc /tmp/x.png")
    check("rdc-thumb missing file error", "error" in d, str(d)[:120])


def test_cap_parse(sandbox: Sandbox):
    print("\n=== .cap capture-settings ===")

    d = run(sandbox, f"cap-parse {CAPTURES_DIR}/preset.cap")
    check("cap-parse executable", d.get("executable") == "/usr/bin/glxgears", str(d)[:200])
    check("cap-parse workingDir", d.get("workingDir") == "/home/user", str(d)[:200])
    check("cap-parse commandLine has --iters",
          "--iters" in (d.get("commandLine") or ""), str(d)[:200])
    check("cap-parse options has APIValidation",
          isinstance(d.get("options"), dict) and d["options"].get("APIValidation") is True,
          str(d)[:200])
    check("cap-parse env has 2 entries",
          isinstance(d.get("environment"), list) and len(d["environment"]) == 2,
          str(d)[:200])

    d = run(sandbox, f"check-cap-executable {CAPTURES_DIR}/preset.cap /usr/bin/glxgears")
    check("check-cap-executable true", d.get("match") is True, str(d)[:160])

    d = run(sandbox, f"check-cap-executable {CAPTURES_DIR}/preset.cap /bin/wrong")
    check("check-cap-executable false", d.get("match") is False, str(d)[:160])

    d = run(sandbox, f"check-cap-working-dir {CAPTURES_DIR}/preset.cap /home/user")
    check("check-cap-working-dir true", d.get("match") is True, str(d)[:160])

    d = run(sandbox, f"check-cap-command-line {CAPTURES_DIR}/preset.cap --iters")
    check("check-cap-command-line substring true", d.get("match") is True, str(d)[:160])

    d = run(sandbox, f"check-cap-command-line {CAPTURES_DIR}/preset.cap no-such-arg")
    check("check-cap-command-line substring false", d.get("match") is False, str(d)[:160])

    d = run(sandbox, f"check-cap-option {CAPTURES_DIR}/preset.cap APIValidation true")
    check("check-cap-option bool true", d.get("match") is True, str(d)[:160])

    d = run(sandbox, f"check-cap-option {CAPTURES_DIR}/preset.cap APIValidation false")
    check("check-cap-option bool mismatch", d.get("match") is False, str(d)[:160])

    d = run(sandbox, f"check-cap-option {CAPTURES_DIR}/preset.cap CaptureCallstacks false")
    check("check-cap-option bool-false true", d.get("match") is True, str(d)[:160])

    d = run(sandbox, f"check-cap-option {CAPTURES_DIR}/preset.cap NotARealOption true")
    check("check-cap-option missing key false", d.get("match") is False, str(d)[:160])

    d = run(sandbox, f"check-cap-env {CAPTURES_DIR}/preset.cap VK_LAYER_PATH")
    check("check-cap-env present", d.get("present") is True, str(d)[:160])

    d = run(sandbox, f"check-cap-env {CAPTURES_DIR}/preset.cap NOT_SET")
    check("check-cap-env missing false", d.get("present") is False, str(d)[:160])

    d = run(sandbox, "cap-parse /nope/missing.cap")
    check("cap-parse missing error", "error" in d, str(d)[:160])


def test_json_sweep(sandbox: Sandbox):
    print("\n=== JSON validity sweep ===")
    sweep = [
        "config",
        "config Font_GlobalScale",
        "config-keys",
        "check-setting Font_GlobalScale 1.5",
        "check-setting-exists Font_GlobalScale",
        "theme",
        "check-theme Dark",
        "font-scale",
        "check-font-scale 1.5",
        "recent-captures",
        "check-recent-capture triangle.rdc",
        "recent-settings",
        f"rdc-header {CAPTURES_DIR}/triangle.rdc",
        f"check-rdc-valid {CAPTURES_DIR}/triangle.rdc",
        f"check-rdc-version {CAPTURES_DIR}/triangle.rdc 258",
        f"list-captures {CAPTURES_DIR}",
        f"check-capture-count {CAPTURES_DIR} 3",
        f"check-file-exists {CAPTURES_DIR}/triangle.rdc",
        f"file-info {CAPTURES_DIR}/triangle.rdc",
        "rdcmd-available",
        "rdcmd-version",
        "check-rdcmd-version 1.",
        "rdcmd-plugins",
        "check-rdcmd-plugin spirv",
        "vulkan-layer-status",
        f"rdc-sections {CAPTURES_DIR}/triangle.rdc",
        f"check-rdc-has-section {CAPTURES_DIR}/triangle.rdc Thumbnail",
        f"rdc-thumb {CAPTURES_DIR}/triangle.rdc /tmp/_sweep.png",
        f"check-rdc-has-thumbnail {CAPTURES_DIR}/triangle.rdc",
        f"rdc-convert-xml {CAPTURES_DIR}/triangle.rdc",
        f"check-rdc-api {CAPTURES_DIR}/triangle.rdc Vulkan",
        f"check-rdc-min-chunks {CAPTURES_DIR}/triangle.rdc 1",
        f"cap-parse {CAPTURES_DIR}/preset.cap",
        f"check-cap-executable {CAPTURES_DIR}/preset.cap /usr/bin/glxgears",
        f"check-cap-working-dir {CAPTURES_DIR}/preset.cap /home/user",
        f"check-cap-command-line {CAPTURES_DIR}/preset.cap --iters",
        f"check-cap-option {CAPTURES_DIR}/preset.cap APIValidation true",
        f"check-cap-env {CAPTURES_DIR}/preset.cap VK_LAYER_PATH",
        "wat-bad-command",
    ]
    for c in sweep:
        r = run_raw(sandbox, c)
        ok = is_valid_json(r.stdout)
        check(f"JSON: {c}", ok, f"exit={r.exit_code} stdout={r.stdout[:120]}" if not ok else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("RenderDoc Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps ...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        setup_mock_files(sandbox)

        test_help(sandbox)
        test_unknown_command(sandbox)
        test_missing_args(sandbox)
        test_config_endpoints(sandbox)
        test_check_positive(sandbox)
        test_check_negative(sandbox)
        test_rdc_header(sandbox)
        test_check_rdc_valid(sandbox)
        test_check_rdc_version(sandbox)
        test_listing(sandbox)
        test_file_exists(sandbox)
        test_rdcmd_install(sandbox)
        test_rdc_structured(sandbox)
        test_cap_parse(sandbox)
        test_json_sweep(sandbox)
    except Exception as e:
        print("FATAL:", e)
        traceback.print_exc()
    finally:
        try:
            sandbox.kill()
        except Exception:
            pass

    print("\n" + "=" * 60)
    print(f"PASSED: {passed}")
    print(f"FAILED: {failed}")
    print("=" * 60)
    if failed:
        print("\nFailures:")
        for e in errors:
            print(" -", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
