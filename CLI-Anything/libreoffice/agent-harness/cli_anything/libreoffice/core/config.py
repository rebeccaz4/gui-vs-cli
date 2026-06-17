"""LibreOffice user configuration helpers."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


REG_NS = "http://openoffice.org/2001/registry"
ET.register_namespace("oor", REG_NS)


PREF_MAP = {
    "default_sheet_count": (
        "/org.openoffice.Office.Calc/Defaults/Sheet",
        "SheetCount",
    ),
    "default_save_filter_calc": (
        "/org.openoffice.Office.Common/Save/Document",
        "Calc",
    ),
    "measurement_unit_calc": (
        "/org.openoffice.Office.Calc/Layout/Other/MeasureUnit",
        "Calc",
    ),
}


def _config_path(path: str | None = None) -> Path:
    if path:
        return Path(path)
    return Path.home() / ".config" / "libreoffice" / "4" / "user" / "registrymodifications.xcu"


def _load_or_create(path: Path) -> ET.Element:
    if path.exists():
        return ET.parse(str(path)).getroot()
    root = ET.Element(f"{{{REG_NS}}}items")
    return root


def _find_item(root: ET.Element, item_path: str) -> ET.Element | None:
    for item in root.findall(f"{{{REG_NS}}}item"):
        if item.get(f"{{{REG_NS}}}path") == item_path:
            return item
    return None


def set_preference(key: str, value: Any, path: str | None = None) -> dict[str, Any]:
    if key not in PREF_MAP:
        raise ValueError(f"Unknown preference key: {key}. Available: {', '.join(PREF_MAP)}")
    item_path, prop_name = PREF_MAP[key]
    cfg_path = _config_path(path)
    root = _load_or_create(cfg_path)
    item = _find_item(root, item_path)
    if item is None:
        item = ET.SubElement(root, f"{{{REG_NS}}}item", {f"{{{REG_NS}}}path": item_path})
    prop = None
    for candidate in item.findall(f"{{{REG_NS}}}prop"):
        if candidate.get(f"{{{REG_NS}}}name") == prop_name:
            prop = candidate
            break
    if prop is None:
        prop = ET.SubElement(item, f"{{{REG_NS}}}prop", {
            f"{{{REG_NS}}}name": prop_name,
            f"{{{REG_NS}}}op": "fuse",
        })
    value_elem = prop.find(f"{{{REG_NS}}}value")
    if value_elem is None:
        value_elem = ET.SubElement(prop, f"{{{REG_NS}}}value")
    value_elem.text = str(value)
    os.makedirs(cfg_path.parent, exist_ok=True)
    ET.ElementTree(root).write(str(cfg_path), encoding="utf-8", xml_declaration=True)
    return {"path": str(cfg_path), "key": key, "value": value}


def set_registry_value(
    item_path: str,
    prop_name: str,
    value: Any,
    path: str | None = None,
) -> dict[str, Any]:
    """Set an arbitrary LibreOffice registrymodifications.xcu item property."""
    if not item_path or not item_path.startswith("/"):
        raise ValueError("item_path must be an absolute registry path starting with '/'")
    if not prop_name:
        raise ValueError("prop_name must be non-empty")

    cfg_path = _config_path(path)
    root = _load_or_create(cfg_path)
    item = _find_item(root, item_path)
    if item is None:
        item = ET.SubElement(root, f"{{{REG_NS}}}item", {f"{{{REG_NS}}}path": item_path})

    prop = None
    for candidate in item.findall(f"{{{REG_NS}}}prop"):
        if candidate.get(f"{{{REG_NS}}}name") == prop_name:
            prop = candidate
            break
    if prop is None:
        prop = ET.SubElement(item, f"{{{REG_NS}}}prop", {
            f"{{{REG_NS}}}name": prop_name,
            f"{{{REG_NS}}}op": "fuse",
        })

    for existing in list(prop.findall(f"{{{REG_NS}}}value")):
        prop.remove(existing)
    value_elem = ET.SubElement(prop, f"{{{REG_NS}}}value")
    value_elem.text = str(value)

    os.makedirs(cfg_path.parent, exist_ok=True)
    ET.ElementTree(root).write(str(cfg_path), encoding="utf-8", xml_declaration=True)
    return {
        "path": str(cfg_path),
        "item_path": item_path,
        "prop_name": prop_name,
        "value": value,
    }
