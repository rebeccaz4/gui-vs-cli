"""Statistics module for CloudCompare CLI harness.

Provides statistical calculations and property checks for point clouds and meshes.
Built on top of the parser module.
"""

import os
from typing import Any

from .parser import parse_cloud, get_format


# ── Count Functions ───────────────────────────────────────────────────────────

def get_point_count(file_path: str) -> dict:
    """Get the number of points/vertices in a file.

    Args:
        file_path: Path to the point cloud or mesh file.

    Returns:
        dict with keys:
            - count: int (number of points/vertices)
            - error: str (if error occurred)

    Example:
        >>> result = get_point_count("scan.ply")
        >>> print(f"Point count: {result['count']}")
    """
    info = parse_cloud(file_path)
    if "error" in info:
        return {"error": info["error"]}

    count = info.get("vertex_count") or info.get("points", 0)
    return {"count": count}


def get_face_count(file_path: str) -> dict:
    """Get the number of faces in a mesh file.

    Args:
        file_path: Path to the mesh file.

    Returns:
        dict with keys:
            - count: int (number of faces)
            - is_mesh: bool (whether the file contains faces)
            - error: str (if error occurred)

    Example:
        >>> result = get_face_count("mesh.obj")
        >>> print(f"Face count: {result['count']}")
        >>> print(f"Is mesh: {result['is_mesh']}")
    """
    info = parse_cloud(file_path)
    if "error" in info:
        return {"error": info["error"]}

    count = info.get("face_count", 0)
    return {
        "count": count,
        "is_mesh": count > 0,
    }


# ── Bounding Box Functions ─────────────────────────────────────────────────────

def get_bbox(file_path: str) -> dict:
    """Get the bounding box of a point cloud or mesh.

    Args:
        file_path: Path to the file.

    Returns:
        dict with keys:
            - bbox: [[xmin, ymin, zmin], [xmax, ymax, zmax]] or None
            - extents: [x_extent, y_extent, z_extent] or None
            - center: [cx, cy, cz] or None
            - volume: float (bbox volume) or None
            - error: str (if error occurred)

    Example:
        >>> result = get_bbox("scan.ply")
        >>> print(f"BBox: {result['bbox']}")
        >>> print(f"Extents: {result['extents']}")
    """
    info = parse_cloud(file_path)
    if "error" in info:
        return {"error": info["error"]}

    bbox = info.get("bbox")
    if bbox is None:
        return {
            "bbox": None,
            "extents": None,
            "center": None,
            "volume": None,
        }

    min_xyz, max_xyz = bbox
    extents = [
        max_xyz[0] - min_xyz[0],
        max_xyz[1] - min_xyz[1],
        max_xyz[2] - min_xyz[2],
    ]
    center = [
        (min_xyz[0] + max_xyz[0]) / 2,
        (min_xyz[1] + max_xyz[1]) / 2,
        (min_xyz[2] + max_xyz[2]) / 2,
    ]
    volume = extents[0] * extents[1] * extents[2]

    return {
        "bbox": bbox,
        "extents": extents,
        "center": center,
        "volume": volume,
    }


def check_bbox_within(
    file_path: str,
    xmin: float, ymin: float, zmin: float,
    xmax: float, ymax: float, zmax: float,
    eps: float = 1e-6,
) -> dict:
    """Check if the file's bounding box is within the given box.

    Args:
        file_path: Path to the file.
        xmin, ymin, zmin: Minimum coordinates of the reference box.
        xmax, ymax, zmax: Maximum coordinates of the reference box.
        eps: Tolerance for floating-point comparison.

    Returns:
        dict with keys:
            - within: bool (whether bbox is within the reference box)
            - bbox: [[xmin, ymin, zmin], [xmax, ymax, zmax]] or None
            - reference: [[xmin, ymin, zmin], [xmax, ymax, zmax]]
            - error: str (if error occurred)

    Example:
        >>> result = check_bbox_within("scan.ply", 0, 0, 0, 10, 10, 10)
        >>> print(f"Within box: {result['within']}")
    """
    bbox_result = get_bbox(file_path)
    if "error" in bbox_result:
        return {"error": bbox_result["error"]}

    bbox = bbox_result["bbox"]
    if bbox is None:
        return {
            "within": False,
            "bbox": None,
            "reference": [[xmin, ymin, zmin], [xmax, ymax, zmax]],
            "error": "No bbox available",
        }

    (lo, hi) = bbox
    ok = (
        lo[0] >= xmin - eps and lo[1] >= ymin - eps and lo[2] >= zmin - eps
        and hi[0] <= xmax + eps and hi[1] <= ymax + eps and hi[2] <= zmax + eps
    )

    return {
        "within": ok,
        "bbox": bbox,
        "reference": [[xmin, ymin, zmin], [xmax, ymax, zmax]],
    }


def get_bbox_extent(file_path: str, axis: str) -> dict:
    """Get the extent (size) of the bounding box along a specific axis.

    Args:
        file_path: Path to the file.
        axis: One of "x", "y", "z".

    Returns:
        dict with keys:
            - axis: str (the axis)
            - extent: float (the extent along that axis)
            - error: str (if error occurred)

    Example:
        >>> result = get_bbox_extent("scan.ply", "z")
        >>> print(f"Z extent: {result['extent']}")
    """
    bbox_result = get_bbox(file_path)
    if "error" in bbox_result:
        return {"error": bbox_result["error"]}

    extents = bbox_result["extents"]
    if extents is None:
        return {"error": "No bbox available"}

    axis = axis.lower()
    if axis not in ("x", "y", "z"):
        return {"error": f"Invalid axis: {axis}"}

    idx = {"x": 0, "y": 1, "z": 2}[axis]

    return {
        "axis": axis,
        "extent": extents[idx],
    }


def check_bbox_min_extent(file_path: str, axis: str, min_extent: float) -> dict:
    """Check that the bounding box extent along an axis is >= min_extent.

    Args:
        file_path: Path to the file.
        axis: One of "x", "y", "z".
        min_extent: Minimum extent threshold.

    Returns:
        dict with keys:
            - passes: bool (whether extent >= min_extent)
            - axis: str
            - extent: float
            - min_extent: float
            - error: str (if error occurred)

    Example:
        >>> result = check_bbox_min_extent("scan.ply", "z", 1.0)
        >>> print(f"Z extent >= 1.0: {result['passes']}")
    """
    extent_result = get_bbox_extent(file_path, axis)
    if "error" in extent_result:
        return {"error": extent_result["error"]}

    extent = extent_result["extent"]
    return {
        "passes": extent >= min_extent,
        "axis": axis,
        "extent": extent,
        "min_extent": min_extent,
    }


# ── Property Check Functions ──────────────────────────────────────────────────

def has_property(file_path: str, prop: str) -> dict:
    """Check if a file has a specific property (color/intensity/normals).

    Args:
        file_path: Path to the file.
        prop: Property name ("color", "intensity", "normals", "texcoords").

    Returns:
        dict with keys:
            - has: bool (whether the property exists)
            - property: str
            - error: str (if error occurred)

    Example:
        >>> result = has_property("scan.ply", "color")
        >>> print(f"Has color: {result['has']}")
    """
    info = parse_cloud(file_path)
    if "error" in info:
        return {"error": info["error"]}

    prop = prop.lower()
    if prop == "color":
        has = info.get("has_color", False)
    elif prop == "intensity":
        has = info.get("has_intensity", False)
    elif prop == "normals":
        has = info.get("has_normals", False)
    elif prop == "texcoords":
        has = info.get("has_texcoords", False)
    else:
        return {"error": f"Unknown property: {prop}"}

    return {
        "has": has,
        "property": prop,
    }


def has_color(file_path: str) -> dict:
    """Check if a file has color information.

    Args:
        file_path: Path to the file.

    Returns:
        dict with keys:
            - has_color: bool
            - error: str (if error occurred)

    Example:
        >>> result = has_color("scan.ply")
        >>> print(f"Has color: {result['has_color']}")
    """
    return has_property(file_path, "color")


def has_intensity(file_path: str) -> dict:
    """Check if a file has intensity information.

    Args:
        file_path: Path to the file.

    Returns:
        dict with keys:
            - has_intensity: bool
            - error: str (if error occurred)

    Example:
        >>> result = has_intensity("scan.ply")
        >>> print(f"Has intensity: {result['has_intensity']}")
    """
    return has_property(file_path, "intensity")


def has_normals(file_path: str) -> dict:
    """Check if a file has normal vectors.

    Args:
        file_path: Path to the file.

    Returns:
        dict with keys:
            - has_normals: bool
            - error: str (if error occurred)

    Example:
        >>> result = has_normals("mesh.obj")
        >>> print(f"Has normals: {result['has_normals']}")
    """
    return has_property(file_path, "normals")


def is_mesh(file_path: str) -> dict:
    """Check if a file contains faces (i.e., is a mesh, not just a cloud).

    Args:
        file_path: Path to the file.

    Returns:
        dict with keys:
            - is_mesh: bool
            - face_count: int
            - error: str (if error occurred)

    Example:
        >>> result = is_mesh("model.obj")
        >>> print(f"Is mesh: {result['is_mesh']}")
        >>> print(f"Face count: {result['face_count']}")
    """
    info = parse_cloud(file_path)
    if "error" in info:
        return {"error": info["error"]}

    face_count = info.get("face_count", 0)
    return {
        "is_mesh": face_count > 0,
        "face_count": face_count,
    }


# ── Format Functions ──────────────────────────────────────────────────────────

def get_format(file_path: str) -> dict:
    """Get the actual file format by inspecting content (not just extension).

    Args:
        file_path: Path to the file.

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
    return get_format(file_path)


def check_format(file_path: str, expected: str) -> dict:
    """Check if the file's actual format matches the expected format.

    Args:
        file_path: Path to the file.
        expected: Expected format ("ply", "obj", "ascii").

    Returns:
        dict with keys:
            - match: bool
            - expected: str
            - actual: str
            - error: str (if error occurred)

    Example:
        >>> result = check_format("scan.ply", "ply")
        >>> print(f"Format matches: {result['match']}")
    """
    format_result = get_format(file_path)
    if "error" in format_result:
        return {"error": format_result["error"]}

    actual = format_result["format"]
    expected = expected.lower()

    return {
        "match": actual == expected,
        "expected": expected,
        "actual": actual,
    }


def check_ply_format(file_path: str, expected: str) -> dict:
    """Check the PLY encoding format.

    Args:
        file_path: Path to the PLY file.
        expected: Expected encoding ("ascii", "binary_little_endian", "binary_big_endian").

    Returns:
        dict with keys:
            - match: bool
            - expected: str
            - actual: str
            - error: str (if error occurred)

    Example:
        >>> result = check_ply_format("scan.ply", "ascii")
        >>> print(f"Format matches: {result['match']}")
    """
    from .parser import parse_ply_header

    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}

    header = parse_ply_header(file_path)
    if "error" in header:
        return {"error": header["error"]}

    actual = header["format"]
    expected = expected.lower()

    return {
        "match": actual == expected,
        "expected": expected,
        "actual": actual,
    }


# ── File Check Functions ──────────────────────────────────────────────────────

def file_exists(file_path: str) -> dict:
    """Check if a file exists.

    Args:
        file_path: Path to check.

    Returns:
        dict with keys:
            - exists: bool
            - path: str
            - size: int (file size in bytes, if exists)

    Example:
        >>> result = file_exists("scan.ply")
        >>> print(f"Exists: {result['exists']}")
        >>> print(f"Size: {result['size']} bytes")
    """
    from pathlib import Path

    p = Path(file_path)
    if p.exists():
        return {"exists": True, "path": str(p), "size": p.stat().st_size}
    return {"exists": False, "path": str(p), "size": 0}


def check_file_size(file_path: str, min_bytes: int) -> dict:
    """Check if a file is at least a certain size.

    Args:
        file_path: Path to the file.
        min_bytes: Minimum file size in bytes.

    Returns:
        dict with keys:
            - passes: bool
            - size: int
            - min_bytes: int
            - error: str (if error occurred)

    Example:
        >>> result = check_file_size("scan.ply", 1000)
        >>> print(f"Size >= 1000 bytes: {result['passes']}")
    """
    exists_result = file_exists(file_path)
    if not exists_result["exists"]:
        return {
            "passes": False,
            "size": 0,
            "min_bytes": min_bytes,
            "error": "File not found",
        }

    size = exists_result["size"]
    return {
        "passes": size >= min_bytes,
        "size": size,
        "min_bytes": min_bytes,
    }
