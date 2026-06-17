"""OBS websocket helpers for live OBS Studio sessions."""

from __future__ import annotations

import os
from typing import Any


def _client(host: str = "127.0.0.1", port: int = 4455, password: str | None = None, timeout: int = 5):
    try:
        import obsws_python as obs
    except ImportError as exc:
        raise RuntimeError("obsws-python not installed. Run: pip install obsws-python") from exc

    return obs.ReqClient(
        host=host,
        port=port,
        password=password if password is not None else os.environ.get("OBS_WS_PASSWORD", ""),
        timeout=timeout,
    )


def scenes(host: str = "127.0.0.1", port: int = 4455, password: str | None = None) -> dict[str, Any]:
    cl = _client(host, port, password)
    resp = cl.get_scene_list()
    return {
        "current_scene": getattr(resp, "currentProgramSceneName", ""),
        "scenes": getattr(resp, "scenes", []),
    }


def sources(host: str = "127.0.0.1", port: int = 4455, password: str | None = None) -> dict[str, Any]:
    cl = _client(host, port, password)
    resp = cl.get_input_list()
    return {"inputs": getattr(resp, "inputs", [])}


def status(host: str = "127.0.0.1", port: int = 4455, password: str | None = None) -> dict[str, Any]:
    cl = _client(host, port, password)
    result: dict[str, Any] = {}
    rec = cl.get_record_status()
    result["recording"] = getattr(rec, "outputActive", False)
    result["recording_paused"] = getattr(rec, "outputPaused", False)
    result["recording_time"] = getattr(rec, "outputTimecode", "")
    stream = cl.get_stream_status()
    result["streaming"] = getattr(stream, "outputActive", False)
    result["streaming_time"] = getattr(stream, "outputTimecode", "")
    return result


def current_scene(host: str = "127.0.0.1", port: int = 4455, password: str | None = None) -> dict[str, Any]:
    cl = _client(host, port, password)
    resp = cl.get_current_program_scene()
    return {"current_scene": getattr(resp, "currentProgramSceneName", "")}


def set_current_scene(scene_name: str, host: str = "127.0.0.1", port: int = 4455, password: str | None = None) -> dict[str, Any]:
    cl = _client(host, port, password)
    cl.set_current_program_scene(scene_name)
    return {"current_scene": scene_name}


def start_recording(host: str = "127.0.0.1", port: int = 4455, password: str | None = None) -> dict[str, Any]:
    cl = _client(host, port, password)
    cl.start_record()
    return {"recording": True}


def stop_recording(host: str = "127.0.0.1", port: int = 4455, password: str | None = None) -> dict[str, Any]:
    cl = _client(host, port, password)
    cl.stop_record()
    return {"recording": False}


def start_streaming(host: str = "127.0.0.1", port: int = 4455, password: str | None = None) -> dict[str, Any]:
    cl = _client(host, port, password)
    cl.start_stream()
    return {"streaming": True}


def stop_streaming(host: str = "127.0.0.1", port: int = 4455, password: str | None = None) -> dict[str, Any]:
    cl = _client(host, port, password)
    cl.stop_stream()
    return {"streaming": False}

