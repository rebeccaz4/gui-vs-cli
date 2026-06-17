"""
Draw.io Verifier — programmatic state inspection for draw.io (.drawio) files.

Verification channel:
  XML file parsing — .drawio files are XML with <mxfile> root, <diagram> elements,
  and <mxCell> elements representing shapes (vertices) and connections (edges).

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/drawio.py diagrams /path/to/file.drawio")
    sandbox.commands.run("python3 /home/user/verifiers/drawio.py cells /path/to/file.drawio")
    sandbox.commands.run("python3 /home/user/verifiers/drawio.py check-cell-exists /path/to/file.drawio 3")

Usage from Python (inside sandbox or via E2B):
    from verifiers.drawio import DrawioVerifier
    v = DrawioVerifier()
    diagrams = v.get_diagrams("/path/to/file.drawio")
    cells = v.get_cells("/path/to/file.drawio")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - xml.etree.ElementTree (standard library)
  - base64, zlib, urllib.parse (standard library)
"""

import base64
import json
import os
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from typing import Any


# ---------------------------------------------------------------------------
# XML decoding helpers
# ---------------------------------------------------------------------------

def _decode_diagram_content(encoded: str) -> ET.Element:
    """Decode base64+deflate encoded diagram content to an mxGraphModel Element.

    draw.io encodes diagram XML as: URL-encode -> deflate -> base64.
    To decode: base64 -> deflate decompress -> URL-decode -> XML.
    """
    # base64 decode
    raw = base64.b64decode(encoded)
    # deflate decompress (raw deflate, wbits=-15 for raw; try -15 first, then auto)
    try:
        decompressed = zlib.decompress(raw, -zlib.MAX_WBITS)
    except zlib.error:
        decompressed = zlib.decompress(raw)
    # URL-decode
    xml_str = urllib.parse.unquote(decompressed.decode("utf-8"))
    return ET.fromstring(xml_str)


def _parse_drawio(filepath: str) -> ET.Element:
    """Parse a .drawio file and return the root <mxfile> element."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")
    tree = ET.parse(filepath)
    root = tree.getroot()
    if root.tag != "mxfile":
        raise ValueError(f"Not a valid .drawio file: root element is <{root.tag}>, expected <mxfile>")
    return root


def _get_graph_model(root: ET.Element, page_index: int = 0) -> ET.Element | None:
    """Get the <mxGraphModel> element for a specific diagram page.

    Handles both inline XML and base64+deflate encoded content.
    """
    diagrams = root.findall("diagram")
    if page_index < 0 or page_index >= len(diagrams):
        return None
    diagram = diagrams[page_index]

    # Check for inline mxGraphModel child
    model = diagram.find("mxGraphModel")
    if model is not None:
        return model

    # Try decoding encoded content
    text = (diagram.text or "").strip()
    if text:
        try:
            return _decode_diagram_content(text)
        except Exception:
            return None

    return None


def _get_cells(root: ET.Element, page_index: int = 0) -> list[ET.Element]:
    """Get all <mxCell> elements for a diagram page."""
    model = _get_graph_model(root, page_index)
    if model is None:
        return []
    # mxCell elements are inside <root> child of mxGraphModel
    root_elem = model.find("root")
    if root_elem is None:
        # Some files have cells directly under mxGraphModel
        return list(model.findall("mxCell"))
    return list(root_elem.findall("mxCell"))


def _parse_style(style_str: str) -> dict:
    """Parse a draw.io style string into a dict.

    Style format: "shape=rectangle;fillColor=#fff;strokeColor=#000"
    The first token before ';' may be a shape name without '=' (e.g., "ellipse;...").
    """
    if not style_str:
        return {}
    result = {}
    parts = style_str.rstrip(";").split(";")
    for part in parts:
        if "=" in part:
            key, _, value = part.partition("=")
            result[key.strip()] = value.strip()
        elif part.strip():
            # Shape name without key (e.g., "ellipse", "rounded")
            result["_shape"] = part.strip()
    return result


def _cell_to_dict(cell: ET.Element) -> dict:
    """Convert an mxCell element to a serializable dict."""
    attribs = dict(cell.attrib)
    result = {
        "id": attribs.get("id", ""),
        "value": attribs.get("value", ""),
        "vertex": attribs.get("vertex") == "1",
        "edge": attribs.get("edge") == "1",
        "source": attribs.get("source"),
        "target": attribs.get("target"),
        "style": attribs.get("style", ""),
        "parent": attribs.get("parent", ""),
    }
    # Include geometry if present
    geom = cell.find("mxGeometry")
    if geom is not None:
        result["geometry"] = dict(geom.attrib)
    return result


# ---------------------------------------------------------------------------
# DrawioVerifier class
# ---------------------------------------------------------------------------

class DrawioVerifier:
    """Stateless verifier — each method call is independent."""

    # === Query endpoints ===

    def get_diagrams(self, filepath: str) -> list[dict]:
        """List all diagram pages in the file.

        Example return:
        [{"index": 0, "name": "Page-1", "id": "abc123"}, ...]
        """
        root = _parse_drawio(filepath)
        diagrams = root.findall("diagram")
        return [
            {
                "index": i,
                "name": d.get("name", ""),
                "id": d.get("id", ""),
            }
            for i, d in enumerate(diagrams)
        ]

    def get_cells(self, filepath: str, page_index: int = 0) -> list[dict]:
        """List all cells (vertices and edges) on a diagram page.

        Includes the two default cells (id=0 root, id=1 default parent).
        """
        root = _parse_drawio(filepath)
        cells = _get_cells(root, page_index)
        return [_cell_to_dict(c) for c in cells]

    def get_vertices(self, filepath: str, page_index: int = 0) -> list[dict]:
        """List only vertex cells (shapes) on a diagram page."""
        root = _parse_drawio(filepath)
        cells = _get_cells(root, page_index)
        return [_cell_to_dict(c) for c in cells if c.get("vertex") == "1"]

    def get_edges(self, filepath: str, page_index: int = 0) -> list[dict]:
        """List only edge cells (connections) on a diagram page."""
        root = _parse_drawio(filepath)
        cells = _get_cells(root, page_index)
        return [_cell_to_dict(c) for c in cells if c.get("edge") == "1"]

    def get_cell_info(self, filepath: str, cell_id: str, page_index: int = 0) -> dict:
        """Get detailed info for a specific cell by ID.

        Returns the cell dict or an error if not found.
        """
        root = _parse_drawio(filepath)
        cells = _get_cells(root, page_index)
        for c in cells:
            if c.get("id") == cell_id:
                return _cell_to_dict(c)
        return {"error": f"Cell with id '{cell_id}' not found on page {page_index}"}

    def get_labels(self, filepath: str, page_index: int = 0) -> list[dict]:
        """Extract all text labels from cells on a diagram page.

        Returns cells that have non-empty value attributes.
        """
        root = _parse_drawio(filepath)
        cells = _get_cells(root, page_index)
        results = []
        for c in cells:
            value = c.get("value", "")
            if value:
                results.append({
                    "id": c.get("id", ""),
                    "label": value,
                    "vertex": c.get("vertex") == "1",
                    "edge": c.get("edge") == "1",
                })
        return results

    def get_connections(self, filepath: str, page_index: int = 0) -> list[dict]:
        """List all source->target connections on a diagram page.

        Returns edges that have both source and target set.
        """
        root = _parse_drawio(filepath)
        cells = _get_cells(root, page_index)
        results = []
        for c in cells:
            if c.get("edge") == "1":
                source = c.get("source")
                target = c.get("target")
                if source and target:
                    results.append({
                        "id": c.get("id", ""),
                        "source": source,
                        "target": target,
                        "value": c.get("value", ""),
                    })
        return results

    def get_styles(self, filepath: str, cell_id: str, page_index: int = 0) -> dict:
        """Parse the style string for a specific cell into a dict.

        Example return:
        {"_shape": "ellipse", "fillColor": "#ffffff", "strokeColor": "#000000"}
        """
        root = _parse_drawio(filepath)
        cells = _get_cells(root, page_index)
        for c in cells:
            if c.get("id") == cell_id:
                style_str = c.get("style", "")
                return _parse_style(style_str)
        return {"error": f"Cell with id '{cell_id}' not found on page {page_index}"}

    # === Check endpoints ===

    def check_file_exists(self, filepath: str) -> dict:
        """Check if the file exists and is a valid .drawio file.

        Returns: {"exists": bool, "valid": bool, "page_count": int}
        """
        exists = os.path.exists(filepath)
        if not exists:
            return {"exists": False, "valid": False, "page_count": 0}
        try:
            root = _parse_drawio(filepath)
            pages = root.findall("diagram")
            return {"exists": True, "valid": True, "page_count": len(pages)}
        except Exception as e:
            return {"exists": True, "valid": False, "page_count": 0, "error": str(e)}

    def check_cell_exists(self, filepath: str, cell_id: str) -> dict:
        """Check if a cell with the given ID exists (searches all pages).

        Returns: {"exists": bool, "page_index": int|None, "cell": dict|None}
        """
        root = _parse_drawio(filepath)
        diagrams = root.findall("diagram")
        for i in range(len(diagrams)):
            cells = _get_cells(root, i)
            for c in cells:
                if c.get("id") == cell_id:
                    return {"exists": True, "page_index": i, "cell": _cell_to_dict(c)}
        return {"exists": False, "page_index": None, "cell": None}

    def check_label_exists(self, filepath: str, text: str) -> dict:
        """Check if any cell contains the given label text (case-sensitive, substring match).

        Returns: {"exists": bool, "matches": [{"id": str, "label": str, "page_index": int}]}
        """
        root = _parse_drawio(filepath)
        diagrams = root.findall("diagram")
        matches = []
        for i in range(len(diagrams)):
            cells = _get_cells(root, i)
            for c in cells:
                value = c.get("value", "")
                if text in value:
                    matches.append({
                        "id": c.get("id", ""),
                        "label": value,
                        "page_index": i,
                    })
        return {"exists": len(matches) > 0, "matches": matches}

    def check_connection_exists(self, filepath: str, source_id: str, target_id: str) -> dict:
        """Check if an edge connecting source_id to target_id exists (searches all pages).

        Returns: {"exists": bool, "edge_id": str|None, "page_index": int|None}
        """
        root = _parse_drawio(filepath)
        diagrams = root.findall("diagram")
        for i in range(len(diagrams)):
            cells = _get_cells(root, i)
            for c in cells:
                if (c.get("edge") == "1"
                        and c.get("source") == source_id
                        and c.get("target") == target_id):
                    return {"exists": True, "edge_id": c.get("id", ""), "page_index": i}
        return {"exists": False, "edge_id": None, "page_index": None}

    def check_cell_count(self, filepath: str, count: int, page_index: int = 0) -> dict:
        """Check that the total cell count matches the expected value.

        Returns: {"match": bool, "expected": int, "actual": int}
        """
        root = _parse_drawio(filepath)
        cells = _get_cells(root, page_index)
        actual = len(cells)
        return {"match": actual == count, "expected": count, "actual": actual}

    def check_vertex_count(self, filepath: str, count: int, page_index: int = 0) -> dict:
        """Check that the vertex count matches the expected value.

        Returns: {"match": bool, "expected": int, "actual": int}
        """
        root = _parse_drawio(filepath)
        cells = _get_cells(root, page_index)
        actual = sum(1 for c in cells if c.get("vertex") == "1")
        return {"match": actual == count, "expected": count, "actual": actual}

    def check_edge_count(self, filepath: str, count: int, page_index: int = 0) -> dict:
        """Check that the edge count matches the expected value.

        Returns: {"match": bool, "expected": int, "actual": int}
        """
        root = _parse_drawio(filepath)
        cells = _get_cells(root, page_index)
        actual = sum(1 for c in cells if c.get("edge") == "1")
        return {"match": actual == count, "expected": count, "actual": actual}

    def check_page_count(self, filepath: str, count: int) -> dict:
        """Check that the diagram page count matches the expected value.

        Returns: {"match": bool, "expected": int, "actual": int}
        """
        root = _parse_drawio(filepath)
        diagrams = root.findall("diagram")
        actual = len(diagrams)
        return {"match": actual == count, "expected": count, "actual": actual}

    def check_style_property(self, filepath: str, cell_id: str, prop: str, value: str,
                             page_index: int = 0) -> dict:
        """Check that a cell's style has a specific property value.

        Returns: {"match": bool, "expected": str, "actual": str|None}
        """
        root = _parse_drawio(filepath)
        cells = _get_cells(root, page_index)
        for c in cells:
            if c.get("id") == cell_id:
                styles = _parse_style(c.get("style", ""))
                actual = styles.get(prop)
                return {"match": actual == value, "expected": value, "actual": actual}
        return {"error": f"Cell with id '{cell_id}' not found on page {page_index}"}


# ---------------------------------------------------------------------------
# CLI interface — for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

COMMANDS = {
    # Query
    "diagrams": (
        "List diagram pages (name, id)",
        lambda v, args: v.get_diagrams(args[0]),
    ),
    "cells": (
        "List all cells (vertices and edges)",
        lambda v, args: v.get_cells(args[0], int(args[1]) if len(args) > 1 else 0),
    ),
    "vertices": (
        "List vertex cells (shapes)",
        lambda v, args: v.get_vertices(args[0], int(args[1]) if len(args) > 1 else 0),
    ),
    "edges": (
        "List edge cells (connections)",
        lambda v, args: v.get_edges(args[0], int(args[1]) if len(args) > 1 else 0),
    ),
    "cell-info": (
        "Detailed cell info by ID",
        lambda v, args: v.get_cell_info(args[0], args[1], int(args[2]) if len(args) > 2 else 0),
    ),
    "labels": (
        "Extract all text labels",
        lambda v, args: v.get_labels(args[0], int(args[1]) if len(args) > 1 else 0),
    ),
    "connections": (
        "List source->target connections",
        lambda v, args: v.get_connections(args[0], int(args[1]) if len(args) > 1 else 0),
    ),
    "styles": (
        "Parse style string into dict",
        lambda v, args: v.get_styles(args[0], args[1], int(args[2]) if len(args) > 2 else 0),
    ),

    # Check
    "check-file-exists": (
        "Check file exists and is valid",
        lambda v, args: v.check_file_exists(args[0]),
    ),
    "check-cell-exists": (
        "Check cell with ID exists",
        lambda v, args: v.check_cell_exists(args[0], args[1]),
    ),
    "check-label-exists": (
        "Check label text exists",
        lambda v, args: v.check_label_exists(args[0], args[1]),
    ),
    "check-connection-exists": (
        "Check source->target connection exists",
        lambda v, args: v.check_connection_exists(args[0], args[1], args[2]),
    ),
    "check-cell-count": (
        "Check total cell count",
        lambda v, args: v.check_cell_count(args[0], int(args[1]), int(args[2]) if len(args) > 2 else 0),
    ),
    "check-vertex-count": (
        "Check vertex count",
        lambda v, args: v.check_vertex_count(args[0], int(args[1]), int(args[2]) if len(args) > 2 else 0),
    ),
    "check-edge-count": (
        "Check edge count",
        lambda v, args: v.check_edge_count(args[0], int(args[1]), int(args[2]) if len(args) > 2 else 0),
    ),
    "check-page-count": (
        "Check diagram page count",
        lambda v, args: v.check_page_count(args[0], int(args[1])),
    ),
    "check-style-property": (
        "Check style property value",
        lambda v, args: v.check_style_property(
            args[0], args[1], args[2], args[3], int(args[4]) if len(args) > 4 else 0
        ),
    ),
}


def _print_usage():
    print("Draw.io Verifier — query .drawio file state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print("\nAll output is JSON. Parses .drawio XML files directly (no API/IPC needed).")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = DrawioVerifier()
    _, handler = COMMANDS[cmd]

    try:
        result = handler(v, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except FileNotFoundError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))
