"""
Test FreeCAD verifier endpoints in a live E2B sandbox.

Builds:
  - a rich .FCStd file with Box/Cylinder/Sphere/Cone/Cut/Compound via
    freecadcmd
  - exports STL/STEP/OBJ via FreeCAD's exporter
  - a hand-written user.cfg preferences fixture
  - a tiny hand-written ASCII STL

Then exercises every endpoint of verifiers/freecad/freecad.py, testing
positive and negative cases plus error handling.

Usage:
    python verifiers/freecad/test_freecad.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "freecad.py"
VERIFIER_REMOTE = "/home/user/verifiers/freecad.py"
V = f"python3 {VERIFIER_REMOTE}"

TEST_FCSTD = "/home/user/test.FCStd"
CFG_PATH = "/home/user/.config/FreeCAD/user.cfg"
STL_BIN = "/home/user/exports/box.stl"
STL_ASCII = "/home/user/exports/box_ascii.stl"
STEP_FILE = "/home/user/exports/box.step"
OBJ_FILE = "/home/user/exports/box.obj"

passed = 0
failed = 0
errors: list[str] = []


class CmdResult:
    def __init__(self, exit_code, stdout, stderr):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def run_raw(sb, cmd, timeout=60):
    try:
        result = sb.commands.run(f"{V} {cmd}", timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def run(sb, cmd, timeout=60):
    r = run_raw(sb, cmd, timeout=timeout)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


def run_shell(sb, cmd, timeout=120):
    try:
        result = sb.commands.run(cmd, timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  -- {detail}")
        errors.append(f"{name}: {detail}")


def is_valid_json(s):
    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


# ── Fixture: FreeCAD build script ─────────────────────────────────────────────

BUILD_FREECAD_SCRIPT = r'''
import FreeCAD
import Part
import Mesh
import Import  # STEP export
import os

os.makedirs("/home/user/exports", exist_ok=True)

doc = FreeCAD.newDocument("Test")
doc.Comment = "verifier fixture"

# Box
box = doc.addObject("Part::Box", "Box")
box.Label = "RedBox"
box.Length = 20.0
box.Width = 15.0
box.Height = 10.0

# Cylinder
cyl = doc.addObject("Part::Cylinder", "Cylinder")
cyl.Label = "GreenCyl"
cyl.Radius = 5.0
cyl.Height = 20.0

# Sphere
sph = doc.addObject("Part::Sphere", "Sphere")
sph.Label = "BlueSphere"
sph.Radius = 8.0

# Cone
cone = doc.addObject("Part::Cone", "Cone")
cone.Label = "YellowCone"
cone.Radius1 = 6.0
cone.Radius2 = 1.0
cone.Height = 12.0

# Boolean Cut (Box - Cylinder)
cut = doc.addObject("Part::Cut", "Cut")
cut.Base = box
cut.Tool = cyl
cut.Label = "CutResult"

doc.recompute()

# Compound of sphere+cone
comp = doc.addObject("Part::Compound", "Compound")
comp.Links = [sph, cone]
comp.Label = "MyCompound"

doc.recompute()

# Save FCStd
doc.saveAs("/home/user/test.FCStd")

# Export STL (binary) of the Cut result
Mesh.export([cut], "/home/user/exports/box.stl")

# Export STEP of the Cut result
Import.export([cut], "/home/user/exports/box.step")

# Export OBJ via Mesh
mesh_obj = doc.addObject("Mesh::Feature", "TempMesh")
import MeshPart
mesh_obj.Mesh = MeshPart.meshFromShape(Shape=cut.Shape, MaxLength=2.0)
Mesh.export([mesh_obj], "/home/user/exports/box.obj")

print("FIXTURE_OK")
'''

USER_CFG = r'''<?xml version="1.0" encoding="utf-8"?>
<FCParameters>
 <FCParamGroup Name="Root">
  <FCParamGroup Name="BaseApp">
   <FCParamGroup Name="Preferences">
    <FCParamGroup Name="General">
     <FCText Name="ThemeName" Value="Dark"/>
     <FCBool Name="AutoSaveEnabled" Value="true"/>
     <FCInt Name="AutoSaveInterval" Value="300"/>
    </FCParamGroup>
    <FCParamGroup Name="Units">
     <FCInt Name="UserSchema" Value="1"/>
    </FCParamGroup>
    <FCParamGroup Name="Mod">
     <FCText Name="StartWorkbench" Value="PartDesignWorkbench"/>
    </FCParamGroup>
   </FCParamGroup>
  </FCParamGroup>
 </FCParamGroup>
</FCParameters>
'''

ASCII_STL = """solid simple
facet normal 0 0 1
  outer loop
    vertex 0 0 0
    vertex 1 0 0
    vertex 0 1 0
  endloop
endfacet
endsolid simple
"""


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_help(sb):
    print("\n=== Help / Errors ===")
    r = run_raw(sb, "--help")
    check("help exits 0", r.exit_code == 0)
    check("help mentions commands", "Commands:" in r.stdout)

    r = run_raw(sb, "objects")
    check("missing file arg exits 1", r.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(r.stdout))

    data = run(sb, "objects /nonexistent/file.FCStd")
    check("nonexistent fcstd returns error", "error" in data, str(data)[:100])

    r = run_raw(sb, "nonexistent-command test.FCStd")
    check("unknown cmd exits 1", r.exit_code == 1)

    # Non-zip file
    run_shell(sb, "echo 'not-a-zip' > /tmp/bad.FCStd")
    data = run(sb, "objects /tmp/bad.FCStd")
    check("non-zip FCStd returns error", "error" in data, str(data)[:100])


def test_document_info(sb):
    print("\n=== document-info ===")
    data = run(sb, f"document-info {TEST_FCSTD}")
    check("document-info no error", "error" not in data, str(data)[:200])
    if "error" in data:
        return
    check("has program_version", "program_version" in data)
    check("has archive_files list", isinstance(data.get("archive_files"), list))
    check("archive has Document.xml",
          "Document.xml" in data.get("archive_files", []))
    check("object_count > 0", data.get("object_count", 0) > 0,
          f"count={data.get('object_count')}")
    check("has_thumbnail is bool", isinstance(data.get("has_thumbnail"), bool))
    check("Comment matches fixture",
          data.get("properties", {}).get("Comment") == "verifier fixture",
          str(data.get("properties"))[:200])


def test_objects(sb):
    print("\n=== objects / object-info / object-types ===")
    data = run(sb, f"objects {TEST_FCSTD}")
    check("objects returns dict", "error" not in data, str(data)[:200])
    if "error" in data:
        return
    names = [o["name"] for o in data.get("objects", [])]
    for expected in ["Box", "Cylinder", "Sphere", "Cone", "Cut", "Compound"]:
        check(f"{expected} in objects", expected in names, str(names))
    check("object count >= 6", data.get("count", 0) >= 6,
          f"count={data.get('count')}")

    # Object info
    data = run(sb, f"object-info {TEST_FCSTD} Box")
    check("Box object-info", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("Box type Part::Box", data.get("type") == "Part::Box",
              f"type={data.get('type')}")
        props = data.get("properties", {})
        check("Box has Length property", "Length" in props,
              str(list(props.keys()))[:200])

    # Nonexistent
    data = run(sb, f"object-info {TEST_FCSTD} NoSuchObject")
    check("nonexistent object returns error", "error" in data, str(data)[:200])

    # object-types
    data = run(sb, f"object-types {TEST_FCSTD}")
    check("object-types no error", "error" not in data, str(data)[:200])
    if "error" not in data:
        counts = data.get("counts", {})
        check("Part::Box in counts", "Part::Box" in counts, str(counts))
        check("Part::Cylinder in counts", "Part::Cylinder" in counts, str(counts))


def test_parameters(sb):
    print("\n=== parameter / label / placement ===")
    # Box.Length = 20
    data = run(sb, f"parameter {TEST_FCSTD} Box Length")
    check("Box.Length parameter", "error" not in data, str(data)[:200])
    if "error" not in data:
        val = data.get("value")
        check("Box.Length value 20",
              isinstance(val, (int, float)) and abs(float(val) - 20.0) < 1e-6,
              f"value={val}")

    # Box.Width = 15
    data = run(sb, f"parameter {TEST_FCSTD} Box Width")
    if "error" not in data:
        check("Box.Width value 15", abs(float(data.get("value", 0)) - 15.0) < 1e-6)

    # Cylinder.Radius = 5
    data = run(sb, f"parameter {TEST_FCSTD} Cylinder Radius")
    if "error" not in data:
        check("Cylinder.Radius 5", abs(float(data.get("value", 0)) - 5.0) < 1e-6)

    # Nonexistent param
    data = run(sb, f"parameter {TEST_FCSTD} Box NoSuchParam")
    check("nonexistent param returns error", "error" in data)

    # Label
    data = run(sb, f"label {TEST_FCSTD} Box")
    check("Box label readable", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("Box label RedBox", data.get("label") == "RedBox",
              f"label={data.get('label')}")

    # Placement
    data = run(sb, f"placement {TEST_FCSTD} Box")
    check("Box placement readable", "error" not in data, str(data)[:200])


def test_preferences(sb):
    print("\n=== preferences / preference ===")
    # write user.cfg
    run_shell(sb, "mkdir -p /home/user/.config/FreeCAD")
    sb.files.write(CFG_PATH, USER_CFG)

    data = run(sb, "preferences")
    check("preferences no error", "error" not in data, str(data)[:200])
    if "error" not in data:
        prefs = data.get("preferences", {})
        theme_key = "BaseApp/Preferences/General/ThemeName"
        check("theme key present", theme_key in prefs, str(list(prefs.keys()))[:300])
        check("theme value Dark", prefs.get(theme_key) == "Dark",
              f"theme={prefs.get(theme_key)}")
        auto_key = "BaseApp/Preferences/General/AutoSaveInterval"
        check("AutoSaveInterval int 300", prefs.get(auto_key) == 300,
              f"val={prefs.get(auto_key)}")
        auto_en_key = "BaseApp/Preferences/General/AutoSaveEnabled"
        check("AutoSaveEnabled bool True", prefs.get(auto_en_key) is True,
              f"val={prefs.get(auto_en_key)}")
        units_key = "BaseApp/Preferences/Units/UserSchema"
        check("UserSchema int 1", prefs.get(units_key) == 1,
              f"val={prefs.get(units_key)}")

    # Single pref
    data = run(sb, "preference BaseApp/Preferences/General/ThemeName")
    check("preference direct get", data.get("value") == "Dark", str(data)[:200])

    # Suffix match
    data = run(sb, "preference ThemeName")
    check("preference suffix match", data.get("value") == "Dark", str(data)[:200])

    # Nonexistent
    data = run(sb, "preference BaseApp/Preferences/General/NoSuchKey")
    check("nonexistent preference error", "error" in data, str(data)[:200])


def test_exported_files(sb):
    print("\n=== parse-stl / parse-step / parse-obj ===")
    # Write ASCII STL
    sb.files.write(STL_ASCII, ASCII_STL)

    data = run(sb, f"parse-stl {STL_ASCII}")
    check("ascii stl parse", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("ascii format detected", data.get("format") == "ascii",
              f"format={data.get('format')}")
        check("ascii 1 triangle", data.get("triangles") == 1,
              f"tri={data.get('triangles')}")

    data = run(sb, f"parse-stl {STL_BIN}")
    check("binary stl parse", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("binary format detected", data.get("format") == "binary",
              f"format={data.get('format')}")
        check("binary triangles > 0", data.get("triangles", 0) > 0,
              f"tri={data.get('triangles')}")

    data = run(sb, f"parse-step {STEP_FILE}")
    check("step parse", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("is_step true", data.get("is_step") is True, str(data)[:200])
        check("step entities > 0", data.get("entities", 0) > 0,
              f"ent={data.get('entities')}")

    data = run(sb, f"parse-obj {OBJ_FILE}")
    check("obj parse", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("obj vertices > 0", data.get("vertices", 0) > 0,
              f"v={data.get('vertices')}")
        check("obj faces > 0", data.get("faces", 0) > 0,
              f"f={data.get('faces')}")

    # Nonexistent
    data = run(sb, "parse-stl /no/such/file.stl")
    check("parse-stl nonexistent", "error" in data, str(data)[:200])


def test_checks_positive(sb):
    print("\n=== check-* positive ===")
    data = run(sb, f"check-file-exists {TEST_FCSTD}")
    check("check-file-exists true", data.get("exists") is True, str(data)[:200])

    data = run(sb, f"check-object-exists {TEST_FCSTD} Box")
    check("check-object-exists Box", data.get("exists") is True, str(data)[:200])

    data = run(sb, f"check-object-type {TEST_FCSTD} Box Part::Box")
    check("check-object-type Box=Part::Box", data.get("match") is True, str(data)[:200])

    # Total count >= 6 -- use the actual count from objects endpoint
    odata = run(sb, f"objects {TEST_FCSTD}")
    real_count = odata.get("count", 0) if "error" not in odata else 0
    data = run(sb, f"check-object-count {TEST_FCSTD} {real_count}")
    check(f"check-object-count={real_count}", data.get("match") is True, str(data)[:200])

    data = run(sb, f"check-object-type-count {TEST_FCSTD} Part::Box 1")
    check("check-object-type-count Part::Box=1", data.get("match") is True,
          str(data)[:200])

    data = run(sb, f"check-parameter-value {TEST_FCSTD} Box Length 20")
    check("check-parameter-value Box.Length=20", data.get("match") is True,
          str(data)[:200])

    data = run(sb, f"check-label {TEST_FCSTD} Box RedBox")
    check("check-label Box=RedBox", data.get("match") is True, str(data)[:200])

    data = run(sb, f"check-document-property {TEST_FCSTD} Comment 'verifier fixture'")
    # Skip this one - bash splits the quoted arg anyway, use underscores
    # Retry with a single-word check
    data = run(sb, f"check-document-property {TEST_FCSTD} Comment verifier fixture")
    # It'll use first two args; let's instead just verify doc-info showed it
    # and skip exact single-word check (Comment contains space).
    # Use a raw shell invocation with proper quoting:
    r = run_shell(sb, f"{V} check-document-property {TEST_FCSTD} Comment \"verifier fixture\"")
    try:
        data = json.loads(r.stdout)
    except Exception:
        data = {}
    check("check-document-property Comment",
          data.get("match") is True, str(data)[:200])

    data = run(sb, "check-preference BaseApp/Preferences/General/ThemeName Dark")
    check("check-preference ThemeName=Dark", data.get("match") is True,
          str(data)[:200])

    data = run(sb, "check-preference BaseApp/Preferences/General/AutoSaveInterval 300")
    check("check-preference AutoSaveInterval=300", data.get("match") is True,
          str(data)[:200])

    # STL checks (positive)
    pstl = run(sb, f"parse-stl {STL_BIN}")
    tri = pstl.get("triangles", 0)
    if tri > 0:
        data = run(sb, f"check-stl-triangles {STL_BIN} {tri}")
        check(f"check-stl-triangles={tri}", data.get("match") is True,
              str(data)[:200])

    data = run(sb, f"check-stl-min-triangles {STL_BIN} 1")
    check("check-stl-min-triangles>=1", data.get("match") is True, str(data)[:200])

    data = run(sb, f"check-step-valid {STEP_FILE}")
    check("check-step-valid true", data.get("valid") is True, str(data)[:200])

    data = run(sb, f"check-obj-min-vertices {OBJ_FILE} 4")
    check("check-obj-min-vertices>=4", data.get("match") is True, str(data)[:200])

    data = run(sb, f"check-has-thumbnail {TEST_FCSTD}")
    # Non-GUI saved FCStd may or may not have a thumbnail; just ensure it
    # returns a bool without error.
    check("check-has-thumbnail returns bool",
          isinstance(data.get("has_thumbnail"), bool), str(data)[:200])


def test_checks_negative(sb):
    print("\n=== check-* negative ===")
    data = run(sb, "check-file-exists /no/such/path.FCStd")
    check("check-file-exists false", data.get("exists") is False, str(data)[:200])

    data = run(sb, f"check-object-exists {TEST_FCSTD} NoSuchObj")
    check("check-object-exists false", data.get("exists") is False, str(data)[:200])

    data = run(sb, f"check-object-type {TEST_FCSTD} Box Part::Cylinder")
    check("check-object-type wrong", data.get("match") is False, str(data)[:200])

    data = run(sb, f"check-object-count {TEST_FCSTD} 999")
    check("check-object-count wrong", data.get("match") is False, str(data)[:200])

    data = run(sb, f"check-object-type-count {TEST_FCSTD} Part::Box 99")
    check("check-object-type-count wrong", data.get("match") is False,
          str(data)[:200])

    data = run(sb, f"check-parameter-value {TEST_FCSTD} Box Length 999")
    check("check-parameter-value wrong", data.get("match") is False,
          str(data)[:200])

    data = run(sb, f"check-label {TEST_FCSTD} Box NotRedBox")
    check("check-label wrong", data.get("match") is False, str(data)[:200])

    data = run(sb, "check-preference BaseApp/Preferences/General/ThemeName Light")
    check("check-preference wrong", data.get("match") is False, str(data)[:200])

    data = run(sb, f"check-stl-triangles {STL_ASCII} 999")
    check("check-stl-triangles wrong", data.get("match") is False, str(data)[:200])

    data = run(sb, f"check-stl-min-triangles {STL_ASCII} 1000000")
    check("check-stl-min-triangles unreachable", data.get("match") is False,
          str(data)[:200])

    data = run(sb, f"check-step-valid {STL_ASCII}")
    check("check-step-valid on stl false", data.get("valid") is False,
          str(data)[:200])

    data = run(sb, f"check-obj-min-vertices {OBJ_FILE} 100000000")
    check("check-obj-min-vertices unreachable", data.get("match") is False,
          str(data)[:200])


def test_json_sweep(sb):
    print("\n=== JSON validity sweep ===")
    cmds = [
        f"document-info {TEST_FCSTD}",
        f"objects {TEST_FCSTD}",
        f"object-info {TEST_FCSTD} Box",
        f"object-types {TEST_FCSTD}",
        f"parameter {TEST_FCSTD} Box Length",
        f"label {TEST_FCSTD} Box",
        f"placement {TEST_FCSTD} Box",
        "preferences",
        "preference BaseApp/Preferences/General/ThemeName",
        f"parse-stl {STL_ASCII}",
        f"parse-stl {STL_BIN}",
        f"parse-step {STEP_FILE}",
        f"parse-obj {OBJ_FILE}",
        f"check-file-exists {TEST_FCSTD}",
        f"check-object-exists {TEST_FCSTD} Box",
        f"check-object-type {TEST_FCSTD} Box Part::Box",
        f"check-object-count {TEST_FCSTD} 6",
        f"check-object-type-count {TEST_FCSTD} Part::Box 1",
        f"check-parameter-value {TEST_FCSTD} Box Length 20",
        f"check-label {TEST_FCSTD} Box RedBox",
        "check-preference BaseApp/Preferences/General/ThemeName Dark",
        f"check-stl-triangles {STL_ASCII} 1",
        f"check-stl-min-triangles {STL_BIN} 1",
        f"check-step-valid {STEP_FILE}",
        f"check-obj-min-vertices {OBJ_FILE} 1",
        f"check-has-thumbnail {TEST_FCSTD}",
    ]
    for cmd in cmds:
        r = run_raw(sb, cmd)
        label = cmd.split()[0]
        check(f"{label} valid JSON", is_valid_json(r.stdout),
              f"stdout={r.stdout[:100]}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("FreeCAD Verifier — Live Sandbox Test Suite")
    print("=" * 60)

    sb = Sandbox.create(template="desktop-all-apps", timeout=900)
    try:
        sb.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sb.files.write(VERIFIER_REMOTE, f.read())

        # Verify freecadcmd presence
        r = run_shell(sb, "which freecadcmd || which FreeCADCmd || echo MISSING")
        print(f"\nfreecadcmd: {r.stdout.strip()} | stderr={r.stderr.strip()[:100]}")
        freecadcmd = r.stdout.strip().splitlines()[0].strip()
        if not freecadcmd or freecadcmd == "MISSING":
            # try common paths
            for candidate in ["/usr/bin/freecadcmd", "/usr/bin/FreeCADCmd",
                              "/snap/bin/freecad.cmd"]:
                r = run_shell(sb, f"test -x {candidate} && echo {candidate}")
                if r.stdout.strip():
                    freecadcmd = r.stdout.strip()
                    break
        if not freecadcmd or freecadcmd == "MISSING":
            check("freecadcmd available", False, "freecadcmd not found in PATH")
            return

        check("freecadcmd available", True, freecadcmd)

        # Run build script
        sb.files.write("/tmp/build_fixture.py", BUILD_FREECAD_SCRIPT)
        r = run_shell(sb, f"{freecadcmd} -c 'exec(open(\"/tmp/build_fixture.py\").read())'",
                      timeout=180)
        ok = "FIXTURE_OK" in r.stdout
        check("fixture built", ok,
              f"stdout={r.stdout[-300:]} stderr={r.stderr[-300:]}")
        if not ok:
            return

        # Test CLI help + errors (no FCStd dependency)
        test_help(sb)

        # Document/object tests
        test_document_info(sb)
        test_objects(sb)
        test_parameters(sb)

        # Preferences
        test_preferences(sb)

        # Exported files
        test_exported_files(sb)

        # Check-* positive + negative
        test_checks_positive(sb)
        test_checks_negative(sb)

        # JSON sweep
        test_json_sweep(sb)

    except Exception:
        traceback.print_exc()
        global failed
        failed += 1
        errors.append(f"Unhandled: {traceback.format_exc()}")
    finally:
        sb.kill()

    print(f"\n{'='*60}\nResults: {passed} passed, {failed} failed\n{'='*60}")
    if errors:
        for e in errors[:30]:
            print(f"  - {e}")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
