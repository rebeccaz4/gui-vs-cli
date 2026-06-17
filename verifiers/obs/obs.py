"""
OBS Studio Verifier — programmatic state inspection for OBS Studio in E2B sandbox.

Verification channels (in order of preference):
  1. File-based (offline) — parse scene collection JSON and profile INI files
     No running OBS instance required.
  2. obs-websocket (live) — real-time state via OBS WebSocket protocol (port 4455)
     Requires OBS 28+ running with WebSocket server enabled.

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/obs.py scenes")
    sandbox.commands.run("python3 /home/user/verifiers/obs.py check-scene-exists MyScene")
    sandbox.commands.run("python3 /home/user/verifiers/obs.py live-status")

Usage from Python (inside sandbox or via E2B):
    from verifiers.obs import OBSVerifier
    v = OBSVerifier()
    scenes = v.get_scenes()
    exists = v.check_scene_exists("MyScene")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - Scene collection files at ~/.config/obs-studio/basic/scenes/<collection>.json
  - Profile files at ~/.config/obs-studio/basic/profiles/<profile>/basic.ini
  - For live endpoints: pip install obsws-python (OBS must be running)
"""

import configparser
import json
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OBS_WS_HOST = "127.0.0.1"
OBS_WS_PORT = 4455
OBS_WS_PASSWORD = os.environ.get("OBS_WS_PASSWORD", "")

OBS_CONFIG_DIR = Path(os.environ.get(
    "OBS_CONFIG_DIR",
    Path.home() / ".config" / "obs-studio",
))

SCENES_DIR = OBS_CONFIG_DIR / "basic" / "scenes"
PROFILES_DIR = OBS_CONFIG_DIR / "basic" / "profiles"


# ---------------------------------------------------------------------------
# File-based helpers
# ---------------------------------------------------------------------------

def _find_scene_collection(collection_file: str | None = None) -> Path | None:
    """Resolve a scene collection JSON file path.

    If collection_file is given:
      - Treat as absolute path if it starts with /
      - Otherwise look in SCENES_DIR for <collection_file> or <collection_file>.json
    If not given, return the first .json found in SCENES_DIR.
    """
    if collection_file:
        p = Path(collection_file)
        if p.is_absolute():
            return p if p.exists() else None
        # Relative to scenes dir
        candidate = SCENES_DIR / collection_file
        if candidate.exists():
            return candidate
        if not collection_file.endswith(".json"):
            candidate = SCENES_DIR / f"{collection_file}.json"
            if candidate.exists():
                return candidate
        return None

    # Auto-discover first collection
    if SCENES_DIR.exists():
        for f in sorted(SCENES_DIR.glob("*.json")):
            return f
    return None


def _load_scene_collection(collection_file: str | None = None) -> tuple[dict | None, str | None]:
    """Load and parse a scene collection JSON file.

    Returns (data_dict, error_string). Exactly one will be None.
    """
    path = _find_scene_collection(collection_file)
    if path is None:
        if collection_file:
            return None, f"Scene collection not found: {collection_file}"
        return None, f"No scene collection files found in {SCENES_DIR}"

    try:
        with open(path) as f:
            data = json.load(f)
        return data, None
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON in {path}: {e}"
    except OSError as e:
        return None, f"Cannot read {path}: {e}"


def _load_profile(profile_name: str | None = None) -> tuple[configparser.ConfigParser | None, str | None]:
    """Load a profile's basic.ini.

    Returns (config, error_string). Exactly one will be None.
    """
    if not PROFILES_DIR.exists():
        return None, f"Profiles directory not found: {PROFILES_DIR}"

    if profile_name:
        ini_path = PROFILES_DIR / profile_name / "basic.ini"
    else:
        # Auto-discover first profile
        ini_path = None
        for d in sorted(PROFILES_DIR.iterdir()):
            candidate = d / "basic.ini"
            if candidate.exists():
                ini_path = candidate
                break
        if ini_path is None:
            return None, f"No profiles found in {PROFILES_DIR}"

    if not ini_path.exists():
        return None, f"Profile config not found: {ini_path}"

    config = configparser.ConfigParser()
    try:
        config.read(str(ini_path))
        return config, None
    except Exception as e:
        return None, f"Cannot parse {ini_path}: {e}"


def _extract_sources_from_scene(scene: dict) -> list[dict]:
    """Extract the list of sources from a scene dict.

    OBS scene collections store sources under various keys depending on
    the version.  Common layouts:
      - scene["settings"]["items"]  (array of source dicts)
      - scene["sources"] (older format)
    """
    sources = []

    # Try settings.items first (most common modern format)
    items = scene.get("settings", {}).get("items", [])
    if items:
        for item in items:
            sources.append({
                "name": item.get("name", ""),
                "id": item.get("id", item.get("source_uuid", "")),
                "visible": item.get("visible", True),
                "locked": item.get("locked", False),
                "pos_x": item.get("pos", {}).get("x", 0) if isinstance(item.get("pos"), dict) else 0,
                "pos_y": item.get("pos", {}).get("y", 0) if isinstance(item.get("pos"), dict) else 0,
            })
        return sources

    # Fallback: top-level sources array in the scene
    for item in scene.get("sources", []):
        sources.append({
            "name": item.get("name", ""),
            "id": item.get("id", ""),
            "visible": item.get("visible", True),
        })

    return sources


def _all_sources_from_collection(data: dict) -> list[dict]:
    """Get every unique source across all scenes in a collection.

    Also includes top-level 'sources' array that OBS stores separately
    from the scene tree.
    """
    seen = set()
    results = []

    # Top-level sources array (OBS stores full source definitions here)
    for src in data.get("sources", []):
        name = src.get("name", "")
        if name and name not in seen:
            seen.add(name)
            results.append({
                "name": name,
                "type": src.get("versioned_id", src.get("id", "")),
                "settings": src.get("settings", {}),
                "enabled": src.get("enabled", True),
                "muted": src.get("mute", src.get("muted", False)),
            })

    # Also walk scene items for names that might not be in top-level sources
    for scene in data.get("scene_order", data.get("scenes", [])):
        scene_name = scene.get("name", "") if isinstance(scene, dict) else scene
        # Find full scene definition
        for src in data.get("sources", []):
            if src.get("name") == scene_name:
                for item in src.get("settings", {}).get("items", []):
                    item_name = item.get("name", "")
                    if item_name and item_name not in seen:
                        seen.add(item_name)
                        results.append({
                            "name": item_name,
                            "type": "scene_item",
                            "visible": item.get("visible", True),
                        })

    return results


# ---------------------------------------------------------------------------
# WebSocket helpers (live)
# ---------------------------------------------------------------------------

def _get_ws_client():
    """Get an obsws-python client. Returns (client, error)."""
    try:
        import obsws_python as obs
    except ImportError:
        return None, "obsws-python not installed. Run: pip install obsws-python"

    try:
        cl = obs.ReqClient(
            host=OBS_WS_HOST,
            port=OBS_WS_PORT,
            password=OBS_WS_PASSWORD,
            timeout=5,
        )
        return cl, None
    except Exception as e:
        return None, f"Cannot connect to OBS WebSocket at {OBS_WS_HOST}:{OBS_WS_PORT}: {e}"


# ---------------------------------------------------------------------------
# OBSVerifier class
# ---------------------------------------------------------------------------

class OBSVerifier:
    """Stateless verifier — each method call is independent."""

    # === File-based: Offline state ===

    def get_scenes(self, collection_file: str | None = None) -> list[dict]:
        """List all scenes in a scene collection.

        Example return:
        [
            {"name": "Scene 1", "source_count": 3},
            {"name": "Webcam Only", "source_count": 1}
        ]
        """
        data, err = _load_scene_collection(collection_file)
        if err:
            return [{"error": err}]

        scenes = []

        # scene_order gives the ordered list of scene names
        scene_order = data.get("scene_order", [])
        source_defs = {s.get("name"): s for s in data.get("sources", [])}

        if scene_order:
            for entry in scene_order:
                name = entry.get("name", "") if isinstance(entry, dict) else str(entry)
                src_def = source_defs.get(name, {})
                items = src_def.get("settings", {}).get("items", [])
                scenes.append({
                    "name": name,
                    "source_count": len(items),
                })
        else:
            # Fallback: treat every source of type "scene" as a scene
            for src in data.get("sources", []):
                vid = src.get("versioned_id", src.get("id", ""))
                if "scene" in vid.lower():
                    items = src.get("settings", {}).get("items", [])
                    scenes.append({
                        "name": src.get("name", ""),
                        "source_count": len(items),
                    })

        return scenes

    def get_scene_sources(self, scene_name: str, collection_file: str | None = None) -> list[dict]:
        """List sources in a specific scene.

        Example return:
        [
            {"name": "Webcam", "visible": true, "locked": false},
            {"name": "Desktop Capture", "visible": true, "locked": false}
        ]
        """
        data, err = _load_scene_collection(collection_file)
        if err:
            return [{"error": err}]

        for src in data.get("sources", []):
            if src.get("name") == scene_name:
                return _extract_sources_from_scene(src)

        return [{"error": f"Scene '{scene_name}' not found in collection"}]

    def get_sources(self, collection_file: str | None = None) -> list[dict]:
        """List all sources across all scenes.

        Example return:
        [
            {"name": "Webcam", "type": "v4l2_input", "enabled": true},
            {"name": "Desktop", "type": "xshm_input", "enabled": true}
        ]
        """
        data, err = _load_scene_collection(collection_file)
        if err:
            return [{"error": err}]
        return _all_sources_from_collection(data)

    def get_source_info(self, source_name: str, collection_file: str | None = None) -> dict:
        """Get detailed properties for a specific source.

        Example return:
        {"name": "Webcam", "type": "v4l2_input", "settings": {...}, "enabled": true}
        """
        data, err = _load_scene_collection(collection_file)
        if err:
            return {"error": err}

        for src in data.get("sources", []):
            if src.get("name") == source_name:
                return {
                    "name": src.get("name", ""),
                    "type": src.get("versioned_id", src.get("id", "")),
                    "settings": src.get("settings", {}),
                    "enabled": src.get("enabled", True),
                    "muted": src.get("mute", src.get("muted", False)),
                    "volume": src.get("volume", src.get("db", None)),
                    "push_to_talk": src.get("push-to-talk", False),
                    "filters": src.get("filters", []),
                    "mixers": src.get("mixers", None),
                    "monitoring_type": src.get("monitoring_type", 0),
                    "sync": src.get("sync", 0),
                    "balance": src.get("balance", 0.5),
                    "flags": src.get("flags", 0),
                }

        return {"error": f"Source '{source_name}' not found"}

    def get_profiles(self) -> list[dict]:
        """List available OBS profiles.

        Example return:
        [
            {"name": "Default", "has_config": true},
            {"name": "Streaming", "has_config": true}
        ]
        """
        if not PROFILES_DIR.exists():
            return [{"error": f"Profiles directory not found: {PROFILES_DIR}"}]

        profiles = []
        for d in sorted(PROFILES_DIR.iterdir()):
            if d.is_dir():
                profiles.append({
                    "name": d.name,
                    "has_config": (d / "basic.ini").exists(),
                })
        return profiles

    def get_scene_collections(self) -> list[dict]:
        """List available scene collection files.

        Example return:
        [
            {"name": "Untitled", "file": "Untitled.json", "path": "/home/user/.config/..."}
        ]
        """
        if not SCENES_DIR.exists():
            return [{"error": f"Scenes directory not found: {SCENES_DIR}"}]

        collections = []
        for f in sorted(SCENES_DIR.glob("*.json")):
            collections.append({
                "name": f.stem,
                "file": f.name,
                "path": str(f),
            })
        return collections

    def get_recording_settings(self, profile_name: str | None = None) -> dict:
        """Read recording settings from a profile's basic.ini.

        Example return:
        {"RecFilePath": "/home/user/Videos", "RecFormat": "mkv", ...}
        """
        config, err = _load_profile(profile_name)
        if err:
            return {"error": err}

        settings = {}

        # SimpleOutput section
        if config.has_section("SimpleOutput"):
            for key in config.options("SimpleOutput"):
                settings[key] = config.get("SimpleOutput", key)

        # AdvOut section (advanced output mode)
        if config.has_section("AdvOut"):
            for key in config.options("AdvOut"):
                settings[f"adv_{key}"] = config.get("AdvOut", key)

        # Output section
        if config.has_section("Output"):
            for key in config.options("Output"):
                settings[f"output_{key}"] = config.get("Output", key)

        # Video section
        if config.has_section("Video"):
            for key in config.options("Video"):
                settings[f"video_{key}"] = config.get("Video", key)

        if not settings:
            return {"error": "No recording-related settings found in profile"}

        return settings

    # === Filters, transitions, hotkeys, streaming, global config ===

    def get_source_filters(self, source_name: str, collection_file: str | None = None) -> list[dict]:
        """List all filters attached to a source.

        Returns a list of {"name", "type", "settings", "enabled"} dicts.
        """
        data, err = _load_scene_collection(collection_file)
        if err:
            return [{"error": err}]

        for src in data.get("sources", []):
            if src.get("name") == source_name:
                out = []
                for f in src.get("filters", []) or []:
                    out.append({
                        "name": f.get("name", ""),
                        "type": f.get("versioned_id", f.get("id", "")),
                        "settings": f.get("settings", {}),
                        "enabled": f.get("enabled", True),
                    })
                return out

        return [{"error": f"Source '{source_name}' not found"}]

    def get_source_filter_info(self, source_name: str, filter_name: str, collection_file: str | None = None) -> dict:
        """Get detailed info for a specific filter on a source."""
        filters = self.get_source_filters(source_name, collection_file)
        if filters and "error" in filters[0]:
            return filters[0]
        for f in filters:
            if f.get("name") == filter_name:
                return f
        return {"error": f"Filter '{filter_name}' not found on source '{source_name}'",
                "available_filters": [f.get("name") for f in filters]}

    def check_source_has_filter(self, source_name: str, filter_name_or_type: str, collection_file: str | None = None) -> dict:
        """Check if a source has a filter with the given name OR matching type substring."""
        filters = self.get_source_filters(source_name, collection_file)
        if filters and "error" in filters[0]:
            return {"exists": False, "error": filters[0]["error"]}

        for f in filters:
            if f.get("name") == filter_name_or_type or filter_name_or_type in (f.get("type") or ""):
                return {
                    "exists": True,
                    "filter_name": f.get("name", ""),
                    "filter_type": f.get("type", ""),
                    "settings": f.get("settings", {}),
                }
        return {
            "exists": False,
            "filter_name": filter_name_or_type,
            "available_filters": [f.get("name") for f in filters],
        }

    def get_transitions(self, collection_file: str | None = None) -> list[dict]:
        """List transitions defined in a scene collection.

        OBS stores transitions at the top level under 'transitions'.
        """
        data, err = _load_scene_collection(collection_file)
        if err:
            return [{"error": err}]

        out = []
        for t in data.get("transitions", []) or []:
            out.append({
                "name": t.get("name", ""),
                "type": t.get("id", t.get("versioned_id", "")),
                "settings": t.get("settings", {}),
            })
        # Also expose collection-wide transition settings
        return out

    def check_transition_exists(self, name: str, collection_file: str | None = None) -> dict:
        """Check if a named transition exists."""
        ts = self.get_transitions(collection_file)
        if ts and "error" in ts[0]:
            return {"exists": False, "error": ts[0]["error"]}
        for t in ts:
            if t.get("name") == name:
                return {"exists": True, "name": name, "type": t.get("type", ""), "settings": t.get("settings", {})}
        return {"exists": False, "name": name, "available": [t.get("name") for t in ts]}

    def get_collection_meta(self, collection_file: str | None = None) -> dict:
        """Return top-level collection metadata useful for verifying global settings:
        current_scene, current_transition, transition_duration, current_program_scene,
        current_preview_scene, preview_locked, studio_mode, virtual_cam, replay_buffer."""
        data, err = _load_scene_collection(collection_file)
        if err:
            return {"error": err}
        return {
            "name": data.get("name", ""),
            "current_scene": data.get("current_scene", ""),
            "current_program_scene": data.get("current_program_scene", ""),
            "preview_scene": data.get("preview_scene", data.get("current_preview_scene", "")),
            "current_transition": data.get("current_transition", ""),
            "transition_duration": data.get("transition_duration", 0),
            "preview_locked": data.get("preview_locked", False),
            "scaling_enabled": data.get("scaling_enabled", False),
            "virtual_cam": data.get("virtual-cam", data.get("virtual_cam", {})),
            "replay_buffer": data.get("replay_buffer", {}),
            "modules": data.get("modules", {}),
            "quick_transitions": data.get("quick_transitions", []),
        }

    def get_hotkey(self, action: str, collection_file: str | None = None) -> dict:
        """Read hotkey bindings for a given action key.

        Hotkeys in scene collections can live in several places:
          - top-level data['hotkeys'][action]
          - inside a source: source['hotkeys'][action]
        The 'action' key format depends on OBS (e.g. "OBSBasic.SelectScene"
        for scene switches, or source-specific keys like "libobs.mute").
        """
        data, err = _load_scene_collection(collection_file)
        if err:
            return {"error": err}

        # Top-level hotkeys
        top = data.get("hotkeys", {}) or {}
        if action in top:
            return {"found": True, "scope": "global", "action": action, "bindings": top[action]}

        # Per-source hotkeys
        for src in data.get("sources", []):
            hotkeys = src.get("hotkeys", {}) or {}
            if action in hotkeys:
                return {
                    "found": True,
                    "scope": "source",
                    "source": src.get("name", ""),
                    "action": action,
                    "bindings": hotkeys[action],
                }

        return {"found": False, "action": action}

    def get_source_hotkeys(self, source_name: str, collection_file: str | None = None) -> dict:
        """Return every hotkey dict attached to a particular source."""
        data, err = _load_scene_collection(collection_file)
        if err:
            return {"error": err}
        for src in data.get("sources", []):
            if src.get("name") == source_name:
                return {"source": source_name, "hotkeys": src.get("hotkeys", {}) or {}}
        return {"error": f"Source '{source_name}' not found"}

    def get_streaming_settings(self, profile_name: str | None = None) -> dict:
        """Read streaming-related settings.

        Combines:
          - basic.ini [AdvOut] keyframes / bitrate etc. (already in recording-settings but
            returned here narrowed to the streaming context)
          - service.json (sibling file in the profile directory) which holds service,
            server, bitrate, stream key.
        """
        if not PROFILES_DIR.exists():
            return {"error": f"Profiles directory not found: {PROFILES_DIR}"}

        if profile_name:
            pdir = PROFILES_DIR / profile_name
        else:
            pdirs = [d for d in sorted(PROFILES_DIR.iterdir()) if d.is_dir()]
            if not pdirs:
                return {"error": "No profiles found"}
            pdir = pdirs[0]

        result: dict[str, Any] = {"profile": pdir.name}

        service_path = pdir / "service.json"
        if service_path.exists():
            try:
                with open(service_path) as f:
                    svc = json.load(f)
                result["service_file"] = str(service_path)
                result["service_type"] = svc.get("type", "")
                settings = svc.get("settings", {}) or {}
                result["service"] = settings.get("service", "")
                result["server"] = settings.get("server", "")
                result["bwtest"] = settings.get("bwtest", False)
                result["stream_key_present"] = bool(settings.get("key", ""))
                result["settings"] = settings
            except Exception as e:
                result["service_error"] = str(e)
        else:
            result["service_error"] = "service.json not found"

        ini_path = pdir / "basic.ini"
        if ini_path.exists():
            cfg = configparser.ConfigParser()
            try:
                cfg.read(str(ini_path))
                for section in ("AdvOut", "SimpleOutput", "Output", "Video"):
                    if cfg.has_section(section):
                        result[f"ini_{section}"] = dict(cfg.items(section))
            except Exception as e:
                result["ini_error"] = str(e)

        return result

    def get_global_config(self, section: str | None = None, key: str | None = None) -> dict:
        """Read values from OBS global config (~/.config/obs-studio/global.ini
        or user.ini on newer versions).

        With no args, returns the merged {section: {key: value}} tree.
        With section, returns that section. With key, returns the single value.
        Useful for checking studio mode, virtual cam defaults, etc.
        """
        candidates = [
            OBS_CONFIG_DIR / "user.ini",
            OBS_CONFIG_DIR / "global.ini",
        ]
        ini_path = None
        for c in candidates:
            if c.exists():
                ini_path = c
                break
        if ini_path is None:
            return {"error": f"No global config found in {OBS_CONFIG_DIR}"}

        cfg = configparser.ConfigParser()
        try:
            cfg.read(str(ini_path))
        except Exception as e:
            return {"error": f"Cannot parse {ini_path}: {e}"}

        if section and key:
            if cfg.has_option(section, key):
                return {"section": section, "key": key, "value": cfg.get(section, key), "path": str(ini_path)}
            return {"section": section, "key": key, "value": None, "path": str(ini_path)}
        if section:
            if cfg.has_section(section):
                return {"section": section, "values": dict(cfg.items(section)), "path": str(ini_path)}
            return {"section": section, "values": {}, "path": str(ini_path)}
        return {
            "path": str(ini_path),
            "sections": {s: dict(cfg.items(s)) for s in cfg.sections()},
        }

    # === WebSocket: Live state ===

    def get_live_scenes(self) -> dict:
        """Get scenes from running OBS via WebSocket.

        Example return:
        {"current_scene": "Scene 1", "scenes": [{"name": "Scene 1"}, ...]}
        """
        cl, err = _get_ws_client()
        if err:
            return {"error": err}

        try:
            resp = cl.get_scene_list()
            scenes = [{"name": s.get("sceneName", "")} for s in getattr(resp, "scenes", [])]
            return {
                "current_scene": getattr(resp, "currentProgramSceneName", ""),
                "scenes": scenes,
            }
        except Exception as e:
            return {"error": f"WebSocket call failed: {e}"}

    def get_live_sources(self) -> dict:
        """Get input sources from running OBS via WebSocket.

        Example return:
        {"inputs": [{"name": "Webcam", "kind": "v4l2_input"}, ...]}
        """
        cl, err = _get_ws_client()
        if err:
            return {"error": err}

        try:
            resp = cl.get_input_list()
            inputs = []
            for inp in getattr(resp, "inputs", []):
                inputs.append({
                    "name": inp.get("inputName", ""),
                    "kind": inp.get("inputKind", ""),
                    "uuid": inp.get("unversionedInputKind", ""),
                })
            return {"inputs": inputs}
        except Exception as e:
            return {"error": f"WebSocket call failed: {e}"}

    def get_live_status(self) -> dict:
        """Get recording/streaming status from running OBS.

        Example return:
        {"recording": true, "streaming": false, "recording_time": "00:05:23"}
        """
        cl, err = _get_ws_client()
        if err:
            return {"error": err}

        result = {}
        try:
            rec = cl.get_record_status()
            result["recording"] = getattr(rec, "outputActive", False)
            result["recording_paused"] = getattr(rec, "outputPaused", False)
            result["recording_time"] = getattr(rec, "outputTimecode", "")
            result["recording_bytes"] = getattr(rec, "outputBytes", 0)
        except Exception as e:
            result["recording_error"] = str(e)

        try:
            stream = cl.get_stream_status()
            result["streaming"] = getattr(stream, "outputActive", False)
            result["streaming_time"] = getattr(stream, "outputTimecode", "")
            result["streaming_bytes"] = getattr(stream, "outputBytes", 0)
        except Exception as e:
            result["streaming_error"] = str(e)

        return result

    def get_live_current_scene(self) -> dict:
        """Get the currently active scene from running OBS.

        Example return:
        {"current_scene": "Scene 1"}
        """
        cl, err = _get_ws_client()
        if err:
            return {"error": err}

        try:
            resp = cl.get_current_program_scene()
            return {"current_scene": getattr(resp, "currentProgramSceneName", "")}
        except Exception as e:
            return {"error": f"WebSocket call failed: {e}"}

    # === Check endpoints (return primary boolean) ===

    def check_file_exists(self, path: str) -> dict:
        """Check if a file exists on disk.

        Example return:
        {"exists": true, "path": "/home/user/Videos/recording.mkv", "size": 12345}
        """
        p = Path(path)
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

    def check_scene_exists(self, scene_name: str, collection_file: str | None = None) -> dict:
        """Check if a scene exists in a collection.

        Example return:
        {"exists": true, "scene_name": "Scene 1", "source_count": 3}
        """
        scenes = self.get_scenes(collection_file)
        if scenes and "error" in scenes[0]:
            return scenes[0]

        for scene in scenes:
            if scene.get("name") == scene_name:
                return {"exists": True, "scene_name": scene_name, "source_count": scene.get("source_count", 0)}

        return {"exists": False, "scene_name": scene_name, "available_scenes": [s.get("name") for s in scenes]}

    def check_source_exists(self, source_name: str, collection_file: str | None = None) -> dict:
        """Check if a source exists anywhere in the collection.

        Example return:
        {"exists": true, "source_name": "Webcam", "type": "v4l2_input"}
        """
        sources = self.get_sources(collection_file)
        if sources and "error" in sources[0]:
            return sources[0]

        for src in sources:
            if src.get("name") == source_name:
                return {"exists": True, "source_name": source_name, "type": src.get("type", "")}

        return {"exists": False, "source_name": source_name}

    def check_source_in_scene(self, source_name: str, scene_name: str, collection_file: str | None = None) -> dict:
        """Check if a specific source is present in a specific scene.

        Example return:
        {"exists": true, "source_name": "Webcam", "scene_name": "Scene 1", "visible": true}
        """
        scene_sources = self.get_scene_sources(scene_name, collection_file)
        if scene_sources and "error" in scene_sources[0]:
            return scene_sources[0]

        for src in scene_sources:
            if src.get("name") == source_name:
                return {
                    "exists": True,
                    "source_name": source_name,
                    "scene_name": scene_name,
                    "visible": src.get("visible", True),
                }

        return {"exists": False, "source_name": source_name, "scene_name": scene_name}

    def check_scene_count(self, expected_count: int, collection_file: str | None = None) -> dict:
        """Check if the number of scenes matches expected count.

        Example return:
        {"match": true, "expected": 3, "actual": 3}
        """
        scenes = self.get_scenes(collection_file)
        if scenes and "error" in scenes[0]:
            return scenes[0]

        actual = len(scenes)
        return {
            "match": actual == expected_count,
            "expected": expected_count,
            "actual": actual,
        }

    def check_source_visible(self, source_name: str, collection_file: str | None = None) -> dict:
        """Check if a source is visible in any scene.

        Example return:
        {"visible": true, "source_name": "Webcam", "found_in_scenes": ["Scene 1"]}
        """
        data, err = _load_scene_collection(collection_file)
        if err:
            return {"error": err}

        found_scenes = []
        visible = False

        for src in data.get("sources", []):
            items = src.get("settings", {}).get("items", [])
            for item in items:
                if item.get("name") == source_name:
                    if item.get("visible", True):
                        visible = True
                        found_scenes.append(src.get("name", ""))
                    else:
                        found_scenes.append(src.get("name", "") + " (hidden)")

        if not found_scenes:
            return {"visible": False, "source_name": source_name, "error": "Source not found in any scene"}

        return {"visible": visible, "source_name": source_name, "found_in_scenes": found_scenes}

    def check_recording_active(self) -> dict:
        """Live check if OBS is currently recording (via WebSocket).

        Example return:
        {"recording": true, "recording_time": "00:05:23"}
        """
        cl, err = _get_ws_client()
        if err:
            return {"recording": False, "error": err}

        try:
            rec = cl.get_record_status()
            active = getattr(rec, "outputActive", False)
            return {
                "recording": active,
                "recording_time": getattr(rec, "outputTimecode", ""),
            }
        except Exception as e:
            return {"recording": False, "error": f"WebSocket call failed: {e}"}

    def check_streaming_active(self) -> dict:
        """Live check if OBS is currently streaming (via WebSocket).

        Example return:
        {"streaming": true, "streaming_time": "01:23:45"}
        """
        cl, err = _get_ws_client()
        if err:
            return {"streaming": False, "error": err}

        try:
            stream = cl.get_stream_status()
            active = getattr(stream, "outputActive", False)
            return {
                "streaming": active,
                "streaming_time": getattr(stream, "outputTimecode", ""),
            }
        except Exception as e:
            return {"streaming": False, "error": f"WebSocket call failed: {e}"}


# ---------------------------------------------------------------------------
# CLI interface — for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

COMMANDS = {
    # File-based (offline, no OBS needed)
    "scenes": ("List all scenes", lambda v, args: v.get_scenes(args[0] if args else None)),
    "scene-sources": ("List sources in a scene", lambda v, args: v.get_scene_sources(args[0], args[1] if len(args) > 1 else None)),
    "sources": ("List all sources", lambda v, args: v.get_sources(args[0] if args else None)),
    "source-info": ("Detailed source properties", lambda v, args: v.get_source_info(args[0], args[1] if len(args) > 1 else None)),
    "profiles": ("List available profiles", lambda v, args: v.get_profiles()),
    "scene-collections": ("List scene collection files", lambda v, args: v.get_scene_collections()),
    "recording-settings": ("Read recording settings", lambda v, args: v.get_recording_settings(args[0] if args else None)),
    "streaming-settings": ("Read streaming settings (service.json + ini)", lambda v, args: v.get_streaming_settings(args[0] if args else None)),
    "global-config": ("Read ~/.config/obs-studio global.ini/user.ini (optional section, key)", lambda v, args: v.get_global_config(args[0] if args else None, args[1] if len(args) > 1 else None)),
    "source-filters": ("List filters on a source", lambda v, args: v.get_source_filters(args[0], args[1] if len(args) > 1 else None)),
    "source-filter-info": ("Get specific filter settings", lambda v, args: v.get_source_filter_info(args[0], args[1], args[2] if len(args) > 2 else None)),
    "transitions": ("List transitions in the collection", lambda v, args: v.get_transitions(args[0] if args else None)),
    "collection-meta": ("Top-level collection metadata (studio mode, transitions, virtual cam)", lambda v, args: v.get_collection_meta(args[0] if args else None)),
    "hotkey": ("Read hotkey bindings for an action", lambda v, args: v.get_hotkey(args[0], args[1] if len(args) > 1 else None)),
    "source-hotkeys": ("Read all hotkeys attached to a source", lambda v, args: v.get_source_hotkeys(args[0], args[1] if len(args) > 1 else None)),

    # WebSocket (live, needs OBS running)
    "live-scenes": ("Get scenes via WebSocket", lambda v, args: v.get_live_scenes()),
    "live-sources": ("Get sources via WebSocket", lambda v, args: v.get_live_sources()),
    "live-status": ("Recording/streaming status", lambda v, args: v.get_live_status()),
    "live-scene-current": ("Get current active scene", lambda v, args: v.get_live_current_scene()),

    # Checks
    "check-file-exists": ("Check file exists", lambda v, args: v.check_file_exists(args[0])),
    "check-scene-exists": ("Check scene exists", lambda v, args: v.check_scene_exists(args[0], args[1] if len(args) > 1 else None)),
    "check-source-exists": ("Check source exists", lambda v, args: v.check_source_exists(args[0], args[1] if len(args) > 1 else None)),
    "check-source-in-scene": ("Check source is in scene", lambda v, args: v.check_source_in_scene(args[0], args[1], args[2] if len(args) > 2 else None)),
    "check-scene-count": ("Check number of scenes", lambda v, args: v.check_scene_count(int(args[0]), args[1] if len(args) > 1 else None)),
    "check-source-visible": ("Check source is visible", lambda v, args: v.check_source_visible(args[0], args[1] if len(args) > 1 else None)),
    "check-source-has-filter": ("Check source has a filter (by name or type substring)", lambda v, args: v.check_source_has_filter(args[0], args[1], args[2] if len(args) > 2 else None)),
    "check-transition-exists": ("Check a transition exists", lambda v, args: v.check_transition_exists(args[0], args[1] if len(args) > 1 else None)),
    "check-recording-active": ("Live check if recording", lambda v, args: v.check_recording_active()),
    "check-streaming-active": ("Live check if streaming", lambda v, args: v.check_streaming_active()),
}


def _print_usage():
    print("OBS Studio Verifier — query OBS state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nFile-based commands read from {SCENES_DIR}")
    print(f"Live commands connect to obs-websocket at {OBS_WS_HOST}:{OBS_WS_PORT}")
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

    v = OBSVerifier()
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
