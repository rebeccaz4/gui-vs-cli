"""
LibreOffice Draw Verifier — programmatic state inspection for drawings in E2B sandbox.

Verification channels (in order of preference):
  1. UNO API — live inspection of open drawings via Python-UNO bridge (pages, shapes, connectors)
  2. ODF file parsing — .odg files are ZIP archives; parse content.xml directly
  3. File-based checks — file existence, modification time, size

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/libreoffice_draw.py pages")
    sandbox.commands.run("python3 /home/user/verifiers/libreoffice_draw.py page-shapes 0")
    sandbox.commands.run("python3 /home/user/verifiers/libreoffice_draw.py check-page-count 3")

Usage from Python (inside sandbox or via E2B):
    from verifiers.libreoffice_draw import LibreOfficeDrawVerifier
    v = LibreOfficeDrawVerifier()
    pages = v.get_pages()
    shapes = v.get_page_shapes(0)

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - LibreOffice launched with:
    soffice --draw --accept="socket,host=localhost,port=2002;urp;" --norestore
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
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "presentation": "urn:oasis:names:tc:opendocument:xmlns:presentation:1.0",
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
    """Get the current Draw document via UNO."""
    desktop, err = _get_uno_desktop()
    if err:
        return None, None, err
    doc = desktop.getCurrentComponent()
    if doc is None:
        return desktop, None, "No document is currently open."
    return desktop, doc, None


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

    # Check if it's a connector
    try:
        if shape.supportsService("com.sun.star.drawing.ConnectorShape"):
            info["is_connector"] = True
            try:
                start_shape = shape.getPropertyValue("StartShape")
                end_shape = shape.getPropertyValue("EndShape")
                if start_shape:
                    info["start_shape"] = start_shape.getName()
                if end_shape:
                    info["end_shape"] = end_shape.getName()
            except Exception:
                pass
    except Exception:
        pass

    # CustomShape geometric subtype — toolbar-drawn ellipses/rectangles are
    # com.sun.star.drawing.CustomShape with the geometric kind in CustomShapeGeometry['Type'].
    try:
        if shape.supportsService("com.sun.star.drawing.CustomShape"):
            try:
                geom = shape.getPropertyValue("CustomShapeGeometry")
                for pv in geom:
                    if getattr(pv, "Name", None) == "Type":
                        info["custom_shape_type"] = pv.Value
                        break
            except Exception:
                pass
    except Exception:
        pass

    # Fill and line properties
    try:
        fill_style = str(shape.getPropertyValue("FillStyle"))
        info["fill_style"] = fill_style.split(".")[-1].lower()
    except Exception:
        pass

    try:
        fill_color = shape.getPropertyValue("FillColor")
        if fill_color is not None:
            info["fill_color"] = f"#{fill_color:06X}"
    except Exception:
        pass

    return info


# ---------------------------------------------------------------------------
# ODF file parsing helpers
# ---------------------------------------------------------------------------

def _parse_odg_content(file_path: str) -> tuple[ET.Element | None, str | None]:
    """Extract and parse content.xml from an .odg file."""
    if not os.path.exists(file_path):
        return None, f"File not found: {file_path}"
    try:
        with zipfile.ZipFile(file_path, "r") as z:
            with z.open("content.xml") as f:
                tree = ET.parse(f)
                return tree.getroot(), None
    except zipfile.BadZipFile:
        return None, f"Not a valid ODG/ZIP file: {file_path}"
    except KeyError:
        return None, f"No content.xml found in: {file_path}"


def _elem_all_text(elem) -> str:
    """Recursively extract all text from an ODF element."""
    return "".join(elem.itertext())


def _find_odg_file() -> str | None:
    """Try to find a recently saved .odg file in common locations."""
    search_dirs = [
        Path.home(),
        Path.home() / "Documents",
        Path.home() / "Desktop",
        Path("/tmp"),
    ]
    odg_files = []
    for d in search_dirs:
        if d.exists():
            for f in d.glob("*.odg"):
                odg_files.append(f)
    if odg_files:
        return str(max(odg_files, key=lambda f: f.stat().st_mtime))
    return None


# ---------------------------------------------------------------------------
# LibreOfficeDrawVerifier class
# ---------------------------------------------------------------------------

class LibreOfficeDrawVerifier:
    """Stateless verifier — each method call is independent."""

    # === UNO: Live drawing state ===

    def get_pages(self) -> dict:
        """List all pages with their name and shape count.

        Example return:
        {"pages": [{"index": 0, "name": "page1", "shape_count": 5}], "count": 3}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            draw_pages = doc.getDrawPages()
            pages = []
            for i in range(draw_pages.getCount()):
                page = draw_pages.getByIndex(i)
                pages.append({
                    "index": i,
                    "name": page.getName(),
                    "shape_count": page.getCount(),
                })
            return {"pages": pages, "count": len(pages)}
        except Exception as e:
            return {"error": f"Failed to get pages: {e}"}

    def get_page_shapes(self, page_index: int = 0) -> dict:
        """Get all shapes on a page with their properties.

        Example:
            v.get_page_shapes(0)
            => {"index": 0, "shapes": [{"name": "rect1", "type": "RectangleShape", ...}], "count": 3}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            draw_pages = doc.getDrawPages()
            if page_index >= draw_pages.getCount():
                return {"error": f"Page index {page_index} out of range (have {draw_pages.getCount()})"}

            page = draw_pages.getByIndex(page_index)
            shapes = []
            for i in range(page.getCount()):
                shape = page.getByIndex(i)
                shapes.append(_extract_shape_info(shape))

            return {
                "index": page_index,
                "shapes": shapes,
                "count": len(shapes),
                "name": page.getName(),
            }
        except Exception as e:
            return {"error": f"Failed to get shapes: {e}"}

    def get_page_text(self, page_index: int = 0) -> dict:
        """Get all text from shapes on a page.

        Example:
            v.get_page_text(0)
            => {"index": 0, "texts": ["Box 1", "Label"], "full_text": "Box 1\\nLabel"}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            draw_pages = doc.getDrawPages()
            if page_index >= draw_pages.getCount():
                return {"error": f"Page index {page_index} out of range"}

            page = draw_pages.getByIndex(page_index)
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
                "index": page_index,
                "texts": texts,
                "full_text": "\n".join(texts),
                "name": page.getName(),
            }
        except Exception as e:
            return {"error": f"Failed to get page text: {e}"}

    def get_page_size(self) -> dict:
        """Get the page dimensions.

        Example:
            v.get_page_size()
            => {"width": 28000, "height": 21000}
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
            return {"error": f"Failed to get page size: {e}"}

    def get_document_info(self) -> dict:
        """Get document metadata.

        Example:
            v.get_document_info()
            => {"path": "file:///home/user/test.odg", "title": "test.odg", "page_count": 3, "modified": true}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            return {
                "path": doc.getURL(),
                "title": doc.getTitle(),
                "page_count": doc.getDrawPages().getCount(),
                "modified": doc.isModified(),
            }
        except Exception as e:
            return {"error": f"Failed to get doc info: {e}"}

    def get_layers(self) -> dict:
        """List all layers in the document.

        Example:
            v.get_layers()
            => {"layers": [{"index": 0, "name": "Layout", "visible": true, "printable": true}], "count": 3}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            layer_mgr = doc.getLayerManager()
            layers = []
            for i in range(layer_mgr.getCount()):
                layer = layer_mgr.getByIndex(i)
                # Layer objects use Name property, not getName()
                name = layer.getPropertyValue("Name")
                layers.append({
                    "index": i,
                    "name": name,
                    "visible": layer.getPropertyValue("IsVisible"),
                    "printable": layer.getPropertyValue("IsPrintable"),
                    "locked": layer.getPropertyValue("IsLocked"),
                })
            return {"layers": layers, "count": len(layers)}
        except Exception as e:
            return {"error": f"Failed to get layers: {e}"}

    def get_connectors(self, page_index: int = 0) -> dict:
        """List all connector shapes on a page.

        Example:
            v.get_connectors(0)
            => {"connectors": [{"name": "conn1", "start_shape": "rect1", "end_shape": "rect2"}], "count": 1}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            draw_pages = doc.getDrawPages()
            if page_index >= draw_pages.getCount():
                return {"error": f"Page index {page_index} out of range"}

            page = draw_pages.getByIndex(page_index)
            connectors = []
            for i in range(page.getCount()):
                shape = page.getByIndex(i)
                try:
                    if shape.supportsService("com.sun.star.drawing.ConnectorShape"):
                        info = _extract_shape_info(shape)
                        connectors.append(info)
                except Exception:
                    pass

            return {"connectors": connectors, "count": len(connectors), "index": page_index}
        except Exception as e:
            return {"error": f"Failed to get connectors: {e}"}

    # === ODF file parsing: Offline verification ===

    def parse_file_pages(self, file_path: str | None = None) -> dict:
        """List pages from an ODG file (no UNO needed).

        Example:
            v.parse_file_pages("/home/user/test.odg")
            => {"pages": [{"index": 0, "name": "page1", "shape_count": 3}], "count": 1}
        """
        if file_path is None:
            file_path = _find_odg_file()
        if file_path is None:
            return {"error": "No ODG file found. Provide file_path."}

        root, err = _parse_odg_content(file_path)
        if err:
            return {"error": err}

        body = root.find("office:body", ODF_NS)
        drawing = body.find("office:drawing", ODF_NS) if body is not None else None
        if drawing is None:
            return {"error": "No drawing content found."}

        pages = []
        for i, page in enumerate(drawing.findall("draw:page", ODF_NS)):
            name = page.get(f"{{{ODF_NS['draw']}}}name", f"page{i+1}")
            # Count all direct child elements that are shapes
            shape_count = 0
            for child in page:
                tag = child.tag
                if any(tag.endswith(s) for s in ["rect", "circle", "ellipse", "line",
                       "polyline", "polygon", "path", "frame", "custom-shape",
                       "connector", "g"]):
                    shape_count += 1
            pages.append({"index": i, "name": name, "shape_count": shape_count})

        return {"pages": pages, "count": len(pages), "file": file_path}

    def parse_file_page_text(self, page_index: int = 0, file_path: str | None = None) -> dict:
        """Extract text from shapes on a page in an ODG file.

        Example:
            v.parse_file_page_text(0, "/home/user/test.odg")
            => {"index": 0, "texts": ["Box 1", "Label"], "full_text": "Box 1\\nLabel"}
        """
        if file_path is None:
            file_path = _find_odg_file()
        if file_path is None:
            return {"error": "No ODG file found. Provide file_path."}

        root, err = _parse_odg_content(file_path)
        if err:
            return {"error": err}

        body = root.find("office:body", ODF_NS)
        drawing = body.find("office:drawing", ODF_NS) if body is not None else None
        if drawing is None:
            return {"error": "No drawing content found."}

        pages = drawing.findall("draw:page", ODF_NS)
        if page_index >= len(pages):
            return {"error": f"Page index {page_index} out of range (have {len(pages)})"}

        page = pages[page_index]
        texts = []
        for elem in page.iter():
            tag = elem.tag
            if tag == f"{{{ODF_NS['text']}}}p" or tag == f"{{{ODF_NS['text']}}}h":
                t = _elem_all_text(elem)
                if t.strip():
                    texts.append(t)

        name = page.get(f"{{{ODF_NS['draw']}}}name", f"page{page_index+1}")
        return {
            "index": page_index,
            "name": name,
            "texts": list(dict.fromkeys(texts)),  # deduplicate preserving order
            "full_text": "\n".join(dict.fromkeys(texts)),
            "file": file_path,
        }

    # === Composite checks ===

    def check_page_count(self, expected: int) -> dict:
        """Check the number of pages.

        Example:
            v.check_page_count(3)
            => {"match": true, "expected": 3, "actual": 3}
        """
        result = self.get_pages()
        if "error" in result:
            return result
        actual = result["count"]
        return {"match": actual == expected, "expected": expected, "actual": actual}

    def check_shape_count(self, page_index: int, expected: int) -> dict:
        """Check the number of shapes on a page.

        Example:
            v.check_shape_count(0, 5)
            => {"match": true, "index": 0, "expected": 5, "actual": 5}
        """
        result = self.get_page_shapes(page_index)
        if "error" in result:
            return result
        actual = result["count"]
        return {"match": actual == expected, "index": page_index, "expected": expected, "actual": actual}

    def check_shape_exists(self, page_index: int, shape_type: str | None = None,
                           shape_name: str | None = None) -> dict:
        """Check if a shape matching type or name exists on a page.

        Matches against the native `type` (e.g. 'RectangleShape') and also against
        `custom_shape_type` for CustomShape instances drawn via the toolbar, where
        the geometric kind is 'rectangle', 'round-rectangle', 'ellipse', etc.
        So `shape_type='EllipseShape'` matches any CustomShape whose
        CustomShapeGeometry Type contains 'ellipse', and `'RectangleShape'`
        matches 'rectangle' / 'round-rectangle'.

        Example:
            v.check_shape_exists(0, shape_type="RectangleShape")
            => {"exists": true, "index": 0, "shape": {"name": "rect1", "type": "RectangleShape"}}
        """
        result = self.get_page_shapes(page_index)
        if "error" in result:
            return result

        # Map a requested native shape_type to the geometric token used by CustomShapeGeometry.
        custom_alias = None
        if shape_type:
            st_lower = shape_type.lower()
            if "ellipse" in st_lower or "oval" in st_lower:
                custom_alias = "ellipse"
            elif "rectangle" in st_lower or "rect" in st_lower:
                custom_alias = "rectangle"

        for s in result["shapes"]:
            if shape_type:
                if shape_type.lower() in s.get("type", "").lower():
                    return {"exists": True, "index": page_index, "shape": s}
                cst = (s.get("custom_shape_type") or "").lower()
                if cst:
                    # Direct substring (e.g. shape_type='ellipse' matches 'ellipse')
                    if shape_type.lower() in cst:
                        return {"exists": True, "index": page_index, "shape": s}
                    # Native-name -> geometric-token mapping
                    if custom_alias and custom_alias in cst:
                        return {"exists": True, "index": page_index, "shape": s}
            if shape_name and shape_name.lower() in s.get("name", "").lower():
                return {"exists": True, "index": page_index, "shape": s}

        return {"exists": False, "index": page_index, "shapes_checked": result["count"]}

    def check_page_contains_text(self, page_index: int, text: str) -> dict:
        """Check if any shape on the page contains specific text.

        Example:
            v.check_page_contains_text(0, "Hello")
            => {"contains": true, "index": 0, "snippet": "Hello World"}
        """
        result = self.get_page_text(page_index)
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

        return {"contains": found, "index": page_index, "snippet": snippet}

    def check_connector_exists(self, page_index: int,
                                start_name: str | None = None,
                                end_name: str | None = None) -> dict:
        """Check if a connector between two shapes exists.

        Example:
            v.check_connector_exists(0, start_name="rect1", end_name="rect2")
            => {"exists": true, "connector": {...}}
        """
        result = self.get_connectors(page_index)
        if "error" in result:
            return result

        for c in result["connectors"]:
            start_ok = start_name is None or start_name.lower() in c.get("start_shape", "").lower()
            end_ok = end_name is None or end_name.lower() in c.get("end_shape", "").lower()
            if start_ok and end_ok:
                return {"exists": True, "connector": c}

        return {"exists": False, "index": page_index, "connectors_checked": result["count"]}

    def check_layer_exists(self, layer_name: str) -> dict:
        """Check if a layer with the given name exists.

        Example:
            v.check_layer_exists("Layout")
            => {"exists": true, "layer": {"name": "Layout", "visible": true}}
        """
        result = self.get_layers()
        if "error" in result:
            return result

        for l in result["layers"]:
            if l["name"].lower() == layer_name.lower():
                return {"exists": True, "layer": l}
        return {"exists": False, "layer_name": layer_name,
                "available": [l["name"] for l in result["layers"]]}

    def check_file_exists(self, file_path: str) -> dict:
        """Check if a drawing file exists."""
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

    # ==================================================================
    # Preferences / settings inspection (registrymodifications.xcu)
    # ==================================================================

    def _load_registry_modifications(self) -> tuple[ET.Element | None, str | None]:
        """Load the user's registrymodifications.xcu file into an ElementTree root."""
        candidates = [
            Path.home() / ".config" / "libreoffice" / "4" / "user" / "registrymodifications.xcu",
            Path.home() / ".config" / "libreoffice" / "user" / "registrymodifications.xcu",
        ]
        for p in candidates:
            if p.exists():
                try:
                    tree = ET.parse(str(p))
                    return tree.getroot(), None
                except Exception as e:
                    return None, f"Failed to parse {p}: {e}"
        return None, "registrymodifications.xcu not found"

    def get_draw_prefs(self) -> dict:
        """Parse registrymodifications.xcu and return a dict of known Draw preferences.

        Recognised keys (all values are raw strings from the XML or None):

          - measurement_unit_draw  — Office.Draw/Layout/Other/MeasureUnit/Metric (enum: 0=cm, 1=mm, 2=inch,
            3=point, 4=pica, 8=cm, ...). Draw shares the UnitConversion Metric enum with Impress.
          - default_tab_stop_draw  — Office.Draw/Layout/Other/TabStop (1/100 mm)
          - default_save_filter_draw — Office.Common/Save/Document/Draw
          - autosave_enabled        — Office.Common/Save/Document/AutoSave
          - autosave_interval       — Office.Common/Save/Document/AutoSaveTimeIntervall
          - backup_enabled          — Office.Common/Save/Document/CreateBackup
          - grid_visible_draw       — Office.Draw/Snap/Grid/Options/VisibleGrid
          - snap_to_grid_draw       — Office.Draw/Snap/Grid/Options/SnapToGrid
          - grid_resolution_x       — Office.Draw/Snap/Grid/Resolution/XAxis
          - grid_resolution_y       — Office.Draw/Snap/Grid/Resolution/YAxis
          - grid_subdivision_x      — Office.Draw/Snap/Grid/Subdivision/XAxis
          - grid_subdivision_y      — Office.Draw/Snap/Grid/Subdivision/YAxis
          - snap_to_page_margins    — Office.Draw/Snap/Object/SnapToPageMargins
          - snap_to_object_frame    — Office.Draw/Snap/Object/SnapToObjectFrame
          - raw: list of (path, prop, value) triples.
        """
        root, err = self._load_registry_modifications()
        if err:
            return {"error": err}
        ns = "{http://openoffice.org/2001/registry}"
        result: dict = {
            "measurement_unit_draw": None,
            "default_tab_stop_draw": None,
            "default_save_filter_draw": None,
            "autosave_enabled": None,
            "autosave_interval": None,
            "backup_enabled": None,
            "grid_visible_draw": None,
            "snap_to_grid_draw": None,
            "grid_resolution_x": None,
            "grid_resolution_y": None,
            "grid_subdivision_x": None,
            "grid_subdivision_y": None,
            "snap_to_page_margins": None,
            "snap_to_object_frame": None,
            "raw": [],
        }
        for item in root.findall(f"{ns}item"):
            path = item.get(f"{ns}path", "")
            # Walk prop + value directly
            for prop in item.findall(f"{ns}prop"):
                prop_name = prop.get(f"{ns}name", "")
                value_elem = prop.find(f"{ns}value")
                value_text = None
                if value_elem is not None:
                    value_text = "".join(value_elem.itertext()).strip()
                result["raw"].append({"path": path, "prop": prop_name, "value": value_text})
                # Measurement unit — Draw specific
                if "Draw/Layout/Other/MeasureUnit" in path and prop_name == "Metric":
                    result["measurement_unit_draw"] = value_text
                # Default tab stop for Draw
                if "Draw/Layout/Other" in path and prop_name == "TabStop":
                    result["default_tab_stop_draw"] = value_text
                # Default save filter for Draw
                if "Save/Document" in path and prop_name == "Draw":
                    result["default_save_filter_draw"] = value_text
                # Autosave
                if "Save/Document" in path and prop_name == "AutoSave":
                    result["autosave_enabled"] = value_text
                if "Save/Document" in path and prop_name == "AutoSaveTimeIntervall":
                    result["autosave_interval"] = value_text
                if "Save/Document" in path and prop_name == "CreateBackup":
                    result["backup_enabled"] = value_text
                # Grid / snap (Draw-scoped)
                if "Draw/Snap/Grid/Options" in path and prop_name == "VisibleGrid":
                    result["grid_visible_draw"] = value_text
                if "Draw/Snap/Grid/Options" in path and prop_name == "SnapToGrid":
                    result["snap_to_grid_draw"] = value_text
                if "Draw/Snap/Grid/Resolution/XAxis" in path and prop_name == "Metric":
                    result["grid_resolution_x"] = value_text
                if "Draw/Snap/Grid/Resolution/YAxis" in path and prop_name == "Metric":
                    result["grid_resolution_y"] = value_text
                if "Draw/Snap/Grid/Subdivision/XAxis" in path and prop_name == "Count":
                    result["grid_subdivision_x"] = value_text
                if "Draw/Snap/Grid/Subdivision/YAxis" in path and prop_name == "Count":
                    result["grid_subdivision_y"] = value_text
                if "Draw/Snap/Object" in path and prop_name == "SnapToPageMargins":
                    result["snap_to_page_margins"] = value_text
                if "Draw/Snap/Object" in path and prop_name == "SnapToObjectFrame":
                    result["snap_to_object_frame"] = value_text
        return result

    def check_draw_pref(self, key: str, expected: str) -> dict:
        """Check a Draw preference by well-known key. Returns {"match": bool, ...}."""
        prefs = self.get_draw_prefs()
        if "error" in prefs:
            return {"match": False, **prefs}
        actual = prefs.get(key)
        match = False
        if actual is not None:
            a = str(actual).strip().lower()
            e = str(expected).strip().lower()
            if key in ("default_save_filter_draw",):
                # Accept substring (case-insensitive)
                match = e in a
            else:
                # Numeric-aware comparison
                try:
                    match = int(a) == int(e)
                except Exception:
                    match = a == e
        return {"match": match, "key": key, "expected": expected, "actual": actual}

    def check_registry_key(self, path_substring: str, prop_name: str, expected: str) -> dict:
        """Generic: find an item where `path_substring` is in its path and `prop_name` matches,
        then compare its value to `expected` (case-insensitive substring or int match)."""
        prefs = self.get_draw_prefs()
        if "error" in prefs:
            return {"match": False, **prefs}
        for row in prefs.get("raw", []):
            if path_substring in (row.get("path") or "") and row.get("prop") == prop_name:
                actual = row.get("value")
                a = str(actual).strip().lower() if actual is not None else ""
                e = str(expected).strip().lower()
                try:
                    match = int(a) == int(e)
                except Exception:
                    match = e in a or a == e
                return {"match": match, "path_substring": path_substring,
                        "prop": prop_name, "expected": expected, "actual": actual}
        return {"match": False, "path_substring": path_substring,
                "prop": prop_name, "expected": expected, "actual": None,
                "note": "no matching registry item found"}

    # ==================================================================
    # ODF page-level inspection (offline): size, margins, background, names
    # ==================================================================

    @staticmethod
    def _convert_odf_length_to_cm(value: str | None) -> float | None:
        if not value:
            return None
        value = value.strip()
        try:
            if value.endswith("cm"):
                return float(value[:-2])
            if value.endswith("mm"):
                return float(value[:-2]) / 10.0
            if value.endswith("in"):
                return float(value[:-2]) * 2.54
            if value.endswith("pt"):
                return float(value[:-2]) * 2.54 / 72.0
            return float(value)  # unitless -> cm assumed
        except ValueError:
            return None

    def parse_file_page_properties(self, file_path: str | None = None) -> dict:
        """Parse all pages' name, size, margins and background-fill from styles.xml + content.xml.

        Returns: {"pages": [{"index":0,"name":"Cover","width_cm":42.0,"height_cm":29.7,
                              "margin_top_cm":2.0,"margin_left_cm":2.0,"margin_right_cm":2.0,
                              "margin_bottom_cm":2.0,"background_fill":"#FFFFCC"}], ...}
        """
        if file_path is None:
            file_path = _find_odg_file()
        if file_path is None:
            return {"error": "No ODG file found. Provide file_path."}
        if not os.path.exists(file_path):
            return {"error": f"File not found: {file_path}"}

        try:
            with zipfile.ZipFile(file_path, "r") as z:
                # content.xml — gives draw:page elements, and references master-page-name + style-name
                with z.open("content.xml") as f:
                    content_root = ET.parse(f).getroot()
                # styles.xml — gives master-page -> page-layout-name, and page-layout-properties
                styles_root = None
                try:
                    with z.open("styles.xml") as f:
                        styles_root = ET.parse(f).getroot()
                except KeyError:
                    pass
        except zipfile.BadZipFile:
            return {"error": f"Not a valid ODG/ZIP file: {file_path}"}

        # Build maps from styles.xml
        layout_props: dict[str, dict] = {}  # style:name -> {width_cm, height_cm, margin_*_cm}
        master_to_layout: dict[str, str] = {}  # master-page-name -> page-layout-name
        master_to_draw_style: dict[str, str] = {}  # master-page-name -> draw:style-name
        draw_style_fill: dict[str, dict] = {}  # draw:style-name -> {fill_style, fill_color}

        def _walk_for_styles(root):
            if root is None:
                return
            for pl in root.iter(f"{{{ODF_NS['style']}}}page-layout"):
                name = pl.get(f"{{{ODF_NS['style']}}}name")
                props = pl.find(f"{{{ODF_NS['style']}}}page-layout-properties")
                if name is None or props is None:
                    continue
                layout_props[name] = {
                    "width_cm": self._convert_odf_length_to_cm(props.get(f"{{{ODF_NS['fo']}}}page-width")),
                    "height_cm": self._convert_odf_length_to_cm(props.get(f"{{{ODF_NS['fo']}}}page-height")),
                    "margin_top_cm": self._convert_odf_length_to_cm(props.get(f"{{{ODF_NS['fo']}}}margin-top")),
                    "margin_bottom_cm": self._convert_odf_length_to_cm(props.get(f"{{{ODF_NS['fo']}}}margin-bottom")),
                    "margin_left_cm": self._convert_odf_length_to_cm(props.get(f"{{{ODF_NS['fo']}}}margin-left")),
                    "margin_right_cm": self._convert_odf_length_to_cm(props.get(f"{{{ODF_NS['fo']}}}margin-right")),
                }
            for mp in root.iter(f"{{{ODF_NS['style']}}}master-page"):
                mp_name = mp.get(f"{{{ODF_NS['style']}}}name")
                layout_name = mp.get(f"{{{ODF_NS['style']}}}page-layout-name")
                draw_style = mp.get(f"{{{ODF_NS['draw']}}}style-name")
                if mp_name and layout_name:
                    master_to_layout[mp_name] = layout_name
                if mp_name and draw_style:
                    master_to_draw_style[mp_name] = draw_style
            # draw:style-name -> fill properties (drawing-page style family)
            for s in root.iter(f"{{{ODF_NS['style']}}}style"):
                sname = s.get(f"{{{ODF_NS['style']}}}name")
                family = s.get(f"{{{ODF_NS['style']}}}family")
                if sname is None:
                    continue
                # drawing-page background lives on style:drawing-page-properties
                props = s.find(f"{{{ODF_NS['style']}}}drawing-page-properties")
                if props is None:
                    props = s.find(f"{{{ODF_NS['style']}}}graphic-properties")
                if props is None:
                    continue
                fill_style = props.get(f"{{{ODF_NS['draw']}}}fill")
                fill_color = props.get(f"{{{ODF_NS['draw']}}}fill-color")
                if fill_style or fill_color:
                    draw_style_fill[sname] = {
                        "fill_style": fill_style,
                        "fill_color": (fill_color.upper() if fill_color else None),
                    }

        _walk_for_styles(styles_root)
        _walk_for_styles(content_root)

        body = content_root.find("office:body", ODF_NS)
        drawing = body.find("office:drawing", ODF_NS) if body is not None else None
        if drawing is None:
            return {"error": "No drawing content found."}

        pages_out = []
        for i, page in enumerate(drawing.findall("draw:page", ODF_NS)):
            name = page.get(f"{{{ODF_NS['draw']}}}name", f"page{i+1}")
            master_name = page.get(f"{{{ODF_NS['draw']}}}master-page-name")
            # Page's own draw:style-name overrides master-page draw-style
            page_style = page.get(f"{{{ODF_NS['draw']}}}style-name")
            layout_name = master_to_layout.get(master_name) if master_name else None
            lp = layout_props.get(layout_name, {}) if layout_name else {}

            fill_info: dict = {}
            if page_style and page_style in draw_style_fill:
                fill_info = draw_style_fill[page_style]
            elif master_name and master_to_draw_style.get(master_name) in draw_style_fill:
                fill_info = draw_style_fill[master_to_draw_style[master_name]]

            pages_out.append({
                "index": i,
                "name": name,
                "master_page": master_name,
                "width_cm": lp.get("width_cm"),
                "height_cm": lp.get("height_cm"),
                "margin_top_cm": lp.get("margin_top_cm"),
                "margin_bottom_cm": lp.get("margin_bottom_cm"),
                "margin_left_cm": lp.get("margin_left_cm"),
                "margin_right_cm": lp.get("margin_right_cm"),
                "background_fill_style": fill_info.get("fill_style"),
                "background_fill_color": fill_info.get("fill_color"),
            })
        return {"pages": pages_out, "count": len(pages_out), "file": file_path}

    def check_page_property(self, page_index: int, key: str, expected: str,
                             tol_cm: float = 0.1, file_path: str | None = None) -> dict:
        """Check one property (name, width_cm, height_cm, margin_*_cm, background_fill_color)
        of the page at index `page_index` in the saved ODG at file_path.

        Numeric comparisons tolerate +/- tol_cm. Colors compare case-insensitively after stripping '#'.
        """
        info = self.parse_file_page_properties(file_path)
        if "error" in info:
            return {"match": False, **info}
        pages = info.get("pages", [])
        if page_index >= len(pages):
            return {"match": False, "error": f"page_index {page_index} out of range", "count": len(pages)}
        actual = pages[page_index].get(key)
        match = False
        if key in ("name", "background_fill_style", "master_page"):
            match = actual is not None and str(actual).lower() == str(expected).lower()
        elif key == "background_fill_color":
            a = (actual or "").lstrip("#").upper()
            e = str(expected).lstrip("#").upper()
            match = a == e
        else:
            try:
                match = abs(float(actual) - float(expected)) <= tol_cm
            except (TypeError, ValueError):
                match = False
        return {"match": match, "key": key, "index": page_index,
                "expected": expected, "actual": actual}

    # ==================================================================
    # Shape hyperlinks (ODF offline)
    # ==================================================================

    def parse_file_shape_hyperlinks(self, page_index: int, file_path: str | None = None) -> dict:
        """Return a list of hyperlinks on shapes/text of a given page in a saved ODG.

        Hyperlinks appear as <draw:a xlink:href="..."> wrappers or <text:a xlink:href="..."> runs.
        """
        if file_path is None:
            file_path = _find_odg_file()
        if file_path is None:
            return {"error": "No ODG file found. Provide file_path."}
        root, err = _parse_odg_content(file_path)
        if err:
            return {"error": err}
        body = root.find("office:body", ODF_NS)
        drawing = body.find("office:drawing", ODF_NS) if body is not None else None
        if drawing is None:
            return {"error": "No drawing content found."}
        pages = drawing.findall("draw:page", ODF_NS)
        if page_index >= len(pages):
            return {"error": f"Page index {page_index} out of range (have {len(pages)})"}
        page = pages[page_index]
        links = []
        href_attr = f"{{{ODF_NS['xlink']}}}href"
        for elem in page.iter():
            if href_attr in elem.attrib:
                href = elem.attrib[href_attr]
                text = _elem_all_text(elem).strip()
                links.append({"href": href, "text": text, "tag": elem.tag.split('}')[-1]})
        return {"index": page_index, "links": links, "count": len(links), "file": file_path}

    def check_shape_hyperlink(self, page_index: int, href_substring: str,
                              text_substring: str | None = None,
                              file_path: str | None = None) -> dict:
        """Check that page contains a hyperlink whose href contains `href_substring`
        and (optionally) whose visible text contains `text_substring`."""
        info = self.parse_file_shape_hyperlinks(page_index, file_path)
        if "error" in info:
            return {"exists": False, **info}
        for l in info.get("links", []):
            h_ok = href_substring.lower() in (l.get("href") or "").lower()
            t_ok = text_substring is None or text_substring.lower() in (l.get("text") or "").lower()
            if h_ok and t_ok:
                return {"exists": True, "index": page_index, "link": l}
        return {"exists": False, "index": page_index, "links_checked": info.get("count", 0),
                "all_links": info.get("links", [])}

    # ==================================================================
    # PDF inspection (stdlib-only parser for page count + outlines)
    # ==================================================================

    def parse_pdf_info(self, file_path: str) -> dict:
        """Return basic metadata for a PDF file: page count and outline/bookmark titles.

        Uses a small stdlib-only PDF parser. It decodes xref-visible object dictionaries and
        walks the /Outlines tree via /First and /Next pointers.
        """
        if not os.path.exists(file_path):
            return {"error": f"File not found: {file_path}"}
        try:
            with open(file_path, "rb") as fh:
                data = fh.read()
        except Exception as e:
            return {"error": f"Failed to open: {e}"}
        if not data.startswith(b"%PDF"):
            return {"error": "Not a PDF"}

        import re
        import zlib

        # Map obj_id -> bytes of its body (between "N G obj" and "endobj")
        obj_re = re.compile(rb"(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj\b", re.DOTALL)
        objects: dict[int, bytes] = {}
        for m in obj_re.finditer(data):
            oid = int(m.group(1))
            body = m.group(3)
            objects[oid] = body

        # Some PDFs put objects inside /ObjStm compressed streams (the "N first" stream dict
        # gives the list of contained obj ids). We decompress them and register their bodies.
        stream_re = re.compile(rb"(\d+)\s+\d+\s+obj\b(.*?)stream\s*?\n(.*?)\s*?endstream\b",
                               re.DOTALL)
        for m in stream_re.finditer(data):
            oid = int(m.group(1))
            header = m.group(2)
            stream_bytes = m.group(3)
            if b"/Type" not in header or b"/ObjStm" not in header:
                continue
            # Check filter
            filter_match = re.search(rb"/Filter\s*/FlateDecode", header)
            if not filter_match:
                continue
            try:
                decompressed = zlib.decompress(stream_bytes)
            except Exception:
                continue
            # N + First from header
            n_match = re.search(rb"/N\s+(\d+)", header)
            first_match = re.search(rb"/First\s+(\d+)", header)
            if not n_match or not first_match:
                continue
            n = int(n_match.group(1))
            first = int(first_match.group(1))
            header_part = decompressed[:first]
            body_part = decompressed[first:]
            # Header is N pairs of "objnum offset"
            nums = header_part.split()
            pairs: list[tuple[int, int]] = []
            for i in range(n):
                try:
                    onum = int(nums[i * 2])
                    off = int(nums[i * 2 + 1])
                    pairs.append((onum, off))
                except (IndexError, ValueError):
                    break
            # Each contained obj's body runs from its offset to the next offset
            for idx, (onum, off) in enumerate(pairs):
                end = pairs[idx + 1][1] if idx + 1 < len(pairs) else len(body_part)
                objects[onum] = body_part[off:end]

        def ref_of(body: bytes, key: bytes) -> int | None:
            m = re.search(rb"/" + re.escape(key) + rb"\s+(\d+)\s+(\d+)\s+R", body)
            return int(m.group(1)) if m else None

        def int_of(body: bytes, key: bytes) -> int | None:
            m = re.search(rb"/" + re.escape(key) + rb"\s+(-?\d+)\b", body)
            return int(m.group(1)) if m else None

        # Find the trailer Root reference
        root_id = None
        trailer_match = re.search(rb"trailer\s*<<(.+?)>>", data, re.DOTALL)
        if trailer_match:
            root_id = ref_of(trailer_match.group(1), b"Root")
        # Fallback — find /Type /Catalog
        if root_id is None:
            for oid, body in objects.items():
                if re.search(rb"/Type\s*/Catalog", body):
                    root_id = oid
                    break
        if root_id is None:
            return {"error": "Could not locate /Catalog"}

        catalog = objects.get(root_id, b"")

        # Page count via /Pages -> /Count
        page_count = None
        pages_id = ref_of(catalog, b"Pages")
        if pages_id is not None:
            pages_body = objects.get(pages_id, b"")
            page_count = int_of(pages_body, b"Count")

        # Outline walk
        outlines_id = ref_of(catalog, b"Outlines")
        titles: list[str] = []

        def _decode_pdf_string(s: bytes) -> str:
            # UTF-16BE BOM
            if s.startswith(b"\xfe\xff"):
                try:
                    return s[2:].decode("utf-16-be", errors="replace")
                except Exception:
                    return s.decode("latin-1", errors="replace")
            # PDFDocEncoding / latin-1 approximation
            try:
                return s.decode("latin-1")
            except Exception:
                return s.decode("utf-8", errors="replace")

        def _extract_title(body: bytes) -> str | None:
            # Title may be either a literal string (..) or a hex string <..>
            m = re.search(rb"/Title\s*\(((?:\\\)|[^)])*)\)", body, re.DOTALL)
            if m:
                raw = m.group(1)
                # Unescape common PDF escapes
                raw = raw.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
                return _decode_pdf_string(raw)
            m = re.search(rb"/Title\s*<([0-9A-Fa-f\s]+)>", body)
            if m:
                hexs = m.group(1).decode("ascii").replace(" ", "").replace("\n", "")
                try:
                    return _decode_pdf_string(bytes.fromhex(hexs))
                except Exception:
                    return None
            return None

        if outlines_id is not None:
            visited = set()
            # Start with /First of the outlines root
            first_id = ref_of(objects.get(outlines_id, b""), b"First")
            stack = [first_id] if first_id else []
            while stack:
                oid = stack.pop(0)
                if oid is None or oid in visited:
                    continue
                visited.add(oid)
                body = objects.get(oid, b"")
                title = _extract_title(body)
                if title is not None:
                    titles.append(title)
                # Walk children depth-first-ish
                child = ref_of(body, b"First")
                if child:
                    stack.insert(0, child)
                sibling = ref_of(body, b"Next")
                if sibling:
                    stack.append(sibling)

        return {
            "file": file_path,
            "size": os.path.getsize(file_path),
            "page_count": page_count,
            "bookmarks": titles,
            "bookmark_count": len(titles),
        }

    def check_pdf_bookmark(self, file_path: str, title_substring: str) -> dict:
        """Check that the PDF outline contains a bookmark title containing `title_substring`."""
        info = self.parse_pdf_info(file_path)
        if "error" in info:
            return {"exists": False, **info}
        for t in info.get("bookmarks", []):
            if title_substring.lower() in str(t).lower():
                return {"exists": True, "title": t, "all_bookmarks": info["bookmarks"]}
        return {"exists": False, "expected_substring": title_substring,
                "all_bookmarks": info.get("bookmarks", [])}

    def check_pdf_page_count(self, file_path: str, expected: int) -> dict:
        """Check the page count of a PDF."""
        info = self.parse_pdf_info(file_path)
        if "error" in info:
            return {"match": False, **info}
        actual = info.get("page_count")
        return {"match": actual == int(expected), "expected": int(expected), "actual": actual}


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

COMMANDS = {
    # UNO live state
    "pages": ("List all pages", lambda v, args: v.get_pages()),
    "page-shapes": ("Get shapes on page", lambda v, args: v.get_page_shapes(
        int(args[0]) if args else 0)),
    "page-text": ("Get text on page", lambda v, args: v.get_page_text(
        int(args[0]) if args else 0)),
    "page-size": ("Get page dimensions", lambda v, args: v.get_page_size()),
    "doc-info": ("Get document info", lambda v, args: v.get_document_info()),
    "layers": ("List layers", lambda v, args: v.get_layers()),
    "connectors": ("List connectors on page", lambda v, args: v.get_connectors(
        int(args[0]) if args else 0)),

    # ODF file parsing (offline)
    "parse-pages": ("List pages from ODG", lambda v, args: v.parse_file_pages(
        args[0] if args else None)),
    "parse-page-text": ("Get page text from ODG", lambda v, args: v.parse_file_page_text(
        int(args[0]) if args else 0,
        args[1] if len(args) > 1 else None)),

    # Composite checks
    "check-page-count": ("Check page count", lambda v, args: v.check_page_count(int(args[0]))),
    "check-shape-count": ("Check shape count", lambda v, args: v.check_shape_count(
        int(args[0]), int(args[1]))),
    "check-shape-exists": ("Check shape exists", lambda v, args: v.check_shape_exists(
        int(args[0]), shape_type=args[1] if len(args) > 1 else None)),
    "check-page-contains": ("Check page has text", lambda v, args: v.check_page_contains_text(
        int(args[0]), args[1])),
    "check-connector-exists": ("Check connector exists", lambda v, args: v.check_connector_exists(
        int(args[0]),
        start_name=args[1] if len(args) > 1 else None,
        end_name=args[2] if len(args) > 2 else None)),
    "check-layer-exists": ("Check layer exists", lambda v, args: v.check_layer_exists(args[0])),
    "check-file-exists": ("Check file exists", lambda v, args: v.check_file_exists(args[0])),
    "check-file-saved": ("Check document saved", lambda v, args: v.check_file_saved()),

    # Preferences / settings (reads registrymodifications.xcu)
    "draw-prefs": ("Get Draw user preferences from registrymodifications.xcu",
        lambda v, args: v.get_draw_prefs()),
    "check-draw-pref": ("Check Draw preference key/value",
        lambda v, args: v.check_draw_pref(args[0], args[1])),
    "check-registry-key": ("Check arbitrary registry <path_substring> <prop> <expected>",
        lambda v, args: v.check_registry_key(args[0], args[1], args[2])),

    # Page properties (offline ODF parsing)
    "parse-page-props": ("Parse per-page name/size/margins/background from ODG",
        lambda v, args: v.parse_file_page_properties(args[0] if args else None)),
    "check-page-property": ("Check page property: <index> <key> <expected> [file_path]",
        lambda v, args: v.check_page_property(int(args[0]), args[1], args[2],
            file_path=args[3] if len(args) > 3 else None)),

    # Shape hyperlinks (offline ODF parsing)
    "parse-shape-hyperlinks": ("Parse hyperlinks on shapes of a page: <index> [file_path]",
        lambda v, args: v.parse_file_shape_hyperlinks(int(args[0]),
            args[1] if len(args) > 1 else None)),
    "check-shape-hyperlink": ("Check a hyperlink exists on page: <index> <href_substring> [text] [file_path]",
        lambda v, args: v.check_shape_hyperlink(int(args[0]), args[1],
            text_substring=args[2] if len(args) > 2 else None,
            file_path=args[3] if len(args) > 3 else None)),

    # PDF inspection
    "parse-pdf-info": ("Parse PDF for page_count and outline/bookmarks: <file_path>",
        lambda v, args: v.parse_pdf_info(args[0])),
    "check-pdf-bookmark": ("Check PDF outline contains bookmark: <file_path> <title_substring>",
        lambda v, args: v.check_pdf_bookmark(args[0], args[1])),
    "check-pdf-page-count": ("Check PDF page count: <file_path> <expected>",
        lambda v, args: v.check_pdf_page_count(args[0], int(args[1]))),
}


def _print_usage():
    print("LibreOffice Draw Verifier — query drawing state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nUNO endpoints require LibreOffice running with --accept on port {UNO_PORT}")
    print("ODF parse-* endpoints work on saved .odg files without UNO")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = LibreOfficeDrawVerifier()
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
