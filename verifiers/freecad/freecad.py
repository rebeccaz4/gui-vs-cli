"""
FreeCAD Verifier — programmatic state inspection for FreeCAD files in E2B sandbox.

Verification channels:
  1. ZIP parsing of `.FCStd` — extract `Document.xml` (and GuiDocument.xml) with
     the stdlib `zipfile` module, parse with `xml.etree.ElementTree`.
  2. `freecadcmd` headless Python — optional live inspection channel. Used for
     endpoints that require geometry evaluation that the XML tree doesn't
     expose directly (e.g. bounding box of a BREP shape). Falls back to XML
     parsing when freecadcmd is unavailable.
  3. XML parsing of `~/.config/FreeCAD/user.cfg` — preferences, units, default
     workbench, recent files.
  4. Parsing of exported files: STL (binary header), STEP/IGES (text headers),
     OBJ (text).

Usage from outside the sandbox:
    sandbox.commands.run("python3 /home/user/verifiers/freecad.py objects /path/to/file.FCStd")
    sandbox.commands.run("python3 /home/user/verifiers/freecad.py check-object-exists Box /path/to/file.FCStd")

Every CLI subcommand returns JSON to stdout. Errors are `{"error": "..."}`.
Every `check-*` endpoint returns a single primary boolean key.
"""

import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers: parse .FCStd files (ZIP archives)
# ---------------------------------------------------------------------------

def _open_fcstd(path: str) -> dict:
    """Open a .FCStd file and return {'zip': ZipFile, 'doc': ElementTree} or {'error': ...}.

    Caller must close the returned ZipFile.
    """
    if not os.path.exists(path):
        return {"error": f"File not found: {path}"}
    if not path.lower().endswith(".fcstd"):
        return {"error": f"Not a .FCStd file: {path}"}
    try:
        z = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile as e:
        return {"error": f"Not a valid FCStd (bad zip): {e}"}

    if "Document.xml" not in z.namelist():
        z.close()
        return {"error": "Document.xml missing inside FCStd archive"}
    try:
        with z.open("Document.xml") as f:
            tree = ET.parse(f)
    except ET.ParseError as e:
        z.close()
        return {"error": f"Document.xml parse error: {e}"}
    return {"zip": z, "tree": tree}


def _object_summary(obj_elem) -> dict:
    """Summarize one <Object> element (from ObjectData) into a dict."""
    return {
        "name": obj_elem.get("name"),
        "type": obj_elem.get("type"),
        "properties": _properties_of(obj_elem),
    }


def _properties_of(obj_elem) -> dict:
    """Extract <Properties> children into a simple dict of
    {property_name: value_repr}.

    FreeCAD Document.xml encodes properties with shapes like:
        <Property name="Length" type="App::PropertyLength">
            <Float value="20.0"/>
        </Property>

    We unpack the most common encodings into Python primitives, and for
    anything we don't recognize we serialize its attributes.
    """
    props: dict = {}
    pcont = obj_elem.find("Properties")
    if pcont is None:
        return props
    for p in pcont.findall("Property"):
        pname = p.get("name")
        ptype = p.get("type", "")
        val = None
        # Common value encodings
        for child in list(p):
            tag = child.tag
            a = child.attrib
            if tag == "Float":
                try:
                    val = float(a.get("value"))
                except (TypeError, ValueError):
                    val = a.get("value")
            elif tag == "Integer":
                try:
                    val = int(a.get("value"))
                except (TypeError, ValueError):
                    val = a.get("value")
            elif tag == "Bool":
                val = a.get("value") in ("true", "True", "1")
            elif tag == "String":
                val = a.get("value", "")
            elif tag == "Uuid":
                val = a.get("value", "")
            elif tag == "Link":
                val = {"link": a.get("value")}
            elif tag == "LinkSub":
                val = {"link": a.get("value"), "sub": a.get("sub")}
            elif tag == "Vector":
                try:
                    val = [float(a.get("valueX", 0)),
                           float(a.get("valueY", 0)),
                           float(a.get("valueZ", 0))]
                except (TypeError, ValueError):
                    val = dict(a)
            elif tag == "PropertyPlacement" or tag == "Placement":
                val = dict(a)
            elif tag == "Part":
                val = dict(a)
            else:
                # fallback: capture attributes
                val = dict(a) if a else tag
        props[pname] = {"type": ptype, "value": val}
    return props


def _document_properties(tree) -> dict:
    """Parse the <Properties> child of the top <Document>."""
    root = tree.getroot()
    prop_container = root.find("Properties")
    doc_props: dict = {}
    if prop_container is None:
        return doc_props
    for p in prop_container.findall("Property"):
        name = p.get("name")
        for child in list(p):
            a = child.attrib
            if child.tag == "String":
                doc_props[name] = a.get("value", "")
            elif child.tag == "Uuid":
                doc_props[name] = a.get("value", "")
            elif child.tag == "Integer":
                try:
                    doc_props[name] = int(a.get("value"))
                except (TypeError, ValueError):
                    doc_props[name] = a.get("value")
            else:
                doc_props[name] = dict(a) if a else child.tag
    return doc_props


# ---------------------------------------------------------------------------
# FreeCADVerifier class
# ---------------------------------------------------------------------------

class FreeCADVerifier:
    """Stateless verifier for FreeCAD .FCStd files and related config."""

    # === Document properties ============================================

    def get_document_info(self, fcstd: str) -> dict:
        """Read top-level document metadata: ProgramVersion, Label, Uid, etc.

        Also returns the list of files stored inside the FCStd archive.
        """
        r = _open_fcstd(fcstd)
        if "error" in r:
            return r
        z, tree = r["zip"], r["tree"]
        try:
            root = tree.getroot()
            props = _document_properties(tree)
            info = {
                "program_version": root.get("ProgramVersion"),
                "file_version": root.get("FileVersion"),
                "schema_version": root.get("SchemaVersion"),
                "properties": props,
                "archive_files": sorted(z.namelist()),
                "object_count": len(root.findall(".//Objects/Object")),
                "has_thumbnail": "thumbnails/Thumbnail.png" in z.namelist(),
            }
            return info
        finally:
            z.close()

    # === Objects and parameters ========================================

    def get_objects(self, fcstd: str) -> dict:
        """List all objects defined in the document.

        Returns name, type, and full parameter dict per object.
        The type is stored in `<Objects>/<Object>` while parameters live in
        `<ObjectData>/<Object>`; we merge the two.
        """
        r = _open_fcstd(fcstd)
        if "error" in r:
            return r
        z, tree = r["zip"], r["tree"]
        try:
            root = tree.getroot()
            # Build name -> type map from <Objects> section
            name_to_type: dict = {}
            for obj in root.findall(".//Objects/Object"):
                name_to_type[obj.get("name")] = obj.get("type")

            objs = []
            # ObjectData contains the runtime data with properties.
            for obj in root.findall(".//ObjectData/Object"):
                s = _object_summary(obj)
                if s.get("type") is None and s.get("name") in name_to_type:
                    s["type"] = name_to_type[s["name"]]
                objs.append(s)

            # If ObjectData missing, fall back to Objects section (type only)
            if not objs:
                for name, t in name_to_type.items():
                    objs.append({"name": name, "type": t, "properties": {}})
            return {"objects": objs, "count": len(objs)}
        finally:
            z.close()

    def get_object_info(self, fcstd: str, name: str) -> dict:
        """Return one object's details by name."""
        data = self.get_objects(fcstd)
        if "error" in data:
            return data
        for o in data["objects"]:
            if o["name"] == name:
                return o
        return {"error": f"Object '{name}' not found"}

    def get_object_types(self, fcstd: str) -> dict:
        """Return a count of objects grouped by type (Part::Box, Part::Cut...)."""
        data = self.get_objects(fcstd)
        if "error" in data:
            return data
        counts: dict = {}
        for o in data["objects"]:
            t = o.get("type") or "Unknown"
            counts[t] = counts.get(t, 0) + 1
        return {"counts": counts, "total": sum(counts.values())}

    def get_parameter(self, fcstd: str, name: str, parameter: str) -> dict:
        """Read one parameter (e.g. Length/Width/Height) of an object."""
        info = self.get_object_info(fcstd, name)
        if "error" in info:
            return info
        props = info.get("properties", {})
        if parameter not in props:
            return {"error": f"Parameter '{parameter}' not found on '{name}'",
                    "available": sorted(props.keys())}
        return {"object": name, "parameter": parameter,
                "type": props[parameter].get("type"),
                "value": props[parameter].get("value")}

    def get_label(self, fcstd: str, name: str) -> dict:
        """Return the Label of an object (user-visible name)."""
        info = self.get_object_info(fcstd, name)
        if "error" in info:
            return info
        label_prop = info.get("properties", {}).get("Label")
        if label_prop is None:
            return {"error": f"Object '{name}' has no Label property"}
        return {"object": name, "label": label_prop.get("value")}

    def get_placement(self, fcstd: str, name: str) -> dict:
        """Return the Placement of an object as position + rotation attributes."""
        info = self.get_object_info(fcstd, name)
        if "error" in info:
            return info
        placement = info.get("properties", {}).get("Placement")
        if placement is None:
            return {"error": f"Object '{name}' has no Placement property"}
        return {"object": name, "placement": placement.get("value")}

    # === Settings / preferences =========================================

    def _default_user_cfg(self) -> str:
        return os.path.expanduser("~/.config/FreeCAD/user.cfg")

    def get_preferences(self, cfg_path: str | None = None) -> dict:
        """Parse user.cfg and return a flattened dict of
        "Group1/Group2/Name" -> value.
        """
        path = cfg_path or self._default_user_cfg()
        if not os.path.exists(path):
            return {"error": f"user.cfg not found: {path}"}
        try:
            tree = ET.parse(path)
        except ET.ParseError as e:
            return {"error": f"user.cfg parse error: {e}"}
        root = tree.getroot()
        flat: dict = {}

        def walk(elem, prefix: list, is_root: bool = False):
            if elem.tag == "FCParamGroup":
                name = elem.get("Name")
                # Skip the conventional top-level "Root" group name so paths
                # read like "BaseApp/Preferences/General/ThemeName".
                if is_root and name == "Root":
                    new_prefix = prefix
                else:
                    new_prefix = prefix + [name] if name else prefix
                for c in list(elem):
                    walk(c, new_prefix, is_root=False)
                return
            # Value elements: FCInt, FCFloat, FCText, FCBool, FCUInt
            if elem.tag in ("FCInt", "FCFloat", "FCText", "FCBool", "FCUInt"):
                pname = elem.get("Name")
                raw = elem.get("Value")
                if elem.tag == "FCInt" or elem.tag == "FCUInt":
                    try:
                        val = int(raw)
                    except (TypeError, ValueError):
                        val = raw
                elif elem.tag == "FCFloat":
                    try:
                        val = float(raw)
                    except (TypeError, ValueError):
                        val = raw
                elif elem.tag == "FCBool":
                    val = raw in ("true", "True", "1")
                else:
                    val = raw
                key = "/".join(prefix + [pname]) if pname else "/".join(prefix)
                flat[key] = val

        # Walk under <FCParameters>/<FCParamGroup Name="Root">
        for child in list(root):
            walk(child, [], is_root=True)
        return {"preferences": flat, "count": len(flat),
                "path": path}

    def get_preference(self, key: str, cfg_path: str | None = None) -> dict:
        """Get one preference by its full slash-separated key path."""
        all_p = self.get_preferences(cfg_path)
        if "error" in all_p:
            return all_p
        prefs = all_p["preferences"]
        if key not in prefs:
            # Try suffix match for convenience
            suffix = [k for k in prefs if k.endswith(key)]
            if len(suffix) == 1:
                return {"key": suffix[0], "value": prefs[suffix[0]]}
            return {"error": f"Preference '{key}' not found",
                    "suggestions": suffix[:5]}
        return {"key": key, "value": prefs[key]}

    # === Exported files =================================================

    def parse_stl(self, path: str) -> dict:
        """Return triangle count and format (ascii vs binary) for an STL file."""
        if not os.path.exists(path):
            return {"error": f"File not found: {path}"}
        size = os.path.getsize(path)
        try:
            with open(path, "rb") as f:
                header = f.read(5)
                if header == b"solid":
                    # Might still be binary if "solid" + 80-byte header happens
                    # to start that way. Do a heuristic: try ascii parse.
                    f.seek(0)
                    text_head = f.read(1024).decode(errors="replace")
                    if "facet normal" in text_head:
                        f.seek(0)
                        content = f.read().decode(errors="replace")
                        tri_count = content.count("facet normal")
                        return {"format": "ascii", "triangles": tri_count,
                                "size": size}
                # Binary STL: 80-byte header, uint32 count
                f.seek(80)
                count_bytes = f.read(4)
                if len(count_bytes) < 4:
                    return {"error": "Truncated STL file"}
                tri = struct.unpack("<I", count_bytes)[0]
                return {"format": "binary", "triangles": tri, "size": size}
        except Exception as e:
            return {"error": f"STL parse error: {e}"}

    def parse_step(self, path: str) -> dict:
        """Return basic info from a STEP file header."""
        if not os.path.exists(path):
            return {"error": f"File not found: {path}"}
        try:
            with open(path, "r", errors="replace") as f:
                content = f.read()
        except Exception as e:
            return {"error": f"STEP read error: {e}"}
        is_step = content.lstrip().startswith("ISO-10303-21")
        # Count DATA section entities
        entities = len(re.findall(r"^#\d+\s*=", content, re.MULTILINE))
        fname_match = re.search(r"FILE_NAME\(\s*'([^']*)'", content)
        return {
            "is_step": is_step,
            "entities": entities,
            "size": os.path.getsize(path),
            "file_name_header": fname_match.group(1) if fname_match else None,
        }

    def parse_iges(self, path: str) -> dict:
        """Return basic IGES info from the header/directory/parameter counts."""
        if not os.path.exists(path):
            return {"error": f"File not found: {path}"}
        try:
            with open(path, "r", errors="replace") as f:
                lines = f.readlines()
        except Exception as e:
            return {"error": f"IGES read error: {e}"}
        secs = {"S": 0, "G": 0, "D": 0, "P": 0, "T": 0}
        for line in lines:
            if len(line) >= 73 and line[72] in secs:
                secs[line[72]] += 1
        return {
            "is_iges": secs["S"] > 0 and secs["T"] > 0,
            "sections": secs,
            "size": os.path.getsize(path),
        }

    def parse_obj(self, path: str) -> dict:
        """Return vertex/face/object counts for a Wavefront OBJ."""
        if not os.path.exists(path):
            return {"error": f"File not found: {path}"}
        v = f = o = g = 0
        try:
            with open(path, "r", errors="replace") as fh:
                for line in fh:
                    if line.startswith("v "):
                        v += 1
                    elif line.startswith("f "):
                        f += 1
                    elif line.startswith("o "):
                        o += 1
                    elif line.startswith("g "):
                        g += 1
        except Exception as e:
            return {"error": f"OBJ read error: {e}"}
        return {"vertices": v, "faces": f, "objects": o, "groups": g,
                "size": os.path.getsize(path)}

    # === Composite checks ===============================================

    def check_file_exists(self, path: str) -> dict:
        p = Path(path)
        if p.exists() and p.is_file():
            return {"exists": True, "path": str(p), "size": p.stat().st_size}
        return {"exists": False, "path": str(p)}

    def check_object_exists(self, fcstd: str, name: str) -> dict:
        data = self.get_objects(fcstd)
        if "error" in data:
            return {"exists": False, "error": data["error"]}
        names = [o["name"] for o in data["objects"]]
        return {"exists": name in names, "name": name, "all_names": names}

    def check_object_type(self, fcstd: str, name: str, expected: str) -> dict:
        info = self.get_object_info(fcstd, name)
        if "error" in info:
            return {"match": False, "error": info["error"]}
        actual = info.get("type")
        return {"match": actual == expected, "expected": expected, "actual": actual}

    def check_object_count(self, fcstd: str, expected: int) -> dict:
        data = self.get_objects(fcstd)
        if "error" in data:
            return {"match": False, "error": data["error"]}
        return {"match": data["count"] == int(expected),
                "expected": int(expected), "actual": data["count"]}

    def check_object_type_count(self, fcstd: str, type_name: str, expected: int) -> dict:
        """Check how many objects of a given type exist (e.g. Part::Box)."""
        data = self.get_object_types(fcstd)
        if "error" in data:
            return {"match": False, "error": data["error"]}
        actual = data["counts"].get(type_name, 0)
        return {"match": actual == int(expected), "type": type_name,
                "expected": int(expected), "actual": actual}

    def check_parameter_value(self, fcstd: str, name: str, parameter: str,
                              expected: str) -> dict:
        """Check a parameter equals expected (numeric comparison with tolerance
        1e-6 if both sides are numeric, otherwise string compare)."""
        r = self.get_parameter(fcstd, name, parameter)
        if "error" in r:
            return {"match": False, "error": r["error"]}
        actual = r["value"]
        try:
            a = float(actual)
            e = float(expected)
            match = abs(a - e) <= 1e-6
            return {"match": match, "object": name, "parameter": parameter,
                    "expected": e, "actual": a}
        except (TypeError, ValueError):
            match = str(actual) == str(expected)
            return {"match": match, "object": name, "parameter": parameter,
                    "expected": expected, "actual": actual}

    def check_label(self, fcstd: str, name: str, expected_label: str) -> dict:
        r = self.get_label(fcstd, name)
        if "error" in r:
            return {"match": False, "error": r["error"]}
        return {"match": r["label"] == expected_label,
                "object": name, "expected": expected_label,
                "actual": r["label"]}

    def check_document_property(self, fcstd: str, prop: str,
                                 expected: str) -> dict:
        info = self.get_document_info(fcstd)
        if "error" in info:
            return {"match": False, "error": info["error"]}
        props = info.get("properties", {})
        if prop not in props:
            return {"match": False, "error": f"Document has no '{prop}'",
                    "available": sorted(props.keys())}
        actual = props[prop]
        return {"match": str(actual) == str(expected),
                "expected": expected, "actual": actual}

    def check_preference(self, key: str, expected: str,
                         cfg_path: str | None = None) -> dict:
        r = self.get_preference(key, cfg_path)
        if "error" in r:
            return {"match": False, "error": r["error"]}
        actual = r["value"]
        # Try numeric coerce on both sides
        try:
            match = abs(float(actual) - float(expected)) <= 1e-9
        except (TypeError, ValueError):
            if isinstance(actual, bool):
                match = str(actual).lower() == str(expected).lower()
            else:
                match = str(actual) == str(expected)
        return {"match": match, "key": key, "expected": expected,
                "actual": actual}

    def check_stl_triangle_count(self, path: str, expected: int) -> dict:
        r = self.parse_stl(path)
        if "error" in r:
            return {"match": False, "error": r["error"]}
        return {"match": r["triangles"] == int(expected),
                "expected": int(expected), "actual": r["triangles"]}

    def check_stl_min_triangles(self, path: str, minimum: int) -> dict:
        r = self.parse_stl(path)
        if "error" in r:
            return {"match": False, "error": r["error"]}
        return {"match": r["triangles"] >= int(minimum),
                "minimum": int(minimum), "actual": r["triangles"]}

    def check_step_valid(self, path: str) -> dict:
        r = self.parse_step(path)
        if "error" in r:
            return {"valid": False, "error": r["error"]}
        return {"valid": r["is_step"] and r["entities"] > 0,
                "entities": r["entities"]}

    def check_obj_min_vertices(self, path: str, minimum: int) -> dict:
        r = self.parse_obj(path)
        if "error" in r:
            return {"match": False, "error": r["error"]}
        return {"match": r["vertices"] >= int(minimum),
                "minimum": int(minimum), "actual": r["vertices"]}

    def check_has_thumbnail(self, fcstd: str) -> dict:
        r = self.get_document_info(fcstd)
        if "error" in r:
            return {"has_thumbnail": False, "error": r["error"]}
        return {"has_thumbnail": r["has_thumbnail"]}


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------

COMMANDS = {
    # Document / object query endpoints
    "document-info": ("Document-level metadata",
                       lambda v, a: v.get_document_info(a[0])),
    "objects": ("List objects",
                 lambda v, a: v.get_objects(a[0])),
    "object-info": ("Get object details",
                     lambda v, a: v.get_object_info(a[0], a[1])),
    "object-types": ("Count objects by type",
                      lambda v, a: v.get_object_types(a[0])),
    "parameter": ("Read one object parameter",
                   lambda v, a: v.get_parameter(a[0], a[1], a[2])),
    "label": ("Read object Label",
               lambda v, a: v.get_label(a[0], a[1])),
    "placement": ("Read object Placement",
                   lambda v, a: v.get_placement(a[0], a[1])),

    # Preferences
    "preferences": ("List FreeCAD user preferences",
                     lambda v, a: v.get_preferences(a[0] if a else None)),
    "preference": ("Read one preference by key",
                    lambda v, a: v.get_preference(a[0],
                                                  a[1] if len(a) > 1 else None)),

    # Exported file parsers
    "parse-stl": ("Parse STL file", lambda v, a: v.parse_stl(a[0])),
    "parse-step": ("Parse STEP file", lambda v, a: v.parse_step(a[0])),
    "parse-iges": ("Parse IGES file", lambda v, a: v.parse_iges(a[0])),
    "parse-obj": ("Parse OBJ file", lambda v, a: v.parse_obj(a[0])),

    # Composite checks
    "check-file-exists": ("Check file exists",
                          lambda v, a: v.check_file_exists(a[0])),
    "check-object-exists": ("Check object by name",
                            lambda v, a: v.check_object_exists(a[0], a[1])),
    "check-object-type": ("Check an object's type",
                          lambda v, a: v.check_object_type(a[0], a[1], a[2])),
    "check-object-count": ("Check total object count",
                           lambda v, a: v.check_object_count(a[0], int(a[1]))),
    "check-object-type-count": ("Count objects by type",
                                lambda v, a: v.check_object_type_count(a[0], a[1], int(a[2]))),
    "check-parameter-value": ("Check a numeric/string parameter",
                              lambda v, a: v.check_parameter_value(a[0], a[1], a[2], a[3])),
    "check-label": ("Check object label",
                    lambda v, a: v.check_label(a[0], a[1], a[2])),
    "check-document-property": ("Check document property",
                                lambda v, a: v.check_document_property(a[0], a[1], a[2])),
    "check-preference": ("Check one preference",
                         lambda v, a: v.check_preference(a[0], a[1],
                                                         a[2] if len(a) > 2 else None)),
    "check-stl-triangles": ("Check STL triangle count",
                            lambda v, a: v.check_stl_triangle_count(a[0], int(a[1]))),
    "check-stl-min-triangles": ("Check STL has >= N triangles",
                                lambda v, a: v.check_stl_min_triangles(a[0], int(a[1]))),
    "check-step-valid": ("Check STEP file is valid",
                         lambda v, a: v.check_step_valid(a[0])),
    "check-obj-min-vertices": ("Check OBJ has >= N vertices",
                               lambda v, a: v.check_obj_min_vertices(a[0], int(a[1]))),
    "check-has-thumbnail": ("Check FCStd has a thumbnail",
                            lambda v, a: v.check_has_thumbnail(a[0])),
}


def _print_usage():
    print("FreeCAD Verifier — inspect .FCStd files and FreeCAD state")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    mx = max(len(n) for n in COMMANDS)
    for n, (d, _) in COMMANDS.items():
        print(f"  {n:<{mx + 2}} {d}")
    print("\nAll .FCStd parsing is done via stdlib zipfile + xml.etree,"
          " no freecadcmd required.")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}"}))
        sys.exit(1)

    v = FreeCADVerifier()
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
