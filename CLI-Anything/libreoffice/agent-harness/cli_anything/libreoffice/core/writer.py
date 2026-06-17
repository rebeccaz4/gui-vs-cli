"""LibreOffice CLI - Writer (word processor) module."""

import os
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional


def _ensure_writer(project: Dict[str, Any]) -> None:
    """Ensure the project is a Writer document."""
    if project.get("type") != "writer":
        raise ValueError(
            f"Document type is '{project.get('type')}', expected 'writer'."
        )
    if "content" not in project:
        project["content"] = []


def add_paragraph(
    project: Dict[str, Any],
    text: str = "",
    style: Optional[Dict] = None,
    position: Optional[int] = None,
) -> Dict[str, Any]:
    """Add a paragraph to the document."""
    _ensure_writer(project)
    item = {
        "type": "paragraph",
        "text": text,
        "style": style or {},
    }
    if position is not None:
        if position < 0 or position > len(project["content"]):
            raise IndexError(
                f"Position {position} out of range "
                f"(0-{len(project['content'])})"
            )
        project["content"].insert(position, item)
    else:
        project["content"].append(item)
    return item


def add_heading(
    project: Dict[str, Any],
    text: str = "",
    level: int = 1,
    style: Optional[Dict] = None,
    position: Optional[int] = None,
) -> Dict[str, Any]:
    """Add a heading to the document."""
    _ensure_writer(project)
    if level < 1 or level > 6:
        raise ValueError(f"Heading level must be 1-6, got {level}")
    item = {
        "type": "heading",
        "level": level,
        "text": text,
        "style": style or {},
    }
    if position is not None:
        if position < 0 or position > len(project["content"]):
            raise IndexError(
                f"Position {position} out of range "
                f"(0-{len(project['content'])})"
            )
        project["content"].insert(position, item)
    else:
        project["content"].append(item)
    return item


def add_list(
    project: Dict[str, Any],
    items: Optional[List[str]] = None,
    list_style: str = "bullet",
    position: Optional[int] = None,
) -> Dict[str, Any]:
    """Add a list to the document."""
    _ensure_writer(project)
    if list_style not in ("bullet", "number"):
        raise ValueError(
            f"Invalid list style: {list_style}. Use 'bullet' or 'number'."
        )
    item = {
        "type": "list",
        "list_style": list_style,
        "items": items or [],
    }
    if position is not None:
        if position < 0 or position > len(project["content"]):
            raise IndexError(
                f"Position {position} out of range "
                f"(0-{len(project['content'])})"
            )
        project["content"].insert(position, item)
    else:
        project["content"].append(item)
    return item


def add_table(
    project: Dict[str, Any],
    rows: int = 2,
    cols: int = 2,
    data: Optional[List[List[str]]] = None,
    name: Optional[str] = None,
    position: Optional[int] = None,
) -> Dict[str, Any]:
    """Add a table to the document."""
    _ensure_writer(project)
    if rows < 1 or cols < 1:
        raise ValueError(f"Table must have at least 1 row and 1 column")
    if data is None:
        data = [["" for _ in range(cols)] for _ in range(rows)]
    item = {
        "type": "table",
        "name": name or f"Table{len([c for c in project.get('content', []) if c.get('type') == 'table']) + 1}",
        "rows": rows,
        "cols": cols,
        "data": data,
    }
    if position is not None:
        if position < 0 or position > len(project["content"]):
            raise IndexError(
                f"Position {position} out of range "
                f"(0-{len(project['content'])})"
            )
        project["content"].insert(position, item)
    else:
        project["content"].append(item)
    return item


def set_table_cell(
    project: Dict[str, Any],
    table_index: int,
    row: int,
    col: int,
    value: str,
) -> Dict[str, Any]:
    """Set a table cell value by table index."""
    _ensure_writer(project)
    tables = [item for item in project.get("content", []) if item.get("type") == "table"]
    if table_index < 0 or table_index >= len(tables):
        raise IndexError(f"Table index {table_index} out of range (0-{len(tables) - 1})")
    table = tables[table_index]
    rows = int(table.get("rows", 0))
    cols = int(table.get("cols", 0))
    if row < 0 or row >= rows:
        raise IndexError(f"Row {row} out of range (0-{rows - 1})")
    if col < 0 or col >= cols:
        raise IndexError(f"Column {col} out of range (0-{cols - 1})")
    data = table.setdefault("data", [["" for _ in range(cols)] for _ in range(rows)])
    while len(data) < rows:
        data.append(["" for _ in range(cols)])
    for row_data in data:
        while len(row_data) < cols:
            row_data.append("")
    data[row][col] = value
    return {"table_index": table_index, "table": table.get("name"), "row": row, "col": col, "value": value}


def add_image(
    project: Dict[str, Any],
    path: str,
    name: str = "Image",
    width: str = "5cm",
    height: str = "5cm",
    position: Optional[int] = None,
) -> Dict[str, Any]:
    """Add an image reference to the document."""
    _ensure_writer(project)
    item = {
        "type": "image_ref",
        "path": path,
        "name": name,
        "width": width,
        "height": height,
    }
    if position is not None:
        if position < 0 or position > len(project["content"]):
            raise IndexError(f"Position {position} out of range (0-{len(project['content'])})")
        project["content"].insert(position, item)
    else:
        project["content"].append(item)
    return item


def add_bookmark(
    project: Dict[str, Any],
    name: str,
    text: str = "",
    position: Optional[int] = None,
) -> Dict[str, Any]:
    """Add a bookmark marker, optionally around visible text."""
    _ensure_writer(project)
    item = {"type": "bookmark", "name": name, "text": text}
    if position is not None:
        if position < 0 or position > len(project["content"]):
            raise IndexError(f"Position {position} out of range (0-{len(project['content'])})")
        project["content"].insert(position, item)
    else:
        project["content"].append(item)
    return item


def set_header(project: Dict[str, Any], text: str) -> Dict[str, Any]:
    """Set Standard page style header text."""
    _ensure_writer(project)
    project["header"] = text
    return {"header": text}


def set_footer(project: Dict[str, Any], text: str) -> Dict[str, Any]:
    """Set Standard page style footer text."""
    _ensure_writer(project)
    project["footer"] = text
    return {"footer": text}


def add_page_break(
    project: Dict[str, Any],
    position: Optional[int] = None,
) -> Dict[str, Any]:
    """Add a page break to the document."""
    _ensure_writer(project)
    item = {"type": "page_break"}
    if position is not None:
        if position < 0 or position > len(project["content"]):
            raise IndexError(
                f"Position {position} out of range "
                f"(0-{len(project['content'])})"
            )
        project["content"].insert(position, item)
    else:
        project["content"].append(item)
    return item


def remove_content(
    project: Dict[str, Any],
    index: int,
) -> Dict[str, Any]:
    """Remove a content item by index."""
    _ensure_writer(project)
    content = project["content"]
    if not content:
        raise ValueError("No content to remove.")
    if index < 0 or index >= len(content):
        raise IndexError(
            f"Index {index} out of range (0-{len(content) - 1})"
        )
    return content.pop(index)


def list_content(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    """List all content items with their indices."""
    _ensure_writer(project)
    result = []
    for i, item in enumerate(project.get("content", [])):
        entry = {
            "index": i,
            "type": item.get("type", "unknown"),
        }
        if item.get("type") == "heading":
            entry["level"] = item.get("level", 1)
            entry["text"] = item.get("text", "")[:80]
        elif item.get("type") == "paragraph":
            entry["text"] = item.get("text", "")[:80]
        elif item.get("type") == "list":
            entry["list_style"] = item.get("list_style", "bullet")
            entry["item_count"] = len(item.get("items", []))
        elif item.get("type") == "table":
            entry["rows"] = item.get("rows", 0)
            entry["cols"] = item.get("cols", 0)
        result.append(entry)
    return result


def get_content(project: Dict[str, Any], index: int) -> Dict[str, Any]:
    """Get a content item by index."""
    _ensure_writer(project)
    content = project.get("content", [])
    if index < 0 or index >= len(content):
        raise IndexError(
            f"Index {index} out of range (0-{len(content) - 1})"
        )
    return content[index]


def set_content_text(
    project: Dict[str, Any],
    index: int,
    text: str,
) -> Dict[str, Any]:
    """Set the text of a content item."""
    _ensure_writer(project)
    content = project.get("content", [])
    if index < 0 or index >= len(content):
        raise IndexError(
            f"Index {index} out of range (0-{len(content) - 1})"
        )
    item = content[index]
    if item["type"] not in ("paragraph", "heading"):
        raise ValueError(
            f"Cannot set text on content type '{item['type']}'"
        )
    item["text"] = text
    return item


def _blank_import_project(path: str, name: Optional[str] = None) -> Dict[str, Any]:
    return {
        "version": "1.0",
        "name": name or os.path.splitext(os.path.basename(path))[0],
        "type": "writer",
        "settings": {
            "page_width": "21cm",
            "page_height": "29.7cm",
            "margin_top": "2cm",
            "margin_bottom": "2cm",
            "margin_left": "2cm",
            "margin_right": "2cm",
        },
        "styles": {},
        "content": [],
        "metadata": {
            "title": "",
            "author": "",
            "description": "",
            "subject": "",
            "software": "libreoffice-cli 1.0",
        },
    }


def import_odt(path: str, name: Optional[str] = None) -> Dict[str, Any]:
    """Import basic paragraphs, headings, and tables from an .odt file."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"ODT file not found: {path}")
    try:
        with zipfile.ZipFile(path, "r") as zf:
            content_xml = zf.read("content.xml")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid ODT file: {path}") from exc
    except KeyError as exc:
        raise ValueError(f"No content.xml found in ODT file: {path}") from exc

    ns = {
        "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
        "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    }
    root = ET.fromstring(content_xml)
    project = _blank_import_project(path, name=name)
    text_elem = root.find("office:body/office:text", ns)
    if text_elem is None:
        return project
    for child in text_elem:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "h":
            level = int(child.get(f"{{{ns['text']}}}outline-level", "1"))
            project["content"].append({"type": "heading", "level": level, "text": "".join(child.itertext()), "style": {}})
        elif local == "p":
            text = "".join(child.itertext())
            if text:
                project["content"].append({"type": "paragraph", "text": text, "style": {}})
        elif local == "table":
            data = []
            for row_elem in child.findall("table:table-row", ns):
                row_data = []
                for cell in row_elem.findall("table:table-cell", ns):
                    row_data.append("".join(cell.itertext()))
                data.append(row_data)
            rows = len(data)
            cols = max((len(row) for row in data), default=0)
            project["content"].append({
                "type": "table",
                "name": child.get(f"{{{ns['table']}}}name", "Table1"),
                "rows": rows,
                "cols": cols,
                "data": data,
            })
    return project


def _import_docx_basic(path: str, name: Optional[str] = None) -> Dict[str, Any]:
    """Import basic text and tables from a .docx file without LibreOffice."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            document_xml = zf.read("word/document.xml")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid DOCX file: {path}") from exc
    except KeyError as exc:
        raise ValueError(f"No word/document.xml found in DOCX file: {path}") from exc

    ns = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    }
    root = ET.fromstring(document_xml)
    project = _blank_import_project(path, name=name)
    body = root.find("w:body", ns)
    if body is None:
        return project
    table_index = 1
    for child in body:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "p":
            text = "".join(node.text or "" for node in child.findall(".//w:t", ns))
            if not text:
                continue
            style = child.find("w:pPr/w:pStyle", ns)
            style_val = style.get(f"{{{ns['w']}}}val") if style is not None else ""
            match = re.search(r"Heading(\d+)", style_val or "")
            if match:
                project["content"].append({"type": "heading", "level": int(match.group(1)), "text": text, "style": {}})
            else:
                project["content"].append({"type": "paragraph", "text": text, "style": {}})
        elif local == "tbl":
            data = []
            for tr in child.findall("w:tr", ns):
                row = []
                for tc in tr.findall("w:tc", ns):
                    row.append("".join(node.text or "" for node in tc.findall(".//w:t", ns)))
                data.append(row)
            project["content"].append({
                "type": "table",
                "name": f"Table{table_index}",
                "rows": len(data),
                "cols": max((len(row) for row in data), default=0),
                "data": data,
            })
            table_index += 1
    return project


def import_document(path: str, name: Optional[str] = None) -> Dict[str, Any]:
    """Import an existing .odt or .docx into Writer project state."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Writer document not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".odt":
        return import_odt(path, name=name)
    if ext == ".docx":
        try:
            from cli_anything.libreoffice.utils.lo_backend import convert

            with tempfile.TemporaryDirectory(prefix="lo_import_writer_") as tmpdir:
                odt_path = convert(path, "odt", output_dir=tmpdir)
                return import_odt(odt_path, name=name)
        except Exception:
            return _import_docx_basic(path, name=name)
    raise ValueError("Only .odt and .docx Writer import are supported.")
