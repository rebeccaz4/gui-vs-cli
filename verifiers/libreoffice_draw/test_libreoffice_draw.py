"""
Test LibreOffice Draw verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (LibreOffice not running, bad args)
  - ODF file parsing endpoints (ODG file, no UNO needed)
  - UNO live endpoints with ODG file (pages, shapes, text, layers, connectors)
  - Composite check-* endpoints — positive and negative cases

Usage:
    python verifiers/libreoffice_draw/test_libreoffice_draw.py
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

VERIFIER_LOCAL = Path(__file__).parent / "libreoffice_draw.py"
VERIFIER_REMOTE = "/home/user/verifiers/libreoffice_draw.py"
V = f"python3 {VERIFIER_REMOTE}"

TEST_ODG_PATH = "/home/user/test_verifier.odg"

# ── ODG fixture (stdlib ZIP+XML) ────────────────────────────────────────

CREATE_ODG_SCRIPT = r'''
import zipfile

CONTENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
  xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
  office:version="1.2">
  <office:body>
    <office:drawing>
      <draw:page draw:name="Diagram">
        <draw:rect draw:name="Box1" svg:x="2cm" svg:y="2cm" svg:width="6cm" svg:height="3cm">
          <text:p>Start Process</text:p>
        </draw:rect>
        <draw:rect draw:name="Box2" svg:x="12cm" svg:y="2cm" svg:width="6cm" svg:height="3cm">
          <text:p>End Process</text:p>
        </draw:rect>
        <draw:ellipse draw:name="Circle1" svg:x="7cm" svg:y="8cm" svg:width="4cm" svg:height="4cm">
          <text:p>Decision</text:p>
        </draw:ellipse>
      </draw:page>
      <draw:page draw:name="Layout">
        <draw:rect draw:name="Header" svg:x="1cm" svg:y="1cm" svg:width="18cm" svg:height="2cm">
          <text:p>Page Header</text:p>
        </draw:rect>
      </draw:page>
    </office:drawing>
  </office:body>
</office:document-content>
"""

MANIFEST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">
  <manifest:file-entry manifest:media-type="application/vnd.oasis.opendocument.graphics" manifest:full-path="/"/>
  <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="content.xml"/>
</manifest:manifest>
"""

path = "/home/user/test_verifier.odg"
with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("mimetype", "application/vnd.oasis.opendocument.graphics")
    z.writestr("content.xml", CONTENT_XML)
    z.writestr("META-INF/manifest.xml", MANIFEST_XML)

print("OK")
'''

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


def run_shell(sandbox: Sandbox, cmd: str, timeout: int = 60) -> CmdResult:
    try:
        result = sandbox.commands.run(cmd, timeout=timeout)
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
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    print("\n=== Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
    check("help mentions commands", "Commands:" in result.stdout, result.stdout[:100])


def test_errors_lo_not_running(sandbox: Sandbox):
    print("\n=== Errors (LibreOffice not running) ===")
    for cmd, name in [("pages", "pages"), ("page-shapes 0", "page-shapes"), ("doc-info", "doc-info")]:
        data = run(sandbox, cmd)
        check(f"{name} returns error when LO down", "error" in data, str(data)[:100])


def test_errors_bad_args(sandbox: Sandbox):
    print("\n=== Errors (bad args) ===")
    result = run_raw(sandbox, "check-shape-count")
    check("missing arg exits 1", result.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])


def test_odg_file_parsing(sandbox: Sandbox):
    """ODG parsing endpoints (no UNO needed)."""
    print("\n=== ODG File Parsing ===")

    data = run(sandbox, f"parse-pages {TEST_ODG_PATH}")
    check("parse-pages returns pages", len(data.get("pages", [])) > 0, str(data)[:150])
    if "error" not in data:
        check("parse-pages has 2 pages", data.get("count") == 2, f"count={data.get('count')}")
        names = [p["name"] for p in data.get("pages", [])]
        check("parse-pages has Diagram", "Diagram" in names, str(names))

    data = run(sandbox, f"parse-page-text 0 {TEST_ODG_PATH}")
    check("parse-page-text returns texts", "texts" in data and "error" not in data, str(data)[:150])
    if "error" not in data:
        check("parse-page-text has Start Process",
              "Start Process" in data.get("full_text", ""),
              data.get("full_text", "")[:100])
        check("parse-page-text has Decision",
              "Decision" in data.get("full_text", ""),
              data.get("full_text", "")[:100])

    data = run(sandbox, "parse-pages /nonexistent/file.odg")
    check("parse missing file returns error", "error" in data, str(data)[:100])


def test_uno_basic(sandbox: Sandbox):
    """Basic UNO endpoints with ODG loaded."""
    print("\n=== UNO Basic (ODG) ===")

    data = run(sandbox, "pages")
    check("pages returns dict", isinstance(data, dict) and "error" not in data, str(data)[:200])
    if "error" not in data:
        check("pages count = 2", data.get("count") == 2, f"count={data.get('count')}")

    data = run(sandbox, "doc-info")
    check("doc-info has title", "title" in data and "error" not in data, str(data)[:150])
    if "error" not in data:
        check("doc-info page_count = 2", data.get("page_count") == 2,
              f"page_count={data.get('page_count')}")

    data = run(sandbox, "page-size")
    check("page-size returns dict", isinstance(data, dict) and "error" not in data, str(data)[:100])
    if "error" not in data:
        check("page-size has width", "width" in data, str(data.keys()))


def test_uno_shapes(sandbox: Sandbox):
    """Shape and text endpoints via UNO."""
    print("\n=== UNO Shapes ===")

    data = run(sandbox, "page-shapes 0")
    check("page-shapes returns shapes", "shapes" in data and "error" not in data, str(data)[:200])
    if "error" not in data:
        check("page 0 has shapes", data.get("count", 0) >= 3, f"count={data.get('count')}")
        # Check shape types
        types = [s.get("type", "") for s in data.get("shapes", [])]
        type_str = " ".join(types).lower()
        check("has rectangle shape", "rectangle" in type_str or "rect" in type_str,
              f"types={types}")

    data = run(sandbox, "page-text 0")
    check("page-text returns texts", "texts" in data and "error" not in data, str(data)[:200])
    if "error" not in data:
        full = data.get("full_text", "")
        check("page-text has Start Process", "Start Process" in full, full[:100])
        check("page-text has Decision", "Decision" in full, full[:100])

    data = run(sandbox, "page-shapes 1")
    if "error" not in data:
        check("page 1 has shapes", data.get("count", 0) >= 1, f"count={data.get('count')}")


def test_uno_layers(sandbox: Sandbox):
    """Layer endpoints via UNO."""
    print("\n=== UNO Layers ===")

    data = run(sandbox, "layers")
    check("layers returns dict", isinstance(data, dict) and "error" not in data, str(data)[:200])
    if "error" not in data:
        check("layers count >= 1", data.get("count", 0) >= 1, f"count={data.get('count')}")
        names = [l["name"] for l in data.get("layers", [])]
        names_lower = [n.lower() for n in names]
        check("has layout layer", "layout" in names_lower, str(names))


def test_uno_connectors(sandbox: Sandbox):
    """Connector endpoints via UNO."""
    print("\n=== UNO Connectors ===")

    data = run(sandbox, "connectors 0")
    check("connectors returns dict", isinstance(data, dict) and "error" not in data, str(data)[:100])
    if "error" not in data:
        check("connectors has count", "count" in data, str(data.keys()))


def test_checks_positive(sandbox: Sandbox):
    """Composite check-* endpoints — positive cases."""
    print("\n=== Checks (positive) ===")

    data = run(sandbox, "check-page-count 2")
    check("check-page-count 2 match", data.get("match") is True, str(data)[:100])

    # Get actual shape count for page 0
    shapes = run(sandbox, "page-shapes 0")
    if "error" not in shapes:
        count = shapes["count"]
        data = run(sandbox, f"check-shape-count 0 {count}")
        check("check-shape-count match", data.get("match") is True, str(data)[:100])

    data = run(sandbox, 'check-page-contains 0 "Start Process"')
    check("check-page-contains found", data.get("contains") is True, str(data)[:100])

    # Check shape type exists
    data = run(sandbox, "check-shape-exists 0 Rect")
    check("check-shape-exists Rect", data.get("exists") is True, str(data)[:100])

    # Check layer exists
    data = run(sandbox, "check-layer-exists Layout")
    check("check-layer-exists Layout", data.get("exists") is True, str(data)[:100])

    data = run(sandbox, f"check-file-exists {TEST_ODG_PATH}")
    check("check-file-exists true", data.get("exists") is True, str(data)[:100])

    data = run(sandbox, "check-file-saved")
    check("check-file-saved has key", "saved" in data or "error" in data, str(data)[:100])


def test_checks_negative(sandbox: Sandbox):
    """Composite check-* endpoints — negative cases."""
    print("\n=== Checks (negative) ===")

    data = run(sandbox, "check-page-count 99")
    check("check-page-count mismatch", data.get("match") is False, str(data)[:100])

    data = run(sandbox, "check-shape-count 0 9999")
    check("check-shape-count mismatch", data.get("match") is False, str(data)[:100])

    data = run(sandbox, 'check-page-contains 0 "xyzzy_nonexistent_12345"')
    check("check-page-contains false", data.get("contains") is False, str(data)[:100])

    data = run(sandbox, "check-shape-exists 0 NonExistentShapeType12345")
    check("check-shape-exists false", data.get("exists") is False, str(data)[:100])

    data = run(sandbox, "check-layer-exists NonExistentLayer12345")
    check("check-layer-exists false", data.get("exists") is False, str(data)[:100])

    data = run(sandbox, "check-file-exists /nonexistent/file.odg")
    check("check-file-exists false", data.get("exists") is False, str(data)[:100])


def test_all_commands_return_json(sandbox: Sandbox):
    """Every CLI command should output valid JSON."""
    print("\n=== JSON validity (all commands) ===")

    no_arg_cmds = ["pages", "page-size", "doc-info", "layers"]
    for cmd in no_arg_cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        check(f"{cmd} valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    arg_cmds = [
        ("page-shapes", "0"),
        ("page-shapes", "1"),
        ("page-text", "0"),
        ("connectors", "0"),
        ("parse-pages", TEST_ODG_PATH),
        ("parse-page-text", f"0 {TEST_ODG_PATH}"),
        ("check-page-count", "2"),
        ("check-shape-count", "0 1"),
        ("check-shape-exists", "0 Rect"),
        ("check-page-contains", '0 "test"'),
        ("check-layer-exists", "Layout"),
        ("check-file-exists", TEST_ODG_PATH),
        ("check-file-saved", ""),
    ]

    for cmd, arg in arg_cmds:
        full_cmd = f"{cmd} {arg}".strip()
        result = run_raw(sandbox, full_cmd)
        valid = is_valid_json(result.stdout)
        check(f"{full_cmd} valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def launch_libreoffice(sandbox: Sandbox, file_path: str) -> bool:
    """Launch LibreOffice Draw with UNO socket, opening the given file."""
    try:
        sandbox.commands.run("pkill -9 -f soffice", timeout=5)
    except (CommandExitException, Exception):
        pass
    try:
        sandbox.commands.run("pkill -9 -f oosplash", timeout=5)
    except (CommandExitException, Exception):
        pass
    time.sleep(2)

    launch_script = f'''#!/bin/bash
soffice --draw \
  '--accept=socket,host=localhost,port=2002;urp;' \
  --norestore --nologo \
  {file_path} \
  > /tmp/lo.log 2>&1
'''
    sandbox.files.write("/tmp/launch_lo.sh", launch_script)
    sandbox.commands.run("chmod +x /tmp/launch_lo.sh", timeout=3)
    sandbox.commands.run("/tmp/launch_lo.sh", background=True)

    check_script = '''
import uno, time
for attempt in range(5):
    try:
        ctx = uno.getComponentContext()
        resolver = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", ctx
        )
        resolved = resolver.resolve(
            "uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext"
        )
        smgr = resolved.ServiceManager
        desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", resolved)
        doc = desktop.getCurrentComponent()
        if doc is not None:
            print("READY")
            break
        else:
            print("NODOC")
            break
    except Exception as e:
        if attempt < 4:
            time.sleep(1)
        else:
            print(f"ERR:{e}")
'''
    sandbox.files.write("/tmp/check_uno.py", check_script)

    for i in range(30):
        try:
            r = sandbox.commands.run("python3 /tmp/check_uno.py", timeout=10)
            if "READY" in r.stdout:
                print(f"  LibreOffice UNO ready (attempt {i+1})")
                return True
            if "NODOC" in r.stdout:
                print(f"  UNO connected but no doc yet (attempt {i+1})")
        except (CommandExitException, Exception) as e:
            if i > 15:
                print(f"  attempt {i+1}: {str(e)[:80]}")
        time.sleep(2)

    try:
        r = sandbox.commands.run("tail -20 /tmp/lo.log", timeout=3)
        print(f"  [lo log] {r.stdout[-300:]}")
    except (CommandExitException, Exception):
        pass
    return False


def main():
    global passed, failed

    print("=" * 60)
    print("LibreOffice Draw Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # ── Tests with LibreOffice NOT running ──
        test_help(sandbox)
        test_errors_lo_not_running(sandbox)
        test_errors_bad_args(sandbox)

        # ── Create ODG test file ──
        print("\n  Creating ODG test file...")
        sandbox.files.write("/home/user/create_odg.py", CREATE_ODG_SCRIPT)
        r = run_shell(sandbox, "python3 /home/user/create_odg.py")
        odg_ok = "OK" in r.stdout
        check("ODG file created", odg_ok, f"stdout={r.stdout[:100]} stderr={r.stderr[:100]}")
        if odg_ok:
            test_odg_file_parsing(sandbox)

        # ── Launch LibreOffice Draw with ODG ──
        print("\nLaunching LibreOffice Draw with ODG file...")
        lo_ready = launch_libreoffice(sandbox, TEST_ODG_PATH)
        if not lo_ready:
            print("  WARNING: LibreOffice UNO not ready -- UNO tests may fail")

        # ── UNO tests ──
        test_uno_basic(sandbox)
        test_uno_shapes(sandbox)
        test_uno_layers(sandbox)
        test_uno_connectors(sandbox)
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

    # ── Summary ──
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print("=" * 60)

    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  - {e}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
