"""Small XLSX patch helpers for Calc task workflows.

The functions here intentionally edit the OOXML ZIP directly using stdlib XML.
They cover the verifier-facing spreadsheet state used by the Calc tasks:
cells, formulas, bold cell formatting, merged ranges, named ranges, data
validations, and conditional-format placeholders.
"""

from __future__ import annotations

import os
import posixpath
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from copy import deepcopy
from typing import Any


NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

for prefix, uri in NS.items():
    ET.register_namespace("" if prefix == "main" else prefix, uri)


def _n(local: str) -> str:
    return f"{{{NS['main']}}}{local}"


def _r(local: str) -> str:
    return f"{{{NS['rel']}}}{local}"


def _pr(local: str) -> str:
    return f"{{{NS['pkgrel']}}}{local}"


def _col_row(ref: str) -> tuple[str, int]:
    ref = ref.upper().strip()
    col = "".join(ch for ch in ref if ch.isalpha())
    row = "".join(ch for ch in ref if ch.isdigit())
    if not col or not row:
        raise ValueError(f"Invalid cell reference: {ref}")
    return col, int(row)


def _col_index(col: str) -> int:
    value = 0
    for ch in col.upper():
        value = value * 26 + ord(ch) - ord("A") + 1
    return value


def _sheet_path(zf: zipfile.ZipFile, sheet_name: str | None = None, index: int = 0) -> tuple[str, str]:
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.get("Id"): rel.get("Target") for rel in rels.findall(_pr("Relationship"))}
    sheets = wb.find(_n("sheets"))
    if sheets is None:
        raise ValueError("Workbook has no sheets")
    sheet_elems = sheets.findall(_n("sheet"))
    target = None
    if sheet_name:
        for elem in sheet_elems:
            if elem.get("name") == sheet_name:
                target = elem
                break
    else:
        if index < 0 or index >= len(sheet_elems):
            raise IndexError(f"Sheet index {index} out of range")
        target = sheet_elems[index]
    if target is None:
        raise ValueError(f"Sheet not found: {sheet_name}")
    rel_id = target.get(_r("id"))
    path = rel_map.get(rel_id)
    if not path:
        raise ValueError(f"Sheet relationship missing: {rel_id}")
    if not path.startswith("xl/"):
        path = posixpath.normpath(posixpath.join("xl", path))
    return path, target.get("name", "")


def _sheet_paths(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.get("Id"): rel.get("Target") for rel in rels.findall(_pr("Relationship"))}
    sheets = wb.find(_n("sheets"))
    result = []
    if sheets is None:
        return result
    for sheet in sheets.findall(_n("sheet")):
        rel_id = sheet.get(_r("id"))
        path = rel_map.get(rel_id)
        if not path:
            continue
        if not path.startswith("xl/"):
            path = posixpath.normpath(posixpath.join("xl", path))
        result.append((sheet.get("name", "Sheet"), path))
    return result


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    strings = []
    for si in root.findall(_n("si")):
        texts = [t.text or "" for t in si.findall(f".//{_n('t')}")]
        strings.append("".join(texts))
    return strings


def _read_xml(zf: zipfile.ZipFile, path: str) -> ET.Element:
    return ET.fromstring(zf.read(path))


def _write_zip_replace(xlsx_path: str, replacements: dict[str, bytes]) -> None:
    fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    try:
        with zipfile.ZipFile(xlsx_path, "r") as zin, zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            replaced = set()
            for item in zin.infolist():
                if item.filename in replacements:
                    zout.writestr(item, replacements[item.filename])
                    replaced.add(item.filename)
                else:
                    zout.writestr(item, zin.read(item.filename))
            for name, data in replacements.items():
                if name not in replaced:
                    zout.writestr(name, data)
        shutil.move(tmp_path, xlsx_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _xml_bytes(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def import_xlsx(path: str) -> dict[str, Any]:
    """Import workbook sheets and basic cells into CLI JSON project state."""
    with zipfile.ZipFile(path, "r") as zf:
        shared = _shared_strings(zf)
        sheets = []
        for name, sheet_path in _sheet_paths(zf):
            root = _read_xml(zf, sheet_path)
            cells: dict[str, dict[str, Any]] = {}
            for cell in root.findall(f".//{_n('c')}"):
                ref = cell.get("r")
                if not ref:
                    continue
                formula_elem = cell.find(_n("f"))
                value_elem = cell.find(_n("v"))
                inline_text = cell.find(f"{_n('is')}/{_n('t')}")
                value: Any = ""
                cell_type = "string"
                if inline_text is not None:
                    value = inline_text.text or ""
                elif cell.get("t") == "s" and value_elem is not None:
                    idx = int(value_elem.text or 0)
                    value = shared[idx] if 0 <= idx < len(shared) else ""
                elif value_elem is not None:
                    raw = value_elem.text or ""
                    try:
                        value = float(raw)
                        cell_type = "float"
                    except ValueError:
                        value = raw
                cell_data: dict[str, Any] = {"value": value, "type": cell_type}
                if formula_elem is not None:
                    cell_data["formula"] = "=" + (formula_elem.text or "")
                if cell.get("s"):
                    cell_data["style"] = {"style_index": cell.get("s")}
                cells[ref.upper()] = cell_data
            merged = []
            merge_cells = root.find(_n("mergeCells"))
            if merge_cells is not None:
                merged = [m.get("ref", "") for m in merge_cells.findall(_n("mergeCell")) if m.get("ref")]
            sheets.append({"name": name, "cells": cells, "merged_cells": merged})
    return {
        "version": "1.0",
        "name": os.path.splitext(os.path.basename(path))[0],
        "type": "calc",
        "settings": {},
        "styles": {},
        "metadata": {"title": os.path.basename(path), "author": "", "description": "", "subject": ""},
        "sheets": sheets or [{"name": "Sheet1", "cells": {}}],
    }


def _get_or_create_row(sheet: ET.Element, row_num: int) -> ET.Element:
    sheet_data = sheet.find(_n("sheetData"))
    if sheet_data is None:
        sheet_data = ET.SubElement(sheet, _n("sheetData"))
    rows = sheet_data.findall(_n("row"))
    for row in rows:
        if int(row.get("r", "0")) == row_num:
            return row
    row = ET.Element(_n("row"), {"r": str(row_num)})
    inserted = False
    for i, existing in enumerate(rows):
        if int(existing.get("r", "0")) > row_num:
            sheet_data.insert(i, row)
            inserted = True
            break
    if not inserted:
        sheet_data.append(row)
    return row


def _get_or_create_cell(row: ET.Element, ref: str) -> ET.Element:
    col, _ = _col_row(ref)
    target_col = _col_index(col)
    cells = row.findall(_n("c"))
    for cell in cells:
        if cell.get("r", "").upper() == ref.upper():
            return cell
    cell = ET.Element(_n("c"), {"r": ref.upper()})
    inserted = False
    for i, existing in enumerate(cells):
        ex_col = "".join(ch for ch in existing.get("r", "") if ch.isalpha())
        if ex_col and _col_index(ex_col) > target_col:
            row.insert(i, cell)
            inserted = True
            break
    if not inserted:
        row.append(cell)
    return cell


def _clear_cell_contents(cell: ET.Element) -> None:
    for child in list(cell):
        if child.tag in {_n("v"), _n("f"), _n("is")}:
            cell.remove(child)


def set_cell(path: str, ref: str, value: Any, sheet_name: str | None = None,
             sheet_index: int = 0, formula: str | None = None,
             cell_type: str = "string") -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as zf:
        sheet_path, resolved_sheet = _sheet_path(zf, sheet_name, sheet_index)
        sheet = _read_xml(zf, sheet_path)
    col, row_num = _col_row(ref)
    cell_ref = f"{col}{row_num}"
    row = _get_or_create_row(sheet, row_num)
    cell = _get_or_create_cell(row, cell_ref)
    _clear_cell_contents(cell)
    if formula:
        cell.attrib.pop("t", None)
        f = ET.SubElement(cell, _n("f"))
        f.text = formula[1:] if formula.startswith("=") else formula
        if value not in (None, ""):
            v = ET.SubElement(cell, _n("v"))
            v.text = str(value)
    elif cell_type in ("float", "number"):
        cell.attrib.pop("t", None)
        v = ET.SubElement(cell, _n("v"))
        v.text = str(value)
    else:
        cell.set("t", "inlineStr")
        is_elem = ET.SubElement(cell, _n("is"))
        t = ET.SubElement(is_elem, _n("t"))
        t.text = str(value)
    _write_zip_replace(path, {sheet_path: _xml_bytes(sheet)})
    return {"file": path, "sheet": resolved_sheet, "ref": cell_ref, "value": value, "formula": formula}


def _ensure_bold_style(styles: ET.Element) -> int:
    fonts = styles.find(_n("fonts"))
    if fonts is None:
        fonts = ET.SubElement(styles, _n("fonts"), {"count": "0"})
    font_elems = fonts.findall(_n("font"))
    bold_font_id = None
    for i, font in enumerate(font_elems):
        if font.find(_n("b")) is not None:
            bold_font_id = i
            break
    if bold_font_id is None:
        base = deepcopy(font_elems[0]) if font_elems else ET.Element(_n("font"))
        if base.find(_n("b")) is None:
            base.insert(0, ET.Element(_n("b")))
        fonts.append(base)
        bold_font_id = len(font_elems)
        fonts.set("count", str(bold_font_id + 1))

    cell_xfs = styles.find(_n("cellXfs"))
    if cell_xfs is None:
        cell_xfs = ET.SubElement(styles, _n("cellXfs"), {"count": "0"})
    for i, xf in enumerate(cell_xfs.findall(_n("xf"))):
        if xf.get("fontId") == str(bold_font_id):
            return i
    xf = ET.Element(_n("xf"), {"fontId": str(bold_font_id), "fillId": "0", "borderId": "0", "xfId": "0", "applyFont": "1"})
    cell_xfs.append(xf)
    idx = len(cell_xfs.findall(_n("xf"))) - 1
    cell_xfs.set("count", str(idx + 1))
    return idx


def format_cell(path: str, ref: str, sheet_name: str | None = None,
                sheet_index: int = 0, bold: bool = False) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as zf:
        sheet_path, resolved_sheet = _sheet_path(zf, sheet_name, sheet_index)
        sheet = _read_xml(zf, sheet_path)
        styles = _read_xml(zf, "xl/styles.xml")
    if not bold:
        return {"file": path, "sheet": resolved_sheet, "ref": ref.upper(), "bold": False}
    style_idx = _ensure_bold_style(styles)
    _, row_num = _col_row(ref)
    row = _get_or_create_row(sheet, row_num)
    cell = _get_or_create_cell(row, ref.upper())
    cell.set("s", str(style_idx))
    _write_zip_replace(path, {sheet_path: _xml_bytes(sheet), "xl/styles.xml": _xml_bytes(styles)})
    return {"file": path, "sheet": resolved_sheet, "ref": ref.upper(), "bold": True}


def merge_cells(path: str, range_ref: str, sheet_name: str | None = None,
                sheet_index: int = 0) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as zf:
        sheet_path, resolved_sheet = _sheet_path(zf, sheet_name, sheet_index)
        sheet = _read_xml(zf, sheet_path)
    merge_cells_elem = sheet.find(_n("mergeCells"))
    if merge_cells_elem is None:
        merge_cells_elem = ET.Element(_n("mergeCells"))
        sheet.append(merge_cells_elem)
    refs = [m.get("ref", "").upper() for m in merge_cells_elem.findall(_n("mergeCell"))]
    if range_ref.upper() not in refs:
        ET.SubElement(merge_cells_elem, _n("mergeCell"), {"ref": range_ref.upper()})
    merge_cells_elem.set("count", str(len(merge_cells_elem.findall(_n("mergeCell")))))
    _write_zip_replace(path, {sheet_path: _xml_bytes(sheet)})
    return {"file": path, "sheet": resolved_sheet, "range": range_ref.upper(), "merged": True}


def add_named_range(path: str, name: str, target: str) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as zf:
        wb = _read_xml(zf, "xl/workbook.xml")
    defined = wb.find(_n("definedNames"))
    if defined is None:
        defined = ET.Element(_n("definedNames"))
        wb.append(defined)
    for elem in defined.findall(_n("definedName")):
        if elem.get("name") == name:
            elem.text = target
            break
    else:
        elem = ET.SubElement(defined, _n("definedName"), {"name": name})
        elem.text = target
    _write_zip_replace(path, {"xl/workbook.xml": _xml_bytes(wb)})
    return {"file": path, "name": name, "target": target}


def add_data_validation(path: str, range_ref: str, formula: str,
                        sheet_name: str | None = None, sheet_index: int = 0,
                        validation_type: str = "list") -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as zf:
        sheet_path, resolved_sheet = _sheet_path(zf, sheet_name, sheet_index)
        sheet = _read_xml(zf, sheet_path)
    dvs = sheet.find(_n("dataValidations"))
    if dvs is None:
        dvs = ET.Element(_n("dataValidations"))
        sheet.append(dvs)
    dv = ET.SubElement(dvs, _n("dataValidation"), {
        "type": validation_type,
        "allowBlank": "1",
        "showErrorMessage": "1",
        "sqref": range_ref.upper(),
    })
    f1 = ET.SubElement(dv, _n("formula1"))
    f1.text = formula[1:] if formula.startswith("=") else formula
    dvs.set("count", str(len(dvs.findall(_n("dataValidation")))))
    _write_zip_replace(path, {sheet_path: _xml_bytes(sheet)})
    return {"file": path, "sheet": resolved_sheet, "range": range_ref.upper(), "formula": formula}


def add_conditional_format(path: str, range_ref: str, sheet_name: str | None = None,
                           sheet_index: int = 0, formula: str | None = None) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as zf:
        sheet_path, resolved_sheet = _sheet_path(zf, sheet_name, sheet_index)
        sheet = _read_xml(zf, sheet_path)
    cf = ET.Element(_n("conditionalFormatting"), {"sqref": range_ref.upper()})
    rule = ET.SubElement(cf, _n("cfRule"), {"type": "expression", "priority": "1"})
    f = ET.SubElement(rule, _n("formula"))
    f.text = formula or "TRUE()"
    sheet.append(cf)
    _write_zip_replace(path, {sheet_path: _xml_bytes(sheet)})
    return {"file": path, "sheet": resolved_sheet, "range": range_ref.upper()}


def add_autofilter(path: str, range_ref: str, sheet_name: str | None = None,
                   sheet_index: int = 0) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as zf:
        sheet_path, resolved_sheet = _sheet_path(zf, sheet_name, sheet_index)
        sheet = _read_xml(zf, sheet_path)
    auto_filter = sheet.find(_n("autoFilter"))
    if auto_filter is None:
        auto_filter = ET.Element(_n("autoFilter"))
        sheet.append(auto_filter)
    auto_filter.set("ref", range_ref.upper())
    _write_zip_replace(path, {sheet_path: _xml_bytes(sheet)})
    return {"file": path, "sheet": resolved_sheet, "range": range_ref.upper()}


def freeze_rows(path: str, rows: int, sheet_name: str | None = None,
                sheet_index: int = 0) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as zf:
        sheet_path, resolved_sheet = _sheet_path(zf, sheet_name, sheet_index)
        sheet = _read_xml(zf, sheet_path)
    sheet_views = sheet.find(_n("sheetViews"))
    if sheet_views is None:
        sheet_views = ET.Element(_n("sheetViews"))
        sheet.insert(0, sheet_views)
    sheet_view = sheet_views.find(_n("sheetView"))
    if sheet_view is None:
        sheet_view = ET.SubElement(sheet_views, _n("sheetView"), {"workbookViewId": "0"})
    pane = sheet_view.find(_n("pane"))
    if pane is None:
        pane = ET.SubElement(sheet_view, _n("pane"))
    pane.set("ySplit", str(rows))
    pane.set("topLeftCell", f"A{rows + 1}")
    pane.set("activePane", "bottomLeft")
    pane.set("state", "frozen")
    _write_zip_replace(path, {sheet_path: _xml_bytes(sheet)})
    return {"file": path, "sheet": resolved_sheet, "rows": rows}


def set_active_sheet(path: str, sheet_name: str | None = None, sheet_index: int = 0) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as zf:
        wb = _read_xml(zf, "xl/workbook.xml")
        sheets = wb.find(_n("sheets"))
        sheet_elems = sheets.findall(_n("sheet")) if sheets is not None else []
    if sheet_name:
        for idx, sheet in enumerate(sheet_elems):
            if sheet.get("name") == sheet_name:
                sheet_index = idx
                break
        else:
            raise ValueError(f"Sheet not found: {sheet_name}")
    book_views = wb.find(_n("bookViews"))
    if book_views is None:
        book_views = ET.Element(_n("bookViews"))
        wb.insert(0, book_views)
    workbook_view = book_views.find(_n("workbookView"))
    if workbook_view is None:
        workbook_view = ET.SubElement(book_views, _n("workbookView"))
    workbook_view.set("activeTab", str(sheet_index))
    _write_zip_replace(path, {"xl/workbook.xml": _xml_bytes(wb)})
    resolved = sheet_elems[sheet_index].get("name", "") if 0 <= sheet_index < len(sheet_elems) else ""
    return {"file": path, "sheet": resolved, "index": sheet_index}
