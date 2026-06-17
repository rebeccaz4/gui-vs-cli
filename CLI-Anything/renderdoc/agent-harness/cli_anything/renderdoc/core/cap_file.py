"""RenderDoc .cap capture settings file parser.

.cap files are JSON files written by qrenderdoc that store capture settings
for "launch and capture" workflows. They contain:
- executable: Program to run
- commandLine: Command line arguments
- workingDir: Working directory
- options: Capture options (environment, API, etc.)
- environment: Environment variables

Example .cap file structure:
{
    "executable": "/path/to/app",
    "commandLine": "--arg1 value1",
    "workingDir": "/path/to/dir",
    "options": {
        "api": "Vulkan",
        "captureOnFrame": 100
    },
    "environment": {
        "VAR1": "value1",
        "VAR2": "value2"
    }
}
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


def parse_cap_file(cap_path: str) -> Dict[str, Any]:
    """Parse a .cap capture settings file.

    Args:
        cap_path: Path to .cap file

    Returns:
        Parsed .cap file contents as dict

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file is not valid JSON
    """
    cap_path = os.path.abspath(cap_path)
    if not os.path.exists(cap_path):
        raise FileNotFoundError(f".cap file not found: {cap_path}")

    if not cap_path.endswith(".cap"):
        raise ValueError(f"File must have .cap extension: {cap_path}")

    with open(cap_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {cap_path}: {e}")

    # Validate required fields. qrenderdoc can store fields at top level or
    # under a nested "settings" object.
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else data
    if "executable" not in settings:
        raise ValueError(f".cap file missing 'executable' field: {cap_path}")

    return data


def _normalise_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    settings = data.get("settings")
    if isinstance(settings, dict):
        return settings
    return data


def write_cap_file(
    cap_path: str,
    executable: str = "",
    command_line: str = "",
    working_dir: str = "",
    options: Optional[Dict[str, Any]] = None,
    environment: Optional[List[Any]] = None,
    nested: bool = True,
) -> Dict[str, Any]:
    """Write a qrenderdoc-compatible .cap capture settings JSON file."""
    path = Path(cap_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    settings = {
        "executable": executable,
        "commandLine": command_line,
        "workingDir": working_dir,
        "options": options or {},
        "environment": environment or [],
        "autoStart": False,
        "queueFrameCap": False,
        "numQueuedFrames": 0,
    }
    data = {"rdocCaptureSettings": 1, "settings": settings} if nested else settings
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    return {"path": str(path), "settings": settings}


def set_cap_option(cap_path: str, key: str, value: Any) -> Dict[str, Any]:
    """Set one .cap options entry, preserving existing settings."""
    data = parse_cap_file(cap_path)
    settings = _normalise_settings(data)
    options = settings.get("options")
    if not isinstance(options, dict):
        options = {}
    options[key] = value
    settings["options"] = options
    if "settings" in data and isinstance(data["settings"], dict):
        data["settings"] = settings
        nested = True
    else:
        data = settings
        nested = False
    return write_cap_file(
        cap_path,
        executable=settings.get("executable", ""),
        command_line=settings.get("commandLine", ""),
        working_dir=settings.get("workingDir", ""),
        options=options,
        environment=settings.get("environment") if isinstance(settings.get("environment"), list) else [],
        nested=nested,
    )


def add_cap_env(cap_path: str, name: str, value: str = "") -> Dict[str, Any]:
    """Append an environment variable to a .cap file as NAME=VALUE."""
    data = parse_cap_file(cap_path)
    settings = _normalise_settings(data)
    env = settings.get("environment")
    if not isinstance(env, list):
        env = []
    env.append(f"{name}={value}")
    settings["environment"] = env
    nested = "settings" in data and isinstance(data["settings"], dict)
    return write_cap_file(
        cap_path,
        executable=settings.get("executable", ""),
        command_line=settings.get("commandLine", ""),
        working_dir=settings.get("workingDir", ""),
        options=settings.get("options") if isinstance(settings.get("options"), dict) else {},
        environment=env,
        nested=nested,
    )


def get_executable(cap_path: str) -> str:
    """Get the executable path from a .cap file.

    Args:
        cap_path: Path to .cap file

    Returns:
        Executable path string
    """
    cap_data = parse_cap_file(cap_path)
    return _normalise_settings(cap_data)["executable"]


def check_cap_executable(cap_path: str, expected: str) -> Dict[str, Any]:
    """Check if .cap file executable matches expected value.

    Args:
        cap_path: Path to .cap file
        expected: Expected executable path

    Returns:
        Dict with 'match' (bool), 'expected', 'actual'
    """
    try:
        actual = get_executable(cap_path)
        match = actual == expected

        return {
            "match": match,
            "expected": expected,
            "actual": actual,
            "cap_file": cap_path,
        }
    except (FileNotFoundError, ValueError) as e:
        return {
            "match": False,
            "expected": expected,
            "cap_file": cap_path,
            "error": str(e),
        }


def get_working_dir(cap_path: str) -> str:
    """Get the working directory from a .cap file.

    Args:
        cap_path: Path to .cap file

    Returns:
        Working directory path string
    """
    cap_data = parse_cap_file(cap_path)
    return _normalise_settings(cap_data).get("workingDir", "")


def check_cap_working_dir(cap_path: str, expected: str) -> Dict[str, Any]:
    """Check if .cap file working directory matches expected value.

    Args:
        cap_path: Path to .cap file
        expected: Expected working directory

    Returns:
        Dict with 'match' (bool), 'expected', 'actual'
    """
    try:
        actual = get_working_dir(cap_path)
        match = actual == expected

        return {
            "match": match,
            "expected": expected,
            "actual": actual,
            "cap_file": cap_path,
        }
    except (FileNotFoundError, ValueError) as e:
        return {
            "match": False,
            "expected": expected,
            "cap_file": cap_path,
            "error": str(e),
        }


def get_command_line(cap_path: str) -> str:
    """Get the command line arguments from a .cap file.

    Args:
        cap_path: Path to .cap file

    Returns:
        Command line string
    """
    cap_data = parse_cap_file(cap_path)
    return _normalise_settings(cap_data).get("commandLine", "")


def check_cap_command_line(cap_path: str, substring: str) -> Dict[str, Any]:
    """Check if .cap file command line contains a substring.

    Args:
        cap_path: Path to .cap file
        substring: Substring to search for in command line

    Returns:
        Dict with 'match' (bool), 'substring', 'actual'
    """
    try:
        actual = get_command_line(cap_path)
        match = substring in actual

        return {
            "match": match,
            "substring": substring,
            "actual": actual,
            "cap_file": cap_path,
        }
    except (FileNotFoundError, ValueError) as e:
        return {
            "match": False,
            "substring": substring,
            "cap_file": cap_path,
            "error": str(e),
        }


def get_option(cap_path: str, key: str) -> Any:
    """Get an option value from a .cap file.

    Args:
        cap_path: Path to .cap file
        key: Option key name

    Returns:
        Option value, or None if not found
    """
    cap_data = parse_cap_file(cap_path)
    options = _normalise_settings(cap_data).get("options", {})
    return options.get(key)


def check_cap_option(cap_path: str, key: str, expected: Any) -> Dict[str, Any]:
    """Check if a .cap file option matches expected value.

    Args:
        cap_path: Path to .cap file
        key: Option key name
        expected: Expected value

    Returns:
        Dict with 'match' (bool), 'key', 'expected', 'actual'
    """
    try:
        actual = get_option(cap_path, key)

        # If expected is a string, try to parse as JSON for comparison
        if isinstance(expected, str):
            try:
                expected_parsed = json.loads(expected)
            except json.JSONDecodeError:
                expected_parsed = expected
        else:
            expected_parsed = expected

        match = actual == expected_parsed

        return {
            "match": match,
            "key": key,
            "expected": expected_parsed,
            "actual": actual,
            "cap_file": cap_path,
        }
    except (FileNotFoundError, ValueError) as e:
        return {
            "match": False,
            "key": key,
            "expected": expected,
            "cap_file": cap_path,
            "error": str(e),
        }


def get_environment_var(cap_path: str, var_name: str) -> Optional[str]:
    """Get an environment variable value from a .cap file.

    Args:
        cap_path: Path to .cap file
        var_name: Environment variable name

    Returns:
        Environment variable value, or None if not found
    """
    cap_data = parse_cap_file(cap_path)
    env = _normalise_settings(cap_data).get("environment", {})
    if isinstance(env, dict):
        return env.get(var_name)
    if isinstance(env, list):
        for item in env:
            if isinstance(item, str) and item.split("=", 1)[0] == var_name:
                return item.split("=", 1)[1] if "=" in item else ""
            if isinstance(item, dict) and (item.get("name") or item.get("variable")) == var_name:
                return item.get("value")
    return None


def check_cap_env(cap_path: str, var_name: str,
                  expected_value: Optional[str] = None) -> Dict[str, Any]:
    """Check if a .cap file has an environment variable (optionally with expected value).

    Args:
        cap_path: Path to .cap file
        var_name: Environment variable name
        expected_value: Expected value (if None, only checks existence)

    Returns:
        Dict with 'match' (bool), 'var_name', 'expected', 'actual'
    """
    try:
        actual = get_environment_var(cap_path, var_name)
        exists = actual is not None

        if expected_value is None:
            # Only check existence
            return {
                "match": exists,
                "var_name": var_name,
                "exists": exists,
                "actual": actual,
                "cap_file": cap_path,
            }
        else:
            # Check both existence and value
            match = exists and (actual == expected_value)
            return {
                "match": match,
                "var_name": var_name,
                "expected": expected_value,
                "actual": actual,
                "exists": exists,
                "cap_file": cap_path,
            }
    except (FileNotFoundError, ValueError) as e:
        return {
            "match": False,
            "var_name": var_name,
            "expected": expected_value,
            "cap_file": cap_path,
            "error": str(e),
        }


def list_all_options(cap_path: str) -> Dict[str, Any]:
    """List all options in a .cap file.

    Args:
        cap_path: Path to .cap file

    Returns:
        Dict with 'options' (dict), 'count'
    """
    cap_data = parse_cap_file(cap_path)
    options = _normalise_settings(cap_data).get("options", {})

    return {
        "options": options,
        "count": len(options),
    }


def list_all_environment_vars(cap_path: str) -> Dict[str, Any]:
    """List all environment variables in a .cap file.

    Args:
        cap_path: Path to .cap file

    Returns:
        Dict with 'environment' (dict), 'count'
    """
    cap_data = parse_cap_file(cap_path)
    env = _normalise_settings(cap_data).get("environment", {})

    return {
        "environment": env,
        "count": len(env),
    }


def get_cap_summary(cap_path: str) -> Dict[str, Any]:
    """Get a comprehensive summary of a .cap file.

    Args:
        cap_path: Path to .cap file

    Returns:
        Dict with all cap file fields
    """
    try:
        cap_data = parse_cap_file(cap_path)
        settings = _normalise_settings(cap_data)
        options = list_all_options(cap_path)
        env = list_all_environment_vars(cap_path)

        return {
            "executable": settings.get("executable", ""),
            "command_line": settings.get("commandLine", ""),
            "working_dir": settings.get("workingDir", ""),
            "options": options["options"],
            "option_count": options["count"],
            "environment": env["environment"],
            "environment_count": env["count"],
            "cap_file": cap_path,
        }
    except (FileNotFoundError, ValueError) as e:
        return {
            "error": str(e),
            "cap_file": cap_path,
        }
