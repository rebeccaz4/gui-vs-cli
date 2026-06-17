"""Godot editor settings writers."""

from pathlib import Path

from cli_anything.godot.core.text_artifacts import godot_value, set_ini_section_key


def set_editor_setting(
    key: str,
    value: str,
    raw: bool = False,
    version: str = "4.3",
    settings_path: str | None = None,
) -> dict:
    """Create or update editor_settings-4.X.tres in the user's config dir."""
    if settings_path:
        path = Path(settings_path)
    else:
        path = Path.home() / ".config" / "godot" / f"editor_settings-{version}.tres"

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[gd_resource type="EditorSettings" format=3]\n\n[resource]\n', encoding="utf-8")

    serialized = godot_value(value, raw=raw)
    set_ini_section_key(path, "resource", key, serialized)
    return {"status": "ok", "path": str(path), "key": key, "value": serialized}
