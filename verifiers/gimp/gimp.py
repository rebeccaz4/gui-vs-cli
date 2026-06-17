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

COMMANDS = {
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
