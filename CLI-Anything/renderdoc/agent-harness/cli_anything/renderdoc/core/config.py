"""RenderDoc UI.config reader for qrenderdoc GUI settings.

UI.config is a JSON file written by qrenderdoc located at:
~/.local/share/qrenderdoc/UI.config

This module provides functions to read and verify UI settings.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


# Default UI.config path
DEFAULT_CONFIG_PATH = Path.home() / ".local" / "share" / "qrenderdoc" / "UI.config"


def _read_json_file(path: str) -> Dict[str, Any]:
    """Read a JSON file, handling control characters from text editors.

    Tries strict=False first, then retries after stripping control characters
    if the first attempt fails.

    Args:
        path: Path to JSON file

    Returns:
        Parsed JSON dict

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file is not valid JSON
    """
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"UI.config not found: {path}")

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Try with strict=False first
    try:
        return json.loads(content, strict=False)
    except json.JSONDecodeError:
        # Retry after stripping control characters (except tab, newline, carriage return)
        sanitized = "".join(
            ch for ch in content
            if ch >= "\t" or ch in ("\n", "\r")
        )
        try:
            return json.loads(sanitized)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {path}: {e}")


def get_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Read entire UI.config file.

    Args:
        config_path: Path to UI.config (default: ~/.local/share/qrenderdoc/UI.config)

    Returns:
        Full UI.config JSON dict

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is not valid JSON
    """
    if config_path is None:
        config_path = str(DEFAULT_CONFIG_PATH)

    return _read_json_file(config_path)


def write_config(config: Dict[str, Any], config_path: Optional[str] = None) -> Dict[str, Any]:
    """Write a qrenderdoc UI.config JSON object."""
    if config_path is None:
        config_path = str(DEFAULT_CONFIG_PATH)
    path = Path(config_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, sort_keys=True)
        f.write("\n")
    return {"path": str(path), "keys": sorted(config.keys()), "count": len(config)}


def set_config_key(key: str, value: Any, config_path: Optional[str] = None) -> Dict[str, Any]:
    """Set one top-level UI.config key, creating the file if needed."""
    if config_path is None:
        config_path = str(DEFAULT_CONFIG_PATH)
    try:
        config = get_config(config_path)
    except FileNotFoundError:
        config = {}
    config[key] = value
    result = write_config(config, config_path)
    result.update({"key": key, "value": value})
    return result


def append_config_list(key: str, value: Any, config_path: Optional[str] = None) -> Dict[str, Any]:
    """Append one item to a list-valued UI.config key, creating the list if needed."""
    if config_path is None:
        config_path = str(DEFAULT_CONFIG_PATH)
    try:
        config = get_config(config_path)
    except FileNotFoundError:
        config = {}
    current = config.get(key, [])
    if not isinstance(current, list):
        current = []
    current.append(value)
    config[key] = current
    result = write_config(config, config_path)
    result.update({"key": key, "value": value, "items": current})
    return result


def get_config_key(key: str, config_path: Optional[str] = None) -> Any:
    """Read a single key from UI.config.

    Args:
        key: Top-level key name (e.g., "Font_GlobalScale", "UIStyle")
        config_path: Path to UI.config

    Returns:
        Value associated with key

    Raises:
        FileNotFoundError: If config file doesn't exist
        KeyError: If key doesn't exist in config
        ValueError: If config file is not valid JSON
    """
    config = get_config(config_path)
    if key not in config:
        raise KeyError(f"Key '{key}' not found in UI.config")
    return config[key]


def list_config_keys(config_path: Optional[str] = None) -> List[str]:
    """List all top-level keys in UI.config.

    Args:
        config_path: Path to UI.config

    Returns:
        List of key names

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is not valid JSON
    """
    config = get_config(config_path)
    return list(config.keys())


def check_setting(key: str, expected: Any, config_path: Optional[str] = None) -> Dict[str, Any]:
    """Check if a UI.config key matches expected value.

    Args:
        key: Key name to check
        expected: Expected value (will be parsed as JSON if string)
        config_path: Path to UI.config

    Returns:
        Dict with 'match' (bool), 'key', 'expected', 'actual'
    """
    try:
        # If expected is a string, try to parse it as JSON
        if isinstance(expected, str):
            try:
                expected_parsed = json.loads(expected)
            except json.JSONDecodeError:
                expected_parsed = expected
        else:
            expected_parsed = expected

        actual = get_config_key(key, config_path)
        match = _compare_values(actual, expected_parsed)

        return {
            "match": match,
            "key": key,
            "expected": expected_parsed,
            "actual": actual,
        }
    except (FileNotFoundError, KeyError, ValueError) as e:
        return {
            "match": False,
            "key": key,
            "expected": expected,
            "error": str(e),
        }


def check_setting_exists(key: str, config_path: Optional[str] = None) -> Dict[str, Any]:
    """Check if a key exists in UI.config.

    Args:
        key: Key name to check
        config_path: Path to UI.config

    Returns:
        Dict with 'exists' (bool) and 'key'
    """
    try:
        config = get_config(config_path)
        exists = key in config
        return {"exists": exists, "key": key}
    except (FileNotFoundError, ValueError) as e:
        return {"exists": False, "key": key, "error": str(e)}


def get_theme(config_path: Optional[str] = None) -> str:
    """Get the current UI theme.

    Shortcut for get_config_key("UIStyle").

    Args:
        config_path: Path to UI.config

    Returns:
        Theme name (e.g., "", "Default", "Light", "Dark")
    """
    return get_config_key("UIStyle", config_path)


def check_theme(expected: str, config_path: Optional[str] = None) -> Dict[str, Any]:
    """Check if UI theme matches expected value.

    Args:
        expected: Expected theme name
        config_path: Path to UI.config

    Returns:
        Dict with 'match' (bool), 'expected', 'actual'
    """
    return check_setting("UIStyle", expected, config_path)


def get_font_scale(config_path: Optional[str] = None) -> float:
    """Get the global font scale.

    Shortcut for get_config_key("Font_GlobalScale").

    Args:
        config_path: Path to UI.config

    Returns:
        Font scale factor (float)
    """
    return float(get_config_key("Font_GlobalScale", config_path))


def check_font_scale(expected: float, config_path: Optional[str] = None,
                    tolerance: float = 1e-6) -> Dict[str, Any]:
    """Check if font scale matches expected value (with tolerance).

    Args:
        expected: Expected font scale
        config_path: Path to UI.config
        tolerance: Float comparison tolerance

    Returns:
        Dict with 'match' (bool), 'expected', 'actual'
    """
    try:
        actual = get_font_scale(config_path)
        match = abs(actual - float(expected)) <= tolerance
        return {
            "match": match,
            "expected": expected,
            "actual": actual,
            "tolerance": tolerance,
        }
    except (FileNotFoundError, KeyError, ValueError) as e:
        return {
            "match": False,
            "expected": expected,
            "error": str(e),
        }


def _compare_values(a: Any, b: Any) -> bool:
    """Compare two values with appropriate type handling.

    Handles:
    - Float comparison with tolerance
    - List comparison (order-insensitive)
    - Dict comparison (key-insensitive)
    - Direct equality for other types

    Args:
        a: First value
        b: Second value

    Returns:
        True if values match, False otherwise
    """
    # Float comparison with tolerance
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= 1e-6

    # List comparison (order-insensitive)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_compare_values(x, y) for x, y in zip(sorted(a), sorted(b)))

    # Direct comparison
    return a == b
