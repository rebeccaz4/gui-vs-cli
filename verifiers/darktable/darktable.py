"""
darktable Verifier — programmatic state inspection for darktable in E2B sandbox.

Verification channels (in order of preference):
  1. SQLite (library.db, data.db) — images, metadata, tags, styles, presets
  2. XMP sidecar files — full edit history in XML alongside raw images
  3. darktable-cli — headless export verification

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/darktable.py library-images")
    sandbox.commands.run("python3 /home/user/verifiers/darktable.py image-tags 1")
    sandbox.commands.run("python3 /home/user/verifiers/darktable.py check-tag-exists landscape")

Usage from Python (inside sandbox or via E2B):
    from verifiers.darktable import DarktableVerifier
    v = DarktableVerifier()
    images = v.library_images()
    tags = v.image_tags(1)

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - darktable installed (for darktable-cli export verification)
  - sqlite3 (standard library)
  - xml.etree.ElementTree (standard library)
  - PIL/Pillow (for export-info dimensions)
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DARKTABLE_CONFIG_DIR = Path.home() / ".config" / "darktable"
LIBRARY_DB = "library.db"
DATA_DB = "data.db"

# XMP / darktable namespaces
XMP_NAMESPACES = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "xmpMM": "http://ns.adobe.com/xap/1.0/mm/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "darktable": "http://darktable.sf.net/",
    "exif": "http://ns.adobe.com/exif/1.0/",
    "lr": "http://ns.adobe.com/lightroom/1.0/",
}

# Register namespaces so ET output is clean
for prefix, uri in XMP_NAMESPACES.items():
    ET.register_namespace(prefix, uri)


def _find_config_dir() -> Path | None:
    """Locate the darktable config directory."""
    env_dir = os.environ.get("DARKTABLE_CONFIG_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.exists():
            return p
    if DARKTABLE_CONFIG_DIR.exists():
        return DARKTABLE_CONFIG_DIR
    # Fallback: check /tmp for sandbox setups
    for d in Path("/tmp").glob("darktable-*/"):
        if d.exists():
            return d
    return None


# ---------------------------------------------------------------------------
# SQLite helpers (copy DB before reading to avoid WAL locks)
# ---------------------------------------------------------------------------

def _query_sqlite(db_name: str, query: str, params: tuple = ()) -> list[dict]:
    """Query a darktable SQLite DB safely (copies it first to avoid WAL locks)."""
    config_dir = _find_config_dir()
    if not config_dir:
        return [{"error": "darktable config directory not found"}]

    db_path = config_dir / db_name
    if not db_path.exists():
        return [{"error": f"{db_name} not found at {db_path}"}]

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        shutil.copy2(db_path, tmp.name)
        for ext in ("-wal", "-shm"):
            wal = Path(str(db_path) + ext)
            if wal.exists():
                shutil.copy2(wal, tmp.name + ext)

        conn = sqlite3.connect(tmp.name)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    finally:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)


def _query_sqlite_joined(query: str, params: tuple = ()) -> list[dict]:
    """Query across library.db and data.db (tags table moved to data.db in modern darktable).

    Opens library.db as `main` and attaches data.db as `data`, so queries can
    reference `main.tagged_images` alongside `data.tags` in a single statement.
    Safely copies both DBs first to avoid WAL locks.
    """
    config_dir = _find_config_dir()
    if not config_dir:
        return [{"error": "darktable config directory not found"}]

    lib_path = config_dir / LIBRARY_DB
    data_path = config_dir / DATA_DB
    if not lib_path.exists():
        return [{"error": f"{LIBRARY_DB} not found at {lib_path}"}]
    if not data_path.exists():
        return [{"error": f"{DATA_DB} not found at {data_path}"}]

    lib_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    lib_tmp.close()
    data_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    data_tmp.close()
    try:
        for src, dst in ((lib_path, lib_tmp.name), (data_path, data_tmp.name)):
            shutil.copy2(src, dst)
            for ext in ("-wal", "-shm"):
                wal = Path(str(src) + ext)
                if wal.exists():
                    shutil.copy2(wal, dst + ext)

        conn = sqlite3.connect(lib_tmp.name)
        conn.row_factory = sqlite3.Row
        conn.execute("ATTACH DATABASE ? AS data", (data_tmp.name,))
        cursor = conn.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    finally:
        for name in (lib_tmp.name, data_tmp.name):
            if os.path.exists(name):
                os.unlink(name)
            for ext in ("-wal", "-shm"):
                p = name + ext
                if os.path.exists(p):
                    os.unlink(p)


# ---------------------------------------------------------------------------
# XMP parsing helpers
# ---------------------------------------------------------------------------

def _parse_xmp(xmp_path: str) -> ET.Element | dict:
    """Parse an XMP sidecar file and return the root element, or error dict."""
    p = Path(xmp_path)
    if not p.exists():
        return {"error": f"XMP file not found: {xmp_path}"}
    try:
        tree = ET.parse(p)
        return tree.getroot()
    except ET.ParseError as e:
        return {"error": f"Failed to parse XMP: {e}"}


def _get_rdf_description(root: ET.Element) -> ET.Element | None:
    """Find the main rdf:Description element in an XMP tree."""
    # Try direct child of rdf:RDF
    rdf_ns = XMP_NAMESPACES["rdf"]
    for rdf in root.iter(f"{{{rdf_ns}}}RDF"):
        for desc in rdf.iter(f"{{{rdf_ns}}}Description"):
            return desc
    # Fallback: search anywhere
    for desc in root.iter(f"{{{rdf_ns}}}Description"):
        return desc
    return None


# ---------------------------------------------------------------------------
# DarktableVerifier class
# ---------------------------------------------------------------------------

class DarktableVerifier:
    """Stateless verifier — each method call is independent."""

    # === Query: SQLite ===

    def library_images(self, query: str | None = None, limit: int = 50) -> list[dict]:
        """List images from library.db, optionally filtering by filename.

        Example:
            v.library_images("sunset")
            => [{"id": 1, "filename": "sunset.CR2", "film_id": 1, ...}]
        """
        if query:
            sql = """
                SELECT i.id, i.film_id, i.filename, i.datetime_taken,
                       i.width, i.height, i.flags, i.version,
                       f.folder as film_roll
                FROM main.images i
                LEFT JOIN main.film_rolls f ON i.film_id = f.id
                WHERE i.filename LIKE ?
                ORDER BY i.id DESC
                LIMIT ?
            """
            return _query_sqlite(LIBRARY_DB, sql, (f"%{query}%", limit))
        else:
            sql = """
                SELECT i.id, i.film_id, i.filename, i.datetime_taken,
                       i.width, i.height, i.flags, i.version,
                       f.folder as film_roll
                FROM main.images i
                LEFT JOIN main.film_rolls f ON i.film_id = f.id
                ORDER BY i.id DESC
                LIMIT ?
            """
            return _query_sqlite(LIBRARY_DB, sql, (limit,))

    def image_info(self, image_id: int) -> dict:
        """Get detailed info for a specific image by ID.

        Example:
            v.image_info(1)
            => {"id": 1, "filename": "photo.CR2", "width": 6000, ...}
        """
        sql = """
            SELECT i.id, i.film_id, i.filename, i.datetime_taken,
                   i.width, i.height, i.flags, i.version,
                   i.output_width, i.output_height,
                   i.longitude, i.latitude, i.altitude,
                   i.exposure, i.aperture, i.iso, i.focal_length,
                   i.maker, i.model, i.lens,
                   f.folder as film_roll
            FROM main.images i
            LEFT JOIN main.film_rolls f ON i.film_id = f.id
            WHERE i.id = ?
        """
        rows = _query_sqlite(LIBRARY_DB, sql, (image_id,))
        if rows and "error" in rows[0]:
            return rows[0]
        if not rows:
            return {"error": f"Image with id={image_id} not found"}
        return rows[0]

    def tags(self, query: str | None = None) -> list[dict]:
        """List all tags, optionally filtering by name.

        Example:
            v.tags("landscape")
            => [{"id": 1, "name": "landscape"}]
        """
        if query:
            sql = "SELECT id, name FROM main.tags WHERE name LIKE ? ORDER BY name"
            return _query_sqlite(DATA_DB, sql, (f"%{query}%",))
        else:
            sql = "SELECT id, name FROM main.tags ORDER BY name"
            return _query_sqlite(DATA_DB, sql)

    def image_tags(self, image_id: int) -> list[dict]:
        """Get all tags assigned to a specific image.

        Example:
            v.image_tags(1)
            => [{"tag_id": 1, "tag_name": "landscape"}, {"tag_id": 2, "tag_name": "sunset"}]
        """
        sql = """
            SELECT t.id as tag_id, t.name as tag_name
            FROM main.tagged_images ti
            JOIN data.tags t ON ti.tagid = t.id
            WHERE ti.imgid = ?
            ORDER BY t.name
        """
        return _query_sqlite_joined(sql, (image_id,))

    def styles(self) -> list[dict]:
        """List available styles from data.db.

        Example:
            v.styles()
            => [{"id": 1, "name": "B&W Film", "description": "Classic film look"}]
        """
        sql = "SELECT id, name, description FROM styles ORDER BY name"
        return _query_sqlite(DATA_DB, sql)

    def presets(self) -> list[dict]:
        """List available presets from data.db.

        Example:
            v.presets()
            => [{"name": "my preset", "operation": "exposure", "op_version": 1}]
        """
        sql = """
            SELECT name, operation, op_version, enabled, description
            FROM presets
            ORDER BY name
        """
        return _query_sqlite(DATA_DB, sql)

    def collections(self) -> list[dict]:
        """List film rolls (collections) from library.db.

        Example:
            v.collections()
            => [{"id": 1, "folder": "/home/user/photos"}]
        """
        sql = "SELECT id, folder FROM main.film_rolls ORDER BY id"
        return _query_sqlite(LIBRARY_DB, sql)

    # === Query: XMP sidecar ===

    def xmp_history(self, xmp_file: str) -> dict:
        """Parse XMP sidecar for edit history (darktable operations).

        Example:
            v.xmp_history("photo.CR2.xmp")
            => {"operations": [{"operation": "exposure", "enabled": "1", "params": "..."}]}
        """
        root = _parse_xmp(xmp_file)
        if isinstance(root, dict):
            return root

        dt_ns = XMP_NAMESPACES["darktable"]
        rdf_ns = XMP_NAMESPACES["rdf"]

        operations = []

        # Look for darktable:history_operation, darktable:history_enabled, etc.
        # darktable stores history as parallel Bag/Seq elements
        desc = _get_rdf_description(root)
        if desc is None:
            return {"operations": [], "note": "No rdf:Description found"}

        # Find darktable:history as a sequence
        history_ops = []
        history_enabled = []
        history_params = []
        history_modversion = []

        for elem in desc:
            tag = elem.tag
            if tag == f"{{{dt_ns}}}history_operation":
                for item in elem.iter(f"{{{rdf_ns}}}li"):
                    history_ops.append(item.text or "")
            elif tag == f"{{{dt_ns}}}history_enabled":
                for item in elem.iter(f"{{{rdf_ns}}}li"):
                    history_enabled.append(item.text or "")
            elif tag == f"{{{dt_ns}}}history_params":
                for item in elem.iter(f"{{{rdf_ns}}}li"):
                    history_params.append(item.text or "")
            elif tag == f"{{{dt_ns}}}history_modversion":
                for item in elem.iter(f"{{{rdf_ns}}}li"):
                    history_modversion.append(item.text or "")

        for i in range(len(history_ops)):
            op = {
                "operation": history_ops[i] if i < len(history_ops) else None,
                "enabled": history_enabled[i] if i < len(history_enabled) else None,
                "params": history_params[i] if i < len(history_params) else None,
                "modversion": history_modversion[i] if i < len(history_modversion) else None,
            }
            operations.append(op)

        return {"operations": operations, "count": len(operations)}

    def xmp_rating(self, xmp_file: str) -> dict:
        """Get the star rating from an XMP sidecar file.

        Example:
            v.xmp_rating("photo.CR2.xmp")
            => {"rating": 4}
        """
        root = _parse_xmp(xmp_file)
        if isinstance(root, dict):
            return root

        xmp_ns = XMP_NAMESPACES["xmp"]
        desc = _get_rdf_description(root)
        if desc is None:
            return {"rating": None, "note": "No rdf:Description found"}

        # Rating can be an attribute or child element
        rating = desc.get(f"{{{xmp_ns}}}Rating")
        if rating is None:
            rating_elem = desc.find(f"{{{xmp_ns}}}Rating")
            if rating_elem is not None:
                rating = rating_elem.text

        if rating is not None:
            try:
                return {"rating": int(rating)}
            except ValueError:
                return {"rating": rating}
        return {"rating": None}

    # === Query: Export info ===

    def export_info(self, file_path: str) -> dict:
        """Get info about an exported file (dimensions, format, size).

        Example:
            v.export_info("/home/user/output.jpg")
            => {"path": "...", "exists": true, "size_bytes": 123456,
                "width": 6000, "height": 4000, "format": "JPEG"}
        """
        p = Path(file_path)
        if not p.exists():
            return {"error": f"File not found: {file_path}"}

        info: dict[str, Any] = {
            "path": str(p),
            "exists": True,
            "size_bytes": p.stat().st_size,
        }

        try:
            from PIL import Image
            with Image.open(p) as img:
                info["width"] = img.width
                info["height"] = img.height
                info["format"] = img.format
                info["mode"] = img.mode
        except ImportError:
            info["note"] = "PIL not installed — dimensions unavailable"
        except Exception as e:
            info["image_error"] = str(e)

        return info

    # === Check endpoints ===

    def check_file_exists(self, path: str) -> dict:
        """Check if a file exists.

        Example:
            v.check_file_exists("/home/user/photos/sunset.CR2")
            => {"exists": true, "size_bytes": 25000000}
        """
        p = Path(path)
        exists = p.exists()
        result: dict[str, Any] = {"exists": exists}
        if exists:
            result["size_bytes"] = p.stat().st_size
            result["is_file"] = p.is_file()
        return result

    def check_image_imported(self, filename: str) -> dict:
        """Check if an image with the given filename is in the library.

        Example:
            v.check_image_imported("sunset.CR2")
            => {"imported": true, "image_id": 1, "film_roll": "/home/user/photos"}
        """
        sql = """
            SELECT i.id, i.filename, f.folder as film_roll
            FROM main.images i
            LEFT JOIN main.film_rolls f ON i.film_id = f.id
            WHERE i.filename = ?
            LIMIT 1
        """
        rows = _query_sqlite(LIBRARY_DB, sql, (filename,))
        if rows and "error" in rows[0]:
            return rows[0]
        if rows:
            return {"imported": True, "image_id": rows[0]["id"], "film_roll": rows[0].get("film_roll")}
        return {"imported": False}

    def check_tag_exists(self, tag_name: str) -> dict:
        """Check if a tag exists in the library.

        Handles darktable's hierarchical tag format (e.g. "darktable|landscape")
        by matching both exact name and pipe-delimited suffix.

        Example:
            v.check_tag_exists("landscape")
            => {"exists": true, "tag_id": 1}
        """
        sql = "SELECT id, name FROM main.tags WHERE name = ? OR name LIKE ? LIMIT 1"
        rows = _query_sqlite(DATA_DB, sql, (tag_name, f"%|{tag_name}"))
        if rows and "error" in rows[0]:
            return rows[0]
        if rows:
            return {"exists": True, "tag_id": rows[0]["id"], "name": rows[0]["name"]}
        return {"exists": False}

    def check_image_tagged(self, image_id: int, tag_name: str) -> dict:
        """Check if a specific image has a specific tag.

        Handles darktable's hierarchical tag format (e.g. "darktable|landscape").

        Example:
            v.check_image_tagged(1, "landscape")
            => {"tagged": true, "tag_id": 1}
        """
        sql = """
            SELECT t.id as tag_id, t.name as tag_name
            FROM main.tagged_images ti
            JOIN data.tags t ON ti.tagid = t.id
            WHERE ti.imgid = ? AND (t.name = ? OR t.name LIKE ?)
            LIMIT 1
        """
        rows = _query_sqlite_joined(sql, (image_id, tag_name, f"%|{tag_name}"))
        if rows and "error" in rows[0]:
            return rows[0]
        if rows:
            return {"tagged": True, "tag_id": rows[0]["tag_id"]}
        return {"tagged": False}

    def check_image_exported(self, output_path: str) -> dict:
        """Check if an exported file exists and is a valid image.

        Example:
            v.check_image_exported("/home/user/output.jpg")
            => {"exported": true, "valid_image": true, "size_bytes": 123456}
        """
        p = Path(output_path)
        if not p.exists():
            return {"exported": False}

        result: dict[str, Any] = {
            "exported": True,
            "size_bytes": p.stat().st_size,
        }

        try:
            from PIL import Image
            with Image.open(p) as img:
                img.verify()
            result["valid_image"] = True
        except ImportError:
            result["valid_image"] = None
            result["note"] = "PIL not installed — cannot verify image validity"
        except Exception:
            result["valid_image"] = False

        return result

    def check_xmp_has_operation(self, xmp_file: str, operation: str) -> dict:
        """Check if an XMP sidecar's edit history contains a specific operation.

        Example:
            v.check_xmp_has_operation("photo.CR2.xmp", "exposure")
            => {"has_operation": true, "count": 2}
        """
        history = self.xmp_history(xmp_file)
        if "error" in history:
            return history

        matches = [
            op for op in history.get("operations", [])
            if op.get("operation") == operation
        ]
        return {"has_operation": len(matches) > 0, "count": len(matches)}

    def check_image_rating(self, image_id: int, expected_rating: int) -> dict:
        """Check if an image has a specific star rating in library.db.

        Example:
            v.check_image_rating(1, 4)
            => {"matches": true, "actual_rating": 4, "expected_rating": 4}
        """
        sql = "SELECT id, flags FROM main.images WHERE id = ?"
        rows = _query_sqlite(LIBRARY_DB, sql, (image_id,))
        if rows and "error" in rows[0]:
            return rows[0]
        if not rows:
            return {"error": f"Image with id={image_id} not found"}

        # In darktable, rating is stored in the lower bits of flags (bits 0-2 = stars 0-5)
        # Rating mask: flags & 0x7
        flags = rows[0].get("flags", 0)
        actual_rating = flags & 0x7
        return {
            "matches": actual_rating == expected_rating,
            "actual_rating": actual_rating,
            "expected_rating": expected_rating,
        }

    def check_image_tagged_by_filename(self, filename: str, tag_name: str) -> dict:
        """Check if an image (looked up by filename) has a specific tag.

        Avoids hardcoding image IDs — looks up the image by filename first.

        Example:
            v.check_image_tagged_by_filename("photo.png", "landscape")
            => {"tagged": true, "tag_id": 1, "image_id": 3}
        """
        sql = "SELECT id FROM main.images WHERE filename = ? LIMIT 1"
        rows = _query_sqlite(LIBRARY_DB, sql, (filename,))
        if rows and "error" in rows[0]:
            return rows[0]
        if not rows:
            return {"tagged": False, "error": f"Image '{filename}' not found in library"}
        image_id = rows[0]["id"]
        result = self.check_image_tagged(image_id, tag_name)
        result["image_id"] = image_id
        return result

    def check_image_rating_by_filename(self, filename: str, expected_rating: int) -> dict:
        """Check if an image (looked up by filename) has a specific star rating.

        Avoids hardcoding image IDs — looks up the image by filename first.

        Example:
            v.check_image_rating_by_filename("photo.png", 3)
            => {"matches": true, "actual_rating": 3, "expected_rating": 3, "image_id": 1}
        """
        sql = "SELECT id, flags FROM main.images WHERE filename = ? LIMIT 1"
        rows = _query_sqlite(LIBRARY_DB, sql, (filename,))
        if rows and "error" in rows[0]:
            return rows[0]
        if not rows:
            return {"matches": False, "error": f"Image '{filename}' not found in library"}
        image_id = rows[0]["id"]
        flags = rows[0].get("flags", 0)
        actual_rating = flags & 0x7
        return {
            "matches": actual_rating == expected_rating,
            "actual_rating": actual_rating,
            "expected_rating": expected_rating,
            "image_id": image_id,
        }

    def check_db_has_operation(self, filename: str, operation: str) -> dict:
        """Check if an image's processing history in library.db contains a specific operation.

        Queries the history table directly — more reliable than XMP checks because:
        - XMP sidecars may not be flushed to disk during a session
        - Avoids darktable namespace URI mismatches in XMP parsing

        Example:
            v.check_db_has_operation("photo.png", "exposure")
            => {"has_operation": true, "count": 1, "image_id": 1}
        """
        img_sql = "SELECT id FROM main.images WHERE filename = ? LIMIT 1"
        rows = _query_sqlite(LIBRARY_DB, img_sql, (filename,))
        if rows and "error" in rows[0]:
            return rows[0]
        if not rows:
            return {"has_operation": False, "error": f"Image '{filename}' not found in library"}
        image_id = rows[0]["id"]

        hist_sql = "SELECT operation, enabled FROM history WHERE imgid = ? AND operation = ?"
        hist_rows = _query_sqlite(LIBRARY_DB, hist_sql, (image_id, operation))
        if hist_rows and "error" in hist_rows[0]:
            return {"has_operation": False, "image_id": image_id, "note": str(hist_rows[0].get("error"))}
        return {
            "has_operation": len(hist_rows) > 0,
            "count": len(hist_rows),
            "image_id": image_id,
        }

    def check_style_exists(self, style_name: str) -> dict:
        """Check if a style with the given name exists in data.db.

        Example:
            v.check_style_exists("B&W Film")
            => {"exists": true, "style_id": 1}
        """
        sql = "SELECT id, name, description FROM styles WHERE name = ? LIMIT 1"
        rows = _query_sqlite(DATA_DB, sql, (style_name,))
        if rows and "error" in rows[0]:
            return rows[0]
        if rows:
            return {"exists": True, "style_id": rows[0]["id"], "name": rows[0]["name"]}
        return {"exists": False}


# ---------------------------------------------------------------------------
# CLI interface — for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

COMMANDS = {
    # Query: SQLite
    "library-images": (
        "List images from library",
        lambda v, args: v.library_images(query=args[0] if args else None),
    ),
    "image-info": (
        "Detailed image info by ID",
        lambda v, args: v.image_info(int(args[0])),
    ),
    "tags": (
        "List tags",
        lambda v, args: v.tags(query=args[0] if args else None),
    ),
    "image-tags": (
        "Tags on a specific image",
        lambda v, args: v.image_tags(int(args[0])),
    ),
    "styles": (
        "List available styles",
        lambda v, args: v.styles(),
    ),
    "presets": (
        "List available presets",
        lambda v, args: v.presets(),
    ),
    "collections": (
        "List film rolls/collections",
        lambda v, args: v.collections(),
    ),

    # Query: XMP
    "xmp-history": (
        "Parse XMP sidecar edit history",
        lambda v, args: v.xmp_history(args[0]),
    ),
    "xmp-rating": (
        "Get rating from XMP sidecar",
        lambda v, args: v.xmp_rating(args[0]),
    ),

    # Query: Export
    "export-info": (
        "Info about an exported file",
        lambda v, args: v.export_info(args[0]),
    ),

    # Checks
    "check-file-exists": (
        "Check if file exists",
        lambda v, args: v.check_file_exists(args[0]),
    ),
    "check-image-imported": (
        "Check if image is in library",
        lambda v, args: v.check_image_imported(args[0]),
    ),
    "check-tag-exists": (
        "Check if tag exists",
        lambda v, args: v.check_tag_exists(args[0]),
    ),
    "check-image-tagged": (
        "Check if image has tag",
        lambda v, args: v.check_image_tagged(int(args[0]), args[1]),
    ),
    "check-image-exported": (
        "Check if exported file is valid",
        lambda v, args: v.check_image_exported(args[0]),
    ),
    "check-xmp-has-operation": (
        "Check XMP for edit operation",
        lambda v, args: v.check_xmp_has_operation(args[0], args[1]),
    ),
    "check-image-rating": (
        "Check image star rating",
        lambda v, args: v.check_image_rating(int(args[0]), int(args[1])),
    ),
    "check-style-exists": (
        "Check if style exists",
        lambda v, args: v.check_style_exists(args[0]),
    ),
    "check-image-tagged-by-filename": (
        "Check if image (by filename) has tag",
        lambda v, args: v.check_image_tagged_by_filename(args[0], args[1]),
    ),
    "check-image-rating-by-filename": (
        "Check image star rating by filename",
        lambda v, args: v.check_image_rating_by_filename(args[0], int(args[1])),
    ),
    "check-db-has-operation": (
        "Check library.db history for edit operation (by filename)",
        lambda v, args: v.check_db_has_operation(args[0], args[1]),
    ),
}


def _print_usage():
    print("darktable Verifier — query darktable state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nAll output is JSON. Reads from {DARKTABLE_CONFIG_DIR}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = DarktableVerifier()
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
