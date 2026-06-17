"""
Shotcut Verifier — programmatic state inspection for Shotcut projects in E2B sandbox.

Shotcut is a free open-source video editor. Native project files are .mlt
(Media Lovin' Toolkit XML). User configuration lives in
~/.config/Meltytech/Shotcut.conf (Qt INI). Exports go through ffmpeg.

Verification channels (in order of preference):
  1. XML parsing — .mlt project files (producers/chains/tracks/filters/transitions/profile)
  2. INI parsing — ~/.config/Meltytech/Shotcut.conf (recent files, theme, defaults)
  3. ffprobe — verify exported media files (codec, resolution, duration, fps)

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/shotcut.py project-info /path/to/project.mlt")
    sandbox.commands.run("python3 /home/user/verifiers/shotcut.py clips /path/to/project.mlt")
    sandbox.commands.run("python3 /home/user/verifiers/shotcut.py check-clip-count /path/to/project.mlt 3")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - ffprobe (from ffmpeg) for export-info / check-export-output
  - Python standard library only (xml.etree.ElementTree, configparser, subprocess)

Skipped categories (documented here so task generators do not use them):
  - Keybindings: Shotcut has no user-editable keybinding file the verifier can parse.
  - Extensions/plugins: Shotcut has no plugin system.
  - Live IPC: Shotcut has no D-Bus/WebSocket/AT-SPI state interface; all
    verification is file-based.
"""

import configparser
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SHOTCUT_CONFIG = Path.home() / ".config" / "Meltytech" / "Shotcut.conf"


# ---------------------------------------------------------------------------
# XML helpers — .mlt files
# ---------------------------------------------------------------------------

def _parse_project(filepath: str) -> ET.ElementTree:
    """Parse a .mlt project file and return the ElementTree."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Project file not found: {filepath}")
    if path.suffix.lower() not in (".mlt", ".xml"):
        raise ValueError(f"Not a .mlt file: {filepath}")
    return ET.parse(filepath)


def _get_root(filepath: str) -> ET.Element:
    """Parse and return the root <mlt> element."""
    tree = _parse_project(filepath)
    root = tree.getroot()
    if root.tag != "mlt":
        raise ValueError(f"Expected <mlt> root element, got <{root.tag}>")
    return root


def _props(elem: ET.Element) -> dict:
    """Collect all direct <property name="..."> children of an element."""
    out = {}
    for prop in elem.findall("property"):
        name = prop.get("name", "")
        if name:
            out[name] = prop.text or ""
    return out


def _get_profile(root: ET.Element) -> dict:
    """Extract <profile> element attributes."""
    profile = root.find(".//profile")
    if profile is None:
        return {"error": "No <profile> element found in project"}
    return dict(profile.attrib)


def _get_producers(root: ET.Element) -> list[dict]:
    """Extract all <producer> and <chain> elements (media clips).

    Shotcut (modern) stores clips as <chain> elements in the timeline and
    also writes <producer> elements. The verifier searches both so it works
    on files produced by current Shotcut versions AND hand-crafted .mlt.
    """
    results = []
    for tag in ("producer", "chain"):
        for elem in root.iter(tag):
            info = {
                "id": elem.get("id", ""),
                "in": elem.get("in", ""),
                "out": elem.get("out", ""),
                "tag": tag,
            }
            props = _props(elem)
            # Common MLT properties we care about
            for key in (
                "resource", "mlt_service", "length", "shotcut:caption",
                "shotcut:hash", "audio_index", "video_index",
                "shotcut:producer", "shotcut:defaultAudioIndex",
                "kdenlive:clipname", "xml",
            ):
                if key in props:
                    info[key] = props[key]
            results.append(info)
    return results


def _get_playlists(root: ET.Element) -> list[dict]:
    """Extract all <playlist> elements (bin + tracks)."""
    playlists = []
    for pl in root.iter("playlist"):
        entries = []
        for entry in pl.findall("entry"):
            entries.append({
                "producer": entry.get("producer", ""),
                "in": entry.get("in", ""),
                "out": entry.get("out", ""),
            })
        blanks = []
        for blank in pl.findall("blank"):
            blanks.append({"length": blank.get("length", "")})

        info = {"id": pl.get("id", "")}
        props = _props(pl)
        for key in (
            "shotcut:name", "shotcut:audio", "shotcut:video",
            "shotcut:hidden", "shotcut:locked",
        ):
            if key in props:
                info[key] = props[key]
        info["entries"] = entries
        info["blanks"] = blanks
        playlists.append(info)
    return playlists


def _get_tracks_from_tractor(root: ET.Element) -> list[dict]:
    """Extract track references from the main <tractor>."""
    tracks = []
    tractor = root.find(".//tractor")
    if tractor is None:
        return tracks
    for t in tractor.findall("track"):
        tracks.append({"producer": t.get("producer", "")})
    return tracks


def _get_filters(root: ET.Element) -> list[dict]:
    """Extract all <filter> elements (effects)."""
    filters = []
    for filt in root.iter("filter"):
        info = {
            "id": filt.get("id", ""),
            "in": filt.get("in", ""),
            "out": filt.get("out", ""),
        }
        props = _props(filt)
        for key in (
            "mlt_service", "shotcut:filter", "shotcut:name",
            "kdenlive_id", "disable",
        ):
            if key in props:
                info[key] = props[key]
        track = filt.get("track")
        if track:
            info["track"] = track
        filters.append(info)
    return filters


def _get_transitions(root: ET.Element) -> list[dict]:
    """Extract all <transition> elements."""
    transitions = []
    for trans in root.iter("transition"):
        info = {
            "id": trans.get("id", ""),
            "in": trans.get("in", ""),
            "out": trans.get("out", ""),
        }
        props = _props(trans)
        for key in (
            "mlt_service", "a_track", "b_track", "always_active",
            "version", "progressive", "resource",
        ):
            if key in props:
                info[key] = props[key]
        transitions.append(info)
    return transitions


def _run_ffprobe(filepath: str) -> dict:
    """Run ffprobe on a media file and return parsed JSON output."""
    path = Path(filepath)
    if not path.exists():
        return {"error": f"File not found: {filepath}"}

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                filepath,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {"error": f"ffprobe failed: {result.stderr[:300]}"}
        return json.loads(result.stdout)
    except FileNotFoundError:
        return {"error": "ffprobe not found. Install ffmpeg."}
    except subprocess.TimeoutExpired:
        return {"error": "ffprobe timed out"}
    except json.JSONDecodeError:
        return {"error": f"ffprobe returned invalid JSON: {result.stdout[:300]}"}


# ---------------------------------------------------------------------------
# Config (INI) helpers
# ---------------------------------------------------------------------------

def _load_config(path: str | None = None) -> tuple[configparser.ConfigParser | None, str | None]:
    """Load Shotcut.conf as a ConfigParser. Returns (config, error)."""
    cfg_path = Path(path) if path else SHOTCUT_CONFIG
    if not cfg_path.exists():
        return None, f"Shotcut config not found: {cfg_path}"
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    # Qt INI files preserve case
    parser.optionxform = str  # type: ignore
    try:
        parser.read(str(cfg_path))
    except Exception as e:
        return None, f"Cannot parse {cfg_path}: {e}"
    return parser, None


def _config_get(section: str, key: str, path: str | None = None) -> Any:
    cfg, err = _load_config(path)
    if err:
        return {"error": err}
    if not cfg.has_section(section):
        return {"error": f"Section '{section}' not found", "sections": cfg.sections()}
    if not cfg.has_option(section, key):
        return {"error": f"Key '{key}' not found in section '{section}'",
                "keys": cfg.options(section)}
    return {"section": section, "key": key, "value": cfg.get(section, key)}


# ---------------------------------------------------------------------------
# ShotcutVerifier class
# ---------------------------------------------------------------------------

class ShotcutVerifier:
    """Stateless verifier — each method call is independent."""

    # === Query endpoints ===

    def get_project_info(self, filepath: str) -> dict:
        """Get project settings: profile + counts of clips/tracks/filters/transitions."""
        root = _get_root(filepath)
        profile = _get_profile(root)
        producers = _get_producers(root)
        playlists = _get_playlists(root)
        filters = _get_filters(root)
        transitions = _get_transitions(root)
        tractor_tracks = _get_tracks_from_tractor(root)

        return {
            "file": str(filepath),
            "profile": profile,
            "producer_count": len(producers),
            "playlist_count": len(playlists),
            "tractor_track_count": len(tractor_tracks),
            "filter_count": len(filters),
            "transition_count": len(transitions),
        }

    def get_clips(self, filepath: str) -> list[dict]:
        """List all media clips (producers + chains)."""
        root = _get_root(filepath)
        return _get_producers(root)

    def get_playlists(self, filepath: str) -> list[dict]:
        """List all <playlist> elements (bin + tracks)."""
        root = _get_root(filepath)
        return _get_playlists(root)

    def get_tracks(self, filepath: str) -> list[dict]:
        """List tracks referenced by the main <tractor>."""
        root = _get_root(filepath)
        return _get_tracks_from_tractor(root)

    def get_filters(self, filepath: str) -> list[dict]:
        """List all filter/effect elements."""
        root = _get_root(filepath)
        return _get_filters(root)

    def get_transitions(self, filepath: str) -> list[dict]:
        """List all transition elements."""
        root = _get_root(filepath)
        return _get_transitions(root)

    def get_clip_info(self, filepath: str, clip_id: str) -> dict:
        """Detailed info for a specific <producer> or <chain> by id."""
        root = _get_root(filepath)
        for tag in ("producer", "chain"):
            for elem in root.iter(tag):
                if elem.get("id") == clip_id:
                    info = {
                        "id": elem.get("id", ""),
                        "in": elem.get("in", ""),
                        "out": elem.get("out", ""),
                        "tag": tag,
                    }
                    info.update(_props(elem))
                    return info
        return {"error": f"Clip '{clip_id}' not found"}

    def get_profile(self, filepath: str) -> dict:
        """Return <profile> attributes (resolution, fps, colorspace, aspect)."""
        root = _get_root(filepath)
        return _get_profile(root)

    def get_export_info(self, output_file: str) -> dict:
        """Run ffprobe on an exported file and return its metadata."""
        return _run_ffprobe(output_file)

    # --- Config endpoints ---

    def get_config(self, path: str | None = None) -> dict:
        """Return the full Shotcut.conf as a nested dict."""
        cfg, err = _load_config(path)
        if err:
            return {"error": err}
        out = {}
        for section in cfg.sections():
            out[section] = {k: cfg.get(section, k) for k in cfg.options(section)}
        return out

    def get_config_value(self, section: str, key: str, path: str | None = None) -> dict:
        return _config_get(section, key, path)

    def get_recent_files(self, path: str | None = None) -> dict:
        """Read the list of recent files from Shotcut.conf.

        Qt stores recent files under [RecentFiles] with keys like:
            1\\Path = /home/user/foo.mlt
            size = 10
        """
        cfg, err = _load_config(path)
        if err:
            return {"error": err}
        # Collect all sections that contain RecentFiles information
        recent = []
        for section in cfg.sections():
            if section.lower().startswith("recentfiles"):
                for key in cfg.options(section):
                    val = cfg.get(section, key)
                    if val:
                        recent.append({"key": key, "value": val})
        return {"recent_files": recent}

    # === Check endpoints ===

    def check_file_exists(self, path: str) -> dict:
        """Check if a file exists on disk."""
        p = Path(path)
        exists = p.exists()
        result: dict[str, Any] = {"exists": exists, "path": str(path)}
        if exists:
            result["size"] = p.stat().st_size
            result["is_file"] = p.is_file()
        return result

    def check_clip_exists(self, filepath: str, needle: str) -> dict:
        """Check if any clip's resource / caption / id contains `needle`."""
        root = _get_root(filepath)
        producers = _get_producers(root)
        needle_lc = needle.lower()
        matches = []
        for prod in producers:
            fields = " ".join(str(prod.get(k, "")) for k in (
                "id", "resource", "shotcut:caption", "kdenlive:clipname",
            )).lower()
            if needle_lc in fields:
                matches.append(prod)
        return {
            "exists": len(matches) > 0,
            "match_count": len(matches),
            "matches": matches,
        }

    def check_clip_count(self, filepath: str, expected_count: int) -> dict:
        """Check the project has exactly the expected number of clips."""
        root = _get_root(filepath)
        actual = len(_get_producers(root))
        return {"match": actual == expected_count,
                "expected": expected_count, "actual": actual}

    def check_playlist_count(self, filepath: str, expected_count: int) -> dict:
        """Check the project has exactly the expected number of <playlist>s."""
        root = _get_root(filepath)
        actual = len(_get_playlists(root))
        return {"match": actual == expected_count,
                "expected": expected_count, "actual": actual}

    def check_track_count(self, filepath: str, expected_count: int) -> dict:
        """Check the number of tracks referenced by the main <tractor>."""
        root = _get_root(filepath)
        actual = len(_get_tracks_from_tractor(root))
        return {"match": actual == expected_count,
                "expected": expected_count, "actual": actual}

    def check_filter_exists(self, filepath: str, needle: str) -> dict:
        """Check if a filter with matching mlt_service/id/shotcut:name exists."""
        root = _get_root(filepath)
        filters = _get_filters(root)
        needle_lc = needle.lower()
        matches = []
        for f in filters:
            fields = " ".join(str(f.get(k, "")) for k in (
                "id", "mlt_service", "shotcut:filter", "shotcut:name", "kdenlive_id",
            )).lower()
            if needle_lc in fields:
                matches.append(f)
        return {"exists": len(matches) > 0,
                "match_count": len(matches), "matches": matches}

    def check_filter_count(self, filepath: str, expected_count: int) -> dict:
        """Check exact number of filters in the project."""
        root = _get_root(filepath)
        actual = len(_get_filters(root))
        return {"match": actual == expected_count,
                "expected": expected_count, "actual": actual}

    def check_transition_exists(self, filepath: str, transition_type: str) -> dict:
        """Check if a transition of the given mlt_service/id exists."""
        root = _get_root(filepath)
        transitions = _get_transitions(root)
        needle_lc = transition_type.lower()
        matches = []
        for t in transitions:
            fields = " ".join(str(t.get(k, "")) for k in ("id", "mlt_service")).lower()
            if needle_lc in fields:
                matches.append(t)
        return {"exists": len(matches) > 0,
                "match_count": len(matches), "matches": matches}

    def check_transition_count(self, filepath: str, expected_count: int) -> dict:
        """Check exact number of transitions in the project."""
        root = _get_root(filepath)
        actual = len(_get_transitions(root))
        return {"match": actual == expected_count,
                "expected": expected_count, "actual": actual}

    def check_resolution(self, filepath: str, width: int, height: int) -> dict:
        """Check project profile resolution matches width x height."""
        root = _get_root(filepath)
        profile = _get_profile(root)
        if "error" in profile:
            return profile
        try:
            aw = int(profile.get("width", 0))
            ah = int(profile.get("height", 0))
        except ValueError:
            return {"match": False, "error": "Non-integer width/height in profile"}
        return {"match": aw == width and ah == height,
                "expected": {"width": width, "height": height},
                "actual": {"width": aw, "height": ah}}

    def check_fps(self, filepath: str, expected_fps: float) -> dict:
        """Check project frame rate matches expected_fps (within 0.01)."""
        root = _get_root(filepath)
        profile = _get_profile(root)
        if "error" in profile:
            return profile
        try:
            num = int(profile.get("frame_rate_num", 0))
            den = int(profile.get("frame_rate_den", 1))
        except ValueError:
            return {"match": False, "error": "Non-integer fps num/den"}
        actual = num / den if den else 0.0
        return {"match": abs(actual - expected_fps) < 0.01,
                "expected": expected_fps, "actual": actual}

    def check_clip_resource(self, filepath: str, clip_id: str, substring: str) -> dict:
        """Check a specific clip's resource property contains a substring."""
        info = self.get_clip_info(filepath, clip_id)
        if "error" in info:
            return info
        resource = info.get("resource", "")
        return {
            "match": substring in resource,
            "clip_id": clip_id,
            "resource": resource,
            "needle": substring,
        }

    def check_playlist_entry_count(self, filepath: str, playlist_id: str,
                                   expected_count: int) -> dict:
        """Check a specific playlist contains the expected number of entries."""
        root = _get_root(filepath)
        for pl in root.iter("playlist"):
            if pl.get("id") == playlist_id:
                n = len(pl.findall("entry"))
                return {"match": n == expected_count,
                        "expected": expected_count, "actual": n,
                        "playlist_id": playlist_id}
        return {"error": f"Playlist '{playlist_id}' not found"}

    def check_config_value(self, section: str, key: str, expected: str,
                           path: str | None = None) -> dict:
        """Check a Shotcut.conf setting equals expected string value."""
        got = _config_get(section, key, path)
        if "error" in got:
            return {"match": False, **got}
        actual = got.get("value", "")
        return {"match": str(actual) == str(expected),
                "section": section, "key": key,
                "expected": expected, "actual": actual}

    def check_export_output(self, output_file: str) -> dict:
        """Verify an exported media file exists and is a valid media file."""
        p = Path(output_file)
        if not p.exists():
            return {"valid": False, "error": f"File not found: {output_file}"}
        if p.stat().st_size == 0:
            return {"valid": False, "error": f"File is empty: {output_file}"}

        probe = _run_ffprobe(output_file)
        if "error" in probe:
            return {"valid": False, **probe}

        fmt = probe.get("format", {})
        streams = probe.get("streams", [])
        video_codec = None
        audio_codec = None
        width = None
        height = None
        for s in streams:
            if s.get("codec_type") == "video":
                if not video_codec:
                    video_codec = s.get("codec_name")
                    width = s.get("width")
                    height = s.get("height")
            elif s.get("codec_type") == "audio" and not audio_codec:
                audio_codec = s.get("codec_name")

        return {
            "valid": True,
            "path": str(output_file),
            "size": p.stat().st_size,
            "duration": fmt.get("duration"),
            "format_name": fmt.get("format_name"),
            "video_codec": video_codec,
            "audio_codec": audio_codec,
            "width": width,
            "height": height,
            "stream_count": len(streams),
        }

    def check_export_resolution(self, output_file: str, width: int, height: int) -> dict:
        """Check the exported file's video resolution matches width x height."""
        probe = _run_ffprobe(output_file)
        if "error" in probe:
            return {"match": False, **probe}
        for s in probe.get("streams", []):
            if s.get("codec_type") == "video":
                aw = s.get("width")
                ah = s.get("height")
                return {"match": aw == width and ah == height,
                        "expected": {"width": width, "height": height},
                        "actual": {"width": aw, "height": ah}}
        return {"match": False, "error": "No video stream found"}

    def check_export_codec(self, output_file: str, codec: str, stream_type: str = "video") -> dict:
        """Check the exported file has a stream with the given codec.

        stream_type: 'video' or 'audio'.
        """
        probe = _run_ffprobe(output_file)
        if "error" in probe:
            return {"match": False, **probe}
        for s in probe.get("streams", []):
            if s.get("codec_type") == stream_type:
                cname = s.get("codec_name", "")
                return {"match": cname == codec,
                        "expected": codec, "actual": cname,
                        "stream_type": stream_type}
        return {"match": False, "error": f"No {stream_type} stream found"}


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

COMMANDS = {
    # Query
    "project-info":    ("Get project profile + counts",
                        lambda v, a: v.get_project_info(a[0])),
    "clips":           ("List all media clips",
                        lambda v, a: v.get_clips(a[0])),
    "playlists":       ("List all playlists (bin + tracks)",
                        lambda v, a: v.get_playlists(a[0])),
    "tracks":          ("List tractor track references",
                        lambda v, a: v.get_tracks(a[0])),
    "filters":         ("List all filters/effects",
                        lambda v, a: v.get_filters(a[0])),
    "transitions":     ("List all transitions",
                        lambda v, a: v.get_transitions(a[0])),
    "clip-info":       ("Detailed clip info by id",
                        lambda v, a: v.get_clip_info(a[0], a[1])),
    "profile":         ("Video profile (resolution, fps)",
                        lambda v, a: v.get_profile(a[0])),
    "export-info":     ("ffprobe metadata for an exported file",
                        lambda v, a: v.get_export_info(a[0])),
    "config":          ("Dump Shotcut.conf as JSON (optional path)",
                        lambda v, a: v.get_config(a[0] if a else None)),
    "config-value":    ("Read one setting: <section> <key> [path]",
                        lambda v, a: v.get_config_value(a[0], a[1], a[2] if len(a) > 2 else None)),
    "recent-files":    ("Recent files from Shotcut.conf (optional path)",
                        lambda v, a: v.get_recent_files(a[0] if a else None)),

    # Checks
    "check-file-exists":      ("Check file exists",
                               lambda v, a: v.check_file_exists(a[0])),
    "check-clip-exists":      ("Check clip exists in project",
                               lambda v, a: v.check_clip_exists(a[0], a[1])),
    "check-clip-count":       ("Check number of clips",
                               lambda v, a: v.check_clip_count(a[0], int(a[1]))),
    "check-playlist-count":   ("Check number of playlists",
                               lambda v, a: v.check_playlist_count(a[0], int(a[1]))),
    "check-track-count":      ("Check number of tractor tracks",
                               lambda v, a: v.check_track_count(a[0], int(a[1]))),
    "check-filter-exists":    ("Check filter/effect exists",
                               lambda v, a: v.check_filter_exists(a[0], a[1])),
    "check-filter-count":     ("Check number of filters",
                               lambda v, a: v.check_filter_count(a[0], int(a[1]))),
    "check-transition-exists":("Check transition type exists",
                               lambda v, a: v.check_transition_exists(a[0], a[1])),
    "check-transition-count": ("Check number of transitions",
                               lambda v, a: v.check_transition_count(a[0], int(a[1]))),
    "check-resolution":       ("Check project resolution",
                               lambda v, a: v.check_resolution(a[0], int(a[1]), int(a[2]))),
    "check-fps":              ("Check project frame rate",
                               lambda v, a: v.check_fps(a[0], float(a[1]))),
    "check-clip-resource":    ("Check clip resource contains substring",
                               lambda v, a: v.check_clip_resource(a[0], a[1], a[2])),
    "check-playlist-entry-count": ("Check specific playlist entry count",
                               lambda v, a: v.check_playlist_entry_count(a[0], a[1], int(a[2]))),
    "check-config-value":     ("Check config setting equals value",
                               lambda v, a: v.check_config_value(a[0], a[1], a[2], a[3] if len(a) > 3 else None)),
    "check-export-output":    ("Check exported file is valid",
                               lambda v, a: v.check_export_output(a[0])),
    "check-export-resolution":("Check exported file resolution",
                               lambda v, a: v.check_export_resolution(a[0], int(a[1]), int(a[2]))),
    "check-export-codec":     ("Check exported file codec <file> <codec> [video|audio]",
                               lambda v, a: v.check_export_codec(a[0], a[1], a[2] if len(a) > 2 else "video")),
}


def _print_usage():
    print("Shotcut Verifier — query Shotcut project state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print("\nAll output is JSON. .mlt files are MLT XML. Export verification uses ffprobe.")
    print(f"Config path: {SHOTCUT_CONFIG}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = ShotcutVerifier()
    _, handler = COMMANDS[cmd]

    try:
        result = handler(v, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except FileNotFoundError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))
