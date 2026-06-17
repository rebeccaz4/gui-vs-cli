"""
Export module for the Krita CLI harness.

Handles rendering and exporting images using the real Krita backend,
including building .kra files from project JSON state and converting
to various output formats.
"""

import os
import base64
import struct
import tempfile
import xml.etree.ElementTree as ET
import zlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cli_anything.krita.utils.krita_backend import (
    export_animation as backend_export_animation,
    export_file,
    find_krita,
)

# ---------------------------------------------------------------------------
# Export preset definitions
# ---------------------------------------------------------------------------

EXPORT_PRESETS: Dict[str, Dict[str, Any]] = {
    "png": {
        "extension": "png",
        "description": "PNG with full alpha, compression 6",
        "mime": "image/png",
        "options": {
            "alpha": True,
            "compression": 6,
            "indexed": False,
        },
    },
    "png-web": {
        "extension": "png",
        "description": "PNG optimized for web (indexed if possible)",
        "mime": "image/png",
        "options": {
            "alpha": True,
            "compression": 9,
            "indexed": True,
        },
    },
    "jpeg": {
        "extension": "jpg",
        "description": "JPEG quality 90",
        "mime": "image/jpeg",
        "options": {
            "quality": 90,
        },
    },
    "jpeg-web": {
        "extension": "jpg",
        "description": "JPEG quality 75",
        "mime": "image/jpeg",
        "options": {
            "quality": 75,
        },
    },
    "jpeg-low": {
        "extension": "jpg",
        "description": "JPEG quality 50",
        "mime": "image/jpeg",
        "options": {
            "quality": 50,
        },
    },
    "tiff": {
        "extension": "tiff",
        "description": "TIFF uncompressed",
        "mime": "image/tiff",
        "options": {
            "compression": "none",
        },
    },
    "tiff-lzw": {
        "extension": "tiff",
        "description": "TIFF with LZW compression",
        "mime": "image/tiff",
        "options": {
            "compression": "lzw",
        },
    },
    "psd": {
        "extension": "psd",
        "description": "Photoshop PSD",
        "mime": "image/vnd.adobe.photoshop",
        "options": {},
    },
    "pdf": {
        "extension": "pdf",
        "description": "PDF export",
        "mime": "application/pdf",
        "options": {},
    },
    "svg": {
        "extension": "svg",
        "description": "SVG export",
        "mime": "image/svg+xml",
        "options": {},
    },
    "webp": {
        "extension": "webp",
        "description": "WebP quality 85",
        "mime": "image/webp",
        "options": {
            "quality": 85,
        },
    },
    "gif": {
        "extension": "gif",
        "description": "GIF (for animation)",
        "mime": "image/gif",
        "options": {},
    },
    "bmp": {
        "extension": "bmp",
        "description": "BMP uncompressed",
        "mime": "image/bmp",
        "options": {},
    },
}

# ---------------------------------------------------------------------------
# Helpers for building minimal valid PNGs
# ---------------------------------------------------------------------------


def _make_png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Build a single PNG chunk with correct CRC."""
    chunk_body = chunk_type + data
    crc = struct.pack(">I", zlib.crc32(chunk_body) & 0xFFFFFFFF)
    length = struct.pack(">I", len(data))
    return length + chunk_body + crc


def _make_blank_png(width: int, height: int) -> bytes:
    """Create a minimal valid RGBA PNG of the given dimensions (fully transparent)."""
    png_signature = b"\x89PNG\r\n\x1a\n"

    # IHDR: width, height, bit depth 8, color type 6 (RGBA)
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr = _make_png_chunk(b"IHDR", ihdr_data)

    # IDAT: zlib-compressed scanlines (filter byte 0 + 4 zero bytes per pixel)
    raw_scanlines = b""
    for _ in range(height):
        raw_scanlines += b"\x00" + (b"\x00" * width * 4)
    compressed = zlib.compress(raw_scanlines)
    idat = _make_png_chunk(b"IDAT", compressed)

    # IEND
    iend = _make_png_chunk(b"IEND", b"")

    return png_signature + ihdr + idat + iend


# ---------------------------------------------------------------------------
# .kra file builder
# ---------------------------------------------------------------------------


def _canvas(project: dict) -> dict:
    canvas = dict(project.get("canvas") or {})
    image = project.get("image") or {}
    return {
        "width": int(canvas.get("width", image.get("width", 1920))),
        "height": int(canvas.get("height", image.get("height", 1080))),
        "colorspace": canvas.get("colorspace", image.get("colorspace", "RGBA")),
        "depth": canvas.get("depth", image.get("color_depth", "U8")),
        "resolution": int(canvas.get("resolution", image.get("resolution", 300))),
        "profile": canvas.get("profile", image.get("profile", "sRGB-elle-V2-srgbtrc.icc")),
    }


def _project_name(project: dict) -> str:
    image = project.get("image") or {}
    return str(image.get("name") or project.get("name") or "Untitled")


def _bool_attr(value: Any) -> str:
    return "1" if bool(value) else "0"


def _add_keyframes(layer_el: ET.Element, layer: dict) -> None:
    keyframes = layer.get("keyframes") or []
    if not keyframes:
        return
    keyframes_el = ET.SubElement(layer_el, "keyframes")
    for idx, frame in enumerate(keyframes):
        frame_el = ET.SubElement(keyframes_el, "keyframe")
        if isinstance(frame, dict):
            frame_el.set("time", str(frame.get("time", idx)))
        else:
            frame_el.set("time", str(frame))


def _add_masks(layer_el: ET.Element, layer: dict, colorspace: str) -> None:
    for mask in layer.get("masks", []):
        mask_el = ET.SubElement(layer_el, "mask")
        mask_el.set("name", str(mask.get("name", "Mask")))
        mask_el.set("nodetype", str(mask.get("type", "transparencymask")))
        mask_el.set("visible", _bool_attr(mask.get("visible", True)))
        mask_el.set("opacity", str(mask.get("opacity", 255)))
        mask_el.set("colorspacename", colorspace)
        mask_el.set("filename", _layer_filename(mask.get("name", "Mask")))


def _add_layer(parent: ET.Element, layer: dict, colorspace: str) -> None:
    layer_el = ET.SubElement(parent, "layer")
    layer_name = str(layer.get("name", "Layer"))
    layer_el.set("name", layer_name)
    layer_el.set("nodetype", str(layer.get("type", "paintlayer")))
    layer_el.set("visible", _bool_attr(layer.get("visible", True)))
    layer_el.set("opacity", str(layer.get("opacity", 255)))
    layer_el.set("compositeop", str(layer.get("blending_mode", "normal")))
    layer_el.set("colorspacename", colorspace)
    layer_el.set("x", str(layer.get("x", 0)))
    layer_el.set("y", str(layer.get("y", 0)))
    layer_el.set("onionskin", _bool_attr(layer.get("onionskin", False)))
    layer_el.set("intimeline", _bool_attr(layer.get("intimeline", False)))
    layer_el.set("locked", _bool_attr(layer.get("locked", False)))
    layer_el.set("collapsed", _bool_attr(layer.get("collapsed", False)))
    layer_el.set("filename", _layer_filename(layer_name))
    if "width" in layer:
        layer_el.set("width", str(layer["width"]))
    if "height" in layer:
        layer_el.set("height", str(layer["height"]))
    if layer.get("type") == "grouplayer" and layer.get("children"):
        children_el = ET.SubElement(layer_el, "layers")
        for child in layer.get("children", []):
            _add_layer(children_el, child, colorspace)
    _add_keyframes(layer_el, layer)
    _add_masks(layer_el, layer, colorspace)


def _build_maindoc_xml(project: dict) -> bytes:
    """Build maindoc.xml content from project state."""
    canvas = _canvas(project)
    width = canvas["width"]
    height = canvas["height"]
    colorspace = canvas["colorspace"]
    name = _project_name(project)
    resolution = canvas["resolution"]

    doc = ET.Element("DOC")
    doc.set("xmlns", "http://www.calligra.org/DTD/krita")
    doc.set("editor", "CLI-Anything Krita Harness")
    doc.set("syntaxVersion", "2.0")

    image_el = ET.SubElement(doc, "IMAGE")
    image_el.set("name", name)
    image_el.set("width", str(width))
    image_el.set("height", str(height))
    image_el.set("colorspacename", colorspace)
    image_el.set("x-res", str(resolution))
    image_el.set("y-res", str(resolution))
    image_el.set("mime", "application/x-kra")
    image_el.set("profile", str(canvas.get("profile", "")))
    proofing = project.get("proofing") or {}
    if proofing:
        image_el.set("proofing-config-enabled", "true" if proofing.get("enabled", True) else "false")
        image_el.set("proofing-profile-name", str(proofing.get("profile", "")))

    layers_el = ET.SubElement(image_el, "layers")

    layers = project.get("layers", [])
    if not layers:
        # Create a default paint layer
        layers = [
            {
                "name": "Background",
                "type": "paintlayer",
                "visible": True,
                "opacity": 255,
                "uuid": "00000000-0000-0000-0000-000000000001",
            }
        ]

    for layer in layers:
        _add_layer(layers_el, layer, colorspace)

    bg = project.get("background_color", [0, 0, 0])
    if isinstance(bg, str):
        bg = [int(p.strip()) for p in bg.split(",")]
    if len(bg) >= 3:
        r, g, b = [int(v) for v in bg[:3]]
        bg_el = ET.SubElement(image_el, "ProjectionBackgroundColor")
        bg_el.set("ColorData", base64.b64encode(bytes([b, g, r, 255])).decode("ascii"))

    animation = project.get("animation") or {}
    if animation:
        anim_el = ET.SubElement(image_el, "animation")
        fps_el = ET.SubElement(anim_el, "framerate")
        fps_el.set("value", str(animation.get("framerate", 24)))
        range_el = ET.SubElement(anim_el, "range")
        range_el.set("from", str(animation.get("range_from", 0)))
        range_el.set("to", str(animation.get("range_to", 0)))
        current_el = ET.SubElement(anim_el, "currentTime")
        current_el.set("value", str(animation.get("current_time", 0)))

    tree = ET.ElementTree(doc)
    from io import BytesIO

    buf = BytesIO()
    tree.write(buf, encoding="UTF-8", xml_declaration=True)
    return buf.getvalue()


def _build_documentinfo_xml(project: dict) -> bytes:
    """Build documentinfo.xml with Dublin Core metadata."""
    metadata = project.get("metadata") or {}
    name = metadata.get("title") or _project_name(project)
    author = metadata.get("author") or project.get("author") or "CLI-Anything"

    doc = ET.Element("document-info")
    doc.set("xmlns", "http://www.calligra.org/DTD/document-info")

    about = ET.SubElement(doc, "about")
    title_el = ET.SubElement(about, "title")
    title_el.text = str(name)
    abstract_el = ET.SubElement(about, "abstract")
    abstract_el.text = str(metadata.get("description", ""))
    subject_el = ET.SubElement(about, "subject")
    subject_el.text = str(metadata.get("subject", ""))
    keyword_el = ET.SubElement(about, "keyword")
    keyword_el.text = str(metadata.get("keyword", ""))
    creation_el = ET.SubElement(about, "creation-date")
    creation_el.text = str(metadata.get("creation_date", project.get("created", "")))
    editing_el = ET.SubElement(about, "editing-cycles")
    editing_el.text = str(metadata.get("editing_cycles", "1"))
    creator_el = ET.SubElement(about, "creator")
    creator_el.text = str(author)
    date_el = ET.SubElement(about, "date")
    date_el.text = str(metadata.get("date", datetime.now(timezone.utc).isoformat()))

    author_el = ET.SubElement(doc, "author")
    full_name = ET.SubElement(author_el, "full-name")
    full_name.text = str(author)

    tree = ET.ElementTree(doc)
    from io import BytesIO

    buf = BytesIO()
    tree.write(buf, encoding="UTF-8", xml_declaration=True)
    return buf.getvalue()


def _layer_filename(layer_name: str) -> str:
    """Derive a safe filename for a layer inside the .kra archive."""
    safe = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in layer_name)
    return safe


def build_kra_from_project(project: dict, output_path: str) -> str:
    """
    Build a minimal valid .kra file (ZIP archive) from the project JSON state.

    Creates:
    - mimetype (first entry, uncompressed): ``application/x-kra``
    - maindoc.xml with image properties and layer stack
    - documentinfo.xml with Dublin Core metadata
    - A blank RGBA PNG for each paint layer under ``<image_name>/layers/``

    Parameters
    ----------
    project : dict
        The project JSON state containing image properties and layers.
    output_path : str
        Destination path for the ``.kra`` file.

    Returns
    -------
    str
        Absolute path to the created ``.kra`` file.
    """
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    canvas = _canvas(project)
    width = canvas["width"]
    height = canvas["height"]
    image_name = _project_name(project)

    layers = project.get("layers", [])
    if not layers:
        layers = [
            {
                "name": "Background",
                "type": "paintlayer",
                "visible": True,
                "opacity": 255,
            }
        ]

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_STORED) as zf:
        # mimetype must be the first entry, uncompressed
        zf.writestr("mimetype", "application/x-kra", compress_type=zipfile.ZIP_STORED)

        # maindoc.xml
        zf.writestr("maindoc.xml", _build_maindoc_xml(project))

        # documentinfo.xml
        zf.writestr("documentinfo.xml", _build_documentinfo_xml(project))

        # Verifier-readable preview images
        blank_png = _make_blank_png(width, height)
        zf.writestr("mergedimage.png", blank_png)
        zf.writestr("preview.png", blank_png)

        # Blank pixel layer PNGs
        for layer in layers:
            layer_name = layer.get("name", "Layer")
            filename = _layer_filename(layer_name)
            layer_path = f"{image_name}/layers/{filename}"
            zf.writestr(layer_path, blank_png)
            for mask in layer.get("masks", []):
                mask_path = f"{image_name}/layers/{_layer_filename(mask.get('name', 'Mask'))}"
                zf.writestr(mask_path, blank_png)

    return output_path


def export_kra(project: dict, output_path: str, overwrite: bool = False) -> Dict[str, Any]:
    """Export a project directly to a verifier-readable .kra file."""
    output_path = os.path.abspath(output_path)
    if not overwrite and os.path.exists(output_path):
        raise FileExistsError(
            f"Output file already exists: {output_path}. Set overwrite=True to replace it."
        )
    build_kra_from_project(project, output_path)
    return {
        "output_path": output_path,
        "file_size": os.path.getsize(output_path),
        "format": "kra",
        "method": "synthetic-kra",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def export_image(
    project: dict,
    output_path: str,
    preset: str = "png",
    overwrite: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Export a project to an image file.

    1. Builds a ``.kra`` file from the project JSON state.
    2. Calls the Krita backend to convert to the target format.

    Parameters
    ----------
    project : dict
        The project JSON state.
    output_path : str
        Destination file path for the exported image.
    preset : str
        Name of an export preset (see ``EXPORT_PRESETS``).
    overwrite : bool
        If *False* (default), raise ``FileExistsError`` when *output_path*
        already exists.
    **kwargs
        Extra options forwarded to the backend export call.

    Returns
    -------
    dict
        ``{"output_path": str, "file_size": int, "format": str, "method": str}``

    Raises
    ------
    FileExistsError
        If *output_path* exists and *overwrite* is False.
    ValueError
        If *preset* is not a known preset name.
    """
    output_path = os.path.abspath(output_path)

    if not overwrite and os.path.exists(output_path):
        raise FileExistsError(
            f"Output file already exists: {output_path}. "
            "Set overwrite=True to replace it."
        )

    if preset not in EXPORT_PRESETS:
        raise ValueError(
            f"Unknown export preset '{preset}'. "
            f"Available presets: {', '.join(sorted(EXPORT_PRESETS))}"
        )

    preset_config = EXPORT_PRESETS[preset]
    export_options = {**preset_config.get("options", {}), **kwargs}

    # Build a temporary .kra from the project state
    tmp_dir = tempfile.mkdtemp(prefix="krita_export_")
    kra_path = os.path.join(tmp_dir, "project.kra")
    build_kra_from_project(project, kra_path)

    # Use the Krita backend to export
    method = "krita_backend"
    try:
        export_file(
            input_path=kra_path,
            output_path=output_path,
            export_options=export_options,
        )
    except Exception:
        # Re-raise so callers can handle backend failures
        raise

    file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

    return {
        "output_path": output_path,
        "file_size": file_size,
        "format": preset_config["extension"],
        "method": method,
    }


def export_animation(
    project: dict,
    output_dir: str,
    preset: str = "png",
    frame_range: Optional[Tuple[int, int]] = None,
    basename: str = "frame",
) -> Dict[str, Any]:
    """
    Export animation frames using the Krita backend.

    Parameters
    ----------
    project : dict
        The project JSON state.
    output_dir : str
        Directory to write frame files into.
    preset : str
        Export preset name.
    frame_range : tuple[int, int] | None
        Optional ``(start, end)`` frame range. ``None`` exports all frames.
    basename : str
        Base filename for exported frames (e.g. ``frame`` -> ``frame_0001.png``).

    Returns
    -------
    dict
        ``{"frame_count": int, "output_dir": str, "format": str}``
    """
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    if preset not in EXPORT_PRESETS:
        raise ValueError(
            f"Unknown export preset '{preset}'. "
            f"Available presets: {', '.join(sorted(EXPORT_PRESETS))}"
        )

    preset_config = EXPORT_PRESETS[preset]

    # Build temporary .kra
    tmp_dir = tempfile.mkdtemp(prefix="krita_anim_export_")
    kra_path = os.path.join(tmp_dir, "project.kra")
    build_kra_from_project(project, kra_path)

    result = backend_export_animation(
        input_path=kra_path,
        output_dir=output_dir,
        frame_range=frame_range,
        basename=basename,
        export_options=preset_config.get("options", {}),
    )

    frame_count = result.get("frame_count", 0) if isinstance(result, dict) else 0

    return {
        "frame_count": frame_count,
        "output_dir": output_dir,
        "format": preset_config["extension"],
    }


def list_presets() -> List[Dict[str, str]]:
    """
    Return a list of available export presets with descriptions.

    Returns
    -------
    list[dict]
        Each entry has ``name``, ``extension``, and ``description`` keys.
    """
    return [
        {
            "name": name,
            "extension": cfg["extension"],
            "description": cfg["description"],
        }
        for name, cfg in EXPORT_PRESETS.items()
    ]


def get_supported_formats() -> List[str]:
    """
    Return a sorted list of all supported export format extensions.

    Returns
    -------
    list[str]
        Unique format extensions (e.g. ``["bmp", "gif", "jpg", ...]``).
    """
    formats = sorted({cfg["extension"] for cfg in EXPORT_PRESETS.values()})
    return formats
