"""Godot scene management — create, read, and modify .tscn scene files."""

from pathlib import Path
from cli_anything.godot.utils.godot_backend import validate_project
from cli_anything.godot.core.text_artifacts import (
    as_res_path,
    godot_value,
    parse_key_values,
    resolve_project_path,
    scene_header_attr,
    set_block_property,
    split_scene_sections,
    write_scene_sections,
)


def create_scene(
    project_path: str,
    scene_path: str,
    root_type: str = "Node2D",
    root_name: str | None = None,
) -> dict:
    """Create a new .tscn scene file with a root node.

    Args:
        project_path: Godot project directory.
        scene_path: Relative path for the scene (e.g. 'scenes/Main.tscn').
        root_type: Node type for root (Node2D, Node3D, Control, etc.).
        root_name: Name for the root node; defaults to filename stem.

    Returns:
        Dict with status and created file path.
    """
    if not validate_project(project_path):
        return {"status": "error", "message": f"Not a Godot project: {project_path}"}

    full_path = Path(project_path) / scene_path
    if full_path.exists():
        return {"status": "error", "message": f"Scene already exists: {scene_path}"}

    if root_name is None:
        root_name = full_path.stem

    full_path.parent.mkdir(parents=True, exist_ok=True)

    content = (
        f'[gd_scene format=3 uid="uid://{_generate_uid()}"]\n\n'
        f'[node name="{root_name}" type="{root_type}"]\n'
    )
    full_path.write_text(content, encoding="utf-8")

    return {
        "status": "ok",
        "scene_path": scene_path,
        "root_type": root_type,
        "root_name": root_name,
        "absolute_path": str(full_path.resolve()),
    }


def read_scene(project_path: str, scene_path: str) -> dict:
    """Parse a .tscn file and return its node tree structure.

    Args:
        project_path: Godot project directory.
        scene_path: Relative path to the .tscn file.

    Returns:
        Dict with scene structure (nodes, resources, connections).
    """
    full_path = Path(project_path) / scene_path
    if not full_path.exists():
        return {"status": "error", "message": f"Scene not found: {scene_path}"}

    text = full_path.read_text(encoding="utf-8")
    nodes = []
    ext_resources = []
    sub_resources = []
    connections = []

    current_section = None
    current_attrs = {}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            if current_section and current_attrs:
                _store_section(current_section, current_attrs,
                               nodes, ext_resources, sub_resources, connections)
                current_section = None
                current_attrs = {}
            continue

        if line.startswith("[") and line.endswith("]"):
            if current_section and current_attrs:
                _store_section(current_section, current_attrs,
                               nodes, ext_resources, sub_resources, connections)
            tag_content = line[1:-1]
            parts = tag_content.split(None, 1)
            current_section = parts[0]
            current_attrs = _parse_tag_attrs(parts[1] if len(parts) > 1 else "")
            continue

        if "=" in line and current_section:
            key, _, value = line.partition("=")
            current_attrs[key.strip()] = value.strip()

    if current_section and current_attrs:
        _store_section(current_section, current_attrs,
                       nodes, ext_resources, sub_resources, connections)

    return {
        "status": "ok",
        "scene_path": scene_path,
        "nodes": nodes,
        "ext_resources": ext_resources,
        "sub_resources": sub_resources,
        "connections": connections,
    }


def add_node(
    project_path: str,
    scene_path: str,
    node_name: str,
    node_type: str,
    parent: str = ".",
) -> dict:
    """Append a child node to an existing .tscn scene.

    Args:
        project_path: Godot project directory.
        scene_path: Relative path to the .tscn file.
        node_name: Name of the new node.
        node_type: Type of the node (Sprite2D, CollisionShape2D, etc.).
        parent: Parent node path (default '.' = root).

    Returns:
        Dict with status.
    """
    full_path = Path(project_path) / scene_path
    if not full_path.exists():
        return {"status": "error", "message": f"Scene not found: {scene_path}"}

    node_line = f'\n[node name="{node_name}" type="{node_type}" parent="{parent}"]\n'
    with open(full_path, "a", encoding="utf-8") as f:
        f.write(node_line)

    return {
        "status": "ok",
        "node_name": node_name,
        "node_type": node_type,
        "parent": parent,
    }


def set_node_property(
    project_path: str,
    scene_path: str,
    node_name: str,
    prop: str,
    value: str,
    raw: bool = False,
) -> dict:
    """Set a property line on a node block in a .tscn file."""
    full_path = resolve_project_path(project_path, scene_path)
    if not full_path.exists():
        return {"status": "error", "message": f"Scene not found: {scene_path}"}

    sections = split_scene_sections(full_path.read_text(encoding="utf-8"))
    serialized = godot_value(value, raw=raw)
    for section in sections:
        header = section[0].strip() if section else ""
        if header.startswith("[node ") and scene_header_attr(header, "name") == node_name:
            set_block_property(section, prop, serialized)
            write_scene_sections(full_path, sections)
            return {"status": "ok", "node_name": node_name, "prop": prop, "value": serialized}
    return {"status": "error", "message": f"Node not found: {node_name}"}


def add_ext_resource(
    project_path: str,
    scene_path: str,
    resource_type: str,
    resource_path: str,
    resource_id: str,
) -> dict:
    """Add or replace an ext_resource header in a scene."""
    full_path = resolve_project_path(project_path, scene_path)
    if not full_path.exists():
        return {"status": "error", "message": f"Scene not found: {scene_path}"}

    sections = split_scene_sections(full_path.read_text(encoding="utf-8"))
    res_path = as_res_path(project_path, resource_path)
    header = f'[ext_resource type="{resource_type}" path="{res_path}" id="{resource_id}"]'
    for section in sections:
        existing = section[0].strip() if section else ""
        if existing.startswith("[ext_resource ") and scene_header_attr(existing, "id") == resource_id:
            section[0] = header
            break
    else:
        insert_at = 1 if sections and sections[0][0].startswith("[gd_scene") else 0
        sections.insert(insert_at, [header])
    write_scene_sections(full_path, sections)
    return {"status": "ok", "id": resource_id, "type": resource_type, "path": res_path}


def add_sub_resource(
    project_path: str,
    scene_path: str,
    resource_type: str,
    resource_id: str,
    properties: tuple[str, ...] | list[str] = (),
    raw: bool = False,
) -> dict:
    """Add or replace a sub_resource block in a scene."""
    full_path = resolve_project_path(project_path, scene_path)
    if not full_path.exists():
        return {"status": "error", "message": f"Scene not found: {scene_path}"}

    props = parse_key_values(properties)
    block = [f'[sub_resource type="{resource_type}" id="{resource_id}"]']
    for key, value in props.items():
        block.append(f"{key} = {godot_value(value, raw=raw)}")

    sections = split_scene_sections(full_path.read_text(encoding="utf-8"))
    for idx, section in enumerate(sections):
        header = section[0].strip() if section else ""
        if header.startswith("[sub_resource ") and scene_header_attr(header, "id") == resource_id:
            sections[idx] = block
            break
    else:
        insert_at = 1
        while insert_at < len(sections) and sections[insert_at][0].startswith("[ext_resource "):
            insert_at += 1
        sections.insert(insert_at, block)
    write_scene_sections(full_path, sections)
    return {"status": "ok", "id": resource_id, "type": resource_type, "properties": props}


def attach_script(
    project_path: str,
    scene_path: str,
    node_name: str,
    script_path: str,
    resource_id: str = "1_script",
) -> dict:
    """Reference a script from a scene and attach it to a node."""
    res = add_ext_resource(project_path, scene_path, "Script", script_path, resource_id)
    if res.get("status") != "ok":
        return res
    return set_node_property(
        project_path,
        scene_path,
        node_name,
        "script",
        f'ExtResource("{resource_id}")',
        raw=True,
    )


# ---------- internal helpers ----------

def _generate_uid() -> str:
    """Generate a UID for scene files using uuid4 for uniqueness."""
    import uuid
    return uuid.uuid4().hex[:12]


def _parse_tag_attrs(attr_string: str) -> dict:
    """Parse tag attributes like 'name="Foo" type="Node2D"'."""
    attrs = {}
    import re
    for match in re.finditer(r'(\w+)="([^"]*)"', attr_string):
        attrs[match.group(1)] = match.group(2)
    for match in re.finditer(r'(\w+)=(\d+)', attr_string):
        attrs[match.group(1)] = match.group(2)
    return attrs


def _store_section(section, attrs, nodes, ext_resources, sub_resources, connections):
    """Store parsed section into the appropriate list."""
    if section == "node":
        nodes.append(attrs)
    elif section == "ext_resource":
        ext_resources.append(attrs)
    elif section == "sub_resource":
        sub_resources.append(attrs)
    elif section == "connection":
        connections.append(attrs)
