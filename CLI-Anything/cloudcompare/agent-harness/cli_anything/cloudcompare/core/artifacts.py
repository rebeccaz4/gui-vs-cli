"""Deterministic CloudCompare-compatible artifact writers."""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path
from typing import Iterable


def _ensure_parent(path: str) -> Path:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _points(count: int, bbox: tuple[float, float, float, float, float, float]) -> Iterable[tuple[float, float, float]]:
    xmin, ymin, zmin, xmax, ymax, zmax = bbox
    if count <= 1:
        yield xmin, ymin, zmin
        return
    for i in range(count):
        t = i / (count - 1)
        yield (
            xmin + (xmax - xmin) * t,
            ymin + (ymax - ymin) * t,
            zmin + (zmax - zmin) * t,
        )


def write_ascii_cloud(
    path: str,
    count: int = 10,
    bbox: tuple[float, float, float, float, float, float] = (0, 0, 0, 1, 1, 1),
    color: bool = False,
    intensity: bool = False,
) -> dict:
    p = _ensure_parent(path)
    with p.open("w", encoding="utf-8") as f:
        for i, (x, y, z) in enumerate(_points(count, bbox)):
            row = [x, y, z]
            if intensity:
                row.append(float(i))
            if color:
                row.extend([i % 256, 100, 200])
            f.write(" ".join(str(v) for v in row) + "\n")
    return {"path": str(p), "format": "ascii", "points": count, "color": color, "intensity": intensity}


def write_ply_cloud(
    path: str,
    count: int = 10,
    bbox: tuple[float, float, float, float, float, float] = (0, 0, 0, 1, 1, 1),
    encoding: str = "ascii",
    color: bool = False,
    intensity: bool = False,
    normals: bool = False,
    faces: int = 0,
) -> dict:
    p = _ensure_parent(path)
    pts = list(_points(count, bbox))
    if encoding == "ascii":
        with p.open("w", encoding="utf-8") as f:
            f.write("ply\nformat ascii 1.0\n")
            _write_ply_header(f, count, color, intensity, normals, faces)
            for i, (x, y, z) in enumerate(pts):
                row = [x, y, z]
                if normals:
                    row.extend([0, 0, 1])
                if intensity:
                    row.append(float(i))
                if color:
                    row.extend([i % 256, 100, 200])
                f.write(" ".join(str(v) for v in row) + "\n")
            for i in range(faces):
                f.write(f"3 {i % count} {(i + 1) % count} {(i + 2) % count}\n")
    elif encoding in ("binary_little_endian", "binary_big_endian"):
        endian = "<" if encoding == "binary_little_endian" else ">"
        with p.open("wb") as f:
            header = ["ply", f"format {encoding} 1.0"]
            header.extend(_ply_header_lines(count, color, intensity, normals, faces))
            header.append("end_header")
            f.write(("\n".join(header) + "\n").encode("ascii"))
            for i, (x, y, z) in enumerate(pts):
                f.write(struct.pack(endian + "fff", float(x), float(y), float(z)))
                if normals:
                    f.write(struct.pack(endian + "fff", 0.0, 0.0, 1.0))
                if intensity:
                    f.write(struct.pack(endian + "f", float(i)))
                if color:
                    f.write(struct.pack("BBB", i % 256, 100, 200))
            for i in range(faces):
                f.write(struct.pack("B", 3))
                f.write(struct.pack(endian + "iii", i % count, (i + 1) % count, (i + 2) % count))
    else:
        raise ValueError("encoding must be ascii, binary_little_endian, or binary_big_endian")
    return {"path": str(p), "format": "ply", "encoding": encoding, "vertices": count, "faces": faces}


def _ply_header_lines(count: int, color: bool, intensity: bool, normals: bool, faces: int) -> list[str]:
    lines = [
        f"element vertex {count}",
        "property float x",
        "property float y",
        "property float z",
    ]
    if normals:
        lines.extend(["property float nx", "property float ny", "property float nz"])
    if intensity:
        lines.append("property float intensity")
    if color:
        lines.extend(["property uchar red", "property uchar green", "property uchar blue"])
    if faces:
        lines.extend([f"element face {faces}", "property list uchar int vertex_indices"])
    return lines


def _write_ply_header(f, count: int, color: bool, intensity: bool, normals: bool, faces: int) -> None:
    for line in _ply_header_lines(count, color, intensity, normals, faces):
        f.write(line + "\n")
    f.write("end_header\n")


def write_obj_mesh(
    path: str,
    vertices: int = 8,
    faces: int = 12,
    bbox: tuple[float, float, float, float, float, float] = (0, 0, 0, 1, 1, 1),
    normals: bool = True,
) -> dict:
    p = _ensure_parent(path)
    vertices = max(vertices, 3)
    with p.open("w", encoding="utf-8") as f:
        f.write("# cli-anything-cloudcompare fixture\n")
        for x, y, z in _points(vertices, bbox):
            f.write(f"v {x} {y} {z}\n")
        if normals:
            f.write("vn 0 0 1\n")
        for i in range(faces):
            a = i % vertices + 1
            b = (i + 1) % vertices + 1
            c = (i + 2) % vertices + 1
            f.write(f"f {a} {b} {c}\n")
    return {"path": str(p), "format": "obj", "vertices": vertices, "faces": faces, "normals": normals}


def set_config_value(path: str | None, section: str, key: str, value: str) -> dict:
    import configparser

    conf_path = Path(path or os.path.expanduser("~/.config/CCorp/CloudCompare.conf")).expanduser()
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    cp = configparser.ConfigParser(strict=False)
    cp.optionxform = str
    if conf_path.exists():
        cp.read(conf_path)
    if section not in cp:
        cp.add_section(section)
    cp[section][key] = str(value)
    with conf_path.open("w", encoding="utf-8") as f:
        cp.write(f)
    return {"path": str(conf_path), "section": section, "key": key, "value": str(value)}


def add_recent_file(path: str | None, file_path: str) -> dict:
    import configparser

    conf_path = Path(path or os.path.expanduser("~/.config/CCorp/CloudCompare.conf")).expanduser()
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    cp = configparser.ConfigParser(strict=False)
    cp.optionxform = str
    if conf_path.exists():
        cp.read(conf_path)
    if "General" not in cp:
        cp.add_section("General")
    existing = [k for k in cp["General"].keys() if k.lower().startswith("recentfile")]
    cp["General"][f"recentFile{len(existing)}"] = file_path
    with conf_path.open("w", encoding="utf-8") as f:
        cp.write(f)
    return {"path": str(conf_path), "file": file_path, "index": len(existing)}


def parse_bbox(raw: str) -> tuple[float, float, float, float, float, float]:
    vals = json.loads(raw) if raw.strip().startswith("[") else raw.split(",")
    vals = [float(v) for v in vals]
    if len(vals) != 6:
        raise ValueError("bbox must contain 6 values: xmin,ymin,zmin,xmax,ymax,zmax")
    return tuple(vals)  # type: ignore[return-value]
