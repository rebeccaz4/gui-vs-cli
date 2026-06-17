"""RenderDoc recent captures and settings history reader.

Reads from UI.config:
- RecentCaptureFiles: List of recently opened .rdc files
- RecentCaptureSettings: List of recently saved .cap files
"""

import os
from pathlib import Path
from typing import Dict, List, Any, Optional

from cli_anything.renderdoc.core.config import get_config, DEFAULT_CONFIG_PATH


def get_recent_captures(config_path: Optional[str] = None) -> List[str]:
    """Get list of recent capture files from UI.config.

    Args:
        config_path: Path to UI.config

    Returns:
        List of file paths (strings)

    Raises:
        FileNotFoundError: If config file doesn't exist
        KeyError: If RecentCaptureFiles key doesn't exist
        ValueError: If config file is not valid JSON
    """
    config = get_config(config_path)
    recent = config.get("RecentCaptureFiles", [])

    # RecentCaptureFiles might be a list or might need extraction
    if isinstance(recent, list):
        return recent
    elif isinstance(recent, dict):
        # Sometimes stored as {"files": [...]}
        return recent.get("files", [])
    else:
        return []


def check_recent_capture(substring: str, config_path: Optional[str] = None) -> Dict[str, Any]:
    """Check if a recent capture path contains the given substring.

    Args:
        substring: Substring to search for in recent files
        config_path: Path to UI.config

    Returns:
        Dict with 'found' (bool), 'substring', 'matching_files' (list)
    """
    try:
        recent = get_recent_captures(config_path)
        matching = [f for f in recent if substring in f]
        found = len(matching) > 0

        return {
            "found": found,
            "substring": substring,
            "matching_files": matching,
            "count": len(matching),
        }
    except (FileNotFoundError, KeyError, ValueError) as e:
        return {
            "found": False,
            "substring": substring,
            "error": str(e),
        }


def get_recent_settings(config_path: Optional[str] = None) -> List[str]:
    """Get list of recent capture settings files (.cap files) from UI.config.

    Args:
        config_path: Path to UI.config

    Returns:
        List of .cap file paths

    Raises:
        FileNotFoundError: If config file doesn't exist
        KeyError: If RecentCaptureSettings key doesn't exist
        ValueError: If config file is not valid JSON
    """
    config = get_config(config_path)
    recent = config.get("RecentCaptureSettings", [])

    # RecentCaptureSettings might be a list or might need extraction
    if isinstance(recent, list):
        return recent
    elif isinstance(recent, dict):
        # Sometimes stored as {"files": [...]} or {"settings": [...]}
        return recent.get("files", recent.get("settings", []))
    else:
        return []


def check_recent_setting(substring: str, config_path: Optional[str] = None) -> Dict[str, Any]:
    """Check if a recent settings file contains the given substring.

    Args:
        substring: Substring to search for in recent settings files
        config_path: Path to UI.config

    Returns:
        Dict with 'found' (bool), 'substring', 'matching_files' (list)
    """
    try:
        recent = get_recent_settings(config_path)
        matching = [f for f in recent if substring in f]
        found = len(matching) > 0

        return {
            "found": found,
            "substring": substring,
            "matching_files": matching,
            "count": len(matching),
        }
    except (FileNotFoundError, KeyError, ValueError) as e:
        return {
            "found": False,
            "substring": substring,
            "error": str(e),
        }


def get_recent_captures_count(config_path: Optional[str] = None) -> int:
    """Get count of recent capture files.

    Args:
        config_path: Path to UI.config

    Returns:
        Number of recent capture files
    """
    try:
        return len(get_recent_captures(config_path))
    except (FileNotFoundError, KeyError, ValueError):
        return 0


def get_recent_settings_count(config_path: Optional[str] = None) -> int:
    """Get count of recent settings files.

    Args:
        config_path: Path to UI.config

    Returns:
        Number of recent settings files
    """
    try:
        return len(get_recent_settings(config_path))
    except (FileNotFoundError, KeyError, ValueError):
        return 0


def get_recent_history_summary(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Get summary of recent captures and settings.

    Args:
        config_path: Path to UI.config

    Returns:
        Dict with 'recent_captures' (list, 'count'),
             'recent_settings' (list, 'count'),
             'total_recent_items'
    """
    try:
        captures = get_recent_captures(config_path)
        settings = get_recent_settings(config_path)

        return {
            "recent_captures": {
                "files": captures,
                "count": len(captures),
            },
            "recent_settings": {
                "files": settings,
                "count": len(settings),
            },
            "total_recent_items": len(captures) + len(settings),
        }
    except (FileNotFoundError, ValueError) as e:
        return {
            "error": str(e),
            "recent_captures": {"files": [], "count": 0},
            "recent_settings": {"files": [], "count": 0},
            "total_recent_items": 0,
        }
