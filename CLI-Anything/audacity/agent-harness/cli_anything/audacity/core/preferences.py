"""Audacity CLI - Preferences management module.

Handles reading and writing Audacity preferences in audacity.cfg format.
This enables compatibility with the verifier's preference checking endpoints.
"""

import os
import configparser
from typing import Dict, Any, Optional, List
from pathlib import Path


# Default Audacity preferences path
DEFAULT_AUDACITY_CFG = Path.home() / ".audacity-data" / "audacity.cfg"


def read_preferences(cfg_path: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """Read Audacity preferences from audacity.cfg file.

    Args:
        cfg_path: Path to audacity.cfg. If None, uses default location.

    Returns:
        Dict mapping section names to dicts of key-value pairs.

    Raises:
        FileNotFoundError: If config file doesn't exist
        configparser.Error: If config file is invalid
    """
    if cfg_path is None:
        cfg_path = DEFAULT_AUDACITY_CFG

    cfg_path = Path(cfg_path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")

    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    cfg.optionxform = str  # Preserve case sensitivity

    try:
        with open(cfg_path, "r", encoding="utf-8", errors="replace") as f:
            cfg.read_file(f)
    except configparser.Error as e:
        raise ValueError(f"Cannot parse config file: {e}")

    # Convert to dict
    result = {}
    for section in cfg.sections():
        result[section] = {k: cfg.get(section, k) for k in cfg.options(section)}

    return result


def write_preferences(prefs: Dict[str, Dict[str, str]], cfg_path: Optional[str] = None):
    """Write Audacity preferences to audacity.cfg file.

    Args:
        prefs: Dict mapping section names to dicts of key-value pairs
        cfg_path: Path to audacity.cfg. If None, uses default location.

    Raises:
        IOError: If file cannot be written
    """
    if cfg_path is None:
        cfg_path = DEFAULT_AUDACITY_CFG

    cfg_path = Path(cfg_path)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    cfg.optionxform = str

    for section, options in prefs.items():
        cfg.add_section(section)
        for key, value in options.items():
            cfg.set(section, key, str(value))

    with open(cfg_path, "w", encoding="utf-8") as f:
        cfg.write(f)


def get_preference(section: str, key: str, cfg_path: Optional[str] = None) -> str:
    """Get a single preference value.

    Args:
        section: Section name (e.g., "AudioIO", "Quality")
        key: Preference key
        cfg_path: Path to audacity.cfg

    Returns:
        Preference value as string

    Raises:
        KeyError: If section or key not found
    """
    prefs = read_preferences(cfg_path)
    if section not in prefs:
        raise KeyError(f"Section not found: {section}")
    if key not in prefs[section]:
        raise KeyError(f"Key not found: {section}/{key}")
    return prefs[section][key]


def set_preference(section: str, key: str, value: str, cfg_path: Optional[str] = None):
    """Set a single preference value.

    Args:
        section: Section name
        key: Preference key
        value: Preference value
        cfg_path: Path to audacity.cfg
    """
    try:
        prefs = read_preferences(cfg_path)
    except FileNotFoundError:
        prefs = {}

    if section not in prefs:
        prefs[section] = {}
    prefs[section][key] = value

    write_preferences(prefs, cfg_path)


def list_sections(cfg_path: Optional[str] = None) -> List[str]:
    """List all preference sections.

    Args:
        cfg_path: Path to audacity.cfg

    Returns:
        List of section names
    """
    try:
        prefs = read_preferences(cfg_path)
        return list(prefs.keys())
    except FileNotFoundError:
        return []


def create_default_config(cfg_path: Optional[str] = None):
    """Create a default audacity.cfg file with standard settings.

    Args:
        cfg_path: Path where to create the file
    """
    default_prefs = {
        "AudioIO": {
            "RecordingDevice": "default",
            "PlaybackDevice": "default",
            "Host": "alsa",
        },
        "Quality": {
            "SampleRate": "44100",
            "SampleFormat": "16",
        },
        "Warnings": {
            "FirstProjectSave": "0",
        },
        "GUI": {
            "Theme": "light",
        },
    }

    write_preferences(default_prefs, cfg_path)


def preference_exists(section: str, key: str, cfg_path: Optional[str] = None) -> bool:
    """Check if a preference exists.

    Args:
        section: Section name
        key: Preference key
        cfg_path: Path to audacity.cfg

    Returns:
        True if preference exists, False otherwise
    """
    try:
        prefs = read_preferences(cfg_path)
        return section in prefs and key in prefs[section]
    except FileNotFoundError:
        return False


def delete_preference(section: str, key: str, cfg_path: Optional[str] = None):
    """Delete a preference value.

    Args:
        section: Section name
        key: Preference key
        cfg_path: Path to audacity.cfg
    """
    prefs = read_preferences(cfg_path)
    if section in prefs and key in prefs[section]:
        del prefs[section][key]
        # Remove section if empty
        if not prefs[section]:
            del prefs[section]
        write_preferences(prefs, cfg_path)
