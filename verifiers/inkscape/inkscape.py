"""
Inkscape Verifier — programmatic state inspection for Inkscape SVG files in E2B sandbox.

Verification channels (in order of preference):
  1. Direct SVG/XML parsing via xml.etree.ElementTree (stdlib) — fast, no deps
  2. Inkscape CLI (inkscape --query-all) — geometry queries for rendered bounds

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/inkscape.py elements drawing.svg")
    sandbox.commands.run("python3 /home/user/verifiers/inkscape.py check-element-exists drawing.svg rect1234")
    sandbox.commands.run("python3 /home/user/verifiers/inkscape.py layers drawing.svg")

Usage from Python (inside sandbox or via E2B):
    from verifiers.inkscape import InkscapeVerifier
    v = InkscapeVerifier()
    elems = v.get_elements("drawing.svg")
    layers = v.get_layers("drawing.svg")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - xml.etree.ElementTree (standard library)
  - inkscape CLI (optional, for geometry queries)
"""

import json
import os
import sys
import xml.etree.ElementTree as ET
from typing import Any

# ---------------------------------------------------------------------------
# SVG Namespaces
# ---------------------------------------------------------------------------

NAMESPACES = {
    "svg": "http://www.w3.org/2000/svg",
    "inkscape": "http://www.inkscape.org/namespaces/inkscape",
    "sodipodi": "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
    "xlink": "http://www.w3.org/1999/xlink",
}

# Register namespaces so ET.tostring preserves prefixes
for prefix, uri in NAMESPACES.items():
    ET.register_namespace(prefix, uri)


def _ns(tag: str) -> str:
    """Expand a prefixed tag like 'svg:rect' to '{http://...}rect'."""
    if ":" in tag:
        prefix, local = tag.split(":", 1)
        uri = NAMESPACES.get(prefix)
        if uri:
            return f"{{{uri}}}{local}"
    return tag


def _strip_ns(tag: str) -> str:
    """Strip namespace URI from a tag: '{http://...}rect' -> 'rect'."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _get_ns_prefix(tag: str) -> str:
    """Get the namespace prefix for a fully-qualified tag."""
    if tag.startswith("{"):
        uri = tag.split("}")[0][1:]
        for prefix, ns_uri in NAMESPACES.items():
            if ns_uri == uri:
                return prefix
    return ""


def _parse_svg(path: str) -> ET.ElementTree:
    """Parse an SVG file, returning the ElementTree."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    return ET.parse(path)


def _parse_style(style_str: str) -> dict:
    """Parse a CSS style string into a dict."""
    if not style_str:
        return {}
    result = {}
    for part in style_str.split(";"):
        part = part.strip()
        if ":" in part:
            key, val = part.split(":", 1)
            result[key.strip()] = val.strip()
    return result


def _norm_color(s):
    """Normalize a hex color string for case-insensitive comparison.

    Inkscape persists fill/stroke colors as lowercase hex (e.g. '#ff0000') in
    saved SVGs, while task authors and humans typically write uppercase. Compare
    via lowercased form for any '#'-prefixed string.
    """
    if isinstance(s, str) and s.startswith("#"):
        return s.lower()
    return s


def _element_summary(elem: ET.Element) -> dict:
    """Build a summary dict for an SVG element."""
    tag = _strip_ns(elem.tag)
    attribs = dict(elem.attrib)
    elem_id = attribs.get("id", "")
    transform = attribs.get("transform", "")
    style = attribs.get("style", "")
    label = attribs.get(_ns("inkscape:label"), "")
    summary = {
        "id": elem_id,
        "tag": tag,
    }
    if transform:
        summary["transform"] = transform
    if style:
        summary["style"] = style
    if label:
        summary["label"] = label
    return summary


# ---------------------------------------------------------------------------
# InkscapeVerifier class
# ---------------------------------------------------------------------------

class InkscapeVerifier:
    """Stateless verifier -- each method call is independent."""

    # === Query endpoints ===

    def get_elements(self, svg_path: str) -> dict:
        """List all elements with id, tag, transform, style.

        Returns:
            {"count": N, "elements": [{"id": "...", "tag": "rect", ...}, ...]}
        """
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        elements = []
        for elem in root.iter():
            elements.append(_element_summary(elem))
        return {"count": len(elements), "elements": elements}

    def get_element_info(self, svg_path: str, element_id: str) -> dict:
        """Detailed info for a specific element by id.

        Returns all attributes, child count, text content, parsed style.
        """
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        for elem in root.iter():
            if elem.attrib.get("id") == element_id:
                tag = _strip_ns(elem.tag)
                attribs = {}
                for k, v in elem.attrib.items():
                    # Simplify namespace keys for readability
                    attribs[_strip_ns(k) if k.startswith("{") else k] = v
                children = [_element_summary(c) for c in elem]
                style = _parse_style(elem.attrib.get("style", ""))
                text = elem.text.strip() if elem.text and elem.text.strip() else None
                return {
                    "id": element_id,
                    "tag": tag,
                    "attributes": attribs,
                    "style_parsed": style,
                    "text": text,
                    "child_count": len(children),
                    "children": children,
                }
        return {"error": f"Element with id '{element_id}' not found"}

    def get_text_content(self, svg_path: str) -> dict:
        """Extract all text elements with their content and position.

        Returns:
            {"count": N, "texts": [{"id": "...", "text": "Hello", "x": "10", "y": "20"}, ...]}
        """
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        texts = []
        for elem in root.iter(_ns("svg:text")):
            # Gather all text including tspan children
            full_text = "".join(elem.itertext()).strip()
            entry = {
                "id": elem.attrib.get("id", ""),
                "text": full_text,
                "x": elem.attrib.get("x", ""),
                "y": elem.attrib.get("y", ""),
            }
            style = elem.attrib.get("style", "")
            if style:
                entry["style"] = style
            label = elem.attrib.get(_ns("inkscape:label"), "")
            if label:
                entry["label"] = label
            texts.append(entry)
        return {"count": len(texts), "texts": texts}

    def get_layers(self, svg_path: str) -> dict:
        """List Inkscape layers (g elements with inkscape:groupmode='layer').

        Returns:
            {"count": N, "layers": [{"id": "...", "label": "Layer 1", "style": "..."}, ...]}
        """
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        layers = []
        groupmode_attr = _ns("inkscape:groupmode")
        label_attr = _ns("inkscape:label")
        for elem in root.iter(_ns("svg:g")):
            if elem.attrib.get(groupmode_attr) == "layer":
                child_count = len(list(elem))
                entry = {
                    "id": elem.attrib.get("id", ""),
                    "label": elem.attrib.get(label_attr, ""),
                    "child_count": child_count,
                }
                style = elem.attrib.get("style", "")
                if style:
                    entry["style"] = style
                layers.append(entry)
        return {"count": len(layers), "layers": layers}

    def get_page_info(self, svg_path: str) -> dict:
        """Page dimensions, viewBox, units.

        Returns:
            {"width": "210mm", "height": "297mm", "viewBox": "0 0 210 297", ...}
        """
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        result = {
            "width": root.attrib.get("width", ""),
            "height": root.attrib.get("height", ""),
            "viewBox": root.attrib.get("viewBox", ""),
        }
        # Inkscape-specific document units
        units = root.attrib.get(_ns("inkscape:document-units"), "")
        if units:
            result["document_units"] = units
        # sodipodi named view for page properties
        for nv in root.iter(_ns("sodipodi:namedview")):
            page_color = nv.attrib.get("pagecolor", "")
            if page_color:
                result["page_color"] = page_color
            border_color = nv.attrib.get("bordercolor", "")
            if border_color:
                result["border_color"] = border_color
        return result

    def get_styles(self, svg_path: str, element_id: str | None = None) -> dict:
        """Get style properties for one element or all elements with styles.

        If element_id is given, returns parsed style for that element.
        Otherwise, lists all elements that have a style attribute.
        """
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        if element_id:
            for elem in root.iter():
                if elem.attrib.get("id") == element_id:
                    raw = elem.attrib.get("style", "")
                    return {
                        "id": element_id,
                        "tag": _strip_ns(elem.tag),
                        "style_raw": raw,
                        "style_parsed": _parse_style(raw),
                    }
            return {"error": f"Element with id '{element_id}' not found"}
        # All elements with style
        styled = []
        for elem in root.iter():
            raw = elem.attrib.get("style", "")
            if raw:
                styled.append({
                    "id": elem.attrib.get("id", ""),
                    "tag": _strip_ns(elem.tag),
                    "style_parsed": _parse_style(raw),
                })
        return {"count": len(styled), "elements": styled}

    def get_paths(self, svg_path: str) -> dict:
        """List all path elements with d attribute summary.

        Returns:
            {"count": N, "paths": [{"id": "...", "d_length": 123, "d_preview": "M 0 0 L 10 ..."}, ...]}
        """
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        paths = []
        for elem in root.iter(_ns("svg:path")):
            d = elem.attrib.get("d", "")
            entry = {
                "id": elem.attrib.get("id", ""),
                "d_length": len(d),
                "d_preview": d[:100] + ("..." if len(d) > 100 else ""),
            }
            style = elem.attrib.get("style", "")
            if style:
                entry["style"] = style
            label = elem.attrib.get(_ns("inkscape:label"), "")
            if label:
                entry["label"] = label
            paths.append(entry)
        return {"count": len(paths), "paths": paths}

    def get_groups(self, svg_path: str) -> dict:
        """List all groups and their children.

        Returns:
            {"count": N, "groups": [{"id": "...", "children": [...], "child_count": M}, ...]}
        """
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        groups = []
        groupmode_attr = _ns("inkscape:groupmode")
        label_attr = _ns("inkscape:label")
        for elem in root.iter(_ns("svg:g")):
            children = [_element_summary(c) for c in elem]
            entry = {
                "id": elem.attrib.get("id", ""),
                "child_count": len(children),
                "children": children,
            }
            label = elem.attrib.get(label_attr, "")
            if label:
                entry["label"] = label
            groupmode = elem.attrib.get(groupmode_attr, "")
            if groupmode:
                entry["groupmode"] = groupmode
            groups.append(entry)
        return {"count": len(groups), "groups": groups}

    def get_connections(self, svg_path: str) -> dict:
        """List connections/arrows between elements (connector elements).

        Inkscape connectors use the tag 'svg:path' with inkscape:connector-type attribute,
        and connection-start/connection-end attributes pointing to element ids.
        """
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        connector_type_attr = _ns("inkscape:connector-type")
        connection_start_attr = _ns("inkscape:connection-start")
        connection_end_attr = _ns("inkscape:connection-end")
        connectors = []
        for elem in root.iter():
            ctype = elem.attrib.get(connector_type_attr, "")
            if ctype:
                start = elem.attrib.get(connection_start_attr, "")
                end = elem.attrib.get(connection_end_attr, "")
                # Strip leading '#' from id references
                if start.startswith("#"):
                    start = start[1:]
                if end.startswith("#"):
                    end = end[1:]
                connectors.append({
                    "id": elem.attrib.get("id", ""),
                    "type": ctype,
                    "start": start,
                    "end": end,
                })
        return {"count": len(connectors), "connections": connectors}

    # === Check endpoints ===

    def check_file_exists(self, path: str) -> dict:
        """Check if a file exists at the given path."""
        exists = os.path.isfile(path)
        return {"exists": exists, "path": path}

    def check_element_exists(self, svg_path: str, element_id: str) -> dict:
        """Check if an element with the given id exists."""
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        for elem in root.iter():
            if elem.attrib.get("id") == element_id:
                return {"exists": True, "id": element_id, "tag": _strip_ns(elem.tag)}
        return {"exists": False, "id": element_id}

    def check_element_count(self, svg_path: str, expected_count: int) -> dict:
        """Check total element count matches expected."""
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        actual = sum(1 for _ in root.iter())
        return {
            "match": actual == expected_count,
            "expected": expected_count,
            "actual": actual,
        }

    def check_text_contains(self, svg_path: str, text: str) -> dict:
        """Check if the SVG contains the given text string in any text element."""
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        for elem in root.iter(_ns("svg:text")):
            full_text = "".join(elem.itertext())
            if text in full_text:
                return {"contains": True, "text": text, "found_in": elem.attrib.get("id", "")}
        return {"contains": False, "text": text}

    def check_layer_exists(self, svg_path: str, layer_name: str) -> dict:
        """Check if a layer with the given name/label exists."""
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        groupmode_attr = _ns("inkscape:groupmode")
        label_attr = _ns("inkscape:label")
        for elem in root.iter(_ns("svg:g")):
            if elem.attrib.get(groupmode_attr) == "layer":
                label = elem.attrib.get(label_attr, "")
                if label == layer_name:
                    return {"exists": True, "layer_name": layer_name, "id": elem.attrib.get("id", "")}
        return {"exists": False, "layer_name": layer_name}

    def check_layer_count(self, svg_path: str, expected_count: int) -> dict:
        """Check the number of layers matches expected."""
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        groupmode_attr = _ns("inkscape:groupmode")
        actual = sum(
            1 for elem in root.iter(_ns("svg:g"))
            if elem.attrib.get(groupmode_attr) == "layer"
        )
        return {
            "match": actual == expected_count,
            "expected": expected_count,
            "actual": actual,
        }

    def check_page_size(self, svg_path: str, width: str, height: str) -> dict:
        """Check page dimensions match expected width and height."""
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        actual_w = root.attrib.get("width", "")
        actual_h = root.attrib.get("height", "")
        return {
            "match": actual_w == width and actual_h == height,
            "expected_width": width,
            "expected_height": height,
            "actual_width": actual_w,
            "actual_height": actual_h,
        }

    def check_element_attribute(self, svg_path: str, element_id: str, attr: str, value: str) -> dict:
        """Check if an element's attribute matches the expected value."""
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        for elem in root.iter():
            if elem.attrib.get("id") == element_id:
                # Try the attribute directly, then with namespace expansion
                actual = elem.attrib.get(attr)
                if actual is None:
                    # Try expanding namespace prefix
                    actual = elem.attrib.get(_ns(attr))
                return {
                    "match": _norm_color(actual) == _norm_color(value),
                    "element_id": element_id,
                    "attribute": attr,
                    "expected": value,
                    "actual": actual,
                }
        return {"error": f"Element with id '{element_id}' not found"}

    def check_style_property(self, svg_path: str, element_id: str, prop: str, value: str) -> dict:
        """Check if an element's CSS style property matches the expected value."""
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        for elem in root.iter():
            if elem.attrib.get("id") == element_id:
                style = _parse_style(elem.attrib.get("style", ""))
                actual = style.get(prop)
                return {
                    "match": _norm_color(actual) == _norm_color(value),
                    "element_id": element_id,
                    "property": prop,
                    "expected": value,
                    "actual": actual,
                }
        return {"error": f"Element with id '{element_id}' not found"}

    def check_has_element_type(self, svg_path: str, tag: str) -> dict:
        """Check if any element of the given type exists (rect, circle, path, text, etc.)."""
        tree = _parse_svg(svg_path)
        root = tree.getroot()
        # Search with SVG namespace
        full_tag = _ns(f"svg:{tag}")
        found = []
        for elem in root.iter(full_tag):
            found.append(elem.attrib.get("id", ""))
        if found:
            return {"exists": True, "tag": tag, "count": len(found), "ids": found}
        # Fallback: search without namespace (bare tags)
        for elem in root.iter(tag):
            found.append(elem.attrib.get("id", ""))
        return {
            "exists": len(found) > 0,
            "tag": tag,
            "count": len(found),
            "ids": found,
        }


# ---------------------------------------------------------------------------
# CLI interface -- for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

def _unquote(s: str) -> str:
    """Strip surrounding quotes from a CLI argument value.

    Some execution environments pass shell quotes literally (e.g. ``'#ff0000'``
    instead of ``#ff0000``).  This helper strips matched outer quotes.
    """
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _split_prop_value(args):
    """Parse property and value from CLI args for check-style-property.

    Handles three calling conventions:
      1. ["fill", "#ff0000"]  ->  ("fill", "#ff0000")   -- normal (4+ shell args)
      2. ["fill"]             ->  tries reading value from the SVG (shell ate #value)
      3. ["fill:#ff0000"]     ->  ("fill", "#ff0000")   -- combined format

    When the shell strips a #-prefixed value (treated as a comment), only the
    property name survives.  In that case we look for a colon in the property
    arg as a combined format, or raise IndexError if nothing works.

    Returns (prop, value) tuple.
    """
    if len(args) >= 2:
        return args[0], _unquote(args[1])
    if len(args) == 1:
        # Value was likely stripped by the shell (started with #).
        # Try combined "prop:value" format
        if ":" in args[0]:
            prop, val = args[0].split(":", 1)
            return prop, _unquote(val)
    raise IndexError("Missing property value argument")


COMMANDS = {
    # Query endpoints
    "elements":     ("List all elements",                   lambda v, a: v.get_elements(a[0])),
    "element-info": ("Detailed info for element by id",     lambda v, a: v.get_element_info(a[0], a[1])),
    "text-content": ("Extract all text elements",           lambda v, a: v.get_text_content(a[0])),
    "layers":       ("List Inkscape layers",                lambda v, a: v.get_layers(a[0])),
    "page-info":    ("Page dimensions and viewBox",         lambda v, a: v.get_page_info(a[0])),
    "styles":       ("Get style properties",                lambda v, a: v.get_styles(a[0], a[1] if len(a) > 1 else None)),
    "paths":        ("List all path elements",              lambda v, a: v.get_paths(a[0])),
    "groups":       ("List all groups and children",        lambda v, a: v.get_groups(a[0])),
    "connections":  ("List connector elements",             lambda v, a: v.get_connections(a[0])),

    # Check endpoints
    "check-file-exists":        ("Check file exists",                   lambda v, a: v.check_file_exists(a[0])),
    "check-element-exists":     ("Check element exists by id",          lambda v, a: v.check_element_exists(a[0], a[1])),
    "check-element-count":      ("Check total element count",           lambda v, a: v.check_element_count(a[0], int(a[1]))),
    "check-text-contains":      ("Check SVG contains text",             lambda v, a: v.check_text_contains(a[0], a[1])),
    "check-layer-exists":       ("Check layer exists by name",          lambda v, a: v.check_layer_exists(a[0], a[1])),
    "check-layer-count":        ("Check number of layers",              lambda v, a: v.check_layer_count(a[0], int(a[1]))),
    "check-page-size":          ("Check page dimensions",               lambda v, a: v.check_page_size(a[0], a[1], a[2])),
    "check-element-attribute":  ("Check element attribute value",       lambda v, a: v.check_element_attribute(a[0], a[1], a[2], _unquote(a[3]))),
    "check-style-property":     ("Check CSS style property",            lambda v, a: v.check_style_property(a[0], a[1], *_split_prop_value(a[2:]))),
    "check-has-element-type":   ("Check element type exists",           lambda v, a: v.check_has_element_type(a[0], a[1])),
}


def _print_usage():
    print("Inkscape Verifier — query SVG/Inkscape document state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print("\nAll output is JSON. SVG files are parsed with xml.etree.ElementTree.")



if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    # Debug: print proc info to stderr for diagnosis
    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = InkscapeVerifier()
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
