"""GIMP gimprc preference writer."""

from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_CONFIG_DIR = Path.home() / ".config" / "GIMP" / "2.10"


def _format_value(value: str) -> str:
    if value.lower() in ("true", "false", "yes", "no") or value.replace(".", "", 1).isdigit():
        return value
    if value.startswith('"') and value.endswith('"'):
        return value
    return '"' + value.replace('"', '\\"') + '"'


def set_preference(key: str, value: str, config_dir: str | None = None) -> dict[str, Any]:
    """Set one top-level gimprc preference."""
    cfg = Path(config_dir).expanduser() if config_dir else DEFAULT_CONFIG_DIR
    cfg.mkdir(parents=True, exist_ok=True)
    gimprc = cfg / "gimprc"
    prefs: dict[str, str] = {}
    if gimprc.exists():
        for line in gimprc.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("(") and line.endswith(")") and " " in line:
                inner = line[1:-1]
                name, raw = inner.split(" ", 1)
                prefs[name] = raw.strip()
    prefs[key] = _format_value(value)
    with open(gimprc, "w", encoding="utf-8") as f:
        for name in sorted(prefs):
            f.write(f"({name} {prefs[name]})\n")
    return {"path": str(gimprc), "key": key, "value": value, "count": len(prefs)}
