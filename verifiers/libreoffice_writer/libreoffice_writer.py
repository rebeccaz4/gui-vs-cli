"""
LibreOffice Writer Verifier — programmatic state inspection for documents in E2B sandbox.

Verification channels (in order of preference):
  1. UNO API — live inspection of open documents via Python-UNO bridge (text, paragraphs, formatting)
  2. ODF file parsing — .odt files are ZIP archives; parse content.xml / styles.xml directly
  3. File-based checks — file existence, modification time, size

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/libreoffice_writer.py paragraphs")
    sandbox.commands.run("python3 /home/user/verifiers/libreoffice_writer.py text")
    sandbox.commands.run("python3 /home/user/verifiers/libreoffice_writer.py check-text-contains Hello")

Usage from Python (inside sandbox or via E2B):
    from verifiers.libreoffice_writer import LibreOfficeWriterVerifier
    v = LibreOfficeWriterVerifier()
    text = v.get_text()
    paras = v.get_paragraphs()

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - LibreOffice launched with:
    soffice --writer --accept="socket,host=localhost,port=2002;urp;" --norestore
  - For ODF parsing: only stdlib (zipfile, xml.etree)
"""

import json
import os
import re
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
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "number": "urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
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
    """Get the current Writer document via UNO."""
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

def _parse_odt_content(file_path: str) -> tuple[ET.Element | None, str | None]:
    """Extract and parse content.xml from an .odt file."""
    if not os.path.exists(file_path):
        return None, f"File not found: {file_path}"
    try:
        with zipfile.ZipFile(file_path, "r") as z:
            with z.open("content.xml") as f:
                tree = ET.parse(f)
                return tree.getroot(), None
    except zipfile.BadZipFile:
        return None, f"Not a valid ODT/ZIP file: {file_path}"
    except KeyError:
        return None, f"No content.xml found in: {file_path}"


def _parse_odt_styles(file_path: str) -> tuple[ET.Element | None, str | None]:
    """Extract and parse styles.xml from an .odt file."""
    if not os.path.exists(file_path):
        return None, f"File not found: {file_path}"
    try:
        with zipfile.ZipFile(file_path, "r") as z:
            with z.open("styles.xml") as f:
                tree = ET.parse(f)
                return tree.getroot(), None
    except (zipfile.BadZipFile, KeyError) as e:
        return None, f"Cannot read styles.xml: {e}"


def _elem_text(elem) -> str:
    """Recursively extract all text from an ODF element."""
    return "".join(elem.itertext())


def _normalize_text(text: str | None) -> str:
    """Normalize whitespace for robust text comparisons."""
    return re.sub(r"\s+", " ", text or "").strip()


def _extract_heading_level(style_name: str | None) -> int | None:
    """Extract a heading level from common Writer style names."""
    if not style_name:
        return None
    normalized = style_name.lower().replace("_20_", " ")
    if "heading" not in normalized:
        return None
    match = re.search(r"(\d+)", normalized)
    if not match:
        return None
    return int(match.group(1))


def _find_odt_file() -> str | None:
    """Try to find a recently saved .odt file in common locations."""
    search_dirs = [
        Path.home(),
        Path.home() / "Documents",
        Path.home() / "Desktop",
        Path("/tmp"),
    ]
    odt_files = []
    for d in search_dirs:
        if d.exists():
            for f in d.glob("*.odt"):
                odt_files.append(f)
            for f in d.glob("*.docx"):
                odt_files.append(f)
    if odt_files:
        return str(max(odt_files, key=lambda f: f.stat().st_mtime))
    return None


# ---------------------------------------------------------------------------
# LibreOfficeWriterVerifier class
# ---------------------------------------------------------------------------

class LibreOfficeWriterVerifier:
    """Stateless verifier — each method call is independent.

    Methods try UNO first (live state), then fall back to ODF file parsing.
    """

    # === UNO: Live document state ===

    def get_text(self) -> dict:
        """Get the full text content of the document.

        Example return:
        {"text": "Hello World\\nSecond paragraph", "length": 30}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            text_obj = doc.getText()
            full_text = text_obj.getString()
            return {"text": full_text, "length": len(full_text)}
        except Exception as e:
            return {"error": f"Failed to get text: {e}"}

    def get_paragraphs(self, max_count: int = 100) -> dict:
        """List paragraphs with their text and style.

        Example return:
        {"paragraphs": [{"index": 0, "text": "Title", "style": "Heading 1"}, ...], "count": 5}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            text_obj = doc.getText()
            enum = text_obj.createEnumeration()
            paragraphs = []
            idx = 0
            while enum.hasMoreElements() and idx < max_count:
                para = enum.nextElement()
                # Skip text tables — they are enumerated among text content
                if para.supportsService("com.sun.star.text.TextTable"):
                    continue
                para_text = para.getString()
                style = para.getPropertyValue("ParaStyleName")
                entry = {
                    "index": idx,
                    "text": para_text,
                    "style": style,
                }
                try:
                    outline_level = int(para.getPropertyValue("OutlineLevel"))
                except Exception:
                    outline_level = 0
                actual_level = outline_level if outline_level > 0 else _extract_heading_level(style)
                if actual_level is not None:
                    entry["heading"] = True
                    entry["level"] = actual_level
                paragraphs.append(entry)
                idx += 1
            return {"paragraphs": paragraphs, "count": len(paragraphs)}
        except Exception as e:
            return {"error": f"Failed to get paragraphs: {e}"}

    def get_paragraph_format(self, para_index: int = 0) -> dict:
        """Get formatting of a specific paragraph (alignment, spacing, style).

        Example:
            v.get_paragraph_format(0)
            => {"index": 0, "style": "Heading 1", "alignment": "center", "font_name": "Arial", ...}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            text_obj = doc.getText()
            enum = text_obj.createEnumeration()
            idx = 0
            while enum.hasMoreElements():
                para = enum.nextElement()
                if para.supportsService("com.sun.star.text.TextTable"):
                    continue
                if idx == para_index:
                    # Get paragraph-level properties
                    align_val = str(para.getPropertyValue("ParaAdjust")).upper()
                    if "LEFT" in align_val:
                        alignment = "left"
                    elif "RIGHT" in align_val:
                        alignment = "right"
                    elif "CENTER" in align_val:
                        alignment = "center"
                    elif "BLOCK" in align_val:
                        alignment = "justified"
                    else:
                        alignment = align_val.lower()

                    # Get first text portion for character formatting
                    portions = para.createEnumeration()
                    bold = False
                    italic = False
                    font_name = ""
                    font_size = 0.0
                    font_color = None
                    if portions.hasMoreElements():
                        portion = portions.nextElement()
                        bold = portion.getPropertyValue("CharWeight") > 100
                        italic = "NONE" not in str(portion.getPropertyValue("CharPosture"))
                        font_name = portion.getPropertyValue("CharFontName")
                        font_size = portion.getPropertyValue("CharHeight")
                        color_int = portion.getPropertyValue("CharColor")
                        font_color = f"#{color_int:06X}" if color_int else None

                    return {
                        "index": para_index,
                        "text": para.getString(),
                        "style": para.getPropertyValue("ParaStyleName"),
                        "alignment": alignment,
                        "bold": bold,
                        "italic": italic,
                        "font_name": font_name,
                        "font_size": font_size,
                        "font_color": font_color,
                    }
                idx += 1
            return {"error": f"Paragraph index {para_index} out of range (have {idx} paragraphs)"}
        except Exception as e:
            return {"error": f"Failed to get paragraph format: {e}"}

    def get_document_info(self) -> dict:
        """Get document metadata (file path, title, page count, word count).

        Example:
            v.get_document_info()
            => {"path": "file:///home/user/test.odt", "title": "test.odt", "page_count": 3, "word_count": 150}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            word_count = doc.getPropertyValue("WordCount") if doc.supportsService("com.sun.star.document.DocumentProperties") else None
            # Try to get word count from document statistics
            try:
                word_count = doc.WordCount
            except Exception:
                pass
            return {
                "path": doc.getURL(),
                "title": doc.getTitle(),
                "page_count": doc.getCurrentController().getPropertyValue("PageCount") if doc.getCurrentController() else None,
                "word_count": word_count,
                "modified": doc.isModified(),
            }
        except Exception as e:
            return {"error": f"Failed to get doc info: {e}"}

    def get_page_count(self) -> dict:
        """Get the number of pages in the document.

        Example:
            v.get_page_count()
            => {"page_count": 3}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            controller = doc.getCurrentController()
            page_count = controller.getPropertyValue("PageCount")
            return {"page_count": page_count}
        except Exception as e:
            return {"error": f"Failed to get page count: {e}"}

    def get_tables(self) -> dict:
        """List all tables in the document.

        Example:
            v.get_tables()
            => {"tables": [{"name": "Table1", "rows": 3, "cols": 4}], "count": 1}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            tables_obj = doc.getTextTables()
            tables = []
            for i in range(tables_obj.getCount()):
                table = tables_obj.getByIndex(i)
                tables.append({
                    "name": table.getName(),
                    "rows": table.getRows().getCount(),
                    "cols": table.getColumns().getCount(),
                })
            return {"tables": tables, "count": len(tables)}
        except Exception as e:
            return {"error": f"Failed to get tables: {e}"}

    def get_table_data(self, table_name: str | None = None, table_index: int = 0) -> dict:
        """Get cell data from a table.

        Example:
            v.get_table_data("Table1")
            => {"name": "Table1", "data": [["Name", "Score"], ["Alice", "90"]], "rows": 2, "cols": 2}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            tables_obj = doc.getTextTables()
            if tables_obj.getCount() == 0:
                return {"error": "No tables in document."}

            if table_name:
                if not tables_obj.hasByName(table_name):
                    return {"error": f"Table '{table_name}' not found."}
                table = tables_obj.getByName(table_name)
            else:
                if table_index >= tables_obj.getCount():
                    return {"error": f"Table index {table_index} out of range (have {tables_obj.getCount()})."}
                table = tables_obj.getByIndex(table_index)

            rows = table.getRows().getCount()
            cols = table.getColumns().getCount()
            data = []
            for r in range(rows):
                row_data = []
                for c in range(cols):
                    cell_name = table.getCellByPosition(c, r).getCellName() if hasattr(table.getCellByPosition(c, r), 'getCellName') else ""
                    cell = table.getCellByPosition(c, r)
                    cell_text = cell.getString()
                    val = cell.getValue()
                    if val != 0 or cell_text == "0":
                        row_data.append(val if val != int(val) else int(val))
                    else:
                        row_data.append(cell_text)
                data.append(row_data)

            return {
                "name": table.getName(),
                "data": data,
                "rows": rows,
                "cols": cols,
            }
        except Exception as e:
            return {"error": f"Failed to get table data: {e}"}

    def get_images(self) -> dict:
        """List all images/graphic objects in the document.

        Example:
            v.get_images()
            => {"images": [{"name": "Image1", "width": 1000, "height": 800}], "count": 1}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            graphics = doc.getGraphicObjects()
            images = []
            for i in range(graphics.getCount()):
                img = graphics.getByIndex(i)
                size = img.getPropertyValue("Size")
                images.append({
                    "name": img.getName(),
                    "width": size.Width,
                    "height": size.Height,
                })
            return {"images": images, "count": len(images)}
        except Exception as e:
            return {"error": f"Failed to get images: {e}"}

    def get_page_style(self, style_name: str = "Standard") -> dict:
        """Get page style properties (margins, orientation, size).

        Example:
            v.get_page_style()
            => {"name": "Standard", "width": 21000, "height": 29700, "orientation": "portrait", ...}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            page_styles = doc.getStyleFamilies().getByName("PageStyles")
            if not page_styles.hasByName(style_name):
                return {"error": f"Page style '{style_name}' not found."}
            ps = page_styles.getByName(style_name)
            is_landscape = str(ps.getPropertyValue("IsLandscape"))
            return {
                "name": style_name,
                "width": ps.getPropertyValue("Width"),
                "height": ps.getPropertyValue("Height"),
                "orientation": "landscape" if "True" in is_landscape else "portrait",
                "margin_top": ps.getPropertyValue("TopMargin"),
                "margin_bottom": ps.getPropertyValue("BottomMargin"),
                "margin_left": ps.getPropertyValue("LeftMargin"),
                "margin_right": ps.getPropertyValue("RightMargin"),
            }
        except Exception as e:
            return {"error": f"Failed to get page style: {e}"}

    def search_text(self, search_string: str, regex: bool = False) -> dict:
        """Search for text in the document and return match locations.

        Example:
            v.search_text("Hello")
            => {"found": true, "count": 2, "matches": [{"text": "Hello", "para_index": 0}, ...]}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            search = doc.createSearchDescriptor()
            search.SearchRegularExpression = regex
            search.SearchString = search_string
            search.SearchWords = False

            results = doc.findAll(search)
            if results is None or results.getCount() == 0:
                return {"found": False, "count": 0, "matches": []}

            matches = []
            for i in range(min(results.getCount(), 50)):
                result = results.getByIndex(i)
                matches.append({
                    "text": result.getString(),
                    "index": i,
                })
            return {"found": True, "count": results.getCount(), "matches": matches}
        except Exception as e:
            return {"error": f"Search failed: {e}"}

    def get_bookmarks(self) -> dict:
        """List all bookmarks in the document.

        Example:
            v.get_bookmarks()
            => {"bookmarks": ["bookmark1", "bookmark2"], "count": 2}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            bm_obj = doc.getBookmarks()
            names = [bm_obj.getByIndex(i).getName() for i in range(bm_obj.getCount())]
            return {"bookmarks": names, "count": len(names)}
        except Exception as e:
            return {"error": f"Failed to get bookmarks: {e}"}

    def get_headers_footers(self) -> dict:
        """Get header and footer text from the Standard page style.

        Example:
            v.get_headers_footers()
            => {"header_left": "", "header_center": "My Document", ...}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            page_styles = doc.getStyleFamilies().getByName("PageStyles")
            ps = page_styles.getByName("Standard")

            def _get_hf_text(prop_name):
                try:
                    hf = ps.getPropertyValue(prop_name)
                    if hf is None:
                        return ""
                    text = hf.getText()
                    return text.getString() if text else ""
                except Exception:
                    return ""

            return {
                "header_on": ps.getPropertyValue("HeaderIsOn"),
                "footer_on": ps.getPropertyValue("FooterIsOn"),
                "header_text": _get_hf_text("HeaderText"),
                "header_text_left": _get_hf_text("HeaderTextLeft"),
                "header_text_right": _get_hf_text("HeaderTextRight"),
                "footer_text": _get_hf_text("FooterText"),
                "footer_text_left": _get_hf_text("FooterTextLeft"),
                "footer_text_right": _get_hf_text("FooterTextRight"),
            }
        except Exception as e:
            return {"error": f"Failed to get headers/footers: {e}"}

    # === ODF file parsing: Offline verification ===

    def parse_file_text(self, file_path: str | None = None) -> dict:
        """Extract all text from an ODT file (no UNO needed).

        Example:
            v.parse_file_text("/home/user/test.odt")
            => {"text": "Hello World\\nSecond paragraph", "length": 30}
        """
        if file_path is None:
            file_path = _find_odt_file()
        if file_path is None:
            return {"error": "No ODT file found. Provide file_path."}

        root, err = _parse_odt_content(file_path)
        if err:
            return {"error": err}

        body = root.find("office:body", ODF_NS)
        text_elem = body.find("office:text", ODF_NS) if body is not None else None
        if text_elem is None:
            return {"error": "No text content found in file."}

        paragraphs = []
        for p in text_elem.findall("text:p", ODF_NS):
            paragraphs.append(_elem_text(p))
        for p in text_elem.findall("text:h", ODF_NS):
            paragraphs.append(_elem_text(p))

        full_text = "\n".join(paragraphs)
        return {"text": full_text, "length": len(full_text), "file": file_path}

    def parse_file_paragraphs(self, file_path: str | None = None) -> dict:
        """List paragraphs from an ODT file with style names (no UNO needed).

        Example:
            v.parse_file_paragraphs("/home/user/test.odt")
            => {"paragraphs": [{"index": 0, "text": "Title", "style": "Heading_20_1"}], "count": 5}
        """
        if file_path is None:
            file_path = _find_odt_file()
        if file_path is None:
            return {"error": "No ODT file found. Provide file_path."}

        root, err = _parse_odt_content(file_path)
        if err:
            return {"error": err}

        body = root.find("office:body", ODF_NS)
        text_elem = body.find("office:text", ODF_NS) if body is not None else None
        if text_elem is None:
            return {"error": "No text content found."}

        paragraphs = []
        idx = 0
        for child in text_elem:
            tag = child.tag
            if tag == f"{{{ODF_NS['text']}}}p" or tag == f"{{{ODF_NS['text']}}}h":
                style = child.get(f"{{{ODF_NS['text']}}}style-name", "")
                text = _elem_text(child)
                is_heading = tag.endswith("}h")
                outline_level = child.get(f"{{{ODF_NS['text']}}}outline-level") if is_heading else None
                entry = {"index": idx, "text": text, "style": style}
                if is_heading:
                    entry["heading"] = True
                    if outline_level:
                        entry["level"] = int(outline_level)
                paragraphs.append(entry)
                idx += 1

        return {"paragraphs": paragraphs, "count": len(paragraphs), "file": file_path}

    def parse_file_tables(self, file_path: str | None = None) -> dict:
        """List tables from an ODT file (no UNO needed).

        Example:
            v.parse_file_tables("/home/user/test.odt")
            => {"tables": [{"name": "Table1", "rows": 3, "cols": 2, "data": [...]}], "count": 1}
        """
        if file_path is None:
            file_path = _find_odt_file()
        if file_path is None:
            return {"error": "No ODT file found. Provide file_path."}

        root, err = _parse_odt_content(file_path)
        if err:
            return {"error": err}

        body = root.find("office:body", ODF_NS)
        text_elem = body.find("office:text", ODF_NS) if body is not None else None
        if text_elem is None:
            return {"error": "No text content found."}

        tables = []
        tbl_ns = ODF_NS["table"]
        for table_elem in text_elem.findall("table:table", ODF_NS):
            name = table_elem.get(f"{{{tbl_ns}}}name", "")
            data = []
            for row_elem in table_elem.findall("table:table-row", ODF_NS):
                # Handle table:number-rows-repeated on row level
                row_repeat = int(row_elem.get(f"{{{tbl_ns}}}number-rows-repeated", "1"))
                row_data = []
                for child in row_elem:
                    tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if tag == "table-cell":
                        cell_text = _elem_text(child)
                        col_repeat = int(child.get(f"{{{tbl_ns}}}number-columns-repeated", "1"))
                        for _ in range(col_repeat):
                            row_data.append(cell_text)
                    elif tag == "covered-table-cell":
                        # Merged/covered cells — empty placeholder
                        col_repeat = int(child.get(f"{{{tbl_ns}}}number-columns-repeated", "1"))
                        for _ in range(col_repeat):
                            row_data.append("")
                for _ in range(row_repeat):
                    data.append(list(row_data))
            tables.append({
                "name": name,
                "rows": len(data),
                "cols": len(data[0]) if data else 0,
                "data": data,
            })

        return {"tables": tables, "count": len(tables), "file": file_path}

    # === Composite checks (common RL verification patterns) ===

    def check_text_contains(self, text: str, case_sensitive: bool = False) -> dict:
        """Check if the document contains specific text.

        Example:
            v.check_text_contains("Hello World")
            => {"contains": true, "count": 1, "snippet": "...Hello World..."}
        """
        result = self.get_text()
        if "error" in result:
            return result

        doc_text = result["text"]
        if case_sensitive:
            found = text in doc_text
            count = doc_text.count(text)
        else:
            found = text.lower() in doc_text.lower()
            count = doc_text.lower().count(text.lower())

        snippet = None
        if found:
            search_text = doc_text if case_sensitive else doc_text.lower()
            search_needle = text if case_sensitive else text.lower()
            idx = search_text.index(search_needle)
            start = max(0, idx - 50)
            end = min(len(doc_text), idx + len(text) + 50)
            snippet = doc_text[start:end]

        return {"contains": found, "count": count, "snippet": snippet}

    def check_paragraph_count(self, expected: int) -> dict:
        """Check the number of paragraphs in the document.

        Example:
            v.check_paragraph_count(5)
            => {"match": true, "expected": 5, "actual": 5}
        """
        result = self.get_paragraphs()
        if "error" in result:
            return result
        actual = result["count"]
        return {"match": actual == expected, "expected": expected, "actual": actual}

    def check_paragraph_text(self, para_index: int, expected_text: str) -> dict:
        """Check if a paragraph has the expected text.

        Example:
            v.check_paragraph_text(0, "Hello World")
            => {"match": true, "index": 0, "expected": "Hello World", "actual": "Hello World"}
        """
        result = self.get_paragraphs()
        if "error" in result:
            return result

        paras = result["paragraphs"]
        if para_index >= len(paras):
            return {
                "match": False,
                "index": para_index,
                "expected": expected_text,
                "actual": None,
                "reason": f"Only {len(paras)} paragraphs in document",
            }

        actual = paras[para_index]["text"]
        return {
            "match": actual.strip() == expected_text.strip(),
            "index": para_index,
            "expected": expected_text,
            "actual": actual,
            "style": paras[para_index].get("style"),
        }

    def check_paragraph_style(self, para_index: int, expected_style: str) -> dict:
        """Check if a paragraph has the expected style (e.g. 'Heading 1', 'Default Paragraph Style').

        Example:
            v.check_paragraph_style(0, "Heading 1")
            => {"match": true, "index": 0, "expected": "Heading 1", "actual": "Heading 1"}
        """
        result = self.get_paragraphs()
        if "error" in result:
            return result

        paras = result["paragraphs"]
        if para_index >= len(paras):
            return {
                "match": False,
                "index": para_index,
                "expected": expected_style,
                "actual": None,
                "reason": f"Only {len(paras)} paragraphs in document",
            }

        actual = paras[para_index]["style"]
        match = actual.lower().replace(" ", "").replace("_20_", "") == expected_style.lower().replace(" ", "").replace("_20_", "")
        return {
            "match": match,
            "index": para_index,
            "expected": expected_style,
            "actual": actual,
        }

    def check_paragraph_formatted(self, para_index: int,
                                   bold: bool | None = None,
                                   italic: bool | None = None,
                                   alignment: str | None = None,
                                   font_name: str | None = None,
                                   font_size: float | None = None) -> dict:
        """Check if a paragraph has specific formatting.

        Example:
            v.check_paragraph_formatted(0, bold=True, alignment="center")
            => {"match": true, "index": 0, "checks": {"bold": {"expected": true, "actual": true, "ok": true}}}
        """
        result = self.get_paragraph_format(para_index)
        if "error" in result:
            return result

        checks = {}
        all_match = True

        def _check(key, expected, actual):
            nonlocal all_match
            if expected is None:
                return
            if isinstance(expected, str) and isinstance(actual, str):
                ok = expected.lower() == actual.lower()
            else:
                ok = expected == actual
            checks[key] = {"expected": expected, "actual": actual, "ok": ok}
            if not ok:
                all_match = False

        _check("bold", bold, result.get("bold"))
        _check("italic", italic, result.get("italic"))
        _check("alignment", alignment, result.get("alignment"))
        _check("font_name", font_name, result.get("font_name"))
        _check("font_size", font_size, result.get("font_size"))

        return {"match": all_match, "index": para_index, "checks": checks}

    def check_table_exists(self, table_name: str) -> dict:
        """Check if a table with the given name exists.

        Example:
            v.check_table_exists("Table1")
            => {"exists": true, "table": "Table1", "rows": 3, "cols": 4}
        """
        result = self.get_tables()
        if "error" in result:
            return result

        for t in result["tables"]:
            if t["name"].lower() == table_name.lower():
                return {"exists": True, "table": t["name"], "rows": t["rows"], "cols": t["cols"]}
        return {"exists": False, "table": table_name, "available": [t["name"] for t in result["tables"]]}

    def check_table_cell(self, table_name: str, row: int, col: int, expected: str) -> dict:
        """Check if a specific table cell has the expected value.

        Example:
            v.check_table_cell("Table1", 0, 0, "Name")
            => {"match": true, "table": "Table1", "row": 0, "col": 0, "expected": "Name", "actual": "Name"}
        """
        result = self.get_table_data(table_name=table_name)
        if "error" in result:
            return result

        data = result["data"]
        if row >= len(data):
            return {"match": False, "error": f"Row {row} out of range (have {len(data)} rows)"}
        if col >= len(data[row]):
            return {"match": False, "error": f"Col {col} out of range (have {len(data[row])} cols)"}

        actual = data[row][col]
        # Smart comparison
        match = False
        try:
            match = float(actual) == float(expected)
        except (ValueError, TypeError):
            match = str(actual).strip().lower() == str(expected).strip().lower()

        return {
            "match": match,
            "table": table_name,
            "row": row,
            "col": col,
            "expected": expected,
            "actual": actual,
        }

    def check_table_exists_file(self, table_name: str, file_path: str | None = None) -> dict:
        """Check if a table with the given name exists (file-based, no UNO needed).

        More reliable than check_table_exists which uses UNO.
        Example:
            v.check_table_exists_file("Table1", "/home/user/doc.odt")
            => {"exists": true, "table": "Table1", "rows": 3, "cols": 4}
        """
        result = self.parse_file_tables(file_path)
        if "error" in result:
            return result

        for t in result["tables"]:
            if t["name"].lower() == table_name.lower():
                return {"exists": True, "table": t["name"], "rows": t["rows"], "cols": t["cols"]}
        return {"exists": False, "table": table_name, "available": [t["name"] for t in result["tables"]]}

    def check_table_cell_file(self, table_name: str, row: int, col: int, expected: str, file_path: str | None = None) -> dict:
        """Check if a specific table cell has the expected value (file-based, no UNO needed).

        More reliable than check_table_cell which uses UNO.
        Example:
            v.check_table_cell_file("Table1", 0, 0, "Name", "/home/user/doc.odt")
            => {"match": true, "table": "Table1", "row": 0, "col": 0, "expected": "Name", "actual": "Name"}
        """
        result = self.parse_file_tables(file_path)
        if "error" in result:
            return result

        # Find the table
        table = None
        for t in result["tables"]:
            if t["name"].lower() == table_name.lower():
                table = t
                break
        if table is None:
            return {"match": False, "error": f"Table '{table_name}' not found.", "available": [t["name"] for t in result["tables"]]}

        data = table["data"]
        if row >= len(data):
            return {"match": False, "error": f"Row {row} out of range (have {len(data)} rows)"}
        if col >= len(data[row]):
            return {"match": False, "error": f"Col {col} out of range (have {len(data[row])} cols)"}

        actual = data[row][col]
        # Smart comparison
        match = False
        try:
            match = float(actual) == float(expected)
        except (ValueError, TypeError):
            match = str(actual).strip().lower() == str(expected).strip().lower()

        return {
            "match": match,
            "table": table["name"],
            "row": row,
            "col": col,
            "expected": expected,
            "actual": actual,
        }

    def check_heading_exists(self, heading_text: str, level: int | None = None) -> dict:
        """Check if a heading with the given text exists.

        Example:
            v.check_heading_exists("Introduction", level=1)
            => {"exists": true, "heading": "Introduction", "level": 1, "index": 2}
        """
        result = self.get_paragraphs()
        live_error = result.get("error")
        if live_error:
            result = self.parse_file_paragraphs()
            if "error" in result:
                return {"error": f"{result['error']} (live check also failed: {live_error})"}

        expected_text = _normalize_text(heading_text)
        for p in result["paragraphs"]:
            actual_text = _normalize_text(p.get("text"))
            actual_level = p.get("level")
            if actual_level is None:
                actual_level = _extract_heading_level(p.get("style"))
            is_heading = bool(p.get("heading")) or actual_level is not None
            if not is_heading or actual_text != expected_text:
                continue
            if level is not None and actual_level != level:
                continue
            return {
                "exists": True,
                "heading": p["text"],
                "level": actual_level,
                "index": p["index"],
                "style": p.get("style"),
            }
        return {"exists": False, "heading": heading_text, "level": level}

    def check_word_count(self, min_words: int | None = None, max_words: int | None = None) -> dict:
        """Check if the document word count is within range.

        Example:
            v.check_word_count(min_words=100, max_words=500)
            => {"in_range": true, "word_count": 250, "min": 100, "max": 500}
        """
        result = self.get_text()
        if "error" in result:
            return result

        words = len(result["text"].split())
        in_range = True
        if min_words is not None and words < min_words:
            in_range = False
        if max_words is not None and words > max_words:
            in_range = False

        return {
            "in_range": in_range,
            "word_count": words,
            "min": min_words,
            "max": max_words,
        }

    def check_file_exists(self, file_path: str) -> dict:
        """Check if a document file exists at the given path.

        Example:
            v.check_file_exists("/home/user/report.odt")
            => {"exists": true, "path": "/home/user/report.odt", "size": 12345}
        """
        exists = os.path.exists(file_path)
        result = {"exists": exists, "path": file_path}
        if exists:
            stat = os.stat(file_path)
            result["size"] = stat.st_size
            result["modified"] = stat.st_mtime
        return result

    def check_file_saved(self) -> dict:
        """Check if the current document has been saved (not modified since last save).

        Example:
            v.check_file_saved()
            => {"saved": true, "path": "file:///home/user/test.odt"}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        return {
            "saved": not doc.isModified(),
            "path": doc.getURL(),
            "title": doc.getTitle(),
        }

    def check_image_count(self, expected: int) -> dict:
        """Check the number of images in the document.

        Example:
            v.check_image_count(2)
            => {"match": true, "expected": 2, "actual": 2}
        """
        result = self.get_images()
        if "error" in result:
            return result
        actual = result["count"]
        return {"match": actual == expected, "expected": expected, "actual": actual}

    # === File format validation for export formats ===

    def check_file_format(self, file_path: str, expected_format: str) -> dict:
        """Check if a file is in the expected format.

        Example:
            v.check_file_format("/home/user/doc.docx", "docx")
            => {"match": true, "format": "docx", "detected": "docx"}
        """
        if not os.path.exists(file_path):
            return {"match": False, "expected": expected_format, "actual": None, "error": "File not found"}

        detected = self._detect_file_format(file_path)
        match = detected.lower() == expected_format.lower()

        return {
            "match": match,
            "expected": expected_format,
            "detected": detected,
            "file_path": file_path
        }

    def _detect_file_format(self, file_path: str) -> str:
        """Detect the file format by examining file headers and structure.

        Returns: One of 'docx', 'doc', 'rtf', 'txt', 'html', 'odt', 'unknown'
        """
        if not os.path.exists(file_path):
            return "unknown"

        try:
            with open(file_path, "rb") as f:
                header = f.read(16)

            # DOCX: ZIP file with specific header
            if header.startswith(b"PK\x03\x04"):
                try:
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        # Check for [Content_Types].xml which indicates DOCX
                        if '[Content_Types].xml' in zip_ref.namelist():
                            return "docx"
                except Exception:
                    pass

            # DOC: Specific file header
            if header[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
                return "doc"

            # RTF: Starts with "{\\rtf"
            if header.startswith(b"{\\rtf"):
                return "rtf"

            # HTML: Starts with "<!DOCTYPE" or "<html"
            content_start = header[:15].lower()
            if b'<!doctype html' in content_start or b'<html' in content_start:
                return "html"

            # TXT: No specific header (text file)
            # Assume it's text if it doesn't match other formats
            return "txt"

        except Exception as e:
            return "unknown"

    def check_docx_contains(self, file_path: str, text: str) -> dict:
        """Check if a DOCX file contains specific text.

        Example:
            v.check_docx_contains("/home/user/doc.docx", "Hello World")
            => {"contains": true, "text": "Hello World", "file": "doc.docx"}
        """
        if not os.path.exists(file_path):
            return {"contains": False, "error": "File not found"}

        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                # DOCX content is in word/document.xml
                with zip_ref.open('word/document.xml') as xml_file:
                    content = xml_file.read().decode('utf-8', errors='ignore')
                    found = text in content
                    return {"contains": found, "text": text, "file": file_path}
        except Exception as e:
            return {"contains": False, "error": f"Failed to parse DOCX: {e}"}

    def check_doc_contains(self, file_path: str, text: str) -> dict:
        """Check if a DOC file contains specific text (basic implementation).

        Note: DOC format is complex; this uses heuristics.

        Example:
            v.check_doc_contains("/home/user/doc.doc", "Hello World")
            => {"contains": true, "text": "Hello World", "file": "doc.doc"}
        """
        if not os.path.exists(file_path):
            return {"contains": False, "error": "File not found"}

        try:
            # Simple text extraction from DOC (not perfect but functional)
            with open(file_path, 'rb') as f:
                content = f.read()
                # Try to find readable text between null bytes
                text_parts = []
                current_part = []
                for byte in content:
                    if byte == 0:
                        if current_part:
                            try:
                                text_parts.append(bytes(current_part).decode('utf-8', errors='ignore'))
                            except:
                                pass
                            current_part = []
                    elif 32 <= byte <= 126:  # Printable ASCII
                        current_part.append(byte)

                if current_part:
                    text_parts.append(bytes(current_part).decode('utf-8', errors='ignore'))

                full_text = ' '.join(text_parts)
                found = text in full_text
                return {"contains": found, "text": text, "file": file_path}
        except Exception as e:
            return {"contains": False, "error": f"Failed to parse DOC: {e}"}

    def check_rtf_contains(self, file_path: str, text: str) -> dict:
        """Check if an RTF file contains specific text.

        Example:
            v.check_rtf_contains("/home/user/doc.rtf", "Hello World")
            => {"contains": true, "text": "Hello World", "file": "doc.rtf"}
        """
        if not os.path.exists(file_path):
            return {"contains": False, "error": "File not found"}

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Remove RTF formatting codes to get plain text
            # Remove common RTF control words
            plain_text = re.sub(r'\\[a-zA-Z]+', '', content)
            # Remove special characters
            plain_text = re.sub(r'\\[\'"0-9a-zA-Z]+', '', plain_text)
            # Remove braces
            plain_text = plain_text.replace('{', '').replace('}', '')

            found = text in plain_text
            return {"contains": found, "text": text, "file": file_path}
        except Exception as e:
            return {"contains": False, "error": f"Failed to parse RTF: {e}"}

    def check_txt_contains(self, file_path: str, text: str) -> dict:
        """Check if a TXT file contains specific text.

        Example:
            v.check_txt_contains("/home/user/doc.txt", "Hello World")
            => {"contains": true, "text": "Hello World", "file": "doc.txt"}
        """
        if not os.path.exists(file_path):
            return {"contains": False, "error": "File not found"}

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                found = text in content
                return {"contains": found, "text": text, "file": file_path}
        except Exception as e:
            return {"contains": False, "error": f"Failed to parse TXT: {e}"}

    def check_html_contains(self, file_path: str, text: str) -> dict:
        """Check if an HTML file contains specific text.

        Example:
            v.check_html_contains("/home/user/doc.html", "Hello World")
            => {"contains": true, "text": "Hello World", "file": "doc.html"}
        """
        if not os.path.exists(file_path):
            return {"contains": False, "error": "File not found"}

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Simple HTML tag removal to get text content
            plain_text = re.sub(r'<[^>]+>', ' ', content)
            plain_text = re.sub(r'\s+', ' ', plain_text).strip()

            found = text in plain_text
            return {"contains": found, "text": text, "file": file_path}
        except Exception as e:
            return {"contains": False, "error": f"Failed to parse HTML: {e}"}


# ---------------------------------------------------------------------------
# CLI interface — for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

COMMANDS = {
    # UNO live state
    "text": ("Get document text", lambda v, args: v.get_text()),
    "paragraphs": ("List paragraphs", lambda v, args: v.get_paragraphs()),
    "paragraph-format": ("Get paragraph formatting", lambda v, args: v.get_paragraph_format(
        int(args[0]) if args else 0)),
    "doc-info": ("Get document info", lambda v, args: v.get_document_info()),
    "page-count": ("Get page count", lambda v, args: v.get_page_count()),
    "tables": ("List tables", lambda v, args: v.get_tables()),
    "table-data": ("Get table data", lambda v, args: v.get_table_data(
        table_name=args[0] if args else None)),
    "images": ("List images", lambda v, args: v.get_images()),
    "page-style": ("Get page style", lambda v, args: v.get_page_style(
        args[0] if args else "Standard")),
    "search": ("Search for text", lambda v, args: v.search_text(
        args[0], regex=len(args) > 1 and args[1].lower() == "regex")),
    "bookmarks": ("List bookmarks", lambda v, args: v.get_bookmarks()),
    "headers-footers": ("Get headers/footers", lambda v, args: v.get_headers_footers()),

    # ODF file parsing (offline)
    "parse-text": ("Extract text from ODT", lambda v, args: v.parse_file_text(
        args[0] if args else None)),
    "parse-paragraphs": ("List paragraphs from ODT", lambda v, args: v.parse_file_paragraphs(
        args[0] if args else None)),
    "parse-tables": ("List tables from ODT", lambda v, args: v.parse_file_tables(
        args[0] if args else None)),

    # Composite checks
    "check-text-contains": ("Check document has text", lambda v, args: v.check_text_contains(args[0])),
    "check-paragraph-count": ("Check paragraph count", lambda v, args: v.check_paragraph_count(int(args[0]))),
    "check-paragraph-text": ("Check paragraph text", lambda v, args: v.check_paragraph_text(
        int(args[0]), args[1])),
    "check-paragraph-style": ("Check paragraph style", lambda v, args: v.check_paragraph_style(
        int(args[0]), args[1])),
    "check-paragraph-formatted": ("Check paragraph formatting", lambda v, args: v.check_paragraph_formatted(
        int(args[0]), bold=args[1].lower() == "true" if len(args) > 1 else None)),
    "check-table-exists": ("Check table exists (UNO)", lambda v, args: v.check_table_exists(args[0])),
    "check-table-cell": ("Check table cell value (UNO)", lambda v, args: v.check_table_cell(
        args[0], int(args[1]), int(args[2]), args[3])),
    "check-table-exists-file": ("Check table exists (file-based)", lambda v, args: v.check_table_exists_file(
        args[0], file_path=args[1] if len(args) > 1 else None)),
    "check-table-cell-file": ("Check table cell value (file-based)", lambda v, args: v.check_table_cell_file(
        args[0], int(args[1]), int(args[2]), args[3], file_path=args[4] if len(args) > 4 else None)),
    "check-heading-exists": ("Check heading exists", lambda v, args: v.check_heading_exists(
        args[0], level=int(args[1]) if len(args) > 1 else None)),
    "check-word-count": ("Check word count range", lambda v, args: v.check_word_count(
        min_words=int(args[0]) if args else None,
        max_words=int(args[1]) if len(args) > 1 else None)),
    "check-file-exists": ("Check file exists", lambda v, args: v.check_file_exists(args[0])),
    "check-file-saved": ("Check document saved", lambda v, args: v.check_file_saved()),
    "check-image-count": ("Check image count", lambda v, args: v.check_image_count(int(args[0]))),

    # File format validation
    "check-file-format": ("Check file format: <file_path> <expected_format>",
        lambda v, args: v.check_file_format(args[0], args[1])),
    "check-docx-contains": ("Check DOCX file contains text: <file_path> <text>",
        lambda v, args: v.check_docx_contains(args[0], args[1])),
    "check-doc-contains": ("Check DOC file contains text: <file_path> <text>",
        lambda v, args: v.check_doc_contains(args[0], args[1])),
    "check-rtf-contains": ("Check RTF file contains text: <file_path> <text>",
        lambda v, args: v.check_rtf_contains(args[0], args[1])),
    "check-txt-contains": ("Check TXT file contains text: <file_path> <text>",
        lambda v, args: v.check_txt_contains(args[0], args[1])),
    "check-html-contains": ("Check HTML file contains text: <file_path> <text>",
        lambda v, args: v.check_html_contains(args[0], args[1])),
}


def _print_usage():
    print("LibreOffice Writer Verifier — query document state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nUNO endpoints require LibreOffice running with --accept on port {UNO_PORT}")
    print("ODF parse-* endpoints work on saved .odt files without UNO")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = LibreOfficeWriterVerifier()
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
