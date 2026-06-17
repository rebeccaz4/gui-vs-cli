"""Godot .tres resource writers."""

from pathlib import Path

from cli_anything.godot.core.text_artifacts import (
    godot_value,
    parse_key_values,
    resolve_project_path,
    set_ini_section_key,
)
from cli_anything.godot.utils.godot_backend import validate_project


def create_resource(
    project_path: str,
    resource_path: str,
    resource_type: str,
    properties: tuple[str, ...] | list[str] = (),
    raw: bool = False,
) -> dict:
    """Create a .tres resource file with optional properties."""
    if not validate_project(project_path):
        return {"status": "error", "message": f"Not a Godot project: {project_path}"}

    full_path = resolve_project_path(project_path, resource_path)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    props = parse_key_values(properties)
    lines = [f'[gd_resource type="{resource_type}" format=3]', "", "[resource]"]
    for key, value in props.items():
        lines.append(f"{key} = {godot_value(value, raw=raw)}")
    full_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"status": "ok", "resource": resource_path, "type": resource_type, "properties": props}


def set_resource_property(
    project_path: str,
    resource_path: str,
    prop: str,
    value: str,
    raw: bool = False,
) -> dict:
    """Set a property in the [resource] section of a .tres file."""
    full_path = resolve_project_path(project_path, resource_path)
    if not full_path.exists():
        return {"status": "error", "message": f"Resource not found: {resource_path}"}
    serialized = godot_value(value, raw=raw)
    set_ini_section_key(Path(full_path), "resource", prop, serialized)
    return {"status": "ok", "resource": resource_path, "prop": prop, "value": serialized}
