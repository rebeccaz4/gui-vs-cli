"""
Godot 4 Verifier — programmatic state inspection for Godot 4 projects in E2B sandbox.

Godot projects are stored as text files in an INI-like format, so the verifier
works purely by file parsing (stdlib only). It also supports a live "project
parses" check via the `godot4 --headless --check-only` command.

Verification channels:
  1. Text parsing of `project.godot` (INI-like with a leading magic-comment line,
     and nested type annotations in values). Exposes:
       - [application] section (name, main_scene, config/features, icon)
       - [input] section (action maps with events)
       - [rendering] section (driver, defaults)
       - [autoload] section
       - [display] section (window size)
       - [physics] section
       - arbitrary section/key lookups
  2. Text parsing of `.tscn` scene files (line-based `[node name="..." type="..."
     parent="..."]` blocks with property lines). Exposes:
       - Node tree with name/type/parent
       - Node property values
       - ext_resource / sub_resource references
       - Script attachments
  3. Text parsing of `.gd` GDScript files. Exposes:
       - class_name declarations
       - func declarations (name and argument count)
       - @export variable declarations
       - extends clause
  4. Text parsing of `.tres` resource files. Exposes:
       - resource type
       - top-level properties
  5. Text parsing of `editor_settings-4.X.tres` for editor preferences.
  6. Live check: `godot4 --headless --check-only --path <project_dir>` returns 0
     if the project parses, non-zero on errors. Used for project-validity checks.

Usage from outside the sandbox:
    sandbox.commands.run("python3 /home/user/verifiers/godot4.py project-setting /path/project.godot application/config/name")
    sandbox.commands.run("python3 /home/user/verifiers/godot4.py check-node-exists /path/scene.tscn Player")

All output is JSON.

Requires:
  - /usr/local/bin/godot4 available on PATH for live project-validity checks only
  - Everything else works with pure Python stdlib file parsing.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Low-level parser: project.godot / .tres / .tscn are all INI-like
# ---------------------------------------------------------------------------

# Value parsing handles:
#   - strings: "quoted"
#   - numbers: 42, 1.5, -3.0
#   - booleans: true / false
#   - null
#   - simple arrays / dicts: [1,2,3] {"a":1}
#   - typed values: Vector2(1, 2), Color(1,0,0,1), NodePath("x")  -> stored as raw string
#   - SubResource("id") / ExtResource("id")                       -> stored as raw string

def _strip_comment(line: str) -> str:
    """Strip ';'-prefixed comments but preserve ';' inside quotes."""
    in_str = False
    for i, c in enumerate(line):
        if c == '"':
            in_str = not in_str
        elif c == ";" and not in_str:
            return line[:i]
    return line


def _parse_value(raw: str) -> Any:
    """Parse a value from the right side of an INI key=value line."""
    s = raw.strip()
    if not s:
        return ""
    # String
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return s[1:-1]
    # Boolean / null
    if s == "true":
        return True
    if s == "false":
        return False
    if s == "null":
        return None
    # Number
    try:
        if "." in s or "e" in s or "E" in s:
            return float(s)
        return int(s)
    except ValueError:
        pass
    # Array / Dict (JSON-compatible subset)
    if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return s
    # Typed/structured (Vector2(...), SubResource("..."), Color(...), NodePath(...), PackedStringArray(...), etc.)
    return s


def _parse_ini_like(text: str) -> tuple[dict, list[tuple[dict, dict]]]:
    """Parse a Godot INI-like file.

    Returns:
        (header_values, sections)
      - header_values: dict of key=value pairs at the top of the file before any [section]
      - sections: list of (section_header_dict, properties_dict) tuples

    Section header dict includes a special key "__name__" for the section name and
    any attribute values (e.g. type="Node2D", parent="." for tscn nodes).

    Multi-line values (arrays/dicts across lines) are concatenated before parsing.
    """
    header_values: dict[str, Any] = {}
    sections: list[tuple[dict, dict]] = []

    current_header: dict[str, Any] | None = None
    current_props: dict[str, Any] = {}

    # Pre-process: join multi-line array/dict values. A line that has unclosed
    # brackets will absorb subsequent lines until balanced.
    joined_lines: list[str] = []
    buf: str | None = None
    depth = 0
    in_str_buf = False

    def _bracket_delta(s: str) -> tuple[int, bool]:
        d = 0
        in_str = in_str_buf
        i = 0
        while i < len(s):
            c = s[i]
            if c == "\\" and in_str and i + 1 < len(s):
                i += 2
                continue
            if c == '"':
                in_str = not in_str
            elif not in_str:
                if c in "[{(":
                    d += 1
                elif c in "]})":
                    d -= 1
            i += 1
        return d, in_str

    for raw_line in text.splitlines():
        line_wo_comment = _strip_comment(raw_line)
        if buf is None:
            candidate = line_wo_comment
        else:
            candidate = buf + "\n" + line_wo_comment
        delta, new_in_str = _bracket_delta(line_wo_comment)
        depth += delta
        in_str_buf = new_in_str
        if depth > 0 or in_str_buf:
            buf = candidate
            continue
        # depth <= 0 and not in string
        joined_lines.append(candidate)
        buf = None
        depth = 0
        in_str_buf = False

    if buf is not None:
        joined_lines.append(buf)

    for line in joined_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(";"):
            continue
        # Section header
        if stripped.startswith("[") and stripped.rstrip().endswith("]"):
            # Flush current
            if current_header is not None:
                sections.append((current_header, current_props))
            # Parse header: [name key=val key=val ...]
            inner = stripped[1:stripped.rindex("]")]
            current_header = _parse_section_header(inner)
            current_props = {}
            continue
        # key = value
        if "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        key = key.strip()
        value = _parse_value(val.strip())
        if current_header is None:
            header_values[key] = value
        else:
            current_props[key] = value

    if current_header is not None:
        sections.append((current_header, current_props))

    return header_values, sections


def _parse_section_header(inner: str) -> dict[str, Any]:
    """Parse the inside of a [section] header.

    Examples:
        application                       -> {"__name__": "application"}
        node name="Root" type="Node2D"    -> {"__name__": "node", "name": "Root", "type": "Node2D"}
        ext_resource path="res://x" type="Script" id="1_abc"
                                          -> {"__name__": "ext_resource", "path": "res://x", ...}
    """
    result: dict[str, Any] = {}
    # Find name: first whitespace-delimited token (but may be alone)
    m = re.match(r"\s*([^\s=]+)", inner)
    if not m:
        return {"__name__": ""}
    result["__name__"] = m.group(1)
    rest = inner[m.end():].strip()

    # Parse key="value" or key=number pairs
    pattern = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*("(?:[^"\\]|\\.)*"|\S+)')
    for km in pattern.finditer(rest):
        k = km.group(1)
        v = km.group(2)
        result[k] = _parse_value(v)
    return result


# ---------------------------------------------------------------------------
# Godot4Verifier — all public methods return JSON-serializable values
# ---------------------------------------------------------------------------

class Godot4Verifier:
    """Stateless verifier for Godot 4 project files."""

    # ---- project.godot ----

    def get_project_sections(self, project_godot: str) -> dict:
        """Return a list of all top-level sections in project.godot."""
        p = Path(project_godot)
        if not p.exists():
            return {"error": f"File not found: {project_godot}"}
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as e:
            return {"error": f"Cannot read {project_godot}: {e}"}
        _, sections = _parse_ini_like(text)
        names = sorted({s[0].get("__name__", "") for s in sections if s[0].get("__name__")})
        return {"sections": names, "count": len(names), "path": str(p)}

    def get_project_setting(self, project_godot: str, key: str) -> dict:
        """Get a specific `section/subkey` value from project.godot.

        `key` is a slash-separated path like `application/config/name` or
        `rendering/renderer/rendering_method`. Godot stores these as dotted keys
        inside matching sections (e.g. [application] -> config/name="...").
        """
        p = Path(project_godot)
        if not p.exists():
            return {"error": f"File not found: {project_godot}"}
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as e:
            return {"error": f"Cannot read {project_godot}: {e}"}
        _, sections = _parse_ini_like(text)
        if "/" not in key:
            return {"error": f"Invalid key '{key}' (expected section/subkey)"}
        section_name, _, subkey = key.partition("/")
        for header, props in sections:
            if header.get("__name__") == section_name:
                if subkey in props:
                    return {"key": key, "value": props[subkey], "found": True}
        return {"key": key, "value": None, "found": False}

    def get_project_section(self, project_godot: str, section: str) -> dict:
        """Return all key/value pairs in a given project.godot section."""
        p = Path(project_godot)
        if not p.exists():
            return {"error": f"File not found: {project_godot}"}
        text = p.read_text(encoding="utf-8")
        _, sections = _parse_ini_like(text)
        merged: dict[str, Any] = {}
        for header, props in sections:
            if header.get("__name__") == section:
                merged.update(props)
        return {"section": section, "keys": merged, "count": len(merged)}

    def get_input_actions(self, project_godot: str) -> dict:
        """Return the input map (action name -> list of event type strings)."""
        data = self.get_project_section(project_godot, "input")
        if "error" in data:
            return data
        actions = {}
        for k, v in data.get("keys", {}).items():
            # v is usually a raw string like '{"deadzone": 0.5, "events": [...]}'
            # Python json may have parsed it already if it was pure JSON.
            events_info: list[str] = []
            raw = v
            if isinstance(v, str):
                # Try to find event class names in the string.
                events_info = sorted(set(re.findall(r"InputEvent[A-Za-z]+", v)))
            elif isinstance(v, dict):
                evs = v.get("events", [])
                if isinstance(evs, list):
                    for e in evs:
                        if isinstance(e, dict) and "type" in e:
                            events_info.append(str(e["type"]))
                        elif isinstance(e, str):
                            events_info.extend(re.findall(r"InputEvent[A-Za-z]+", e))
            actions[k] = {"events": events_info, "raw": raw if isinstance(raw, str) else None}
        return {"actions": actions, "count": len(actions)}

    def get_autoloads(self, project_godot: str) -> dict:
        """Return the list of autoloads defined in the project."""
        data = self.get_project_section(project_godot, "autoload")
        if "error" in data:
            return data
        autoloads = {}
        for name, path in data.get("keys", {}).items():
            autoloads[name] = path
        return {"autoloads": autoloads, "count": len(autoloads)}

    def check_project_parses(self, project_godot: str, timeout: int = 30) -> dict:
        """Run `godot4 --headless --check-only --path <dir>` and return exit status."""
        p = Path(project_godot)
        if not p.exists():
            return {"error": f"File not found: {project_godot}", "parses": False}
        project_dir = str(p.parent)
        try:
            proc = subprocess.run(
                ["godot4", "--headless", "--check-only", "--path", project_dir, "--quit"],
                capture_output=True, text=True, timeout=timeout,
            )
            return {
                "parses": proc.returncode == 0,
                "returncode": proc.returncode,
                "stderr": proc.stderr[-400:],
            }
        except FileNotFoundError:
            return {"error": "godot4 not installed", "parses": False}
        except subprocess.TimeoutExpired:
            return {"error": f"godot4 check timed out after {timeout}s", "parses": False}

    def check_project_setting(self, project_godot: str, key: str, expected: str) -> dict:
        """Check if a project setting matches an expected value (parsed as JSON if possible)."""
        try:
            expected_val = json.loads(expected)
        except (json.JSONDecodeError, TypeError):
            expected_val = expected
        result = self.get_project_setting(project_godot, key)
        if "error" in result:
            return {**result, "match": False, "expected": expected_val}
        actual = result.get("value")
        # Normalize string/number comparison leniently
        match = actual == expected_val
        if not match and isinstance(actual, (int, float)) and isinstance(expected_val, str):
            try:
                match = actual == float(expected_val)
            except ValueError:
                pass
        return {"match": match, "key": key, "expected": expected_val, "actual": actual}

    def check_input_action_exists(self, project_godot: str, action: str) -> dict:
        """Check if an input action is defined."""
        result = self.get_input_actions(project_godot)
        if "error" in result:
            return {**result, "exists": False}
        exists = action in result.get("actions", {})
        return {"exists": exists, "action": action, "count": result.get("count", 0)}

    # Godot 4 physical keycode numeric values for common named keys.
    # Source: Godot source `core/os/keyboard.h` key enum.
    _NAMED_KEYCODES = {
        "SPACE": 32,
        "ENTER": 4194309,
        "RETURN": 4194309,
        "ESCAPE": 4194305,
        "ESC": 4194305,
        "TAB": 4194306,
        "BACKSPACE": 4194308,
        "SHIFT": 4194326,
        "CTRL": 4194328,
        "ALT": 4194329,
        "LEFT": 4194319,
        "RIGHT": 4194321,
        "UP": 4194320,
        "DOWN": 4194322,
        "F1": 4194332, "F2": 4194333, "F3": 4194334, "F4": 4194335,
        "F5": 4194336, "F6": 4194337, "F7": 4194338, "F8": 4194339,
        "F9": 4194340, "F10": 4194341, "F11": 4194342, "F12": 4194343,
    }

    def check_input_action_has_key(self, project_godot: str, action: str, keycode: str) -> dict:
        """Check that a given action is bound to a physical key.

        `keycode` should be an uppercase keysym name like A, SPACE, UP, ESCAPE,
        or a decimal keycode. We scan the raw string for the numeric value
        (matching `physical_keycode` or `keycode`) or for the literal name.
        """
        result = self.get_project_section(project_godot, "input")
        if "error" in result:
            return {**result, "match": False}
        raw = result.get("keys", {}).get(action)
        if raw is None:
            return {"match": False, "action": action, "reason": "action not found"}
        raw_s = raw if isinstance(raw, str) else json.dumps(raw)

        key_upper = keycode.upper()
        candidates: list[str] = []
        # Try named keycode first
        if key_upper in self._NAMED_KEYCODES:
            candidates.append(str(self._NAMED_KEYCODES[key_upper]))
        # Single letter/digit -> ASCII ordinal (Godot uses uppercase ASCII as keycode)
        if len(key_upper) == 1:
            candidates.append(str(ord(key_upper)))
        # Numeric input
        if keycode.isdigit():
            candidates.append(keycode)
        # Raw name fallback
        candidates.append(key_upper)

        ok = False
        matched = None
        for c in candidates:
            # Require the candidate to appear adjacent to a keycode field so
            # e.g. "32" doesn't match a random number. We check two patterns:
            #   "physical_keycode":<c>
            #   "keycode":<c>
            patterns = [
                f'"physical_keycode":{c}',
                f'"keycode":{c}',
                f'physical_keycode={c}',
                f'keycode={c}',
            ]
            for p in patterns:
                if p in raw_s:
                    ok = True
                    matched = c
                    break
            if ok:
                break
        # Finally, fall back to substring match on the literal name (for tests
        # that only have the key name as a comment)
        if not ok and key_upper in raw_s.upper():
            ok = True
            matched = key_upper
        return {"match": ok, "action": action, "keycode": keycode, "matched_value": matched}

    def check_autoload_exists(self, project_godot: str, name: str) -> dict:
        """Check that the given autoload is defined."""
        result = self.get_autoloads(project_godot)
        if "error" in result:
            return {**result, "exists": False}
        exists = name in result.get("autoloads", {})
        return {"exists": exists, "name": name}

    # ---- .tscn scenes ----

    def get_scene_nodes(self, tscn_path: str) -> dict:
        """Return a list of nodes in a .tscn file with name/type/parent."""
        p = Path(tscn_path)
        if not p.exists():
            return {"error": f"File not found: {tscn_path}"}
        text = p.read_text(encoding="utf-8")
        _, sections = _parse_ini_like(text)
        nodes = []
        for header, props in sections:
            if header.get("__name__") != "node":
                continue
            nodes.append({
                "name": header.get("name"),
                "type": header.get("type"),
                "parent": header.get("parent"),
                "instance": header.get("instance"),
                "groups": header.get("groups"),
                "properties": {k: v for k, v in props.items()},
            })
        return {"nodes": nodes, "count": len(nodes)}

    def get_scene_node(self, tscn_path: str, name: str) -> dict:
        """Return a single node's full record by name."""
        data = self.get_scene_nodes(tscn_path)
        if "error" in data:
            return data
        for n in data.get("nodes", []):
            if n.get("name") == name:
                return {"found": True, "node": n}
        return {"found": False, "name": name, "count": data.get("count", 0)}

    def get_scene_ext_resources(self, tscn_path: str) -> dict:
        """Return all [ext_resource] entries from a .tscn file."""
        p = Path(tscn_path)
        if not p.exists():
            return {"error": f"File not found: {tscn_path}"}
        text = p.read_text(encoding="utf-8")
        _, sections = _parse_ini_like(text)
        resources = []
        for header, _ in sections:
            if header.get("__name__") == "ext_resource":
                resources.append({k: v for k, v in header.items() if k != "__name__"})
        return {"ext_resources": resources, "count": len(resources)}

    def get_scene_sub_resources(self, tscn_path: str) -> dict:
        """Return all [sub_resource] entries from a .tscn file."""
        p = Path(tscn_path)
        if not p.exists():
            return {"error": f"File not found: {tscn_path}"}
        text = p.read_text(encoding="utf-8")
        _, sections = _parse_ini_like(text)
        resources = []
        for header, props in sections:
            if header.get("__name__") == "sub_resource":
                entry = {k: v for k, v in header.items() if k != "__name__"}
                entry["properties"] = props
                resources.append(entry)
        return {"sub_resources": resources, "count": len(resources)}

    def check_node_exists(self, tscn_path: str, name: str) -> dict:
        """Check if a node with the given name exists in a scene."""
        data = self.get_scene_nodes(tscn_path)
        if "error" in data:
            return {**data, "exists": False}
        for n in data.get("nodes", []):
            if n.get("name") == name:
                return {"exists": True, "name": name, "type": n.get("type")}
        return {"exists": False, "name": name, "count": data.get("count", 0)}

    def check_node_type(self, tscn_path: str, name: str, type_name: str) -> dict:
        """Check if a node has the expected type."""
        data = self.get_scene_node(tscn_path, name)
        if "error" in data:
            return {**data, "match": False}
        if not data.get("found"):
            return {"match": False, "name": name, "reason": "node not found"}
        actual = data["node"].get("type")
        return {"match": actual == type_name, "name": name, "expected": type_name, "actual": actual}

    def check_node_parent(self, tscn_path: str, name: str, parent: str) -> dict:
        """Check if a node has the expected parent path (as used by Godot: '.', 'Root', etc.)."""
        data = self.get_scene_node(tscn_path, name)
        if "error" in data:
            return {**data, "match": False}
        if not data.get("found"):
            return {"match": False, "name": name, "reason": "node not found"}
        actual = data["node"].get("parent")
        return {"match": actual == parent, "name": name, "expected": parent, "actual": actual}

    def check_node_property(self, tscn_path: str, name: str, prop: str, expected: str) -> dict:
        """Check if a node has a given property with the expected value."""
        try:
            expected_val = json.loads(expected)
        except (json.JSONDecodeError, TypeError):
            expected_val = expected
        data = self.get_scene_node(tscn_path, name)
        if "error" in data:
            return {**data, "match": False}
        if not data.get("found"):
            return {"match": False, "name": name, "reason": "node not found"}
        props = data["node"].get("properties", {})
        if prop not in props:
            return {"match": False, "name": name, "prop": prop, "reason": "property not set"}
        actual = props[prop]
        match = actual == expected_val
        # Leniency: for string comparisons, also match substring of raw
        if not match and isinstance(actual, str) and isinstance(expected_val, str):
            match = expected_val in actual
        return {"match": match, "name": name, "prop": prop,
                "expected": expected_val, "actual": actual}

    def check_scene_node_count(self, tscn_path: str, expected: int) -> dict:
        """Check if the scene has exactly `expected` nodes."""
        data = self.get_scene_nodes(tscn_path)
        if "error" in data:
            return {**data, "match": False}
        actual = data.get("count", 0)
        return {"match": actual == expected, "expected": expected, "actual": actual}

    def check_scene_has_script(self, tscn_path: str, script_hint: str) -> dict:
        """Check if the scene references a script whose path contains `script_hint`."""
        data = self.get_scene_ext_resources(tscn_path)
        if "error" in data:
            return {**data, "found": False}
        for r in data.get("ext_resources", []):
            if r.get("type") == "Script":
                path = str(r.get("path", ""))
                if script_hint in path:
                    return {"found": True, "path": path}
        return {"found": False, "script_hint": script_hint}

    # ---- .gd scripts ----

    def get_script_info(self, gd_path: str) -> dict:
        """Parse a .gd script file and return structural info."""
        p = Path(gd_path)
        if not p.exists():
            return {"error": f"File not found: {gd_path}"}
        text = p.read_text(encoding="utf-8")
        class_name = None
        extends = None
        funcs: list[dict] = []
        exports: list[dict] = []
        signals: list[str] = []
        const_names: list[str] = []
        var_names: list[str] = []

        lines = text.splitlines()
        for i, raw in enumerate(lines):
            line = raw.strip()
            if line.startswith("class_name "):
                class_name = line.split()[1].rstrip(":")
            elif line.startswith("extends "):
                extends = line[len("extends "):].strip()
            elif line.startswith("func "):
                m = re.match(r"func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)", line)
                if m:
                    name = m.group(1)
                    args_raw = m.group(2).strip()
                    arg_count = 0 if not args_raw else len([a for a in args_raw.split(",") if a.strip()])
                    funcs.append({"name": name, "arg_count": arg_count})
            elif line.startswith("signal "):
                m = re.match(r"signal\s+([A-Za-z_][A-Za-z0-9_]*)", line)
                if m:
                    signals.append(m.group(1))
            elif line.startswith("@export"):
                # could be on same line as var or next line
                rest = line
                if "var " not in rest and i + 1 < len(lines):
                    rest = line + " " + lines[i + 1].strip()
                m = re.search(r"var\s+([A-Za-z_][A-Za-z0-9_]*)", rest)
                if m:
                    exports.append({"name": m.group(1), "line": rest})
            elif line.startswith("const "):
                m = re.match(r"const\s+([A-Za-z_][A-Za-z0-9_]*)", line)
                if m:
                    const_names.append(m.group(1))
            elif line.startswith("var "):
                m = re.match(r"var\s+([A-Za-z_][A-Za-z0-9_]*)", line)
                if m:
                    var_names.append(m.group(1))

        return {
            "path": str(p),
            "class_name": class_name,
            "extends": extends,
            "funcs": funcs,
            "func_count": len(funcs),
            "exports": exports,
            "export_count": len(exports),
            "signals": signals,
            "const_names": const_names,
            "var_names": var_names,
            "line_count": len(lines),
        }

    def check_script_has_class_name(self, gd_path: str, expected: str) -> dict:
        data = self.get_script_info(gd_path)
        if "error" in data:
            return {**data, "match": False}
        actual = data.get("class_name")
        return {"match": actual == expected, "expected": expected, "actual": actual}

    def check_script_extends(self, gd_path: str, expected: str) -> dict:
        data = self.get_script_info(gd_path)
        if "error" in data:
            return {**data, "match": False}
        actual = data.get("extends") or ""
        return {"match": expected in actual, "expected": expected, "actual": actual}

    def check_script_has_func(self, gd_path: str, func_name: str) -> dict:
        data = self.get_script_info(gd_path)
        if "error" in data:
            return {**data, "exists": False}
        for f in data.get("funcs", []):
            if f.get("name") == func_name:
                return {"exists": True, "name": func_name, "arg_count": f.get("arg_count")}
        return {"exists": False, "name": func_name}

    def check_script_has_export(self, gd_path: str, var_name: str) -> dict:
        data = self.get_script_info(gd_path)
        if "error" in data:
            return {**data, "exists": False}
        for e in data.get("exports", []):
            if e.get("name") == var_name:
                return {"exists": True, "name": var_name}
        return {"exists": False, "name": var_name}

    def check_script_has_signal(self, gd_path: str, signal_name: str) -> dict:
        data = self.get_script_info(gd_path)
        if "error" in data:
            return {**data, "exists": False}
        exists = signal_name in data.get("signals", [])
        return {"exists": exists, "name": signal_name}

    # ---- .tres resources ----

    def get_resource_info(self, tres_path: str) -> dict:
        """Parse a .tres resource file."""
        p = Path(tres_path)
        if not p.exists():
            return {"error": f"File not found: {tres_path}"}
        text = p.read_text(encoding="utf-8")
        header_values, sections = _parse_ini_like(text)
        # The main resource is a [resource] section
        resource_props: dict[str, Any] = {}
        gd_resource_header: dict[str, Any] = {}
        for header, props in sections:
            name = header.get("__name__")
            if name == "gd_resource":
                gd_resource_header = header
            elif name == "resource":
                resource_props.update(props)
        return {
            "path": str(p),
            "type": gd_resource_header.get("type"),
            "format": gd_resource_header.get("format"),
            "properties": resource_props,
            "property_count": len(resource_props),
        }

    def check_resource_type(self, tres_path: str, expected: str) -> dict:
        data = self.get_resource_info(tres_path)
        if "error" in data:
            return {**data, "match": False}
        actual = data.get("type")
        return {"match": actual == expected, "expected": expected, "actual": actual}

    def check_resource_property(self, tres_path: str, prop: str, expected: str) -> dict:
        try:
            expected_val = json.loads(expected)
        except (json.JSONDecodeError, TypeError):
            expected_val = expected
        data = self.get_resource_info(tres_path)
        if "error" in data:
            return {**data, "match": False}
        props = data.get("properties", {})
        if prop not in props:
            return {"match": False, "prop": prop, "reason": "property not set"}
        actual = props[prop]
        match = actual == expected_val
        if not match and isinstance(actual, str) and isinstance(expected_val, str):
            match = expected_val in actual
        return {"match": match, "prop": prop, "expected": expected_val, "actual": actual}

    # ---- editor settings ----

    def _find_editor_settings(self) -> Path | None:
        """Return the path to editor_settings-4.X.tres or None if not present."""
        base = Path.home() / ".config" / "godot"
        if not base.exists():
            return None
        matches = sorted(base.glob("editor_settings-4*.tres"))
        return matches[0] if matches else None

    def get_editor_settings(self, key: str | None = None) -> Any:
        """Read the [resource] section of editor_settings-4.X.tres."""
        path = self._find_editor_settings()
        if not path:
            return {"error": "editor_settings not found"}
        data = self.get_resource_info(str(path))
        if "error" in data:
            return data
        props = data.get("properties", {})
        if key is None:
            return {"path": str(path), "keys": props, "count": len(props)}
        if key in props:
            return {"key": key, "value": props[key]}
        return {"key": key, "value": None, "found": False}

    def check_editor_setting(self, key: str, expected: str) -> dict:
        try:
            expected_val = json.loads(expected)
        except (json.JSONDecodeError, TypeError):
            expected_val = expected
        data = self.get_editor_settings(key)
        if isinstance(data, dict) and "error" in data:
            return {**data, "match": False, "key": key, "expected": expected_val}
        actual = data.get("value") if isinstance(data, dict) else None
        match = actual == expected_val
        return {"match": match, "key": key, "expected": expected_val, "actual": actual}

    # ---- generic file helpers ----

    def check_file_exists(self, path: str) -> dict:
        p = Path(path)
        exists = p.exists()
        result = {"exists": exists, "path": str(p)}
        if exists:
            try:
                st = p.stat()
                result["size"] = st.st_size
                result["is_file"] = p.is_file()
                result["is_dir"] = p.is_dir()
            except OSError:
                pass
        return result

    def check_file_contains(self, path: str, text: str) -> dict:
        p = Path(path)
        if not p.exists():
            return {"contains": False, "error": f"File not found: {path}"}
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            return {"contains": False, "error": str(e)}
        return {"contains": text in content, "path": str(p)}

    def list_project_files(self, project_dir: str, extension: str) -> dict:
        """Recursively list project files with a given extension (e.g. 'tscn', 'gd')."""
        base = Path(project_dir)
        if not base.exists():
            return {"error": f"Directory not found: {project_dir}"}
        ext = extension.lstrip(".")
        files = [str(p) for p in sorted(base.rglob(f"*.{ext}"))]
        return {"extension": ext, "files": files, "count": len(files)}


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------

def _int(x: str) -> int:
    try:
        return int(x)
    except (ValueError, TypeError):
        return 0


COMMANDS = {
    # project.godot
    "project-sections": ("List top-level sections in project.godot",
                         lambda v, a: v.get_project_sections(a[0])),
    "project-section": ("Dump all keys in a project.godot section",
                        lambda v, a: v.get_project_section(a[0], a[1])),
    "project-setting": ("Get a project.godot 'section/subkey' value",
                        lambda v, a: v.get_project_setting(a[0], a[1])),
    "input-actions": ("List input actions",
                      lambda v, a: v.get_input_actions(a[0])),
    "autoloads": ("List autoloads",
                  lambda v, a: v.get_autoloads(a[0])),

    "check-project-parses": ("Run godot4 --check-only on project",
                             lambda v, a: v.check_project_parses(a[0])),
    "check-project-setting": ("Check project.godot setting value",
                              lambda v, a: v.check_project_setting(a[0], a[1], a[2])),
    "check-input-action": ("Check input action exists",
                           lambda v, a: v.check_input_action_exists(a[0], a[1])),
    "check-input-action-key": ("Check input action has a key binding",
                               lambda v, a: v.check_input_action_has_key(a[0], a[1], a[2])),
    "check-autoload": ("Check autoload exists",
                       lambda v, a: v.check_autoload_exists(a[0], a[1])),

    # .tscn
    "scene-nodes": ("List nodes in a .tscn file",
                    lambda v, a: v.get_scene_nodes(a[0])),
    "scene-node": ("Get info for one node by name",
                   lambda v, a: v.get_scene_node(a[0], a[1])),
    "scene-ext-resources": ("List ext_resource entries in a .tscn",
                            lambda v, a: v.get_scene_ext_resources(a[0])),
    "scene-sub-resources": ("List sub_resource entries in a .tscn",
                            lambda v, a: v.get_scene_sub_resources(a[0])),
    "check-node-exists": ("Check node exists in scene",
                          lambda v, a: v.check_node_exists(a[0], a[1])),
    "check-node-type": ("Check node has expected type",
                        lambda v, a: v.check_node_type(a[0], a[1], a[2])),
    "check-node-parent": ("Check node has expected parent path",
                          lambda v, a: v.check_node_parent(a[0], a[1], a[2])),
    "check-node-property": ("Check node property value",
                            lambda v, a: v.check_node_property(a[0], a[1], a[2], a[3])),
    "check-node-count": ("Check scene node count",
                         lambda v, a: v.check_scene_node_count(a[0], _int(a[1]))),
    "check-scene-has-script": ("Check scene has a script ext_resource",
                               lambda v, a: v.check_scene_has_script(a[0], a[1])),

    # .gd
    "script-info": ("Parse a .gd script and return structural info",
                    lambda v, a: v.get_script_info(a[0])),
    "check-script-class-name": ("Check script class_name",
                                lambda v, a: v.check_script_has_class_name(a[0], a[1])),
    "check-script-extends": ("Check script extends substring",
                             lambda v, a: v.check_script_extends(a[0], a[1])),
    "check-script-func": ("Check script defines function",
                          lambda v, a: v.check_script_has_func(a[0], a[1])),
    "check-script-export": ("Check script has @export variable",
                            lambda v, a: v.check_script_has_export(a[0], a[1])),
    "check-script-signal": ("Check script declares signal",
                            lambda v, a: v.check_script_has_signal(a[0], a[1])),

    # .tres
    "resource-info": ("Parse a .tres resource file",
                      lambda v, a: v.get_resource_info(a[0])),
    "check-resource-type": ("Check resource type",
                            lambda v, a: v.check_resource_type(a[0], a[1])),
    "check-resource-property": ("Check resource property value",
                                lambda v, a: v.check_resource_property(a[0], a[1], a[2])),

    # editor settings
    "editor-settings": ("Read editor_settings-4.X.tres (optional key)",
                        lambda v, a: v.get_editor_settings(a[0] if a else None)),
    "check-editor-setting": ("Check editor setting value",
                             lambda v, a: v.check_editor_setting(a[0], a[1])),

    # generic file helpers
    "file-exists": ("Check file exists",
                    lambda v, a: v.check_file_exists(a[0])),
    "check-file-contains": ("Check file contains text",
                            lambda v, a: v.check_file_contains(a[0], a[1])),
    "list-files": ("List project files by extension",
                   lambda v, a: v.list_project_files(a[0], a[1])),
}


def _print_usage() -> None:
    print("Godot 4 Verifier — inspect Godot 4 projects for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print("\nAll output is JSON.")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = Godot4Verifier()
    _, handler = COMMANDS[cmd]
    try:
        result = handler(v, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
