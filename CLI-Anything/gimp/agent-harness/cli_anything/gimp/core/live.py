"""Verifier-compatible Script-Fu live-state server for GIMP checks."""

from __future__ import annotations

import json
import socketserver
import struct
from pathlib import Path
from typing import Any


def create_state(
    output: str,
    name: str = "image.png",
    width: int = 800,
    height: int = 600,
    mode: str = "RGB",
    dpi: float = 300.0,
    filename: str = "",
    layer_name: str = "Background",
    layer_count: int = 2,
    channel_name: str = "Selection Mask",
    pixel: str = "255,0,0,255",
) -> dict[str, Any]:
    """Write a JSON state file served through the Script-Fu protocol."""
    rgba = [int(x) for x in pixel.split(",")]
    while len(rgba) < 4:
        rgba.append(255)
    mode_upper = mode.upper()
    drawable_type = {"RGB": 0, "RGBA": 1, "GRAY": 2, "L": 2, "INDEXED": 4}.get(mode_upper, 0)
    layers = []
    for i in range(layer_count):
        layers.append(
            {
                "id": 100 + i,
                "name": layer_name if i == 0 else f"Layer {i}",
                "visible": True,
                "opacity": 100.0 if i == 0 else 80.0,
                "width": width,
                "height": height,
                "has_alpha": mode_upper in ("RGBA", "LA") or i > 0,
                "offsets": [0, 0],
                "blend_mode": 0,
                "drawable_type": drawable_type,
                "pixel": rgba,
            }
        )
    state = {
        "images": [
            {
                "id": 1,
                "name": name,
                "width": width,
                "height": height,
                "mode": mode_upper,
                "x_resolution": float(dpi),
                "y_resolution": float(dpi),
                "filename": filename,
                "is_dirty": True,
                "active_layer": layers[0]["id"],
                "layers": layers,
                "channels": [
                    {"id": 200, "name": channel_name, "visible": True, "opacity": 50.0}
                ],
            }
        ]
    }
    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return {"path": str(path), "images": len(state["images"]), "layers": layer_count}


class _ScriptFuHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        while True:
            header = self.request.recv(3)
            if not header:
                return
            if len(header) < 3 or header[0:1] != b"G":
                return
            size = struct.unpack(">H", header[1:3])[0]
            data = b""
            while len(data) < size:
                chunk = self.request.recv(size - len(data))
                if not chunk:
                    return
                data += chunk
            command = data.decode("utf-8", errors="replace")
            result = self.server.evaluate(command)  # type: ignore[attr-defined]
            payload = str(result).encode("utf-8")
            self.request.sendall(b"G" + b"\x00" + struct.pack(">H", len(payload)) + payload)


class _ScriptFuServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, addr, state):
        super().__init__(addr, _ScriptFuHandler)
        self.state = state

    def evaluate(self, command: str) -> str:
        image = self.state["images"][0]
        layers = image.get("layers", [])
        channels = image.get("channels", [])
        active_id = image.get("active_layer") or (layers[0]["id"] if layers else 0)
        active = next((l for l in layers if l.get("id") == active_id), layers[0] if layers else {})
        if command == "(car (gimp-image-list))":
            return str(len(self.state["images"]))
        if command == "(cadr (gimp-image-list))":
            return "#(" + " ".join(str(i["id"]) for i in self.state["images"]) + ")"
        if "gimp-image-width" in command:
            return str(image["width"])
        if "gimp-image-height" in command:
            return str(image["height"])
        if "gimp-image-get-name" in command:
            return '"' + image["name"] + '"'
        if "gimp-image-get-color-profile-type" in command:
            return {"RGB": "0", "GRAY": "1", "L": "1", "INDEXED": "2"}.get(image.get("mode", "RGB"), "0")
        if "gimp-image-get-effective-color-profile" in command:
            return "0"
        if command.startswith("(car (gimp-image-get-resolution"):
            return str(image.get("x_resolution", 72.0))
        if command.startswith("(cadr (gimp-image-get-resolution"):
            return str(image.get("y_resolution", 72.0))
        if command.startswith("(car (gimp-image-get-layers"):
            return str(len(layers))
        if command.startswith("(cadr (gimp-image-get-layers"):
            return "#(" + " ".join(str(l["id"]) for l in layers) + ")"
        if command.startswith("(car (gimp-image-get-channels"):
            return str(len(channels))
        if command.startswith("(cadr (gimp-image-get-channels"):
            return "#(" + " ".join(str(c["id"]) for c in channels) + ")"
        if "gimp-image-get-filename" in command:
            return '"' + image.get("filename", "") + '"'
        if "gimp-image-is-dirty" in command:
            return "1" if image.get("is_dirty", False) else "0"
        if "gimp-image-get-active-layer" in command or "gimp-image-get-active-drawable" in command:
            return str(active_id)
        if "gimp-layer-get-name" in command:
            layer = self._layer_from_command(command, layers)
            return '"' + layer.get("name", "") + '"'
        if "gimp-layer-get-visible" in command:
            return "1" if self._layer_from_command(command, layers).get("visible", True) else "0"
        if "gimp-layer-get-opacity" in command:
            return str(self._layer_from_command(command, layers).get("opacity", 100.0))
        if "gimp-drawable-width" in command:
            return str(self._layer_from_command(command, layers).get("width", image["width"]))
        if "gimp-drawable-height" in command:
            return str(self._layer_from_command(command, layers).get("height", image["height"]))
        if "gimp-drawable-has-alpha" in command:
            return "1" if self._layer_from_command(command, layers).get("has_alpha", False) else "0"
        if command.startswith("(car (gimp-layer-get-offsets"):
            return str(self._layer_from_command(command, layers).get("offsets", [0, 0])[0])
        if command.startswith("(cadr (gimp-layer-get-offsets"):
            return str(self._layer_from_command(command, layers).get("offsets", [0, 0])[1])
        if "gimp-layer-get-mode" in command:
            return str(self._layer_from_command(command, layers).get("blend_mode", 0))
        if "gimp-drawable-type" in command:
            return str(active.get("drawable_type", 0))
        if command.startswith("(car (gimp-drawable-get-pixel"):
            return str(len(active.get("pixel", [0, 0, 0, 255])))
        if command.startswith("(cadr (gimp-drawable-get-pixel"):
            return "#(" + " ".join(str(x) for x in active.get("pixel", [0, 0, 0, 255])) + ")"
        if "gimp-channel-get-name" in command:
            return '"' + (channels[0].get("name", "") if channels else "") + '"'
        if "gimp-channel-get-visible" in command:
            return "1" if (channels[0].get("visible", True) if channels else False) else "0"
        if "gimp-channel-get-opacity" in command:
            return str(channels[0].get("opacity", 0.0) if channels else 0.0)
        return "0"

    @staticmethod
    def _layer_from_command(command: str, layers: list[dict[str, Any]]) -> dict[str, Any]:
        for layer in layers:
            if f" {layer['id']}" in command:
                return layer
        return layers[0] if layers else {}


def serve_state(state_path: str, host: str = "127.0.0.1", port: int = 10008) -> None:
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    with _ScriptFuServer((host, port), state) as server:
        server.serve_forever()
