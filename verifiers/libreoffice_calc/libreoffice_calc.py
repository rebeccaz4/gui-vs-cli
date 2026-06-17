"""
LibreOffice Calc Verifier — programmatic state inspection for spreadsheets in E2B sandbox.

Verification channels (in order of preference):
  1. UNO API — live inspection of open documents via Python-UNO bridge (cells, sheets, formatting)
  2. ODF file parsing — .ods files are ZIP archives; parse content.xml / styles.xml directly
  3. File-based checks — file existence, modification time, size

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/libreoffice_calc.py sheets")
    sandbox.commands.run("python3 /home/user/verifiers/libreoffice_calc.py cell-value A1")
    sandbox.commands.run("python3 /home/user/verifiers/libreoffice_calc.py check-cell-value A1 42")

Usage from Python (inside sandbox or via E2B):
    from verifiers.libreoffice_calc import LibreOfficeCalcVerifier
    v = LibreOfficeCalcVerifier()
    sheets = v.get_sheets()
    val = v.get_cell_value("A1")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - LibreOffice launched with:
    soffice --calc --accept="socket,host=localhost,port=2002;urp;" --norestore
  - For ODF parsing: only stdlib (zipfile, xml.etree)
"""

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
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
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "number": "urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "chart": "urn:oasis:names:tc:opendocument:xmlns:chart:1.0",
    "calcext": "urn:org:documentfoundation:names:experimental:calc:xmlns:calcext:1.0",
}

# ---------------------------------------------------------------------------
# UNO Enum helper
# ---------------------------------------------------------------------------

def _enum_val(enum_obj):
    """Convert a UNO Enum to a comparable value. Handles com.sun.star.* enums
    which may not support int() or == with int directly."""
    if hasattr(enum_obj, 'value'):
        v = enum_obj.value
        # value might be a string like "NONE" or a number
        if isinstance(v, (int, float)):
            return v
        return str(v)
    try:
        return int(enum_obj)
    except (TypeError, ValueError):
        return str(enum_obj)

# ---------------------------------------------------------------------------
# Cell address helpers
# ---------------------------------------------------------------------------

def _col_name_to_index(col: str) -> int:
    """Convert column letter(s) to 0-based index. A=0, B=1, ..., Z=25, AA=26."""
    col = col.upper()
    result = 0
    for c in col:
        result = result * 26 + (ord(c) - ord("A") + 1)
    return result - 1


def _index_to_col_name(idx: int) -> str:
    """Convert 0-based column index to letter(s). 0=A, 25=Z, 26=AA."""
    result = ""
    idx += 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        result = chr(65 + rem) + result
    return result


def _parse_cell_ref(ref: str) -> tuple[int, int]:
    """Parse a cell reference like 'A1' or 'AB123' into (col_index, row_index), both 0-based."""
    match = re.match(r"^([A-Za-z]+)(\d+)$", ref)
    if not match:
        raise ValueError(f"Invalid cell reference: {ref}")
    col = _col_name_to_index(match.group(1))
    row = int(match.group(2)) - 1  # 1-based to 0-based
    return col, row


def _parse_range_ref(ref: str) -> tuple[int, int, int, int]:
    """Parse 'A1:C3' into (col_start, row_start, col_end, row_end), all 0-based."""
    parts = ref.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid range reference: {ref}. Expected format: A1:C3")
    c1, r1 = _parse_cell_ref(parts[0])
    c2, r2 = _parse_cell_ref(parts[1])
    return c1, r1, c2, r2


# ---------------------------------------------------------------------------
# UNO helpers
# ---------------------------------------------------------------------------

def _get_uno_desktop():
    """Connect to running LibreOffice via UNO and return the desktop object."""
    try:
        import uno
        from com.sun.star.connection import NoConnectException
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
    """Get the current Calc document via UNO."""
    desktop, err = _get_uno_desktop()
    if err:
        return None, None, err
    doc = desktop.getCurrentComponent()
    if doc is None:
        return desktop, None, "No document is currently open."
    return desktop, doc, None


def _get_uno_sheet(doc, sheet_name: str | None = None):
    """Get a sheet by name or the active sheet."""
    if sheet_name:
        sheets = doc.getSheets()
        if not sheets.hasByName(sheet_name):
            return None, f"Sheet '{sheet_name}' not found."
        return sheets.getByName(sheet_name), None
    else:
        return doc.getCurrentController().getActiveSheet(), None


# ---------------------------------------------------------------------------
# ODF file parsing helpers
# ---------------------------------------------------------------------------

def _parse_ods_content(file_path: str) -> tuple[ET.Element | None, str | None]:
    """Extract and parse content.xml from an .ods file."""
    if not os.path.exists(file_path):
        return None, f"File not found: {file_path}"
    try:
        with zipfile.ZipFile(file_path, "r") as z:
            with z.open("content.xml") as f:
                tree = ET.parse(f)
                return tree.getroot(), None
    except zipfile.BadZipFile:
        return None, f"Not a valid ODS/ZIP file: {file_path}"
    except KeyError:
        return None, f"No content.xml found in: {file_path}"


def _parse_ods_styles(file_path: str) -> tuple[ET.Element | None, str | None]:
    """Extract and parse styles.xml from an .ods file."""
    if not os.path.exists(file_path):
        return None, f"File not found: {file_path}"
    try:
        with zipfile.ZipFile(file_path, "r") as z:
            with z.open("styles.xml") as f:
                tree = ET.parse(f)
                return tree.getroot(), None
    except (zipfile.BadZipFile, KeyError) as e:
        return None, f"Cannot read styles.xml: {e}"


def _parse_ods_meta(file_path: str) -> tuple[ET.Element | None, str | None]:
    """Extract and parse meta.xml from an .ods file."""
    if not os.path.exists(file_path):
        return None, f"File not found: {file_path}"
    try:
        with zipfile.ZipFile(file_path, "r") as z:
            with z.open("meta.xml") as f:
                tree = ET.parse(f)
                return tree.getroot(), None
    except (zipfile.BadZipFile, KeyError) as e:
        return None, f"Cannot read meta.xml: {e}"


def _get_cell_text(cell_elem) -> str:
    """Extract text content from an ODF table-cell element."""
    texts = []
    for p in cell_elem.findall("text:p", ODF_NS):
        t = "".join(p.itertext())
        texts.append(t)
    return "\n".join(texts)


def _get_cell_value(cell_elem) -> Any:
    """Extract the typed value from an ODF table-cell element."""
    val_type = cell_elem.get(f"{{{ODF_NS['office']}}}value-type")
    if val_type == "float":
        raw = cell_elem.get(f"{{{ODF_NS['office']}}}value")
        if raw is not None:
            f = float(raw)
            return int(f) if f == int(f) else f
    elif val_type == "percentage":
        raw = cell_elem.get(f"{{{ODF_NS['office']}}}value")
        if raw is not None:
            return float(raw)
    elif val_type == "currency":
        raw = cell_elem.get(f"{{{ODF_NS['office']}}}value")
        if raw is not None:
            return float(raw)
    elif val_type == "date":
        return cell_elem.get(f"{{{ODF_NS['office']}}}date-value")
    elif val_type == "time":
        return cell_elem.get(f"{{{ODF_NS['office']}}}time-value")
    elif val_type == "boolean":
        raw = cell_elem.get(f"{{{ODF_NS['office']}}}boolean-value")
        return raw == "true" if raw else None
    elif val_type == "string":
        return _get_cell_text(cell_elem)
    # Fallback: return display text
    text = _get_cell_text(cell_elem)
    return text if text else None


def _expand_ods_rows(table_elem) -> list[list[tuple[Any, str | None, dict]]]:
    """Expand repeated rows/cells in an ODF table, returning a grid.

    Each cell is (value, display_text, attributes_dict).
    """
    rows = []
    for row_elem in table_elem.findall("table:table-row", ODF_NS):
        row_repeat = int(row_elem.get(f"{{{ODF_NS['table']}}}number-rows-repeated", "1"))
        cells = []
        for cell_elem in row_elem.findall("table:table-cell", ODF_NS):
            col_repeat = int(cell_elem.get(f"{{{ODF_NS['table']}}}number-columns-repeated", "1"))
            value = _get_cell_value(cell_elem)
            display = _get_cell_text(cell_elem)
            val_type = cell_elem.get(f"{{{ODF_NS['office']}}}value-type")
            formula = cell_elem.get(f"{{{ODF_NS['table']}}}formula")
            style = cell_elem.get(f"{{{ODF_NS['table']}}}style-name")
            attrs = {}
            if val_type:
                attrs["type"] = val_type
            if formula:
                attrs["formula"] = formula
            if style:
                attrs["style"] = style
            for _ in range(col_repeat):
                cells.append((value, display, attrs))
        for _ in range(row_repeat):
            rows.append(list(cells))
    return rows


def _find_ods_file() -> str | None:
    """Try to find a recently saved .ods file in common locations."""
    search_dirs = [
        Path.home(),
        Path.home() / "Documents",
        Path.home() / "Desktop",
        Path("/tmp"),
    ]
    ods_files = []
    for d in search_dirs:
        if d.exists():
            for f in d.glob("*.ods"):
                ods_files.append(f)
            for f in d.glob("*.xlsx"):
                ods_files.append(f)
    if ods_files:
        # Return most recently modified
        return str(max(ods_files, key=lambda f: f.stat().st_mtime))
    return None


# ---------------------------------------------------------------------------
# LibreOfficeCalcVerifier class
# ---------------------------------------------------------------------------

class LibreOfficeCalcVerifier:
    """Stateless verifier — each method call is independent.

    Methods try UNO first (live state), then fall back to ODF file parsing.
    For file-based methods, pass file_path explicitly or let it auto-detect.
    """

    # === UNO: Live document state ===

    def get_sheets(self) -> dict:
        """List all sheets in the current workbook.

        Example return:
        {"sheets": [{"name": "Sheet1", "index": 0, "rows": 10, "cols": 5}], "active": "Sheet1", "count": 1}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}

        try:
            sheets_obj = doc.getSheets()
            active_name = doc.getCurrentController().getActiveSheet().getName()
            sheets = []
            for i in range(sheets_obj.getCount()):
                sheet = sheets_obj.getByIndex(i)
                cursor = sheet.createCursor()
                cursor.gotoEndOfUsedArea(False)
                addr = cursor.getRangeAddress()
                sheets.append({
                    "name": sheet.getName(),
                    "index": i,
                    "rows": addr.EndRow + 1,
                    "cols": addr.EndColumn + 1,
                    "visible": sheet.IsVisible,
                })
            return {"sheets": sheets, "active": active_name, "count": len(sheets)}
        except Exception as e:
            return {"error": f"Failed to get sheets: {e}"}

    def get_cell_value(self, cell_ref: str, sheet_name: str | None = None) -> dict:
        """Get the value and type of a cell.

        Example:
            v.get_cell_value("A1")
            => {"cell": "A1", "value": 42.0, "type": "float", "display": "42", "formula": null}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}

        try:
            col, row = _parse_cell_ref(cell_ref)
        except ValueError as e:
            return {"error": str(e)}

        try:
            sheet, err = _get_uno_sheet(doc, sheet_name)
            if err:
                return {"error": err}

            cell = sheet.getCellByPosition(col, row)
            # com.sun.star.table.CellContentType: EMPTY=0, VALUE=1, TEXT=2, FORMULA=3
            cell_type_raw = cell.getType()
            cell_type_str = str(cell_type_raw).upper()
            # com.sun.star.table.CellContentType: EMPTY=0, VALUE=1, TEXT=2, FORMULA=3
            # Detect by checking the string representation (handles UNO Enum quirks)
            is_formula = "FORMULA" in cell_type_str
            is_empty = "EMPTY" in cell_type_str
            # "VALUE" must not match inside "TEXTVALUE" etc — check it's not TEXT
            is_value = "VALUE" in cell_type_str and not is_formula and not is_empty
            is_text = not is_empty and not is_value and not is_formula

            type_name = "empty" if is_empty else "float" if is_value else "formula" if is_formula else "string"

            value = None
            if is_value:
                value = cell.getValue()
                if value == int(value):
                    value = int(value)
            elif is_text:
                value = cell.getString()
            elif is_formula:
                value = cell.getValue() if cell.getValue() != 0 or cell.getString() == "0" else cell.getString()

            formula = cell.getFormula() if is_formula else None
            return {
                "cell": cell_ref.upper(),
                "value": value,
                "type": type_name,
                "display": cell.getString(),
                "formula": formula,
                "sheet": sheet.getName(),
            }
        except Exception as e:
            return {"error": f"Failed to read cell {cell_ref}: {e}"}

    def get_range_values(self, range_ref: str, sheet_name: str | None = None) -> dict:
        """Get values for a range of cells (e.g. 'A1:C3').

        Example:
            v.get_range_values("A1:B2")
            => {"range": "A1:B2", "data": [[1, "Name"], [2, "Alice"]], "rows": 2, "cols": 2}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}

        try:
            c1, r1, c2, r2 = _parse_range_ref(range_ref)
        except ValueError as e:
            return {"error": str(e)}

        try:
            sheet, err = _get_uno_sheet(doc, sheet_name)
            if err:
                return {"error": err}

            data = []
            for r in range(r1, r2 + 1):
                row_data = []
                for c in range(c1, c2 + 1):
                    cell = sheet.getCellByPosition(c, r)
                    ct_str = str(cell.getType()).upper()
                    if "EMPTY" in ct_str:
                        row_data.append(None)
                    elif "FORMULA" in ct_str:
                        v = cell.getValue()
                        s = cell.getString()
                        if v != 0 or s == "0":
                            row_data.append(int(v) if v == int(v) else v)
                        else:
                            row_data.append(s)
                    elif "VALUE" in ct_str:
                        v = cell.getValue()
                        row_data.append(int(v) if v == int(v) else v)
                    else:
                        row_data.append(cell.getString())
                data.append(row_data)

            return {
                "range": range_ref.upper(),
                "data": data,
                "rows": r2 - r1 + 1,
                "cols": c2 - c1 + 1,
                "sheet": sheet.getName(),
            }
        except Exception as e:
            return {"error": f"Failed to read range {range_ref}: {e}"}

    def get_sheet_data(self, sheet_name: str | None = None, max_rows: int = 50, max_cols: int = 26) -> dict:
        """Get all data from a sheet (up to max_rows x max_cols).

        Example:
            v.get_sheet_data("Sheet1")
            => {"sheet": "Sheet1", "data": [...], "rows": 10, "cols": 3, "headers": ["A", "B", "C"]}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}

        try:
            sheet, err = _get_uno_sheet(doc, sheet_name)
            if err:
                return {"error": err}

            cursor = sheet.createCursor()
            cursor.gotoEndOfUsedArea(False)
            addr = cursor.getRangeAddress()
            end_row = min(addr.EndRow, max_rows - 1)
            end_col = min(addr.EndColumn, max_cols - 1)

            headers = [_index_to_col_name(c) for c in range(end_col + 1)]
            data = []
            for r in range(end_row + 1):
                row_data = []
                for c in range(end_col + 1):
                    cell = sheet.getCellByPosition(c, r)
                    ct_str = str(cell.getType()).upper()
                    if "EMPTY" in ct_str:
                        row_data.append(None)
                    elif "FORMULA" in ct_str:
                        v = cell.getValue()
                        s = cell.getString()
                        if v != 0 or s == "0":
                            row_data.append(int(v) if v == int(v) else v)
                        else:
                            row_data.append(s)
                    elif "VALUE" in ct_str:
                        v = cell.getValue()
                        row_data.append(int(v) if v == int(v) else v)
                    else:
                        row_data.append(cell.getString())
                data.append(row_data)

            return {
                "sheet": sheet.getName(),
                "data": data,
                "rows": end_row + 1,
                "cols": end_col + 1,
                "headers": headers,
            }
        except Exception as e:
            return {"error": f"Failed to read sheet data: {e}"}

    def get_cell_format(self, cell_ref: str, sheet_name: str | None = None) -> dict:
        """Get formatting info for a cell (font, color, alignment, number format).

        Example:
            v.get_cell_format("A1")
            => {"cell": "A1", "bold": true, "italic": false, "font_size": 12, ...}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}

        try:
            col, row = _parse_cell_ref(cell_ref)
        except ValueError as e:
            return {"error": str(e)}

        try:
            sheet, err = _get_uno_sheet(doc, sheet_name)
            if err:
                return {"error": err}

            cell = sheet.getCellByPosition(col, row)

            # Get number format string
            nf_key = cell.NumberFormat
            formats = doc.getNumberFormats()
            nf_props = formats.getByKey(nf_key)
            nf_string = nf_props.getPropertyValue("FormatString")

            # Color as hex
            def _color_hex(color_int):
                return f"#{color_int:06X}" if color_int else None

            return {
                "cell": cell_ref.upper(),
                "bold": cell.getPropertyValue("CharWeight") > 100,
                "italic": "NONE" not in str(cell.getPropertyValue("CharPosture")),
                "font_name": cell.getPropertyValue("CharFontName"),
                "font_size": cell.getPropertyValue("CharHeight"),
                "font_color": _color_hex(cell.getPropertyValue("CharColor")),
                "bg_color": _color_hex(cell.getPropertyValue("CellBackColor")),
                "h_align": str(cell.getPropertyValue("HoriJustify")).split(".")[-1].lower(),
                "v_align": str(cell.getPropertyValue("VertJustify")).split(".")[-1].lower(),
                "number_format": nf_string,
                "wrap_text": cell.getPropertyValue("IsTextWrapped"),
                "sheet": sheet.getName(),
            }
        except Exception as e:
            return {"error": f"Failed to read format for {cell_ref}: {e}"}

    def get_merged_cells(self, sheet_name: str | None = None) -> dict:
        """Get all merged cell ranges in a sheet.

        Example:
            v.get_merged_cells()
            => {"merged": ["A1:C1", "B3:B5"], "count": 2}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}

        try:
            sheet, err = _get_uno_sheet(doc, sheet_name)
            if err:
                return {"error": err}

            # Iterate over used area looking for merged regions
            cursor = sheet.createCursor()
            cursor.gotoEndOfUsedArea(False)
            addr = cursor.getRangeAddress()

            merged = []
            visited = set()
            for r in range(addr.EndRow + 1):
                for c in range(addr.EndColumn + 1):
                    if (c, r) in visited:
                        continue
                    cell = sheet.getCellByPosition(c, r)
                    if cell.getIsMerged():
                        # Find merge range via cell range
                        rng = sheet.getCellRangeByPosition(c, r, c, r)
                        merge_addr = rng.getRangeAddress()
                        # The actual merged range might be bigger; query the merge
                        cursor2 = sheet.createCursorByRange(rng)
                        cursor2.collapseToMergedArea()
                        ma = cursor2.getRangeAddress()
                        start = f"{_index_to_col_name(ma.StartColumn)}{ma.StartRow + 1}"
                        end = f"{_index_to_col_name(ma.EndColumn)}{ma.EndRow + 1}"
                        ref = f"{start}:{end}" if start != end else start
                        if ref not in merged:
                            merged.append(ref)
                        for mr in range(ma.StartRow, ma.EndRow + 1):
                            for mc in range(ma.StartColumn, ma.EndColumn + 1):
                                visited.add((mc, mr))

            return {"merged": merged, "count": len(merged), "sheet": sheet.getName()}
        except Exception as e:
            return {"error": f"Failed to get merged cells: {e}"}

    def get_active_sheet(self) -> dict:
        """Get the name and index of the active sheet.

        Example:
            v.get_active_sheet()
            => {"name": "Sheet1", "index": 0}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            active = doc.getCurrentController().getActiveSheet()
            sheets = doc.getSheets()
            idx = None
            for i in range(sheets.getCount()):
                if sheets.getByIndex(i).getName() == active.getName():
                    idx = i
                    break
            return {"name": active.getName(), "index": idx}
        except Exception as e:
            return {"error": f"Failed to get active sheet: {e}"}

    def get_document_info(self) -> dict:
        """Get document metadata (file path, title, sheet count).

        Example:
            v.get_document_info()
            => {"path": "/home/user/test.ods", "title": "test.ods", "sheet_count": 3, "modified": true}
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            return {
                "path": doc.getURL(),
                "title": doc.getTitle(),
                "sheet_count": doc.getSheets().getCount(),
                "modified": doc.isModified(),
            }
        except Exception as e:
            return {"error": f"Failed to get doc info: {e}"}

    # === ODF file parsing: Offline verification ===

    def parse_file_sheets(self, file_path: str | None = None) -> dict:
        """List sheets in an ODS file by parsing content.xml (no UNO needed).

        Example:
            v.parse_file_sheets("/home/user/test.ods")
            => {"sheets": [{"name": "Sheet1", "rows": 10, "cols": 3}], "count": 1}
        """
        if file_path is None:
            file_path = _find_ods_file()
        if file_path is None:
            return {"error": "No ODS file found. Provide file_path."}

        root, err = _parse_ods_content(file_path)
        if err:
            return {"error": err}

        body = root.find("office:body", ODF_NS)
        spreadsheet = body.find("office:spreadsheet", ODF_NS) if body is not None else None
        if spreadsheet is None:
            return {"error": "No spreadsheet content found in file."}

        sheets = []
        for table in spreadsheet.findall("table:table", ODF_NS):
            name = table.get(f"{{{ODF_NS['table']}}}name", "")
            grid = _expand_ods_rows(table)
            # Trim trailing empty rows/cols
            max_col = 0
            non_empty_rows = 0
            for row in grid:
                for ci, cell in enumerate(row):
                    if cell[0] is not None:
                        max_col = max(max_col, ci + 1)
                        non_empty_rows = max(non_empty_rows, grid.index(row) + 1)
            sheets.append({"name": name, "rows": non_empty_rows, "cols": max_col})

        return {"sheets": sheets, "count": len(sheets), "file": file_path}

    def parse_file_cell(self, cell_ref: str, file_path: str | None = None,
                        sheet_name: str | None = None) -> dict:
        """Read a cell value from an ODS file without UNO (parses content.xml).

        Example:
            v.parse_file_cell("A1", "/home/user/test.ods")
            => {"cell": "A1", "value": 42, "display": "42", "type": "float"}
        """
        if file_path is None:
            file_path = _find_ods_file()
        if file_path is None:
            return {"error": "No ODS file found. Provide file_path."}

        try:
            col, row = _parse_cell_ref(cell_ref)
        except ValueError as e:
            return {"error": str(e)}

        root, err = _parse_ods_content(file_path)
        if err:
            return {"error": err}

        body = root.find("office:body", ODF_NS)
        spreadsheet = body.find("office:spreadsheet", ODF_NS) if body is not None else None
        if spreadsheet is None:
            return {"error": "No spreadsheet content found."}

        tables = spreadsheet.findall("table:table", ODF_NS)
        target_table = None
        if sheet_name:
            for t in tables:
                if t.get(f"{{{ODF_NS['table']}}}name") == sheet_name:
                    target_table = t
                    break
            if target_table is None:
                return {"error": f"Sheet '{sheet_name}' not found in file."}
        else:
            target_table = tables[0] if tables else None

        if target_table is None:
            return {"error": "No sheets found in file."}

        grid = _expand_ods_rows(target_table)
        if row >= len(grid) or col >= len(grid[row]):
            return {"cell": cell_ref.upper(), "value": None, "display": "", "type": "empty"}

        value, display, attrs = grid[row][col]
        return {
            "cell": cell_ref.upper(),
            "value": value,
            "display": display,
            "type": attrs.get("type", "empty"),
            "formula": attrs.get("formula"),
            "sheet": target_table.get(f"{{{ODF_NS['table']}}}name", ""),
            "file": file_path,
        }

    def parse_file_range(self, range_ref: str, file_path: str | None = None,
                         sheet_name: str | None = None) -> dict:
        """Read a range of cell values from an ODS file without UNO.

        Example:
            v.parse_file_range("A1:B2", "/home/user/test.ods")
            => {"range": "A1:B2", "data": [[1, "Name"], [2, "Alice"]], "rows": 2, "cols": 2}
        """
        if file_path is None:
            file_path = _find_ods_file()
        if file_path is None:
            return {"error": "No ODS file found. Provide file_path."}

        try:
            c1, r1, c2, r2 = _parse_range_ref(range_ref)
        except ValueError as e:
            return {"error": str(e)}

        root, err = _parse_ods_content(file_path)
        if err:
            return {"error": err}

        body = root.find("office:body", ODF_NS)
        spreadsheet = body.find("office:spreadsheet", ODF_NS) if body is not None else None
        if spreadsheet is None:
            return {"error": "No spreadsheet content found."}

        tables = spreadsheet.findall("table:table", ODF_NS)
        target_table = None
        if sheet_name:
            for t in tables:
                if t.get(f"{{{ODF_NS['table']}}}name") == sheet_name:
                    target_table = t
                    break
        else:
            target_table = tables[0] if tables else None

        if target_table is None:
            return {"error": "Sheet not found."}

        grid = _expand_ods_rows(target_table)
        data = []
        for r in range(r1, r2 + 1):
            row_data = []
            for c in range(c1, c2 + 1):
                if r < len(grid) and c < len(grid[r]):
                    row_data.append(grid[r][c][0])
                else:
                    row_data.append(None)
            data.append(row_data)

        return {
            "range": range_ref.upper(),
            "data": data,
            "rows": r2 - r1 + 1,
            "cols": c2 - c1 + 1,
            "sheet": target_table.get(f"{{{ODF_NS['table']}}}name", ""),
            "file": file_path,
        }

    # === Composite checks (common RL verification patterns) ===

    def check_cell_value(self, cell_ref: str, expected: str, sheet_name: str | None = None,
                         file_path: str | None = None) -> dict:
        """Check if a cell has the expected value. Tries UNO first, falls back to file parsing.

        Comparison is case-insensitive for strings. Numeric strings are compared as numbers.

        Example:
            v.check_cell_value("A1", "42")
            => {"match": true, "cell": "A1", "expected": "42", "actual": 42}
        """
        # Try UNO first
        result = self.get_cell_value(cell_ref, sheet_name)
        if "error" in result:
            # Fall back to file parsing
            result = self.parse_file_cell(cell_ref, file_path, sheet_name)
        if "error" in result:
            return result

        actual = result.get("value")
        display = result.get("display", "")

        # Smart comparison: try numeric, then string
        match = False
        try:
            expected_num = float(expected)
            if actual is not None:
                match = float(actual) == expected_num
        except (ValueError, TypeError):
            # String comparison (case-insensitive)
            actual_str = str(actual) if actual is not None else ""
            match = actual_str.lower() == expected.lower() or display.lower() == expected.lower()

        return {
            "match": match,
            "cell": cell_ref.upper(),
            "expected": expected,
            "actual": actual,
            "display": display,
            "sheet": result.get("sheet"),
        }

    def check_sheet_exists(self, sheet_name: str, file_path: str | None = None) -> dict:
        """Check if a sheet with the given name exists.

        Example:
            v.check_sheet_exists("Sales Data")
            => {"exists": true, "sheet": "Sales Data", "index": 1}
        """
        # Try UNO
        result = self.get_sheets()
        if "error" in result:
            # Fall back to file parsing
            result = self.parse_file_sheets(file_path)
        if "error" in result:
            return result

        for s in result.get("sheets", []):
            if s["name"].lower() == sheet_name.lower():
                return {"exists": True, "sheet": s["name"], "index": s.get("index")}
        return {"exists": False, "sheet": sheet_name, "available": [s["name"] for s in result.get("sheets", [])]}

    def check_sheet_count(self, expected_count: int, file_path: str | None = None) -> dict:
        """Check if the workbook has the expected number of sheets.

        Example:
            v.check_sheet_count(3)
            => {"match": true, "expected": 3, "actual": 3}
        """
        result = self.get_sheets()
        if "error" in result:
            result = self.parse_file_sheets(file_path)
        if "error" in result:
            return result
        actual = result.get("count", 0)
        return {"match": actual == expected_count, "expected": expected_count, "actual": actual}

    def check_cell_formula(self, cell_ref: str, expected_formula: str,
                           sheet_name: str | None = None) -> dict:
        """Check if a cell contains the expected formula.

        Formula comparison ignores leading '=' and is case-insensitive.

        Example:
            v.check_cell_formula("C1", "=A1+B1")
            => {"match": true, "cell": "C1", "expected": "=A1+B1", "actual": "=A1+B1"}
        """
        result = self.get_cell_value(cell_ref, sheet_name)
        if "error" in result:
            return result

        actual = result.get("formula")
        if actual is None:
            return {
                "match": False,
                "cell": cell_ref.upper(),
                "expected": expected_formula,
                "actual": None,
                "reason": "Cell does not contain a formula",
            }

        # Normalize: strip leading =, case-insensitive
        norm_expected = expected_formula.lstrip("=").upper().strip()
        norm_actual = actual.lstrip("=").upper().strip()

        return {
            "match": norm_expected == norm_actual,
            "cell": cell_ref.upper(),
            "expected": expected_formula,
            "actual": actual,
            "sheet": result.get("sheet"),
        }

    def _parse_file_cell_format(self, cell_ref: str, file_path: str | None = None,
                               sheet_name: str | None = None) -> dict:
        """Get basic formatting from ODF file (bold/italic from style)."""
        if file_path is None:
            file_path = _find_ods_file()
        if file_path is None:
            return {"error": "No ODS file found."}

        try:
            col, row = _parse_cell_ref(cell_ref)
        except ValueError as e:
            return {"error": str(e)}

        root, err = _parse_ods_content(file_path)
        if err:
            return {"error": err}

        # Build style map from automatic-styles
        styles = {}
        for auto_styles in root.findall("office:automatic-styles", ODF_NS):
            for style_elem in auto_styles.findall("style:style", ODF_NS):
                sname = style_elem.get(f"{{{ODF_NS['style']}}}name")
                if sname:
                    text_props = style_elem.find("style:text-properties", ODF_NS)
                    cell_props = style_elem.find("style:table-cell-properties", ODF_NS)
                    s = {}
                    if text_props is not None:
                        fw = text_props.get(f"{{{ODF_NS['fo']}}}font-weight")
                        s["bold"] = fw == "bold" if fw else False
                        fs = text_props.get(f"{{{ODF_NS['fo']}}}font-style")
                        s["italic"] = fs == "italic" if fs else False
                        fn = text_props.get(f"{{{ODF_NS['style']}}}font-name")
                        if fn:
                            s["font_name"] = fn
                        fsize = text_props.get(f"{{{ODF_NS['fo']}}}font-size")
                        if fsize:
                            s["font_size"] = fsize
                        fc = text_props.get(f"{{{ODF_NS['fo']}}}color")
                        if fc:
                            s["font_color"] = fc.upper()
                    if cell_props is not None:
                        bg = cell_props.get(f"{{{ODF_NS['fo']}}}background-color")
                        if bg:
                            s["bg_color"] = bg.upper()
                    styles[sname] = s

        body = root.find("office:body", ODF_NS)
        spreadsheet = body.find("office:spreadsheet", ODF_NS) if body is not None else None
        if spreadsheet is None:
            return {"error": "No spreadsheet content."}

        tables = spreadsheet.findall("table:table", ODF_NS)
        target = None
        if sheet_name:
            for t in tables:
                if t.get(f"{{{ODF_NS['table']}}}name") == sheet_name:
                    target = t
                    break
        else:
            target = tables[0] if tables else None
        if target is None:
            return {"error": "Sheet not found."}

        grid = _expand_ods_rows(target)
        if row >= len(grid) or col >= len(grid[row]):
            return {"cell": cell_ref.upper(), "bold": False, "italic": False}

        _, _, attrs = grid[row][col]
        style_name = attrs.get("style")
        fmt = styles.get(style_name, {}) if style_name else {}
        return {
            "cell": cell_ref.upper(),
            "bold": fmt.get("bold", False),
            "italic": fmt.get("italic", False),
            "font_name": fmt.get("font_name"),
            "font_size": fmt.get("font_size"),
            "font_color": fmt.get("font_color"),
            "bg_color": fmt.get("bg_color"),
        }

    def check_cell_formatted(self, cell_ref: str, bold: bool | None = None,
                             italic: bool | None = None, font_name: str | None = None,
                             font_size: float | None = None, font_color: str | None = None,
                             bg_color: str | None = None, number_format: str | None = None,
                             sheet_name: str | None = None,
                             file_path: str | None = None) -> dict:
        """Check if a cell has specific formatting properties.

        Only checks properties that are explicitly provided (non-None).

        Example:
            v.check_cell_formatted("A1", bold=True, font_size=14)
            => {"match": true, "cell": "A1", "checks": {"bold": {"expected": true, "actual": true, "ok": true}, ...}}
        """
        result = self.get_cell_format(cell_ref, sheet_name)
        if "error" in result:
            # Fall back to ODF parsing for basic formatting
            result = self._parse_file_cell_format(cell_ref, file_path, sheet_name)
        if "error" in result:
            return result

        checks = {}
        all_match = True

        def _check(key, expected, actual):
            nonlocal all_match
            if expected is None:
                return
            if isinstance(expected, str) and isinstance(actual, str):
                ok = expected.upper() == actual.upper()
            else:
                ok = expected == actual
            checks[key] = {"expected": expected, "actual": actual, "ok": ok}
            if not ok:
                all_match = False

        _check("bold", bold, result.get("bold"))
        _check("italic", italic, result.get("italic"))
        _check("font_name", font_name, result.get("font_name"))
        _check("font_size", font_size, result.get("font_size"))
        _check("font_color", font_color, result.get("font_color"))
        _check("bg_color", bg_color, result.get("bg_color"))
        _check("number_format", number_format, result.get("number_format"))

        return {"match": all_match, "cell": cell_ref.upper(), "checks": checks}

    def check_range_values(self, range_ref: str, expected: list[list],
                           sheet_name: str | None = None, file_path: str | None = None) -> dict:
        """Check if a range of cells matches expected values.

        Example:
            v.check_range_values("A1:B2", [[1, "Name"], [2, "Alice"]])
            => {"match": true, "range": "A1:B2", "mismatches": []}
        """
        result = self.get_range_values(range_ref, sheet_name)
        if "error" in result:
            result = self.parse_file_range(range_ref, file_path, sheet_name)
        if "error" in result:
            return result

        actual = result.get("data", [])
        mismatches = []
        all_match = True

        for ri, (exp_row, act_row) in enumerate(zip(expected, actual)):
            for ci, (exp_val, act_val) in enumerate(zip(exp_row, act_row)):
                match = False
                try:
                    if exp_val is None and act_val is None:
                        match = True
                    elif exp_val is not None and act_val is not None:
                        match = float(exp_val) == float(act_val)
                except (ValueError, TypeError):
                    match = str(exp_val).lower() == str(act_val).lower()
                if not match:
                    all_match = False
                    cell_name = f"{_index_to_col_name(_parse_range_ref(range_ref)[0] + ci)}{_parse_range_ref(range_ref)[1] + ri + 1}"
                    mismatches.append({"cell": cell_name, "expected": exp_val, "actual": act_val})

        return {"match": all_match, "range": range_ref.upper(), "mismatches": mismatches}

    def check_column_sorted(self, col_ref: str, ascending: bool = True,
                            start_row: int = 1, end_row: int | None = None,
                            sheet_name: str | None = None,
                            file_path: str | None = None) -> dict:
        """Check if a column is sorted.

        Example:
            v.check_column_sorted("A", ascending=True, start_row=2)
            => {"sorted": true, "column": "A", "direction": "ascending", "rows_checked": 10}
        """
        col_idx = _col_name_to_index(col_ref)
        values = []

        # Try UNO first
        _, doc, err = _get_uno_doc()
        if not err:
            try:
                sheet, serr = _get_uno_sheet(doc, sheet_name)
                if not serr:
                    cursor = sheet.createCursor()
                    cursor.gotoEndOfUsedArea(False)
                    max_row = cursor.getRangeAddress().EndRow

                    if end_row is None:
                        end_row = max_row + 1

                    for r in range(start_row - 1, min(end_row, max_row + 1)):
                        cell = sheet.getCellByPosition(col_idx, r)
                        ct_str = str(cell.getType())
                        if "EMPTY" in ct_str:
                            continue
                        elif "VALUE" in ct_str or "FORMULA" in ct_str:
                            # For VALUE and FORMULA cells, try numeric value first
                            v = cell.getValue()
                            s = cell.getString()
                            if v != 0 or s == "0":
                                values.append(v)
                            else:
                                values.append(s)
                        else:
                            values.append(cell.getString())
            except Exception:
                values = []

        # Fallback to ODF parsing
        if not values:
            if file_path is None:
                file_path = _find_ods_file()
            if file_path:
                root, perr = _parse_ods_content(file_path)
                if root is not None:
                    body = root.find("office:body", ODF_NS)
                    spreadsheet = body.find("office:spreadsheet", ODF_NS) if body is not None else None
                    if spreadsheet is not None:
                        tables = spreadsheet.findall("table:table", ODF_NS)
                        target = None
                        if sheet_name:
                            for t in tables:
                                if t.get(f"{{{ODF_NS['table']}}}name") == sheet_name:
                                    target = t
                                    break
                        else:
                            target = tables[0] if tables else None
                        if target is not None:
                            grid = _expand_ods_rows(target)
                            max_r = len(grid)
                            if end_row is None:
                                end_row = max_r
                            for r in range(start_row - 1, min(end_row, max_r)):
                                if col_idx < len(grid[r]):
                                    val = grid[r][col_idx][0]
                                    if val is not None:
                                        values.append(val)

        if not values:
            return {"error": "Could not read column data via UNO or file parsing."}

        is_sorted = True
        for i in range(1, len(values)):
            try:
                if ascending and values[i] < values[i - 1]:
                    is_sorted = False
                    break
                elif not ascending and values[i] > values[i - 1]:
                    is_sorted = False
                    break
            except TypeError:
                is_sorted = False
                break

        return {
            "sorted": is_sorted,
            "column": col_ref.upper(),
            "direction": "ascending" if ascending else "descending",
            "rows_checked": len(values),
        }

    def check_file_exists(self, file_path: str) -> dict:
        """Check if a spreadsheet file exists at the given path.

        Example:
            v.check_file_exists("/home/user/report.ods")
            => {"exists": true, "path": "/home/user/report.ods", "size": 12345}
        """
        exists = os.path.exists(file_path)
        result = {"exists": exists, "path": file_path}
        if exists:
            stat = os.stat(file_path)
            result["size"] = stat.st_size
            result["modified"] = stat.st_mtime
        return result

    def check_file_saved(self, file_path: str | None = None) -> dict:
        """Check if the current document has been saved (not modified since last save).

        Example:
            v.check_file_saved()
            => {"saved": true, "path": "file:///home/user/test.ods"}
        """
        _, doc, err = _get_uno_doc()
        if err:
            if file_path:
                return {"saved": os.path.exists(file_path), "path": file_path}
            return {"error": err}

        return {
            "saved": not doc.isModified(),
            "path": doc.getURL(),
            "title": doc.getTitle(),
        }

    def check_merged_cells(self, expected_range: str, sheet_name: str | None = None) -> dict:
        """Check if a specific range is merged.

        Example:
            v.check_merged_cells("A1:C1")
            => {"merged": true, "range": "A1:C1"}
        """
        result = self.get_merged_cells(sheet_name)
        if "error" in result:
            return result

        expected_upper = expected_range.upper()
        found = expected_upper in [m.upper() for m in result.get("merged", [])]
        return {
            "merged": found,
            "range": expected_upper,
            "all_merged": result.get("merged", []),
        }

    # ------------------------------------------------------------------
    # Preference / settings inspection (registrymodifications.xcu)
    # ------------------------------------------------------------------

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

    def get_calc_prefs(self) -> dict:
        """Parse registrymodifications.xcu and return a dict of known Calc-related preferences.

        Returns keys: default_sheet_count, default_save_filter_calc, measurement_unit_calc,
        raw (list of all (path, prop, value) triples).
        """
        root, err = self._load_registry_modifications()
        if err:
            return {"error": err}
        ns = "{http://openoffice.org/2001/registry}"
        result = {
            "default_sheet_count": None,
            "default_save_filter_calc": None,
            "measurement_unit_calc": None,
            "raw": [],
        }
        for item in root.findall(f"{ns}item"):
            path = item.get(f"{ns}path", "")
            for prop in item.findall(f"{ns}prop"):
                prop_name = prop.get(f"{ns}name", "")
                value_elem = prop.find(f"{ns}value")
                value_text = None
                if value_elem is not None:
                    value_text = "".join(value_elem.itertext()).strip()
                result["raw"].append({"path": path, "prop": prop_name, "value": value_text})
                # Default sheet count for new workbooks
                if "Defaults/Sheet" in path and prop_name == "SheetCount":
                    try:
                        result["default_sheet_count"] = int(value_text) if value_text else None
                    except ValueError:
                        result["default_sheet_count"] = value_text
                # Default save filter for Calc documents
                if "Save/Document" in path and prop_name == "Calc":
                    result["default_save_filter_calc"] = value_text
                # Measurement unit for Calc
                if "Layout/Other/MeasureUnit" in path and "Calc" in path:
                    result["measurement_unit_calc"] = value_text
        return result

    def check_calc_pref(self, key: str, expected: str) -> dict:
        """Check a Calc preference by well-known key.

        Supported keys:
          - default_sheet_count
          - default_save_filter_calc
          - measurement_unit_calc
        """
        prefs = self.get_calc_prefs()
        if "error" in prefs:
            return {"match": False, **prefs}
        actual = prefs.get(key)
        match = False
        if actual is not None:
            if key == "default_sheet_count":
                try:
                    match = int(actual) == int(expected)
                except Exception:
                    match = False
            elif key == "default_save_filter_calc":
                # Accept any variant that includes the expected substring (case-insensitive)
                match = expected.lower() in str(actual).lower()
            elif key == "measurement_unit_calc":
                # Numeric representation (e.g. "2" for Inch) or string like "INCH"
                match = str(actual).strip().lower() == str(expected).strip().lower()
            else:
                match = str(actual) == str(expected)
        return {"match": match, "key": key, "expected": expected, "actual": actual}

    # ------------------------------------------------------------------
    # Conditional formatting
    # ------------------------------------------------------------------

    def check_conditional_format(self, range_ref: str, sheet_name: str | None = None) -> dict:
        """Check whether any conditional-formatting rule exists on cells within range_ref.

        Uses UNO ConditionalFormats on the sheet, iterating each CF and checking
        if its range intersects with the requested range.
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        sheet, err = _get_uno_sheet(doc, sheet_name)
        if err:
            return {"error": err}
        try:
            c1, r1, c2, r2 = _parse_range_ref(range_ref)
        except ValueError as e:
            return {"error": str(e)}
        found = False
        count = 0
        try:
            cfs = sheet.ConditionalFormats  # XConditionalFormats
            items = cfs.ConditionalFormats if hasattr(cfs, "ConditionalFormats") else []
            count = len(items)
            for cf in items:
                try:
                    addresses = cf.Range.RangeAddresses
                except Exception:
                    try:
                        addresses = [cf.Range.RangeAddress]
                    except Exception:
                        addresses = []
                for addr in addresses:
                    if (addr.StartColumn <= c2 and addr.EndColumn >= c1 and
                            addr.StartRow <= r2 and addr.EndRow >= r1):
                        found = True
                        break
                if found:
                    break
        except Exception as e:
            return {"error": f"Could not read conditional formats: {e}"}
        return {"match": found, "range": range_ref.upper(), "cf_count": count}

    # ------------------------------------------------------------------
    # Named ranges
    # ------------------------------------------------------------------

    def check_named_range(self, name: str, expected_content: str | None = None) -> dict:
        """Check whether a named range with the given name exists.

        If expected_content is given, also verify the named range's content/target includes it.
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        try:
            names = doc.getNamedRanges()
            if not names.hasByName(name):
                return {"match": False, "name": name, "exists": False}
            nr = names.getByName(name)
            content = None
            try:
                content = nr.getContent()
            except Exception:
                try:
                    content = nr.Content
                except Exception:
                    content = None
            match = True
            if expected_content:
                match = expected_content.lower() in (content or "").lower()
            return {
                "match": match,
                "name": name,
                "exists": True,
                "content": content,
            }
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Data validation
    # ------------------------------------------------------------------

    def check_data_validation(self, cell_ref: str, sheet_name: str | None = None) -> dict:
        """Check whether a cell has a data-validation rule applied.

        Returns the validation type if present.
        """
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        sheet, err = _get_uno_sheet(doc, sheet_name)
        if err:
            return {"error": err}
        try:
            col, row = _parse_cell_ref(cell_ref)
        except ValueError as e:
            return {"error": str(e)}
        try:
            cell = sheet.getCellByPosition(col, row)
            validation = cell.Validation  # XPropertySet
            vtype = validation.Type  # com.sun.star.sheet.ValidationType
            vtype_str = _enum_val(vtype)
            # 0 = ANY (no validation), others = specific validation
            is_set = False
            try:
                is_set = int(vtype_str) != 0
            except Exception:
                is_set = str(vtype_str).upper() not in ("ANY", "0")
            return {
                "match": is_set,
                "cell": cell_ref.upper(),
                "type": str(vtype_str),
                "formula1": getattr(validation, "Formula1", "") or "",
                "formula2": getattr(validation, "Formula2", "") or "",
            }
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # AutoFilter and frozen panes
    # ------------------------------------------------------------------

    def check_autofilter(self, sheet_name: str | None = None) -> dict:
        """Check whether AutoFilter is enabled on the sheet (any database range with AutoFilter=true)."""
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        sheet, err = _get_uno_sheet(doc, sheet_name)
        if err:
            return {"error": err}
        try:
            enabled = False
            db_range = None
            # Check if any database range on this sheet has AutoFilter
            dbr = doc.DatabaseRanges
            for i in range(dbr.Count):
                r = dbr.getByIndex(i)
                addr = r.DataArea
                # DatabaseRanges has Sheet index; compare with this sheet
                try:
                    if addr.Sheet != sheet.getRangeAddress().Sheet:
                        continue
                except Exception:
                    pass
                if getattr(r, "AutoFilter", False):
                    enabled = True
                    db_range = r.Name
                    break
            # Also check sheet-level "Unnamed" autofilter via UnnamedDatabaseRanges
            if not enabled:
                try:
                    udbr = doc.UnnamedDatabaseRanges
                    sheet_idx = sheet.getRangeAddress().Sheet
                    if udbr.hasByTable(sheet_idx):
                        r = udbr.getByTable(sheet_idx)
                        if getattr(r, "AutoFilter", False):
                            enabled = True
                            db_range = "<unnamed>"
                except Exception:
                    pass
            return {"match": enabled, "sheet": sheet.getName(), "db_range": db_range}
        except Exception as e:
            return {"error": str(e)}

    def check_frozen_rows(self, expected_rows: int, sheet_name: str | None = None) -> dict:
        """Check whether the sheet has the first N rows frozen."""
        _, doc, err = _get_uno_doc()
        if err:
            return {"error": err}
        sheet, err = _get_uno_sheet(doc, sheet_name)
        if err:
            return {"error": err}
        try:
            controller = doc.getCurrentController()
            # Activate the requested sheet to read its freeze state
            controller.setActiveSheet(sheet)
            split_row = controller.SplitRow
            is_frozen = bool(controller.IsWindowSplit) or split_row > 0
            match = (split_row == expected_rows) and (split_row > 0)
            return {
                "match": match,
                "sheet": sheet.getName(),
                "split_row": split_row,
                "is_frozen": is_frozen,
            }
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # CSV helpers
    # ------------------------------------------------------------------

    def check_csv_rows(self, file_path: str, expected_rows: int, has_header: bool = True) -> dict:
        """Check that a CSV file exists and contains expected_rows data rows (excluding header if has_header)."""
        if not os.path.exists(file_path):
            return {"match": False, "exists": False, "path": file_path}
        try:
            import csv
            with open(file_path, "r", encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
        except Exception as e:
            return {"error": str(e), "path": file_path}
        total = len(rows)
        data_rows = total - 1 if has_header else total
        return {
            "match": data_rows == expected_rows,
            "path": file_path,
            "total_rows": total,
            "data_rows": data_rows,
            "expected": expected_rows,
        }

    # === File format validation for export formats ===

    def check_file_format(self, file_path: str, expected_format: str) -> dict:
        """Check if a file is in the expected format.

        Example:
            v.check_file_format("/home/user/spreadsheet.xlsx", "xlsx")
            => {"match": true, "expected": "xlsx", "detected": "xlsx"}
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

        Returns: One of 'xlsx', 'xls', 'csv', 'html', 'ods', 'unknown'
        """
        if not os.path.exists(file_path):
            return "unknown"

        try:
            with open(file_path, "rb") as f:
                header = f.read(16)

            # XLSX: ZIP file with xl/worksheets/sheet*.xml
            if header.startswith(b"PK\x03\x04"):
                try:
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        namelist = zip_ref.namelist()
                        # Check for XLSX structure (has xl/worksheets)
                        if any('xl/worksheets/sheet' in name for name in namelist):
                            return "xlsx"
                        # Check for ODS structure (has content.xml)
                        if 'content.xml' in namelist:
                            return "ods"
                except Exception:
                    pass

            # XLS: Specific file header
            if header[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
                return "xls"

            # HTML: Starts with "<!DOCTYPE" or "<html"
            content_start = header[:15].lower()
            if b'<!doctype html' in content_start or b'<html' in content_start:
                return "html"

            # CSV: Check if it's a CSV file by trying to parse it
            try:
                with open(file_path, 'r', encoding='utf-8', newline='') as f:
                    # Try to read as CSV
                    reader = csv.reader(f)
                    first_row = next(reader)
                    # If we can read it and it has commas or tabs, likely CSV
                    if len(first_row) > 1:
                        return "csv"
            except Exception:
                pass

            return "unknown"

        except Exception as e:
            return "unknown"

    def check_xlsx_contains(self, file_path: str, text: str) -> dict:
        """Check if an XLSX file contains specific text.

        Example:
            v.check_xlsx_contains("/home/user/spreadsheet.xlsx", "Total")
            => {"contains": true, "text": "Total", "file": "spreadsheet.xlsx"}
        """
        if not os.path.exists(file_path):
            return {"contains": False, "error": "File not found"}

        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                all_text = []

                # XLSX stores data in xl/sharedStrings.xml (for shared strings)
                # and xl/worksheets/sheet*.xml (for cell data)
                try:
                    # First check shared strings
                    if 'xl/sharedStrings.xml' in zip_ref.namelist():
                        with zip_ref.open('xl/sharedStrings.xml') as strings_file:
                            content = strings_file.read().decode('utf-8', errors='ignore')
                            all_text.append(content)
                except Exception:
                    pass

                # Then check all worksheets
                worksheet_files = [f for f in zip_ref.namelist() if f.startswith('xl/worksheets/sheet')]
                for worksheet_file in worksheet_files:
                    try:
                        with zip_ref.open(worksheet_file) as sheet_file:
                            content = sheet_file.read().decode('utf-8', errors='ignore')
                            all_text.append(content)
                    except Exception:
                        pass

                combined_text = ' '.join(all_text)
                found = text in combined_text
                return {"contains": found, "text": text, "file": file_path}

        except Exception as e:
            return {"contains": False, "error": f"Failed to parse XLSX: {e}"}

    def check_html_contains(self, file_path: str, text: str) -> dict:
        """Check if an HTML file contains specific text.

        Example:
            v.check_html_contains("/home/user/spreadsheet.html", "Total")
            => {"contains": true, "text": "Total", "file": "spreadsheet.html"}
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
    "sheets": ("List all sheets", lambda v, args: v.get_sheets()),
    "active-sheet": ("Get active sheet name", lambda v, args: v.get_active_sheet()),
    "doc-info": ("Get document info", lambda v, args: v.get_document_info()),
    "cell-value": ("Get cell value", lambda v, args: v.get_cell_value(
        args[0], args[1] if len(args) > 1 else None)),
    "range-values": ("Get range values", lambda v, args: v.get_range_values(
        args[0], args[1] if len(args) > 1 else None)),
    "sheet-data": ("Get all sheet data", lambda v, args: v.get_sheet_data(
        args[0] if args else None)),
    "cell-format": ("Get cell formatting", lambda v, args: v.get_cell_format(
        args[0], args[1] if len(args) > 1 else None)),
    "merged-cells": ("Get merged cell ranges", lambda v, args: v.get_merged_cells(
        args[0] if args else None)),

    # ODF file parsing (offline)
    "parse-sheets": ("List sheets from ODS file", lambda v, args: v.parse_file_sheets(
        args[0] if args else None)),
    "parse-cell": ("Read cell from ODS file", lambda v, args: v.parse_file_cell(
        args[0], args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None)),
    "parse-range": ("Read range from ODS file", lambda v, args: v.parse_file_range(
        args[0], args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None)),

    # Composite checks
    "check-cell-value": ("Check cell has expected value", lambda v, args: v.check_cell_value(
        args[0], args[1], args[2] if len(args) > 2 else None)),
    "check-sheet-exists": ("Check sheet exists by name", lambda v, args: v.check_sheet_exists(args[0])),
    "check-sheet-count": ("Check number of sheets", lambda v, args: v.check_sheet_count(int(args[0]))),
    "check-cell-formula": ("Check cell formula", lambda v, args: v.check_cell_formula(
        args[0], args[1], args[2] if len(args) > 2 else None)),
    "check-cell-formatted": ("Check cell formatting", lambda v, args: v.check_cell_formatted(
        args[0], bold=args[1].lower() == "true" if len(args) > 1 else None,
        sheet_name=args[2] if len(args) > 2 else None)),
    "check-column-sorted": ("Check column is sorted", lambda v, args: v.check_column_sorted(
        args[0], ascending=args[1].lower() != "desc" if len(args) > 1 else True,
        start_row=int(args[2]) if len(args) > 2 else 1,
        end_row=int(args[3]) if len(args) > 3 else None,
        sheet_name=args[4] if len(args) > 4 else None)),
    "check-file-exists": ("Check file exists", lambda v, args: v.check_file_exists(args[0])),
    "check-file-saved": ("Check document saved", lambda v, args: v.check_file_saved(
        args[0] if args else None)),
    "check-merged-cells": ("Check if range is merged", lambda v, args: v.check_merged_cells(
        args[0], args[1] if len(args) > 1 else None)),

    # Preferences / settings (reads registrymodifications.xcu)
    "calc-prefs": ("Get Calc user preferences from registrymodifications.xcu",
                   lambda v, args: v.get_calc_prefs()),
    "check-calc-pref": ("Check a Calc preference key against expected value",
                        lambda v, args: v.check_calc_pref(args[0], args[1])),

    # Conditional formatting
    "check-conditional-format": ("Check any conditional format rule exists on a range",
                                 lambda v, args: v.check_conditional_format(
                                     args[0], args[1] if len(args) > 1 else None)),

    # Named ranges
    "check-named-range": ("Check a named range exists (optionally matching expected content)",
                          lambda v, args: v.check_named_range(
                              args[0], args[1] if len(args) > 1 else None)),

    # Data validation
    "check-data-validation": ("Check a cell has a data-validation rule",
                              lambda v, args: v.check_data_validation(
                                  args[0], args[1] if len(args) > 1 else None)),

    # AutoFilter / freeze
    "check-autofilter": ("Check AutoFilter is enabled on a sheet",
                         lambda v, args: v.check_autofilter(args[0] if args else None)),
    "check-frozen-rows": ("Check first N rows are frozen",
                          lambda v, args: v.check_frozen_rows(
                              int(args[0]), args[1] if len(args) > 1 else None)),

    # CSV helper
    "check-csv-rows": ("Check CSV file exists and has expected row count",
                       lambda v, args: v.check_csv_rows(
                           args[0], int(args[1]),
                           has_header=args[2].lower() == "true" if len(args) > 2 else True)),

    # File format validation
    "check-file-format": ("Check file format: <file_path> <expected_format>",
        lambda v, args: v.check_file_format(args[0], args[1])),
    "check-xlsx-contains": ("Check XLSX file contains text: <file_path> <text>",
        lambda v, args: v.check_xlsx_contains(args[0], args[1])),
    "check-html-contains": ("Check HTML file contains text: <file_path> <text>",
        lambda v, args: v.check_html_contains(args[0], args[1])),
}


def _print_usage():
    print("LibreOffice Calc Verifier — query spreadsheet state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nUNO endpoints require LibreOffice running with --accept on port {UNO_PORT}")
    print("ODF parse-* endpoints work on saved .ods files without UNO")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = LibreOfficeCalcVerifier()
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
