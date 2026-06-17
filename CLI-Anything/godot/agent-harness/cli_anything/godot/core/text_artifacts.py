"""Helpers for writing Godot 4 text artifacts.

Godot stores projects, scenes, scripts, and resources as text. These helpers
perform small deterministic edits that preserve enough structure for Godot's
parser and the verifier to read the resulting files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable


RAW_PREFIXES = (
    "PackedStringArray(",
    "Vector2(",
    "Vector3(",
    "Color(",
    "NodePath(",
    "ExtResource(",
    "SubResource(",
    "Object(",
    "Resource(",
)


def resolve_project_path(project_path: str, relative_or_abs: str) -> Path:
    path = Path(relative_or_abs)
    if path.is_absolute():
        return path
    return Path(project_path) / path


def as_res_path(project_path: str, relative_or_abs: str) -> str:
    path = Path(relative_or_abs)
    if str(relative_or_abs).startswith("res://"):
        return relative_or_abs
    if path.is_absolute():
        try:
            rel = path.relative_to(Path(project_path))
        except ValueError:
            rel = path.name
    else:
        rel = path
    return "res://" + rel.as_posix()


def godot_value(value: str | int | float | bool | None, raw: bool = False) -> str:
    if raw:
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)

    text = str(value)
    stripped = text.strip()
    if stripped in {"true", "false", "null"}:
        return stripped
    if re.fullmatch(r"-?\d+(\.\d+)?", stripped):
        return stripped
    if stripped.startswith(RAW_PREFIXES):
        return stripped
    if (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    ):
        return stripped
    if len(stripped) >= 2 and stripped[0] == stripped[-1] == '"':
        return stripped
    return json.dumps(text)


def set_ini_section_key(file_path: Path, section: str, key: str, value: str) -> None:
    if file_path.exists():
        lines = file_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    section_header = f"[{section}]"
    section_start = None
    section_end = len(lines)
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == section_header:
            section_start = idx
            continue
        if section_start is not None and idx > section_start and stripped.startswith("[") and stripped.endswith("]"):
            section_end = idx
            break

    new_line = f"{key}={value}"
    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([section_header, "", new_line])
    else:
        for idx in range(section_start + 1, section_end):
            stripped = lines[idx].strip()
            if stripped.startswith(f"{key}="):
                lines[idx] = new_line
                break
        else:
            insert_at = section_end
            while insert_at > section_start + 1 and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines.insert(insert_at, new_line)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def split_scene_sections(text: str) -> list[list[str]]:
    sections: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("[") and line.endswith("]"):
            if current:
                sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append(current)
    return sections


def scene_header_attr(header: str, attr: str) -> str | None:
    match = re.search(rf'{re.escape(attr)}="([^"]*)"', header)
    return match.group(1) if match else None


def write_scene_sections(path: Path, sections: Iterable[Iterable[str]]) -> None:
    chunks = ["\n".join(section).rstrip() for section in sections]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(chunks).rstrip() + "\n", encoding="utf-8")


def set_block_property(section: list[str], prop: str, value: str) -> None:
    new_line = f"{prop} = {value}"
    for idx in range(1, len(section)):
        if section[idx].strip().startswith(f"{prop} "):
            section[idx] = new_line
            return
    section.append(new_line)


def parse_key_values(pairs: tuple[str, ...] | list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in pairs:
        if "=" not in item:
            raise RuntimeError(f"Property must be key=value: {item}")
        key, _, value = item.partition("=")
        parsed[key.strip()] = value.strip()
    return parsed
