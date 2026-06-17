"""
VLC Verifier — programmatic state inspection for VLC media player in E2B sandbox.

Verification channels (in order of preference):
  1. HTTP API — real-time playback state (requires --intf http)
  2. D-Bus/MPRIS2 — playback control queries via playerctl
  3. File-based — vlcrc config, recent media, ffprobe media analysis

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/vlc.py status")
    sandbox.commands.run("python3 /home/user/verifiers/vlc.py check-playing")
    sandbox.commands.run("python3 /home/user/verifiers/vlc.py media-file-info /path/to/video.mp4")

Usage from Python (inside sandbox or via E2B):
    from verifiers.vlc import VLCVerifier
    v = VLCVerifier()
    status = v.get_status()
    playing = v.check_playing()

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - VLC launched with: vlc --intf http --http-port 8080 --http-password secret
  - playerctl (optional, for D-Bus/MPRIS2 queries)
  - ffprobe (optional, for media file analysis)
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
import base64
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HTTP_HOST = "127.0.0.1"
HTTP_PORT = int(os.environ.get("VLC_HTTP_PORT", 8080))
HTTP_PASSWORD = os.environ.get("VLC_HTTP_PASSWORD", "secret")
HTTP_BASE = f"http://:{HTTP_PASSWORD}@{HTTP_HOST}:{HTTP_PORT}"
MPRIS_DEST = "org.mpris.MediaPlayer2.vlc"
MPRIS_OBJECT_PATH = "/org/mpris/MediaPlayer2"
MPRIS_PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"

VLC_CONFIG_DIR = Path.home() / ".config" / "vlc"
VLC_RC_PATH = VLC_CONFIG_DIR / "vlcrc"
VLC_QT_CONF_PATH = VLC_CONFIG_DIR / "vlc-qt-interface.conf"


# ---------------------------------------------------------------------------
# HTTP API helpers
# ---------------------------------------------------------------------------

def _http_get(path: str, timeout: float = 5.0) -> Any:
    """GET a VLC HTTP API endpoint, return parsed JSON."""
    url = f"http://{HTTP_HOST}:{HTTP_PORT}{path}"
    # VLC HTTP API uses basic auth with empty username and configured password
    credentials = base64.b64encode(f":{HTTP_PASSWORD}".encode()).decode()
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Basic {credentials}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        return {"error": f"VLC HTTP API connection failed: {e}. Is VLC running with --intf http --http-port {HTTP_PORT}?"}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON from VLC HTTP API: {e}"}


def _http_status(timeout: float = 5.0) -> dict:
    """Get VLC playback status via HTTP API."""
    return _http_get("/requests/status.json", timeout)


def _http_playlist(timeout: float = 5.0) -> dict:
    """Get VLC playlist via HTTP API."""
    return _http_get("/requests/playlist.json", timeout)


# ---------------------------------------------------------------------------
# D-Bus/MPRIS2 helpers (via playerctl or gdbus fallback)
# ---------------------------------------------------------------------------

def _playerctl(subcommand: str, timeout: float = 5.0) -> dict:
    """Run a playerctl command targeting VLC and return the result."""
    try:
        result = subprocess.run(
            ["playerctl", "--player=vlc", subcommand],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "No players found" in stderr or "No player could handle" in stderr:
                return {"error": f"VLC not found via D-Bus. Is VLC running? ({stderr})"}
            return {"error": f"playerctl error: {stderr}"}
        return {"value": result.stdout.strip()}
    except FileNotFoundError:
        return {"error": "playerctl not installed"}
    except subprocess.TimeoutExpired:
        return {"error": "playerctl timed out"}


def _mpris_call(method_args: list[str], timeout: float = 5.0) -> dict:
    """Run a gdbus call against VLC's MPRIS endpoint and return stdout."""
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", MPRIS_DEST,
                "--object-path", MPRIS_OBJECT_PATH,
                *method_args,
            ],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            return {"error": f"gdbus error: {stderr}"}
        return {"value": result.stdout.strip()}
    except FileNotFoundError:
        return {"error": "gdbus not installed"}
    except subprocess.TimeoutExpired:
        return {"error": "gdbus timed out"}


def _mpris_unescape(value: str) -> str:
    """Decode the limited escapes used by gdbus string rendering."""
    return value.replace("\\'", "'").replace("\\\\", "\\")


def _mpris_extract_string(raw: str) -> str | None:
    """Extract a string from a gdbus variant payload like (<\'Playing\'>,)."""
    patterns = (
        r"\(\s*<\s*'((?:\\.|[^'])*)'\s*>\s*,?\s*\)$",
        r"\(\s*'((?:\\.|[^'])*)'\s*,?\s*\)$",
    )
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            return _mpris_unescape(match.group(1))
    return None


def _mpris_extract_float(raw: str) -> float | None:
    """Extract a float from a gdbus variant payload."""
    patterns = (
        r"\(\s*<\s*(?:double\s+)?([-+]?\d+(?:\.\d+)?)\s*>\s*,?\s*\)$",
        r"\(\s*(?:double\s+)?([-+]?\d+(?:\.\d+)?)\s*,?\s*\)$",
    )
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            return float(match.group(1))
    return None


def _mpris_dict_string(raw: str, key: str) -> str | None:
    """Extract a string field from a gdbus-rendered metadata dict."""
    patterns = (
        rf"'{re.escape(key)}':\s*<\s*'((?:\\.|[^'])*)'\s*>",
        rf"'{re.escape(key)}':\s*'((?:\\.|[^'])*)'",
    )
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            return _mpris_unescape(match.group(1))
    return None


def _mpris_dict_int(raw: str, key: str) -> int | None:
    """Extract an integer field from a gdbus-rendered metadata dict."""
    patterns = (
        rf"'{re.escape(key)}':\s*<\s*(?:int64|uint64|int32|uint32)\s+(-?\d+)\s*>",
        rf"'{re.escape(key)}':\s*<\s*(-?\d+)\s*>",
        rf"'{re.escape(key)}':\s*(-?\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            return int(match.group(1))
    return None


def _mpris_get_player_property(prop: str, timeout: float = 5.0) -> dict:
    """Read a VLC MPRIS Player property using gdbus."""
    result = _mpris_call(
        [
            "--method", "org.freedesktop.DBus.Properties.Get",
            MPRIS_PLAYER_IFACE,
            prop,
        ],
        timeout=timeout,
    )
    if "error" in result:
        return result

    raw = str(result.get("value") or "")
    if prop == "PlaybackStatus":
        value = _mpris_extract_string(raw)
        if value is None:
            return {"error": f"Could not parse MPRIS PlaybackStatus: {raw}"}
        return {"value": value}
    if prop == "Volume":
        value = _mpris_extract_float(raw)
        if value is None:
            return {"error": f"Could not parse MPRIS Volume: {raw}"}
        return {"value": value}
    return {"value": raw}


def _mpris_get_metadata(timeout: float = 5.0) -> dict:
    """Get current track metadata directly from VLC's MPRIS endpoint."""
    result = _mpris_get_player_property("Metadata", timeout=timeout)
    if "error" in result:
        return result

    raw = str(result.get("value") or "")
    metadata = {
        "artist": "",
        "title": _mpris_dict_string(raw, "xesam:title") or "",
        "album": _mpris_dict_string(raw, "xesam:album") or "",
        "url": _mpris_dict_string(raw, "xesam:url") or "",
    }
    length_us = _mpris_dict_int(raw, "mpris:length")
    metadata["length_us"] = str(length_us) if length_us is not None else ""
    return metadata


def _dbus_status(timeout: float = 5.0) -> dict:
    """Get VLC playback status via playerctl, falling back to gdbus."""
    result = _playerctl("status", timeout=timeout)
    if "error" not in result:
        return result
    return _mpris_get_player_property("PlaybackStatus", timeout=timeout)


def _playerctl_metadata(timeout: float = 5.0) -> dict:
    """Get metadata for current track via playerctl."""
    try:
        result = subprocess.run(
            ["playerctl", "--player=vlc", "metadata", "--format",
             '{"artist":"{{artist}}","title":"{{title}}","album":"{{album}}","length_us":"{{mpris:length}}","url":"{{xesam:url}}"}'],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return {"error": f"playerctl metadata error: {result.stderr.strip()}"}
        try:
            return json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            return {"raw": result.stdout.strip()}
    except FileNotFoundError:
        return {"error": "playerctl not installed"}
    except subprocess.TimeoutExpired:
        return {"error": "playerctl metadata timed out"}


def _dbus_metadata(timeout: float = 5.0) -> dict:
    """Get VLC metadata via playerctl, falling back to gdbus."""
    result = _playerctl_metadata(timeout=timeout)
    if "error" not in result:
        return result
    return _mpris_get_metadata(timeout=timeout)


def _playerctl_volume(timeout: float = 5.0) -> dict:
    """Get current volume via D-Bus/MPRIS2 (playerctl volume)."""
    try:
        result = subprocess.run(
            ["playerctl", "--player=vlc", "volume"],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "No players found" in stderr or "No player could handle" in stderr:
                return {"error": f"VLC not found via D-Bus. Is VLC running? ({stderr})"}
            return {"error": f"playerctl volume error: {stderr}"}
        scalar = float(result.stdout.strip())
        return {
            "volume_scalar": scalar,
            "volume_percent": round(scalar * 100, 1),
            "volume_raw": round(scalar * 256),
        }
    except FileNotFoundError:
        return {"error": "playerctl not installed"}
    except ValueError:
        return {"error": f"playerctl volume output not parseable: {result.stdout.strip()}"}
    except subprocess.TimeoutExpired:
        return {"error": "playerctl volume timed out"}


def _dbus_volume(timeout: float = 5.0) -> dict:
    """Get VLC volume via playerctl, falling back to gdbus."""
    result = _playerctl_volume(timeout=timeout)
    if "error" not in result:
        return result

    prop = _mpris_get_player_property("Volume", timeout=timeout)
    if "error" in prop:
        return prop

    scalar = float(prop["value"])
    return {
        "volume_scalar": scalar,
        "volume_percent": round(scalar * 100, 1),
        "volume_raw": round(scalar * 256),
    }


def _http_filename(data: dict) -> str:
    """Extract the current filename from VLC HTTP status payload."""
    return str(
        data.get("information", {})
        .get("category", {})
        .get("meta", {})
        .get("filename")
        or ""
    ).strip()


def _dbus_state_value(data: dict) -> str | None:
    """Normalize a playerctl status payload into a lowercase state."""
    if "error" in data:
        return None
    value = str(data.get("value") or "").strip().lower()
    return value or None


def _basename_from_media_ref(value: str) -> str:
    """Get a filesystem basename from a local path or file:// URL."""
    if not value:
        return ""
    parsed = urlparse(value)
    path = parsed.path if parsed.scheme else value
    return os.path.basename(unquote(path))


def _http_status_is_stale(data: dict, dbus_state: str | None = None) -> bool:
    """Detect common cases where VLC's HTTP endpoint is not the active player session."""
    if "error" in data:
        return True
    state = str(data.get("state") or "").strip().lower()
    filename = _http_filename(data)
    if state == "stopped" and not filename:
        return True
    if dbus_state and state and state != dbus_state:
        return True
    return False


# ---------------------------------------------------------------------------
# File-based helpers
# ---------------------------------------------------------------------------

def _parse_vlcrc(key: str | None = None) -> dict:
    """Parse vlcrc config file. If key given, return that key's value."""
    if not VLC_RC_PATH.exists():
        return {"error": f"vlcrc not found at {VLC_RC_PATH}"}

    config = {}
    try:
        with open(VLC_RC_PATH, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    config[k.strip()] = v.strip()
    except Exception as e:
        return {"error": f"Failed to parse vlcrc: {e}"}

    if key is not None:
        if key in config:
            return {"key": key, "value": config[key]}
        # Try case-insensitive match
        for k, v in config.items():
            if k.lower() == key.lower():
                return {"key": k, "value": v}
        return {"error": f"Key '{key}' not found in vlcrc", "available_keys_sample": list(config.keys())[:20]}

    return {"key_count": len(config), "keys": list(config.keys())[:50]}


def _parse_recent_media() -> dict:
    """Parse recent media list from vlc-qt-interface.conf."""
    if not VLC_QT_CONF_PATH.exists():
        return {"error": f"vlc-qt-interface.conf not found at {VLC_QT_CONF_PATH}"}

    recent = []
    in_recent_section = False
    try:
        with open(VLC_QT_CONF_PATH, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line == "[RecentsMRL]":
                    in_recent_section = True
                    continue
                if in_recent_section:
                    if line.startswith("["):
                        break
                    if line.startswith("list="):
                        entries = line[5:].split(", ")
                        recent.extend(entries)
                    elif "=" in line and not line.startswith("list"):
                        # Other keys in section like times=
                        pass
    except Exception as e:
        return {"error": f"Failed to parse qt-interface.conf: {e}"}

    return {"count": len(recent), "recent": recent}


def _ffprobe_info(file_path: str) -> dict:
    """Get media file info using ffprobe."""
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", file_path],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {"error": f"ffprobe error: {result.stderr.strip()[:300]}"}
        data = json.loads(result.stdout)
        # Extract key info
        fmt = data.get("format", {})
        streams = data.get("streams", [])

        info = {
            "filename": fmt.get("filename"),
            "format_name": fmt.get("format_name"),
            "format_long_name": fmt.get("format_long_name"),
            "duration": float(fmt["duration"]) if "duration" in fmt else None,
            "size_bytes": int(fmt["size"]) if "size" in fmt else None,
            "bit_rate": int(fmt["bit_rate"]) if "bit_rate" in fmt else None,
            "streams": [],
        }

        for s in streams:
            stream_info = {
                "codec_type": s.get("codec_type"),
                "codec_name": s.get("codec_name"),
            }
            if s.get("codec_type") == "video":
                stream_info["width"] = s.get("width")
                stream_info["height"] = s.get("height")
                stream_info["fps"] = s.get("r_frame_rate")
            elif s.get("codec_type") == "audio":
                stream_info["sample_rate"] = s.get("sample_rate")
                stream_info["channels"] = s.get("channels")
            info["streams"].append(stream_info)

        return info
    except FileNotFoundError:
        return {"error": "ffprobe not installed"}
    except subprocess.TimeoutExpired:
        return {"error": "ffprobe timed out"}
    except json.JSONDecodeError as e:
        return {"error": f"ffprobe output not valid JSON: {e}"}


# ---------------------------------------------------------------------------
# VLCVerifier class
# ---------------------------------------------------------------------------

class VLCVerifier:
    """Stateless verifier -- each method call is independent."""

    # === HTTP API: Real-time state ===

    def get_status(self) -> dict:
        """Get current playback status via HTTP API.

        Example return:
        {
            "state": "playing",
            "position": 0.25,
            "time": 30,
            "length": 120,
            "volume": 256,
            "filename": "video.mp4",
            ...
        }
        """
        data = _http_status()
        if "error" in data:
            return data
        return {
            "state": data.get("state"),
            "position": data.get("position"),
            "time": data.get("time"),
            "length": data.get("length"),
            "volume": data.get("volume"),
            "filename": data.get("information", {}).get("category", {}).get("meta", {}).get("filename"),
            "fullscreen": data.get("fullscreen"),
            "loop": data.get("loop"),
            "repeat": data.get("repeat"),
            "random": data.get("random"),
        }

    def get_playlist(self) -> dict:
        """Get current playlist via HTTP API.

        Example return:
        {
            "count": 3,
            "items": [
                {"name": "video.mp4", "uri": "file:///path/video.mp4", "id": "3", "current": true},
                ...
            ]
        }
        """
        data = _http_playlist()
        if "error" in data:
            return data

        items = []
        # VLC playlist JSON has nested children structure
        for node in data.get("children", []):
            for child in node.get("children", []):
                items.append({
                    "name": child.get("name"),
                    "uri": child.get("uri"),
                    "id": child.get("id"),
                    "current": child.get("current", "") == "current",
                })

        return {"count": len(items), "items": items}

    def get_media_info(self) -> dict:
        """Get info about currently playing media via HTTP API.

        Returns the full information/category block from VLC status.
        """
        data = _http_status()
        if "error" in data:
            return data
        info = data.get("information", {})
        category = info.get("category", {})
        return {
            "meta": category.get("meta", {}),
            "streams": {k: v for k, v in category.items() if k != "meta"},
        }

    def get_volume(self) -> dict:
        """Get current volume level.

        VLC HTTP API returns volume on 0-512 scale (256 = 100%).
        """
        dbus = _dbus_volume()
        if "error" not in dbus:
            return {**dbus, "source": "dbus"}

        data = _http_status()
        if "error" in data:
            return data
        vol_raw = data.get("volume", 0)
        return {
            "volume_raw": vol_raw,
            "volume_percent": round((vol_raw / 256) * 100, 1) if isinstance(vol_raw, (int, float)) else None,
            "source": "http",
        }

    # === D-Bus/MPRIS2 queries ===

    def get_dbus_status(self) -> dict:
        """Get playback status via D-Bus/MPRIS2."""
        return _dbus_status()

    def get_dbus_metadata(self) -> dict:
        """Get current track metadata via D-Bus/MPRIS2."""
        return _dbus_metadata()

    def get_dbus_volume(self) -> dict:
        """Get current volume via D-Bus/MPRIS2."""
        return _dbus_volume()

    # === File-based queries ===

    def get_config(self, key: str | None = None) -> dict:
        """Read vlcrc config. Optionally get a specific key.

        Example:
            v.get_config("volume")
            => {"key": "volume", "value": "256"}
        """
        return _parse_vlcrc(key)

    def get_recent_media(self) -> dict:
        """List recent media from vlc-qt-interface.conf.

        Example return:
        {"count": 3, "recent": ["file:///path/video.mp4", ...]}
        """
        return _parse_recent_media()

    def get_media_file_info(self, file_path: str) -> dict:
        """Get media file info using ffprobe.

        Example:
            v.get_media_file_info("/path/to/video.mp4")
            => {"format_name": "mov,mp4", "duration": 120.5, "streams": [...]}
        """
        return _ffprobe_info(file_path)

    # === Composite checks ===

    def check_file_exists(self, path: str) -> dict:
        """Check if a file exists.

        Example:
            v.check_file_exists("/home/user/video.mp4")
            => {"exists": true, "size_bytes": 12345}
        """
        exists = os.path.exists(path)
        result = {"exists": exists}
        if exists:
            try:
                stat = os.stat(path)
                result["size_bytes"] = stat.st_size
                result["is_file"] = os.path.isfile(path)
            except OSError:
                pass
        return result

    def check_playing(self) -> dict:
        """Check if VLC is currently playing.

        Example:
            v.check_playing()
            => {"playing": true, "state": "playing", "filename": "video.mp4"}
        """
        data = _http_status()
        dbus = _dbus_status()
        dbus_state = _dbus_state_value(dbus)

        if dbus_state is not None and _http_status_is_stale(data, dbus_state):
            metadata = _dbus_metadata()
            current = _basename_from_media_ref(str(metadata.get("url") or "")) if "error" not in metadata else ""
            return {"playing": dbus_state == "playing", "state": dbus_state, "filename": current or None, "source": "dbus"}

        if "error" in data:
            if dbus_state is not None:
                metadata = _dbus_metadata()
                current = _basename_from_media_ref(str(metadata.get("url") or "")) if "error" not in metadata else ""
                return {"playing": dbus_state == "playing", "state": dbus_state, "filename": current or None, "source": "dbus"}
            return {"playing": False, "error": data["error"]}

        state = data.get("state", "")
        filename = _http_filename(data) or None
        return {"playing": state == "playing", "state": state, "filename": filename, "source": "http"}

    def check_media_loaded(self, filename: str) -> dict:
        """Check if a specific media file is loaded (by filename substring).

        Example:
            v.check_media_loaded("video.mp4")
            => {"loaded": true, "current_file": "video.mp4"}
        """
        expected = filename.lower()
        data = _http_status()
        dbus_status = _dbus_state_value(_dbus_status())
        current = _http_filename(data) if "error" not in data else ""
        loaded = expected in current.lower() if current else False
        if loaded and not _http_status_is_stale(data, dbus_status):
            return {"loaded": True, "current_file": current, "source": "http"}

        metadata = _dbus_metadata()
        if "error" not in metadata:
            url = str(metadata.get("url") or "")
            basename = _basename_from_media_ref(url)
            title = str(metadata.get("title") or "")
            candidates = [candidate for candidate in (basename, url, title) if candidate]
            dbus_loaded = any(expected in candidate.lower() for candidate in candidates)
            current_file = basename or url or title
            if dbus_loaded or "error" in data or not current or _http_status_is_stale(data, dbus_status):
                return {"loaded": dbus_loaded, "current_file": current_file, "source": "dbus"}

        if "error" in data:
            return {"loaded": False, "error": data["error"]}
        return {"loaded": loaded, "current_file": current, "source": "http"}

    def check_volume(self, level: int | float) -> dict:
        """Check if volume is at expected level.

        Accepts 0-100 (percent) or 0-512 (VLC raw scale).
        Values <= 100 are treated as percent, > 100 as raw.

        Example:
            v.check_volume(50)   # 50%
            => {"match": true, "expected_raw": 128, "actual_raw": 128}
        """
        level = float(level)

        # Interpret: <= 100 means percent, > 100 means raw
        if level <= 100:
            expected_raw = round((level / 100) * 256)
        else:
            expected_raw = round(level)

        # Allow a tolerance of +/- 5 raw units (~2%)
        tolerance = 5
        dbus_volume = _dbus_volume()
        if "error" not in dbus_volume:
            actual_raw = dbus_volume["volume_raw"]
            match = abs(actual_raw - expected_raw) <= tolerance
            return {
                "match": match,
                "expected_raw": expected_raw,
                "actual_raw": actual_raw,
                "expected_percent": round((expected_raw / 256) * 100, 1),
                "actual_percent": dbus_volume["volume_percent"],
                "actual_scalar": dbus_volume["volume_scalar"],
                "source": "dbus",
            }

        data = _http_status()
        dbus_state = _dbus_state_value(_dbus_status())
        if "error" in data:
            return {"match": False, "error": data["error"]}
        if _http_status_is_stale(data, dbus_state):
            return {
                "match": False,
                "error": "HTTP status is not a reliable source for volume in this VLC session",
                "source": "http",
            }

        actual_raw = data.get("volume", 0)
        match = abs(actual_raw - expected_raw) <= tolerance
        return {
            "match": match,
            "expected_raw": expected_raw,
            "actual_raw": actual_raw,
            "expected_percent": round((expected_raw / 256) * 100, 1),
            "actual_percent": round((actual_raw / 256) * 100, 1) if isinstance(actual_raw, (int, float)) else None,
            "source": "http",
        }

    def check_position(self, seconds: float, tolerance: float = 5.0) -> dict:
        """Check if playback position is at expected time (in seconds).

        Example:
            v.check_position(30, tolerance=5)
            => {"match": true, "expected": 30, "actual": 32, "tolerance": 5}
        """
        data = _http_status()
        if "error" in data:
            return {"match": False, "error": data["error"]}

        actual = data.get("time", 0)
        seconds = float(seconds)
        tolerance = float(tolerance)
        match = abs(actual - seconds) <= tolerance
        return {
            "match": match,
            "expected": seconds,
            "actual": actual,
            "tolerance": tolerance,
            "length": data.get("length"),
        }

    def check_media_duration(self, file_path: str, seconds: float, tolerance: float = 1.0) -> dict:
        """Verify a media file's duration using ffprobe.

        Example:
            v.check_media_duration("/path/video.mp4", 120, tolerance=2)
            => {"match": true, "expected": 120, "actual": 120.5, "tolerance": 2}
        """
        info = _ffprobe_info(file_path)
        if "error" in info:
            return {"match": False, "error": info["error"]}

        actual = info.get("duration")
        if actual is None:
            return {"match": False, "error": "Duration not available in file metadata"}

        seconds = float(seconds)
        tolerance = float(tolerance)
        match = abs(actual - seconds) <= tolerance
        return {
            "match": match,
            "expected": seconds,
            "actual": actual,
            "tolerance": tolerance,
        }

    def check_media_format(self, file_path: str, fmt: str) -> dict:
        """Verify a media file's format (container type).

        Example:
            v.check_media_format("/path/video.mp4", "mp4")
            => {"match": true, "expected": "mp4", "actual": "mov,mp4,m4a,3gp,3g2,mj2"}
        """
        info = _ffprobe_info(file_path)
        if "error" in info:
            return {"match": False, "error": info["error"]}

        actual = info.get("format_name", "")
        # ffprobe format_name can be comma-separated list like "mov,mp4,m4a,3gp"
        fmt_lower = fmt.lower()
        actual_lower = actual.lower()
        match = fmt_lower in actual_lower
        return {
            "match": match,
            "expected": fmt,
            "actual": actual,
        }

    def check_playlist_count(self, count: int) -> dict:
        """Check if playlist has expected number of items.

        Example:
            v.check_playlist_count(3)
            => {"match": true, "expected": 3, "actual": 3}
        """
        playlist = self.get_playlist()
        if "error" in playlist:
            return {"match": False, "error": playlist["error"]}

        actual = playlist.get("count", 0)
        count = int(count)
        return {
            "match": actual == count,
            "expected": count,
            "actual": actual,
        }

    def check_config(self, key: str, expected: str) -> dict:
        """Check if a vlcrc config key matches expected value.

        Example:
            v.check_config("volume", "256")
            => {"match": true, "key": "volume", "expected": "256", "actual": "256"}
        """
        data = _parse_vlcrc(key)
        if "error" in data:
            return {"match": False, "error": data["error"], "key": key, "expected": expected}

        actual = data.get("value", "")
        match = str(actual).strip() == str(expected).strip()
        return {"match": match, "key": key, "expected": expected, "actual": actual}

    def check_state(self, expected_state: str) -> dict:
        """Check if VLC is in a specific state (playing, paused, stopped).

        Example:
            v.check_state("paused")
            => {"match": true, "expected": "paused", "actual": "paused"}
        """
        data = _http_status()
        dbus = _dbus_status()
        dbus_state = _dbus_state_value(dbus)
        if dbus_state is not None and _http_status_is_stale(data, dbus_state):
            match = dbus_state == expected_state.lower()
            return {"match": match, "expected": expected_state, "actual": dbus_state, "source": "dbus"}
        if "error" in data:
            if dbus_state is not None:
                match = dbus_state == expected_state.lower()
                return {"match": match, "expected": expected_state, "actual": dbus_state, "source": "dbus"}
            return {"match": False, "error": data["error"]}
        actual = data.get("state", "")
        match = actual.lower() == expected_state.lower()
        return {"match": match, "expected": expected_state, "actual": actual, "source": "http"}

    def check_fullscreen(self, expected: bool = True) -> dict:
        """Check if VLC is in fullscreen mode.

        Example:
            v.check_fullscreen(true)
            => {"match": true, "fullscreen": true}
        """
        data = _http_status()
        if "error" in data:
            return {"match": False, "error": data["error"]}
        actual = data.get("fullscreen", False)
        if isinstance(expected, str):
            expected = expected.lower() in ("true", "1", "yes")
        match = bool(actual) == bool(expected)
        return {"match": match, "fullscreen": bool(actual)}

    def check_loop(self, expected: bool = True) -> dict:
        """Check if VLC loop mode is enabled.

        Example:
            v.check_loop(true)
            => {"match": true, "loop": true}
        """
        data = _http_status()
        if "error" in data:
            return {"match": False, "error": data["error"]}
        actual = data.get("loop", False)
        if isinstance(expected, str):
            expected = expected.lower() in ("true", "1", "yes")
        match = bool(actual) == bool(expected)
        return {"match": match, "loop": bool(actual)}

    def check_repeat(self, expected: bool = True) -> dict:
        """Check if VLC repeat mode is enabled.

        Example:
            v.check_repeat(true)
            => {"match": true, "repeat": true}
        """
        data = _http_status()
        if "error" in data:
            return {"match": False, "error": data["error"]}
        actual = data.get("repeat", False)
        if isinstance(expected, str):
            expected = expected.lower() in ("true", "1", "yes")
        match = bool(actual) == bool(expected)
        return {"match": match, "repeat": bool(actual)}

    def check_random(self, expected: bool = True) -> dict:
        """Check if VLC random/shuffle mode is enabled.

        Example:
            v.check_random(true)
            => {"match": true, "random": true}
        """
        data = _http_status()
        if "error" in data:
            return {"match": False, "error": data["error"]}
        actual = data.get("random", False)
        if isinstance(expected, str):
            expected = expected.lower() in ("true", "1", "yes")
        match = bool(actual) == bool(expected)
        return {"match": match, "random": bool(actual)}

    def check_media_has_video(self, file_path: str) -> dict:
        """Check if a media file contains a video stream.

        Example:
            v.check_media_has_video("/path/video.mp4")
            => {"has_video": true, "codec": "h264", "width": 1920, "height": 1080}
        """
        info = _ffprobe_info(file_path)
        if "error" in info:
            return {"has_video": False, "error": info["error"]}

        for s in info.get("streams", []):
            if s.get("codec_type") == "video":
                return {
                    "has_video": True,
                    "codec": s.get("codec_name"),
                    "width": s.get("width"),
                    "height": s.get("height"),
                }
        return {"has_video": False}

    def check_media_has_audio(self, file_path: str) -> dict:
        """Check if a media file contains an audio stream.

        Example:
            v.check_media_has_audio("/path/video.mp4")
            => {"has_audio": true, "codec": "aac", "channels": 2, "sample_rate": "44100"}
        """
        info = _ffprobe_info(file_path)
        if "error" in info:
            return {"has_audio": False, "error": info["error"]}

        for s in info.get("streams", []):
            if s.get("codec_type") == "audio":
                return {
                    "has_audio": True,
                    "codec": s.get("codec_name"),
                    "channels": s.get("channels"),
                    "sample_rate": s.get("sample_rate"),
                }
        return {"has_audio": False}

    def check_media_resolution(self, file_path: str, width: int, height: int) -> dict:
        """Check if a video file has the expected resolution.

        Example:
            v.check_media_resolution("/path/video.mp4", 1280, 720)
            => {"match": true, "expected": [1280, 720], "actual": [1280, 720]}
        """
        info = _ffprobe_info(file_path)
        if "error" in info:
            return {"match": False, "error": info["error"]}

        width = int(width)
        height = int(height)
        for s in info.get("streams", []):
            if s.get("codec_type") == "video":
                actual_w = s.get("width")
                actual_h = s.get("height")
                match = actual_w == width and actual_h == height
                return {
                    "match": match,
                    "expected": [width, height],
                    "actual": [actual_w, actual_h],
                }
        return {"match": False, "error": "No video stream found"}

    def check_media_codec(self, file_path: str, codec: str) -> dict:
        """Check if a media file uses a specific codec (audio or video).

        Example:
            v.check_media_codec("/path/video.mp4", "h264")
            => {"match": true, "expected": "h264", "found_in": "video", "actual": "h264"}
        """
        info = _ffprobe_info(file_path)
        if "error" in info:
            return {"match": False, "error": info["error"]}

        codec_lower = codec.lower()
        for s in info.get("streams", []):
            actual_codec = (s.get("codec_name") or "").lower()
            if codec_lower in actual_codec or actual_codec in codec_lower:
                return {
                    "match": True,
                    "expected": codec,
                    "found_in": s.get("codec_type"),
                    "actual": s.get("codec_name"),
                }
        all_codecs = [s.get("codec_name") for s in info.get("streams", [])]
        return {"match": False, "expected": codec, "actual_codecs": all_codecs}


# ---------------------------------------------------------------------------
# CLI interface -- for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

COMMANDS = {
    # HTTP API real-time
    "status": ("Playback status (state, position, volume)", lambda v, args: v.get_status()),
    "playlist": ("Current playlist items", lambda v, args: v.get_playlist()),
    "media-info": ("Info about currently playing media", lambda v, args: v.get_media_info()),
    "volume": ("Current volume level", lambda v, args: v.get_volume()),

    # D-Bus/MPRIS2
    "dbus-status": ("Playback status via D-Bus", lambda v, args: v.get_dbus_status()),
    "dbus-metadata": ("Track metadata via D-Bus", lambda v, args: v.get_dbus_metadata()),
    "dbus-volume": ("Volume via D-Bus", lambda v, args: v.get_dbus_volume()),

    # File-based
    "config": ("Read vlcrc config [key]", lambda v, args: v.get_config(args[0] if args else None)),
    "recent-media": ("List recent media from qt config", lambda v, args: v.get_recent_media()),
    "media-file-info": ("Media file info via ffprobe", lambda v, args: v.get_media_file_info(args[0])),

    # Composite checks
    "check-file-exists": ("Check file exists", lambda v, args: v.check_file_exists(args[0])),
    "check-playing": ("Is VLC currently playing", lambda v, args: v.check_playing()),
    "check-media-loaded": ("Is specific media loaded", lambda v, args: v.check_media_loaded(args[0])),
    "check-volume": ("Volume at expected level", lambda v, args: v.check_volume(float(args[0]))),
    "check-position": ("Playback at expected position",
                        lambda v, args: v.check_position(float(args[0]), float(args[1]) if len(args) > 1 else 5.0)),
    "check-media-duration": ("Verify media file duration",
                              lambda v, args: v.check_media_duration(args[0], float(args[1]), float(args[2]) if len(args) > 2 else 1.0)),
    "check-media-format": ("Verify media file format", lambda v, args: v.check_media_format(args[0], args[1])),
    "check-playlist-count": ("Playlist has expected item count", lambda v, args: v.check_playlist_count(int(args[0]))),
    "check-config": ("Check vlcrc config value", lambda v, args: v.check_config(args[0], args[1])),
    "check-state": ("Check playback state", lambda v, args: v.check_state(args[0])),
    "check-fullscreen": ("Check fullscreen mode", lambda v, args: v.check_fullscreen(args[0] if args else True)),
    "check-loop": ("Check loop mode", lambda v, args: v.check_loop(args[0] if args else True)),
    "check-repeat": ("Check repeat mode", lambda v, args: v.check_repeat(args[0] if args else True)),
    "check-random": ("Check random/shuffle mode", lambda v, args: v.check_random(args[0] if args else True)),
    "check-media-has-video": ("Check media has video stream", lambda v, args: v.check_media_has_video(args[0])),
    "check-media-has-audio": ("Check media has audio stream", lambda v, args: v.check_media_has_audio(args[0])),
    "check-media-resolution": ("Check video resolution", lambda v, args: v.check_media_resolution(args[0], int(args[1]), int(args[2]))),
    "check-media-codec": ("Check media uses specific codec", lambda v, args: v.check_media_codec(args[0], args[1])),
}


def _print_usage():
    print("VLC Verifier — query VLC state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nAll output is JSON. HTTP API requires VLC running with --intf http --http-port {HTTP_PORT}")
    print(f"Environment variables: VLC_HTTP_PORT (default {HTTP_PORT}), VLC_HTTP_PASSWORD (default 'secret')")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = VLCVerifier()
    _, handler = COMMANDS[cmd]

    try:
        result = handler(v, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))
