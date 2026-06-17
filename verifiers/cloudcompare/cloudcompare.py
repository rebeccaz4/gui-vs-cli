"""
CloudCompare Verifier — file-based inspection for point clouds / meshes used
with CloudCompare in an E2B sandbox.

Verification channels:
  - ASCII point cloud parsing (.xyz / .asc / .txt): counts, bounding box,
    channel detection (intensity / RGB color).
  - PLY parsing (.ply, ASCII or binary): header parse (stdlib only) for
    element counts, properties, bounding box (reads vertex element via
    struct for binary, text for ASCII).
  - OBJ parsing (.obj): counts vertices / faces, basic bounding box.
  - CloudCompare INI parsing (~/.config/CCorp/CloudCompare.conf): reads
    settings, recent files.
  - File existence/size checks for exports.

CloudCompare cannot be driven programmatically in the same rich way Blender's
`bpy` provides, so this verifier is deliberately thinner than the Blender or
Krita verifiers. Deliberately skipped categories are listed in README.md.

Usage from outside the sandbox:
    sandbox.commands.run(
        "python3 /home/user/verifiers/cloudcompare.py "
        "cloud-info /home/user/Documents/scan.ply"
    )
"""

from __future__ import annotations

import configparser
import json
import os
import re
import struct
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _err(msg: str) -> dict:
    return {"error": msg}


def _ensure_exists(path: str) -> dict | None:
    if not os.path.exists(path):
        return _err(f"File not found: {path}")
    return None


def _round_bbox(bbox: list[list[float]] | None) -> list[list[float]] | None:
    if not bbox:
        return bbox
    return [[round(float(v), 6) for v in p] for p in bbox]


# ---------------------------------------------------------------------------
# ASCII XYZ / ASC / TXT parsing
# ---------------------------------------------------------------------------

ASCII_EXTS = {".xyz", ".asc", ".txt", ".pts", ".csv"}


def _parse_ascii_cloud(path: str) -> dict:
    """Parse an ASCII point cloud.

    Accepts lines of whitespace- or comma-separated numbers, optionally with
    a leading comment line that starts with #. Column count decides channels:
      3 -> XYZ
      4 -> XYZ + intensity (or scalar)
      6 -> XYZ + RGB
      7 -> XYZ + intensity + RGB (or RGBI)
    Lines that fail to parse are skipped.
    """
    points = 0
    min_xyz = [float("inf")] * 3
    max_xyz = [float("-inf")] * 3
    ncols = None
    skipped = 0

    try:
        with open(path, "r", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or line.startswith("//"):
                    continue
                # Allow commas or whitespace as separators
                parts = re.split(r"[,\s]+", line)
                parts = [p for p in parts if p != ""]
                try:
                    nums = [float(p) for p in parts]
                except ValueError:
                    skipped += 1
                    continue
                if len(nums) < 3:
                    skipped += 1
                    continue
                if ncols is None:
                    ncols = len(nums)
                x, y, z = nums[0], nums[1], nums[2]
                if x < min_xyz[0]:
                    min_xyz[0] = x
                if y < min_xyz[1]:
                    min_xyz[1] = y
                if z < min_xyz[2]:
                    min_xyz[2] = z
                if x > max_xyz[0]:
                    max_xyz[0] = x
                if y > max_xyz[1]:
                    max_xyz[1] = y
                if z > max_xyz[2]:
                    max_xyz[2] = z
                points += 1
    except OSError as e:
        return _err(f"Cannot read file: {e}")

    if points == 0:
        return {
            "format": "ascii",
            "points": 0,
            "columns": ncols or 0,
            "bbox": None,
            "has_color": False,
            "has_intensity": False,
            "skipped_lines": skipped,
        }

    has_color = ncols in (6, 7, 9)
    has_intensity = ncols in (4, 7)
    return {
        "format": "ascii",
        "points": points,
        "columns": ncols or 0,
        "bbox": _round_bbox([min_xyz, max_xyz]),
        "has_color": has_color,
        "has_intensity": has_intensity,
        "skipped_lines": skipped,
    }


# ---------------------------------------------------------------------------
# PLY parsing (ASCII + binary)
# ---------------------------------------------------------------------------

_PLY_TYPE_SIZES = {
    "char": 1, "int8": 1,
    "uchar": 1, "uint8": 1,
    "short": 2, "int16": 2,
    "ushort": 2, "uint16": 2,
    "int": 4, "int32": 4,
    "uint": 4, "uint32": 4,
    "float": 4, "float32": 4,
    "double": 8, "float64": 8,
}

_PLY_STRUCT_CODES = {
    "char": "b", "int8": "b",
    "uchar": "B", "uint8": "B",
    "short": "h", "int16": "h",
    "ushort": "H", "uint16": "H",
    "int": "i", "int32": "i",
    "uint": "I", "uint32": "I",
    "float": "f", "float32": "f",
    "double": "d", "float64": "d",
}


def _parse_ply_header(fh) -> dict:
    """Parse a PLY header from a binary file handle.

    Returns a dict containing format, elements list (each with name, count,
    properties), and the byte offset where the body begins.
    """
    line = fh.readline()
    if not line.startswith(b"ply"):
        return _err("Not a PLY file (magic missing)")

    fmt = None
    elements: list[dict] = []
    current = None

    while True:
        line = fh.readline()
        if not line:
            return _err("Unexpected EOF in PLY header")
        try:
            text = line.decode("ascii", errors="replace").strip()
        except Exception:
            return _err("Invalid PLY header encoding")

        if text == "end_header":
            break
        if text.startswith("comment") or text.startswith("obj_info"):
            continue
        if text.startswith("format"):
            parts = text.split()
            if len(parts) >= 2:
                fmt = parts[1]  # ascii / binary_little_endian / binary_big_endian
            continue
        if text.startswith("element"):
            parts = text.split()
            if len(parts) >= 3:
                if current is not None:
                    elements.append(current)
                current = {
                    "name": parts[1],
                    "count": int(parts[2]),
                    "properties": [],
                }
            continue
        if text.startswith("property"):
            parts = text.split()
            if current is None:
                continue
            if len(parts) >= 3 and parts[1] == "list":
                # property list count_type item_type name
                if len(parts) >= 5:
                    current["properties"].append({
                        "name": parts[4],
                        "type": "list",
                        "count_type": parts[2],
                        "item_type": parts[3],
                    })
            elif len(parts) >= 3:
                current["properties"].append({
                    "name": parts[2],
                    "type": parts[1],
                })
            continue

    if current is not None:
        elements.append(current)

    return {
        "format": fmt or "ascii",
        "elements": elements,
        "body_offset": fh.tell(),
    }


def _parse_ply(path: str) -> dict:
    try:
        with open(path, "rb") as fh:
            header = _parse_ply_header(fh)
            if "error" in header:
                return header

            vert_elem = next((e for e in header["elements"] if e["name"] == "vertex"), None)
            face_elem = next((e for e in header["elements"] if e["name"] == "face"), None)

            vertex_count = vert_elem["count"] if vert_elem else 0
            face_count = face_elem["count"] if face_elem else 0

            # Property flags
            prop_names = [p["name"] for p in (vert_elem["properties"] if vert_elem else [])]
            has_color = any(n in prop_names for n in ("red", "green", "blue"))
            has_alpha = "alpha" in prop_names
            has_normal = any(n in prop_names for n in ("nx", "ny", "nz"))
            has_intensity = "intensity" in prop_names or "scalar_Intensity" in prop_names

            # Bounding box: only compute for the vertex element
            bbox = None
            if vert_elem and vertex_count > 0:
                bbox = _ply_bbox(fh, header, vert_elem)

            return {
                "format": header["format"],
                "vertex_count": vertex_count,
                "face_count": face_count,
                "has_color": has_color,
                "has_alpha": has_alpha,
                "has_normal": has_normal,
                "has_intensity": has_intensity,
                "properties": prop_names,
                "bbox": _round_bbox(bbox),
                "elements": [
                    {"name": e["name"], "count": e["count"], "property_count": len(e["properties"])}
                    for e in header["elements"]
                ],
            }
    except OSError as e:
        return _err(f"Cannot read file: {e}")


def _ply_bbox(fh, header: dict, vert_elem: dict) -> list[list[float]] | None:
    fmt = header["format"]
    props = vert_elem["properties"]
    count = vert_elem["count"]

    # Find x/y/z property indices
    idx_x = idx_y = idx_z = None
    for i, p in enumerate(props):
        if p.get("type") == "list":
            continue
        if p["name"] == "x":
            idx_x = i
        elif p["name"] == "y":
            idx_y = i
        elif p["name"] == "z":
            idx_z = i
    if idx_x is None or idx_y is None or idx_z is None:
        return None

    min_xyz = [float("inf")] * 3
    max_xyz = [float("-inf")] * 3

    if fmt == "ascii":
        # Re-open to read as text at body offset
        fh.seek(header["body_offset"])
        read = 0
        for raw in fh:
            if read >= count:
                break
            try:
                text = raw.decode("ascii", errors="replace").strip()
            except Exception:
                continue
            if not text:
                continue
            parts = text.split()
            if len(parts) <= max(idx_x, idx_y, idx_z):
                continue
            try:
                x = float(parts[idx_x])
                y = float(parts[idx_y])
                z = float(parts[idx_z])
            except ValueError:
                continue
            if x < min_xyz[0]:
                min_xyz[0] = x
            if y < min_xyz[1]:
                min_xyz[1] = y
            if z < min_xyz[2]:
                min_xyz[2] = z
            if x > max_xyz[0]:
                max_xyz[0] = x
            if y > max_xyz[1]:
                max_xyz[1] = y
            if z > max_xyz[2]:
                max_xyz[2] = z
            read += 1
        if read == 0:
            return None
        return [min_xyz, max_xyz]

    # Binary
    endian = "<" if fmt == "binary_little_endian" else ">"
    # Build the struct format for one vertex
    fh.seek(header["body_offset"])
    # Fast path: all scalar (no list). Build a format string.
    scalar_only = all(p.get("type") != "list" for p in props)
    if scalar_only:
        code = endian + "".join(_PLY_STRUCT_CODES.get(p["type"], "f") for p in props)
        row_size = struct.calcsize(code)
        for _ in range(count):
            data = fh.read(row_size)
            if len(data) < row_size:
                break
            vals = struct.unpack(code, data)
            x, y, z = vals[idx_x], vals[idx_y], vals[idx_z]
            if x < min_xyz[0]:
                min_xyz[0] = x
            if y < min_xyz[1]:
                min_xyz[1] = y
            if z < min_xyz[2]:
                min_xyz[2] = z
            if x > max_xyz[0]:
                max_xyz[0] = x
            if y > max_xyz[1]:
                max_xyz[1] = y
            if z > max_xyz[2]:
                max_xyz[2] = z
        return [min_xyz, max_xyz]

    # Generic path: parse each property (handle lists)
    for _ in range(count):
        row_vals: list[float] = []
        for p in props:
            if p.get("type") == "list":
                ct = _PLY_STRUCT_CODES[p["count_type"]]
                cs = struct.calcsize(endian + ct)
                cnt_bytes = fh.read(cs)
                if len(cnt_bytes) < cs:
                    return [min_xyz, max_xyz]
                n = struct.unpack(endian + ct, cnt_bytes)[0]
                it = _PLY_STRUCT_CODES[p["item_type"]]
                item_size = struct.calcsize(endian + it)
                fh.read(item_size * n)  # discard list values for bbox
                row_vals.append(0.0)
            else:
                c = _PLY_STRUCT_CODES[p["type"]]
                s = struct.calcsize(endian + c)
                data = fh.read(s)
                if len(data) < s:
                    return [min_xyz, max_xyz]
                row_vals.append(struct.unpack(endian + c, data)[0])
        x, y, z = row_vals[idx_x], row_vals[idx_y], row_vals[idx_z]
        if x < min_xyz[0]:
            min_xyz[0] = x
        if y < min_xyz[1]:
            min_xyz[1] = y
        if z < min_xyz[2]:
            min_xyz[2] = z
        if x > max_xyz[0]:
            max_xyz[0] = x
        if y > max_xyz[1]:
            max_xyz[1] = y
        if z > max_xyz[2]:
            max_xyz[2] = z
    return [min_xyz, max_xyz]


# ---------------------------------------------------------------------------
# OBJ parsing
# ---------------------------------------------------------------------------


def _parse_obj(path: str) -> dict:
    v = 0
    vn = 0
    vt = 0
    faces = 0
    min_xyz = [float("inf")] * 3
    max_xyz = [float("-inf")] * 3
    try:
        with open(path, "r", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("v "):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            x = float(parts[1])
                            y = float(parts[2])
                            z = float(parts[3])
                        except ValueError:
                            continue
                        v += 1
                        if x < min_xyz[0]:
                            min_xyz[0] = x
                        if y < min_xyz[1]:
                            min_xyz[1] = y
                        if z < min_xyz[2]:
                            min_xyz[2] = z
                        if x > max_xyz[0]:
                            max_xyz[0] = x
                        if y > max_xyz[1]:
                            max_xyz[1] = y
                        if z > max_xyz[2]:
                            max_xyz[2] = z
                elif line.startswith("vn "):
                    vn += 1
                elif line.startswith("vt "):
                    vt += 1
                elif line.startswith("f "):
                    faces += 1
    except OSError as e:
        return _err(f"Cannot read file: {e}")

    bbox = [min_xyz, max_xyz] if v > 0 else None
    return {
        "format": "obj",
        "vertex_count": v,
        "normal_count": vn,
        "texcoord_count": vt,
        "face_count": faces,
        "bbox": _round_bbox(bbox),
        "has_normals": vn > 0,
        "has_texcoords": vt > 0,
    }


# ---------------------------------------------------------------------------
# Generic cloud dispatch
# ---------------------------------------------------------------------------


def _detect_format(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".ply":
        return "ply"
    if ext == ".obj":
        return "obj"
    if ext in ASCII_EXTS:
        return "ascii"
    return "unknown"


def _sniff_format(path: str) -> str:
    """Detect the file's actual format by inspecting its bytes.

    Returns one of "ply", "obj", "ascii", or "unknown". Requires the file
    to exist; callers should pre-check with `_ensure_exists`.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        return "unknown"

    if head.startswith(b"ply\n") or head.startswith(b"ply\r"):
        return "ply"

    try:
        text = head.decode("ascii", errors="replace")
    except Exception:
        return "unknown"

    stripped = [ln.strip() for ln in text.splitlines()]
    stripped = [ln for ln in stripped if ln and not ln.startswith("#") and not ln.startswith("//")]
    if not stripped:
        return "unknown"

    obj_tokens = ("v ", "vn ", "vt ", "vp ", "f ", "l ", "o ", "g ", "s ", "mtllib ", "usemtl ")
    if any(ln.startswith(obj_tokens) for ln in stripped):
        return "obj"

    numeric_lines = 0
    for ln in stripped[:20]:
        parts = [p for p in re.split(r"[,\s]+", ln) if p]
        if len(parts) < 3:
            continue
        try:
            [float(p) for p in parts[:3]]
            numeric_lines += 1
        except ValueError:
            continue
    if numeric_lines >= 1:
        return "ascii"

    return "unknown"


def _parse_any(path: str) -> dict:
    err = _ensure_exists(path)
    if err:
        return err
    fmt = _detect_format(path)
    if fmt == "ply":
        return _parse_ply(path)
    if fmt == "obj":
        return _parse_obj(path)
    if fmt == "ascii":
        return _parse_ascii_cloud(path)
    return _err(f"Unsupported format for {path}")


# ---------------------------------------------------------------------------
# INI config parsing
# ---------------------------------------------------------------------------

DEFAULT_CONF = os.path.expanduser("~/.config/CCorp/CloudCompare.conf")


def _read_conf(conf_path: str | None = None) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False)
    cp.optionxform = str  # preserve case
    path = conf_path or DEFAULT_CONF
    if os.path.exists(path):
        try:
            cp.read(path)
        except configparser.Error:
            pass
    return cp


# ---------------------------------------------------------------------------
# CloudCompareVerifier class
# ---------------------------------------------------------------------------


class CloudCompareVerifier:
    """Stateless verifier for CloudCompare files and config."""

    # ---- File I/O ----

    def check_file_exists(self, path: str) -> dict:
        p = Path(path)
        if p.exists():
            return {"exists": True, "path": str(p), "size": p.stat().st_size}
        return {"exists": False, "path": str(p)}

    def check_file_size(self, path: str, min_bytes: int) -> dict:
        if not os.path.exists(path):
            return {"match": False, "error": "File not found"}
        size = os.path.getsize(path)
        return {"match": size >= int(min_bytes), "size": size, "min_bytes": int(min_bytes)}

    # ---- Cloud / mesh inspection ----

    def cloud_info(self, path: str) -> dict:
        return _parse_any(path)

    def ply_header(self, path: str) -> dict:
        err = _ensure_exists(path)
        if err:
            return err
        try:
            with open(path, "rb") as fh:
                h = _parse_ply_header(fh)
                if "error" in h:
                    return h
                return {
                    "format": h["format"],
                    "elements": [
                        {
                            "name": e["name"],
                            "count": e["count"],
                            "properties": e["properties"],
                        }
                        for e in h["elements"]
                    ],
                }
        except OSError as e:
            return _err(f"Cannot read file: {e}")

    # ---- Point count checks ----

    def check_point_count(self, path: str, expected: int) -> dict:
        info = _parse_any(path)
        if "error" in info:
            return {"match": False, **info}
        actual = info.get("vertex_count", info.get("points", 0))
        expected = int(expected)
        return {"match": actual == expected, "expected": expected, "actual": actual}

    def check_point_count_at_least(self, path: str, minimum: int) -> dict:
        info = _parse_any(path)
        if "error" in info:
            return {"match": False, **info}
        actual = info.get("vertex_count", info.get("points", 0))
        minimum = int(minimum)
        return {"match": actual >= minimum, "minimum": minimum, "actual": actual}

    def check_face_count(self, path: str, expected: int) -> dict:
        info = _parse_any(path)
        if "error" in info:
            return {"match": False, **info}
        actual = info.get("face_count", 0)
        expected = int(expected)
        return {"match": actual == expected, "expected": expected, "actual": actual}

    # ---- Bounding box checks ----

    def check_bbox_within(
        self,
        path: str,
        xmin: float,
        ymin: float,
        zmin: float,
        xmax: float,
        ymax: float,
        zmax: float,
    ) -> dict:
        """Return match=True iff the file's bbox is contained in the given box."""
        info = _parse_any(path)
        if "error" in info:
            return {"match": False, **info}
        bbox = info.get("bbox")
        if not bbox:
            return {"match": False, "error": "No bbox available"}
        (lo, hi) = bbox
        eps = 1e-6
        ok = (
            lo[0] >= float(xmin) - eps and lo[1] >= float(ymin) - eps and lo[2] >= float(zmin) - eps
            and hi[0] <= float(xmax) + eps and hi[1] <= float(ymax) + eps and hi[2] <= float(zmax) + eps
        )
        return {
            "match": ok,
            "bbox": bbox,
            "expected_within": [[float(xmin), float(ymin), float(zmin)],
                                [float(xmax), float(ymax), float(zmax)]],
        }

    def check_bbox_min_extent(self, path: str, axis: str, min_extent: float) -> dict:
        """Check that max-min along an axis is >= min_extent."""
        info = _parse_any(path)
        if "error" in info:
            return {"match": False, **info}
        bbox = info.get("bbox")
        if not bbox:
            return {"match": False, "error": "No bbox available"}
        idx = {"x": 0, "y": 1, "z": 2}.get(axis.lower())
        if idx is None:
            return {"match": False, "error": f"Invalid axis: {axis}"}
        extent = bbox[1][idx] - bbox[0][idx]
        return {
            "match": extent >= float(min_extent),
            "axis": axis.lower(),
            "extent": round(extent, 6),
            "min_extent": float(min_extent),
        }

    # ---- Channel / format checks ----

    def check_has_color(self, path: str) -> dict:
        info = _parse_any(path)
        if "error" in info:
            return {"has_color": False, **info}
        return {"has_color": bool(info.get("has_color"))}

    def check_has_intensity(self, path: str) -> dict:
        info = _parse_any(path)
        if "error" in info:
            return {"has_intensity": False, **info}
        return {"has_intensity": bool(info.get("has_intensity"))}

    def check_has_normals(self, path: str) -> dict:
        info = _parse_any(path)
        if "error" in info:
            return {"has_normals": False, **info}
        has = bool(info.get("has_normal") or info.get("has_normals"))
        return {"has_normals": has}

    def check_ply_format(self, path: str, expected: str) -> dict:
        """expected one of: ascii, binary_little_endian, binary_big_endian."""
        info = _parse_ply(path) if _detect_format(path) == "ply" else _err("not a PLY")
        if "error" in info:
            return {"match": False, **info}
        actual = info.get("format")
        return {"match": actual == expected, "expected": expected, "actual": actual}

    def check_format(self, path: str, expected: str) -> dict:
        """Check that the file's actual format matches `expected`.

        expected: one of ply, obj, ascii

        Requires the file to exist and inspects its contents (not just the
        extension) so that a missing file or a file whose bytes don't match
        the extension fails the check.
        """
        err = _ensure_exists(path)
        if err:
            return {"match": False, "expected": expected, "actual": None, **err}
        ext_fmt = _detect_format(path)
        sniffed = _sniff_format(path)
        if sniffed == "unknown":
            return {
                "match": False,
                "expected": expected,
                "actual": "unknown",
                "extension": ext_fmt,
                "error": "File contents do not match any supported format",
            }
        return {
            "match": sniffed == expected,
            "expected": expected,
            "actual": sniffed,
            "extension": ext_fmt,
        }

    def check_is_mesh(self, path: str) -> dict:
        """Check that the file contains faces (i.e. is a mesh, not only a cloud)."""
        info = _parse_any(path)
        if "error" in info:
            return {"is_mesh": False, **info}
        faces = info.get("face_count", 0)
        return {"is_mesh": faces > 0, "face_count": faces}

    # ---- Config / preferences ----

    def settings(self, conf_path: str | None = None) -> dict:
        """Dump the CloudCompare config INI as nested sections -> key -> value."""
        path = conf_path or DEFAULT_CONF
        if not os.path.exists(path):
            return {"exists": False, "path": path, "sections": {}}
        cp = _read_conf(path)
        sections: dict[str, dict[str, str]] = {}
        for s in cp.sections():
            sections[s] = dict(cp.items(s))
        return {"exists": True, "path": path, "sections": sections}

    def check_setting(
        self,
        section: str,
        key: str,
        expected: str,
        conf_path: str | None = None,
    ) -> dict:
        path = conf_path or DEFAULT_CONF
        if not os.path.exists(path):
            return {"match": False, "error": f"Config not found: {path}"}
        cp = _read_conf(path)
        if section not in cp:
            return {"match": False, "error": f"Section not found: {section}",
                    "section": section, "key": key}
        val = cp[section].get(key)
        if val is None:
            return {"match": False, "error": f"Key not found: {key}",
                    "section": section, "key": key}
        # Strip surrounding quotes that Qt INI may add
        stripped = val.strip()
        if (stripped.startswith('"') and stripped.endswith('"')) or \
           (stripped.startswith("'") and stripped.endswith("'")):
            stripped = stripped[1:-1]
        return {
            "match": stripped == str(expected),
            "section": section,
            "key": key,
            "expected": str(expected),
            "actual": stripped,
        }

    def recent_files(self, conf_path: str | None = None) -> dict:
        """Return the list of recent files recorded in CloudCompare's config.

        CloudCompare stores these under a section like [General] with keys
        recentFile0..recentFileN or under [recentFiles]. Both are scanned.
        """
        path = conf_path or DEFAULT_CONF
        if not os.path.exists(path):
            return {"exists": False, "path": path, "files": []}
        cp = _read_conf(path)
        files: list[str] = []
        for section in cp.sections():
            for k, v in cp.items(section):
                if re.match(r"(?i)recentfile\d*$", k) or k.lower().startswith("recentfile"):
                    val = v.strip()
                    if (val.startswith('"') and val.endswith('"')) or \
                       (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    if val:
                        files.append(val)
        return {"exists": True, "path": path, "files": files, "count": len(files)}

    def check_recent_file(self, filename: str, conf_path: str | None = None) -> dict:
        data = self.recent_files(conf_path)
        if not data.get("exists"):
            return {"match": False, "error": "Config not found"}
        hit = any(filename in f for f in data.get("files", []))
        return {"match": hit, "filename": filename, "recent_files": data.get("files", [])}


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

COMMANDS: dict[str, tuple[str, callable]] = {
    # Query
    "cloud-info": ("Parse cloud/mesh file (any supported format)",
                   lambda v, a: v.cloud_info(a[0])),
    "ply-header": ("Parse PLY header", lambda v, a: v.ply_header(a[0])),
    "settings": ("Dump CloudCompare config INI",
                 lambda v, a: v.settings(a[0] if a else None)),
    "recent-files": ("List recent files from CloudCompare config",
                     lambda v, a: v.recent_files(a[0] if a else None)),

    # File
    "check-file-exists": ("Check that a file exists",
                           lambda v, a: v.check_file_exists(a[0])),
    "check-file-size": ("Check that a file is >= N bytes",
                         lambda v, a: v.check_file_size(a[0], int(a[1]))),

    # Counts
    "check-point-count": ("Check exact point/vertex count",
                           lambda v, a: v.check_point_count(a[0], int(a[1]))),
    "check-point-count-at-least": ("Check minimum point/vertex count",
                                    lambda v, a: v.check_point_count_at_least(a[0], int(a[1]))),
    "check-face-count": ("Check exact face count",
                          lambda v, a: v.check_face_count(a[0], int(a[1]))),

    # BBox
    "check-bbox-within": ("Check bbox is inside [xmin ymin zmin xmax ymax zmax]",
                           lambda v, a: v.check_bbox_within(
                               a[0], float(a[1]), float(a[2]), float(a[3]),
                               float(a[4]), float(a[5]), float(a[6]))),
    "check-bbox-min-extent": ("Check axis extent >= min",
                               lambda v, a: v.check_bbox_min_extent(a[0], a[1], float(a[2]))),

    # Channels
    "check-has-color": ("Check that cloud has color channel",
                         lambda v, a: v.check_has_color(a[0])),
    "check-has-intensity": ("Check that cloud has intensity column",
                             lambda v, a: v.check_has_intensity(a[0])),
    "check-has-normals": ("Check that cloud/mesh has normals",
                           lambda v, a: v.check_has_normals(a[0])),

    # Format
    "check-ply-format": ("Check PLY encoding (ascii / binary_little_endian / binary_big_endian)",
                          lambda v, a: v.check_ply_format(a[0], a[1])),
    "check-format": ("Check file format (ply/obj/ascii)",
                      lambda v, a: v.check_format(a[0], a[1])),
    "check-is-mesh": ("Check that file contains faces",
                       lambda v, a: v.check_is_mesh(a[0])),

    # Config
    "check-setting": ("Check config INI key value",
                       lambda v, a: v.check_setting(a[0], a[1], a[2],
                                                    a[3] if len(a) > 3 else None)),
    "check-recent-file": ("Check that a filename appears in recent files",
                           lambda v, a: v.check_recent_file(a[0],
                                                            a[1] if len(a) > 1 else None)),
}


def _print_usage():
    print("CloudCompare Verifier — inspect point clouds / meshes and CloudCompare config")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    mx = max(len(n) for n in COMMANDS)
    for n, (d, _) in COMMANDS.items():
        print(f"  {n:<{mx + 2}} {d}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}"}))
        sys.exit(1)

    v = CloudCompareVerifier()
    _, handler = COMMANDS[cmd]

    try:
        result = handler(v, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except ValueError as e:
        print(json.dumps({"error": f"Invalid argument: {e}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
