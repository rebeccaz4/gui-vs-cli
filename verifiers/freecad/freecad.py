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

import zlib
import base64
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
# CADWorld rule checker (vendored from https://github.com/Zdong104/CADWORLD,
# Apache-2.0). Added for the task-replacement update; see update/README.md.
# Two FreeCAD 0.19 compatibility fixes are applied in the embedded sources
# (marked "[GUI_synth port]").
# ---------------------------------------------------------------------------

_CADWORLD_SOURCES = {'metric_freecad_cam': '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', 'metric_freecad': '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', 'metric_freecad_part': 'eNqdkMGKwjAQhu95iqGnXen6AD0Iwj6Ad5GSJhMNJpkyma707TdalbUUhJ1DDv/8/PP9cUwRZOx9OoKPPbHANo01fHsjSrnr1mh7IQ62jSjsTesYsWgPuzmhOT/ENpLFUC+JrUXRPqBVSll0M0uvWSbfB2MegjQTBw8Bc3PD2Wfh+qoealitqBdPKX/C1wZcIC2NgjJVVe1KFHSYzClqPkM2xMhAP+UpDbTVooFRBk5ooRvhiDIj9cnRuiTdEifrUqM76R3yL9Sbis+v+EfX123zBnF+aYn1F4fztgU=', 'metric_freecad_cloudpoint': 'eNqdkEFqwzAQRfc6xeBVGtwcwItCaW9RilE0o0RE0pjRuMW3rxInoTWGls5Ciz+fP+/LCyfQaQj5ACENLArPeWrhNTg1xp+3zuInS8Q+kUpwvReiqt3s7kjudBP7xEixXRN7JLUhEhpjkPzC4iKPOHDIOrs3QmWM2s00MkYq3QXqrai0Z/W9he2WBw2cywM8PoGPbLUzUKdpmpd7IOwpu2OycoLiWEiAP+pT21i0akFIR8mEsJ/gQLqgDtnzruZdcmfrWrsr7xX1O9qf6t4/5x+9f267X0CXl9aIvwAJ9b2j', 'metric_freecad_macro': 'eNqdkMGKwjAQhu95iqEnV7o+QA/Cwl59ApESk4kGk0yZTFf69qZWZbcUhJ1DDv/8/PP9cUwRZOh8OoGPHbHAVxpq+PZGlHLj1mh7JQ62jSjsTesYsWhPuzmjuTzFNpLFUC+JrUXRPqBVSll0c4s2TJNxxZj7IM0Ewn3A3Nx59lm4HtVDDes1deIp5Q/43IILpKVRUKaqqt2YBUdM5hw1XyAbYmSgn/KUDtpq0cAoPSe0cBzghDJj9cnRpkTdIyfrUqcH6oPyN9W7kq/f+Efbv9vmDeP80hLsDbDjtxY=', 'metric_freecad_mesh': 'eNqdkMGKwjAQhu95iqEnV7o+QA/Cwl59ApESk4kNJpkyma707Y1WZbcUhJ1DDv/8/PP9cUwRZOx9OoGPPbHAVxpr+PZGlHK3rdH2QhxsG1HYm9YxYtGedtOhOT/FNpLFUC+JrUXRPqBVSll0cwvmbvKtGPMQpJk4eAiYmzvOPgvXN/VQw3pNvXhK+QM+t+ACaWkUlKmqalei4IjJdFHzGbIhRgb6KU9poK0WDYwycEILxxFOKDNSnxxtStI9cbIuNXqQPiB/Q72p+PqKf3T9u23eIM4vLbFeAWevtec=', 'metric_freecad_techdraw': 'eNqdkEFqwzAQRfc6xeBVEtwcwItAIUforgSjSKNYRNKY0bjBt68SJyUxhpbOQos/nz/vyzFFkLH36QQ+9sQC72msYe+NKOWuW6PthTjYNqKwN61jxKI97KZDc36IbSSLoV4SW4uifUCrlLLoZhZB01nWl8m7YsxDkGZi4SFgbm5In1m4vqqHGjYb6sVTymt424ELpKVRUKaqqo8Sty9xcMRkuqj5DNkQIwN9lac00VaLBkYZOKGF4wgnlBmxT462Je2WOlmXmt1p76DPYH+o+vMt/+j8um1+wZxfWuL9BrR2urY=', 'metric_freecad_sketch': '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', 'getter_freecad_model': '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', 'getter_freecad_sketch': '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'}
_CADWORLD_ORDER = ['metric_freecad_cam', 'metric_freecad', 'metric_freecad_part', 'metric_freecad_cloudpoint', 'metric_freecad_macro', 'metric_freecad_mesh', 'metric_freecad_techdraw', 'metric_freecad_sketch', 'getter_freecad_model', 'getter_freecad_sketch']
_CADWORLD_LOADED = {}


def _cadworld_load():
    import types as _types
    if _CADWORLD_LOADED:
        return _CADWORLD_LOADED
    for name in _CADWORLD_ORDER:
        code = zlib.decompress(base64.b64decode(_CADWORLD_SOURCES[name])).decode("utf-8")
        mod = _types.ModuleType("cadworld_" + name)
        mod.__file__ = os.path.abspath(__file__)  # some modules resolve helper paths from __file__
        sys.modules["cadworld_" + name] = mod
        exec(compile(code, "cadworld_" + name, "exec"), mod.__dict__)
        _CADWORLD_LOADED[name] = mod
    return _CADWORLD_LOADED


_CADWORLD_METRIC_MODULE = {
    "check_freecad_part_model": "metric_freecad_part",
    "check_freecad_cloudpoint_model": "metric_freecad_cloudpoint",
    "check_freecad_macro_model": "metric_freecad_macro",
    "check_freecad_mesh_model": "metric_freecad_mesh",
    "check_freecad_techdraw_model": "metric_freecad_techdraw",
    "check_freecad_sketch": "metric_freecad_sketch",
}

_CADWORLD_SKETCH_FLAGS = ("entity_match_found", "all_relations_passed", "profile_ok",
                          "extra_geometry_ok", "fully_constrained_ok", "solver_status_ok",
                          "units_ok")


def cadworld_check(fcstd, payload_b64):
    spec = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
    func, rtype, rules = spec["func"], spec["result_type"], spec.get("rules", {})
    mods = _cadworld_load()
    if not os.path.exists(fcstd):
        parsed = {"exists": False}
    elif rtype == "freecad_model_info":
        parsed = mods["getter_freecad_model"].parse_part_fcstd(fcstd)
    elif rtype == "freecad_sketch_info":
        parsed = dict(mods["getter_freecad_sketch"].parse_fcstd(fcstd), exists=True)
    else:
        return {"passed": False, "error": "unsupported result type " + str(rtype)}
    mod = mods[_CADWORLD_METRIC_MODULE[func]]
    detail = getattr(mod, func + "_detailed")(parsed, rules)
    score = float(detail.get("score", 0.0))
    if func == "check_freecad_sketch":
        checks = {k: bool(detail.get(k)) for k in _CADWORLD_SKETCH_FLAGS if k in detail}
        checks["exists"] = bool(parsed.get("exists"))
    else:
        checks = {k: bool(v) for k, v in (detail.get("checks") or {}).items()}
    return {"passed": score >= 1.0, "score": score, "checks": checks,
             "reason": detail.get("reason") or detail.get("error")}


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------

COMMANDS = {
    "cadworld-check": ("Check an FCStd against CADWorld task rules (base64 JSON payload)",
                       lambda v, a: cadworld_check(a[0], a[1])),
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
