"""Local Obsidian vault artifact helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONFIG_FILES = {
    "app": "app.json",
    "appearance": "appearance.json",
    "hotkeys": "hotkeys.json",
    "workspace": "workspace.json",
    "workspace-v2": "workspace-v2.json",
    "bookmarks": "bookmarks.json",
    "starred": "starred.json",
    "community-plugins": "community-plugins.json",
    "core-plugins": "core-plugins.json",
}


def _vault(vault_path: str) -> Path:
    path = Path(vault_path).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    (path / ".obsidian").mkdir(parents=True, exist_ok=True)
    return path


def _note_path(vault_path: str, note_path: str) -> Path:
    vault = _vault(vault_path)
    rel = Path(note_path)
    if rel.suffix != ".md":
        rel = rel.with_suffix(".md")
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _parse_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"path": str(path), "data": data}


def _config_path(vault_path: str, name: str) -> Path:
    filename = CONFIG_FILES.get(name, name)
    if not filename.endswith(".json"):
        filename = f"{filename}.json"
    return _vault(vault_path) / ".obsidian" / filename


def init_vault(vault_path: str) -> dict:
    vault = _vault(vault_path)
    return {"vault": str(vault), "config_dir": str(vault / ".obsidian")}


def write_note(vault_path: str, note_path: str, content: str = "", input_file: str | None = None) -> dict:
    if input_file:
        content = Path(input_file).read_text(encoding="utf-8")
    path = _note_path(vault_path, note_path)
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "size": path.stat().st_size}


def append_note(vault_path: str, note_path: str, content: str, position: str = "end") -> dict:
    path = _note_path(vault_path, note_path)
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    new_content = content + current if position == "beginning" else current + content
    path.write_text(new_content, encoding="utf-8")
    return {"path": str(path), "size": path.stat().st_size}


def make_folder(vault_path: str, folder: str) -> dict:
    path = _vault(vault_path) / folder
    path.mkdir(parents=True, exist_ok=True)
    return {"path": str(path), "exists": path.exists()}


def write_file(path: str, content: str = "", input_file: str | None = None) -> dict:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if input_file:
        content = Path(input_file).read_text(encoding="utf-8")
    target.write_text(content, encoding="utf-8")
    return {"path": str(target), "size": target.stat().st_size}


def config_write(vault_path: str, name: str, json_text: str | None = None, input_file: str | None = None) -> dict:
    if input_file:
        data = json.loads(Path(input_file).read_text(encoding="utf-8"))
    elif json_text:
        data = json.loads(json_text)
    else:
        data = {}
    return _write_json(_config_path(vault_path, name), data)


def config_set(vault_path: str, name: str, key: str, value: str) -> dict:
    path = _config_path(vault_path, name)
    data = _read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    data[key] = _parse_value(value)
    return _write_json(path, data)


def plugin_enable(vault_path: str, plugin_id: str, plugin_type: str = "community", enabled: bool = True) -> dict:
    if plugin_type == "community":
        path = _config_path(vault_path, "community-plugins")
        plugins = _read_json(path, [])
        if not isinstance(plugins, list):
            plugins = []
        if enabled and plugin_id not in plugins:
            plugins.append(plugin_id)
        if not enabled:
            plugins = [p for p in plugins if p != plugin_id]
        return _write_json(path, plugins)

    path = _config_path(vault_path, "core-plugins")
    plugins = _read_json(path, {})
    if isinstance(plugins, list):
        plugins = {p: True for p in plugins}
    if not isinstance(plugins, dict):
        plugins = {}
    plugins[plugin_id] = bool(enabled)
    return _write_json(path, plugins)


def plugin_setting(vault_path: str, plugin_id: str, key: str, value: str) -> dict:
    path = _vault(vault_path) / ".obsidian" / "plugins" / plugin_id / "data.json"
    data = _read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    data[key] = _parse_value(value)
    return _write_json(path, data)


def hotkey_set(vault_path: str, command_id: str, key: str, modifiers: tuple[str, ...]) -> dict:
    path = _config_path(vault_path, "hotkeys")
    data = _read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    data[command_id] = [{"modifiers": list(modifiers), "key": key}]
    return _write_json(path, data)


def bookmark_add(vault_path: str, path_value: str, item_type: str = "file") -> dict:
    path = _config_path(vault_path, "bookmarks")
    data = _read_json(path, {"items": []})
    if not isinstance(data, dict):
        data = {"items": []}
    items = data.setdefault("items", [])
    items.append({"type": item_type, "path": path_value})
    return _write_json(path, data)


def workspace_set(vault_path: str, active: str | None = None, json_text: str | None = None) -> dict:
    if json_text:
        data = json.loads(json_text)
    else:
        path = _config_path(vault_path, "workspace")
        data = _read_json(path, {})
        if not isinstance(data, dict):
            data = {}
        if active is not None:
            data["active"] = active
    return _write_json(_config_path(vault_path, "workspace"), data)


def global_config_set(key: str, value: str, config_path: str | None = None) -> dict:
    path = Path(config_path).expanduser() if config_path else Path.home() / ".config" / "obsidian" / "obsidian.json"
    data = _read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    data[key] = _parse_value(value)
    return _write_json(path, data)
