"""Godot project management — create, info, list scenes, validate."""

from pathlib import Path

from cli_anything.godot.utils.godot_backend import (
    run_godot, validate_project,
)
from cli_anything.godot.core.text_artifacts import godot_value, set_ini_section_key


def create_project(project_path: str, project_name: str | None = None) -> dict:
    """Create a new Godot project at the given path.

    Args:
        project_path: Directory to create the project in.
        project_name: Display name; defaults to directory name.

    Returns:
        Dict with status and project path.
    """
    path = Path(project_path)
    path.mkdir(parents=True, exist_ok=True)

    if project_name is None:
        project_name = path.name

    project_file = path / "project.godot"
    if project_file.exists():
        return {"status": "error", "message": f"Project already exists at {project_path}"}

    content = (
        '; Engine configuration file.\n'
        '; Do not edit unless you know what you are doing.\n\n'
        f'[application]\n\n'
        f'config/name="{project_name}"\n'
        f'config/features=PackedStringArray("4.4", "GL Compatibility")\n\n'
        '[rendering]\n\n'
        'renderer/rendering_method="gl_compatibility"\n'
        'renderer/rendering_method.mobile="gl_compatibility"\n'
    )

    project_file.write_text(content, encoding="utf-8")

    return {
        "status": "ok",
        "project_path": str(path.resolve()),
        "project_name": project_name,
    }


def get_project_info(project_path: str) -> dict:
    """Read project.godot and return parsed project metadata.

    Args:
        project_path: Path to Godot project directory.

    Returns:
        Dict with project name, features, settings.
    """
    if not validate_project(project_path):
        return {"status": "error", "message": f"No project.godot found at {project_path}"}

    project_file = Path(project_path) / "project.godot"
    text = project_file.read_text(encoding="utf-8")

    # Parse key=value from project.godot (INI-like format)
    info = {
        "status": "ok",
        "project_path": str(Path(project_path).resolve()),
        "name": "",
        "features": [],
        "main_scene": "",
        "sections": {},
    }

    current_section = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            if current_section not in info["sections"]:
                info["sections"][current_section] = {}
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"')
            info["sections"].setdefault(current_section, {})[key] = value

            if key == "config/name":
                info["name"] = value
            elif key == "config/features":
                info["features"] = _parse_packed_string_array(value)
            elif key == "run/main_scene":
                info["main_scene"] = value

    return info


def list_scenes(project_path: str) -> dict:
    """List all .tscn and .scn scene files in the project.

    Returns:
        Dict with list of scene file paths (relative to project root).
    """
    if not validate_project(project_path):
        return {"status": "error", "message": f"No project.godot found at {project_path}"}

    root = Path(project_path)
    scenes = []
    for ext in ("*.tscn", "*.scn"):
        for f in root.rglob(ext):
            scenes.append(str(f.relative_to(root).as_posix()))

    scenes.sort()
    return {"status": "ok", "count": len(scenes), "scenes": scenes}


def list_scripts(project_path: str) -> dict:
    """List all .gd GDScript files in the project.

    Returns:
        Dict with list of script file paths.
    """
    if not validate_project(project_path):
        return {"status": "error", "message": f"No project.godot found at {project_path}"}

    root = Path(project_path)
    scripts = [
        str(f.relative_to(root).as_posix())
        for f in root.rglob("*.gd")
    ]
    scripts.sort()
    return {"status": "ok", "count": len(scripts), "scripts": scripts}


def list_resources(project_path: str) -> dict:
    """List all .tres and .res resource files in the project.

    Returns:
        Dict with list of resource file paths.
    """
    if not validate_project(project_path):
        return {"status": "error", "message": f"No project.godot found at {project_path}"}

    root = Path(project_path)
    resources = []
    for ext in ("*.tres", "*.res"):
        for f in root.rglob(ext):
            resources.append(str(f.relative_to(root).as_posix()))

    resources.sort()
    return {"status": "ok", "count": len(resources), "resources": resources}


def reimport_project(project_path: str) -> dict:
    """Force re-import of all project resources.

    Returns:
        Dict with status and Godot output.
    """
    result = run_godot(
        ["--import", "--quit"],
        project_path=project_path,
        headless=True,
        timeout=120,
    )
    return {
        "status": "ok" if result["returncode"] == 0 else "error",
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


def set_project_setting(project_path: str, key: str, value: str, raw: bool = False) -> dict:
    """Set a project.godot value addressed as section/subkey."""
    if "/" not in key:
        return {"status": "error", "message": "Key must be section/subkey"}
    if not validate_project(project_path):
        return {"status": "error", "message": f"No project.godot found at {project_path}"}

    section, _, subkey = key.partition("/")
    serialized = godot_value(value, raw=raw)
    set_ini_section_key(Path(project_path) / "project.godot", section, subkey, serialized)
    return {"status": "ok", "key": key, "value": serialized}


_NAMED_KEYCODES = {
    "SPACE": 32,
    "ENTER": 4194309,
    "RETURN": 4194309,
    "ESCAPE": 4194305,
    "ESC": 4194305,
    "TAB": 4194306,
    "BACKSPACE": 4194308,
    "SHIFT": 4194326,
    "CTRL": 4194328,
    "ALT": 4194329,
    "LEFT": 4194319,
    "RIGHT": 4194321,
    "UP": 4194320,
    "DOWN": 4194322,
    "F1": 4194332, "F2": 4194333, "F3": 4194334, "F4": 4194335,
    "F5": 4194336, "F6": 4194337, "F7": 4194338, "F8": 4194339,
    "F9": 4194340, "F10": 4194341, "F11": 4194342, "F12": 4194343,
}


def _keycode_value(keycode: str) -> int:
    key = keycode.upper()
    if key in _NAMED_KEYCODES:
        return _NAMED_KEYCODES[key]
    if len(key) == 1:
        return ord(key)
    if keycode.isdigit():
        return int(keycode)
    raise RuntimeError(f"Unsupported keycode: {keycode}")


def add_input_action(
    project_path: str,
    action: str,
    keycode: str | None = None,
    deadzone: float = 0.5,
) -> dict:
    """Create or replace an input action in project.godot."""
    if not validate_project(project_path):
        return {"status": "error", "message": f"No project.godot found at {project_path}"}

    if keycode:
        code = _keycode_value(keycode)
        value = (
            "{\n"
            f'"deadzone": {deadzone},\n'
            '"events": [Object(InputEventKey,"device":-1,"keycode":0,'
            f'"physical_keycode":{code},"unicode":0,"echo":false)\n'
            "]\n"
            "}"
        )
    else:
        value = f'{{"deadzone": {deadzone}, "events": []}}'
    set_ini_section_key(Path(project_path) / "project.godot", "input", action, value)
    return {"status": "ok", "action": action, "keycode": keycode}


def add_autoload(
    project_path: str,
    name: str,
    script_path: str,
    singleton: bool = True,
) -> dict:
    """Add an autoload singleton entry to project.godot."""
    if not validate_project(project_path):
        return {"status": "error", "message": f"No project.godot found at {project_path}"}
    path = script_path if script_path.startswith("res://") else f"res://{script_path}"
    prefix = "*" if singleton else ""
    serialized = godot_value(prefix + path)
    set_ini_section_key(Path(project_path) / "project.godot", "autoload", name, serialized)
    return {"status": "ok", "name": name, "path": prefix + path}


def list_files(project_path: str, extension: str) -> dict:
    """List project files by arbitrary extension."""
    if not Path(project_path).exists():
        return {"status": "error", "message": f"Directory not found: {project_path}"}
    ext = extension.lstrip(".")
    root = Path(project_path)
    files = [str(f.relative_to(root).as_posix()) for f in sorted(root.rglob(f"*.{ext}"))]
    return {"status": "ok", "extension": ext, "count": len(files), "files": files}


def _parse_packed_string_array(value: str) -> list[str]:
    """Parse PackedStringArray('a', 'b') into a Python list."""
    value = value.strip()
    if value.startswith("PackedStringArray(") and value.endswith(")"):
        inner = value[len("PackedStringArray("):-1]
        return [s.strip().strip('"').strip("'") for s in inner.split(",") if s.strip()]
    return []
