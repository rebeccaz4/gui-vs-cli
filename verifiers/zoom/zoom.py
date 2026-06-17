"""
Zoom Verifier — programmatic state inspection for Zoom desktop client in E2B sandbox.

Verification channels (in order of preference):
  1. File-based — parse ~/.config/zoomus.conf (INI) via configparser
  2. File-based — parse ~/.zoom/data/ (recent meetings, zoom data files)
  3. Filesystem checks — recording directory, log files, chat transcripts

IMPORTANT: Zoom's verifiable surface in a headless sandbox is thin because most
meaningful state (login, meetings, contacts, calendar, chat history, screen-
sharing state, etc.) requires a live session with a real account. This verifier
therefore focuses on **local preferences and file-system state** that can be
read deterministically without logging in.

Skipped categories (NOT verifiable in this sandbox, documented in README):
  - Meeting state, participants, raise-hand, reactions
  - Contacts, directory, address book
  - Calendar events, scheduled meetings
  - Chat messages, IM history (login required)
  - Real-time audio/video levels, active-speaker state
  - Screen sharing / whiteboard state
  - Breakout room state
  - Cloud recording availability
  - Sign-in status, profile picture, SSO state

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/zoom.py config")
    sandbox.commands.run("python3 /home/user/verifiers/zoom.py check-config General autoMuteMic true")
    sandbox.commands.run("python3 /home/user/verifiers/zoom.py check-recording-path /home/user/ZoomRecordings")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.
"""

import configparser
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ZOOM_CONFIG_PATH = Path(os.environ.get(
    "ZOOM_CONFIG_PATH",
    Path.home() / ".config" / "zoomus.conf",
))
ZOOM_DATA_DIR = Path(os.environ.get(
    "ZOOM_DATA_DIR",
    Path.home() / ".zoom" / "data",
))
ZOOM_LOGS_DIR = Path(os.environ.get(
    "ZOOM_LOGS_DIR",
    Path.home() / ".zoom" / "logs",
))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config(path: Path | None = None) -> tuple[configparser.ConfigParser | None, str | None]:
    """Load and parse zoomus.conf. Returns (config, error)."""
    p = path or ZOOM_CONFIG_PATH
    if not p.exists():
        return None, f"Zoom config file not found: {p}"
    cfg = configparser.ConfigParser(strict=False, interpolation=None)
    # zoomus.conf is case-sensitive for keys
    cfg.optionxform = str  # type: ignore[assignment]
    try:
        cfg.read(str(p), encoding="utf-8")
        return cfg, None
    except configparser.Error as e:
        return None, f"Cannot parse {p}: {e}"
    except OSError as e:
        return None, f"Cannot read {p}: {e}"


def _normalize_bool(value: Any) -> bool | None:
    """Interpret a config value as a bool. Accepts true/false/1/0/yes/no."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("true", "1", "yes", "on", "enabled"):
        return True
    if s in ("false", "0", "no", "off", "disabled"):
        return False
    return None


def _values_equal(actual: Any, expected: str) -> bool:
    """Compare a config value to an expected string (bool-aware)."""
    if actual is None:
        return False
    actual_s = str(actual).strip()
    expected_s = str(expected).strip()
    if actual_s == expected_s:
        return True
    # Bool-aware comparison
    a = _normalize_bool(actual_s)
    e = _normalize_bool(expected_s)
    if a is not None and e is not None:
        return a == e
    # Case-insensitive fallback
    return actual_s.lower() == expected_s.lower()


# ---------------------------------------------------------------------------
# ZoomVerifier class
# ---------------------------------------------------------------------------

class ZoomVerifier:
    """Stateless verifier — each method call is independent."""

    # === File-based: zoomus.conf ===

    def get_config_path(self) -> dict:
        """Return the resolved zoomus.conf path and whether it exists."""
        return {
            "path": str(ZOOM_CONFIG_PATH),
            "exists": ZOOM_CONFIG_PATH.exists(),
        }

    def get_sections(self) -> list[str] | dict:
        """List all sections in zoomus.conf."""
        cfg, err = _load_config()
        if err:
            return {"error": err}
        return list(cfg.sections())

    def get_section(self, section: str) -> dict:
        """Return all key/value pairs in a section."""
        cfg, err = _load_config()
        if err:
            return {"error": err}
        if not cfg.has_section(section):
            return {"error": f"Section '{section}' not found",
                    "available_sections": list(cfg.sections())}
        return {k: cfg.get(section, k) for k in cfg.options(section)}

    def get_all_config(self) -> dict:
        """Dump entire zoomus.conf as nested dict."""
        cfg, err = _load_config()
        if err:
            return {"error": err}
        out: dict[str, dict[str, str]] = {}
        for section in cfg.sections():
            out[section] = {k: cfg.get(section, k) for k in cfg.options(section)}
        return out

    def get_value(self, section: str, key: str) -> dict:
        """Read a specific config value."""
        cfg, err = _load_config()
        if err:
            return {"error": err}
        if not cfg.has_section(section):
            return {"error": f"Section '{section}' not found"}
        if not cfg.has_option(section, key):
            return {"error": f"Key '{key}' not found in section '{section}'",
                    "available_keys": cfg.options(section)}
        value = cfg.get(section, key)
        return {"section": section, "key": key, "value": value}

    # === File-based: ~/.zoom/data/ ===

    def get_data_files(self) -> list[dict] | dict:
        """List files inside ~/.zoom/data/."""
        if not ZOOM_DATA_DIR.exists():
            return {"error": f"Zoom data directory not found: {ZOOM_DATA_DIR}"}
        files = []
        for p in sorted(ZOOM_DATA_DIR.rglob("*")):
            if p.is_file():
                try:
                    stat = p.stat()
                    files.append({
                        "path": str(p),
                        "name": p.name,
                        "size": stat.st_size,
                    })
                except OSError:
                    pass
        return files

    def get_log_files(self) -> list[dict] | dict:
        """List files inside ~/.zoom/logs/."""
        if not ZOOM_LOGS_DIR.exists():
            return {"error": f"Zoom logs directory not found: {ZOOM_LOGS_DIR}"}
        files = []
        for p in sorted(ZOOM_LOGS_DIR.rglob("*")):
            if p.is_file():
                try:
                    stat = p.stat()
                    files.append({
                        "path": str(p),
                        "name": p.name,
                        "size": stat.st_size,
                    })
                except OSError:
                    pass
        return files

    def get_recording_path(self) -> dict:
        """Return the configured local recording directory from [General]localRecordingPath."""
        cfg, err = _load_config()
        if err:
            return {"error": err}
        # Zoom stores it in a few different keys across versions — try them all.
        candidates = [
            ("General", "localRecordingPath"),
            ("General", "recordingPath"),
            ("Recording", "localRecordingPath"),
            ("Recording", "recordingPath"),
        ]
        for section, key in candidates:
            if cfg.has_section(section) and cfg.has_option(section, key):
                value = cfg.get(section, key)
                return {
                    "section": section,
                    "key": key,
                    "value": value,
                    "exists": Path(os.path.expanduser(value)).exists() if value else False,
                }
        return {"error": "No recording path key found in config",
                "searched": [f"{s}.{k}" for s, k in candidates]}

    def list_recordings(self, path: str | None = None) -> list[dict] | dict:
        """List recording files in the configured (or given) recording directory."""
        if path is None:
            rec = self.get_recording_path()
            if "error" in rec:
                return rec
            path = rec.get("value", "")
        d = Path(os.path.expanduser(path))
        if not d.exists():
            return {"error": f"Recording directory does not exist: {d}"}
        if not d.is_dir():
            return {"error": f"Not a directory: {d}"}
        files = []
        for p in sorted(d.rglob("*")):
            if p.is_file():
                try:
                    stat = p.stat()
                    files.append({
                        "path": str(p),
                        "name": p.name,
                        "size": stat.st_size,
                        "ext": p.suffix.lower(),
                    })
                except OSError:
                    pass
        return files

    def find_recent_meeting_ids(self) -> list[str] | dict:
        """Grep Zoom data files for recent meeting IDs (9-11 digit numbers)."""
        if not ZOOM_DATA_DIR.exists():
            return {"error": f"Zoom data directory not found: {ZOOM_DATA_DIR}"}
        ids: set[str] = set()
        pattern = re.compile(r"\b(\d{9,11})\b")
        for p in ZOOM_DATA_DIR.rglob("*"):
            if not p.is_file():
                continue
            try:
                # Only text-readable files
                with open(p, "rb") as f:
                    raw = f.read(1024 * 1024)  # up to 1 MB
                try:
                    text = raw.decode("utf-8", errors="ignore")
                except Exception:
                    continue
                for match in pattern.findall(text):
                    ids.add(match)
            except OSError:
                continue
        return sorted(ids)

    # === Check endpoints ===

    def check_config_exists(self) -> dict:
        """Check whether zoomus.conf exists on disk."""
        return {
            "exists": ZOOM_CONFIG_PATH.exists(),
            "path": str(ZOOM_CONFIG_PATH),
        }

    def check_section_exists(self, section: str) -> dict:
        """Check whether a section exists in zoomus.conf."""
        cfg, err = _load_config()
        if err:
            return {"exists": False, "error": err}
        return {
            "exists": cfg.has_section(section),
            "section": section,
        }

    def check_config(self, section: str, key: str, expected: str) -> dict:
        """Check that [section]key == expected (bool-aware)."""
        cfg, err = _load_config()
        if err:
            return {"match": False, "error": err}
        if not cfg.has_section(section):
            return {
                "match": False,
                "error": f"Section '{section}' not found",
                "section": section,
                "key": key,
                "expected": expected,
            }
        if not cfg.has_option(section, key):
            return {
                "match": False,
                "error": f"Key '{key}' not found in section '{section}'",
                "section": section,
                "key": key,
                "expected": expected,
            }
        actual = cfg.get(section, key)
        return {
            "match": _values_equal(actual, expected),
            "section": section,
            "key": key,
            "expected": expected,
            "actual": actual,
        }

    def check_config_contains(self, section: str, key: str, needle: str) -> dict:
        """Check that a config value contains a substring."""
        cfg, err = _load_config()
        if err:
            return {"match": False, "error": err}
        if not cfg.has_section(section) or not cfg.has_option(section, key):
            return {"match": False, "section": section, "key": key,
                    "error": "section/key not found"}
        actual = cfg.get(section, key)
        return {
            "match": needle in (actual or ""),
            "section": section,
            "key": key,
            "needle": needle,
            "actual": actual,
        }

    def check_recording_path(self, expected: str) -> dict:
        """Check that the configured recording path matches expected (exact or after ~ expansion)."""
        info = self.get_recording_path()
        if "error" in info:
            return {"match": False, "error": info["error"]}
        actual = info.get("value", "")
        exp_norm = os.path.expanduser(expected).rstrip("/")
        act_norm = os.path.expanduser(actual).rstrip("/")
        return {
            "match": exp_norm == act_norm,
            "expected": expected,
            "actual": actual,
        }

    def check_file_exists(self, path: str) -> dict:
        """Check if a file exists on disk."""
        p = Path(os.path.expanduser(path))
        exists = p.exists()
        result: dict[str, Any] = {"exists": exists, "path": str(p)}
        if exists:
            try:
                stat = p.stat()
                result["size"] = stat.st_size
                result["is_file"] = p.is_file()
                result["is_dir"] = p.is_dir()
            except OSError:
                pass
        return result

    def check_directory_exists(self, path: str) -> dict:
        """Check if a directory exists on disk."""
        p = Path(os.path.expanduser(path))
        return {
            "exists": p.exists() and p.is_dir(),
            "path": str(p),
        }

    def check_recording_count(self, expected: int, path: str | None = None) -> dict:
        """Check that the recording directory holds at least N files (non-recursive file count)."""
        files = self.list_recordings(path)
        if isinstance(files, dict) and "error" in files:
            return {"match": False, "error": files["error"]}
        assert isinstance(files, list)
        actual = len(files)
        return {
            "match": actual >= expected,
            "expected_min": expected,
            "actual": actual,
        }

    def check_language(self, expected: str) -> dict:
        """Check Zoom UI language. Zoom stores this under [General]languageID or [General]language."""
        cfg, err = _load_config()
        if err:
            return {"match": False, "error": err}
        candidates = [
            ("General", "language"),
            ("General", "languageID"),
        ]
        for section, key in candidates:
            if cfg.has_section(section) and cfg.has_option(section, key):
                actual = cfg.get(section, key)
                return {
                    "match": _values_equal(actual, expected),
                    "section": section,
                    "key": key,
                    "expected": expected,
                    "actual": actual,
                }
        return {"match": False, "error": "No language key found in [General]"}

    def check_bool_setting(self, section: str, key: str, expected: bool) -> dict:
        """Check that a config key parses to the expected boolean."""
        cfg, err = _load_config()
        if err:
            return {"match": False, "error": err}
        if not cfg.has_section(section) or not cfg.has_option(section, key):
            return {"match": False, "section": section, "key": key,
                    "error": "section/key not found"}
        actual = cfg.get(section, key)
        actual_bool = _normalize_bool(actual)
        return {
            "match": actual_bool is not None and actual_bool == expected,
            "section": section,
            "key": key,
            "expected": expected,
            "actual": actual,
            "parsed_bool": actual_bool,
        }


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

COMMANDS = {
    # Config introspection
    "config-path": ("Show resolved zoomus.conf path", lambda v, a: v.get_config_path()),
    "sections": ("List all zoomus.conf sections", lambda v, a: v.get_sections()),
    "section": ("Dump key/values in a section", lambda v, a: v.get_section(a[0])),
    "config": ("Dump full zoomus.conf as nested dict", lambda v, a: v.get_all_config()),
    "value": ("Read a single config value", lambda v, a: v.get_value(a[0], a[1])),

    # Data / recordings / logs
    "data-files": ("List files in ~/.zoom/data/", lambda v, a: v.get_data_files()),
    "log-files": ("List files in ~/.zoom/logs/", lambda v, a: v.get_log_files()),
    "recording-path": ("Return configured local recording path",
                      lambda v, a: v.get_recording_path()),
    "list-recordings": ("List recording files (in configured or given dir)",
                        lambda v, a: v.list_recordings(a[0] if a else None)),
    "recent-meeting-ids": ("Scan data dir for 9-11 digit meeting IDs",
                           lambda v, a: v.find_recent_meeting_ids()),

    # Checks (primary boolean key listed in README)
    "check-config-exists": ("zoomus.conf exists on disk",
                             lambda v, a: v.check_config_exists()),
    "check-section-exists": ("Config section exists",
                              lambda v, a: v.check_section_exists(a[0])),
    "check-config": ("[section]key matches expected value",
                      lambda v, a: v.check_config(a[0], a[1], a[2])),
    "check-config-contains": ("[section]key contains substring",
                               lambda v, a: v.check_config_contains(a[0], a[1], a[2])),
    "check-bool": ("[section]key parses to expected bool",
                    lambda v, a: v.check_bool_setting(a[0], a[1], a[2].lower() in ("true", "1", "yes"))),
    "check-language": ("Configured UI language matches expected",
                        lambda v, a: v.check_language(a[0])),
    "check-recording-path": ("Recording path matches expected",
                              lambda v, a: v.check_recording_path(a[0])),
    "check-file-exists": ("File exists on disk", lambda v, a: v.check_file_exists(a[0])),
    "check-directory-exists": ("Directory exists on disk",
                                lambda v, a: v.check_directory_exists(a[0])),
    "check-recording-count": ("Recording dir has >= N files",
                               lambda v, a: v.check_recording_count(int(a[0]),
                                                                     a[1] if len(a) > 1 else None)),
}


def _print_usage():
    print("Zoom Verifier — inspect Zoom desktop client state in E2B sandbox")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nConfig file: {ZOOM_CONFIG_PATH}")
    print(f"Data dir:    {ZOOM_DATA_DIR}")
    print(f"Logs dir:    {ZOOM_LOGS_DIR}")
    print("All output is JSON.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = ZoomVerifier()
    _, handler = COMMANDS[cmd]

    try:
        result = handler(v, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except ValueError as e:
        print(json.dumps({"error": f"Invalid argument: {e}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))
