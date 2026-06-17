"""
Test Draw.io verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (bad file, missing args, unknown command)
  - Query endpoints (diagrams, cells, vertices, edges, cell-info, labels, connections, styles)
  - Check endpoints (all check-* commands, positive and negative)
  - Multi-page diagrams

Usage:
    python verifiers/drawio/test_drawio.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "drawio.py"
VERIFIER_REMOTE = "/home/user/verifiers/drawio.py"
V = f"python3 {VERIFIER_REMOTE}"

# ---------------------------------------------------------------------------
# Test .drawio XML fixtures
# ---------------------------------------------------------------------------

# Simple inline diagram: 3 vertices (Start, Process, End), 2 edges
SIMPLE_DRAWIO = """\
<mxfile>
  <diagram name="Page-1" id="page1">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="2" value="Start" style="ellipse;fillColor=#d5e8d4;strokeColor=#82b366" vertex="1" parent="1">
          <mxGeometry x="100" y="100" width="120" height="60" as="geometry"/>
        </mxCell>
        <mxCell id="3" value="Process" style="rounded=1;fillColor=#dae8fc;strokeColor=#6c8ebf" vertex="1" parent="1">
          <mxGeometry x="100" y="220" width="120" height="60" as="geometry"/>
        </mxCell>
        <mxCell id="4" value="End" style="ellipse;fillColor=#f8cecc;strokeColor=#b85450" vertex="1" parent="1">
          <mxGeometry x="100" y="340" width="120" height="60" as="geometry"/>
        </mxCell>
        <mxCell id="5" value="goes to" style="edgeStyle=orthogonalEdgeStyle" edge="1" source="2" target="3" parent="1">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="6" value="" style="edgeStyle=orthogonalEdgeStyle" edge="1" source="3" target="4" parent="1">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""

# Multi-page diagram: 2 pages with different content
MULTIPAGE_DRAWIO = """\
<mxfile>
  <diagram name="Overview" id="overview1">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="2" value="Box A" style="rounded=0;fillColor=#fff2cc" vertex="1" parent="1">
          <mxGeometry x="50" y="50" width="100" height="50" as="geometry"/>
        </mxCell>
        <mxCell id="3" value="Box B" style="rounded=0;fillColor=#e1d5e7" vertex="1" parent="1">
          <mxGeometry x="200" y="50" width="100" height="50" as="geometry"/>
        </mxCell>
        <mxCell id="4" edge="1" source="2" target="3" parent="1">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
  <diagram name="Detail" id="detail1">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="10" value="Detail Node" style="shape=hexagon;fillColor=#f0f0f0" vertex="1" parent="1">
          <mxGeometry x="100" y="100" width="150" height="80" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""

# Empty diagram (valid mxfile, but no user cells)
EMPTY_DRAWIO = """\
<mxfile>
  <diagram name="Empty" id="empty1">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""

TEST_FILE = "/home/user/test_simple.drawio"
MULTIPAGE_FILE = "/home/user/test_multipage.drawio"
EMPTY_FILE = "/home/user/test_empty.drawio"

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
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    """--help should print usage and exit 0."""
    print("\n=== Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
    check("help mentions commands", "Commands:" in result.stdout, result.stdout[:100])
    check("help mentions drawio", "Draw.io" in result.stdout or "drawio" in result.stdout.lower(),
          result.stdout[:100])


def test_errors(sandbox: Sandbox):
    """Error cases: missing file, missing args, unknown command."""
    print("\n=== Errors ===")

    # Unknown command
    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Missing required arg (diagrams needs a file)
    result = run_raw(sandbox, "diagrams")
    check("missing arg exits 1", result.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Nonexistent file
    data = run(sandbox, "diagrams /nonexistent/file.drawio")
    check("nonexistent file returns error", "error" in (data if isinstance(data, dict) else {}),
          str(data)[:100])

    # Invalid file (not XML)
    sandbox.files.write("/home/user/bad.drawio", "this is not xml")
    data = run(sandbox, "diagrams /home/user/bad.drawio")
    check("invalid xml returns error", "error" in (data if isinstance(data, dict) else {}),
          str(data)[:100])


def test_query_diagrams(sandbox: Sandbox):
    """Test the diagrams command."""
    print("\n=== Query: diagrams ===")

    data = run(sandbox, f"diagrams {TEST_FILE}")
    check("diagrams returns list", isinstance(data, list), str(type(data)))
    check("diagrams has 1 page", len(data) == 1, f"got {len(data)}")
    if data:
        check("page name is Page-1", data[0].get("name") == "Page-1", str(data[0]))
        check("page has id", data[0].get("id") == "page1", str(data[0]))

    # Multi-page
    data = run(sandbox, f"diagrams {MULTIPAGE_FILE}")
    check("multipage has 2 pages", len(data) == 2, f"got {len(data)}")
    if len(data) >= 2:
        check("page 0 name=Overview", data[0].get("name") == "Overview", str(data[0]))
        check("page 1 name=Detail", data[1].get("name") == "Detail", str(data[1]))


def test_query_cells(sandbox: Sandbox):
    """Test cells, vertices, edges commands."""
    print("\n=== Query: cells/vertices/edges ===")

    # cells - should include root cells (0, 1) + 3 vertices + 2 edges = 7
    data = run(sandbox, f"cells {TEST_FILE}")
    check("cells returns list", isinstance(data, list), str(type(data)))
    check("cells count is 7", len(data) == 7, f"got {len(data)}")

    # vertices - should be 3 (Start, Process, End)
    data = run(sandbox, f"vertices {TEST_FILE}")
    check("vertices returns list", isinstance(data, list), str(type(data)))
    check("vertex count is 3", len(data) == 3, f"got {len(data)}")
    ids = {c["id"] for c in data}
    check("vertex ids are 2,3,4", ids == {"2", "3", "4"}, str(ids))
    for v_cell in data:
        check(f"vertex {v_cell['id']} has vertex=true", v_cell["vertex"] is True, str(v_cell))

    # edges - should be 2
    data = run(sandbox, f"edges {TEST_FILE}")
    check("edges returns list", isinstance(data, list), str(type(data)))
    check("edge count is 2", len(data) == 2, f"got {len(data)}")
    for e_cell in data:
        check(f"edge {e_cell['id']} has edge=true", e_cell["edge"] is True, str(e_cell))


def test_query_cell_info(sandbox: Sandbox):
    """Test cell-info command."""
    print("\n=== Query: cell-info ===")

    data = run(sandbox, f"cell-info {TEST_FILE} 2")
    check("cell-info returns dict", isinstance(data, dict), str(type(data)))
    check("cell-info id=2", data.get("id") == "2", str(data))
    check("cell-info value=Start", data.get("value") == "Start", str(data.get("value")))
    check("cell-info vertex=true", data.get("vertex") is True, str(data))
    check("cell-info has geometry", "geometry" in data, str(data.keys()))

    # Edge cell
    data = run(sandbox, f"cell-info {TEST_FILE} 5")
    check("edge cell-info edge=true", data.get("edge") is True, str(data))
    check("edge cell-info source=2", data.get("source") == "2", str(data))
    check("edge cell-info target=3", data.get("target") == "3", str(data))

    # Nonexistent cell
    data = run(sandbox, f"cell-info {TEST_FILE} 999")
    check("nonexistent cell returns error", "error" in data, str(data)[:100])


def test_query_labels(sandbox: Sandbox):
    """Test labels command."""
    print("\n=== Query: labels ===")

    data = run(sandbox, f"labels {TEST_FILE}")
    check("labels returns list", isinstance(data, list), str(type(data)))
    label_texts = {item["label"] for item in data}
    check("labels contains Start", "Start" in label_texts, str(label_texts))
    check("labels contains Process", "Process" in label_texts, str(label_texts))
    check("labels contains End", "End" in label_texts, str(label_texts))
    check("labels contains 'goes to'", "goes to" in label_texts, str(label_texts))


def test_query_connections(sandbox: Sandbox):
    """Test connections command."""
    print("\n=== Query: connections ===")

    data = run(sandbox, f"connections {TEST_FILE}")
    check("connections returns list", isinstance(data, list), str(type(data)))
    check("connection count is 2", len(data) == 2, f"got {len(data)}")

    # Check specific connections
    conn_pairs = {(c["source"], c["target"]) for c in data}
    check("connection 2->3 exists", ("2", "3") in conn_pairs, str(conn_pairs))
    check("connection 3->4 exists", ("3", "4") in conn_pairs, str(conn_pairs))


def test_query_styles(sandbox: Sandbox):
    """Test styles command."""
    print("\n=== Query: styles ===")

    # Cell 2: "ellipse;fillColor=#d5e8d4;strokeColor=#82b366"
    data = run(sandbox, f"styles {TEST_FILE} 2")
    check("styles returns dict", isinstance(data, dict), str(type(data)))
    check("style has _shape=ellipse", data.get("_shape") == "ellipse", str(data))
    check("style fillColor=#d5e8d4", data.get("fillColor") == "#d5e8d4", str(data))
    check("style strokeColor=#82b366", data.get("strokeColor") == "#82b366", str(data))

    # Cell 3: "rounded=1;fillColor=#dae8fc;strokeColor=#6c8ebf"
    data = run(sandbox, f"styles {TEST_FILE} 3")
    check("rounded style has rounded=1", data.get("rounded") == "1", str(data))

    # Nonexistent cell
    data = run(sandbox, f"styles {TEST_FILE} 999")
    check("nonexistent cell styles returns error", "error" in data, str(data)[:100])


def test_checks_positive(sandbox: Sandbox):
    """Check endpoints — positive cases (should return true/match)."""
    print("\n=== Checks (positive) ===")

    # check-file-exists
    data = run(sandbox, f"check-file-exists {TEST_FILE}")
    check("check-file-exists exists=true", data.get("exists") is True, str(data))
    check("check-file-exists valid=true", data.get("valid") is True, str(data))
    check("check-file-exists page_count=1", data.get("page_count") == 1, str(data))

    # check-cell-exists
    data = run(sandbox, f"check-cell-exists {TEST_FILE} 2")
    check("check-cell-exists exists=true", data.get("exists") is True, str(data))
    check("check-cell-exists has cell data", data.get("cell") is not None, str(data)[:100])

    # check-label-exists
    data = run(sandbox, f"check-label-exists {TEST_FILE} Start")
    check("check-label-exists exists=true", data.get("exists") is True, str(data))
    check("check-label-exists has matches", len(data.get("matches", [])) > 0, str(data)[:100])

    # check-connection-exists
    data = run(sandbox, f"check-connection-exists {TEST_FILE} 2 3")
    check("check-connection-exists exists=true", data.get("exists") is True, str(data))
    check("check-connection-exists edge_id=5", data.get("edge_id") == "5", str(data))

    # check-cell-count (7 total: 0, 1, 2, 3, 4, 5, 6)
    data = run(sandbox, f"check-cell-count {TEST_FILE} 7")
    check("check-cell-count match=true", data.get("match") is True, str(data))

    # check-vertex-count (3: cells 2, 3, 4)
    data = run(sandbox, f"check-vertex-count {TEST_FILE} 3")
    check("check-vertex-count match=true", data.get("match") is True, str(data))

    # check-edge-count (2: cells 5, 6)
    data = run(sandbox, f"check-edge-count {TEST_FILE} 2")
    check("check-edge-count match=true", data.get("match") is True, str(data))

    # check-page-count
    data = run(sandbox, f"check-page-count {MULTIPAGE_FILE} 2")
    check("check-page-count match=true", data.get("match") is True, str(data))

    # check-style-property
    data = run(sandbox, f"check-style-property {TEST_FILE} 2 fillColor '#d5e8d4'")
    check("check-style-property match=true", data.get("match") is True, str(data))


def test_checks_negative(sandbox: Sandbox):
    """Check endpoints — negative cases (should return false/no match)."""
    print("\n=== Checks (negative) ===")

    # check-file-exists for missing file
    data = run(sandbox, "check-file-exists /nonexistent/file.drawio")
    check("check-file-exists exists=false", data.get("exists") is False, str(data))

    # check-cell-exists for missing cell
    data = run(sandbox, f"check-cell-exists {TEST_FILE} 999")
    check("check-cell-exists exists=false", data.get("exists") is False, str(data))

    # check-label-exists for missing label
    data = run(sandbox, f"check-label-exists {TEST_FILE} NonexistentLabel12345")
    check("check-label-exists exists=false", data.get("exists") is False, str(data))
    check("check-label-exists matches empty", len(data.get("matches", [])) == 0, str(data)[:100])

    # check-connection-exists for missing connection
    data = run(sandbox, f"check-connection-exists {TEST_FILE} 4 2")
    check("check-connection-exists exists=false (reversed)", data.get("exists") is False, str(data))

    data = run(sandbox, f"check-connection-exists {TEST_FILE} 2 4")
    check("check-connection-exists exists=false (no direct)", data.get("exists") is False, str(data))

    # check-cell-count wrong number
    data = run(sandbox, f"check-cell-count {TEST_FILE} 99")
    check("check-cell-count match=false", data.get("match") is False, str(data))
    check("check-cell-count actual=7", data.get("actual") == 7, str(data))

    # check-vertex-count wrong number
    data = run(sandbox, f"check-vertex-count {TEST_FILE} 10")
    check("check-vertex-count match=false", data.get("match") is False, str(data))

    # check-edge-count wrong number
    data = run(sandbox, f"check-edge-count {TEST_FILE} 0")
    check("check-edge-count match=false", data.get("match") is False, str(data))

    # check-page-count wrong number
    data = run(sandbox, f"check-page-count {TEST_FILE} 5")
    check("check-page-count match=false", data.get("match") is False, str(data))

    # check-style-property wrong value
    data = run(sandbox, f"check-style-property {TEST_FILE} 2 fillColor '#000000'")
    check("check-style-property match=false", data.get("match") is False, str(data))
    check("check-style-property actual=#d5e8d4", data.get("actual") == "#d5e8d4", str(data))

    # check-style-property for nonexistent property
    data = run(sandbox, f"check-style-property {TEST_FILE} 2 nonExistentProp value")
    check("check-style-property match=false (no prop)", data.get("match") is False, str(data))
    check("check-style-property actual=None", data.get("actual") is None, str(data))


def test_multipage(sandbox: Sandbox):
    """Test multi-page diagram operations."""
    print("\n=== Multi-page ===")

    # Page 0: 2 vertices (Box A, Box B) + 1 edge + 2 root cells = 5
    data = run(sandbox, f"cells {MULTIPAGE_FILE} 0")
    check("page 0 cell count=5", len(data) == 5, f"got {len(data)}")

    data = run(sandbox, f"vertices {MULTIPAGE_FILE} 0")
    check("page 0 vertex count=2", len(data) == 2, f"got {len(data)}")

    # Page 1: 1 vertex (Detail Node) + 2 root cells = 3
    data = run(sandbox, f"cells {MULTIPAGE_FILE} 1")
    check("page 1 cell count=3", len(data) == 3, f"got {len(data)}")

    data = run(sandbox, f"vertices {MULTIPAGE_FILE} 1")
    check("page 1 vertex count=1", len(data) == 1, f"got {len(data)}")
    if data:
        check("page 1 vertex value=Detail Node", data[0].get("value") == "Detail Node",
              str(data[0].get("value")))

    # Labels on page 0
    data = run(sandbox, f"labels {MULTIPAGE_FILE} 0")
    label_texts = {item["label"] for item in data}
    check("page 0 has Box A", "Box A" in label_texts, str(label_texts))
    check("page 0 has Box B", "Box B" in label_texts, str(label_texts))

    # Connections on page 0
    data = run(sandbox, f"connections {MULTIPAGE_FILE} 0")
    check("page 0 connections count=1", len(data) == 1, f"got {len(data)}")

    # Connections on page 1 (none)
    data = run(sandbox, f"connections {MULTIPAGE_FILE} 1")
    check("page 1 connections count=0", len(data) == 0, f"got {len(data)}")

    # Styles on page 1
    data = run(sandbox, f"styles {MULTIPAGE_FILE} 10 1")
    check("page 1 cell 10 has shape=hexagon", data.get("shape") == "hexagon", str(data))


def test_empty_diagram(sandbox: Sandbox):
    """Test with an empty diagram (only root cells)."""
    print("\n=== Empty diagram ===")

    data = run(sandbox, f"vertices {EMPTY_FILE}")
    check("empty diagram has 0 vertices", len(data) == 0, f"got {len(data)}")

    data = run(sandbox, f"edges {EMPTY_FILE}")
    check("empty diagram has 0 edges", len(data) == 0, f"got {len(data)}")

    data = run(sandbox, f"labels {EMPTY_FILE}")
    check("empty diagram has 0 labels", len(data) == 0, f"got {len(data)}")

    data = run(sandbox, f"connections {EMPTY_FILE}")
    check("empty diagram has 0 connections", len(data) == 0, f"got {len(data)}")

    data = run(sandbox, f"check-vertex-count {EMPTY_FILE} 0")
    check("empty vertex count match=true", data.get("match") is True, str(data))


def test_all_commands_return_json(sandbox: Sandbox):
    """Every CLI command should output valid JSON (not crash with a traceback)."""
    print("\n=== JSON validity (all commands) ===")

    # Commands with file arg only
    file_cmds = ["diagrams", "cells", "vertices", "edges", "labels", "connections"]
    for cmd in file_cmds:
        result = run_raw(sandbox, f"{cmd} {TEST_FILE}")
        valid = is_valid_json(result.stdout)
        check(f"{cmd} returns valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # Commands with file + cell_id
    cell_cmds = [("cell-info", "2"), ("styles", "2")]
    for cmd, cell_id in cell_cmds:
        result = run_raw(sandbox, f"{cmd} {TEST_FILE} {cell_id}")
        valid = is_valid_json(result.stdout)
        check(f"{cmd} {cell_id} returns valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # Check commands
    check_cmds = [
        f"check-file-exists {TEST_FILE}",
        f"check-cell-exists {TEST_FILE} 2",
        f"check-label-exists {TEST_FILE} Start",
        f"check-connection-exists {TEST_FILE} 2 3",
        f"check-cell-count {TEST_FILE} 7",
        f"check-vertex-count {TEST_FILE} 3",
        f"check-edge-count {TEST_FILE} 2",
        f"check-page-count {TEST_FILE} 1",
        f"check-style-property {TEST_FILE} 2 fillColor '#d5e8d4'",
    ]
    for cmd_str in check_cmds:
        cmd_name = cmd_str.split()[0]
        result = run_raw(sandbox, cmd_str)
        valid = is_valid_json(result.stdout)
        check(f"{cmd_name} returns valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed

    print("=" * 60)
    print("Draw.io Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # Upload test fixtures
        print("Uploading test .drawio fixtures...")
        sandbox.files.write(TEST_FILE, SIMPLE_DRAWIO)
        sandbox.files.write(MULTIPAGE_FILE, MULTIPAGE_DRAWIO)
        sandbox.files.write(EMPTY_FILE, EMPTY_DRAWIO)

        # --- Run tests ---
        test_help(sandbox)
        test_errors(sandbox)
        test_query_diagrams(sandbox)
        test_query_cells(sandbox)
        test_query_cell_info(sandbox)
        test_query_labels(sandbox)
        test_query_connections(sandbox)
        test_query_styles(sandbox)
        test_checks_positive(sandbox)
        test_checks_negative(sandbox)
        test_multipage(sandbox)
        test_empty_diagram(sandbox)
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
