"""MuseScore preference file helpers."""

import configparser
import os


def set_preference(section: str, key: str, value: str, path: str | None = None) -> dict:
    """Set a MuseScore3.ini preference value."""
    cfg_path = path or os.path.expanduser("~/.config/MuseScore/MuseScore3.ini")
    cp = configparser.ConfigParser()
    cp.optionxform = str
    if os.path.exists(cfg_path):
        cp.read(cfg_path, encoding="utf-8")
    if section not in cp:
        cp.add_section(section)
    cp[section][key] = str(value)
    os.makedirs(os.path.dirname(os.path.abspath(cfg_path)), exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        cp.write(f)
    return {"path": os.path.abspath(cfg_path), "section": section, "key": key, "value": str(value)}
