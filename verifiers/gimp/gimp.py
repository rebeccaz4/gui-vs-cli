"""
GIMP Verifier — programmatic state inspection for GIMP in E2B sandbox.

Verification channels (in order of preference):
  1. Script-Fu TCP server — live image state, layers, channels, pixel colors, DPI
  2. PIL (Pillow) — exported file inspection (dimensions, format, mode, pixel colors)
  3. File-based config — gimprc preferences, session settings

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/gimp.py images")
    sandbox.commands.run("python3 /home/user/verifiers/gimp.py layers 0")
    sandbox.commands.run("python3 /home/user/verifiers/gimp.py check-file-exists /home/user/output.png")

Usage from Python (inside sandbox or via E2B):
    from verifiers.gimp import GimpVerifier
    v = GimpVerifier()
    imgs = v.get_images()
    info = v.get_file_info("/home/user/export.png")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - GIMP launched with Script-Fu server:
      gimp -b '(plug-in-script-fu-server RUN-NONINTERACTIVE "127.0.0.1" 10008 "")' &
    OR for GIMP 3.0+:
      gimp -b '(script-fu-server 1 10008 "")' &
  - Pillow (PIL) for exported image inspection
  - socket, struct, os (standard library)
"""

import json
import os
import re
import socket
import struct
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SF_HOST = "127.0.0.1"
SF_PORT = 10008
SF_TIMEOUT = 10.0

# GIMP config paths (in order of likelihood)
GIMP_CONFIG_DIRS = [
    Path.home() / ".config" / "GIMP" / "2.10",
    Path.home() / ".config" / "GIMP" / "3.0",
    Path.home() / ".config" / "GIMP" / "2.99",
    Path.home() / ".gimp-2.10",
]

# GIMP image mode constants
IMAGE_MODES = {0: "RGB", 1: "GRAY", 2: "INDEXED"}
IMAGE_MODES_REV = {"RGB": 0, "GRAY": 1, "INDEXED": 2}


def _find_config_dir() -> Path | None:
    env_dir = os.environ.get("GIMP_CONFIG_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.exists():
            return p
    for d in GIMP_CONFIG_DIRS:
        if d.exists():
            return d
    return None


# ---------------------------------------------------------------------------
# Script-Fu TCP helpers
# ---------------------------------------------------------------------------

def _sf_connect(host: str = SF_HOST, port: int = SF_PORT, timeout: float = SF_TIMEOUT) -> socket.socket:
    """Create a TCP connection to the Script-Fu server."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((host, port))
    return sock


def _sf_send_recv(sock: socket.socket, command: str) -> str:
    """Send a Script-Fu command and receive the result via an open socket."""
    cmd_bytes = command.encode("utf-8")
    header = b"G" + struct.pack(">H", len(cmd_bytes))
    sock.sendall(header + cmd_bytes)

    # Response: 'G' (1) + error_code (1) + length (2) + result
    resp_header = b""
    while len(resp_header) < 4:
        chunk = sock.recv(4 - len(resp_header))
        if not chunk:
            raise ConnectionError("Script-Fu server closed connection")
        resp_header += chunk

    error_code = resp_header[1]
    result_len = struct.unpack(">H", resp_header[2:4])[0]

    result = b""
    while len(result) < result_len:
        chunk = sock.recv(result_len - len(result))
        if not chunk:
            break
        result += chunk

    result_str = result.decode("utf-8", errors="replace")

    if error_code != 0:
        raise RuntimeError(f"Script-Fu error: {result_str}")

    return result_str


def _sf_eval(command: str) -> str:
    """Connect, send one Script-Fu command, return result string."""
    try:
        sock = _sf_connect()
        try:
            return _sf_send_recv(sock, command)
        finally:
            sock.close()
    except (ConnectionRefusedError, OSError) as e:
        raise ConnectionError(
            f"Cannot connect to Script-Fu server at {SF_HOST}:{SF_PORT}. "
            f"Start GIMP with: gimp -b '(plug-in-script-fu-server RUN-NONINTERACTIVE \"127.0.0.1\" {SF_PORT} \"\")' &"
        ) from e


def _sf_eval_multi(commands: list[str]) -> list[str]:
    """Send multiple Script-Fu commands over a single TCP connection."""
    try:
        sock = _sf_connect()
        try:
            results = []
            for cmd in commands:
                results.append(_sf_send_recv(sock, cmd))
            return results
        finally:
            sock.close()
    except (ConnectionRefusedError, OSError) as e:
        raise ConnectionError(
            f"Cannot connect to Script-Fu server at {SF_HOST}:{SF_PORT}."
        ) from e


def _sf_int(command: str) -> int:
    return int(_sf_eval(command).strip())


def _sf_float(command: str) -> float:
    return float(_sf_eval(command).strip())


def _sf_str(command: str) -> str:
    s = _sf_eval(command).strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


def _sf_bool(command: str) -> bool:
    result = _sf_eval(command).strip()
    return result not in ("0", "#f", "FALSE")


def _sf_vector_ints(command: str) -> list[int]:
    """Parse a Script-Fu vector response like '#(1 2 3)' to list of ints."""
    result = _sf_eval(command).strip()
    if result.startswith("#(") and result.endswith(")"):
        inner = result[2:-1].strip()
        if not inner:
            return []
        return [int(x) for x in inner.split()]
    # Single value
    if result.isdigit() or (result.startswith("-") and result[1:].isdigit()):
        return [int(result)]
    return []


# ---------------------------------------------------------------------------
# gimprc parser
# ---------------------------------------------------------------------------

def _parse_gimprc(path: Path) -> dict[str, Any]:
    """Parse gimprc S-expression config into a flat dict."""
    if not path.exists():
        return {}

    text = path.read_text(errors="replace")
    result = {}
    # Match top-level (key value) pairs
    # Simple values: (key value) or (key "value")
    for match in re.finditer(r'\((\S+)\s+([^()]+)\)', text):
        key = match.group(1)
        val = match.group(2).strip().strip('"')
        result[key] = val

    return result


# ---------------------------------------------------------------------------
# GimpVerifier class
# ---------------------------------------------------------------------------

class GimpVerifier:
    """Stateless verifier — each method call is independent."""

    # ===================================================================
    # Script-Fu live state endpoints
    # ===================================================================

    def get_images(self) -> list[dict]:
        """List all open images with basic info.

        Example return:
        [
            {"id": 1, "name": "photo.png", "width": 800, "height": 600, "mode": "RGB"},
            {"id": 2, "name": "logo.xcf", "width": 256, "height": 256, "mode": "RGBA"}
        ]
        """
        try:
            num = _sf_int("(car (gimp-image-list))")
        except ConnectionError as e:
            return [{"error": str(e)}]
        except RuntimeError:
            return []

        if num == 0:
            return []

        try:
            ids = _sf_vector_ints("(cadr (gimp-image-list))")
        except Exception:
            return [{"error": "Failed to get image IDs"}]

        images = []
        for img_id in ids:
            try:
                cmds = [
                    f"(car (gimp-image-width {img_id}))",
                    f"(car (gimp-image-height {img_id}))",
                    f"(car (gimp-image-get-name {img_id}))",
                    f"(car (gimp-image-get-color-profile-type {img_id}))",
                ]
                results = _sf_eval_multi(cmds)
                w = int(results[0].strip())
                h = int(results[1].strip())
                name = results[2].strip().strip('"')
                # Get the actual image mode (RGB/GRAY/INDEXED), not color profile type
                mode_val = _sf_int(f"(car (gimp-image-get-effective-color-profile {img_id}))")
            except Exception:
                # Fallback: try to get mode from simpler call
                mode_val = -1

            # Get actual image mode
            try:
                mode_int = _sf_int(f"(car (gimp-image-get-color-profile-type {img_id}))")
            except Exception:
                mode_int = -1

            # Use gimp-image-get-active-drawable to check alpha
            has_alpha = False
            try:
                active = _sf_int(f"(car (gimp-image-get-active-layer {img_id}))")
                if active > 0:
                    has_alpha = _sf_bool(f"(car (gimp-drawable-has-alpha {active}))")
            except Exception:
                pass

            images.append({
                "id": img_id,
                "name": name,
                "width": w,
                "height": h,
                "mode": IMAGE_MODES.get(mode_int, f"UNKNOWN({mode_int})"),
                "has_alpha": has_alpha,
            })

        return images

    def get_image_info(self, image_index: int = 0) -> dict:
        """Get detailed info about an open image by index.

        Example return:
        {
            "id": 1, "name": "photo.png",
            "width": 800, "height": 600,
            "mode": "RGB", "has_alpha": false,
            "x_resolution": 300.0, "y_resolution": 300.0,
            "num_layers": 3, "num_channels": 0,
            "filename": "/home/user/photo.png",
            "is_dirty": true
        }
        """
        try:
            num = _sf_int("(car (gimp-image-list))")
            if num == 0:
                return {"error": "No images open in GIMP"}
            ids = _sf_vector_ints("(cadr (gimp-image-list))")
            if image_index >= len(ids):
                return {"error": f"Image index {image_index} out of range (have {len(ids)} images)"}
            img_id = ids[image_index]
        except ConnectionError as e:
            return {"error": str(e)}

        try:
            w = _sf_int(f"(car (gimp-image-width {img_id}))")
            h = _sf_int(f"(car (gimp-image-height {img_id}))")
            name = _sf_str(f"(car (gimp-image-get-name {img_id}))")

            # Resolution
            xres = _sf_float(f"(car (gimp-image-get-resolution {img_id}))")
            yres = _sf_float(f"(cadr (gimp-image-get-resolution {img_id}))")

            # Layer and channel counts
            num_layers = _sf_int(f"(car (gimp-image-get-layers {img_id}))")
            num_channels = _sf_int(f"(car (gimp-image-get-channels {img_id}))")

            # Filename
            try:
                filename = _sf_str(f"(car (gimp-image-get-filename {img_id}))")
            except Exception:
                filename = ""

            # Dirty flag
            try:
                is_dirty = _sf_bool(f"(car (gimp-image-is-dirty {img_id}))")
            except Exception:
                is_dirty = None

            # Alpha
            has_alpha = False
            try:
                active = _sf_int(f"(car (gimp-image-get-active-layer {img_id}))")
                if active > 0:
                    has_alpha = _sf_bool(f"(car (gimp-drawable-has-alpha {active}))")
            except Exception:
                pass

            return {
                "id": img_id,
                "name": name,
                "width": w,
                "height": h,
                "mode": IMAGE_MODES.get(0, "RGB"),  # will refine below
                "has_alpha": has_alpha,
                "x_resolution": xres,
                "y_resolution": yres,
                "num_layers": num_layers,
                "num_channels": num_channels,
                "filename": filename,
                "is_dirty": is_dirty,
            }
        except ConnectionError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Failed to get image info: {e}"}

    def get_layers(self, image_index: int = 0) -> list[dict]:
        """List all layers for an image with name, visibility, opacity, dimensions.

        Example return:
        [
            {"id": 5, "name": "Background", "visible": true, "opacity": 100.0,
             "width": 800, "height": 600, "has_alpha": false, "offsets": [0, 0]},
            {"id": 6, "name": "Layer 1", "visible": true, "opacity": 80.0,
             "width": 800, "height": 600, "has_alpha": true, "offsets": [10, 20]}
        ]
        """
        try:
            num_imgs = _sf_int("(car (gimp-image-list))")
            if num_imgs == 0:
                return [{"error": "No images open in GIMP"}]
            ids = _sf_vector_ints("(cadr (gimp-image-list))")
            if image_index >= len(ids):
                return [{"error": f"Image index {image_index} out of range"}]
            img_id = ids[image_index]
        except ConnectionError as e:
            return [{"error": str(e)}]

        try:
            num_layers = _sf_int(f"(car (gimp-image-get-layers {img_id}))")
            if num_layers == 0:
                return []
            layer_ids = _sf_vector_ints(f"(cadr (gimp-image-get-layers {img_id}))")
        except Exception as e:
            return [{"error": f"Failed to get layers: {e}"}]

        layers = []
        for lid in layer_ids:
            try:
                name = _sf_str(f"(car (gimp-layer-get-name {lid}))")
                visible = _sf_bool(f"(car (gimp-layer-get-visible {lid}))")
                opacity = _sf_float(f"(car (gimp-layer-get-opacity {lid}))")
                lw = _sf_int(f"(car (gimp-drawable-width {lid}))")
                lh = _sf_int(f"(car (gimp-drawable-height {lid}))")
                has_alpha = _sf_bool(f"(car (gimp-drawable-has-alpha {lid}))")
                ox = _sf_int(f"(car (gimp-layer-get-offsets {lid}))")
                oy = _sf_int(f"(cadr (gimp-layer-get-offsets {lid}))")
                mode = _sf_int(f"(car (gimp-layer-get-mode {lid}))")

                layers.append({
                    "id": lid,
                    "name": name,
                    "visible": visible,
                    "opacity": opacity,
                    "width": lw,
                    "height": lh,
                    "has_alpha": has_alpha,
                    "offsets": [ox, oy],
                    "blend_mode": mode,
                })
            except Exception as e:
                layers.append({"id": lid, "error": str(e)})

        return layers

    def get_channels(self, image_index: int = 0) -> list[dict]:
        """List all custom channels for an image.

        Example return:
        [
            {"id": 10, "name": "Selection Mask", "visible": true, "opacity": 50.0}
        ]
        """
        try:
            num_imgs = _sf_int("(car (gimp-image-list))")
            if num_imgs == 0:
                return [{"error": "No images open in GIMP"}]
            ids = _sf_vector_ints("(cadr (gimp-image-list))")
            if image_index >= len(ids):
                return [{"error": f"Image index {image_index} out of range"}]
            img_id = ids[image_index]
        except ConnectionError as e:
            return [{"error": str(e)}]

        try:
            num_ch = _sf_int(f"(car (gimp-image-get-channels {img_id}))")
            if num_ch == 0:
                return []
            ch_ids = _sf_vector_ints(f"(cadr (gimp-image-get-channels {img_id}))")
        except Exception as e:
            return [{"error": f"Failed to get channels: {e}"}]

        channels = []
        for cid in ch_ids:
            try:
                name = _sf_str(f"(car (gimp-channel-get-name {cid}))")
                visible = _sf_bool(f"(car (gimp-channel-get-visible {cid}))")
                opacity = _sf_float(f"(car (gimp-channel-get-opacity {cid}))")
                channels.append({
                    "id": cid,
                    "name": name,
                    "visible": visible,
                    "opacity": opacity,
                })
            except Exception as e:
                channels.append({"id": cid, "error": str(e)})

        return channels

    def get_active_layer(self, image_index: int = 0) -> dict:
        """Get info about the currently active layer.

        Example return:
        {"id": 5, "name": "Background", "width": 800, "height": 600, "opacity": 100.0}
        """
        try:
            num_imgs = _sf_int("(car (gimp-image-list))")
            if num_imgs == 0:
                return {"error": "No images open in GIMP"}
            ids = _sf_vector_ints("(cadr (gimp-image-list))")
            if image_index >= len(ids):
                return {"error": f"Image index {image_index} out of range"}
            img_id = ids[image_index]
            active = _sf_int(f"(car (gimp-image-get-active-layer {img_id}))")
            if active <= 0:
                return {"error": "No active layer"}

            name = _sf_str(f"(car (gimp-layer-get-name {active}))")
            w = _sf_int(f"(car (gimp-drawable-width {active}))")
            h = _sf_int(f"(car (gimp-drawable-height {active}))")
            opacity = _sf_float(f"(car (gimp-layer-get-opacity {active}))")
            visible = _sf_bool(f"(car (gimp-layer-get-visible {active}))")

            return {
                "id": active,
                "name": name,
                "width": w,
                "height": h,
                "opacity": opacity,
                "visible": visible,
            }
        except ConnectionError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Failed to get active layer: {e}"}

    def get_pixel_color(self, x: int, y: int, image_index: int = 0) -> dict:
        """Get pixel color at (x, y) from the active drawable in a live GIMP image.

        Example return:
        {"r": 255, "g": 128, "b": 0, "a": 255, "num_channels": 4}
        """
        try:
            num_imgs = _sf_int("(car (gimp-image-list))")
            if num_imgs == 0:
                return {"error": "No images open in GIMP"}
            ids = _sf_vector_ints("(cadr (gimp-image-list))")
            if image_index >= len(ids):
                return {"error": f"Image index {image_index} out of range"}
            img_id = ids[image_index]

            # Get active drawable
            active = _sf_int(f"(car (gimp-image-get-active-drawable {img_id}))")
            if active <= 0:
                return {"error": "No active drawable"}

            num_ch = _sf_int(f"(car (gimp-drawable-get-pixel {active} {x} {y}))")
            pixel = _sf_vector_ints(f"(cadr (gimp-drawable-get-pixel {active} {x} {y}))")

            result = {"num_channels": num_ch}
            if len(pixel) >= 1:
                result["r"] = pixel[0]
            if len(pixel) >= 2:
                result["g"] = pixel[1]
            if len(pixel) >= 3:
                result["b"] = pixel[2]
            if len(pixel) >= 4:
                result["a"] = pixel[3]
            return result
        except ConnectionError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Failed to get pixel: {e}"}

    # ===================================================================
    # File-based endpoints (PIL / filesystem)
    # ===================================================================

    def get_file_info(self, path: str) -> dict:
        """Get image file info using PIL: dimensions, format, mode, file size.

        Example return:
        {
            "path": "/home/user/output.png",
            "exists": true,
            "size_bytes": 54321,
            "width": 800, "height": 600,
            "format": "PNG", "mode": "RGBA"
        }
        """
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}", "exists": False}

        result = {
            "path": path,
            "exists": True,
            "size_bytes": os.path.getsize(path),
        }

        try:
            from PIL import Image
            with Image.open(path) as img:
                result["width"] = img.width
                result["height"] = img.height
                result["format"] = img.format
                result["mode"] = img.mode
        except ImportError:
            result["note"] = "Pillow not installed — cannot read image metadata"
        except Exception as e:
            result["error"] = f"Cannot read image: {e}"

        return result

    def get_pixel_color_file(self, path: str, x: int, y: int) -> dict:
        """Get pixel color at (x, y) from an image file on disk.

        Example return:
        {"r": 255, "g": 128, "b": 0, "a": 255, "mode": "RGBA"}
        """
        if not os.path.isfile(path):
            return {"error": f"File not found: {path}"}

        try:
            from PIL import Image
            with Image.open(path) as img:
                if x < 0 or x >= img.width or y < 0 or y >= img.height:
                    return {"error": f"Coordinates ({x}, {y}) out of bounds for {img.width}x{img.height} image"}
                pixel = img.getpixel((x, y))
                result = {"mode": img.mode}
                if img.mode == "L":
                    result["r"] = pixel
                    result["g"] = pixel
                    result["b"] = pixel
                elif img.mode == "LA":
                    result["r"] = pixel[0]
                    result["g"] = pixel[0]
                    result["b"] = pixel[0]
                    result["a"] = pixel[1]
                elif img.mode == "RGB":
                    result["r"] = pixel[0]
                    result["g"] = pixel[1]
                    result["b"] = pixel[2]
                elif img.mode in ("RGBA", "RGBa"):
                    result["r"] = pixel[0]
                    result["g"] = pixel[1]
                    result["b"] = pixel[2]
                    result["a"] = pixel[3]
                elif img.mode == "P":
                    # Palette mode — convert to RGB first
                    rgb_img = img.convert("RGB")
                    px = rgb_img.getpixel((x, y))
                    result["r"] = px[0]
                    result["g"] = px[1]
                    result["b"] = px[2]
                else:
                    result["raw"] = pixel if isinstance(pixel, tuple) else (pixel,)
                return result
        except ImportError:
            return {"error": "Pillow not installed"}
        except Exception as e:
            return {"error": f"Failed to read pixel: {e}"}

    def get_preferences(self, key: str | None = None) -> Any:
        """Read GIMP preferences from gimprc.

        Example:
            v.get_preferences("default-image")
            v.get_preferences()  # returns all top-level keys
        """
        config_dir = _find_config_dir()
        if not config_dir:
            return {"error": "GIMP config directory not found"}

        gimprc = config_dir / "gimprc"
        prefs = _parse_gimprc(gimprc)

        if key is None:
            return {"keys": list(prefs.keys()), "config_dir": str(config_dir)}

        if key in prefs:
            return {"key": key, "value": prefs[key]}

        return {"error": f"Key '{key}' not found in gimprc", "available_keys": list(prefs.keys())}

    # ===================================================================
    # Check endpoints — live (Script-Fu)
    # ===================================================================

    def check_image_open(self, filename: str) -> dict:
        """Check if an image matching the filename substring is open in GIMP.

        Example:
            v.check_image_open("photo.png")
            => {"found": true, "image": {"id": 1, "name": "photo.png", ...}}
        """
        images = self.get_images()
        if images and "error" in images[0]:
            return images[0]

        for img in images:
            if filename.lower() in img.get("name", "").lower():
                return {"found": True, "image": img}

        return {"found": False, "images_checked": len(images)}

    def check_layer_exists(self, layer_name: str, image_index: int = 0) -> dict:
        """Check if a layer with the given name exists.

        Example:
            v.check_layer_exists("Background")
            => {"exists": true, "layer": {"id": 5, "name": "Background", ...}}
        """
        layers = self.get_layers(image_index)
        if layers and "error" in layers[0]:
            return layers[0]

        for layer in layers:
            if layer.get("name") == layer_name:
                return {"exists": True, "layer": layer}

        return {
            "exists": False,
            "layer_name": layer_name,
            "available_layers": [l.get("name") for l in layers if "name" in l],
        }

    def check_layer_count(self, count: int, image_index: int = 0) -> dict:
        """Check if the image has the expected number of layers.

        Example:
            v.check_layer_count(3)
            => {"match": true, "expected": 3, "actual": 3}
        """
        layers = self.get_layers(image_index)
        if layers and "error" in layers[0]:
            return layers[0]

        actual = len(layers)
        return {"match": actual == count, "expected": count, "actual": actual}

    def check_image_mode(self, mode: str, image_index: int = 0) -> dict:
        """Check if the image color mode matches (RGB, GRAY, INDEXED).

        Example:
            v.check_image_mode("GRAY")
            => {"match": true, "expected": "GRAY", "actual": "GRAY"}
        """
        try:
            num_imgs = _sf_int("(car (gimp-image-list))")
            if num_imgs == 0:
                return {"error": "No images open in GIMP"}
            ids = _sf_vector_ints("(cadr (gimp-image-list))")
            if image_index >= len(ids):
                return {"error": f"Image index {image_index} out of range"}
            img_id = ids[image_index]

            # gimp-image-get-color-profile-type returns the mode
            # Actually, we need gimp-image-get-active-drawable and check type
            # Better: use a Script-Fu expression to get the mode directly
            # In GIMP 2.10: no direct "get-mode", but we can check drawable type
            # Actually, check via a workaround:
            # RGB images have 3-channel drawables, GRAY have 1-channel
            active = _sf_int(f"(car (gimp-image-get-active-drawable {img_id}))")
            if active <= 0:
                return {"error": "No active drawable"}

            dtype = _sf_int(f"(car (gimp-drawable-type {active}))")
            # GIMP drawable types:
            # RGB_IMAGE=0, RGBA_IMAGE=1, GRAY_IMAGE=2, GRAYA_IMAGE=3,
            # INDEXED_IMAGE=4, INDEXEDA_IMAGE=5
            type_to_mode = {
                0: "RGB", 1: "RGB",
                2: "GRAY", 3: "GRAY",
                4: "INDEXED", 5: "INDEXED",
            }
            actual_mode = type_to_mode.get(dtype, f"UNKNOWN({dtype})")

            return {
                "match": actual_mode.upper() == mode.upper(),
                "expected": mode.upper(),
                "actual": actual_mode,
            }
        except ConnectionError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Failed to check mode: {e}"}

    def check_has_alpha(self, image_index: int = 0) -> dict:
        """Check if the active layer of the image has an alpha channel.

        Example:
            v.check_has_alpha()
            => {"has_alpha": true}
        """
        try:
            num_imgs = _sf_int("(car (gimp-image-list))")
            if num_imgs == 0:
                return {"error": "No images open in GIMP"}
            ids = _sf_vector_ints("(cadr (gimp-image-list))")
            if image_index >= len(ids):
                return {"error": f"Image index {image_index} out of range"}
            img_id = ids[image_index]

            active = _sf_int(f"(car (gimp-image-get-active-layer {img_id}))")
            if active <= 0:
                return {"error": "No active layer"}

            has_alpha = _sf_bool(f"(car (gimp-drawable-has-alpha {active}))")
            return {"has_alpha": has_alpha}
        except ConnectionError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Failed to check alpha: {e}"}

    def check_resolution(self, xdpi: float, ydpi: float, image_index: int = 0) -> dict:
        """Check if the image resolution matches expected DPI values.

        Example:
            v.check_resolution(300, 300)
            => {"match": true, "expected": [300.0, 300.0], "actual": [300.0, 300.0]}
        """
        try:
            num_imgs = _sf_int("(car (gimp-image-list))")
            if num_imgs == 0:
                return {"error": "No images open in GIMP"}
            ids = _sf_vector_ints("(cadr (gimp-image-list))")
            if image_index >= len(ids):
                return {"error": f"Image index {image_index} out of range"}
            img_id = ids[image_index]

            actual_x = _sf_float(f"(car (gimp-image-get-resolution {img_id}))")
            actual_y = _sf_float(f"(cadr (gimp-image-get-resolution {img_id}))")

            # Allow small floating point tolerance
            match = abs(actual_x - xdpi) < 0.5 and abs(actual_y - ydpi) < 0.5

            return {
                "match": match,
                "expected": [float(xdpi), float(ydpi)],
                "actual": [actual_x, actual_y],
            }
        except ConnectionError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Failed to check resolution: {e}"}

    def check_image_size(self, width: int, height: int, image_index: int = 0) -> dict:
        """Check if the image dimensions match expected width and height.

        Example:
            v.check_image_size(1920, 1080)
            => {"match": true, "expected": [1920, 1080], "actual": [1920, 1080]}
        """
        try:
            num_imgs = _sf_int("(car (gimp-image-list))")
            if num_imgs == 0:
                return {"error": "No images open in GIMP"}
            ids = _sf_vector_ints("(cadr (gimp-image-list))")
            if image_index >= len(ids):
                return {"error": f"Image index {image_index} out of range"}
            img_id = ids[image_index]

            actual_w = _sf_int(f"(car (gimp-image-width {img_id}))")
            actual_h = _sf_int(f"(car (gimp-image-height {img_id}))")

            return {
                "match": actual_w == width and actual_h == height,
                "expected": [width, height],
                "actual": [actual_w, actual_h],
            }
        except ConnectionError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Failed to check size: {e}"}

    # ===================================================================
    # Check endpoints — file-based (PIL)
    # ===================================================================

    def check_file_exists(self, path: str) -> dict:
        """Check if a file exists at the given path.

        Example:
            v.check_file_exists("/home/user/output.png")
            => {"exists": true, "path": "/home/user/output.png", "size_bytes": 54321}
        """
        exists = os.path.isfile(path)
        result = {"exists": exists, "path": path}
        if exists:
            result["size_bytes"] = os.path.getsize(path)
        return result

    def check_file_dimensions(self, path: str, width: int, height: int) -> dict:
        """Check if an exported image file has the expected dimensions.

        Example:
            v.check_file_dimensions("/home/user/output.png", 800, 600)
            => {"match": true, "expected": [800, 600], "actual": [800, 600]}
        """
        info = self.get_file_info(path)
        if "error" in info and not info.get("exists", True):
            return info

        actual_w = info.get("width")
        actual_h = info.get("height")
        if actual_w is None or actual_h is None:
            return {"error": f"Cannot read dimensions from {path}"}

        return {
            "match": actual_w == width and actual_h == height,
            "expected": [width, height],
            "actual": [actual_w, actual_h],
        }

    def check_file_format(self, path: str, expected_format: str) -> dict:
        """Check if a file is in the expected format (PNG, JPEG, BMP, TIFF, GIF, WEBP).

        Example:
            v.check_file_format("/home/user/output.png", "PNG")
            => {"match": true, "expected": "PNG", "actual": "PNG"}
        """
        info = self.get_file_info(path)
        if "error" in info and not info.get("exists", True):
            return info

        actual_fmt = info.get("format", "")
        # Normalize common format names
        fmt_aliases = {"JPG": "JPEG", "TIF": "TIFF"}
        expected_norm = fmt_aliases.get(expected_format.upper(), expected_format.upper())
        actual_norm = fmt_aliases.get((actual_fmt or "").upper(), (actual_fmt or "").upper())

        return {
            "match": actual_norm == expected_norm,
            "expected": expected_norm,
            "actual": actual_norm,
        }

    def check_file_mode(self, path: str, expected_mode: str) -> dict:
        """Check if a file's color mode matches (RGB, RGBA, L, LA, P, etc.).

        Example:
            v.check_file_mode("/home/user/output.png", "RGBA")
            => {"match": true, "expected": "RGBA", "actual": "RGBA"}
        """
        info = self.get_file_info(path)
        if "error" in info and not info.get("exists", True):
            return info

        actual_mode = info.get("mode", "")
        return {
            "match": actual_mode == expected_mode,
            "expected": expected_mode,
            "actual": actual_mode,
        }

    def check_pixel_color_file(self, path: str, x: int, y: int,
                                r: int, g: int, b: int, tolerance: int = 5) -> dict:
        """Check if pixel at (x, y) in an image file matches the expected RGB color.

        Example:
            v.check_pixel_color_file("/home/user/output.png", 0, 0, 255, 0, 0)
            => {"match": true, "expected": [255, 0, 0], "actual": [255, 0, 0]}
        """
        pixel = self.get_pixel_color_file(path, x, y)
        if "error" in pixel:
            return pixel

        ar = pixel.get("r", 0)
        ag = pixel.get("g", 0)
        ab = pixel.get("b", 0)

        match = (abs(ar - r) <= tolerance and
                 abs(ag - g) <= tolerance and
                 abs(ab - b) <= tolerance)

        return {
            "match": match,
            "expected": [r, g, b],
            "actual": [ar, ag, ab],
            "tolerance": tolerance,
        }


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# python-reward: run an inline reward script (added for the task-replacement update;
# used by tasks ported from CUA-Gym, CC-BY-4.0). See update/README.md.
# ---------------------------------------------------------------------------

def python_reward(payload_b64, threshold="0.999"):
    import base64 as _b64
    import subprocess as _sp
    import tempfile as _tf
    import zlib as _zlib
    source = _zlib.decompress(_b64.b64decode(payload_b64)).decode("utf-8")
    with _tf.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(source)
        script = fh.name
    try:
        proc = _sp.run(["python3", script], capture_output=True, text=True, timeout=180)
        out = proc.stdout
    except _sp.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return {"passed": False, "score": 0.0, "error": "reward script timed out", "log_tail": out[-1500:]}
    finally:
        os.unlink(script)
    matches = re.findall(r"REWARD:\s*([-+0-9.eE]+)", out)
    score = float(matches[-1]) if matches else 0.0
    components = [line.strip() for line in out.splitlines()
                  if re.match(r"\s*(PASS|FAIL|PARTIAL|ERROR)\b", line)]
    result = {"passed": bool(matches) and score >= float(threshold), "score": score,
              "components": components[:40], "log_tail": out[-1500:]}
    if not matches:
        result["error"] = "no REWARD line; stderr: " + proc.stderr[-800:]
    return result


# ---------------------------------------------------------------------------
# osworld-check: vendored OSWorld V1 LibreOffice metrics (Apache-2.0), see update/README.md.
# ---------------------------------------------------------------------------

_OSW_SOURCES = {'osworld_lo_support': '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', 'slides': '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', 'docs': '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', 'gimp': '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'}
_OSW_ORDER = ['osworld_lo_support', 'slides', 'docs', 'gimp']
_OSW_LOADED = {}


def _osw_load():
    import base64 as _b64
    import types as _types
    import zlib as _zlib
    if _OSW_LOADED:
        return _OSW_LOADED
    for name in _OSW_ORDER:
        code = _zlib.decompress(_b64.b64decode(_OSW_SOURCES[name])).decode("utf-8")
        mod = _types.ModuleType("osw_" + name)
        mod.__file__ = os.path.abspath(__file__)
        sys.modules["osw_" + name] = mod
        exec(compile(code, "osw_" + name, "exec"), mod.__dict__)
        _OSW_LOADED[name] = mod
        if name == "osworld_lo_support":
            mod.install_shims()
    return _OSW_LOADED


def osworld_check(payload_b64):
    import logging as _logging
    _logging.disable(_logging.CRITICAL)
    mods = _osw_load()
    return mods["osworld_lo_support"].run_check(
        payload_b64, {"slides": mods["slides"], "docs": mods["docs"], "gimp": mods["gimp"]})


COMMANDS = {
    "python-reward": ("Run an inline (base64 zlib) reward script and report its REWARD score",
                      lambda v, args: python_reward(args[0], args[1] if len(args) > 1 else "0.999")),
    "osworld-check": ("Run vendored OSWorld V1 LibreOffice evaluators on a (base64 zlib JSON) payload",
                      lambda v, args: osworld_check(args[0])),
    # Live state (Script-Fu)
    "images": ("List all open images", lambda v, args: v.get_images()),
    "image-info": ("Detailed image info", lambda v, args: v.get_image_info(int(args[0]) if args else 0)),
    "layers": ("List layers", lambda v, args: v.get_layers(int(args[0]) if args else 0)),
    "channels": ("List channels", lambda v, args: v.get_channels(int(args[0]) if args else 0)),
    "active-layer": ("Active layer info", lambda v, args: v.get_active_layer(int(args[0]) if args else 0)),
    "pixel-color": ("Pixel color at x y", lambda v, args: v.get_pixel_color(int(args[0]), int(args[1]), int(args[2]) if len(args) > 2 else 0)),

    # File-based
    "file-info": ("Image file info (PIL)", lambda v, args: v.get_file_info(args[0])),
    "pixel-color-file": ("Pixel color from file", lambda v, args: v.get_pixel_color_file(args[0], int(args[1]), int(args[2]))),
    "preferences": ("Read gimprc preference", lambda v, args: v.get_preferences(args[0] if args else None)),

    # Check — live
    "check-image-open": ("Check image is open", lambda v, args: v.check_image_open(args[0])),
    "check-layer-exists": ("Check layer exists", lambda v, args: v.check_layer_exists(args[0], int(args[1]) if len(args) > 1 else 0)),
    "check-layer-count": ("Check layer count", lambda v, args: v.check_layer_count(int(args[0]), int(args[1]) if len(args) > 1 else 0)),
    "check-image-mode": ("Check color mode (RGB/GRAY/INDEXED)", lambda v, args: v.check_image_mode(args[0], int(args[1]) if len(args) > 1 else 0)),
    "check-has-alpha": ("Check image has alpha", lambda v, args: v.check_has_alpha(int(args[0]) if args else 0)),
    "check-resolution": ("Check DPI resolution", lambda v, args: v.check_resolution(float(args[0]), float(args[1]), int(args[2]) if len(args) > 2 else 0)),
    "check-image-size": ("Check image dimensions", lambda v, args: v.check_image_size(int(args[0]), int(args[1]), int(args[2]) if len(args) > 2 else 0)),

    # Check — file-based
    "check-file-exists": ("Check file exists", lambda v, args: v.check_file_exists(args[0])),
    "check-file-dimensions": ("Check exported image dimensions", lambda v, args: v.check_file_dimensions(args[0], int(args[1]), int(args[2]))),
    "check-file-format": ("Check file format (PNG/JPEG/BMP)", lambda v, args: v.check_file_format(args[0], args[1])),
    "check-file-mode": ("Check file color mode (RGB/RGBA/L)", lambda v, args: v.check_file_mode(args[0], args[1])),
    "check-pixel-color-file": ("Check pixel color in file", lambda v, args: v.check_pixel_color_file(args[0], int(args[1]), int(args[2]), int(args[3]), int(args[4]), int(args[5]), int(args[6]) if len(args) > 6 else 5)),
}


def _print_usage():
    print("GIMP Verifier — query GIMP state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nScript-Fu endpoints require GIMP running with server on port {SF_PORT}.")
    print("File-based endpoints require Pillow (PIL).")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = GimpVerifier()
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
