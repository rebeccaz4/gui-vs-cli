"""Godot script execution — run GDScript files in headless mode."""

import tempfile
from pathlib import Path

from cli_anything.godot.utils.godot_backend import run_godot, validate_project
from cli_anything.godot.core.text_artifacts import godot_value, resolve_project_path


def run_script(
    project_path: str,
    script_path: str,
    timeout: int = 60,
) -> dict:
    """Execute a GDScript file in headless mode.

    The script must extend SceneTree or MainLoop.

    Args:
        project_path: Godot project directory.
        script_path: Path to the .gd file (relative to project or absolute).
        timeout: Execution timeout in seconds.

    Returns:
        Dict with status and script output.
    """
    if not validate_project(project_path):
        return {"status": "error", "message": f"Not a Godot project: {project_path}"}

    full_script = Path(project_path) / script_path
    if not full_script.exists():
        return {"status": "error", "message": f"Script not found: {script_path}"}

    # Godot expects res:// paths
    res_path = f"res://{script_path}"

    result = run_godot(
        ["--script", res_path, "--quit"],
        project_path=project_path,
        headless=True,
        timeout=timeout,
    )

    return {
        "status": "ok" if result["returncode"] == 0 else "error",
        "script": script_path,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


def run_inline(
    project_path: str,
    code: str,
    timeout: int = 60,
) -> dict:
    """Run inline GDScript code by writing a temporary .gd file.

    The code is wrapped in an extends SceneTree boilerplate with _init().

    Args:
        project_path: Godot project directory.
        code: GDScript code to execute (function body).
        timeout: Execution timeout in seconds.

    Returns:
        Dict with status and output.
    """
    if not validate_project(project_path):
        return {"status": "error", "message": f"Not a Godot project: {project_path}"}

    # Wrap user code in SceneTree boilerplate
    wrapped = (
        "extends SceneTree\n\n"
        "func _init():\n"
    )
    for line in code.splitlines():
        wrapped += f"\t{line}\n"
    wrapped += "\tquit()\n"

    # Write to a temp file inside the project (so res:// can find it)
    script_name = "_cli_anything_tmp.gd"
    script_path = Path(project_path) / script_name
    script_path.write_text(wrapped, encoding="utf-8")

    try:
        result = run_godot(
            ["--script", f"res://{script_name}", "--quit"],
            project_path=project_path,
            headless=True,
            timeout=timeout,
        )
        return {
            "status": "ok" if result["returncode"] == 0 else "error",
            "code": code,
            "returncode": result["returncode"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
        }
    finally:
        # Clean up temp script
        script_path.unlink(missing_ok=True)


def validate_script(project_path: str, script_path: str) -> dict:
    """Check if a GDScript file has valid syntax using Godot's parser.

    Args:
        project_path: Godot project directory.
        script_path: Relative path to the .gd file.

    Returns:
        Dict with validation results.
    """
    full_script = Path(project_path) / script_path
    if not full_script.exists():
        return {"status": "error", "message": f"Script not found: {script_path}"}

    # Use --check-only to validate without running
    result = run_godot(
        ["--check-only", "--script", f"res://{script_path}", "--quit"],
        project_path=project_path,
        headless=True,
        timeout=30,
    )

    valid = result["returncode"] == 0
    return {
        "status": "ok",
        "script": script_path,
        "valid": valid,
        "errors": result["stderr"] if not valid else "",
    }


def create_script(
    project_path: str,
    script_path: str,
    extends: str = "Node",
    class_name: str | None = None,
    body: str | None = None,
) -> dict:
    """Create a persistent GDScript file."""
    if not validate_project(project_path):
        return {"status": "error", "message": f"Not a Godot project: {project_path}"}
    full_path = resolve_project_path(project_path, script_path)
    full_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if class_name:
        lines.append(f"class_name {class_name}")
    lines.append(f"extends {extends}")
    if body:
        lines.extend(["", body.rstrip()])
    else:
        lines.append("")
    full_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"status": "ok", "script": script_path, "extends": extends, "class_name": class_name}


def add_function(
    project_path: str,
    script_path: str,
    name: str,
    args: str = "",
    body: str = "pass",
) -> dict:
    """Append or replace a simple function declaration."""
    full_path = resolve_project_path(project_path, script_path)
    if not full_path.exists():
        return {"status": "error", "message": f"Script not found: {script_path}"}
    text = full_path.read_text(encoding="utf-8").rstrip()
    body_lines = body.splitlines() or ["pass"]
    indented = "\n".join(f"\t{line}" if line.strip() else "" for line in body_lines)
    func_block = f"func {name}({args}):\n{indented}"
    text = _remove_top_level_decl(text, rf"func\s+{name}\s*\(")
    full_path.write_text(text.rstrip() + "\n\n" + func_block + "\n", encoding="utf-8")
    return {"status": "ok", "script": script_path, "name": name}


def add_export(
    project_path: str,
    script_path: str,
    name: str,
    type_name: str | None = None,
    default: str | None = None,
    raw: bool = False,
) -> dict:
    """Append or replace an @export variable declaration."""
    suffix = f": {type_name}" if type_name else ""
    if default is not None:
        suffix += f" = {godot_value(default, raw=raw)}"
    line = f"@export var {name}{suffix}"
    return _upsert_line_decl(project_path, script_path, rf"@export\s+var\s+{name}\b", line)


def add_signal(project_path: str, script_path: str, name: str, args: str = "") -> dict:
    line = f"signal {name}({args})" if args else f"signal {name}"
    return _upsert_line_decl(project_path, script_path, rf"signal\s+{name}\b", line)


def add_var(
    project_path: str,
    script_path: str,
    name: str,
    value: str | None = None,
    const: bool = False,
    raw: bool = False,
) -> dict:
    prefix = "const" if const else "var"
    line = f"{prefix} {name}"
    if value is not None:
        line += f" = {godot_value(value, raw=raw)}"
    return _upsert_line_decl(project_path, script_path, rf"{prefix}\s+{name}\b", line)


def _upsert_line_decl(project_path: str, script_path: str, pattern: str, line: str) -> dict:
    full_path = resolve_project_path(project_path, script_path)
    if not full_path.exists():
        return {"status": "error", "message": f"Script not found: {script_path}"}
    lines = full_path.read_text(encoding="utf-8").splitlines()
    import re
    for idx, existing in enumerate(lines):
        if re.match(pattern, existing.strip()):
            lines[idx] = line
            break
    else:
        insert_at = 0
        while insert_at < len(lines) and (
            lines[insert_at].startswith("class_name ") or lines[insert_at].startswith("extends ")
        ):
            insert_at += 1
        lines.insert(insert_at, line)
    full_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"status": "ok", "script": script_path, "line": line}


def _remove_top_level_decl(text: str, start_pattern: str) -> str:
    import re
    lines = text.splitlines()
    output: list[str] = []
    skipping = False
    for line in lines:
        if re.match(start_pattern, line):
            skipping = True
            continue
        if skipping and line and not line.startswith((" ", "\t")):
            skipping = False
        if not skipping:
            output.append(line)
    return "\n".join(output).rstrip()
