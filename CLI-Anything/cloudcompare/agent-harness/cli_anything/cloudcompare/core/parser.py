"""File parsing module for CloudCompare CLI harness.

Provides PLY, OBJ, and ASCII point cloud/mesh parsing capabilities.
This allows agents to inspect files without using the verifier.
"""

from __future__ import annotations

import os
import re
import struct
from pathlib import Path
from typing import Any


# ── Constants ───────────────────────────────────────────────────────────────

ASCII_EXTS = {".xyz", ".asc", ".txt", ".pts", ".csv"}

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


# ── PLY Parsing ───────────────────────────────────────────────────────────────

def _parse_ply_header(fh) -> dict:
    """Parse a PLY header from a binary file handle.

    Returns a dict containing format, elements list (each with name, count,
    properties), and the byte offset where the body begins.
    """
    line = fh.readline()
    if not line.startswith(b"ply"):
        return {"error": "Not a PLY file (magic missing)"}

    fmt = None
    elements: list[dict] = []
    current = None

    while True:
        line = fh.readline()
        if not line:
            return {"error": "Unexpected EOF in PLY header"}
        try:
            text = line.decode("ascii", errors="replace").strip()
        except Exception:
            return {"error": "Invalid PLY header encoding"}

        if text == "end_header":
            break
        if text.startswith("comment") or text.startswith("obj_info"):
            continue
        if text.startswith("format"):
            parts = text.split()
            if len(parts) >= 2:
                fmt = parts[1]
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
    """Parse a PLY file and extract metadata."""
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

            # Bounding box
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
                "bbox": bbox,
                "elements": [
                    {"name": e["name"], "count": e["count"], "property_count": len(e["properties"])}
                    for e in header["elements"]
                ],
            }
    except OSError as e:
        return {"error": f"Cannot read file: {e}"}


def _ply_bbox(fh, header: dict, vert_elem: dict) -> list[list[float]] | None:
    """Compute bounding box from PLY vertex data."""
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
            min_xyz[0] = min(min_xyz[0], x)
            min_xyz[1] = min(min_xyz[1], y)
            min_xyz[2] = min(min_xyz[2], z)
            max_xyz[0] = max(max_xyz[0], x)
            max_xyz[1] = max(max_xyz[1], y)
            max_xyz[2] = max(max_xyz[2], z)
            read += 1
        if read == 0:
            return None
        return [min_xyz, max_xyz]

    # Binary
    endian = "<" if fmt == "binary_little_endian" else ">"
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
            min_xyz[0] = min(min_xyz[0], x)
            min_xyz[1] = min(min_xyz[1], y)
            min_xyz[2] = min(min_xyz[2], z)
            max_xyz[0] = max(max_xyz[0], x)
            max_xyz[1] = max(max_xyz[1], y)
            max_xyz[2] = max(max_xyz[2], z)
        return [min_xyz, max_xyz]

    # Generic path with list properties
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
                fh.read(item_size * n)
                row_vals.append(0.0)
            else:
                c = _PLY_STRUCT_CODES[p["type"]]
                s = struct.calcsize(endian + c)
                data = fh.read(s)
                if len(data) < s:
                    return [min_xyz, max_xyz]
                row_vals.append(struct.unpack(endian + c, data)[0])
        x, y, z = row_vals[idx_x], row_vals[idx_y], row_vals[idx_z]
        min_xyz[0] = min(min_xyz[0], x)
        min_xyz[1] = min(min_xyz[1], y)
        min_xyz[2] = min(min_xyz[2], z)
        max_xyz[0] = max(max_xyz[0], x)
        max_xyz[1] = max(max_xyz[1], y)
        max_xyz[2] = max(max_xyz[2], z)
    return [min_xyz, max_xyz]


# ── OBJ Parsing ───────────────────────────────────────────────────────────────

def _parse_obj(path: str) -> dict:
    """Parse an OBJ file and extract metadata."""
    v = 0
    faces = 0
    min_xyz = [float("inf")] * 3
    max_xyz = [float("-inf")] * 3
    has_normals = False
    has_texcoords = False

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
                        min_xyz[0] = min(min_xyz[0], x)
                        min_xyz[1] = min(min_xyz[1], y)
                        min_xyz[2] = min(min_xyz[2], z)
                        max_xyz[0] = max(max_xyz[0], x)
                        max_xyz[1] = max(max_xyz[1], y)
                        max_xyz[2] = max(max_xyz[2], z)
                elif line.startswith("vn "):
                    has_normals = True
                elif line.startswith("vt "):
                    has_texcoords = True
                elif line.startswith("f "):
                    faces += 1
    except OSError as e:
        return {"error": f"Cannot read file: {e}"}

    bbox = [min_xyz, max_xyz] if v > 0 else None
    return {
        "format": "obj",
        "vertex_count": v,
        "face_count": faces,
        "bbox": bbox,
        "has_normals": has_normals,
        "has_texcoords": has_texcoords,
        "has_color": False,
        "has_intensity": False,
    }


# ── ASCII Parsing ─────────────────────────────────────────────────────────────

def _parse_ascii_cloud(path: str) -> dict:
    """Parse an ASCII point cloud file."""
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
                min_xyz[0] = min(min_xyz[0], x)
                min_xyz[1] = min(min_xyz[1], y)
                min_xyz[2] = min(min_xyz[2], z)
                max_xyz[0] = max(max_xyz[0], x)
                max_xyz[1] = max(max_xyz[1], y)
                max_xyz[2] = max(max_xyz[2], z)
                points += 1
    except OSError as e:
        return {"error": f"Cannot read file: {e}"}

    if points == 0:
        return {
            "format": "ascii",
            "points": 0,
            "vertex_count": 0,
            "columns": ncols or 0,
            "bbox": None,
            "has_color": False,
            "has_intensity": False,
            "skipped_lines": skipped,
        }

    has_color = ncols in (6, 7, 9)
    has_intensity = ncols in (4, 7)
    bbox = [min_xyz, max_xyz]

    return {
        "format": "ascii",
        "points": points,
        "vertex_count": points,
        "columns": ncols or 0,
        "bbox": bbox,
        "has_color": has_color,
        "has_intensity": has_intensity,
        "has_normals": False,
        "skipped_lines": skipped,
    }


# ── Format Detection ──────────────────────────────────────────────────────────

def detect_format(path: str) -> str:
    """Detect file format from extension."""
    ext = Path(path).suffix.lower()
    if ext == ".ply":
        return "ply"
    if ext == ".obj":
        return "obj"
    if ext in ASCII_EXTS:
        return "ascii"
    return "unknown"


def sniff_format(path: str) -> str:
    """Detect the file's actual format by inspecting its bytes."""
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


# ── Public API ───────────────────────────────────────────────────────────────

def parse_cloud(path: str) -> dict:
    """Parse a point cloud or mesh file (PLY/OBJ/ASCII).

    This is the main entry point for agents to inspect files.

    Args:
        path: Path to the file.

    Returns:
        dict with keys:
            - format: str ("ply", "obj", "ascii")
            - vertex_count: int (or "points" for ASCII)
            - face_count: int (0 for clouds)
            - has_color: bool
            - has_intensity: bool
            - has_normals: bool
            - has_texcoords: bool (OBJ only)
            - has_alpha: bool (PLY only)
            - bbox: [[xmin, ymin, zmin], [xmax, ymax, zmax]] or None
            - properties: list[str] (PLY only)
            - columns: int (ASCII only)
            - error: str (if error occurred)

    Example:
        >>> info = parse_cloud("scan.ply")
        >>> print(f"Points: {info['vertex_count']}")
        >>> print(f"Has color: {info['has_color']}")
        >>> print(f"BBox: {info['bbox']}")
    """
    if not os.path.exists(path):
        return {"error": f"File not found: {path}"}

    fmt = detect_format(path)
    if fmt == "ply":
        return _parse_ply(path)
    if fmt == "obj":
        return _parse_obj(path)
    if fmt == "ascii":
        return _parse_ascii_cloud(path)
    return {"error": f"Unsupported format for {path}"}


def parse_ply_header(path: str) -> dict:
    """Parse only the PLY file header (faster for large files).

    Args:
        path: Path to the PLY file.

    Returns:
        dict with keys:
            - format: str ("ascii", "binary_little_endian", "binary_big_endian")
            - elements: list[dict] with keys:
                - name: str ("vertex", "face", etc.)
                - count: int
                - properties: list[dict] with keys:
                    - name: str
                    - type: str
            - error: str (if error occurred)

    Example:
        >>> header = parse_ply_header("scan.ply")
        >>> for elem in header["elements"]:
        ...     print(f"{elem['name']}: {elem['count']}")
    """
    if not os.path.exists(path):
        return {"error": f"File not found: {path}"}

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
        return {"error": f"Cannot read file: {e}"}


def get_format(path: str) -> dict:
    """Get the actual file format by inspecting content (not just extension).

    Args:
        path: Path to the file.

    Returns:
        dict with keys:
            - format: str ("ply", "obj", "ascii", "unknown")
            - extension: str (the file extension)
            - match: bool (extension matches content)
            - error: str (if error occurred)

    Example:
        >>> result = get_format("data.bin")
        >>> print(f"Actual format: {result['format']}")
    """
    if not os.path.exists(path):
        return {"error": f"File not found: {path}"}

    ext_fmt = detect_format(path)
    sniffed = sniff_format(path)

    return {
        "format": sniffed,
        "extension": ext_fmt,
        "match": ext_fmt == sniffed,
    }
