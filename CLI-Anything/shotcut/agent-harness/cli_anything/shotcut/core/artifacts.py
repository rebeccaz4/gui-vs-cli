"""Deterministic Shotcut artifact helpers for local verification."""

from __future__ import annotations

import configparser
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable


def _parse_fps(fps: str) -> tuple[str, str]:
    text = str(fps)
    if "/" in text:
        num, den = text.split("/", 1)
        return str(int(num)), str(int(den))
    value = float(text)
    if value.is_integer():
        return str(int(value)), "1"
    return str(int(round(value * 1000))), "1000"


def _prop(parent: ET.Element, name: str, value: str) -> ET.Element:
    elem = ET.SubElement(parent, "property")
    elem.set("name", name)
    elem.text = str(value)
    return elem


def _parse_clip_spec(spec: str) -> dict:
    parts = spec.split("=", 2)
    if len(parts) < 2:
        raise ValueError("Clip spec must be ID=RESOURCE[=CAPTION]")
    clip_id, resource = parts[0], parts[1]
    caption = parts[2] if len(parts) == 3 else Path(resource).name
    return {"id": clip_id, "resource": resource, "caption": caption}


def _parse_playlist_spec(spec: str) -> tuple[str, list[str]]:
    if "=" not in spec:
        raise ValueError("Playlist spec must be ID=PRODUCER[,PRODUCER...]")
    playlist_id, producers = spec.split("=", 1)
    return playlist_id, [p for p in producers.split(",") if p]


def _tree(path: str) -> ET.ElementTree:
    return ET.parse(path)


def create_mlt(
    output_path: str,
    width: int = 1920,
    height: int = 1080,
    fps: str = "30",
    clips: Iterable[str] = (),
    playlists: Iterable[str] = (),
    tracks: Iterable[str] = (),
    filters: Iterable[str] = (),
    transitions: Iterable[str] = (),
) -> dict:
    """Create a deterministic MLT XML project."""
    fps_num, fps_den = _parse_fps(fps)
    root = ET.Element("mlt", {"LC_NUMERIC": "C", "version": "7.0.0", "producer": "tractor0"})
    ET.SubElement(root, "profile", {
        "description": f"{width}x{height} {fps_num}/{fps_den}fps",
        "width": str(width),
        "height": str(height),
        "frame_rate_num": fps_num,
        "frame_rate_den": fps_den,
        "sample_aspect_num": "1",
        "sample_aspect_den": "1",
        "display_aspect_num": "16",
        "display_aspect_den": "9",
        "progressive": "1",
        "colorspace": "709",
    })

    clip_ids = []
    for spec in clips:
        clip = _parse_clip_spec(spec)
        prod = ET.SubElement(root, "producer", {"id": clip["id"], "in": "00:00:00.000", "out": "00:00:01.000"})
        _prop(prod, "resource", clip["resource"])
        _prop(prod, "mlt_service", "avformat")
        _prop(prod, "shotcut:caption", clip["caption"])
        clip_ids.append(clip["id"])

    playlist_ids = []
    for spec in playlists:
        playlist_id, producers = _parse_playlist_spec(spec)
        pl = ET.SubElement(root, "playlist", {"id": playlist_id})
        for producer in producers:
            ET.SubElement(pl, "entry", {"producer": producer, "in": "00:00:00.000", "out": "00:00:01.000"})
        playlist_ids.append(playlist_id)

    if not playlist_ids and clip_ids:
        pl = ET.SubElement(root, "playlist", {"id": "playlist0"})
        for clip_id in clip_ids:
            ET.SubElement(pl, "entry", {"producer": clip_id, "in": "00:00:00.000", "out": "00:00:01.000"})
        playlist_ids.append("playlist0")

    track_ids = list(tracks) or playlist_ids
    tractor = ET.SubElement(root, "tractor", {"id": "tractor0", "in": "00:00:00.000", "out": "00:00:01.000"})
    multitrack = ET.SubElement(tractor, "multitrack")
    for playlist_id in track_ids:
        ET.SubElement(tractor, "track", {"producer": playlist_id})
        ET.SubElement(multitrack, "track", {"producer": playlist_id})

    for index, service in enumerate(filters):
        filt = ET.SubElement(tractor, "filter", {"id": f"filter{index}"})
        _prop(filt, "mlt_service", service)
        _prop(filt, "shotcut:name", service)

    for index, service in enumerate(transitions):
        trans = ET.SubElement(tractor, "transition", {"id": f"transition{index}"})
        _prop(trans, "mlt_service", service)
        _prop(trans, "a_track", "0")
        _prop(trans, "b_track", "1")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return {"path": str(path), "clips": len(clip_ids), "playlists": len(playlist_ids), "tracks": len(track_ids)}


def add_clip(project_path: str, clip_id: str, resource: str, caption: str | None = None,
             playlist_id: str = "playlist0") -> dict:
    """Add a deterministic producer and playlist entry to an existing MLT file."""
    tree = _tree(project_path)
    root = tree.getroot()
    prod = ET.Element("producer", {"id": clip_id, "in": "00:00:00.000", "out": "00:00:01.000"})
    _prop(prod, "resource", resource)
    _prop(prod, "mlt_service", "avformat")
    _prop(prod, "shotcut:caption", caption or Path(resource).name)
    tractor = root.find("tractor")
    if tractor is not None:
        root.insert(list(root).index(tractor), prod)
    else:
        root.append(prod)

    playlist = root.find(f".//playlist[@id='{playlist_id}']")
    if playlist is None:
        playlist = ET.SubElement(root, "playlist", {"id": playlist_id})
    ET.SubElement(playlist, "entry", {"producer": clip_id, "in": "00:00:00.000", "out": "00:00:01.000"})
    tree.write(project_path, encoding="utf-8", xml_declaration=True)
    return {"path": project_path, "clip_id": clip_id, "playlist_id": playlist_id}


def _config(path: str | None) -> tuple[configparser.ConfigParser, Path]:
    cfg_path = Path(path).expanduser() if path else Path.home() / ".config" / "Meltytech" / "Shotcut.conf"
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore
    if cfg_path.exists():
        parser.read(str(cfg_path))
    return parser, cfg_path


def config_set(section: str, key: str, value: str, path: str | None = None) -> dict:
    parser, cfg_path = _config(path)
    if not parser.has_section(section):
        parser.add_section(section)
    parser.set(section, key, value)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("w", encoding="utf-8") as handle:
        parser.write(handle)
    return {"path": str(cfg_path), "section": section, "key": key, "value": value}


def recent_add(project_path: str, path: str | None = None) -> dict:
    parser, cfg_path = _config(path)
    section = "RecentFiles"
    if not parser.has_section(section):
        parser.add_section(section)
    existing = [k for k in parser.options(section) if k.endswith("\\Path")]
    index = len(existing) + 1
    parser.set(section, f"{index}\\Path", project_path)
    parser.set(section, "size", str(index))
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("w", encoding="utf-8") as handle:
        parser.write(handle)
    return {"path": str(cfg_path), "recent": project_path, "index": index}


def export_sample(output_path: str, width: int = 320, height: int = 240,
                  duration: float = 1.0, codec: str = "libx264") -> dict:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for export-sample")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-f", "lavfi",
        "-i", f"color=c=blue:s={width}x{height}:d={duration}",
        "-c:v", codec,
        "-pix_fmt", "yuv420p",
        str(path),
    ]
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-500:])
    return {"path": str(path), "size": path.stat().st_size, "codec": codec, "width": width, "height": height}
