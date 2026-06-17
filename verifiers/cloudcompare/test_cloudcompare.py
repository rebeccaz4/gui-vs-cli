"""
Test CloudCompare verifier endpoints in a live E2B sandbox.

Usage:
    python verifiers/cloudcompare/test_cloudcompare.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "cloudcompare.py"
VERIFIER_REMOTE = "/home/user/verifiers/cloudcompare.py"
V = f"python3 {VERIFIER_REMOTE}"

FIX_DIR = "/home/user/cc_fixtures"
F_ASCII = f"{FIX_DIR}/ascii.ply"
F_BIN = f"{FIX_DIR}/bin.ply"
F_RICH = f"{FIX_DIR}/rich.ply"
F_XYZ = f"{FIX_DIR}/plain.xyz"
F_RGB = f"{FIX_DIR}/rgb.xyz"
F_INT = f"{FIX_DIR}/intensity.xyz"
F_OBJ = f"{FIX_DIR}/mesh.obj"
F_BROKEN = f"{FIX_DIR}/broken.ply"
CONF_PATH = "/home/user/.config/CCorp/CloudCompare.conf"


# ---------------------------------------------------------------------------
# Fixture generator script (runs inside sandbox)
# ---------------------------------------------------------------------------

FIXTURE_SCRIPT = r'''
import os
import struct

FIX = "/home/user/cc_fixtures"
os.makedirs(FIX, exist_ok=True)
os.makedirs("/home/user/.config/CCorp", exist_ok=True)

# ---- ascii.ply: 100 verts, 50 triangles (strip) ----
N = 100
with open(f"{FIX}/ascii.ply", "w") as f:
    f.write("ply\nformat ascii 1.0\n")
    f.write(f"element vertex {N}\n")
    f.write("property float x\nproperty float y\nproperty float z\n")
    f.write("element face 50\n")
    f.write("property list uchar int vertex_indices\n")
    f.write("end_header\n")
    for i in range(N):
        f.write(f"{float(i)} {float(i*2)} {float(i*3)}\n")
    for i in range(50):
        # degenerate triangle fan inside range
        a = i
        b = (i + 1) % N
        c = (i + 2) % N
        f.write(f"3 {a} {b} {c}\n")

# ---- bin.ply: 64 verts in a 4x4x4 grid, little-endian ----
verts = []
for i in range(4):
    for j in range(4):
        for k in range(4):
            verts.append((float(i), float(j), float(k)))
with open(f"{FIX}/bin.ply", "wb") as f:
    f.write(b"ply\n")
    f.write(b"format binary_little_endian 1.0\n")
    f.write(f"element vertex {len(verts)}\n".encode())
    f.write(b"property float x\nproperty float y\nproperty float z\n")
    f.write(b"end_header\n")
    for v in verts:
        f.write(struct.pack("<fff", *v))

# ---- rich.ply: 25 ascii verts with color + normals ----
N = 25
with open(f"{FIX}/rich.ply", "w") as f:
    f.write("ply\nformat ascii 1.0\n")
    f.write(f"element vertex {N}\n")
    f.write("property float x\nproperty float y\nproperty float z\n")
    f.write("property float nx\nproperty float ny\nproperty float nz\n")
    f.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
    f.write("end_header\n")
    for i in range(N):
        f.write(f"{i} {i*0.5} {i*0.25} 0 0 1 {i*10 % 256} 0 {255 - i*10 % 256}\n")

# ---- plain.xyz: 20 pts, 3 cols ----
with open(f"{FIX}/plain.xyz", "w") as f:
    f.write("# plain xyz\n")
    for i in range(20):
        f.write(f"{i} {i+1} {i+2}\n")

# ---- rgb.xyz: 20 pts, 6 cols ----
with open(f"{FIX}/rgb.xyz", "w") as f:
    for i in range(20):
        f.write(f"{i} {i+1} {i+2} {i*10 % 256} 100 200\n")

# ---- intensity.xyz: 20 pts, 4 cols ----
with open(f"{FIX}/intensity.xyz", "w") as f:
    for i in range(20):
        f.write(f"{i} {i+1} {i+2} {i*5}\n")

# ---- mesh.obj: cube with 8 verts, 12 tris, normals ----
with open(f"{FIX}/mesh.obj", "w") as f:
    f.write("# cube\n")
    for x in (0, 1):
        for y in (0, 1):
            for z in (0, 1):
                f.write(f"v {x} {y} {z}\n")
    f.write("vn 0 0 1\nvn 0 0 -1\nvn 0 1 0\nvn 0 -1 0\nvn 1 0 0\nvn -1 0 0\n")
    tris = [
        (1,2,4),(1,4,3),(5,6,8),(5,8,7),
        (1,2,6),(1,6,5),(3,4,8),(3,8,7),
        (1,3,7),(1,7,5),(2,4,8),(2,8,6),
    ]
    for a,b,c in tris:
        f.write(f"f {a} {b} {c}\n")

# ---- broken.ply: does not start with ply magic ----
with open(f"{FIX}/broken.ply", "w") as f:
    f.write("not a ply file\njunk\njunk\n")

# ---- CloudCompare.conf (Qt INI) ----
with open("/home/user/.config/CCorp/CloudCompare.conf", "w") as f:
    f.write("[General]\n")
    f.write("language=en\n")
    f.write("recentFile0=/home/user/Documents/first.ply\n")
    f.write("recentFile1=/home/user/Documents/second.xyz\n")
    f.write("recentFile2=/home/user/Documents/third.obj\n")
    f.write("[Console]\n")
    f.write("showDialogOnError=false\n")
    f.write("[Display]\n")
    f.write("backgroundColor=#202020\n")
    f.write("defaultPointSize=4\n")

print("FIXTURES_READY")
'''


# ---------------------------------------------------------------------------
# Runner plumbing
# ---------------------------------------------------------------------------

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
    r = run_raw(sb, cmd, timeout)
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


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------


def test_help(sb):
    print("\n=== G1 Help ===")
    r = run_raw(sb, "--help")
    check("help exits 0", r.exit_code == 0)
    check("help mentions Commands:", "Commands:" in r.stdout)


def test_errors(sb):
    print("\n=== G2 Errors ===")
    r = run_raw(sb, "nonexistent-command")
    check("unknown cmd exits 1", r.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(r.stdout))

    r = run_raw(sb, "cloud-info")
    check("missing file arg exits 1", r.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(r.stdout))

    d = run(sb, f"cloud-info /nonexistent/nope.ply")
    check("nonexistent file -> error", "error" in d, str(d)[:120])

    d = run(sb, f"cloud-info {F_BROKEN}")
    check("broken PLY -> error", "error" in d, str(d)[:120])


def test_ascii_ply(sb):
    print("\n=== G3 ASCII PLY ===")
    d = run(sb, f"cloud-info {F_ASCII}")
    check("ascii.ply parses", "error" not in d, str(d)[:200])
    if "error" in d:
        return
    check("ascii.ply format=ascii", d.get("format") == "ascii", str(d.get("format")))
    check("ascii.ply vertex_count=100", d.get("vertex_count") == 100, str(d.get("vertex_count")))
    check("ascii.ply face_count=50", d.get("face_count") == 50, str(d.get("face_count")))
    check("ascii.ply has_color=False", d.get("has_color") is False)
    check("ascii.ply bbox min ~= [0,0,0]",
          d["bbox"][0] == [0.0, 0.0, 0.0], str(d.get("bbox")))
    check("ascii.ply bbox max ~= [99,198,297]",
          d["bbox"][1] == [99.0, 198.0, 297.0], str(d.get("bbox")))

    d = run(sb, f"ply-header {F_ASCII}")
    check("ply-header has vertex elem",
          any(e["name"] == "vertex" for e in d.get("elements", [])),
          str(d)[:200])


def test_bin_ply(sb):
    print("\n=== G4 Binary PLY ===")
    d = run(sb, f"cloud-info {F_BIN}")
    check("bin.ply parses", "error" not in d, str(d)[:200])
    if "error" in d:
        return
    check("bin.ply format=binary_little_endian",
          d.get("format") == "binary_little_endian", str(d.get("format")))
    check("bin.ply vertex_count=64", d.get("vertex_count") == 64)
    check("bin.ply bbox min=[0,0,0]", d["bbox"][0] == [0.0, 0.0, 0.0])
    check("bin.ply bbox max=[3,3,3]", d["bbox"][1] == [3.0, 3.0, 3.0])

    d = run(sb, f"check-ply-format {F_BIN} binary_little_endian")
    check("check-ply-format binary=true", d.get("match") is True, str(d)[:120])


def test_rich_ply(sb):
    print("\n=== G5 Rich PLY ===")
    d = run(sb, f"cloud-info {F_RICH}")
    check("rich.ply parses", "error" not in d, str(d)[:200])
    if "error" in d:
        return
    check("rich.ply has_color", d.get("has_color") is True, str(d)[:200])
    check("rich.ply has_normal", d.get("has_normal") is True, str(d)[:200])
    check("rich.ply vertex_count=25", d.get("vertex_count") == 25)

    d = run(sb, f"check-has-color {F_RICH}")
    check("check-has-color rich=true", d.get("has_color") is True, str(d)[:120])

    d = run(sb, f"check-has-normals {F_RICH}")
    check("check-has-normals rich=true", d.get("has_normals") is True, str(d)[:120])


def test_xyz(sb):
    print("\n=== G6 XYZ ASCII ===")
    d = run(sb, f"cloud-info {F_XYZ}")
    check("plain.xyz parses", "error" not in d, str(d)[:200])
    if "error" not in d:
        check("plain.xyz points=20", d.get("points") == 20)
        check("plain.xyz columns=3", d.get("columns") == 3)
        check("plain.xyz has_color=False", d.get("has_color") is False)
        check("plain.xyz has_intensity=False", d.get("has_intensity") is False)

    d = run(sb, f"cloud-info {F_RGB}")
    check("rgb.xyz parses", "error" not in d)
    if "error" not in d:
        check("rgb.xyz columns=6", d.get("columns") == 6)
        check("rgb.xyz has_color=True", d.get("has_color") is True)

    d = run(sb, f"cloud-info {F_INT}")
    check("intensity.xyz parses", "error" not in d)
    if "error" not in d:
        check("intensity.xyz columns=4", d.get("columns") == 4)
        check("intensity.xyz has_intensity=True", d.get("has_intensity") is True)


def test_obj(sb):
    print("\n=== G7 OBJ ===")
    d = run(sb, f"cloud-info {F_OBJ}")
    check("mesh.obj parses", "error" not in d, str(d)[:200])
    if "error" not in d:
        check("mesh.obj vertex_count=8", d.get("vertex_count") == 8, str(d)[:200])
        check("mesh.obj face_count=12", d.get("face_count") == 12, str(d)[:200])
        check("mesh.obj has_normals", d.get("has_normals") is True)
        check("mesh.obj bbox max=[1,1,1]", d["bbox"][1] == [1.0, 1.0, 1.0])

    d = run(sb, f"check-is-mesh {F_OBJ}")
    check("check-is-mesh obj=true", d.get("is_mesh") is True, str(d)[:120])


def test_checks_positive(sb):
    print("\n=== G8 Checks (positive) ===")

    d = run(sb, f"check-file-exists {F_ASCII}")
    check("check-file-exists true", d.get("exists") is True)

    d = run(sb, f"check-file-size {F_ASCII} 10")
    check("check-file-size true", d.get("match") is True)

    d = run(sb, f"check-point-count {F_ASCII} 100")
    check("check-point-count ascii=100", d.get("match") is True, str(d)[:120])

    d = run(sb, f"check-point-count {F_BIN} 64")
    check("check-point-count bin=64", d.get("match") is True, str(d)[:120])

    d = run(sb, f"check-point-count {F_XYZ} 20")
    check("check-point-count xyz=20", d.get("match") is True, str(d)[:120])

    d = run(sb, f"check-point-count-at-least {F_ASCII} 50")
    check("check-point-count-at-least true", d.get("match") is True)

    d = run(sb, f"check-face-count {F_ASCII} 50")
    check("check-face-count ascii=50", d.get("match") is True, str(d)[:120])

    d = run(sb, f"check-face-count {F_OBJ} 12")
    check("check-face-count obj=12", d.get("match") is True, str(d)[:120])

    d = run(sb, f"check-bbox-within {F_BIN} -1 -1 -1 10 10 10")
    check("check-bbox-within loose=true", d.get("match") is True, str(d)[:200])

    d = run(sb, f"check-bbox-min-extent {F_BIN} x 2")
    check("check-bbox-min-extent x>=2 true", d.get("match") is True, str(d)[:200])

    d = run(sb, f"check-has-color {F_RGB}")
    check("check-has-color rgb=true", d.get("has_color") is True)

    d = run(sb, f"check-has-intensity {F_INT}")
    check("check-has-intensity true", d.get("has_intensity") is True)

    d = run(sb, f"check-has-normals {F_OBJ}")
    check("check-has-normals obj=true", d.get("has_normals") is True)

    d = run(sb, f"check-ply-format {F_ASCII} ascii")
    check("check-ply-format ascii=true", d.get("match") is True)

    d = run(sb, f"check-format {F_ASCII} ply")
    check("check-format ply true", d.get("match") is True)

    d = run(sb, f"check-format {F_OBJ} obj")
    check("check-format obj true", d.get("match") is True)

    d = run(sb, f"check-format {F_XYZ} ascii")
    check("check-format ascii true", d.get("match") is True)

    d = run(sb, f"check-is-mesh {F_ASCII}")
    check("check-is-mesh ascii.ply true", d.get("is_mesh") is True)


def test_checks_negative(sb):
    print("\n=== G9 Checks (negative) ===")

    d = run(sb, f"check-file-exists /nope/none.ply")
    check("check-file-exists false", d.get("exists") is False)

    d = run(sb, f"check-point-count {F_ASCII} 777")
    check("check-point-count wrong=false", d.get("match") is False, str(d)[:120])

    d = run(sb, f"check-point-count-at-least {F_ASCII} 999999")
    check("check-point-count-at-least too big=false", d.get("match") is False)

    d = run(sb, f"check-face-count {F_ASCII} 777")
    check("check-face-count wrong=false", d.get("match") is False)

    d = run(sb, f"check-bbox-within {F_BIN} 0 0 0 1 1 1")
    check("check-bbox-within tight=false", d.get("match") is False, str(d)[:200])

    d = run(sb, f"check-bbox-min-extent {F_BIN} x 1000")
    check("check-bbox-min-extent huge=false", d.get("match") is False)

    d = run(sb, f"check-has-color {F_XYZ}")
    check("check-has-color xyz=false", d.get("has_color") is False)

    d = run(sb, f"check-has-intensity {F_XYZ}")
    check("check-has-intensity xyz=false", d.get("has_intensity") is False)

    d = run(sb, f"check-has-normals {F_XYZ}")
    check("check-has-normals xyz=false", d.get("has_normals") is False)

    d = run(sb, f"check-ply-format {F_BIN} ascii")
    check("check-ply-format ascii-false-on-binary", d.get("match") is False)

    d = run(sb, f"check-format {F_OBJ} ply")
    check("check-format ply-false-on-obj", d.get("match") is False)

    d = run(sb, f"check-is-mesh {F_BIN}")
    check("check-is-mesh bin=false", d.get("is_mesh") is False, str(d)[:200])


def test_config(sb):
    print("\n=== G10 Config / Recent files ===")
    d = run(sb, f"settings {CONF_PATH}")
    check("settings exists=true", d.get("exists") is True, str(d)[:200])
    check("settings has General section", "General" in d.get("sections", {}),
          str(list(d.get("sections", {}).keys())))
    check("settings has Display section", "Display" in d.get("sections", {}))

    d = run(sb, f"check-setting Display defaultPointSize 4 {CONF_PATH}")
    check("check-setting true", d.get("match") is True, str(d)[:200])

    d = run(sb, f"check-setting Display defaultPointSize 99 {CONF_PATH}")
    check("check-setting wrong=false", d.get("match") is False, str(d)[:200])

    d = run(sb, f"check-setting General language en {CONF_PATH}")
    check("check-setting language=en true", d.get("match") is True)

    d = run(sb, f"recent-files {CONF_PATH}")
    check("recent-files exists", d.get("exists") is True)
    check("recent-files count=3", d.get("count") == 3, str(d)[:200])

    d = run(sb, f"check-recent-file first.ply {CONF_PATH}")
    check("check-recent-file positive", d.get("match") is True, str(d)[:200])

    d = run(sb, f"check-recent-file totally_missing.xyz {CONF_PATH}")
    check("check-recent-file negative", d.get("match") is False)

    # nonexistent conf
    d = run(sb, "settings /nope/fake.conf")
    check("settings missing path exists=false", d.get("exists") is False)


def test_json_validity(sb):
    print("\n=== G11 JSON validity sweep ===")
    cmds = [
        f"cloud-info {F_ASCII}",
        f"cloud-info {F_BIN}",
        f"cloud-info {F_RICH}",
        f"cloud-info {F_XYZ}",
        f"cloud-info {F_RGB}",
        f"cloud-info {F_INT}",
        f"cloud-info {F_OBJ}",
        f"ply-header {F_ASCII}",
        f"ply-header {F_BIN}",
        f"settings {CONF_PATH}",
        f"recent-files {CONF_PATH}",
        f"check-file-exists {F_ASCII}",
        f"check-file-size {F_ASCII} 10",
        f"check-point-count {F_ASCII} 100",
        f"check-point-count-at-least {F_ASCII} 10",
        f"check-face-count {F_ASCII} 50",
        f"check-bbox-within {F_BIN} -1 -1 -1 10 10 10",
        f"check-bbox-min-extent {F_BIN} x 1",
        f"check-has-color {F_RGB}",
        f"check-has-intensity {F_INT}",
        f"check-has-normals {F_OBJ}",
        f"check-ply-format {F_ASCII} ascii",
        f"check-format {F_OBJ} obj",
        f"check-is-mesh {F_ASCII}",
        f"check-setting General language en {CONF_PATH}",
        f"check-recent-file first.ply {CONF_PATH}",
    ]
    for cmd in cmds:
        r = run_raw(sb, cmd)
        ok = is_valid_json(r.stdout)
        check(f"json ok: {cmd.split()[0]}", ok, f"stdout={r.stdout[:80]}" if not ok else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed
    print("=" * 60)
    print("CloudCompare Verifier — Test Suite")
    print("=" * 60)

    sb = Sandbox.create(template="desktop-all-apps", timeout=600)
    try:
        sb.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sb.files.write(VERIFIER_REMOTE, f.read())

        sb.files.write("/tmp/mk_cc_fixtures.py", FIXTURE_SCRIPT)
        r = run_shell(sb, "python3 /tmp/mk_cc_fixtures.py", timeout=60)
        fixtures_ok = "FIXTURES_READY" in r.stdout
        check("fixtures generated", fixtures_ok,
              f"stdout={r.stdout[-200:]} stderr={r.stderr[:200]}")
        if not fixtures_ok:
            return

        test_help(sb)
        test_errors(sb)
        test_ascii_ply(sb)
        test_bin_ply(sb)
        test_rich_ply(sb)
        test_xyz(sb)
        test_obj(sb)
        test_checks_positive(sb)
        test_checks_negative(sb)
        test_config(sb)
        test_json_validity(sb)

    except Exception:
        traceback.print_exc()
        failed += 1
        errors.append(f"Unhandled: {traceback.format_exc()}")
    finally:
        sb.kill()

    print(f"\n{'='*60}\nResults: {passed} passed, {failed} failed\n{'='*60}")
    if errors:
        for e in errors:
            print(f"  - {e}")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
