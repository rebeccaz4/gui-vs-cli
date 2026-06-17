"""FreeCAD user.cfg preference writer for CLI-Anything."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List


def default_config_path() -> str:
    return os.path.expanduser("~/.config/FreeCAD/user.cfg")


def _param_tag(value_type: str) -> str:
    vt = value_type.lower()
    if vt in {"text", "str", "string"}:
        return "FCText"
    if vt in {"int", "integer"}:
        return "FCInt"
    if vt in {"uint", "unsigned"}:
        return "FCUInt"
    if vt in {"float", "double"}:
        return "FCFloat"
    if vt in {"bool", "boolean"}:
        return "FCBool"
    raise ValueError("value_type must be one of text, int, uint, float, bool")


def _format_value(value: Any, value_type: str) -> str:
    tag = _param_tag(value_type)
    if tag == "FCBool":
        if isinstance(value, str):
            return "true" if value.lower() in {"1", "true", "yes", "on"} else "false"
        return "true" if bool(value) else "false"
    if tag in {"FCInt", "FCUInt"}:
        return str(int(value))
    if tag == "FCFloat":
        return repr(float(value))
    return str(value)


def _load_or_create(path: str) -> ET.ElementTree:
    if os.path.exists(path):
        return ET.parse(path)
    root = ET.Element("FCParameters")
    ET.SubElement(root, "FCParamGroup", {"Name": "Root"})
    return ET.ElementTree(root)


def _root_group(tree: ET.ElementTree) -> ET.Element:
    root = tree.getroot()
    group = root.find("./FCParamGroup[@Name='Root']")
    if group is None:
        group = ET.SubElement(root, "FCParamGroup", {"Name": "Root"})
    return group


def _ensure_group(parent: ET.Element, name: str) -> ET.Element:
    child = parent.find(f"./FCParamGroup[@Name='{name}']")
    if child is None:
        child = ET.SubElement(parent, "FCParamGroup", {"Name": name})
    return child


def set_preference(
    key: str,
    value: Any,
    *,
    value_type: str = "text",
    cfg_path: str | None = None,
) -> Dict[str, Any]:
    """Set a slash-separated FreeCAD preference key in user.cfg."""
    if not isinstance(key, str) or not key.strip() or "/" not in key:
        raise ValueError("Preference key must be a slash-separated path")
    path = os.path.abspath(os.path.expanduser(cfg_path or default_config_path()))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    parts = [p for p in key.strip("/").split("/") if p]
    pref_name = parts[-1]
    tree = _load_or_create(path)
    group = _root_group(tree)
    for part in parts[:-1]:
        group = _ensure_group(group, part)

    tag = _param_tag(value_type)
    formatted = _format_value(value, value_type)
    for existing in list(group):
        if existing.tag.startswith("FC") and existing.get("Name") == pref_name:
            group.remove(existing)
    ET.SubElement(group, tag, {"Name": pref_name, "Value": formatted})
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return {"path": path, "key": key, "value": formatted, "type": tag}


def create_default_config(cfg_path: str | None = None) -> Dict[str, Any]:
    """Create a minimal FreeCAD user.cfg file."""
    path = os.path.abspath(os.path.expanduser(cfg_path or default_config_path()))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        tree = ET.parse(path)
    else:
        root = ET.Element("FCParameters")
        tree = ET.ElementTree(root)
    _root_group(tree)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return {"path": path}


def _find_preference(key: str, cfg_path: str | None = None) -> tuple[str, ET.Element | None]:
    if not isinstance(key, str) or not key.strip() or "/" not in key:
        raise ValueError("Preference key must be a slash-separated path")
    path = os.path.abspath(os.path.expanduser(cfg_path or default_config_path()))
    if not os.path.exists(path):
        return path, None
    parts = [p for p in key.strip("/").split("/") if p]
    pref_name = parts[-1]
    tree = ET.parse(path)
    group = _root_group(tree)
    for part in parts[:-1]:
        group = group.find(f"./FCParamGroup[@Name='{part}']")
        if group is None:
            return path, None
    for child in group:
        if child.tag.startswith("FC") and child.get("Name") == pref_name:
            return path, child
    return path, None


def get_preference(key: str, cfg_path: str | None = None) -> Dict[str, Any]:
    """Get a slash-separated FreeCAD preference key from user.cfg."""
    path, elem = _find_preference(key, cfg_path)
    if elem is None:
        raise KeyError(f"Preference not found: {key}")
    return {
        "path": path,
        "key": key,
        "value": elem.get("Value", ""),
        "type": elem.tag,
    }


def preference_exists(key: str, cfg_path: str | None = None) -> Dict[str, Any]:
    """Check whether a slash-separated FreeCAD preference key exists."""
    path, elem = _find_preference(key, cfg_path)
    return {"path": path, "key": key, "exists": elem is not None}


def list_preferences(cfg_path: str | None = None) -> Dict[str, Any]:
    """List all preferences in a FreeCAD user.cfg file."""
    path = os.path.abspath(os.path.expanduser(cfg_path or default_config_path()))
    if not os.path.exists(path):
        return {"path": path, "preferences": []}
    tree = ET.parse(path)
    root = _root_group(tree)
    result: List[Dict[str, Any]] = []

    def walk(group: ET.Element, prefix: list[str]) -> None:
        for child in group:
            if child.tag == "FCParamGroup":
                walk(child, prefix + [child.get("Name", "")])
            elif child.tag.startswith("FC"):
                result.append({
                    "key": "/".join(prefix + [child.get("Name", "")]),
                    "value": child.get("Value", ""),
                    "type": child.tag,
                })

    walk(root, [])
    return {"path": path, "preferences": result}


def delete_preference(key: str, cfg_path: str | None = None) -> Dict[str, Any]:
    """Delete a slash-separated FreeCAD preference key from user.cfg."""
    if not isinstance(key, str) or not key.strip() or "/" not in key:
        raise ValueError("Preference key must be a slash-separated path")
    path = os.path.abspath(os.path.expanduser(cfg_path or default_config_path()))
    if not os.path.exists(path):
        return {"path": path, "key": key, "deleted": False}
    parts = [p for p in key.strip("/").split("/") if p]
    pref_name = parts[-1]
    tree = ET.parse(path)
    group = _root_group(tree)
    for part in parts[:-1]:
        group = group.find(f"./FCParamGroup[@Name='{part}']")
        if group is None:
            return {"path": path, "key": key, "deleted": False}
    for child in list(group):
        if child.tag.startswith("FC") and child.get("Name") == pref_name:
            group.remove(child)
            tree.write(path, encoding="utf-8", xml_declaration=True)
            return {"path": path, "key": key, "deleted": True}
    return {"path": path, "key": key, "deleted": False}
