"""
Kdenlive Verifier — programmatic state inspection for Kdenlive projects in E2B sandbox.

Verification channels (in order of preference):
  1. XML parsing — .kdenlive project files use MLT XML schema (clips, tracks, effects, transitions)
  2. ffprobe — verify rendered output media files
  3. File-based config — ~/.config/kdenliverc

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/kdenlive.py project-info /path/to/project.kdenlive")
    sandbox.commands.run("python3 /home/user/verifiers/kdenlive.py clips /path/to/project.kdenlive")
    sandbox.commands.run("python3 /home/user/verifiers/kdenlive.py check-clip-count /path/to/project.kdenlive 3")

Usage from Python (inside sandbox or via E2B):
    from verifiers.kdenlive import KdenliveVerifier
    v = KdenliveVerifier()
    info = v.get_project_info("/path/to/project.kdenlive")
    clips = v.get_clips("/path/to/project.kdenlive")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - ffprobe (from ffmpeg) for render-info
  - Python standard library only (xml.etree.ElementTree)
"""

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

KDENLIVE_CONFIG = Path.home() / ".config" / "kdenliverc"


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _parse_project(filepath: str) -> ET.ElementTree:
    """Parse a .kdenlive project file and return the ElementTree."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Project file not found: {filepath}")
    if not path.suffix == ".kdenlive":
        raise ValueError(f"Not a .kdenlive file: {filepath}")
    return ET.parse(filepath)


def _get_root(filepath: str) -> ET.Element:
    """Parse and return the root <mlt> element."""
    tree = _parse_project(filepath)
    root = tree.getroot()
    if root.tag != "mlt":
        raise ValueError(f"Expected <mlt> root element, got <{root.tag}>")
    return root


def _get_profile(root: ET.Element) -> dict:
    """Extract the <profile> element attributes."""
    profile = root.find(".//profile")
    if profile is None:
        return {"error": "No <profile> element found in project"}
    return dict(profile.attrib)


def _get_producers(root: ET.Element) -> list[dict]:
    """Extract all <producer> elements (media clips)."""
    producers = []
    for prod in root.iter("producer"):
        info = {"id": prod.get("id", ""), "in": prod.get("in", ""), "out": prod.get("out", "")}
        for prop in prod.iter("property"):
            name = prop.get("name", "")
            if name in ("resource", "kdenlive:clipname", "length", "kdenlive:clip_type",
                        "mlt_service", "audio_index", "video_index", "kdenlive:folderid",
                        "kdenlive:id", "kdenlive:originalurl"):
                info[name] = prop.text or ""
        producers.append(info)
    return producers


def _get_playlists(root: ET.Element) -> list[dict]:
    """Extract all <playlist> elements (tracks)."""
    playlists = []
    for pl in root.iter("playlist"):
        entries = []
        for entry in pl.iter("entry"):
            entries.append({
                "producer": entry.get("producer", ""),
                "in": entry.get("in", ""),
                "out": entry.get("out", ""),
            })
        blanks = []
        for blank in pl.iter("blank"):
            blanks.append({"length": blank.get("length", "")})

        info = {"id": pl.get("id", "")}
        # Collect playlist properties
        for prop in pl.iter("property"):
            name = prop.get("name", "")
            if name in ("kdenlive:track_name", "kdenlive:audio_track",
                        "kdenlive:locked_track", "hide"):
                info[name] = prop.text or ""
        info["entries"] = entries
        info["blanks"] = blanks
        playlists.append(info)
    return playlists


def _get_filters(root: ET.Element) -> list[dict]:
    """Extract all <filter> elements (effects)."""
    filters = []
    for filt in root.iter("filter"):
        info = {"id": filt.get("id", ""), "in": filt.get("in", ""), "out": filt.get("out", "")}
        for prop in filt.iter("property"):
            name = prop.get("name", "")
            if name in ("mlt_service", "kdenlive_id", "kdenlive:filter_name", "tag"):
                info[name] = prop.text or ""
        # Include track reference if present
        track = filt.get("track")
        if track:
            info["track"] = track
        filters.append(info)
    return filters


def _get_transitions(root: ET.Element) -> list[dict]:
    """Extract all <transition> elements."""
    transitions = []
    for trans in root.iter("transition"):
        info = {"id": trans.get("id", ""), "in": trans.get("in", ""), "out": trans.get("out", "")}
        for prop in trans.iter("property"):
            name = prop.get("name", "")
            if name in ("mlt_service", "kdenlive_id", "a_track", "b_track",
                        "compositing", "always_active"):
                info[name] = prop.text or ""
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
# KdenliveVerifier class
# ---------------------------------------------------------------------------

class KdenliveVerifier:
    """Stateless verifier -- each method call is independent."""

    # === Query endpoints ===

    def get_project_info(self, filepath: str) -> dict:
        """Get project settings: resolution, fps, duration, colorspace.

        Example return:
        {
            "file": "/path/to/project.kdenlive",
            "profile": {"width": "1920", "height": "1080", "frame_rate_num": "25", ...},
            "producer_count": 5,
            "track_count": 3,
            "filter_count": 2,
            "transition_count": 1
        }
        """
        root = _get_root(filepath)
        profile = _get_profile(root)
        producers = _get_producers(root)
        playlists = _get_playlists(root)
        filters = _get_filters(root)
        transitions = _get_transitions(root)

        return {
            "file": str(filepath),
            "profile": profile,
            "producer_count": len(producers),
            "track_count": len(playlists),
            "filter_count": len(filters),
            "transition_count": len(transitions),
        }

    def get_clips(self, filepath: str) -> list[dict]:
        """List all media clips (producers) in the project.

        Example return:
        [
            {"id": "producer0", "resource": "/path/to/clip.mp4", "length": "250", ...},
            ...
        ]
        """
        root = _get_root(filepath)
        return _get_producers(root)

    def get_tracks(self, filepath: str) -> list[dict]:
        """List all tracks (playlists) in the project.

        Example return:
        [
            {"id": "playlist0", "kdenlive:track_name": "Video 1", "entries": [...], ...},
            ...
        ]
        """
        root = _get_root(filepath)
        return _get_playlists(root)

    def get_effects(self, filepath: str) -> list[dict]:
        """List all effects (filters) in the project.

        Example return:
        [
            {"id": "filter0", "mlt_service": "frei0r.glow", "kdenlive_id": "glow", ...},
            ...
        ]
        """
        root = _get_root(filepath)
        return _get_filters(root)

    def get_transitions(self, filepath: str) -> list[dict]:
        """List all transitions in the project.

        Example return:
        [
            {"id": "transition0", "mlt_service": "luma", "a_track": "0", "b_track": "1", ...},
            ...
        ]
        """
        root = _get_root(filepath)
        return _get_transitions(root)

    def get_clip_info(self, filepath: str, producer_id: str) -> dict:
        """Get detailed info for a specific producer/clip by ID.

        Example:
            v.get_clip_info("project.kdenlive", "producer0")
            => {"id": "producer0", "resource": "/path/to/clip.mp4", ...}
        """
        root = _get_root(filepath)
        for prod in root.iter("producer"):
            if prod.get("id") == producer_id:
                info = {"id": prod.get("id", ""), "in": prod.get("in", ""), "out": prod.get("out", "")}
                for prop in prod.iter("property"):
                    name = prop.get("name", "")
                    info[name] = prop.text or ""
                return info
        return {"error": f"Producer '{producer_id}' not found"}

    def get_profile(self, filepath: str) -> dict:
        """Get video profile (resolution, fps, colorspace, etc.).

        Example return:
        {"width": "1920", "height": "1080", "frame_rate_num": "25",
         "frame_rate_den": "1", "colorspace": "709", ...}
        """
        root = _get_root(filepath)
        return _get_profile(root)

    def get_render_info(self, output_file: str) -> dict:
        """Get info about a rendered output file using ffprobe.

        Example return:
        {"format": {"filename": "...", "duration": "10.5", ...},
         "streams": [{"codec_type": "video", "width": 1920, ...}, ...]}
        """
        return _run_ffprobe(output_file)

    # === Check endpoints ===

    def check_file_exists(self, path: str) -> dict:
        """Check if a file exists.

        Example:
            v.check_file_exists("/path/to/file.mp4")
            => {"exists": true, "path": "/path/to/file.mp4", "size": 12345}
        """
        p = Path(path)
        exists = p.exists()
        result = {"exists": exists, "path": str(path)}
        if exists:
            result["size"] = p.stat().st_size
            result["is_file"] = p.is_file()
        return result

    def check_clip_exists(self, filepath: str, clip_name_or_resource: str) -> dict:
        """Check if a clip matching name or resource path exists in the project.

        Example:
            v.check_clip_exists("project.kdenlive", "clip.mp4")
            => {"exists": true, "matches": [{"id": "producer0", "resource": "/path/clip.mp4"}]}
        """
        root = _get_root(filepath)
        producers = _get_producers(root)
        matches = []
        search = clip_name_or_resource.lower()
        for prod in producers:
            resource = prod.get("resource", "").lower()
            clipname = prod.get("kdenlive:clipname", "").lower()
            if search in resource or search in clipname or search in prod.get("id", "").lower():
                matches.append(prod)
        return {
            "exists": len(matches) > 0,
            "match_count": len(matches),
            "matches": matches,
        }

    def check_clip_count(self, filepath: str, expected_count: int) -> dict:
        """Check that the project has exactly the expected number of clips.

        Example:
            v.check_clip_count("project.kdenlive", 3)
            => {"match": true, "expected": 3, "actual": 3}
        """
        root = _get_root(filepath)
        producers = _get_producers(root)
        actual = len(producers)
        return {
            "match": actual == expected_count,
            "expected": expected_count,
            "actual": actual,
        }

    def check_track_count(self, filepath: str, expected_count: int) -> dict:
        """Check that the project has exactly the expected number of tracks.

        Example:
            v.check_track_count("project.kdenlive", 4)
            => {"match": true, "expected": 4, "actual": 4}
        """
        root = _get_root(filepath)
        playlists = _get_playlists(root)
        actual = len(playlists)
        return {
            "match": actual == expected_count,
            "expected": expected_count,
            "actual": actual,
        }

    def check_effect_exists(self, filepath: str, effect_id: str) -> dict:
        """Check if an effect/filter with the given ID or mlt_service exists.

        Example:
            v.check_effect_exists("project.kdenlive", "frei0r.glow")
            => {"exists": true, "matches": [...]}
        """
        root = _get_root(filepath)
        filters = _get_filters(root)
        search = effect_id.lower()
        matches = []
        for f in filters:
            if (search in f.get("id", "").lower()
                    or search in f.get("mlt_service", "").lower()
                    or search in f.get("kdenlive_id", "").lower()
                    or search in f.get("kdenlive:filter_name", "").lower()):
                matches.append(f)
        return {
            "exists": len(matches) > 0,
            "match_count": len(matches),
            "matches": matches,
        }

    def check_transition_exists(self, filepath: str, transition_type: str) -> dict:
        """Check if a transition of the given type/mlt_service exists.

        Example:
            v.check_transition_exists("project.kdenlive", "luma")
            => {"exists": true, "matches": [...]}
        """
        root = _get_root(filepath)
        transitions = _get_transitions(root)
        search = transition_type.lower()
        matches = []
        for t in transitions:
            if (search in t.get("id", "").lower()
                    or search in t.get("mlt_service", "").lower()
                    or search in t.get("kdenlive_id", "").lower()):
                matches.append(t)
        return {
            "exists": len(matches) > 0,
            "match_count": len(matches),
            "matches": matches,
        }

    def check_resolution(self, filepath: str, width: int, height: int) -> dict:
        """Check that the project resolution matches expected width and height.

        Example:
            v.check_resolution("project.kdenlive", 1920, 1080)
            => {"match": true, "expected": {"width": 1920, "height": 1080},
                "actual": {"width": 1920, "height": 1080}}
        """
        root = _get_root(filepath)
        profile = _get_profile(root)
        if "error" in profile:
            return profile
        actual_w = int(profile.get("width", 0))
        actual_h = int(profile.get("height", 0))
        return {
            "match": actual_w == width and actual_h == height,
            "expected": {"width": width, "height": height},
            "actual": {"width": actual_w, "height": actual_h},
        }

    def check_fps(self, filepath: str, expected_fps: float) -> dict:
        """Check that the project frame rate matches the expected value.

        Example:
            v.check_fps("project.kdenlive", 25.0)
            => {"match": true, "expected": 25.0, "actual": 25.0}
        """
        root = _get_root(filepath)
        profile = _get_profile(root)
        if "error" in profile:
            return profile
        num = int(profile.get("frame_rate_num", 0))
        den = int(profile.get("frame_rate_den", 1))
        actual_fps = num / den if den != 0 else 0.0
        return {
            "match": abs(actual_fps - expected_fps) < 0.01,
            "expected": expected_fps,
            "actual": actual_fps,
        }

    def check_render_output(self, output_file: str) -> dict:
        """Check that a rendered output file exists and is a valid media file.

        Example:
            v.check_render_output("/path/to/output.mp4")
            => {"valid": true, "path": "/path/to/output.mp4", "duration": "10.5",
                "video_codec": "h264", "audio_codec": "aac"}
        """
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
        for s in streams:
            if s.get("codec_type") == "video" and not video_codec:
                video_codec = s.get("codec_name")
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
            "stream_count": len(streams),
        }


# ---------------------------------------------------------------------------
# CLI interface -- for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

COMMANDS = {
    # Query
    "project-info": ("Get project settings", lambda v, args: v.get_project_info(args[0])),
    "clips": ("List all media clips", lambda v, args: v.get_clips(args[0])),
    "tracks": ("List all tracks", lambda v, args: v.get_tracks(args[0])),
    "effects": ("List all effects/filters", lambda v, args: v.get_effects(args[0])),
    "transitions": ("List all transitions", lambda v, args: v.get_transitions(args[0])),
    "clip-info": ("Detailed clip info by producer ID", lambda v, args: v.get_clip_info(args[0], args[1])),
    "profile": ("Video profile (resolution, fps)", lambda v, args: v.get_profile(args[0])),
    "render-info": ("Info about rendered output (ffprobe)", lambda v, args: v.get_render_info(args[0])),

    # Checks
    "check-file-exists": ("Check file exists", lambda v, args: v.check_file_exists(args[0])),
    "check-clip-exists": ("Check clip exists in project", lambda v, args: v.check_clip_exists(args[0], args[1])),
    "check-clip-count": ("Check number of clips", lambda v, args: v.check_clip_count(args[0], int(args[1]))),
    "check-track-count": ("Check number of tracks", lambda v, args: v.check_track_count(args[0], int(args[1]))),
    "check-effect-exists": ("Check effect exists", lambda v, args: v.check_effect_exists(args[0], args[1])),
    "check-transition-exists": ("Check transition type exists", lambda v, args: v.check_transition_exists(args[0], args[1])),
    "check-resolution": ("Check project resolution", lambda v, args: v.check_resolution(args[0], int(args[1]), int(args[2]))),
    "check-fps": ("Check project frame rate", lambda v, args: v.check_fps(args[0], float(args[1]))),
    "check-render-output": ("Check rendered file is valid", lambda v, args: v.check_render_output(args[0])),
}


def _print_usage():
    print("Kdenlive Verifier -- query Kdenlive project state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print("\nAll output is JSON. .kdenlive files are MLT XML. Render verification uses ffprobe.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = KdenliveVerifier()
    _, handler = COMMANDS[cmd]

    try:
        result = handler(v, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except FileNotFoundError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))
