"""LibreOffice CLI - Impress (presentations) module."""

import os
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional


def _ensure_impress(project: Dict[str, Any]) -> None:
    """Ensure the project is an Impress document."""
    if project.get("type") != "impress":
        raise ValueError(
            f"Document type is '{project.get('type')}', expected 'impress'."
        )
    if "slides" not in project:
        project["slides"] = []


def add_slide(
    project: Dict[str, Any],
    title: str = "",
    content: str = "",
    position: Optional[int] = None,
    layout: Optional[int] = None,
) -> Dict[str, Any]:
    """Add a slide to the presentation."""
    _ensure_impress(project)
    slide = {
        "title": title,
        "content": content,
        "elements": [],
    }
    if layout is not None:
        slide["layout"] = int(layout)
    slides = project["slides"]
    if position is not None:
        if position < 0 or position > len(slides):
            raise IndexError(
                f"Position {position} out of range (0-{len(slides)})"
            )
        slides.insert(position, slide)
    else:
        slides.append(slide)
    return slide


def remove_slide(
    project: Dict[str, Any],
    index: int,
) -> Dict[str, Any]:
    """Remove a slide by index."""
    _ensure_impress(project)
    slides = project["slides"]
    if not slides:
        raise ValueError("No slides to remove.")
    if index < 0 or index >= len(slides):
        raise IndexError(
            f"Slide index {index} out of range (0-{len(slides) - 1})"
        )
    return slides.pop(index)


def set_slide_content(
    project: Dict[str, Any],
    index: int,
    title: Optional[str] = None,
    content: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a slide's title and/or content."""
    _ensure_impress(project)
    slides = project["slides"]
    if index < 0 or index >= len(slides):
        raise IndexError(
            f"Slide index {index} out of range (0-{len(slides) - 1})"
        )
    slide = slides[index]
    if title is not None:
        slide["title"] = title
    if content is not None:
        slide["content"] = content
    return slide


def add_slide_element(
    project: Dict[str, Any],
    slide_index: int,
    element_type: str = "text_box",
    text: str = "",
    x: str = "2cm",
    y: str = "2cm",
    width: str = "10cm",
    height: str = "5cm",
    name: Optional[str] = None,
    href: Optional[str] = None,
    action: Optional[str] = None,
    target: Optional[str] = None,
) -> Dict[str, Any]:
    """Add an element to a slide."""
    _ensure_impress(project)
    slides = project["slides"]
    if slide_index < 0 or slide_index >= len(slides):
        raise IndexError(
            f"Slide index {slide_index} out of range (0-{len(slides) - 1})"
        )
    if element_type not in ("text_box", "image", "shape"):
        raise ValueError(
            f"Invalid element type: {element_type}. "
            f"Use 'text_box', 'image', or 'shape'."
        )
    element = {
        "type": element_type,
        "name": name or f"{element_type}_{len(slides[slide_index].get('elements', [])) + 1}",
        "text": text,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }
    if href:
        element["href"] = href
    if action:
        element["action"] = action
    if target:
        element["target"] = target
    slides[slide_index].setdefault("elements", []).append(element)
    return element


def remove_slide_element(
    project: Dict[str, Any],
    slide_index: int,
    element_index: int,
) -> Dict[str, Any]:
    """Remove an element from a slide."""
    _ensure_impress(project)
    slides = project["slides"]
    if slide_index < 0 or slide_index >= len(slides):
        raise IndexError(
            f"Slide index {slide_index} out of range (0-{len(slides) - 1})"
        )
    elements = slides[slide_index].get("elements", [])
    if element_index < 0 or element_index >= len(elements):
        raise IndexError(
            f"Element index {element_index} out of range "
            f"(0-{len(elements) - 1})"
        )
    return elements.pop(element_index)


def move_slide(
    project: Dict[str, Any],
    from_index: int,
    to_index: int,
) -> Dict[str, Any]:
    """Move a slide to a new position."""
    _ensure_impress(project)
    slides = project["slides"]
    if from_index < 0 or from_index >= len(slides):
        raise IndexError(
            f"From index {from_index} out of range (0-{len(slides) - 1})"
        )
    if to_index < 0 or to_index >= len(slides):
        raise IndexError(
            f"To index {to_index} out of range (0-{len(slides) - 1})"
        )
    slide = slides.pop(from_index)
    slides.insert(to_index, slide)
    return slide


def duplicate_slide(
    project: Dict[str, Any],
    index: int,
) -> Dict[str, Any]:
    """Duplicate a slide."""
    _ensure_impress(project)
    import copy
    slides = project["slides"]
    if index < 0 or index >= len(slides):
        raise IndexError(
            f"Slide index {index} out of range (0-{len(slides) - 1})"
        )
    dup = copy.deepcopy(slides[index])
    dup["title"] = dup.get("title", "") + " (copy)"
    slides.insert(index + 1, dup)
    return dup


def list_slides(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    """List all slides with their indices and titles."""
    _ensure_impress(project)
    result = []
    for i, slide in enumerate(project.get("slides", [])):
        result.append({
            "index": i,
            "title": slide.get("title", ""),
            "content_preview": (slide.get("content", "") or "")[:80],
            "element_count": len(slide.get("elements", [])),
        })
    return result


def get_slide(
    project: Dict[str, Any],
    index: int,
) -> Dict[str, Any]:
    """Get a slide by index."""
    _ensure_impress(project)
    slides = project.get("slides", [])
    if index < 0 or index >= len(slides):
        raise IndexError(
            f"Slide index {index} out of range (0-{len(slides) - 1})"
        )
    return slides[index]


def set_notes(project: Dict[str, Any], slide_index: int, notes: str) -> Dict[str, Any]:
    """Set speaker notes for a slide."""
    slide = get_slide(project, slide_index)
    slide["notes"] = notes
    return slide


def set_transition(
    project: Dict[str, Any],
    slide_index: int,
    transition_type: str = "fade",
    subtype: str = "default",
    duration: float = 2.0,
) -> Dict[str, Any]:
    """Set transition metadata for a slide."""
    slide = get_slide(project, slide_index)
    slide["transition"] = {
        "type": transition_type,
        "subtype": subtype,
        "duration": float(duration),
    }
    return slide["transition"]


def set_footer(
    project: Dict[str, Any],
    text: str,
    slide_index: Optional[int] = None,
    name: str = "footer1",
) -> Dict[str, Any]:
    """Declare a footer and enable it globally or on one slide."""
    _ensure_impress(project)
    project.setdefault("footer_decls", {})[name] = text
    if slide_index is None:
        for slide in project.get("slides", []):
            slide["footer"] = name
    else:
        get_slide(project, slide_index)["footer"] = name
    return {"name": name, "text": text, "slide_index": slide_index}


def set_header(
    project: Dict[str, Any],
    text: str,
    slide_index: Optional[int] = None,
    name: str = "header1",
) -> Dict[str, Any]:
    """Declare a header and enable it globally or on one slide."""
    _ensure_impress(project)
    project.setdefault("header_decls", {})[name] = text
    if slide_index is None:
        for slide in project.get("slides", []):
            slide["header"] = name
    else:
        get_slide(project, slide_index)["header"] = name
    return {"name": name, "text": text, "slide_index": slide_index}


def enable_slide_number(project: Dict[str, Any], slide_index: int) -> Dict[str, Any]:
    """Enable a slide-number placeholder on a slide."""
    slide = get_slide(project, slide_index)
    slide["slide_number"] = True
    return slide


def add_animation(
    project: Dict[str, Any],
    slide_index: int,
    animation_type: str = "par",
    target: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a simple ODF animation marker to a slide."""
    slide = get_slide(project, slide_index)
    anim = {"type": animation_type, "target": target}
    slide.setdefault("animations", []).append(anim)
    return anim


def _new_import_project(path: str, name: Optional[str] = None) -> Dict[str, Any]:
    return {
        "version": "1.0",
        "name": name or os.path.splitext(os.path.basename(path))[0],
        "type": "impress",
        "settings": {
            "page_width": "25.4cm",
            "page_height": "19.05cm",
            "margin_top": "0cm",
            "margin_bottom": "0cm",
            "margin_left": "0cm",
            "margin_right": "0cm",
        },
        "styles": {},
        "slides": [],
        "metadata": {
            "title": "",
            "author": "",
            "description": "",
            "subject": "",
            "software": "libreoffice-cli 1.0",
        },
    }


def import_odp(path: str, name: Optional[str] = None) -> Dict[str, Any]:
    """Import a verifier-readable .odp into project JSON, preserving basic slides/text."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"ODP file not found: {path}")
    try:
        with zipfile.ZipFile(path, "r") as zf:
            content_xml = zf.read("content.xml")
            styles_xml = zf.read("styles.xml") if "styles.xml" in zf.namelist() else b""
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid ODP file: {path}") from exc

    ns = {
        "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
        "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
        "presentation": "urn:oasis:names:tc:opendocument:xmlns:presentation:1.0",
        "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
        "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
        "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    }
    root = ET.fromstring(content_xml)
    project = _new_import_project(path, name=name)
    if styles_xml:
        try:
            styles_root = ET.fromstring(styles_xml)
            props = styles_root.find(".//style:page-layout-properties", ns)
            if props is not None:
                width = props.get(f"{{{ns['fo']}}}page-width")
                height = props.get(f"{{{ns['fo']}}}page-height")
                if width:
                    project["settings"]["page_width"] = width
                if height:
                    project["settings"]["page_height"] = height
        except ET.ParseError:
            pass

    pres = root.find("office:body/office:presentation", ns)
    if pres is None:
        return project
    for page in pres.findall("draw:page", ns):
        slide = {
            "title": page.get(f"{{{ns['draw']}}}name", "Slide"),
            "content": "",
            "elements": [],
        }
        texts = []
        for frame in page.findall("draw:frame", ns):
            frame_text = "\n".join(t.strip() for t in frame.itertext() if t.strip())
            if not frame_text:
                continue
            klass = frame.get(f"{{{ns['presentation']}}}class", "")
            if klass == "title" and not texts:
                slide["title"] = frame_text
            elif klass in ("subtitle", "outline", "object") and not slide["content"]:
                slide["content"] = frame_text
            else:
                slide["elements"].append({
                    "type": "text_box",
                    "name": frame.get(f"{{{ns['draw']}}}name", "TextBox"),
                    "text": frame_text,
                    "x": frame.get(f"{{{ns['svg']}}}x", "2cm"),
                    "y": frame.get(f"{{{ns['svg']}}}y", "2cm"),
                    "width": frame.get(f"{{{ns['svg']}}}width", "10cm"),
                    "height": frame.get(f"{{{ns['svg']}}}height", "5cm"),
                })
        project["slides"].append(slide)
    return project


def _slide_number_from_pptx_name(name: str) -> int:
    match = re.search(r"slide(\d+)\.xml$", name)
    return int(match.group(1)) if match else 0


def _import_pptx_basic(path: str, name: Optional[str] = None) -> Dict[str, Any]:
    """Import basic slide text from .pptx without LibreOffice."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            slide_names = sorted(
                (
                    item
                    for item in zf.namelist()
                    if item.startswith("ppt/slides/slide") and item.endswith(".xml")
                ),
                key=_slide_number_from_pptx_name,
            )
            if not slide_names:
                raise ValueError(f"No slides found in PPTX file: {path}")
            project = _new_import_project(path, name=name)
            ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
            for idx, slide_name in enumerate(slide_names, start=1):
                root = ET.fromstring(zf.read(slide_name))
                texts = [
                    (node.text or "").strip()
                    for node in root.findall(".//a:t", ns)
                    if (node.text or "").strip()
                ]
                title = texts[0] if texts else f"Slide {idx}"
                content = "\n".join(texts[1:])
                project["slides"].append({
                    "title": title,
                    "content": content,
                    "elements": [],
                })
            return project
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid PPTX file: {path}") from exc


def import_presentation(path: str, name: Optional[str] = None) -> Dict[str, Any]:
    """Import an existing .odp, .pptx, or .ppt into project JSON."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Presentation file not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".odp":
        return import_odp(path, name=name)
    if ext not in (".pptx", ".ppt"):
        raise ValueError("Only .odp, .pptx, and .ppt import are supported.")

    try:
        from cli_anything.libreoffice.utils.lo_backend import convert

        with tempfile.TemporaryDirectory(prefix="lo_import_presentation_") as tmpdir:
            odp_path = convert(path, "odp", output_dir=tmpdir)
            return import_odp(odp_path, name=name)
    except Exception as exc:
        if ext == ".pptx":
            return _import_pptx_basic(path, name=name)
        raise RuntimeError(
            "Importing .ppt requires LibreOffice headless conversion to .odp."
        ) from exc
