"""OBS Studio native artifact writers.

These helpers write the files that OBS itself and the verifier read:
scene collection JSON, profile INI/service files, and global config INI.
"""

from __future__ import annotations

import configparser
import json
import os
from pathlib import Path
from typing import Any


def _config_dir(config_dir: str | None = None) -> Path:
    return Path(config_dir or os.environ.get("OBS_CONFIG_DIR", Path.home() / ".config" / "obs-studio"))


def _scenes_dir(config_dir: str | None = None) -> Path:
    return _config_dir(config_dir) / "basic" / "scenes"


def _profiles_dir(config_dir: str | None = None) -> Path:
    return _config_dir(config_dir) / "basic" / "profiles"


def _collection_path(name_or_path: str, config_dir: str | None = None) -> Path:
    path = Path(name_or_path)
    if path.is_absolute() or path.parent != Path("."):
        return path
    if not name_or_path.endswith(".json"):
        name_or_path = f"{name_or_path}.json"
    return _scenes_dir(config_dir) / name_or_path


def _load_collection(name_or_path: str, config_dir: str | None = None) -> dict[str, Any]:
    path = _collection_path(name_or_path, config_dir)
    if not path.exists():
        raise FileNotFoundError(f"Scene collection not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_collection(data: dict[str, Any], name_or_path: str, config_dir: str | None = None) -> str:
    path = _collection_path(name_or_path, config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return str(path)


def _parse_value(value: str) -> Any:
    lower = value.lower()
    if lower in ("true", "yes", "on"):
        return True
    if lower in ("false", "no", "off"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def parse_pairs(pairs: tuple[str, ...] | list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Invalid key=value pair: {pair}")
        key, value = pair.split("=", 1)
        result[key] = _parse_value(value)
    return result


def create_collection(name: str, path: str | None = None, config_dir: str | None = None) -> dict[str, Any]:
    data = {
        "name": name,
        "current_scene": "",
        "current_program_scene": "",
        "preview_scene": "",
        "current_transition": "",
        "transition_duration": 300,
        "scene_order": [],
        "sources": [],
        "transitions": [],
        "hotkeys": {},
    }
    saved = _save_collection(data, path or name, config_dir)
    return {"path": saved, "name": name}


def _source(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    for src in data.setdefault("sources", []):
        if src.get("name") == name:
            return src
    return None


def _ensure_scene(data: dict[str, Any], scene_name: str) -> dict[str, Any]:
    src = _source(data, scene_name)
    if src is None:
        src = {
            "name": scene_name,
            "id": "scene",
            "versioned_id": "scene",
            "settings": {"items": []},
            "enabled": True,
        }
        data.setdefault("sources", []).append(src)
    src.setdefault("settings", {}).setdefault("items", [])
    order = data.setdefault("scene_order", [])
    if not any((entry.get("name") if isinstance(entry, dict) else entry) == scene_name for entry in order):
        order.append({"name": scene_name})
    if not data.get("current_scene"):
        data["current_scene"] = scene_name
        data["current_program_scene"] = scene_name
    return src


def add_scene(collection: str, scene_name: str, config_dir: str | None = None) -> dict[str, Any]:
    data = _load_collection(collection, config_dir)
    _ensure_scene(data, scene_name)
    path = _save_collection(data, collection, config_dir)
    return {"path": path, "scene": scene_name}


def add_source(
    collection: str,
    source_name: str,
    source_type: str,
    settings: dict[str, Any] | None = None,
    config_dir: str | None = None,
) -> dict[str, Any]:
    data = _load_collection(collection, config_dir)
    src = _source(data, source_name)
    if src is None:
        src = {
            "name": source_name,
            "id": source_type,
            "versioned_id": source_type,
            "settings": settings or {},
            "enabled": True,
            "filters": [],
        }
        data.setdefault("sources", []).append(src)
    else:
        src["id"] = source_type
        src["versioned_id"] = source_type
        src.setdefault("settings", {}).update(settings or {})
    path = _save_collection(data, collection, config_dir)
    return {"path": path, "source": source_name, "type": source_type}


def add_scene_item(
    collection: str,
    scene_name: str,
    source_name: str,
    visible: bool = True,
    locked: bool = False,
    x: float = 0,
    y: float = 0,
    config_dir: str | None = None,
) -> dict[str, Any]:
    data = _load_collection(collection, config_dir)
    scene = _ensure_scene(data, scene_name)
    items = scene.setdefault("settings", {}).setdefault("items", [])
    item = None
    for existing in items:
        if existing.get("name") == source_name:
            item = existing
            break
    if item is None:
        item = {"name": source_name}
        items.append(item)
    item.update({"visible": bool(visible), "locked": bool(locked), "pos": {"x": x, "y": y}})
    path = _save_collection(data, collection, config_dir)
    return {"path": path, "scene": scene_name, "source": source_name}


def set_scene_item(collection: str, source_name: str, visible: bool | None = None, locked: bool | None = None, config_dir: str | None = None) -> dict[str, Any]:
    data = _load_collection(collection, config_dir)
    changed = 0
    for src in data.get("sources", []):
        for item in src.get("settings", {}).get("items", []):
            if item.get("name") == source_name:
                if visible is not None:
                    item["visible"] = bool(visible)
                if locked is not None:
                    item["locked"] = bool(locked)
                changed += 1
    path = _save_collection(data, collection, config_dir)
    return {"path": path, "source": source_name, "changed": changed}


def add_filter(collection: str, source_name: str, filter_name: str, filter_type: str, settings: dict[str, Any] | None = None, enabled: bool = True, config_dir: str | None = None) -> dict[str, Any]:
    data = _load_collection(collection, config_dir)
    src = _source(data, source_name)
    if src is None:
        raise ValueError(f"Source not found: {source_name}")
    filters = src.setdefault("filters", [])
    filt = None
    for existing in filters:
        if existing.get("name") == filter_name:
            filt = existing
            break
    if filt is None:
        filt = {"name": filter_name}
        filters.append(filt)
    filt.update({"id": filter_type, "versioned_id": filter_type, "settings": settings or {}, "enabled": bool(enabled)})
    path = _save_collection(data, collection, config_dir)
    return {"path": path, "source": source_name, "filter": filter_name}


def add_transition(collection: str, name: str, transition_type: str = "fade_transition", settings: dict[str, Any] | None = None, config_dir: str | None = None) -> dict[str, Any]:
    data = _load_collection(collection, config_dir)
    transitions = data.setdefault("transitions", [])
    transition = None
    for existing in transitions:
        if existing.get("name") == name:
            transition = existing
            break
    if transition is None:
        transition = {"name": name}
        transitions.append(transition)
    transition.update({"id": transition_type, "versioned_id": transition_type, "settings": settings or {}})
    path = _save_collection(data, collection, config_dir)
    return {"path": path, "transition": name}


def set_meta(collection: str, key: str, value: Any, config_dir: str | None = None) -> dict[str, Any]:
    data = _load_collection(collection, config_dir)
    data[key] = value
    path = _save_collection(data, collection, config_dir)
    return {"path": path, "key": key, "value": value}


def set_hotkey(collection: str, action: str, binding: str, config_dir: str | None = None) -> dict[str, Any]:
    data = _load_collection(collection, config_dir)
    data.setdefault("hotkeys", {})[action] = [{"key": binding}]
    path = _save_collection(data, collection, config_dir)
    return {"path": path, "action": action}


def set_source_hotkey(collection: str, source_name: str, action: str, binding: str, config_dir: str | None = None) -> dict[str, Any]:
    data = _load_collection(collection, config_dir)
    src = _source(data, source_name)
    if src is None:
        raise ValueError(f"Source not found: {source_name}")
    src.setdefault("hotkeys", {})[action] = [{"key": binding}]
    path = _save_collection(data, collection, config_dir)
    return {"path": path, "source": source_name, "action": action}


def create_profile(profile: str, config_dir: str | None = None) -> dict[str, Any]:
    pdir = _profiles_dir(config_dir) / profile
    pdir.mkdir(parents=True, exist_ok=True)
    ini_path = pdir / "basic.ini"
    if not ini_path.exists():
        ini_path.write_text("", encoding="utf-8")
    return {"profile": profile, "path": str(ini_path)}


def set_profile_value(profile: str, section: str, key: str, value: str, config_dir: str | None = None) -> dict[str, Any]:
    create_profile(profile, config_dir)
    ini_path = _profiles_dir(config_dir) / profile / "basic.ini"
    cfg = configparser.ConfigParser()
    cfg.optionxform = str
    cfg.read(str(ini_path))
    if not cfg.has_section(section):
        cfg.add_section(section)
    cfg.set(section, key, value)
    with open(ini_path, "w", encoding="utf-8") as f:
        cfg.write(f)
    return {"profile": profile, "section": section, "key": key, "value": value, "path": str(ini_path)}


def set_service(profile: str, service: str, server: str = "auto", key: str = "", service_type: str = "rtmp_common", config_dir: str | None = None) -> dict[str, Any]:
    create_profile(profile, config_dir)
    path = _profiles_dir(config_dir) / profile / "service.json"
    data = {"type": service_type, "settings": {"service": service, "server": server, "key": key}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return {"profile": profile, "path": str(path), "service": service}


def set_global_value(section: str, key: str, value: str, config_dir: str | None = None, filename: str = "user.ini") -> dict[str, Any]:
    path = _config_dir(config_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = configparser.ConfigParser()
    cfg.optionxform = str
    cfg.read(str(path))
    if not cfg.has_section(section):
        cfg.add_section(section)
    cfg.set(section, key, value)
    with open(path, "w", encoding="utf-8") as f:
        cfg.write(f)
    return {"path": str(path), "section": section, "key": key, "value": value}

