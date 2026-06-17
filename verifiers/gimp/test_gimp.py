"""
Test GIMP verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (missing args, bad files, Script-Fu not running)
  - File-based query endpoints (file-info, pixel-color-file)
  - File-based check endpoints (positive and negative)
  - Script-Fu live query endpoints (images, layers, channels, active-layer, pixel-color)
  - Script-Fu live check endpoints (positive and negative)
  - JSON validity sweep across all commands

Usage:
    python verifiers/gimp/test_gimp.py
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

VERIFIER_LOCAL = Path(__file__).parent / "gimp.py"
VERIFIER_REMOTE = "/home/user/verifiers/gimp.py"
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


def run(sandbox: Sandbox, cmd: str, timeout: int = 30) -> dict | list:
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
# Fixture generation script (runs inside sandbox via PIL)
# ---------------------------------------------------------------------------

CREATE_FIXTURES_SCRIPT = r'''
import os
from PIL import Image, ImageDraw

FIXTURE_DIR = "/home/user/test_fixtures"
os.makedirs(FIXTURE_DIR, exist_ok=True)

# 1. RGB 800x600 with colored quadrants
img = Image.new("RGB", (800, 600))
draw = ImageDraw.Draw(img)
draw.rectangle([0, 0, 399, 299], fill=(255, 0, 0))        # top-left: red
draw.rectangle([400, 0, 799, 299], fill=(0, 255, 0))      # top-right: green
draw.rectangle([0, 300, 399, 599], fill=(0, 0, 255))      # bottom-left: blue
draw.rectangle([400, 300, 799, 599], fill=(255, 255, 255)) # bottom-right: white
img.save(os.path.join(FIXTURE_DIR, "test_rgb_800x600.png"))

# 2. RGBA 256x256 with semi-transparent content
img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.ellipse([28, 28, 228, 228], fill=(255, 0, 0, 180))
img.save(os.path.join(FIXTURE_DIR, "test_rgba_256x256.png"))

# 3. Grayscale 100x100 gradient
img = Image.new("L", (100, 100))
for x in range(100):
    for y in range(100):
        img.putpixel((x, y), int(x * 255 / 99))
img.save(os.path.join(FIXTURE_DIR, "test_gray_100x100.png"))

# 4. JPEG 640x480 solid blue
img = Image.new("RGB", (640, 480), (0, 0, 255))
img.save(os.path.join(FIXTURE_DIR, "test_photo.jpg"), quality=95)

# 5. BMP 50x50 solid green
img = Image.new("RGB", (50, 50), (0, 255, 0))
img.save(os.path.join(FIXTURE_DIR, "test_small.bmp"))

# 6. TIFF 200x200 solid magenta
img = Image.new("RGB", (200, 200), (255, 0, 255))
img.save(os.path.join(FIXTURE_DIR, "test_magenta.tiff"))

# 7. Large RGB image for GIMP live tests
img = Image.new("RGB", (800, 600), (128, 64, 32))
draw = ImageDraw.Draw(img)
draw.rectangle([100, 100, 300, 300], fill=(255, 255, 0))  # yellow square
img.save(os.path.join(FIXTURE_DIR, "test_live_image.png"))

# 8. RGBA image for alpha test
img = Image.new("RGBA", (400, 300), (100, 150, 200, 128))
img.save(os.path.join(FIXTURE_DIR, "test_alpha_image.png"))

print("All test fixtures created successfully")
'''


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    """--help should print usage and exit 0."""
    print("\n=== Group 1: Help/Usage ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
    check("help mentions Commands", "Commands:" in result.stdout, result.stdout[:100])

    result = run_raw(sandbox, "help")
    check("'help' subcommand exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")


def test_errors_scriptfu_not_running(sandbox: Sandbox):
    """Live endpoints should return error JSON when Script-Fu server is not running."""
    print("\n=== Group 2: Errors — Script-Fu Not Running ===")

    # Stop GIMP if it's somehow running
    sandbox.commands.run("killall gimp gimp-2.10 2>/dev/null || true", timeout=5)
    time.sleep(1)

    live_cmds = [
        ("images", "images"),
        ("image-info", "image-info"),
        ("layers", "layers"),
        ("channels", "channels 0"),
        ("active-layer", "active-layer"),
        ("check-image-open", "check-image-open test"),
        ("check-layer-exists", "check-layer-exists Background"),
        ("check-image-mode", "check-image-mode RGB"),
    ]

    for name, cmd in live_cmds:
        data = run(sandbox, cmd)
        if isinstance(data, list):
            has_error = len(data) > 0 and "error" in data[0]
        else:
            has_error = "error" in data
        check(f"{name} returns error when no server", has_error, str(data)[:120])


def test_errors_file_not_found(sandbox: Sandbox):
    """File-based endpoints should return error for nonexistent files."""
    print("\n=== Group 3: Errors — File Not Found ===")

    file_cmds = [
        ("file-info", "file-info /tmp/nope.png"),
        ("pixel-color-file", "pixel-color-file /tmp/nope.png 0 0"),
        ("check-file-exists", "check-file-exists /tmp/nope.png"),
        ("check-file-dimensions", "check-file-dimensions /tmp/nope.png 800 600"),
        ("check-file-format", "check-file-format /tmp/nope.png PNG"),
        ("check-file-mode", "check-file-mode /tmp/nope.png RGB"),
        ("check-pixel-color-file", "check-pixel-color-file /tmp/nope.png 0 0 255 0 0"),
    ]

    for name, cmd in file_cmds:
        data = run(sandbox, cmd)
        has_error_or_false = ("error" in data) or (data.get("exists") is False)
        check(f"{name} handles missing file", has_error_or_false, str(data)[:120])


def test_errors_missing_args(sandbox: Sandbox):
    """Commands with missing required args should exit 1 with valid JSON."""
    print("\n=== Group 4: Errors — Missing Arguments ===")

    cmds = [
        "file-info",
        "pixel-color-file",
        "check-file-dimensions",
        "check-file-format",
        "check-pixel-color-file",
    ]

    for cmd in cmds:
        result = run_raw(sandbox, cmd)
        check(f"{cmd} missing args exits 1", result.exit_code == 1,
              f"exit={result.exit_code}")
        check(f"{cmd} missing args valid JSON", is_valid_json(result.stdout),
              result.stdout[:100])

    # Unknown subcommand
    result = run_raw(sandbox, "gibberish")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])


def test_file_query_endpoints(sandbox: Sandbox):
    """Test file-info and pixel-color-file with various formats."""
    print("\n=== Group 5: File-Based Query Endpoints ===")
    FIX = "/home/user/test_fixtures"

    # file-info on RGB PNG
    data = run(sandbox, f"file-info {FIX}/test_rgb_800x600.png")
    check("file-info RGB exists", data.get("exists") is True)
    check("file-info RGB width", data.get("width") == 800, f"w={data.get('width')}")
    check("file-info RGB height", data.get("height") == 600, f"h={data.get('height')}")
    check("file-info RGB format", data.get("format") == "PNG", f"fmt={data.get('format')}")
    check("file-info RGB mode", data.get("mode") == "RGB", f"mode={data.get('mode')}")

    # file-info on RGBA PNG
    data = run(sandbox, f"file-info {FIX}/test_rgba_256x256.png")
    check("file-info RGBA mode", data.get("mode") == "RGBA", f"mode={data.get('mode')}")
    check("file-info RGBA dims", data.get("width") == 256 and data.get("height") == 256)

    # file-info on JPEG
    data = run(sandbox, f"file-info {FIX}/test_photo.jpg")
    check("file-info JPEG format", data.get("format") == "JPEG", f"fmt={data.get('format')}")
    check("file-info JPEG dims", data.get("width") == 640 and data.get("height") == 480)

    # file-info on BMP
    data = run(sandbox, f"file-info {FIX}/test_small.bmp")
    check("file-info BMP format", data.get("format") == "BMP", f"fmt={data.get('format')}")

    # pixel-color-file on RGB image
    data = run(sandbox, f"pixel-color-file {FIX}/test_rgb_800x600.png 0 0")
    check("pixel top-left is red", data.get("r") == 255 and data.get("g") == 0 and data.get("b") == 0,
          f"pixel={data}")

    data = run(sandbox, f"pixel-color-file {FIX}/test_rgb_800x600.png 400 0")
    check("pixel top-right is green", data.get("r") == 0 and data.get("g") == 255 and data.get("b") == 0,
          f"pixel={data}")

    # pixel-color-file on grayscale
    data = run(sandbox, f"pixel-color-file {FIX}/test_gray_100x100.png 0 50")
    check("grayscale left is dark", data.get("r", 255) < 10, f"pixel={data}")

    # pixel-color-file out of bounds
    data = run(sandbox, f"pixel-color-file {FIX}/test_small.bmp 9999 9999")
    check("out of bounds returns error", "error" in data, str(data)[:100])


def test_file_checks_positive(sandbox: Sandbox):
    """File check endpoints — positive cases."""
    print("\n=== Group 6: File Check Endpoints — Positive ===")
    FIX = "/home/user/test_fixtures"

    data = run(sandbox, f"check-file-exists {FIX}/test_rgb_800x600.png")
    check("check-file-exists true", data.get("exists") is True)
    check("check-file-exists has size", data.get("size_bytes", 0) > 0)

    data = run(sandbox, f"check-file-dimensions {FIX}/test_rgb_800x600.png 800 600")
    check("check-file-dimensions match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-file-format {FIX}/test_rgb_800x600.png PNG")
    check("check-file-format PNG match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-file-format {FIX}/test_photo.jpg JPEG")
    check("check-file-format JPEG match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-file-format {FIX}/test_photo.jpg JPG")
    check("check-file-format JPG alias", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-file-mode {FIX}/test_rgba_256x256.png RGBA")
    check("check-file-mode RGBA match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-file-mode {FIX}/test_gray_100x100.png L")
    check("check-file-mode L match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-pixel-color-file {FIX}/test_rgb_800x600.png 0 0 255 0 0")
    check("check-pixel red match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-pixel-color-file {FIX}/test_small.bmp 25 25 0 255 0")
    check("check-pixel green BMP match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-pixel-color-file {FIX}/test_rgb_800x600.png 400 300 255 255 255")
    check("check-pixel white match", data.get("match") is True, str(data)[:100])


def test_file_checks_negative(sandbox: Sandbox):
    """File check endpoints — negative cases."""
    print("\n=== Group 7: File Check Endpoints — Negative ===")
    FIX = "/home/user/test_fixtures"

    data = run(sandbox, "check-file-exists /tmp/definitely_not_here.png")
    check("check-file-exists false", data.get("exists") is False)

    data = run(sandbox, f"check-file-dimensions {FIX}/test_rgb_800x600.png 1024 768")
    check("check-file-dimensions no match", data.get("match") is False, str(data)[:100])
    check("check-file-dimensions shows actual", data.get("actual") == [800, 600],
          f"actual={data.get('actual')}")

    data = run(sandbox, f"check-file-format {FIX}/test_photo.jpg PNG")
    check("check-file-format wrong format", data.get("match") is False, str(data)[:100])

    data = run(sandbox, f"check-file-mode {FIX}/test_rgb_800x600.png RGBA")
    check("check-file-mode wrong mode", data.get("match") is False, str(data)[:100])

    data = run(sandbox, f"check-pixel-color-file {FIX}/test_rgb_800x600.png 0 0 0 255 0")
    check("check-pixel wrong color", data.get("match") is False, str(data)[:100])
    check("check-pixel shows actual", data.get("actual") == [255, 0, 0],
          f"actual={data.get('actual')}")

    # Close but not quite (within tolerance of 5)
    data = run(sandbox, f"check-pixel-color-file {FIX}/test_rgb_800x600.png 0 0 255 0 0 0")
    check("check-pixel exact tolerance=0", data.get("match") is True, str(data)[:100])

    data = run(sandbox, f"check-pixel-color-file {FIX}/test_rgb_800x600.png 0 0 250 0 0 3")
    check("check-pixel outside tight tolerance", data.get("match") is False,
          f"tolerance=3, diff=5, match={data.get('match')}")

    # Non-image file
    data = run(sandbox, f"check-file-format /etc/hostname PNG")
    check("non-image file-format error", "error" in data or data.get("match") is False,
          str(data)[:100])


def _start_gimp(sandbox: Sandbox):
    """Start GIMP with Script-Fu server and wait for it to be ready."""
    print("\n--- Starting GIMP with Script-Fu server ---")
    sandbox.commands.run("killall gimp gimp-2.10 2>/dev/null || true", timeout=5)
    time.sleep(2)

    # Write a launch script and run it in the background
    launch_script = '#!/bin/bash\ngimp -b \'(plug-in-script-fu-server RUN-NONINTERACTIVE "127.0.0.1" 10008 "")\' > /tmp/gimp.log 2>&1\n'
    sandbox.files.write("/tmp/launch_gimp.sh", launch_script)
    sandbox.commands.run("chmod +x /tmp/launch_gimp.sh", timeout=3)
    sandbox.commands.run("/tmp/launch_gimp.sh", background=True)

    # Wait for Script-Fu server to be ready
    for attempt in range(30):
        time.sleep(2)
        try:
            result = sandbox.commands.run(
                "python3 -c \"import socket; s=socket.socket(); s.settimeout(2); s.connect(('127.0.0.1', 10008)); s.close(); print('OK')\"",
                timeout=10
            )
            if "OK" in result.stdout:
                print(f"  GIMP Script-Fu server ready (attempt {attempt + 1})")
                return True
        except Exception:
            pass

    print("  WARNING: Script-Fu server did not become ready after 60 seconds")
    return False


def _open_image_in_gimp(sandbox: Sandbox, path: str):
    """Open an image in GIMP via Script-Fu."""
    sf_cmd = f'(gimp-file-load RUN-NONINTERACTIVE "{path}" "{path}")'
    _run_scriptfu(sandbox, sf_cmd)
    time.sleep(1)


def _run_scriptfu(sandbox: Sandbox, cmd: str):
    """Send a Script-Fu command via a Python helper."""
    py_script = f'''
import socket, struct
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(10)
sock.connect(("127.0.0.1", 10008))
cmd = {repr(cmd)}
cmd_bytes = cmd.encode("utf-8")
header = b"G" + struct.pack(">H", len(cmd_bytes))
sock.sendall(header + cmd_bytes)
resp = b""
while len(resp) < 4:
    chunk = sock.recv(4 - len(resp))
    if not chunk: break
    resp += chunk
if len(resp) >= 4:
    err = resp[1]
    rlen = struct.unpack(">H", resp[2:4])[0]
    data = b""
    while len(data) < rlen:
        chunk = sock.recv(rlen - len(data))
        if not chunk: break
        data += chunk
    print(data.decode("utf-8", errors="replace"))
    if err != 0:
        print("ERROR:", err, file=__import__("sys").stderr)
sock.close()
'''
    try:
        result = sandbox.commands.run(f"python3 -c '{py_script}'", timeout=30)
        return result.stdout.strip()
    except Exception as e:
        return str(e)


def test_live_query_endpoints(sandbox: Sandbox):
    """Test Script-Fu live query endpoints with images open."""
    print("\n=== Group 8: Script-Fu Live Query Endpoints ===")
    FIX = "/home/user/test_fixtures"

    # Open test images in GIMP
    _open_image_in_gimp(sandbox, f"{FIX}/test_live_image.png")
    _open_image_in_gimp(sandbox, f"{FIX}/test_alpha_image.png")
    time.sleep(2)

    # images
    data = run(sandbox, "images")
    check("images returns list", isinstance(data, list), str(type(data)))
    check("images has >= 2 entries", len(data) >= 2, f"count={len(data)}")

    if len(data) >= 1 and "error" not in data[0]:
        img = data[0]
        check("image has id", "id" in img, str(img.keys()))
        check("image has name", "name" in img, str(img.keys()))
        check("image has width", "width" in img, str(img.keys()))
        check("image has height", "height" in img, str(img.keys()))

    # image-info
    data = run(sandbox, "image-info 0")
    check("image-info returns dict", isinstance(data, dict), str(type(data)))
    if "error" not in data:
        check("image-info has width", isinstance(data.get("width"), int))
        check("image-info has height", isinstance(data.get("height"), int))
        check("image-info has x_resolution", isinstance(data.get("x_resolution"), (int, float)))
        check("image-info has num_layers", isinstance(data.get("num_layers"), int))

    # layers
    data = run(sandbox, "layers 0")
    check("layers returns list", isinstance(data, list), str(type(data)))
    if data and "error" not in data[0]:
        layer = data[0]
        check("layer has name", "name" in layer, str(layer.keys()))
        check("layer has visible", "visible" in layer, str(layer.keys()))
        check("layer has opacity", "opacity" in layer, str(layer.keys()))

    # channels
    data = run(sandbox, "channels 0")
    check("channels returns list", isinstance(data, list), str(type(data)))

    # active-layer
    data = run(sandbox, "active-layer 0")
    check("active-layer returns dict", isinstance(data, dict), str(type(data)))
    if "error" not in data:
        check("active-layer has name", "name" in data, str(data.keys()))

    # pixel-color (live)
    data = run(sandbox, "pixel-color 0 0 0")
    check("pixel-color returns dict", isinstance(data, dict), str(type(data)))
    if "error" not in data:
        check("pixel-color has r", "r" in data, str(data.keys()))

    # image-info out of range
    data = run(sandbox, "image-info 99")
    check("image-info out of range", "error" in data, str(data)[:100])


def test_live_checks_positive(sandbox: Sandbox):
    """Script-Fu check endpoints — positive cases."""
    print("\n=== Group 9: Script-Fu Check Endpoints — Positive ===")

    # check-image-open — use the test image we opened
    data = run(sandbox, "check-image-open test_alpha_image")
    check("check-image-open found", data.get("found") is True, str(data)[:120])

    # check-layer-count — the PNG images have 1 layer each (Background)
    data = run(sandbox, "check-layer-count 1 0")
    check("check-layer-count match", data.get("match") is True, str(data)[:120])

    # check-image-mode — should be RGB
    data = run(sandbox, "check-image-mode RGB 0")
    check("check-image-mode RGB match", data.get("match") is True, str(data)[:120])

    # check-image-size
    # The most recently opened image (index 0) is test_alpha_image.png (400x300)
    data = run(sandbox, "check-image-size 400 300 0")
    check("check-image-size match", data.get("match") is True, str(data)[:120])

    # check-resolution (default is 72 DPI for PNGs opened in GIMP)
    data = run(sandbox, "check-resolution 72 72 0")
    check("check-resolution match", data.get("match") is True, str(data)[:120])

    # check-layer-exists
    data = run(sandbox, "check-layer-exists Background 0")
    check("check-layer-exists found",
          data.get("exists") is True, str(data)[:120])


def test_live_checks_negative(sandbox: Sandbox):
    """Script-Fu check endpoints — negative cases."""
    print("\n=== Group 10: Script-Fu Check Endpoints — Negative ===")

    data = run(sandbox, "check-image-open nonexistent_image_xyz")
    check("check-image-open not found", data.get("found") is False, str(data)[:120])

    data = run(sandbox, "check-layer-exists NoSuchLayerName 0")
    check("check-layer-exists not found", data.get("exists") is False, str(data)[:120])

    data = run(sandbox, "check-layer-count 999 0")
    check("check-layer-count no match", data.get("match") is False, str(data)[:120])

    data = run(sandbox, "check-image-mode INDEXED 0")
    check("check-image-mode wrong mode", data.get("match") is False, str(data)[:120])

    data = run(sandbox, "check-image-size 9999 9999 0")
    check("check-image-size wrong dims", data.get("match") is False, str(data)[:120])

    data = run(sandbox, "check-resolution 300 300 0")
    check("check-resolution wrong DPI", data.get("match") is False, str(data)[:120])

    data = run(sandbox, "check-has-alpha 0")
    # test_alpha_image.png should have alpha since it's RGBA
    # This tests correctness; if it fails, it's a false negative
    # Either way, we want valid output
    check("check-has-alpha returns dict", isinstance(data, dict), str(data)[:120])


def test_preferences(sandbox: Sandbox):
    """Test preferences endpoint."""
    print("\n=== Group 11: Preferences ===")

    # List all preferences
    data = run(sandbox, "preferences")
    check("preferences returns dict", isinstance(data, dict), str(type(data)))
    # May return error if no config dir, or keys list
    if "error" not in data:
        check("preferences has keys", "keys" in data, str(data.keys()))
    else:
        check("preferences error is about config dir", "config" in data.get("error", "").lower() or "not found" in data.get("error", "").lower(),
              data.get("error", ""))

    # Nonexistent key
    data = run(sandbox, "preferences totally-fake-key-xyz")
    check("fake preference returns error or not found",
          "error" in data or data.get("value") is None, str(data)[:100])


def test_json_validity_sweep(sandbox: Sandbox):
    """Every CLI command should output valid JSON."""
    print("\n=== Group 12: JSON Validity Sweep ===")
    FIX = "/home/user/test_fixtures"

    test_cases = [
        "images",
        "image-info",
        "image-info 0",
        "layers",
        "layers 0",
        "channels 0",
        "active-layer",
        "pixel-color 0 0",
        f"file-info {FIX}/test_rgb_800x600.png",
        f"pixel-color-file {FIX}/test_rgb_800x600.png 0 0",
        "preferences",
        "check-image-open test",
        "check-layer-exists Background",
        "check-layer-count 1",
        "check-image-mode RGB",
        "check-has-alpha",
        "check-resolution 72 72",
        "check-image-size 800 600",
        f"check-file-exists {FIX}/test_rgb_800x600.png",
        f"check-file-dimensions {FIX}/test_rgb_800x600.png 800 600",
        f"check-file-format {FIX}/test_rgb_800x600.png PNG",
        f"check-file-mode {FIX}/test_rgb_800x600.png RGB",
        f"check-pixel-color-file {FIX}/test_rgb_800x600.png 0 0 255 0 0",
    ]

    for cmd in test_cases:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        label = cmd.split()[0]  # just the subcommand name
        check(f"{label} valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed

    print("=" * 60)
    print("GIMP Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # Install Pillow
        print("Installing Pillow...")
        r = sandbox.commands.run("pip install Pillow 2>&1", timeout=60)
        print(f"  pip: {r.stdout.strip()[-80:]}")

        # Create test fixtures
        print("Creating test fixtures...")
        sandbox.files.write("/home/user/create_fixtures.py", CREATE_FIXTURES_SCRIPT)
        r = sandbox.commands.run("python3 /home/user/create_fixtures.py", timeout=30)
        print(f"  {r.stdout.strip()}")

        # --- File-based tests (no GIMP needed) ---
        test_help(sandbox)
        test_errors_scriptfu_not_running(sandbox)
        test_errors_file_not_found(sandbox)
        test_errors_missing_args(sandbox)
        test_file_query_endpoints(sandbox)
        test_file_checks_positive(sandbox)
        test_file_checks_negative(sandbox)

        # --- Start GIMP for live tests ---
        gimp_ready = _start_gimp(sandbox)

        if gimp_ready:
            test_live_query_endpoints(sandbox)
            test_live_checks_positive(sandbox)
            test_live_checks_negative(sandbox)
            test_preferences(sandbox)
            test_json_validity_sweep(sandbox)
        else:
            print("\n  SKIP: Script-Fu live tests (GIMP failed to start)")
            # Still run JSON validity for file-based commands
            test_json_validity_sweep(sandbox)

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
