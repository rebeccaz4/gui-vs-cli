"""
Test Krita verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (bad file, missing args)
  - Query endpoints (doc-info, metadata, layers, layer-info, color-profile, preview)
  - Check endpoints (positive and negative cases)

The test creates synthetic .kra files (ZIP archives with appropriate XML and PNG)
inside the sandbox, then runs verifier commands against them.

Usage:
    python verifiers/krita/test_krita.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "krita.py"
VERIFIER_REMOTE = "/home/user/verifiers/krita.py"
V = f"python3 {VERIFIER_REMOTE}"

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
# Synthetic .kra file creation (runs inside sandbox)
# ---------------------------------------------------------------------------

CREATE_KRA_SCRIPT = r'''
import zipfile
import io
import struct
import zlib
import os
import uuid

def make_minimal_png(width, height, color=(255, 0, 0, 255), grayscale=False):
    """Create a minimal valid PNG for mergedimage.png preview."""
    def chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    header = b"\x89PNG\r\n\x1a\n"
    if grayscale:
        ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 4, 0, 0, 0)
        gray = color[0] if len(color) >= 1 else 200
        alpha = color[3] if len(color) >= 4 else 255
        pixel = bytes([gray, alpha])
    else:
        ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        pixel = bytes(color[:4])
    ihdr = chunk(b"IHDR", ihdr_data)

    row = b"\x00" + pixel * width
    raw_rows = row * height

    compressed = zlib.compress(raw_rows)
    idat = chunk(b"IDAT", compressed)
    iend = chunk(b"IEND", b"")

    return header + ihdr + idat + iend

def make_default_pixel(color_space, color=(255, 255, 255, 255)):
    """Create .defaultpixel content (raw bytes in Krita's internal format)."""
    if color_space == "GRAYA":
        return bytes([color[0], color[3] if len(color) >= 4 else 255])
    else:
        # Krita stores RGBA as BGRA internally
        return bytes([color[2], color[1], color[0], color[3] if len(color) >= 4 else 255])

def make_layer_data(pixel_size=4):
    """Empty layer tile data in Krita's native format."""
    return f"VERSION 2\nTILEWIDTH 64\nTILEHEIGHT 64\nPIXELSIZE {pixel_size}\nDATA 0\n".encode("ascii")

def create_test_kra(path, width=800, height=600, layers=None, title="Test Painting",
                    author="Test Author", color_space="RGBA", x_res=300, y_res=300):
    """Create a synthetic .kra file that Krita can open natively."""
    if layers is None:
        layers = [
            {"name": "Background", "nodetype": "paintlayer", "visible": "1", "opacity": "255"},
            {"name": "Layer 1", "nodetype": "paintlayer", "visible": "1", "opacity": "200"},
        ]

    is_gray = color_space == "GRAYA"
    pixel_size = 2 if is_gray else 4
    img_name = "test"

    # Build maindoc.xml matching real Krita format
    layer_xml_parts = []
    layer_filenames = []
    for i, layer in enumerate(layers):
        filename = f"layer{i + 2}"
        layer_uuid = "{" + str(uuid.uuid4()) + "}"
        layer_filenames.append((filename, layer.get("name", f"Layer {i}")))

        locked = "1" if layer.get("name") == "Background" else "0"
        selected = "true" if i == 0 else "false"

        attrs = " ".join(f'{k}="{v}"' for k, v in layer.items())
        attrs += f' filename="{filename}" uuid="{layer_uuid}"'
        attrs += f' compositeop="normal" colorspacename="{color_space}" collapsed="0"'
        attrs += f' intimeline="1" x="0" y="0" colorlabel="0" onionskin="0"'
        attrs += f' locked="{locked}" selected="{selected}" channelflags="" channellockflags=""'
        layer_xml_parts.append(f"   <layer {attrs}/>")
    layers_xml = "\n".join(layer_xml_parts)

    maindoc = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE DOC PUBLIC '-//KDE//DTD krita 2.0//EN' 'http://www.calligra.org/DTD/krita-2.0.dtd'>
<DOC xmlns="http://www.calligra.org/DTD/krita" kritaVersion="5.0.2" editor="Krita" syntaxVersion="2.0">
 <IMAGE x-res="{x_res}" y-res="{y_res}" width="{width}" name="{img_name}" colorspacename="{color_space}" mime="application/x-kra" height="{height}" description="" profile="sRGB-elle-V2-srgbtrc.icc">
  <layers>
{layers_xml}
  </layers>
  <ProjectionBackgroundColor ColorData="AAAAAA=="/>
  <GlobalAssistantsColor SimpleColorData="176,176,176,255"/>
  <Palettes/>
  <resources/>
  <animation>
   <framerate value="24" type="value"/>
   <range to="100" from="0" type="timerange"/>
   <currentTime value="0" type="value"/>
  </animation>
 </IMAGE>
</DOC>"""

    # Build documentinfo.xml
    documentinfo = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE document-info PUBLIC '-//KDE//DTD document-info 1.1//EN' 'http://www.calligra.org/DTD/document-info-1.1.dtd'>
<document-info xmlns="http://www.calligra.org/DTD/document-info">
 <about>
  <title>{title}</title>
  <description></description>
  <subject>test</subject>
  <abstract><![CDATA[A test painting for verifier testing]]></abstract>
  <keyword></keyword>
  <initial-creator>Unknown</initial-creator>
  <editing-cycles>3</editing-cycles>
  <editing-time></editing-time>
  <date>2024-06-15T10:30:00</date>
  <creation-date>2024-06-15T10:30:00</creation-date>
  <language></language>
  <license></license>
 </about>
 <author>
  <full-name>{author}</full-name>
  <creator-first-name></creator-first-name>
  <creator-last-name></creator-last-name>
  <initial></initial>
  <author-title></author-title>
  <position></position>
  <company></company>
 </author>
</document-info>"""

    # Create preview PNG (thumbnail)
    preview_scale = min(256 / max(width, height), 1.0)
    preview_w = max(1, int(width * preview_scale))
    preview_h = max(1, int(height * preview_scale))

    png_data = make_minimal_png(width, height, grayscale=is_gray)
    preview_data = make_minimal_png(preview_w, preview_h, grayscale=is_gray)

    # Animation XML
    anim_xml = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE animation-metadata PUBLIC '-//KDE//DTD krita 1.1//EN' 'http://www.calligra.org/DTD/krita-1.1.dtd'>
<animation-metadata xmlns="http://www.calligra.org/DTD/krita">
 <framerate value="24" type="value"/>
 <range to="100" from="0" type="timerange"/>
 <currentTime value="0" type="value"/>
 <export-settings>
  <sequenceFilePath value="" type="value"/>
  <sequenceBaseName value="" type="value"/>
  <sequenceInitialFrameNumber value="-1" type="value"/>
 </export-settings>
</animation-metadata>
"""

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/x-krita", compress_type=zipfile.ZIP_STORED)
        zf.writestr("maindoc.xml", maindoc)
        zf.writestr("documentinfo.xml", documentinfo)
        zf.writestr("preview.png", preview_data)
        # Layer data under {img_name}/layers/
        for filename, lname in layer_filenames:
            if lname == "Background":
                dpx = bytes([255, 255]) if is_gray else bytes([255, 255, 255, 255])
            else:
                dpx = bytes([0, 0]) if is_gray else bytes([0, 0, 0, 0])
            zf.writestr(f"{img_name}/layers/{filename}", make_layer_data(pixel_size))
            zf.writestr(f"{img_name}/layers/{filename}.defaultpixel", dpx)
        zf.writestr("mergedimage.png", png_data)
        zf.writestr(f"{img_name}/animation/index.xml", anim_xml)

# --- Create test files ---

# Standard test file
create_test_kra("/home/user/test_standard.kra",
                width=1920, height=1080,
                title="My Test Painting",
                author="Jane Artist")

# Single layer file
create_test_kra("/home/user/test_single_layer.kra",
                width=640, height=480,
                layers=[{"name": "OnlyLayer", "nodetype": "paintlayer", "visible": "1", "opacity": "255"}],
                title="Single Layer")

# Hidden layer file
create_test_kra("/home/user/test_hidden_layer.kra",
                width=800, height=600,
                layers=[
                    {"name": "Visible", "nodetype": "paintlayer", "visible": "1", "opacity": "255"},
                    {"name": "Hidden", "nodetype": "paintlayer", "visible": "0", "opacity": "128"},
                ])

# Grayscale file
create_test_kra("/home/user/test_grayscale.kra",
                width=500, height=500,
                color_space="GRAYA",
                x_res=150, y_res=150)

# No metadata file (minimal)
create_test_kra("/home/user/test_no_metadata.kra",
                width=100, height=100,
                layers=[{"name": "Background", "nodetype": "paintlayer", "visible": "1", "opacity": "255"}],
                title="", author="",
                x_res=72, y_res=72)

print("All test .kra files created successfully")
'''


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    """--help should print usage and exit 0."""
    print("\n=== Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
    check("help mentions commands", "Commands:" in result.stdout, result.stdout[:100])
    check("help mentions .kra", ".kra" in result.stdout.lower() or "krita" in result.stdout.lower(),
          result.stdout[:100])


def test_errors(sandbox: Sandbox):
    """Error cases should return valid JSON, not crash."""
    print("\n=== Errors ===")

    # Unknown command
    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Missing required arg
    result = run_raw(sandbox, "doc-info")
    check("missing arg exits 1", result.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Non-existent file
    data = run(sandbox, "doc-info /home/user/nonexistent.kra")
    check("nonexistent file returns error", "error" in data, str(data)[:100])

    # Invalid file (not a ZIP)
    sandbox.commands.run("echo 'not a zip' > /home/user/invalid.kra")
    data = run(sandbox, "doc-info /home/user/invalid.kra")
    check("invalid kra returns error", "error" in data, str(data)[:100])


def test_doc_info(sandbox: Sandbox):
    """Test doc-info query endpoint."""
    print("\n=== doc-info ===")

    data = run(sandbox, "doc-info /home/user/test_standard.kra")
    check("doc-info returns dict", isinstance(data, dict), str(type(data)))
    check("doc-info has width", data.get("width") == 1920, f"width={data.get('width')}")
    check("doc-info has height", data.get("height") == 1080, f"height={data.get('height')}")
    check("doc-info has colorspace", data.get("colorspacename") == "RGBA",
          f"cs={data.get('colorspacename')}")
    check("doc-info has x_res", data.get("x_res") == 300, f"x_res={data.get('x_res')}")

    # Grayscale file
    data = run(sandbox, "doc-info /home/user/test_grayscale.kra")
    check("grayscale colorspace", data.get("colorspacename") == "GRAYA",
          f"cs={data.get('colorspacename')}")
    check("grayscale resolution", data.get("x_res") == 150, f"x_res={data.get('x_res')}")


def test_metadata(sandbox: Sandbox):
    """Test metadata query endpoint."""
    print("\n=== metadata ===")

    data = run(sandbox, "metadata /home/user/test_standard.kra")
    check("metadata returns dict", isinstance(data, dict), str(type(data)))
    check("metadata has title", data.get("title") == "My Test Painting",
          f"title={data.get('title')}")
    check("metadata has author", data.get("author") == "Jane Artist",
          f"author={data.get('author')}")
    check("metadata has description", "description" in data, str(data.keys()))
    check("metadata has creation_date", "creation_date" in data, str(data.keys()))

    # No metadata file
    data = run(sandbox, "metadata /home/user/test_no_metadata.kra")
    check("no metadata returns dict", isinstance(data, dict), str(type(data)))
    # Should return empty dict (no documentinfo.xml) or error
    check("no metadata has error or empty", "error" in data or len(data) == 0,
          str(data)[:100])


def test_layers(sandbox: Sandbox):
    """Test layers query endpoint."""
    print("\n=== layers ===")

    data = run(sandbox, "layers /home/user/test_standard.kra")
    check("layers returns list", isinstance(data, list), str(type(data)))
    check("layers has 2 entries", len(data) == 2, f"got {len(data)}")
    if len(data) >= 2:
        check("first layer is Background", data[0].get("name") == "Background",
              f"name={data[0].get('name')}")
        check("second layer is Layer 1", data[1].get("name") == "Layer 1",
              f"name={data[1].get('name')}")
        check("layer has visibility", isinstance(data[0].get("visible"), bool),
              f"visible={data[0].get('visible')}")
        check("layer has opacity", isinstance(data[0].get("opacity"), int),
              f"opacity={data[0].get('opacity')}")

    # Single layer
    data = run(sandbox, "layers /home/user/test_single_layer.kra")
    check("single layer count", len(data) == 1, f"got {len(data)}")


def test_layer_info(sandbox: Sandbox):
    """Test layer-info query endpoint."""
    print("\n=== layer-info ===")

    data = run(sandbox, "layer-info /home/user/test_standard.kra Background")
    check("layer-info returns dict", isinstance(data, dict), str(type(data)))
    check("layer-info has name", data.get("name") == "Background", f"name={data.get('name')}")
    check("layer-info has opacity", data.get("opacity") == 255, f"opacity={data.get('opacity')}")

    # Non-existent layer
    data = run(sandbox, "layer-info /home/user/test_standard.kra NonExistent")
    check("missing layer returns error", "error" in data, str(data)[:100])
    check("missing layer lists available", "available_layers" in data, str(data.keys()))


def test_color_profile(sandbox: Sandbox):
    """Test color-profile query endpoint."""
    print("\n=== color-profile ===")

    data = run(sandbox, "color-profile /home/user/test_standard.kra")
    check("color-profile returns dict", isinstance(data, dict), str(type(data)))
    check("color-profile has colorspacename", data.get("colorspacename") == "RGBA",
          f"cs={data.get('colorspacename')}")
    check("color-profile has profile_name", "profile_name" in data, str(data.keys()))


def test_preview(sandbox: Sandbox):
    """Test preview query endpoint."""
    print("\n=== preview ===")

    data = run(sandbox, "preview /home/user/test_standard.kra")
    check("preview returns dict", isinstance(data, dict), str(type(data)))
    check("preview exists", data.get("exists") is True, f"exists={data.get('exists')}")
    # With PIL available, should have width/height
    if "width" in data:
        check("preview width", data.get("width") == 1920, f"width={data.get('width')}")
        check("preview height", data.get("height") == 1080, f"height={data.get('height')}")

    # No preview file
    data = run(sandbox, "preview /home/user/test_no_metadata.kra")
    check("no preview exists=false", data.get("exists") is False, f"exists={data.get('exists')}")


def test_checks_positive(sandbox: Sandbox):
    """Check endpoints — positive cases (should return true/match)."""
    print("\n=== Checks (positive) ===")

    # check-file-exists
    data = run(sandbox, "check-file-exists /home/user/test_standard.kra")
    check("check-file-exists true", data.get("exists") is True, str(data)[:100])
    check("check-file-exists has size", "size_bytes" in data, str(data.keys()))

    # check-image-size
    data = run(sandbox, "check-image-size /home/user/test_standard.kra 1920 1080")
    check("check-image-size match=true", data.get("match") is True, str(data)[:100])

    # check-layer-exists
    data = run(sandbox, "check-layer-exists /home/user/test_standard.kra Background")
    check("check-layer-exists true", data.get("exists") is True, str(data)[:100])

    # check-layer-count
    data = run(sandbox, "check-layer-count /home/user/test_standard.kra 2")
    check("check-layer-count match=true", data.get("match") is True, str(data)[:100])

    # check-layer-visible
    data = run(sandbox, "check-layer-visible /home/user/test_standard.kra Background")
    check("check-layer-visible true", data.get("visible") is True, str(data)[:100])

    # check-color-space
    data = run(sandbox, "check-color-space /home/user/test_standard.kra RGBA")
    check("check-color-space match=true", data.get("match") is True, str(data)[:100])

    # check-has-metadata
    data = run(sandbox, "check-has-metadata /home/user/test_standard.kra title")
    check("check-has-metadata title exists", data.get("exists") is True, str(data)[:100])
    check("check-has-metadata title value", data.get("value") == "My Test Painting",
          f"value={data.get('value')}")

    data = run(sandbox, "check-has-metadata /home/user/test_standard.kra author")
    check("check-has-metadata author exists", data.get("exists") is True, str(data)[:100])

    # check-resolution
    data = run(sandbox, "check-resolution /home/user/test_standard.kra 300")
    check("check-resolution match=true", data.get("match") is True, str(data)[:100])


def test_checks_negative(sandbox: Sandbox):
    """Check endpoints — negative cases (should return false/no match)."""
    print("\n=== Checks (negative) ===")

    # check-file-exists for missing file
    data = run(sandbox, "check-file-exists /home/user/nonexistent_painting.kra")
    check("check-file-exists false", data.get("exists") is False, str(data)[:100])

    # check-image-size wrong dimensions
    data = run(sandbox, "check-image-size /home/user/test_standard.kra 640 480")
    check("check-image-size match=false", data.get("match") is False, str(data)[:100])
    check("check-image-size has actual", data.get("actual") == [1920, 1080],
          f"actual={data.get('actual')}")

    # check-layer-exists for missing layer
    data = run(sandbox, "check-layer-exists /home/user/test_standard.kra NonExistentLayer")
    check("check-layer-exists false", data.get("exists") is False, str(data)[:100])
    check("check-layer-exists lists available", "available_layers" in data, str(data.keys()))

    # check-layer-count wrong count
    data = run(sandbox, "check-layer-count /home/user/test_standard.kra 5")
    check("check-layer-count match=false", data.get("match") is False, str(data)[:100])
    check("check-layer-count has actual", data.get("actual") == 2, f"actual={data.get('actual')}")

    # check-layer-visible on hidden layer
    data = run(sandbox, "check-layer-visible /home/user/test_hidden_layer.kra Hidden")
    check("check-layer-visible false", data.get("visible") is False, str(data)[:100])

    # check-color-space wrong space
    data = run(sandbox, "check-color-space /home/user/test_standard.kra GRAYA")
    check("check-color-space match=false", data.get("match") is False, str(data)[:100])

    # check-has-metadata missing key
    data = run(sandbox, "check-has-metadata /home/user/test_no_metadata.kra title")
    check("check-has-metadata false or error",
          data.get("exists") is False or "error" in data, str(data)[:100])

    # check-resolution wrong dpi
    data = run(sandbox, "check-resolution /home/user/test_standard.kra 72")
    check("check-resolution match=false", data.get("match") is False, str(data)[:100])


def test_all_commands_return_json(sandbox: Sandbox):
    """Every CLI command should output valid JSON (not crash with a traceback)."""
    print("\n=== JSON validity (all commands) ===")

    KRA = "/home/user/test_standard.kra"

    test_cases = [
        ("doc-info", KRA),
        ("metadata", KRA),
        ("layers", KRA),
        ("layer-info", f"{KRA} Background"),
        ("color-profile", KRA),
        ("preview", KRA),
        ("check-file-exists", KRA),
        ("check-image-size", f"{KRA} 800 600"),
        ("check-layer-exists", f"{KRA} Background"),
        ("check-layer-count", f"{KRA} 2"),
        ("check-layer-visible", f"{KRA} Background"),
        ("check-color-space", f"{KRA} RGBA"),
        ("check-has-metadata", f"{KRA} title"),
        ("check-resolution", f"{KRA} 300"),
    ]

    for cmd, arg in test_cases:
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
    print("Krita Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # Install Pillow for preview inspection
        print("Installing Pillow...")
        r = sandbox.commands.run("pip install Pillow 2>&1", timeout=60)
        print(f"  pip: {r.stdout.strip()[-80:]}")

        # Create synthetic test .kra files
        print("Creating test .kra files in sandbox...")
        sandbox.files.write("/home/user/create_test_kra.py", CREATE_KRA_SCRIPT)
        r = sandbox.commands.run("python3 /home/user/create_test_kra.py", timeout=120)
        print(f"  {r.stdout.strip()}")

        # --- Run tests ---
        test_help(sandbox)
        test_errors(sandbox)
        test_doc_info(sandbox)
        test_metadata(sandbox)
        test_layers(sandbox)
        test_layer_info(sandbox)
        test_color_profile(sandbox)
        test_preview(sandbox)
        test_checks_positive(sandbox)
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
