"""
Test Inkscape verifier endpoints in a live E2B sandbox.

Creates SVG files with known elements (rectangles, circles, text, paths,
groups, layers, connectors), then tests all verifier endpoints.

Usage:
    python verifiers/inkscape/test_inkscape.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "inkscape.py"
VERIFIER_REMOTE = "/home/user/verifiers/inkscape.py"
V = f"python3 {VERIFIER_REMOTE}"
TEST_SVG = "/home/user/test_drawing.svg"

# A test SVG with known structure: rectangles, circles, text, paths, groups, layers, connectors
TEST_SVG_CONTENT = r'''<?xml version="1.0" encoding="UTF-8"?>
<svg
   xmlns="http://www.w3.org/2000/svg"
   xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
   xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
   xmlns:xlink="http://www.w3.org/1999/xlink"
   width="800"
   height="600"
   viewBox="0 0 800 600"
   id="root_svg">
  <sodipodi:namedview
     id="namedview1"
     pagecolor="#ffffff"
     bordercolor="#000000" />
  <defs id="defs1">
    <marker id="arrow1" orient="auto">
      <path d="M 0 0 L 10 5 L 0 10 z" />
    </marker>
  </defs>
  <g
     inkscape:groupmode="layer"
     inkscape:label="Background"
     id="layer_bg"
     style="display:inline">
    <rect
       id="bg_rect"
       width="800"
       height="600"
       x="0"
       y="0"
       style="fill:#eeeeee;stroke:none" />
  </g>
  <g
     inkscape:groupmode="layer"
     inkscape:label="Shapes"
     id="layer_shapes"
     style="display:inline">
    <rect
       id="red_rect"
       width="100"
       height="80"
       x="50"
       y="50"
       rx="5"
       ry="5"
       style="fill:#ff0000;stroke:#000000;stroke-width:2"
       transform="rotate(15 100 90)" />
    <circle
       id="blue_circle"
       cx="300"
       cy="200"
       r="60"
       style="fill:#0000ff;stroke:#333333;stroke-width:1" />
    <ellipse
       id="green_ellipse"
       cx="500"
       cy="200"
       rx="80"
       ry="40"
       style="fill:#00ff00;opacity:0.8" />
  </g>
  <g
     inkscape:groupmode="layer"
     inkscape:label="Text"
     id="layer_text"
     style="display:inline">
    <text
       id="title_text"
       x="400"
       y="50"
       style="font-size:24px;font-family:sans-serif;text-anchor:middle;fill:#000000">Hello Inkscape</text>
    <text
       id="label_text"
       x="50"
       y="400"
       style="font-size:14px;fill:#666666">A test label</text>
  </g>
  <g
     id="group_arrows"
     inkscape:label="Arrows">
    <path
       id="path_wave"
       d="M 10 300 C 50 250, 90 350, 130 300 S 210 250, 250 300"
       style="fill:none;stroke:#ff6600;stroke-width:3" />
    <path
       id="connector1"
       d="M 150 90 L 240 200"
       style="fill:none;stroke:#000000;stroke-width:1"
       inkscape:connector-type="polyline"
       inkscape:connection-start="#red_rect"
       inkscape:connection-end="#blue_circle" />
  </g>
</svg>
'''

passed = 0
failed = 0
errors: list[str] = []


class CmdResult:
    def __init__(self, exit_code, stdout, stderr):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def run(sb, cmd, timeout=60):
    r = run_raw(sb, cmd, timeout)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


def run_raw(sb, cmd, timeout=60):
    try:
        result = sb.commands.run(f"{V} {cmd}", timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


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


def test_help(sb):
    print("\n=== Help ===")
    r = run_raw(sb, "--help")
    check("help exits 0", r.exit_code == 0)
    check("help mentions commands", "Commands:" in r.stdout)


def test_errors(sb):
    print("\n=== Errors ===")
    r = run_raw(sb, "elements")
    check("missing file arg exits 1", r.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(r.stdout))

    data = run(sb, "elements /nonexistent/file.svg")
    check("nonexistent file returns error", "error" in data, str(data)[:100])

    r = run_raw(sb, "nonexistent-command test.svg")
    check("unknown cmd exits 1", r.exit_code == 1)


def test_elements(sb):
    print("\n=== Elements ===")
    data = run(sb, f"elements {TEST_SVG}")
    check("elements returns dict", isinstance(data, dict) and "error" not in data, str(data)[:200])
    if "error" not in data:
        check("elements count > 0", data.get("count", 0) > 0, f"count={data.get('count')}")
        ids = [e["id"] for e in data.get("elements", [])]
        check("red_rect in elements", "red_rect" in ids, str(ids))
        check("blue_circle in elements", "blue_circle" in ids, str(ids))
        check("title_text in elements", "title_text" in ids, str(ids))


def test_element_info(sb):
    print("\n=== Element Info ===")
    data = run(sb, f"element-info {TEST_SVG} red_rect")
    check("element-info works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("tag is rect", data.get("tag") == "rect")
        check("has attributes", "attributes" in data)
        check("has style_parsed", "style_parsed" in data)
        attrs = data.get("attributes", {})
        check("width is 100", attrs.get("width") == "100")

    data = run(sb, f"element-info {TEST_SVG} nonexistent_id")
    check("nonexistent element returns error", "error" in data, str(data)[:100])


def test_text_content(sb):
    print("\n=== Text Content ===")
    data = run(sb, f"text-content {TEST_SVG}")
    check("text-content works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("text count is 2", data.get("count") == 2, f"count={data.get('count')}")
        texts = [t["text"] for t in data.get("texts", [])]
        check("Hello Inkscape in texts", any("Hello Inkscape" in t for t in texts), str(texts))
        check("A test label in texts", any("A test label" in t for t in texts), str(texts))


def test_layers(sb):
    print("\n=== Layers ===")
    data = run(sb, f"layers {TEST_SVG}")
    check("layers works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("layer count is 3", data.get("count") == 3, f"count={data.get('count')}")
        labels = [l["label"] for l in data.get("layers", [])]
        check("Background layer exists", "Background" in labels, str(labels))
        check("Shapes layer exists", "Shapes" in labels, str(labels))
        check("Text layer exists", "Text" in labels, str(labels))


def test_page_info(sb):
    print("\n=== Page Info ===")
    data = run(sb, f"page-info {TEST_SVG}")
    check("page-info works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("width is 800", data.get("width") == "800")
        check("height is 600", data.get("height") == "600")
        check("viewBox is correct", data.get("viewBox") == "0 0 800 600")
        check("page_color is white", data.get("page_color") == "#ffffff")


def test_styles(sb):
    print("\n=== Styles ===")
    # Specific element
    data = run(sb, f"styles {TEST_SVG} red_rect")
    check("styles for element works", "error" not in data, str(data)[:200])
    if "error" not in data:
        parsed = data.get("style_parsed", {})
        check("fill is #ff0000", parsed.get("fill") == "#ff0000", str(parsed))
        check("stroke is #000000", parsed.get("stroke") == "#000000", str(parsed))

    # All styled elements
    data = run(sb, f"styles {TEST_SVG}")
    check("styles all works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("styled count > 0", data.get("count", 0) > 0)

    # Nonexistent element
    data = run(sb, f"styles {TEST_SVG} nonexistent_id")
    check("styles nonexistent returns error", "error" in data, str(data)[:100])


def test_paths(sb):
    print("\n=== Paths ===")
    data = run(sb, f"paths {TEST_SVG}")
    check("paths works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("paths count > 0", data.get("count", 0) > 0, f"count={data.get('count')}")
        ids = [p["id"] for p in data.get("paths", [])]
        check("path_wave in paths", "path_wave" in ids, str(ids))


def test_groups(sb):
    print("\n=== Groups ===")
    data = run(sb, f"groups {TEST_SVG}")
    check("groups works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("groups count > 0", data.get("count", 0) > 0, f"count={data.get('count')}")
        ids = [g["id"] for g in data.get("groups", [])]
        check("layer_shapes in groups", "layer_shapes" in ids, str(ids))
        check("group_arrows in groups", "group_arrows" in ids, str(ids))
        # Check that layer groups have groupmode
        for g in data.get("groups", []):
            if g["id"] == "layer_shapes":
                check("layer_shapes has groupmode=layer", g.get("groupmode") == "layer")
                break


def test_connections(sb):
    print("\n=== Connections ===")
    data = run(sb, f"connections {TEST_SVG}")
    check("connections works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("connections count is 1", data.get("count") == 1, f"count={data.get('count')}")
        if data.get("count", 0) > 0:
            conn = data["connections"][0]
            check("connector start is red_rect", conn.get("start") == "red_rect", str(conn))
            check("connector end is blue_circle", conn.get("end") == "blue_circle", str(conn))
            check("connector type is polyline", conn.get("type") == "polyline", str(conn))


def test_checks_positive(sb):
    print("\n=== Checks (positive) ===")

    data = run(sb, f"check-file-exists {TEST_SVG}")
    check("check-file-exists=true", data.get("exists") is True, str(data)[:100])

    data = run(sb, f"check-element-exists {TEST_SVG} red_rect")
    check("check-element-exists red_rect=true", data.get("exists") is True, str(data)[:100])

    data = run(sb, f"check-text-contains {TEST_SVG} 'Hello Inkscape'")
    check("check-text-contains Hello=true", data.get("contains") is True, str(data)[:100])

    data = run(sb, f"check-layer-exists {TEST_SVG} Shapes")
    check("check-layer-exists Shapes=true", data.get("exists") is True, str(data)[:100])

    data = run(sb, f"check-layer-count {TEST_SVG} 3")
    check("check-layer-count 3=true", data.get("match") is True, str(data)[:100])

    data = run(sb, f"check-page-size {TEST_SVG} 800 600")
    check("check-page-size 800x600=true", data.get("match") is True, str(data)[:100])

    data = run(sb, f"check-element-attribute {TEST_SVG} red_rect width 100")
    check("check-element-attribute width=100 true", data.get("match") is True, str(data)[:100])

    data = run(sb, f"check-style-property {TEST_SVG} red_rect fill '#ff0000'")
    check("check-style-property fill=#ff0000 true", data.get("match") is True, str(data)[:100])

    data = run(sb, f"check-has-element-type {TEST_SVG} rect")
    check("check-has-element-type rect=true", data.get("exists") is True, str(data)[:100])

    data = run(sb, f"check-has-element-type {TEST_SVG} circle")
    check("check-has-element-type circle=true", data.get("exists") is True, str(data)[:100])

    data = run(sb, f"check-has-element-type {TEST_SVG} text")
    check("check-has-element-type text=true", data.get("exists") is True, str(data)[:100])

    data = run(sb, f"check-has-element-type {TEST_SVG} path")
    check("check-has-element-type path=true", data.get("exists") is True, str(data)[:100])


def test_checks_negative(sb):
    print("\n=== Checks (negative) ===")

    data = run(sb, f"check-file-exists /nonexistent/file.svg")
    check("check-file-exists nonexistent=false", data.get("exists") is False, str(data)[:100])

    data = run(sb, f"check-element-exists {TEST_SVG} nonexistent_id")
    check("check-element-exists nonexistent=false", data.get("exists") is False, str(data)[:100])

    data = run(sb, f"check-text-contains {TEST_SVG} 'ZZZNOTHERE'")
    check("check-text-contains missing=false", data.get("contains") is False, str(data)[:100])

    data = run(sb, f"check-layer-exists {TEST_SVG} NonExistentLayer")
    check("check-layer-exists nonexistent=false", data.get("exists") is False, str(data)[:100])

    data = run(sb, f"check-layer-count {TEST_SVG} 99")
    check("check-layer-count wrong=false", data.get("match") is False, str(data)[:100])

    data = run(sb, f"check-page-size {TEST_SVG} 1024 768")
    check("check-page-size wrong=false", data.get("match") is False, str(data)[:100])

    data = run(sb, f"check-element-attribute {TEST_SVG} red_rect width 999")
    check("check-element-attribute wrong=false", data.get("match") is False, str(data)[:100])

    data = run(sb, f"check-style-property {TEST_SVG} red_rect fill '#00ff00'")
    check("check-style-property wrong=false", data.get("match") is False, str(data)[:100])

    data = run(sb, f"check-has-element-type {TEST_SVG} polygon")
    check("check-has-element-type polygon=false", data.get("exists") is False, str(data)[:100])


def test_all_json(sb):
    print("\n=== JSON validity ===")
    cmds = [
        f"elements {TEST_SVG}",
        f"element-info {TEST_SVG} red_rect",
        f"text-content {TEST_SVG}",
        f"layers {TEST_SVG}",
        f"page-info {TEST_SVG}",
        f"styles {TEST_SVG}",
        f"styles {TEST_SVG} red_rect",
        f"paths {TEST_SVG}",
        f"groups {TEST_SVG}",
        f"connections {TEST_SVG}",
        f"check-file-exists {TEST_SVG}",
        f"check-element-exists {TEST_SVG} red_rect",
        f"check-element-count {TEST_SVG} 1",
        f"check-text-contains {TEST_SVG} Hello",
        f"check-layer-exists {TEST_SVG} Shapes",
        f"check-layer-count {TEST_SVG} 3",
        f"check-page-size {TEST_SVG} 800 600",
        f"check-element-attribute {TEST_SVG} red_rect width 100",
        f"check-style-property {TEST_SVG} red_rect fill '#ff0000'",
        f"check-has-element-type {TEST_SVG} rect",
    ]
    for cmd in cmds:
        r = run_raw(sb, cmd)
        check(f"{cmd.split()[0]} valid JSON", is_valid_json(r.stdout),
              f"stdout={r.stdout[:80]}" if not is_valid_json(r.stdout) else "")


def main():
    global passed, failed
    print("=" * 60)
    print("Inkscape Verifier Test Suite")
    print("=" * 60)

    sb = Sandbox.create(template="desktop-all-apps", timeout=600)
    try:
        sb.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sb.files.write(VERIFIER_REMOTE, f.read())

        test_help(sb)
        test_errors(sb)

        # Write test SVG file into sandbox
        print("\n  Creating test SVG file...")
        sb.files.write(TEST_SVG, TEST_SVG_CONTENT)
        r = run_shell(sb, f"test -f {TEST_SVG} && echo SVG_CREATED")
        svg_ok = "SVG_CREATED" in r.stdout
        check("SVG file created", svg_ok, f"stdout={r.stdout[:200]} stderr={r.stderr[:200]}")

        if svg_ok:
            test_elements(sb)
            test_element_info(sb)
            test_text_content(sb)
            test_layers(sb)
            test_page_info(sb)
            test_styles(sb)
            test_paths(sb)
            test_groups(sb)
            test_connections(sb)
            test_checks_positive(sb)
            test_checks_negative(sb)
            test_all_json(sb)

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
