"""
LibreOffice Impress Verifier — programmatic state inspection for presentations in E2B sandbox.

Verification channels (in order of preference):
  1. UNO API — live inspection of open presentations via Python-UNO bridge (slides, shapes, text)
  2. ODF file parsing — .odp files are ZIP archives; parse content.xml directly
  3. File-based checks — file existence, modification time, size

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/libreoffice_impress.py slides")
    sandbox.commands.run("python3 /home/user/verifiers/libreoffice_impress.py slide-text 0")
    sandbox.commands.run("python3 /home/user/verifiers/libreoffice_impress.py check-slide-count 5")

Usage from Python (inside sandbox or via E2B):
    from verifiers.libreoffice_impress import LibreOfficeImpressVerifier
    v = LibreOfficeImpressVerifier()
    slides = v.get_slides()
    text = v.get_slide_text(0)

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - LibreOffice launched with:
    soffice --impress --accept="socket,host=localhost,port=2002;urp;" --norestore
  - For ODF parsing: only stdlib (zipfile, xml.etree)
"""

import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

UNO_HOST = "localhost"
UNO_PORT = 2002

# ODF XML namespaces
ODF_NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "presentation": "urn:oasis:names:tc:opendocument:xmlns:presentation:1.0",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "smil": "urn:oasis:names:tc:opendocument:xmlns:smil-compatible:1.0",
    "anim": "urn:oasis:names:tc:opendocument:xmlns:animation:1.0",
}

# ---------------------------------------------------------------------------
# UNO helpers
# ---------------------------------------------------------------------------

def _get_uno_desktop():
    """Connect to running LibreOffice via UNO and return the desktop object."""
    try:
        import uno
    except ImportError:
        return None, "UNO not available. Ensure python3 is the system Python with UNO bindings."

    try:
        local_ctx = uno.getComponentContext()
        resolver = local_ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local_ctx
        )
        ctx = resolver.resolve(
            f"uno:socket,host={UNO_HOST},port={UNO_PORT};urp;StarOffice.ComponentContext"
        )
        smgr = ctx.ServiceManager
        desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        return desktop, None
    except Exception as e:
        return None, f"UNO connection failed: {e}. Is LibreOffice running with --accept on port {UNO_PORT}?"


def _get_uno_doc():
    """Get the current Impress document via UNO."""
    desktop, err = _get_uno_desktop()
    if err:
        return None, None, err
    doc = desktop.getCurrentComponent()
    if doc is None:
        return desktop, None, "No document is currently open."
    return desktop, doc, None


# ---------------------------------------------------------------------------
# ODF file parsing helpers
# ---------------------------------------------------------------------------

def _parse_odp_content(file_path: str) -> tuple[ET.Element | None, str | None]:
    """Extract and parse content.xml from an .odp file."""
    if not os.path.exists(file_path):
        return None, f"File not found: {file_path}"
    try:
        with zipfile.ZipFile(file_path, "r") as z:
            with z.open("content.xml") as f:
                tree = ET.parse(f)
                return tree.getroot(), None
    except zipfile.BadZipFile:
        return None, f"Not a valid ODP/ZIP file: {file_path}"
    except KeyError:
        return None, f"No content.xml found in: {file_path}"


def _elem_all_text(elem) -> str:
    """Recursively extract all text from an ODF element."""
    return "".join(elem.itertext())


def _find_odp_file() -> str | None:
    """Try to find a recently saved .odp file in common locations."""
    search_dirs = [
        Path.home(),
        Path.home() / "Documents",
        Path.home() / "Desktop",
        Path("/tmp"),
    ]
    odp_files = []
    for d in search_dirs:
        if d.exists():
            for f in d.glob("*.odp"):
                odp_files.append(f)
            for f in d.glob("*.pptx"):
                odp_files.append(f)
    if odp_files:
        return str(max(odp_files, key=lambda f: f.stat().st_mtime))
    return None


def _extract_shape_info(shape) -> dict:
    """Extract common shape properties via UNO."""
    try:
        shape_type = shape.getShapeType() if hasattr(shape, 'getShapeType') else str(type(shape))
    except Exception:
        shape_type = "unknown"

    info = {
        "name": shape.getName() if hasattr(shape, 'getName') else "",
        "type": shape_type.split(".")[-1] if "." in shape_type else shape_type,
    }

    try:
        size = shape.getSize()
        info["width"] = size.Width
        info["height"] = size.Height
    except Exception:
        pass

    try:
        pos = shape.getPosition()
        info["x"] = pos.X
        info["y"] = pos.Y
    except Exception:
        pass

    # Extract text if shape has text
    try:
        if hasattr(shape, 'getString'):
            text = shape.getString()
            if text:
                info["text"] = text
    except Exception:
        pass

    return info


# ---------------------------------------------------------------------------
# LibreOfficeImpressVerifier class
# ---------------------------------------------------------------------------

class LibreOfficeImpressVerifier:
    """Stateless verifier — each method call is independent."""

    # === UNO: Live presentation state ===

    def get_slides(self) -> dict:
        """List all slides with their name and index.

        Example return:
        {"slides": [{"index": 0, "name": "Slide1", "shape_count": 3}], "count": 5}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            draw_pages = doc.getDrawPages()
            slides = []
            for i in range(draw_pages.getCount()):
                page = draw_pages.getByIndex(i)
                slides.append({
                    "index": i,
                    "name": page.getName(),
                    "shape_count": page.getCount(),
                })
            return {"slides": slides, "count": len(slides)}
        except Exception as e:
            return {"error": f"Failed to get slides: {e}"}

    def get_slide_text(self, slide_index: int = 0) -> dict:
        """Get all text content from a slide (from all text shapes).

        Example:
            v.get_slide_text(0)
            => {"index": 0, "texts": ["Title", "Subtitle text"], "full_text": "Title\\nSubtitle text"}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            draw_pages = doc.getDrawPages()
            if slide_index >= draw_pages.getCount():
                return {"error": f"Slide index {slide_index} out of range (have {draw_pages.getCount()})"}

            page = draw_pages.getByIndex(slide_index)
            texts = []
            for i in range(page.getCount()):
                shape = page.getByIndex(i)
                try:
                    if hasattr(shape, 'getString'):
                        t = shape.getString()
                        if t.strip():
                            texts.append(t)
                except Exception:
                    pass

            return {
                "index": slide_index,
                "texts": texts,
                "full_text": "\n".join(texts),
                "name": page.getName(),
            }
        except Exception as e:
            return {"error": f"Failed to get slide text: {e}"}

    def get_slide_shapes(self, slide_index: int = 0) -> dict:
        """Get all shapes on a slide with their properties.

        Example:
            v.get_slide_shapes(0)
            => {"index": 0, "shapes": [{"name": "Title", "type": "TitleTextShape", "text": "Hello"}], "count": 3}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            draw_pages = doc.getDrawPages()
            if slide_index >= draw_pages.getCount():
                return {"error": f"Slide index {slide_index} out of range"}

            page = draw_pages.getByIndex(slide_index)
            shapes = []
            for i in range(page.getCount()):
                shape = page.getByIndex(i)
                shapes.append(_extract_shape_info(shape))

            return {
                "index": slide_index,
                "shapes": shapes,
                "count": len(shapes),
                "name": page.getName(),
            }
        except Exception as e:
            return {"error": f"Failed to get shapes: {e}"}

    def get_slide_layout(self, slide_index: int = 0) -> dict:
        """Get the layout type and master page of a slide.

        Example:
            v.get_slide_layout(0)
            => {"index": 0, "layout": 0, "master_page": "Default"}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            draw_pages = doc.getDrawPages()
            if slide_index >= draw_pages.getCount():
                return {"error": f"Slide index {slide_index} out of range"}

            page = draw_pages.getByIndex(slide_index)
            layout = page.getPropertyValue("Layout")
            master = page.getMasterPage()
            return {
                "index": slide_index,
                "layout": int(str(layout)) if layout is not None else None,
                "master_page": master.getName() if master else None,
                "name": page.getName(),
            }
        except Exception as e:
            return {"error": f"Failed to get slide layout: {e}"}

    def get_document_info(self) -> dict:
        """Get document metadata.

        Example:
            v.get_document_info()
            => {"path": "file:///home/user/test.odp", "title": "test.odp", "slide_count": 5, "modified": true}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            return {
                "path": doc.getURL(),
                "title": doc.getTitle(),
                "slide_count": doc.getDrawPages().getCount(),
                "modified": doc.isModified(),
            }
        except Exception as e:
            return {"error": f"Failed to get doc info: {e}"}

    def get_notes(self, slide_index: int = 0) -> dict:
        """Get speaker notes for a slide.

        Example:
            v.get_notes(0)
            => {"index": 0, "notes": "Remember to explain this slide"}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            draw_pages = doc.getDrawPages()
            if slide_index >= draw_pages.getCount():
                return {"error": f"Slide index {slide_index} out of range"}

            page = draw_pages.getByIndex(slide_index)
            notes_page = page.getNotesPage()
            notes_text = ""
            if notes_page:
                for i in range(notes_page.getCount()):
                    shape = notes_page.getByIndex(i)
                    try:
                        if hasattr(shape, 'getString'):
                            t = shape.getString()
                            if t.strip():
                                notes_text += t + "\n"
                    except Exception:
                        pass

            return {"index": slide_index, "notes": notes_text.strip()}
        except Exception as e:
            return {"error": f"Failed to get notes: {e}"}

    def get_slide_transition(self, slide_index: int = 0) -> dict:
        """Get transition effect for a slide.

        Example:
            v.get_slide_transition(0)
            => {"index": 0, "type": 1, "subtype": 0, "duration": 2.0}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            draw_pages = doc.getDrawPages()
            if slide_index >= draw_pages.getCount():
                return {"error": f"Slide index {slide_index} out of range"}

            page = draw_pages.getByIndex(slide_index)
            return {
                "index": slide_index,
                "type": int(str(page.getPropertyValue("TransitionType"))),
                "subtype": int(str(page.getPropertyValue("TransitionSubtype"))),
                "duration": page.getPropertyValue("TransitionDuration"),
            }
        except Exception as e:
            return {"error": f"Failed to get transition: {e}"}

    def get_slide_size(self) -> dict:
        """Get the slide dimensions.

        Example:
            v.get_slide_size()
            => {"width": 25400, "height": 19050}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            page = doc.getDrawPages().getByIndex(0)
            return {
                "width": page.Width,
                "height": page.Height,
            }
        except Exception as e:
            return {"error": f"Failed to get slide size: {e}"}

    def get_master_slides(self) -> dict:
        """List all master slides.

        Example:
            v.get_master_slides()
            => {"masters": [{"index": 0, "name": "Default"}], "count": 1}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            masters = doc.getMasterPages()
            result = []
            for i in range(masters.getCount()):
                mp = masters.getByIndex(i)
                result.append({"index": i, "name": mp.getName()})
            return {"masters": result, "count": len(result)}
        except Exception as e:
            return {"error": f"Failed to get master slides: {e}"}

    # === ODF file parsing: Offline verification ===

    def parse_file_slides(self, file_path: str | None = None) -> dict:
        """List slides from an ODP file (no UNO needed).

        Example:
            v.parse_file_slides("/home/user/test.odp")
            => {"slides": [{"index": 0, "name": "Slide1", "shape_count": 3}], "count": 5}
        """
        if file_path is None:
            file_path = _find_odp_file()
        if file_path is None:
            return {"error": "No ODP file found. Provide file_path."}

        root, err = _parse_odp_content(file_path)
        if err:
            return {"error": err}

        body = root.find("office:body", ODF_NS)
        pres = body.find("office:presentation", ODF_NS) if body is not None else None
        if pres is None:
            return {"error": "No presentation content found."}

        slides = []
        for i, page in enumerate(pres.findall("draw:page", ODF_NS)):
            name = page.get(f"{{{ODF_NS['draw']}}}name", f"Slide{i+1}")
            shapes = page.findall("draw:frame", ODF_NS) + page.findall("draw:custom-shape", ODF_NS)
            slides.append({"index": i, "name": name, "shape_count": len(shapes)})

        return {"slides": slides, "count": len(slides), "file": file_path}

    def parse_file_slide_text(self, slide_index: int = 0, file_path: str | None = None) -> dict:
        """Extract text from a slide in an ODP file (no UNO needed).

        Example:
            v.parse_file_slide_text(0, "/home/user/test.odp")
            => {"index": 0, "texts": ["Title", "Body"], "full_text": "Title\\nBody"}
        """
        if file_path is None:
            file_path = _find_odp_file()
        if file_path is None:
            return {"error": "No ODP file found. Provide file_path."}

        root, err = _parse_odp_content(file_path)
        if err:
            return {"error": err}

        body = root.find("office:body", ODF_NS)
        pres = body.find("office:presentation", ODF_NS) if body is not None else None
        if pres is None:
            return {"error": "No presentation content found."}

        pages = pres.findall("draw:page", ODF_NS)
        if slide_index >= len(pages):
            return {"error": f"Slide index {slide_index} out of range (have {len(pages)})"}

        page = pages[slide_index]
        texts = []
        for frame in page.findall("draw:frame", ODF_NS):
            text_box = frame.find("draw:text-box", ODF_NS)
            if text_box is not None:
                parts = []
                for p in text_box:
                    t = _elem_all_text(p)
                    if t.strip():
                        parts.append(t)
                if parts:
                    texts.append("\n".join(parts))

        # Also check custom-shape elements
        for shape in page.findall("draw:custom-shape", ODF_NS):
            t = _elem_all_text(shape)
            if t.strip():
                texts.append(t)

        name = page.get(f"{{{ODF_NS['draw']}}}name", f"Slide{slide_index+1}")
        return {
            "index": slide_index,
            "name": name,
            "texts": texts,
            "full_text": "\n".join(texts),
            "file": file_path,
        }

    # === Composite checks ===

    def check_slide_count(self, expected: int) -> dict:
        """Check the number of slides.

        Example:
            v.check_slide_count(5)
            => {"match": true, "expected": 5, "actual": 5}
        """
        result = self.get_slides()
        if "error" in result:
            return result
        actual = result["count"]
        return {"match": actual == expected, "expected": expected, "actual": actual}

    def check_slide_title(self, slide_index: int, expected_title: str) -> dict:
        """Check if a slide contains the expected title text.

        Looks for the expected text in any text shape on the slide.

        Example:
            v.check_slide_title(0, "Introduction")
            => {"match": true, "index": 0, "expected": "Introduction", "actual": "Introduction"}
        """
        result = self.get_slide_text(slide_index)
        if "error" in result:
            return result

        for t in result["texts"]:
            if expected_title.lower().strip() in t.lower().strip():
                return {
                    "match": True,
                    "index": slide_index,
                    "expected": expected_title,
                    "actual": t,
                }

        return {
            "match": False,
            "index": slide_index,
            "expected": expected_title,
            "actual_texts": result["texts"],
        }

    def check_slide_contains_text(self, slide_index: int, text: str) -> dict:
        """Check if a slide contains specific text anywhere.

        Example:
            v.check_slide_contains_text(0, "Hello")
            => {"contains": true, "index": 0, "snippet": "...Hello World..."}
        """
        result = self.get_slide_text(slide_index)
        if "error" in result:
            return result

        full = result["full_text"]
        found = text.lower() in full.lower()
        snippet = None
        if found:
            idx = full.lower().index(text.lower())
            start = max(0, idx - 30)
            end = min(len(full), idx + len(text) + 30)
            snippet = full[start:end]

        return {"contains": found, "index": slide_index, "snippet": snippet}

    def check_shape_exists(self, slide_index: int, shape_type: str | None = None,
                           shape_name: str | None = None) -> dict:
        """Check if a shape matching type or name exists on a slide.

        Example:
            v.check_shape_exists(0, shape_type="TitleTextShape")
            => {"exists": true, "index": 0, "shape": {"name": "Title", "type": "TitleTextShape"}}
        """
        result = self.get_slide_shapes(slide_index)
        if "error" in result:
            return result

        for s in result["shapes"]:
            if shape_type and shape_type.lower() in s.get("type", "").lower():
                return {"exists": True, "index": slide_index, "shape": s}
            if shape_name and shape_name.lower() in s.get("name", "").lower():
                return {"exists": True, "index": slide_index, "shape": s}

        return {"exists": False, "index": slide_index, "shapes_checked": result["count"]}

    def check_shape_count(self, slide_index: int, expected: int) -> dict:
        """Check the number of shapes on a slide.

        Example:
            v.check_shape_count(0, 3)
            => {"match": true, "index": 0, "expected": 3, "actual": 3}
        """
        result = self.get_slide_shapes(slide_index)
        if "error" in result:
            return result
        actual = result["count"]
        return {"match": actual == expected, "index": slide_index, "expected": expected, "actual": actual}

    def check_notes_contain(self, slide_index: int, text: str) -> dict:
        """Check if speaker notes contain specific text.

        Example:
            v.check_notes_contain(0, "important")
            => {"contains": true, "index": 0}
        """
        result = self.get_notes(slide_index)
        if "error" in result:
            return result
        found = text.lower() in result["notes"].lower()
        return {"contains": found, "index": slide_index}

    def check_has_transition(self, slide_index: int) -> dict:
        """Check if a slide has a transition effect set.

        Example:
            v.check_has_transition(0)
            => {"has_transition": true, "index": 0, "type": 1}
        """
        result = self.get_slide_transition(slide_index)
        if "error" in result:
            return result
        has = result.get("type", 0) != 0
        return {"has_transition": has, "index": slide_index, "type": result.get("type")}

    def check_file_exists(self, file_path: str) -> dict:
        """Check if a presentation file exists."""
        exists = os.path.exists(file_path)
        result = {"exists": exists, "path": file_path}
        if exists:
            stat = os.stat(file_path)
            result["size"] = stat.st_size
        return result

    def check_file_saved(self) -> dict:
        """Check if the current document has been saved."""
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        return {
            "saved": not doc.isModified(),
            "path": doc.getURL(),
            "title": doc.getTitle(),
        }

    # === Extended file-parsing endpoints (added for preferences / layout /
    #     animation / action / hidden-slide / custom-show tasks) ===

    def parse_slide_size(self, file_path: str) -> dict:
        """Parse slide width/height from styles.xml in an ODP file.

        Dimensions returned in the units declared in the ODP (cm, in, mm, pt).
        Returns cm, inch, and emu-equivalent helpers for easy comparisons.
        """
        if not os.path.exists(file_path):
            return {"error": f"File not found: {file_path}"}
        try:
            with zipfile.ZipFile(file_path, "r") as z:
                with z.open("styles.xml") as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
        except Exception as e:
            return {"error": f"Failed to parse styles.xml: {e}"}

        page_layouts = root.findall(
            ".//{urn:oasis:names:tc:opendocument:xmlns:style:1.0}page-layout"
        )
        for pl in page_layouts:
            props = pl.find(
                "{urn:oasis:names:tc:opendocument:xmlns:style:1.0}page-layout-properties"
            )
            if props is None:
                continue
            width = props.get(
                "{urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0}page-width"
            )
            height = props.get(
                "{urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0}page-height"
            )
            orientation = props.get(
                "{urn:oasis:names:tc:opendocument:xmlns:style:1.0}print-orientation"
            )
            if width and height:
                return {
                    "width_raw": width,
                    "height_raw": height,
                    "width_cm": _to_cm(width),
                    "height_cm": _to_cm(height),
                    "width_inch": _to_inch(width),
                    "height_inch": _to_inch(height),
                    "orientation": orientation or (
                        "landscape" if _to_cm(width) > _to_cm(height) else "portrait"
                    ),
                    "file": file_path,
                }
        return {"error": "No page-layout found in styles.xml"}

    def check_slide_size(self, file_path: str, width_inch: float, height_inch: float,
                         tolerance: float = 0.02) -> dict:
        """Check that the slide page-layout width/height match expected inches."""
        info = self.parse_slide_size(file_path)
        if "error" in info:
            return info
        wi = info.get("width_inch")

        hi = info.get("height_inch")
        match = (
            wi is not None and hi is not None
            and abs(wi - width_inch) <= tolerance
            and abs(hi - height_inch) <= tolerance
        )
        return {
            "match": match,
            "expected_width_inch": width_inch,
            "expected_height_inch": height_inch,
            "actual_width_inch": wi,
            "actual_height_inch": hi,
            "orientation": info.get("orientation"),
            "file": file_path,
        }

    def parse_header_footer(self, file_path: str) -> dict:
        """Parse header/footer/date declarations and per-page visibility from ODP."""
        root, err = _parse_odp_content(file_path)
        if err:
            return {"error": err}

        decls = {}
        pres_ns = ODF_NS["presentation"]
        # Header/Footer/Date declarations live at the top of <office:presentation>
        body = root.find("office:body", ODF_NS)
        pres = body.find("office:presentation", ODF_NS) if body is not None else None
        if pres is None:
            return {"error": "No presentation content found."}

        for decl in pres.findall("presentation:footer-decl", ODF_NS):
            decls.setdefault("footers", {})[decl.get(f"{{{pres_ns}}}name")] = (
                _elem_all_text(decl).strip()
            )
        for decl in pres.findall("presentation:header-decl", ODF_NS):
            decls.setdefault("headers", {})[decl.get(f"{{{pres_ns}}}name")] = (
                _elem_all_text(decl).strip()
            )
        for decl in pres.findall("presentation:date-time-decl", ODF_NS):
            decls.setdefault("dates", {})[decl.get(f"{{{pres_ns}}}name")] = {
                "source": decl.get(f"{{{pres_ns}}}source"),
                "text": _elem_all_text(decl).strip(),
            }

        pages = []
        for i, page in enumerate(pres.findall("draw:page", ODF_NS)):
            pages.append({
                "index": i,
                "name": page.get(f"{{{ODF_NS['draw']}}}name", f"Slide{i+1}"),
                "use_footer": page.get(f"{{{pres_ns}}}use-footer-name"),
                "use_header": page.get(f"{{{pres_ns}}}use-header-name"),
                "use_date_time": page.get(f"{{{pres_ns}}}use-date-time-name"),
                "visibility": page.get(f"{{{pres_ns}}}visibility", "visible"),
            })

        return {"declarations": decls, "pages": pages, "file": file_path}

    def check_footer_on_slide(self, file_path: str, slide_index: int,
                              expected_text: str | None = None) -> dict:
        """Check that a slide has a footer enabled (and optionally with matching text)."""
        info = self.parse_header_footer(file_path)
        if "error" in info:
            return info
        pages = info.get("pages", [])
        if slide_index >= len(pages):
            return {"error": f"Slide index {slide_index} out of range (have {len(pages)})"}
        page = pages[slide_index]
        footer_name = page.get("use_footer")
        has_footer = bool(footer_name)
        text_match = True
        actual_text = None
        if expected_text is not None:
            footers = info.get("declarations", {}).get("footers", {})
            actual_text = footers.get(footer_name, "") if footer_name else ""
            text_match = expected_text.lower() in actual_text.lower()
        return {
            "match": bool(has_footer and text_match),
            "has_footer": has_footer,
            "footer_name": footer_name,
            "expected_text": expected_text,
            "actual_text": actual_text,
            "index": slide_index,
        }

    def check_slide_number_on_slide(self, file_path: str, slide_index: int) -> dict:
        """Check that the slide has a slide-number placeholder enabled via page-number-related attrs,
        or contains a <text:page-number/> element."""
        root, err = _parse_odp_content(file_path)
        if err:
            return {"error": err}
        body = root.find("office:body", ODF_NS)
        pres = body.find("office:presentation", ODF_NS) if body is not None else None
        if pres is None:
            return {"error": "No presentation content found."}
        pages = pres.findall("draw:page", ODF_NS)
        if slide_index >= len(pages):
            return {"error": f"Slide index {slide_index} out of range (have {len(pages)})"}
        page = pages[slide_index]
        # Look for <text:page-number> anywhere within the slide
        has_pn = len(page.findall(".//text:page-number", ODF_NS)) > 0
        return {"match": has_pn, "has_page_number": has_pn, "index": slide_index}

    def parse_slide_animations(self, file_path: str, slide_index: int) -> dict:
        """Parse <anim:*> elements inside a slide's <draw:page> to list animations."""
        root, err = _parse_odp_content(file_path)
        if err:
            return {"error": err}
        body = root.find("office:body", ODF_NS)
        pres = body.find("office:presentation", ODF_NS) if body is not None else None
        if pres is None:
            return {"error": "No presentation content found."}
        pages = pres.findall("draw:page", ODF_NS)
        if slide_index >= len(pages):
            return {"error": f"Slide index {slide_index} out of range (have {len(pages)})"}
        page = pages[slide_index]
        anim_elems = []
        for child in page.iter():
            tag = child.tag
            if "{urn:oasis:names:tc:opendocument:xmlns:animation:1.0}" in tag:
                local = tag.rsplit("}", 1)[-1]
                anim_elems.append(local)
        return {
            "index": slide_index,
            "animation_elements": anim_elems,
            "count": len(anim_elems),
            "file": file_path,
        }

    def check_has_animation(self, file_path: str, slide_index: int) -> dict:
        """Check whether a slide has at least one animation element."""
        info = self.parse_slide_animations(file_path, slide_index)
        if "error" in info:
            return info
        has = info.get("count", 0) > 0
        return {"has_animation": has, "count": info.get("count", 0), "index": slide_index}

    def parse_hyperlinks(self, file_path: str) -> dict:
        """List all hyperlinks (<text:a>) in the presentation with their hrefs and text."""
        root, err = _parse_odp_content(file_path)
        if err:
            return {"error": err}
        links = []
        for a in root.iter(f"{{{ODF_NS['text']}}}a"):
            href = a.get(f"{{{ODF_NS['xlink']}}}href", "")
            text = _elem_all_text(a).strip()
            links.append({"href": href, "text": text})
        return {"hyperlinks": links, "count": len(links), "file": file_path}

    def check_hyperlink_exists(self, file_path: str, href: str,
                               link_text: str | None = None) -> dict:
        """Check that at least one hyperlink exists whose href (substring) matches,
        and optionally whose visible text contains link_text."""
        info = self.parse_hyperlinks(file_path)
        if "error" in info:
            return info
        for lk in info.get("hyperlinks", []):
            if href.lower() in lk.get("href", "").lower():
                if link_text is None or link_text.lower() in lk.get("text", "").lower():
                    return {"exists": True, "href": lk.get("href"), "text": lk.get("text")}
        return {"exists": False, "href": href, "link_text": link_text,
                "candidates": info.get("hyperlinks", [])[:5]}

    def parse_shape_actions(self, file_path: str, slide_index: int) -> dict:
        """Parse <presentation:event-listener> attached to shapes on a slide.

        Returns a list per shape with {name, text, action, jump_target}.
        """
        root, err = _parse_odp_content(file_path)
        if err:
            return {"error": err}
        body = root.find("office:body", ODF_NS)
        pres = body.find("office:presentation", ODF_NS) if body is not None else None
        if pres is None:
            return {"error": "No presentation content found."}
        pages = pres.findall("draw:page", ODF_NS)
        if slide_index >= len(pages):
            return {"error": f"Slide index {slide_index} out of range (have {len(pages)})"}
        page = pages[slide_index]

        pres_ns = ODF_NS["presentation"]
        xlink_ns = ODF_NS["xlink"]
        shapes_info = []
        # Iterate all direct-and-nested shapes that can host event-listener
        for shape_tag in ("draw:custom-shape", "draw:rect", "draw:frame",
                          "draw:text-box", "draw:ellipse", "draw:polygon"):
            for shape in page.findall(f".//{shape_tag}", ODF_NS):
                ev = shape.find("presentation:event-listener", ODF_NS)
                text = _elem_all_text(shape).strip()
                info = {
                    "shape_tag": shape_tag,
                    "text": text,
                    "action": None,
                    "jump_target": None,
                    "verb": None,
                    "href": None,
                }
                if ev is not None:
                    info["action"] = ev.get(f"{{{pres_ns}}}action")
                    info["verb"] = ev.get(f"{{{pres_ns}}}verb")
                    info["jump_target"] = ev.get(f"{{{xlink_ns}}}href")
                    if info["jump_target"] is None:
                        # Sometimes stored via xlink:href attribute on the shape wrapper
                        info["jump_target"] = shape.get(f"{{{xlink_ns}}}href")
                    info["href"] = info["jump_target"]
                shapes_info.append(info)
        return {"index": slide_index, "shapes": shapes_info, "count": len(shapes_info),
                "file": file_path}

    def check_shape_jumps_to_slide(self, file_path: str, slide_index: int,
                                   shape_text: str, target_slide_name: str) -> dict:
        """Check that a shape on the given slide whose text contains `shape_text`
        has a click-action jumping to the slide named `target_slide_name`.

        The click-action in ODP may appear as:
          - presentation:action="show-page" with xlink:href="#SlideName" (or target slide name)
          - a generic <presentation:event-listener .../> whose xlink:href starts with '#'
        """
        info = self.parse_shape_actions(file_path, slide_index)
        if "error" in info:
            return info
        candidates = []
        for sh in info.get("shapes", []):
            txt = (sh.get("text") or "").strip()
            if shape_text.lower() in txt.lower():
                candidates.append(sh)
                href = sh.get("jump_target") or sh.get("href") or ""
                action = (sh.get("action") or "").lower()
                # href might be e.g. "#Section A" or "Section A"
                target_norm = target_slide_name.lower().strip()
                href_norm = href.lstrip("#").lower().strip()
                if target_norm and (target_norm == href_norm or target_norm in href_norm):
                    return {"match": True, "shape_text": txt, "href": href, "action": action}
        return {
            "match": False,
            "shape_text": shape_text,
            "target": target_slide_name,
            "candidates": candidates,
            "index": slide_index,
        }

    def parse_registry_value(self, item_path: str, prop_name: str | None = None,
                             config_path: str | None = None) -> dict:
        """Parse a value from ~/.config/libreoffice/4/user/registrymodifications.xcu.

        `item_path` is the item's `oor:path` attribute (e.g.
        '/org.openoffice.Office.Common/Save/Document'). `prop_name` is the
        <prop oor:name="..."> we want. If prop_name is None, returns all props
        for the item.
        """
        if config_path is None:
            config_path = os.path.expanduser(
                "~/.config/libreoffice/4/user/registrymodifications.xcu"
            )
        if not os.path.exists(config_path):
            return {"error": f"Registry file not found: {config_path}"}
        try:
            tree = ET.parse(config_path)
            root = tree.getroot()
        except Exception as e:
            return {"error": f"Failed to parse registry: {e}"}

        OOR_NS = "http://openoffice.org/2001/registry"
        matches = []
        for item in root.findall(f"{{{OOR_NS}}}item"):
            path = item.get(f"{{{OOR_NS}}}path")
            if path != item_path:
                continue
            for prop in item.findall(f"{{{OOR_NS}}}prop"):
                name = prop.get(f"{{{OOR_NS}}}name")
                op = prop.get(f"{{{OOR_NS}}}op")
                value_elems = prop.findall(f"{{{OOR_NS}}}value")
                value_texts = [_elem_all_text(v).strip() for v in value_elems]
                value = value_texts[0] if len(value_texts) == 1 else value_texts
                if prop_name is None or name == prop_name:
                    matches.append({"name": name, "op": op, "value": value})

        return {
            "path": item_path,
            "prop_name": prop_name,
            "matches": matches,
            "count": len(matches),
            "config_path": config_path,
        }

    def check_registry_value(self, item_path: str, prop_name: str,
                             expected: str, config_path: str | None = None) -> dict:
        """Check that a registry prop has a specific value (string compare, case-insensitive)."""
        info = self.parse_registry_value(item_path, prop_name, config_path)
        if "error" in info:
            return info
        for m in info.get("matches", []):
            val = m.get("value")
            if isinstance(val, list):
                val_str = ",".join(val)
            else:
                val_str = str(val) if val is not None else ""
            if val_str.strip().lower() == expected.strip().lower():
                return {"match": True, "path": item_path, "prop": prop_name,
                        "expected": expected, "actual": val_str}
        return {
            "match": False,
            "path": item_path,
            "prop": prop_name,
            "expected": expected,
            "matches": info.get("matches", []),
        }

    def check_registry_prop_exists(self, item_path: str, prop_name: str,
                                   config_path: str | None = None) -> dict:
        """Check that a registry item/prop entry exists at all (value-agnostic)."""
        info = self.parse_registry_value(item_path, prop_name, config_path)
        if "error" in info:
            return info
        exists = info.get("count", 0) > 0
        return {
            "exists": exists,
            "path": item_path,
            "prop": prop_name,
            "matches": info.get("matches", []),
        }


# ---------------------------------------------------------------------------
# Unit conversion helpers (used by parse_slide_size)
# ---------------------------------------------------------------------------

def _to_cm(raw: str) -> float | None:
    """Convert an ODF dimension string (e.g. '25.4cm', '10in', '720pt') to cm."""
    if not raw:
        return None
    try:
        if raw.endswith("cm"):
            return float(raw[:-2])
        if raw.endswith("mm"):
            return float(raw[:-2]) / 10.0
        if raw.endswith("in"):
            return float(raw[:-2]) * 2.54
        if raw.endswith("pt"):
            return float(raw[:-2]) * 2.54 / 72.0
        if raw.endswith("pc"):
            return float(raw[:-2]) * 2.54 / 6.0
        return float(raw)
    except Exception:
        return None


def _to_inch(raw: str) -> float | None:
    cm = _to_cm(raw)
    if cm is None:
        return None
    return cm / 2.54


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

COMMANDS = {
    # UNO live state
    "slides": ("List all slides", lambda v, args: v.get_slides()),
    "slide-text": ("Get slide text", lambda v, args: v.get_slide_text(
        int(args[0]) if args else 0)),
    "slide-shapes": ("Get shapes on slide", lambda v, args: v.get_slide_shapes(
        int(args[0]) if args else 0)),
    "slide-layout": ("Get slide layout", lambda v, args: v.get_slide_layout(
        int(args[0]) if args else 0)),
    "doc-info": ("Get document info", lambda v, args: v.get_document_info()),
    "notes": ("Get speaker notes", lambda v, args: v.get_notes(
        int(args[0]) if args else 0)),
    "transition": ("Get slide transition", lambda v, args: v.get_slide_transition(
        int(args[0]) if args else 0)),
    "slide-size": ("Get slide dimensions", lambda v, args: v.get_slide_size()),
    "master-slides": ("List master slides", lambda v, args: v.get_master_slides()),

    # ODF file parsing (offline)
    "parse-slides": ("List slides from ODP", lambda v, args: v.parse_file_slides(
        args[0] if args else None)),
    "parse-slide-text": ("Get slide text from ODP", lambda v, args: v.parse_file_slide_text(
        int(args[0]) if args else 0,
        args[1] if len(args) > 1 else None)),

    # Composite checks
    "check-slide-count": ("Check slide count", lambda v, args: v.check_slide_count(int(args[0]))),
    "check-slide-title": ("Check slide title", lambda v, args: v.check_slide_title(
        int(args[0]), args[1])),
    "check-slide-contains": ("Check slide has text", lambda v, args: v.check_slide_contains_text(
        int(args[0]), args[1])),
    "check-shape-exists": ("Check shape exists", lambda v, args: v.check_shape_exists(
        int(args[0]), shape_type=args[1] if len(args) > 1 else None)),
    "check-shape-count": ("Check shape count", lambda v, args: v.check_shape_count(
        int(args[0]), int(args[1]))),
    "check-notes-contain": ("Check notes have text", lambda v, args: v.check_notes_contain(
        int(args[0]), args[1])),
    "check-has-transition": ("Check transition set", lambda v, args: v.check_has_transition(
        int(args[0]) if args else 0)),
    "check-file-exists": ("Check file exists", lambda v, args: v.check_file_exists(args[0])),
    "check-file-saved": ("Check document saved", lambda v, args: v.check_file_saved()),

    # Extended endpoints (file parsing): slide size, header/footer, animations,
    # hyperlinks, shape actions, and LibreOffice registry preferences.
    "parse-slide-size": ("Parse slide size from ODP styles.xml",
        lambda v, args: v.parse_slide_size(args[0])),
    "check-slide-size": ("Check slide W/H in inches",
        lambda v, args: v.check_slide_size(args[0], float(args[1]), float(args[2]),
                                           float(args[3]) if len(args) > 3 else 0.02)),
    "parse-header-footer": ("Parse header/footer decls and per-slide usage",
        lambda v, args: v.parse_header_footer(args[0])),
    "check-footer-on-slide": ("Check footer enabled on slide (optionally text match)",
        lambda v, args: v.check_footer_on_slide(args[0], int(args[1]),
                                                args[2] if len(args) > 2 else None)),
    "check-slide-number-on-slide": ("Check slide-number placeholder on slide",
        lambda v, args: v.check_slide_number_on_slide(args[0], int(args[1]))),
    "parse-animations": ("Parse <anim:*> elements in a slide",
        lambda v, args: v.parse_slide_animations(args[0], int(args[1]))),
    "check-has-animation": ("Check slide has at least one animation element",
        lambda v, args: v.check_has_animation(args[0], int(args[1]))),
    "parse-hyperlinks": ("List hyperlinks in ODP",
        lambda v, args: v.parse_hyperlinks(args[0])),
    "check-hyperlink-exists": ("Check hyperlink by href substring (and optional text)",
        lambda v, args: v.check_hyperlink_exists(args[0], args[1],
                                                 args[2] if len(args) > 2 else None)),
    "parse-shape-actions": ("Parse shape event-listeners on a slide",
        lambda v, args: v.parse_shape_actions(args[0], int(args[1]))),
    "check-shape-jumps-to-slide": (
        "Check a shape with given text jumps to target slide name",
        lambda v, args: v.check_shape_jumps_to_slide(args[0], int(args[1]), args[2], args[3])),
    "parse-registry-value": ("Read value(s) from LibreOffice registrymodifications.xcu",
        lambda v, args: v.parse_registry_value(args[0], args[1] if len(args) > 1 else None,
                                               args[2] if len(args) > 2 else None)),
    "check-registry-value": ("Check a registry prop has expected value (case-insensitive)",
        lambda v, args: v.check_registry_value(args[0], args[1], args[2],
                                               args[3] if len(args) > 3 else None)),
    "check-registry-prop-exists": ("Check a registry prop entry exists",
        lambda v, args: v.check_registry_prop_exists(args[0], args[1],
                                                     args[2] if len(args) > 2 else None)),
}


def _print_usage():
    print("LibreOffice Impress Verifier — query presentation state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nUNO endpoints require LibreOffice running with --accept on port {UNO_PORT}")
    print("ODF parse-* endpoints work on saved .odp files without UNO")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = LibreOfficeImpressVerifier()
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
