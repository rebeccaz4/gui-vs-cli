"""LibreOffice CLI - Calc (spreadsheet) module."""

from typing import Dict, Any, List, Optional


def _ensure_calc(project: Dict[str, Any]) -> None:
    """Ensure the project is a Calc document."""
    if project.get("type") != "calc":
        raise ValueError(
            f"Document type is '{project.get('type')}', expected 'calc'."
        )
    if "sheets" not in project:
        project["sheets"] = []


def _get_sheet(project: Dict[str, Any], sheet: int) -> Dict[str, Any]:
    """Get a sheet by index."""
    sheets = project.get("sheets", [])
    if sheet < 0 or sheet >= len(sheets):
        raise IndexError(
            f"Sheet index {sheet} out of range (0-{len(sheets) - 1})"
        )
    return sheets[sheet]


def _validate_cell_ref(ref: str) -> str:
    """Validate and normalize a cell reference like 'A1', 'B12'."""
    ref = ref.upper().strip()
    col = ""
    row = ""
    for ch in ref:
        if ch.isalpha():
            if row:
                raise ValueError(f"Invalid cell reference: {ref}")
            col += ch
        elif ch.isdigit():
            row += ch
        else:
            raise ValueError(f"Invalid cell reference: {ref}")
    if not col or not row:
        raise ValueError(f"Invalid cell reference: {ref}")
    row_num = int(row)
    if row_num < 1:
        raise ValueError(f"Row number must be >= 1, got {row_num}")
    return col + row


def add_sheet(
    project: Dict[str, Any],
    name: str = "Sheet",
    position: Optional[int] = None,
) -> Dict[str, Any]:
    """Add a new sheet to the spreadsheet."""
    _ensure_calc(project)
    sheets = project["sheets"]

    # Check for duplicate names
    existing = [s["name"] for s in sheets]
    if name in existing:
        raise ValueError(f"Sheet name '{name}' already exists.")

    sheet = {"name": name, "cells": {}}

    if position is not None:
        if position < 0 or position > len(sheets):
            raise IndexError(
                f"Position {position} out of range (0-{len(sheets)})"
            )
        sheets.insert(position, sheet)
    else:
        sheets.append(sheet)

    return sheet


def remove_sheet(
    project: Dict[str, Any],
    sheet: int,
) -> Dict[str, Any]:
    """Remove a sheet by index."""
    _ensure_calc(project)
    sheets = project["sheets"]
    if not sheets:
        raise ValueError("No sheets to remove.")
    if len(sheets) <= 1:
        raise ValueError("Cannot remove the last sheet.")
    if sheet < 0 or sheet >= len(sheets):
        raise IndexError(
            f"Sheet index {sheet} out of range (0-{len(sheets) - 1})"
        )
    return sheets.pop(sheet)


def rename_sheet(
    project: Dict[str, Any],
    sheet: int,
    name: str,
) -> Dict[str, Any]:
    """Rename a sheet."""
    _ensure_calc(project)
    s = _get_sheet(project, sheet)
    # Check for duplicate names
    existing = [
        sh["name"] for i, sh in enumerate(project["sheets"]) if i != sheet
    ]
    if name in existing:
        raise ValueError(f"Sheet name '{name}' already exists.")
    s["name"] = name
    return s


def set_cell(
    project: Dict[str, Any],
    ref: str,
    value: Any,
    cell_type: str = "string",
    sheet: int = 0,
    formula: Optional[str] = None,
) -> Dict[str, Any]:
    """Set a cell value."""
    _ensure_calc(project)
    ref = _validate_cell_ref(ref)
    s = _get_sheet(project, sheet)

    if "cells" not in s:
        s["cells"] = {}

    cell_data = {"value": value, "type": cell_type}
    if formula:
        cell_data["formula"] = formula
    if cell_type == "float":
        try:
            cell_data["value"] = float(value)
        except (ValueError, TypeError):
            raise ValueError(f"Cannot convert '{value}' to float")

    s["cells"][ref] = cell_data
    return {"ref": ref, "sheet": sheet, **cell_data}


def format_cell(
    project: Dict[str, Any],
    ref: str,
    sheet: int = 0,
    bold: bool = False,
    italic: bool = False,
    font_color: Optional[str] = None,
    bg_color: Optional[str] = None,
) -> Dict[str, Any]:
    """Set verifier-relevant cell formatting in project state."""
    _ensure_calc(project)
    ref = _validate_cell_ref(ref)
    s = _get_sheet(project, sheet)
    cells = s.setdefault("cells", {})
    cell = cells.setdefault(ref, {"value": "", "type": "string"})
    style = cell.setdefault("style", {})
    style["bold"] = bool(bold)
    style["italic"] = bool(italic)
    if font_color is not None:
        style["font_color"] = font_color
    if bg_color is not None:
        style["bg_color"] = bg_color
    return {"ref": ref, "sheet": sheet, "style": style}


def merge_cells(project: Dict[str, Any], range_ref: str, sheet: int = 0) -> Dict[str, Any]:
    """Record a merged cell range in project state."""
    _ensure_calc(project)
    s = _get_sheet(project, sheet)
    merged = s.setdefault("merged_cells", [])
    rng = range_ref.upper()
    if rng not in merged:
        merged.append(rng)
    return {"sheet": sheet, "range": rng, "merged": True}


def add_named_range(project: Dict[str, Any], name: str, target: str) -> Dict[str, Any]:
    """Record a workbook named range."""
    _ensure_calc(project)
    ranges = project.setdefault("named_ranges", {})
    ranges[name] = target
    return {"name": name, "target": target}


def add_data_validation(
    project: Dict[str, Any],
    range_ref: str,
    formula: str,
    sheet: int = 0,
    validation_type: str = "list",
) -> Dict[str, Any]:
    """Record a data-validation rule in project state."""
    _ensure_calc(project)
    s = _get_sheet(project, sheet)
    rules = s.setdefault("data_validations", [])
    rule = {
        "range": range_ref.upper(),
        "formula": formula,
        "type": validation_type,
    }
    rules.append(rule)
    return {"sheet": sheet, **rule}


def add_conditional_format(
    project: Dict[str, Any],
    range_ref: str,
    sheet: int = 0,
    formula: str = "TRUE()",
) -> Dict[str, Any]:
    """Record a conditional-formatting rule in project state."""
    _ensure_calc(project)
    s = _get_sheet(project, sheet)
    rules = s.setdefault("conditional_formats", [])
    rule = {"range": range_ref.upper(), "formula": formula}
    rules.append(rule)
    return {"sheet": sheet, **rule}


def add_autofilter(project: Dict[str, Any], range_ref: str, sheet: int = 0) -> Dict[str, Any]:
    """Record an autofilter range in project state."""
    _ensure_calc(project)
    s = _get_sheet(project, sheet)
    s["autofilter"] = range_ref.upper()
    return {"sheet": sheet, "range": range_ref.upper()}


def freeze_rows(project: Dict[str, Any], rows: int, sheet: int = 0) -> Dict[str, Any]:
    """Record frozen rows in project state."""
    _ensure_calc(project)
    s = _get_sheet(project, sheet)
    s["frozen_rows"] = int(rows)
    return {"sheet": sheet, "rows": int(rows)}


def set_active_sheet(project: Dict[str, Any], sheet: int = 0) -> Dict[str, Any]:
    """Record the active sheet index in project state."""
    _ensure_calc(project)
    _get_sheet(project, sheet)
    project["active_sheet"] = int(sheet)
    return {"sheet": int(sheet)}


def get_cell(
    project: Dict[str, Any],
    ref: str,
    sheet: int = 0,
) -> Dict[str, Any]:
    """Get a cell value."""
    _ensure_calc(project)
    ref = _validate_cell_ref(ref)
    s = _get_sheet(project, sheet)
    cells = s.get("cells", {})
    if ref not in cells:
        return {"ref": ref, "sheet": sheet, "value": None, "type": "empty"}
    cell = cells[ref]
    return {"ref": ref, "sheet": sheet, **cell}


def clear_cell(
    project: Dict[str, Any],
    ref: str,
    sheet: int = 0,
) -> Dict[str, Any]:
    """Clear a cell."""
    _ensure_calc(project)
    ref = _validate_cell_ref(ref)
    s = _get_sheet(project, sheet)
    cells = s.get("cells", {})
    if ref in cells:
        removed = cells.pop(ref)
        return {"ref": ref, "sheet": sheet, "cleared": True, **removed}
    return {"ref": ref, "sheet": sheet, "cleared": False}


def list_sheets(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    """List all sheets with their indices and cell counts."""
    _ensure_calc(project)
    result = []
    for i, sheet in enumerate(project.get("sheets", [])):
        result.append({
            "index": i,
            "name": sheet.get("name", f"Sheet{i+1}"),
            "cell_count": len(sheet.get("cells", {})),
        })
    return result


def get_sheet_data(
    project: Dict[str, Any],
    sheet: int = 0,
) -> Dict[str, Any]:
    """Get all data in a sheet."""
    _ensure_calc(project)
    s = _get_sheet(project, sheet)
    return {
        "name": s.get("name", "Sheet"),
        "cells": s.get("cells", {}),
        "cell_count": len(s.get("cells", {})),
    }
