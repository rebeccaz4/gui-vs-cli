"""Local Zoom desktop artifacts used by verifier-style tasks."""

from __future__ import annotations

import configparser
import json
import os
from pathlib import Path
from typing import Any


def config_path() -> Path:
    return Path(os.environ.get("ZOOM_CONFIG_PATH", Path.home() / ".config" / "zoomus.conf")).expanduser()


def data_dir() -> Path:
    return Path(os.environ.get("ZOOM_DATA_DIR", Path.home() / ".zoom" / "data")).expanduser()


def logs_dir() -> Path:
    return Path(os.environ.get("ZOOM_LOGS_DIR", Path.home() / ".zoom" / "logs")).expanduser()


def _load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    cfg.optionxform = str  # type: ignore[assignment]
    path = config_path()
    if path.exists():
        cfg.read(path, encoding="utf-8")
    return cfg


def _save_config(cfg: configparser.ConfigParser) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        cfg.write(handle)


def set_config(section: str, key: str, value: str) -> dict[str, Any]:
    cfg = _load_config()
    if not cfg.has_section(section):
        cfg.add_section(section)
    cfg.set(section, key, value)
    _save_config(cfg)
    return {"action": "config_set", "path": str(config_path()), "section": section, "key": key, "value": value}


def seed_config(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    sections = payload.get("sections", payload)
    if not isinstance(sections, dict):
        raise RuntimeError("Zoom config seed must be an object or contain a sections object")
    cfg = _load_config()
    updated = 0
    for section, values in sections.items():
        if not isinstance(values, dict):
            raise RuntimeError(f"Section {section!r} must be an object")
        if not cfg.has_section(str(section)):
            cfg.add_section(str(section))
        for key, value in values.items():
            cfg.set(str(section), str(key), str(value))
            updated += 1
    _save_config(cfg)
    return {"action": "config_seed", "path": str(config_path()), "updated": updated}


def write_data_file(name: str, content: str = "") -> dict[str, Any]:
    target = data_dir() / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"action": "data_write", "path": str(target), "size": target.stat().st_size}


def write_log_file(name: str, content: str = "") -> dict[str, Any]:
    target = logs_dir() / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"action": "log_write", "path": str(target), "size": target.stat().st_size}


def set_recording_path(path: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    result = set_config("General", "localRecordingPath", str(target))
    result["action"] = "recording_set_path"
    result["recording_path"] = str(target)
    return result


def add_recording_file(name: str, content: str = "", path: str | None = None) -> dict[str, Any]:
    if path is None:
        cfg = _load_config()
        if cfg.has_section("General") and cfg.has_option("General", "localRecordingPath"):
            path = cfg.get("General", "localRecordingPath")
    if path is None:
        path = str(Path.home() / "Documents" / "Zoom")
    directory = Path(path).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_text(content, encoding="utf-8")
    return {"action": "recording_add_file", "path": str(target), "size": target.stat().st_size}


def touch_file(path: str, content: str = "") -> dict[str, Any]:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"action": "file_touch", "path": str(target), "size": target.stat().st_size}


def ensure_directory(path: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    return {"action": "directory_ensure", "path": str(target), "exists": target.is_dir()}

