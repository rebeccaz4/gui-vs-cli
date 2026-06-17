"""
Test darktable verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (missing DB, bad args, unknown command)
  - SQLite query endpoints (library-images, image-info, tags, image-tags,
    styles, presets, collections)
  - XMP parsing endpoints (xmp-history, xmp-rating)
  - Export info endpoint
  - All check-* endpoints (positive and negative cases)
  - JSON validity for all commands

Usage:
    python verifiers/darktable/test_darktable.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "darktable.py"
VERIFIER_REMOTE = "/home/user/verifiers/darktable.py"
V = f"python3 {VERIFIER_REMOTE}"

CONFIG_DIR = "/home/user/.config/darktable"

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
# Sandbox setup: create test databases, XMP files, and images
# ---------------------------------------------------------------------------

SETUP_SCRIPT = (
    "import sqlite3, os\n"
    "CONFIG_DIR = os.path.expanduser('~/.config/darktable')\n"
    "os.makedirs(CONFIG_DIR, exist_ok=True)\n"
    "\n"
    "# --- library.db ---\n"
    "lib_path = os.path.join(CONFIG_DIR, 'library.db')\n"
    "conn = sqlite3.connect(lib_path)\n"
    "c = conn.cursor()\n"
    "\n"
    "c.execute('CREATE TABLE IF NOT EXISTS film_rolls (id INTEGER PRIMARY KEY, folder TEXT NOT NULL)')\n"
    "c.execute('CREATE TABLE IF NOT EXISTS images (id INTEGER PRIMARY KEY, film_id INTEGER, filename TEXT NOT NULL, datetime_taken TEXT, width INTEGER DEFAULT 0, height INTEGER DEFAULT 0, flags INTEGER DEFAULT 0, version INTEGER DEFAULT 0, output_width INTEGER DEFAULT 0, output_height INTEGER DEFAULT 0, longitude REAL, latitude REAL, altitude REAL, exposure REAL, aperture REAL, iso REAL, focal_length REAL, maker TEXT, model TEXT, lens TEXT, FOREIGN KEY (film_id) REFERENCES film_rolls(id))')\n"
    "c.execute('CREATE TABLE IF NOT EXISTS tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)')\n"
    "c.execute('CREATE TABLE IF NOT EXISTS tagged_images (imgid INTEGER, tagid INTEGER, PRIMARY KEY (imgid, tagid))')\n"
    "\n"
    "c.execute(\"INSERT INTO film_rolls (id, folder) VALUES (1, '/home/user/photos')\")\n"
    "c.execute(\"INSERT INTO film_rolls (id, folder) VALUES (2, '/home/user/vacation')\")\n"
    "\n"
    "c.execute(\"INSERT INTO images (id, film_id, filename, datetime_taken, width, height, flags, maker, model, iso, aperture, exposure, focal_length) VALUES (1, 1, 'sunset.CR2', '2025-06-15 18:30:00', 6000, 4000, 4, 'Canon', 'EOS R5', 100, 2.8, 0.004, 50.0)\")\n"
    "c.execute(\"INSERT INTO images (id, film_id, filename, datetime_taken, width, height, flags, maker, model, iso) VALUES (2, 1, 'portrait.NEF', '2025-07-01 14:00:00', 8256, 5504, 3, 'Nikon', 'Z8', 400)\")\n"
    "c.execute(\"INSERT INTO images (id, film_id, filename, datetime_taken, width, height, flags) VALUES (3, 2, 'beach.ARW', '2025-08-10 12:00:00', 7008, 4672, 5)\")\n"
    "\n"
    "c.execute(\"INSERT INTO tags (id, name) VALUES (1, 'landscape')\")\n"
    "c.execute(\"INSERT INTO tags (id, name) VALUES (2, 'sunset')\")\n"
    "c.execute(\"INSERT INTO tags (id, name) VALUES (3, 'portrait')\")\n"
    "c.execute(\"INSERT INTO tags (id, name) VALUES (4, 'vacation')\")\n"
    "\n"
    "c.execute('INSERT INTO tagged_images (imgid, tagid) VALUES (1, 1)')\n"
    "c.execute('INSERT INTO tagged_images (imgid, tagid) VALUES (1, 2)')\n"
    "c.execute('INSERT INTO tagged_images (imgid, tagid) VALUES (2, 3)')\n"
    "c.execute('INSERT INTO tagged_images (imgid, tagid) VALUES (3, 1)')\n"
    "c.execute('INSERT INTO tagged_images (imgid, tagid) VALUES (3, 4)')\n"
    "\n"
    "conn.commit()\n"
    "conn.close()\n"
    "\n"
    "# --- data.db ---\n"
    "data_path = os.path.join(CONFIG_DIR, 'data.db')\n"
    "conn = sqlite3.connect(data_path)\n"
    "c = conn.cursor()\n"
    "c.execute('CREATE TABLE IF NOT EXISTS styles (id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT)')\n"
    "c.execute('CREATE TABLE IF NOT EXISTS presets (name TEXT, operation TEXT, op_version INTEGER, enabled INTEGER DEFAULT 1, description TEXT)')\n"
    "\n"
    "c.execute(\"INSERT INTO styles (id, name, description) VALUES (1, 'B&W Film', 'Classic black and white film look')\")\n"
    "c.execute(\"INSERT INTO styles (id, name, description) VALUES (2, 'Cinematic Teal', 'Teal and orange cinema grade')\")\n"
    "c.execute(\"INSERT INTO presets (name, operation, op_version, enabled, description) VALUES ('My Exposure', 'exposure', 7, 1, 'Default exposure boost')\")\n"
    "c.execute(\"INSERT INTO presets (name, operation, op_version, enabled, description) VALUES ('Sharp Portrait', 'sharpen', 1, 1, 'Portrait sharpening')\")\n"
    "\n"
    "conn.commit()\n"
    "conn.close()\n"
    "\n"
    "# --- XMP sidecar files ---\n"
    "os.makedirs('/home/user/photos', exist_ok=True)\n"
    "\n"
    "xmp_content = ('<?xml version=\"1.0\" encoding=\"UTF-8\"?>\\n'\n"
    "'<x:xmpmeta xmlns:x=\"adobe:ns:meta/\" x:xmptk=\"darktable\">\\n'\n"
    "'  <rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">\\n'\n"
    "'    <rdf:Description\\n'\n"
    "'        xmlns:xmp=\"http://ns.adobe.com/xap/1.0/\"\\n'\n"
    "'        xmlns:darktable=\"http://darktable.sf.net/\"\\n'\n"
    "'        xmlns:dc=\"http://purl.org/dc/elements/1.1/\"\\n'\n"
    "'        xmlns:exif=\"http://ns.adobe.com/exif/1.0/\"\\n'\n"
    "'        xmp:Rating=\"4\">\\n'\n"
    "'      <darktable:history_operation>\\n'\n"
    "'        <rdf:Seq>\\n'\n"
    "'          <rdf:li>exposure</rdf:li>\\n'\n"
    "'          <rdf:li>colorbalancergb</rdf:li>\\n'\n"
    "'          <rdf:li>sharpen</rdf:li>\\n'\n"
    "'          <rdf:li>exposure</rdf:li>\\n'\n"
    "'        </rdf:Seq>\\n'\n"
    "'      </darktable:history_operation>\\n'\n"
    "'      <darktable:history_enabled>\\n'\n"
    "'        <rdf:Seq>\\n'\n"
    "'          <rdf:li>1</rdf:li>\\n'\n"
    "'          <rdf:li>1</rdf:li>\\n'\n"
    "'          <rdf:li>0</rdf:li>\\n'\n"
    "'          <rdf:li>1</rdf:li>\\n'\n"
    "'        </rdf:Seq>\\n'\n"
    "'      </darktable:history_enabled>\\n'\n"
    "'      <darktable:history_params>\\n'\n"
    "'        <rdf:Seq>\\n'\n"
    "'          <rdf:li>AAAA</rdf:li>\\n'\n"
    "'          <rdf:li>BBBB</rdf:li>\\n'\n"
    "'          <rdf:li>CCCC</rdf:li>\\n'\n"
    "'          <rdf:li>DDDD</rdf:li>\\n'\n"
    "'        </rdf:Seq>\\n'\n"
    "'      </darktable:history_params>\\n'\n"
    "'      <darktable:history_modversion>\\n'\n"
    "'        <rdf:Seq>\\n'\n"
    "'          <rdf:li>7</rdf:li>\\n'\n"
    "'          <rdf:li>4</rdf:li>\\n'\n"
    "'          <rdf:li>1</rdf:li>\\n'\n"
    "'          <rdf:li>7</rdf:li>\\n'\n"
    "'        </rdf:Seq>\\n'\n"
    "'      </darktable:history_modversion>\\n'\n"
    "'    </rdf:Description>\\n'\n"
    "'  </rdf:RDF>\\n'\n"
    "'</x:xmpmeta>\\n')\n"
    "\n"
    "with open('/home/user/photos/sunset.CR2.xmp', 'w') as f:\n"
    "    f.write(xmp_content)\n"
    "\n"
    "xmp_minimal = ('<?xml version=\"1.0\" encoding=\"UTF-8\"?>\\n'\n"
    "'<x:xmpmeta xmlns:x=\"adobe:ns:meta/\" x:xmptk=\"darktable\">\\n'\n"
    "'  <rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">\\n'\n"
    "'    <rdf:Description\\n'\n"
    "'        xmlns:xmp=\"http://ns.adobe.com/xap/1.0/\"\\n'\n"
    "'        xmlns:darktable=\"http://darktable.sf.net/\"\\n'\n"
    "'        xmp:Rating=\"2\">\\n'\n"
    "'    </rdf:Description>\\n'\n"
    "'  </rdf:RDF>\\n'\n"
    "'</x:xmpmeta>\\n')\n"
    "\n"
    "with open('/home/user/photos/portrait.NEF.xmp', 'w') as f:\n"
    "    f.write(xmp_minimal)\n"
    "\n"
    "# --- Test image file (valid JPEG via PIL) ---\n"
    "try:\n"
    "    from PIL import Image\n"
    "    img = Image.new('RGB', (800, 600), color=(100, 150, 200))\n"
    "    img.save('/home/user/photos/exported.jpg', 'JPEG')\n"
    "    img.save('/home/user/photos/exported.png', 'PNG')\n"
    "    print('Test images created with PIL')\n"
    "except ImportError:\n"
    "    with open('/home/user/photos/exported.jpg', 'wb') as f:\n"
    "        f.write(b'\\xff\\xd8\\xff\\xe0' + b'\\x00' * 100)\n"
    "    print('PIL not available, created placeholder files')\n"
    "\n"
    "print('Setup complete')\n"
)


def setup_sandbox(sandbox: Sandbox):
    """Create test databases, XMP files, and images in the sandbox."""
    print("Setting up test data...")
    sandbox.commands.run("mkdir -p /home/user/verifiers")
    with open(VERIFIER_LOCAL) as f:
        sandbox.files.write(VERIFIER_REMOTE, f.read())

    # Install Pillow for export-info tests
    print("Installing Pillow...")
    try:
        r = sandbox.commands.run("pip install Pillow 2>&1", timeout=60)
        print(f"  pip: {r.stdout.strip()[-80:]}")
    except CommandExitException as e:
        print(f"  pip warning: {e.stderr[:100]}")

    # Write and run setup script
    sandbox.files.write("/home/user/setup_test_data.py", SETUP_SCRIPT)
    try:
        r = sandbox.commands.run("python3 /home/user/setup_test_data.py", timeout=30)
        print(f"  Setup: {r.stdout.strip()}")
    except CommandExitException as e:
        print(f"  Setup error: {e.stderr[:200]}")
        raise


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    """--help should print usage and exit 0."""
    print("\n=== Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
    check("help mentions Commands", "Commands:" in result.stdout, result.stdout[:100])
    check("help mentions darktable", "darktable" in result.stdout.lower(), result.stdout[:100])


def test_errors_no_db(sandbox: Sandbox):
    """Endpoints should return error JSON when config dir is missing."""
    print("\n=== Errors (no config dir) ===")

    # Temporarily rename config dir
    sandbox.commands.run(f"mv {CONFIG_DIR} {CONFIG_DIR}.bak")
    try:
        data = run(sandbox, "library-images")
        if isinstance(data, list):
            data = data[0] if data else {}
        check("library-images returns error without DB", "error" in data, str(data)[:100])

        data = run(sandbox, "tags")
        if isinstance(data, list):
            data = data[0] if data else {}
        check("tags returns error without DB", "error" in data, str(data)[:100])
    finally:
        sandbox.commands.run(f"mv {CONFIG_DIR}.bak {CONFIG_DIR}")


def test_errors_bad_args(sandbox: Sandbox):
    """Missing/invalid arguments should return error JSON, not crash."""
    print("\n=== Errors (bad args) ===")

    # Missing required arg
    result = run_raw(sandbox, "image-info")
    check("missing arg exits 1", result.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Unknown command
    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Bad image ID
    data = run(sandbox, "image-info 99999")
    check("bad image_id returns error", "error" in data, str(data)[:100])


def test_library_images(sandbox: Sandbox):
    """Test library-images query endpoint."""
    print("\n=== library-images ===")

    data = run(sandbox, "library-images")
    check("library-images returns list", isinstance(data, list), str(type(data)))
    check("library-images has 3 entries", len(data) == 3, f"got {len(data)}")
    if data and "error" not in data[0]:
        check("image has filename key", "filename" in data[0], str(data[0].keys()))
        check("image has film_roll key", "film_roll" in data[0], str(data[0].keys()))

    # Filter
    data = run(sandbox, "library-images sunset")
    check("filter returns list", isinstance(data, list))
    check("filter finds sunset.CR2", len(data) == 1 and data[0].get("filename") == "sunset.CR2",
          str(data)[:100])

    # No match
    data = run(sandbox, "library-images nonexistent_xyz")
    check("no-match returns empty list", isinstance(data, list) and len(data) == 0,
          str(data)[:100])


def test_image_info(sandbox: Sandbox):
    """Test image-info endpoint."""
    print("\n=== image-info ===")

    data = run(sandbox, "image-info 1")
    check("image-info returns dict", isinstance(data, dict))
    check("image-info has filename", data.get("filename") == "sunset.CR2", str(data)[:100])
    check("image-info has width", data.get("width") == 6000, f"width={data.get('width')}")
    check("image-info has maker", data.get("maker") == "Canon", f"maker={data.get('maker')}")
    check("image-info has iso", data.get("iso") == 100, f"iso={data.get('iso')}")


def test_tags(sandbox: Sandbox):
    """Test tags endpoint."""
    print("\n=== tags ===")

    data = run(sandbox, "tags")
    check("tags returns list", isinstance(data, list))
    check("tags has 4 entries", len(data) == 4, f"got {len(data)}")

    # Filter
    data = run(sandbox, "tags land")
    check("tags filter returns list", isinstance(data, list))
    check("tags filter finds landscape",
          any(t.get("name") == "landscape" for t in data), str(data)[:100])


def test_image_tags(sandbox: Sandbox):
    """Test image-tags endpoint."""
    print("\n=== image-tags ===")

    data = run(sandbox, "image-tags 1")
    check("image-tags returns list", isinstance(data, list))
    check("image-tags has 2 tags", len(data) == 2, f"got {len(data)}")
    tag_names = [t.get("tag_name") for t in data]
    check("image-tags includes landscape", "landscape" in tag_names, str(tag_names))
    check("image-tags includes sunset", "sunset" in tag_names, str(tag_names))

    # Image with no tags (id=99 doesn't exist, should return empty)
    data = run(sandbox, "image-tags 99999")
    check("no-tags returns empty list", isinstance(data, list) and len(data) == 0,
          str(data)[:100])


def test_styles(sandbox: Sandbox):
    """Test styles endpoint."""
    print("\n=== styles ===")

    data = run(sandbox, "styles")
    check("styles returns list", isinstance(data, list))
    check("styles has 2 entries", len(data) == 2, f"got {len(data)}")
    names = [s.get("name") for s in data]
    check("styles includes B&W Film", "B&W Film" in names, str(names))


def test_presets(sandbox: Sandbox):
    """Test presets endpoint."""
    print("\n=== presets ===")

    data = run(sandbox, "presets")
    check("presets returns list", isinstance(data, list))
    check("presets has 2 entries", len(data) == 2, f"got {len(data)}")
    ops = [p.get("operation") for p in data]
    check("presets includes exposure", "exposure" in ops, str(ops))


def test_collections(sandbox: Sandbox):
    """Test collections endpoint."""
    print("\n=== collections ===")

    data = run(sandbox, "collections")
    check("collections returns list", isinstance(data, list))
    check("collections has 2 entries", len(data) == 2, f"got {len(data)}")
    folders = [c.get("folder") for c in data]
    check("collections includes /home/user/photos", "/home/user/photos" in folders, str(folders))


def test_xmp_history(sandbox: Sandbox):
    """Test xmp-history endpoint."""
    print("\n=== xmp-history ===")

    data = run(sandbox, "xmp-history /home/user/photos/sunset.CR2.xmp")
    check("xmp-history returns dict", isinstance(data, dict))
    check("xmp-history has operations", "operations" in data, str(data.keys()))
    ops = data.get("operations", [])
    check("xmp-history has 4 operations", len(ops) == 4, f"got {len(ops)}")

    op_names = [o.get("operation") for o in ops]
    check("xmp-history includes exposure", "exposure" in op_names, str(op_names))
    check("xmp-history includes colorbalancergb", "colorbalancergb" in op_names, str(op_names))

    # Check enabled flags
    check("first op enabled=1", ops[0].get("enabled") == "1", str(ops[0]))
    check("third op enabled=0 (disabled)", ops[2].get("enabled") == "0", str(ops[2]))

    # Minimal XMP (no history)
    data = run(sandbox, "xmp-history /home/user/photos/portrait.NEF.xmp")
    check("minimal xmp has 0 operations", data.get("count", -1) == 0,
          f"count={data.get('count')}")

    # Nonexistent XMP
    data = run(sandbox, "xmp-history /nonexistent.xmp")
    check("missing xmp returns error", "error" in data, str(data)[:100])


def test_xmp_rating(sandbox: Sandbox):
    """Test xmp-rating endpoint."""
    print("\n=== xmp-rating ===")

    data = run(sandbox, "xmp-rating /home/user/photos/sunset.CR2.xmp")
    check("xmp-rating returns dict", isinstance(data, dict))
    check("xmp-rating is 4", data.get("rating") == 4, f"rating={data.get('rating')}")

    data = run(sandbox, "xmp-rating /home/user/photos/portrait.NEF.xmp")
    check("xmp-rating is 2", data.get("rating") == 2, f"rating={data.get('rating')}")

    data = run(sandbox, "xmp-rating /nonexistent.xmp")
    check("missing xmp returns error", "error" in data, str(data)[:100])


def test_export_info(sandbox: Sandbox):
    """Test export-info endpoint."""
    print("\n=== export-info ===")

    data = run(sandbox, "export-info /home/user/photos/exported.jpg")
    check("export-info returns dict", isinstance(data, dict))
    check("export-info exists=true", data.get("exists") is True, str(data)[:100])
    check("export-info has size", isinstance(data.get("size_bytes"), int), str(data)[:100])
    # If PIL is installed, check dimensions
    if "width" in data:
        check("export-info width=800", data.get("width") == 800, f"width={data.get('width')}")
        check("export-info height=600", data.get("height") == 600, f"height={data.get('height')}")
        check("export-info format=JPEG", data.get("format") == "JPEG", f"format={data.get('format')}")

    data = run(sandbox, "export-info /nonexistent_file.jpg")
    check("missing file returns error", "error" in data, str(data)[:100])


def test_checks_positive(sandbox: Sandbox):
    """Check-* endpoints -- positive cases."""
    print("\n=== Checks (positive) ===")

    # check-file-exists
    data = run(sandbox, "check-file-exists /home/user/photos/exported.jpg")
    check("check-file-exists exists=true", data.get("exists") is True, str(data)[:100])
    check("check-file-exists has size", isinstance(data.get("size_bytes"), int), str(data)[:100])

    # check-image-imported
    data = run(sandbox, "check-image-imported sunset.CR2")
    check("check-image-imported imported=true", data.get("imported") is True, str(data)[:100])
    check("check-image-imported has image_id", data.get("image_id") == 1, str(data)[:100])

    # check-tag-exists
    data = run(sandbox, "check-tag-exists landscape")
    check("check-tag-exists exists=true", data.get("exists") is True, str(data)[:100])
    check("check-tag-exists has tag_id", data.get("tag_id") == 1, str(data)[:100])

    # check-image-tagged
    data = run(sandbox, "check-image-tagged 1 landscape")
    check("check-image-tagged tagged=true", data.get("tagged") is True, str(data)[:100])

    # check-image-exported
    data = run(sandbox, "check-image-exported /home/user/photos/exported.jpg")
    check("check-image-exported exported=true", data.get("exported") is True, str(data)[:100])
    if data.get("valid_image") is not None:
        check("check-image-exported valid_image=true", data.get("valid_image") is True, str(data)[:100])

    # check-xmp-has-operation
    data = run(sandbox, "check-xmp-has-operation /home/user/photos/sunset.CR2.xmp exposure")
    check("check-xmp-has-operation has_operation=true", data.get("has_operation") is True, str(data)[:100])
    check("check-xmp-has-operation count=2", data.get("count") == 2, f"count={data.get('count')}")

    # check-image-rating (image 1 has flags=4, rating=4)
    data = run(sandbox, "check-image-rating 1 4")
    check("check-image-rating matches=true", data.get("matches") is True, str(data)[:100])
    check("check-image-rating actual=4", data.get("actual_rating") == 4, str(data)[:100])

    # check-style-exists
    data = run(sandbox, "check-style-exists 'B&W Film'")
    check("check-style-exists exists=true", data.get("exists") is True, str(data)[:100])


def test_checks_negative(sandbox: Sandbox):
    """Check-* endpoints -- negative cases."""
    print("\n=== Checks (negative) ===")

    # check-file-exists
    data = run(sandbox, "check-file-exists /nonexistent/file.txt")
    check("check-file-exists exists=false", data.get("exists") is False, str(data)[:100])

    # check-image-imported
    data = run(sandbox, "check-image-imported nonexistent_photo_xyz.CR2")
    check("check-image-imported imported=false", data.get("imported") is False, str(data)[:100])

    # check-tag-exists
    data = run(sandbox, "check-tag-exists nonexistent_tag_xyz")
    check("check-tag-exists exists=false", data.get("exists") is False, str(data)[:100])

    # check-image-tagged (image 2 does NOT have tag "landscape")
    data = run(sandbox, "check-image-tagged 2 landscape")
    check("check-image-tagged tagged=false", data.get("tagged") is False, str(data)[:100])

    # check-image-exported
    data = run(sandbox, "check-image-exported /nonexistent/output.jpg")
    check("check-image-exported exported=false", data.get("exported") is False, str(data)[:100])

    # check-xmp-has-operation (operation not present)
    data = run(sandbox, "check-xmp-has-operation /home/user/photos/sunset.CR2.xmp denoiseprofile")
    check("check-xmp-has-operation has_operation=false", data.get("has_operation") is False, str(data)[:100])

    # check-image-rating (wrong rating)
    data = run(sandbox, "check-image-rating 1 2")
    check("check-image-rating matches=false", data.get("matches") is False, str(data)[:100])
    check("check-image-rating actual=4 expected=2",
          data.get("actual_rating") == 4 and data.get("expected_rating") == 2, str(data)[:100])

    # check-style-exists
    data = run(sandbox, "check-style-exists 'Nonexistent Style XYZ'")
    check("check-style-exists exists=false", data.get("exists") is False, str(data)[:100])


def test_all_commands_return_json(sandbox: Sandbox):
    """Every CLI command should output valid JSON (not crash with a traceback)."""
    print("\n=== JSON validity (all commands) ===")

    # Commands with no required args
    no_arg_cmds = ["library-images", "tags", "styles", "presets", "collections"]
    for cmd in no_arg_cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        check(f"{cmd} returns valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # Commands with args
    arg_cmds = [
        ("library-images", "sunset"),
        ("image-info", "1"),
        ("tags", "landscape"),
        ("image-tags", "1"),
        ("xmp-history", "/home/user/photos/sunset.CR2.xmp"),
        ("xmp-rating", "/home/user/photos/sunset.CR2.xmp"),
        ("export-info", "/home/user/photos/exported.jpg"),
        ("check-file-exists", "/home/user/photos/exported.jpg"),
        ("check-image-imported", "sunset.CR2"),
        ("check-tag-exists", "landscape"),
        ("check-image-tagged", "1 landscape"),
        ("check-image-exported", "/home/user/photos/exported.jpg"),
        ("check-xmp-has-operation", "/home/user/photos/sunset.CR2.xmp exposure"),
        ("check-image-rating", "1 4"),
        ("check-style-exists", "'B&W Film'"),
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
    print("darktable Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        setup_sandbox(sandbox)

        test_help(sandbox)
        test_errors_bad_args(sandbox)
        test_errors_no_db(sandbox)
        test_library_images(sandbox)
        test_image_info(sandbox)
        test_tags(sandbox)
        test_image_tags(sandbox)
        test_styles(sandbox)
        test_presets(sandbox)
        test_collections(sandbox)
        test_xmp_history(sandbox)
        test_xmp_rating(sandbox)
        test_export_info(sandbox)
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
