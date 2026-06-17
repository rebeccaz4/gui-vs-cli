"""Krita configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict


def default_kritarc_path() -> str:
    return os.path.expanduser("~/.config/kritarc")


def set_kritarc_value(
    section: str,
    key: str,
    value: Any,
    path: str | None = None,
) -> Dict[str, Any]:
    """Set a Krita kritarc INI value."""
    if not section or not key:
        raise ValueError("Section and key must be non-empty")
    cfg_path = Path(os.path.expanduser(path or default_kritarc_path()))
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    sections: dict[str, list[str]] = {}
    order: list[str] = []
    current: str | None = None
    if cfg_path.exists():
        for raw_line in cfg_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.rstrip("\r\n")
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1]
                if current not in sections:
                    sections[current] = []
                    order.append(current)
            elif current is not None:
                sections.setdefault(current, []).append(line)

    if section not in sections:
        sections[section] = []
        order.append(section)

    rendered = f"{key}={value}"
    replaced = False
    lines = []
    for line in sections[section]:
        if "=" in line and line.partition("=")[0].strip() == key:
            lines.append(rendered)
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        lines.append(rendered)
    sections[section] = lines

    out: list[str] = []
    for name in order:
        out.append(f"[{name}]")
        out.extend(sections.get(name, []))
        out.append("")
    cfg_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return {"path": str(cfg_path), "section": section, "key": key, "value": str(value)}
