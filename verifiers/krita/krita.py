"""
Krita Verifier — programmatic state inspection for Krita .kra files in E2B sandbox.

Verification channel:
  .kra files are ZIP archives containing XML metadata and PNG layer data.
  Primary inspection is done by unzipping and parsing maindoc.xml,
  documentinfo.xml, and reading mergedimage.png with PIL.

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/krita.py doc-info /path/to/file.kra")
    sandbox.commands.run("python3 /home/user/verifiers/krita.py layers /path/to/file.kra")
    sandbox.commands.run("python3 /home/user/verifiers/krita.py check-layer-exists /path/to/file.kra 'Background'")

Usage from Python (inside sandbox or via E2B):
    from verifiers.krita import KritaVerifier
    v = KritaVerifier()
    info = v.get_doc_info("/path/to/file.kra")
    layers = v.get_layers("/path/to/file.kra")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - Pillow (PIL) for mergedimage.png inspection
  - zipfile, xml.etree.ElementTree (standard library)

Config:
  - Krita config: ~/.config/kritarc
  - CLI export: krita input.kra --export --export-filename output.png
"""

import json
import os
import sys
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_kra_file(kra_path: str, inner_path: str) -> bytes | None:
    """Read a file from inside a .kra ZIP archive."""
    try:
        with zipfile.ZipFile(kra_path, "r") as zf:
            if inner_path in zf.namelist():
                return zf.read(inner_path)
    except (zipfile.BadZipFile, FileNotFoundError, KeyError):
        pass
    return None


def _parse_maindoc(kra_path: str) -> ET.Element | None:
    """Parse maindoc.xml from a .kra file, return the root element."""
    data = _read_kra_file(kra_path, "maindoc.xml")
    if data is None:
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


def _parse_documentinfo(kra_path: str) -> ET.Element | None:
    """Parse documentinfo.xml from a .kra file, return the root element."""
    data = _read_kra_file(kra_path, "documentinfo.xml")
    if data is None:
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


def _find_image_element(root: ET.Element) -> ET.Element | None:
    """Find the <IMAGE> element in maindoc.xml, handling namespaces."""
    # Try direct tag first
    img = root.find("IMAGE")
    if img is not None:
        return img
    # Try with namespace wildcard
    for elem in root.iter():
        if elem.tag.endswith("IMAGE") or elem.tag == "IMAGE":
            return elem
    # The root itself might be IMAGE
    if root.tag.endswith("IMAGE") or root.tag == "IMAGE":
        return root
    return None


def _collect_layers(element: ET.Element, prefix: str = "", parent: str = "") -> list[dict]:
    """Recursively collect layer info from maindoc.xml layer tree.

    Handles nested <layers> containers (for groups and for masks nested under
    paint layers) and direct <mask> children (older Krita format)."""
    layers = []

    # Collect all <layer> and <mask> elements that appear as children of
    # either this element directly, or of its <layers> child container.
    sources = [element]
    for child in element:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == "layers":
            sources.append(child)

    seen = set()
    for src in sources:
        for layer_elem in src:
            tag = layer_elem.tag.split("}")[-1] if "}" in layer_elem.tag else layer_elem.tag
            if tag not in ("layer", "mask"):
                continue
            if id(layer_elem) in seen:
                continue
            seen.add(id(layer_elem))

            attribs = dict(layer_elem.attrib)
            name = attribs.get("name", "")
            full_name = f"{prefix}/{name}" if prefix else name

            layer_info = {
                "name": name,
                "full_path": full_name,
                "parent": parent,
                "node_type": attribs.get("nodetype", ""),
                "visible": attribs.get("visible", "1") == "1",
                "opacity": int(attribs.get("opacity", "255")),
                "composite_op": attribs.get("compositeop", ""),
                "colorspacename": attribs.get("colorspacename", ""),
                "x": int(attribs.get("x", "0")),
                "y": int(attribs.get("y", "0")),
                "onionskin": attribs.get("onionskin", "0") == "1",
                "intimeline": attribs.get("intimeline", "0") == "1",
                "locked": attribs.get("locked", "0") == "1",
                "collapsed": attribs.get("collapsed", "0") == "1",
                "filename": attribs.get("filename", ""),
                "generator_name": attribs.get("generatorname", ""),
            }

            if "width" in attribs:
                layer_info["width"] = int(attribs["width"])
            if "height" in attribs:
                layer_info["height"] = int(attribs["height"])

            layers.append(layer_info)

            # Recurse into this layer/mask (for nested masks or groups)
            sub_layers = _collect_layers(layer_elem, prefix=full_name, parent=name)
            layers.extend(sub_layers)

    return layers


def _get_text(element: ET.Element, tag: str) -> str | None:
    """Get text content of a child element, handling namespaces."""
    child = element.find(tag)
    if child is None:
        # Try namespace wildcard
        for elem in element:
            local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if local_tag == tag:
                return (elem.text or "").strip()
        return None
    return (child.text or "").strip()


# ---------------------------------------------------------------------------
# KritaVerifier class
# ---------------------------------------------------------------------------

class KritaVerifier:
    """Stateless verifier for Krita .kra files."""

    # === Query endpoints ===

    def get_doc_info(self, kra_path: str) -> dict:
        """Get document dimensions, color space, and resolution from maindoc.xml.

        Example return:
        {
            "width": 1920, "height": 1080,
            "colorspacename": "RGBA",
            "x_res": 300, "y_res": 300,
            "name": "my_painting"
        }
        """
        if not os.path.isfile(kra_path):
            return {"error": f"File not found: {kra_path}"}

        root = _parse_maindoc(kra_path)
        if root is None:
            return {"error": f"Cannot parse maindoc.xml in {kra_path}"}

        img = _find_image_element(root)
        if img is None:
            return {"error": "No IMAGE element found in maindoc.xml"}

        attribs = dict(img.attrib)
        return {
            "width": int(attribs.get("width", "0")),
            "height": int(attribs.get("height", "0")),
            "colorspacename": attribs.get("colorspacename", ""),
            "x_res": int(attribs.get("x-res", "0")),
            "y_res": int(attribs.get("y-res", "0")),
            "name": attribs.get("name", ""),
            "mime": attribs.get("mime", ""),
        }

    def get_metadata(self, kra_path: str) -> dict:
        """Get metadata (title, author, description, dates) from documentinfo.xml.

        Example return:
        {
            "title": "My Painting",
            "author": "Artist Name",
            "description": "A landscape scene",
            "creation_date": "2024-01-15",
            "editing_cycles": "5"
        }
        """
        if not os.path.isfile(kra_path):
            return {"error": f"File not found: {kra_path}"}

        root = _parse_documentinfo(kra_path)
        if root is None:
            return {"error": f"Cannot parse documentinfo.xml in {kra_path}"}

        result = {}

        # documentinfo.xml has <about> section with title, description, etc.
        # and <author> section with full-name, etc.
        # Structure varies but common fields:
        for section in root:
            section_tag = section.tag.split("}")[-1] if "}" in section.tag else section.tag

            if section_tag == "about":
                title = _get_text(section, "title")
                if title:
                    result["title"] = title
                desc = _get_text(section, "abstract") or _get_text(section, "description")
                if desc:
                    result["description"] = desc
                creation = _get_text(section, "creation-date") or _get_text(section, "date")
                if creation:
                    result["creation_date"] = creation
                editing = _get_text(section, "editing-cycles")
                if editing:
                    result["editing_cycles"] = editing
                subject = _get_text(section, "subject")
                if subject:
                    result["subject"] = subject
                keyword = _get_text(section, "keyword")
                if keyword:
                    result["keyword"] = keyword

            elif section_tag == "author":
                full_name = _get_text(section, "full-name") or _get_text(section, "creator-first-name")
                if full_name:
                    result["author"] = full_name

        return result

    def get_layers(self, kra_path: str) -> list[dict]:
        """List all layers with name, type, visibility, opacity, etc.

        Example return:
        [
            {"name": "Background", "node_type": "paintlayer", "visible": true, "opacity": 255, ...},
            {"name": "Layer 1", "node_type": "paintlayer", "visible": true, "opacity": 200, ...}
        ]
        """
        if not os.path.isfile(kra_path):
            return [{"error": f"File not found: {kra_path}"}]

        root = _parse_maindoc(kra_path)
        if root is None:
            return [{"error": f"Cannot parse maindoc.xml in {kra_path}"}]

        img = _find_image_element(root)
        if img is None:
            return [{"error": "No IMAGE element found in maindoc.xml"}]

        return _collect_layers(img)

    def get_layer_info(self, kra_path: str, layer_name: str) -> dict:
        """Get detailed info for a specific layer by name.

        Example return:
        {
            "name": "Background", "node_type": "paintlayer",
            "visible": true, "opacity": 255,
            "composite_op": "normal", "colorspacename": "RGBA"
        }
        """
        layers = self.get_layers(kra_path)
        if layers and "error" in layers[0]:
            return layers[0]

        for layer in layers:
            if layer.get("name") == layer_name:
                return layer

        return {"error": f"Layer '{layer_name}' not found", "available_layers": [l["name"] for l in layers]}

    def get_color_profile(self, kra_path: str) -> dict:
        """Get color profile information from the document.

        Example return:
        {
            "colorspacename": "RGBA",
            "profile_name": "sRGB-elle-V2-srgbtrc.icc",
            "x_res": 300, "y_res": 300
        }
        """
        if not os.path.isfile(kra_path):
            return {"error": f"File not found: {kra_path}"}

        root = _parse_maindoc(kra_path)
        if root is None:
            return {"error": f"Cannot parse maindoc.xml in {kra_path}"}

        img = _find_image_element(root)
        if img is None:
            return {"error": "No IMAGE element found in maindoc.xml"}

        attribs = dict(img.attrib)
        return {
            "colorspacename": attribs.get("colorspacename", ""),
            "profile_name": attribs.get("profile", ""),
            "x_res": int(attribs.get("x-res", "0")),
            "y_res": int(attribs.get("y-res", "0")),
        }

    def get_preview(self, kra_path: str) -> dict:
        """Get info about mergedimage.png (flattened preview).

        Example return:
        {
            "exists": true, "width": 1920, "height": 1080,
            "format": "PNG", "mode": "RGBA"
        }
        """
        if not os.path.isfile(kra_path):
            return {"error": f"File not found: {kra_path}"}

        data = _read_kra_file(kra_path, "mergedimage.png")
        if data is None:
            return {"exists": False}

        try:
            from PIL import Image
            img = Image.open(BytesIO(data))
            return {
                "exists": True,
                "width": img.width,
                "height": img.height,
                "format": img.format or "PNG",
                "mode": img.mode,
            }
        except ImportError:
            # PIL not available, return basic info
            return {
                "exists": True,
                "size_bytes": len(data),
                "note": "Install Pillow for image dimension info",
            }
        except Exception as e:
            return {"exists": True, "size_bytes": len(data), "error": f"Cannot read image: {e}"}

    # === Check endpoints ===

    def check_file_exists(self, path: str) -> dict:
        """Check if a file exists at the given path.

        Example return:
        {"exists": true, "path": "/home/user/painting.kra", "size_bytes": 123456}
        """
        exists = os.path.isfile(path)
        result = {"exists": exists, "path": path}
        if exists:
            result["size_bytes"] = os.path.getsize(path)
        return result

    def check_image_size(self, kra_path: str, width: int, height: int) -> dict:
        """Check if document dimensions match expected width and height.

        Example return:
        {"match": true, "expected": [1920, 1080], "actual": [1920, 1080]}
        """
        info = self.get_doc_info(kra_path)
        if "error" in info:
            return info

        actual_w = info["width"]
        actual_h = info["height"]
        return {
            "match": actual_w == width and actual_h == height,
            "expected": [width, height],
            "actual": [actual_w, actual_h],
        }

    def check_layer_exists(self, kra_path: str, layer_name: str) -> dict:
        """Check if a layer with the given name exists.

        Example return:
        {"exists": true, "layer_name": "Background"}
        """
        layers = self.get_layers(kra_path)
        if layers and "error" in layers[0]:
            return layers[0]

        found = any(l.get("name") == layer_name for l in layers)
        result = {"exists": found, "layer_name": layer_name}
        if not found:
            result["available_layers"] = [l["name"] for l in layers]
        return result

    def check_layer_count(self, kra_path: str, count: int) -> dict:
        """Check if the document has the expected number of layers.

        Example return:
        {"match": true, "expected": 3, "actual": 3}
        """
        layers = self.get_layers(kra_path)
        if layers and "error" in layers[0]:
            return layers[0]

        actual = len(layers)
        return {
            "match": actual == count,
            "expected": count,
            "actual": actual,
        }

    def check_layer_visible(self, kra_path: str, layer_name: str) -> dict:
        """Check if a layer is visible.

        Example return:
        {"visible": true, "layer_name": "Background"}
        """
        layer = self.get_layer_info(kra_path, layer_name)
        if "error" in layer:
            return layer

        return {
            "visible": layer.get("visible", False),
            "layer_name": layer_name,
        }

    def check_color_space(self, kra_path: str, color_space: str) -> dict:
        """Check if the document uses the expected color space (RGBA, GRAYA, etc.).

        Example return:
        {"match": true, "expected": "RGBA", "actual": "RGBA"}
        """
        info = self.get_doc_info(kra_path)
        if "error" in info:
            return info

        actual = info.get("colorspacename", "")
        return {
            "match": actual == color_space,
            "expected": color_space,
            "actual": actual,
        }

    def check_has_metadata(self, kra_path: str, key: str) -> dict:
        """Check if a metadata field exists and is non-empty.

        Valid keys: title, author, description, creation_date, subject, keyword, editing_cycles.

        Example return:
        {"exists": true, "key": "title", "value": "My Painting"}
        """
        metadata = self.get_metadata(kra_path)
        if "error" in metadata:
            return metadata

        value = metadata.get(key)
        exists = value is not None and value != ""
        result = {"exists": exists, "key": key}
        if exists:
            result["value"] = value
        else:
            result["available_keys"] = list(metadata.keys())
        return result

    # === Mask / animation / kritarc helpers ===

    def get_animation_info(self, kra_path: str) -> dict:
        """Get animation framerate and range from maindoc.xml."""
        if not os.path.isfile(kra_path):
            return {"error": f"File not found: {kra_path}"}
        root = _parse_maindoc(kra_path)
        if root is None:
            return {"error": f"Cannot parse maindoc.xml in {kra_path}"}
        img = _find_image_element(root)
        if img is None:
            return {"error": "No IMAGE element in maindoc.xml"}

        anim = None
        for child in img:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "animation":
                anim = child
                break
        if anim is None:
            return {"framerate": None, "range_from": None, "range_to": None}

        framerate = None
        range_from = None
        range_to = None
        current_time = None
        for child in anim:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "framerate":
                try:
                    framerate = int(child.attrib.get("value", "0"))
                except ValueError:
                    pass
            elif tag == "range":
                try:
                    range_from = int(child.attrib.get("from", "0"))
                    range_to = int(child.attrib.get("to", "0"))
                except ValueError:
                    pass
            elif tag == "currentTime":
                try:
                    current_time = int(child.attrib.get("value", "0"))
                except ValueError:
                    pass
        return {
            "framerate": framerate,
            "range_from": range_from,
            "range_to": range_to,
            "current_time": current_time,
        }

    def check_framerate(self, kra_path: str, fps: int) -> dict:
        info = self.get_animation_info(kra_path)
        if "error" in info:
            return info
        actual = info.get("framerate")
        return {"match": actual == fps, "expected": fps, "actual": actual}

    def _get_layer_filename(self, kra_path: str, layer_name: str) -> str | None:
        for layer in self.get_layers(kra_path):
            if layer.get("name") == layer_name:
                return layer.get("filename") or None
        return None

    def check_keyframe_count(self, kra_path: str, layer_name: str, count: int) -> dict:
        """Count keyframes for a given layer. Keyframes are stored either in a
        separate {img}/layers/{filename}.keyframes.xml file, or as <keyframes>
        children of the layer element in maindoc.xml."""
        if not os.path.isfile(kra_path):
            return {"error": f"File not found: {kra_path}"}

        # Find the layer's filename and also count <keyframe> in maindoc subtree.
        layer_filename = None
        maindoc_count = 0
        root = _parse_maindoc(kra_path)
        if root is not None:
            img = _find_image_element(root)
            if img is not None:
                for elem in img.iter():
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if tag == "layer" and elem.attrib.get("name") == layer_name:
                        layer_filename = elem.attrib.get("filename")
                        # Count <keyframe> descendants of this layer
                        for sub in elem.iter():
                            sub_tag = sub.tag.split("}")[-1] if "}" in sub.tag else sub.tag
                            if sub_tag == "keyframe":
                                maindoc_count += 1
                        break

        sidecar_count = 0
        if layer_filename:
            try:
                with zipfile.ZipFile(kra_path, "r") as zf:
                    candidates = [n for n in zf.namelist()
                                  if n.endswith(f"/{layer_filename}.keyframes.xml")
                                  or n.endswith(f"/{layer_filename}.keyframes")]
                    for name in candidates:
                        data = zf.read(name)
                        try:
                            kroot = ET.fromstring(data)
                            for elem in kroot.iter():
                                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                                if tag == "keyframe":
                                    sidecar_count += 1
                        except ET.ParseError:
                            pass
            except (zipfile.BadZipFile, FileNotFoundError):
                pass

        actual = max(maindoc_count, sidecar_count)
        return {
            "match": actual >= count,
            "expected_min": count,
            "actual": actual,
            "layer_name": layer_name,
            "layer_filename": layer_filename,
        }

    def check_mask_of(self, kra_path: str, parent_layer: str, mask_name: str) -> dict:
        """Check that a mask (by name) exists as a child of parent_layer."""
        for layer in self.get_layers(kra_path):
            if layer.get("name") == mask_name and layer.get("parent") == parent_layer:
                return {
                    "exists": True,
                    "node_type": layer.get("node_type", ""),
                    "parent": parent_layer,
                    "mask_name": mask_name,
                }
        return {"exists": False, "parent": parent_layer, "mask_name": mask_name}

    def check_layer_node_type(self, kra_path: str, layer_name: str, expected_type: str) -> dict:
        """Check that a layer/mask has the expected node type."""
        info = self.get_layer_info(kra_path, layer_name)
        if "error" in info:
            return info
        actual = info.get("node_type", "")
        return {"match": actual == expected_type, "expected": expected_type, "actual": actual}

    def check_layer_onionskin(self, kra_path: str, layer_name: str) -> dict:
        info = self.get_layer_info(kra_path, layer_name)
        if "error" in info:
            return info
        return {"onionskin": bool(info.get("onionskin", False)), "layer_name": layer_name}

    def check_layer_animated(self, kra_path: str, layer_name: str) -> dict:
        info = self.get_layer_info(kra_path, layer_name)
        if "error" in info:
            return info
        return {"animated": bool(info.get("intimeline", False)), "layer_name": layer_name}

    def check_background_color(self, kra_path: str, r: int, g: int, b: int, tolerance: int = 10) -> dict:
        """Check ProjectionBackgroundColor element's ColorData (base64 BGRA)."""
        import base64
        root = _parse_maindoc(kra_path)
        if root is None:
            return {"error": "Cannot parse maindoc.xml"}
        img = _find_image_element(root)
        if img is None:
            return {"error": "No IMAGE element"}
        for child in img:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "ProjectionBackgroundColor":
                data = child.attrib.get("ColorData", "")
                try:
                    raw = base64.b64decode(data)
                    if len(raw) >= 3:
                        ab, ag, ar = raw[0], raw[1], raw[2]
                        match = (abs(ab - b) <= tolerance
                                 and abs(ag - g) <= tolerance
                                 and abs(ar - r) <= tolerance)
                        return {"match": match, "expected": [r, g, b],
                                "actual": [ar, ag, ab]}
                except Exception as e:
                    return {"error": f"Cannot decode ColorData: {e}"}
        return {"match": False, "error": "No ProjectionBackgroundColor element"}

    def _parse_kritarc(self, path: str = "/home/user/.config/kritarc") -> dict:
        """Parse a kritarc INI-style file into {section: {key: value}}."""
        if not os.path.isfile(path):
            return {}
        sections: dict[str, dict[str, str]] = {}
        current = None
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.rstrip("\r\n")
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("[") and line.endswith("]"):
                        current = line[1:-1]
                        sections.setdefault(current, {})
                    elif "=" in line and current is not None:
                        k, _, v = line.partition("=")
                        sections[current][k.strip()] = v.strip()
        except OSError:
            return {}
        return sections

    def kritarc_get(self, section: str, key: str, path: str = "/home/user/.config/kritarc") -> dict:
        data = self._parse_kritarc(path)
        if section not in data:
            return {"exists": False, "section": section, "key": key,
                    "available_sections": list(data.keys())}
        if key not in data[section]:
            return {"exists": False, "section": section, "key": key,
                    "available_keys": list(data[section].keys())}
        return {"exists": True, "section": section, "key": key,
                "value": data[section][key]}

    def check_kritarc(self, section: str, key: str, expected: str,
                      path: str = "/home/user/.config/kritarc") -> dict:
        r = self.kritarc_get(section, key, path)
        if not r.get("exists"):
            return {"match": False, "expected": expected, "actual": None,
                    "note": "key not found"}
        actual = r["value"]
        return {"match": actual == expected, "expected": expected, "actual": actual}

    def check_proofing_enabled(self, kra_path: str) -> dict:
        """Proofing attributes live on the <IMAGE> element in newer Krita files."""
        root = _parse_maindoc(kra_path)
        if root is None:
            return {"error": "Cannot parse maindoc.xml"}
        img = _find_image_element(root)
        if img is None:
            return {"error": "No IMAGE element"}
        attrs = dict(img.attrib)
        # Several candidate attrs across Krita versions
        enabled = False
        for k in ("proofing-config-enabled", "proofingConfigEnabled",
                  "proofing-enabled"):
            if attrs.get(k, "").lower() in ("1", "true"):
                enabled = True
                break
        has_profile = bool(attrs.get("proofing-profile-name")
                           or attrs.get("proofing-profile"))
        return {
            "enabled": enabled,
            "has_profile": has_profile,
            "profile": attrs.get("proofing-profile-name")
                       or attrs.get("proofing-profile") or "",
        }

    def check_resolution(self, kra_path: str, dpi: int) -> dict:
        """Check if the document x-resolution matches the expected DPI.

        Example return:
        {"match": true, "expected": 300, "actual_x": 300, "actual_y": 300}
        """
        info = self.get_doc_info(kra_path)
        if "error" in info:
            return info

        actual_x = info.get("x_res", 0)
        actual_y = info.get("y_res", 0)
        return {
            "match": actual_x == dpi,
            "expected": dpi,
            "actual_x": actual_x,
            "actual_y": actual_y,
        }


# ---------------------------------------------------------------------------
# CLI interface — for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

COMMANDS = {
    # Query
    "doc-info": ("Document dimensions, color space, resolution", lambda v, args: v.get_doc_info(args[0])),
    "metadata": ("Title, author, description from documentinfo.xml", lambda v, args: v.get_metadata(args[0])),
    "layers": ("List all layers with properties", lambda v, args: v.get_layers(args[0])),
    "layer-info": ("Detailed info for a specific layer", lambda v, args: v.get_layer_info(args[0], args[1])),
    "color-profile": ("Color profile information", lambda v, args: v.get_color_profile(args[0])),
    "preview": ("Info about mergedimage.png preview", lambda v, args: v.get_preview(args[0])),

    # Check
    "check-file-exists": ("Check file exists", lambda v, args: v.check_file_exists(args[0])),
    "check-image-size": ("Check document dimensions", lambda v, args: v.check_image_size(args[0], int(args[1]), int(args[2]))),
    "check-layer-exists": ("Check layer exists by name", lambda v, args: v.check_layer_exists(args[0], args[1])),
    "check-layer-count": ("Check number of layers", lambda v, args: v.check_layer_count(args[0], int(args[1]))),
    "check-layer-visible": ("Check layer is visible", lambda v, args: v.check_layer_visible(args[0], args[1])),
    "check-color-space": ("Check color model (RGBA, GRAYA, etc.)", lambda v, args: v.check_color_space(args[0], args[1])),
    "check-has-metadata": ("Check metadata field exists", lambda v, args: v.check_has_metadata(args[0], args[1])),
    "check-resolution": ("Check x-resolution DPI", lambda v, args: v.check_resolution(args[0], int(args[1]))),
    # Animation / mask / config extensions
    "animation-info": ("Animation framerate + range", lambda v, args: v.get_animation_info(args[0])),
    "check-framerate": ("Check animation framerate", lambda v, args: v.check_framerate(args[0], int(args[1]))),
    "check-keyframe-count": ("Check >= N keyframes on a layer", lambda v, args: v.check_keyframe_count(args[0], args[1], int(args[2]))),
    "check-mask-of": ("Check mask by name exists under parent layer", lambda v, args: v.check_mask_of(args[0], args[1], args[2])),
    "check-layer-node-type": ("Check layer/mask node type", lambda v, args: v.check_layer_node_type(args[0], args[1], args[2])),
    "check-layer-onionskin": ("Check layer onion skin enabled", lambda v, args: v.check_layer_onionskin(args[0], args[1])),
    "check-layer-animated": ("Check layer is in the timeline (animated)", lambda v, args: v.check_layer_animated(args[0], args[1])),
    "check-background-color": ("Check document projection bg color (R G B)", lambda v, args: v.check_background_color(args[0], int(args[1]), int(args[2]), int(args[3]))),
    "kritarc-get": ("Read kritarc INI value (section key...)",
                    lambda v, args: v.kritarc_get(args[0], " ".join(args[1:]))),
    "check-kritarc": ("Check kritarc value equals (section key... value)",
                      lambda v, args: v.check_kritarc(args[0], " ".join(args[1:-1]), args[-1])),
    "check-proofing-enabled": ("Check document soft-proofing enabled", lambda v, args: v.check_proofing_enabled(args[0])),
}


def _print_usage():
    print("Krita Verifier — inspect .kra file state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print("\nAll output is JSON. .kra files are inspected by unzipping and parsing XML/PNG contents.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = KritaVerifier()
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
