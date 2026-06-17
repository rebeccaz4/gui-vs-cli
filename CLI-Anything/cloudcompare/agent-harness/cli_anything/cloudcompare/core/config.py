"""Configuration module for CloudCompare CLI harness.

Provides reading and parsing of CloudCompare.conf INI files.
"""

import configparser
import os
import re
from pathlib import Path
from typing import Optional


# ── Constants ───────────────────────────────────────────────────────────────

DEFAULT_CONF = os.path.expanduser("~/.config/CCorp/CloudCompare.conf")


# ── Internal Functions ────────────────────────────────────────────────────────

def _read_conf(conf_path: Optional[str] = None) -> configparser.ConfigParser:
    """Read CloudCompare config file."""
    cp = configparser.ConfigParser(strict=False)
    cp.optionxform = str  # preserve case
    path = conf_path or DEFAULT_CONF
    if os.path.exists(path):
        try:
            cp.read(path)
        except configparser.Error:
            pass
    return cp


# ── Public API ───────────────────────────────────────────────────────────────

def get_settings(conf_path: Optional[str] = None) -> dict:
    """Get all settings from CloudCompare config file.

    Args:
        conf_path: Path to config file (uses default if None).

    Returns:
        dict with keys:
            - exists: bool
            - path: str
            - sections: dict[str, dict[str, str]] (nested sections and key-value pairs)

    Example:
        >>> settings = get_settings()
        >>> if settings["exists"]:
        ...     for section, keys in settings["sections"].items():
        ...         print(f"[{section}]")
        ...         for key, value in keys.items():
        ...             print(f"{key} = {value}")
    """
    path = conf_path or DEFAULT_CONF
    if not os.path.exists(path):
        return {
            "exists": False,
            "path": path,
            "sections": {},
        }

    cp = _read_conf(path)
    sections: dict[str, dict[str, str]] = {}
    for s in cp.sections():
        sections[s] = dict(cp.items(s))

    return {
        "exists": True,
        "path": path,
        "sections": sections,
    }


def get_setting(
    section: str,
    key: str,
    conf_path: Optional[str] = None,
    default: Optional[str] = None,
) -> dict:
    """Get a specific setting value from CloudCompare config.

    Args:
        section: Section name (e.g., "General", "Clouds").
        key: Key name.
        conf_path: Path to config file (uses default if None).
        default: Default value if key not found.

    Returns:
        dict with keys:
            - value: Optional[str]
            - found: bool
            - section: str
            - key: str
            - path: str
            - error: str (if error occurred)

    Example:
        >>> result = get_setting("Clouds", "defaultSize")
        >>> if result["found"]:
        ...     print(f"Default cloud size: {result['value']}")
    """
    path = conf_path or DEFAULT_CONF
    if not os.path.exists(path):
        return {
            "value": default,
            "found": False,
            "section": section,
            "key": key,
            "path": path,
            "error": "Config file not found",
        }

    cp = _read_conf(path)
    if section not in cp:
        return {
            "value": default,
            "found": False,
            "section": section,
            "key": key,
            "path": path,
            "error": f"Section not found: {section}",
        }

    if key not in cp[section]:
        return {
            "value": default,
            "found": False,
            "section": section,
            "key": key,
            "path": path,
            "error": f"Key not found: {key}",
        }

    val = cp[section][key]

    # Strip surrounding quotes that Qt INI may add
    stripped = val.strip()
    if (stripped.startswith('"') and stripped.endswith('"')) or \
       (stripped.startswith("'") and stripped.endswith("'")):
        stripped = stripped[1:-1]

    return {
        "value": stripped,
        "found": True,
        "section": section,
        "key": key,
        "path": path,
    }


def check_setting(
    section: str,
    key: str,
    expected: str,
    conf_path: Optional[str] = None,
) -> dict:
    """Check if a setting value matches the expected value.

    Args:
        section: Section name.
        key: Key name.
        expected: Expected value.
        conf_path: Path to config file (uses default if None).

    Returns:
        dict with keys:
            - match: bool
            - expected: str
            - actual: Optional[str]
            - section: str
            - key: str
            - error: str (if error occurred)

    Example:
        >>> result = check_setting("Clouds", "defaultSize", "10.0")
        >>> print(f"Setting matches: {result['match']}")
    """
    get_result = get_setting(section, key, conf_path)
    if "error" in get_result and not get_result.get("found"):
        return {
            "match": False,
            "expected": expected,
            "actual": None,
            "section": section,
            "key": key,
            "error": get_result.get("error", "Setting not found"),
        }

    actual = get_result["value"]
    return {
        "match": str(actual) == str(expected),
        "expected": expected,
        "actual": actual,
        "section": section,
        "key": key,
    }


def get_recent_files(conf_path: Optional[str] = None) -> dict:
    """Get list of recent files from CloudCompare config.

    CloudCompare stores recent files under keys like:
    - [General] recentFile0, recentFile1, ...
    - [recentFiles] entries

    Args:
        conf_path: Path to config file (uses default if None).

    Returns:
        dict with keys:
            - exists: bool
            - path: str
            - files: list[str] (list of recent file paths)
            - count: int

    Example:
        >>> result = get_recent_files()
        >>> print(f"Recent files: {result['count']}")
        >>> for file in result["files"]:
        ...     print(f"  - {file}")
    """
    path = conf_path or DEFAULT_CONF
    if not os.path.exists(path):
        return {
            "exists": False,
            "path": path,
            "files": [],
            "count": 0,
        }

    cp = _read_conf(path)
    files: list[str] = []

    for section in cp.sections():
        for k, v in cp.items(section):
            if re.match(r"(?i)recentfile\d*$", k) or k.lower().startswith("recentfile"):
                val = v.strip()
                if (val.startswith('"') and val.endswith('"')) or \
                   (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                if val:
                    files.append(val)

    return {
        "exists": True,
        "path": path,
        "files": files,
        "count": len(files),
    }


def has_recent_file(filename: str, conf_path: Optional[str] = None) -> dict:
    """Check if a file is in the recent files list.

    Args:
        filename: Filename to search for (can be partial path).
        conf_path: Path to config file (uses default if None).

    Returns:
        dict with keys:
            - found: bool
            - filename: str
            - recent_files: list[str]
            - count: int

    Example:
        >>> result = has_recent_file("scan.ply")
        >>> print(f"In recent files: {result['found']}")
    """
    recent_result = get_recent_files(conf_path)
    if not recent_result["exists"]:
        return {
            "found": False,
            "filename": filename,
            "recent_files": [],
            "count": 0,
        }

    files = recent_result["files"]
    found = any(filename in f for f in files)

    return {
        "found": found,
        "filename": filename,
        "recent_files": files,
        "count": len(files),
    }


def list_sections(conf_path: Optional[str] = None) -> dict:
    """List all sections in the CloudCompare config file.

    Args:
        conf_path: Path to config file (uses default if None).

    Returns:
        dict with keys:
            - exists: bool
            - path: str
            - sections: list[str]
            - count: int

    Example:
        >>> result = list_sections()
        >>> print(f"Sections: {result['count']}")
        >>> for section in result["sections"]:
        ...     print(f"  - [{section}]")
    """
    path = conf_path or DEFAULT_CONF
    if not os.path.exists(path):
        return {
            "exists": False,
            "path": path,
            "sections": [],
            "count": 0,
        }

    cp = _read_conf(path)
    sections = cp.sections()

    return {
        "exists": True,
        "path": path,
        "sections": sections,
        "count": len(sections),
    }


def list_keys(section: str, conf_path: Optional[str] = None) -> dict:
    """List all keys in a specific section.

    Args:
        section: Section name.
        conf_path: Path to config file (uses default if None).

    Returns:
        dict with keys:
            - exists: bool
            - section: str
            - keys: list[str]
            - count: int
            - error: str (if error occurred)

    Example:
        >>> result = list_keys("Clouds")
        >>> if result["exists"]:
        ...     print(f"Keys in [Clouds]: {result['count']}")
        ...     for key in result["keys"]:
        ...         print(f"  - {key}")
    """
    path = conf_path or DEFAULT_CONF
    if not os.path.exists(path):
        return {
            "exists": False,
            "section": section,
            "keys": [],
            "count": 0,
            "error": "Config file not found",
        }

    cp = _read_conf(path)
    if section not in cp:
        return {
            "exists": False,
            "section": section,
            "keys": [],
            "count": 0,
            "error": f"Section not found: {section}",
        }

    keys = list(cp[section].keys())

    return {
        "exists": True,
        "section": section,
        "keys": keys,
        "count": len(keys),
    }


def get_config_path() -> str:
    """Get the default CloudCompare config file path.

    Returns:
        str: Absolute path to the config file.

    Example:
        >>> path = get_config_path()
        >>> print(f"Config file: {path}")
    """
    return DEFAULT_CONF
