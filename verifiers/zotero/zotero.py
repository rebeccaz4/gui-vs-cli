"""
Zotero Verifier — programmatic state inspection for Zotero in E2B sandbox.

Zotero is a Mozilla XULRunner-based reference manager. It keeps its data in a
SQLite database under ~/Zotero/zotero.sqlite, with file attachments in
~/Zotero/storage/. Mozilla-style prefs live under ~/.zotero/zotero/<rand>.default/prefs.js.

Verification channels (in order of preference):
  1. SQLite query of ~/Zotero/zotero.sqlite (items, collections, tags, creators,
     attachments, notes, fields, trash)
  2. File system: ~/Zotero/storage/<key>/ for attached PDFs and other files
  3. Mozilla prefs.js parsing: ~/.zotero/zotero/*.default*/prefs.js for
     user-configurable Zotero preferences (citation style, language, sync)
  4. Export file parsing: BibTeX/RIS/JSON exported by Zotero to a user path

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/zotero.py collections")
    sandbox.commands.run("python3 /home/user/verifiers/zotero.py check-item-exists 'Attention Is All You Need'")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - Zotero profile at ~/Zotero/ (main data) and optionally ~/.zotero/zotero/*
  - sqlite3 (standard library)
  - No external dependencies

Categories skipped (documented):
  - UI layout / window state: Zotero stores XUL window state in Mozilla's
    xulstore.json, but its schema is opaque and unreliable to parse.
  - Network / sync state: only the configured sync username is inspectable via
    prefs — no endpoint exposes the live sync status.
  - History / undo history: Zotero has no user-visible history store.
  - Keybindings: Zotero has no user-customizable keybindings stored on disk.
"""

import glob
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Path discovery
# ---------------------------------------------------------------------------

def _find_data_dir() -> Path | None:
    """Find the Zotero data directory holding zotero.sqlite + storage/."""
    env = os.environ.get("ZOTERO_DATA_DIR")
    if env:
        p = Path(env)
        if p.exists():
            return p

    # Default Linux location
    default = Path.home() / "Zotero"
    if default.exists() and (default / "zotero.sqlite").exists():
        return default

    # Alt: dataDir may be custom. Try /home/*/Zotero.
    for cand in Path("/home").glob("*/Zotero"):
        if (cand / "zotero.sqlite").exists():
            return cand
    return None


def _find_profile_dir() -> Path | None:
    """Find the Mozilla-style profile dir holding prefs.js."""
    env = os.environ.get("ZOTERO_PROFILE_DIR")
    if env:
        p = Path(env)
        if p.exists():
            return p

    base = Path.home() / ".zotero" / "zotero"
    if base.exists():
        # Look for *.default, *.default-release, etc.
        for pattern in ("*.default-release", "*.default", "*"):
            for cand in sorted(base.glob(pattern)):
                if cand.is_dir() and (cand / "prefs.js").exists():
                    return cand
                if cand.is_dir():
                    # accept even without prefs.js if nothing else
                    return cand

    # Some installs use ~/.config/zotero
    alt = Path.home() / ".config" / "zotero"
    if alt.exists():
        for d in alt.iterdir():
            if d.is_dir():
                return d
    return None


# ---------------------------------------------------------------------------
# SQLite helper (copy to avoid lock contention)
# ---------------------------------------------------------------------------

def _query(sql: str, params: tuple = ()) -> list[dict]:
    data_dir = _find_data_dir()
    if not data_dir:
        return [{"error": "Zotero data directory not found (~/Zotero/zotero.sqlite missing)"}]

    db_path = data_dir / "zotero.sqlite"
    if not db_path.exists():
        return [{"error": f"zotero.sqlite not found at {db_path}"}]

    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    try:
        shutil.copy2(db_path, tmp.name)
        for ext in ("-wal", "-shm"):
            wal = Path(str(db_path) + ext)
            if wal.exists():
                shutil.copy2(wal, tmp.name + ext)

        conn = sqlite3.connect(tmp.name)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
        return rows
    except sqlite3.Error as e:
        return [{"error": f"SQLite error: {e}"}]
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)


# ---------------------------------------------------------------------------
# prefs.js parsing
# ---------------------------------------------------------------------------

def _parse_prefs() -> dict[str, Any]:
    profile = _find_profile_dir()
    if not profile:
        return {}
    prefs_path = profile / "prefs.js"
    if not prefs_path.exists():
        return {}
    prefs: dict[str, Any] = {}
    with open(prefs_path) as f:
        for line in f:
            line = line.strip()
            m = re.match(r'user_pref\("([^"]+)",\s*(.+)\);', line)
            if not m:
                continue
            key = m.group(1)
            raw = m.group(2).strip()
            if raw == "true":
                prefs[key] = True
            elif raw == "false":
                prefs[key] = False
            elif raw.startswith('"') and raw.endswith('"'):
                prefs[key] = raw[1:-1]
            else:
                try:
                    prefs[key] = int(raw)
                except ValueError:
                    try:
                        prefs[key] = float(raw)
                    except ValueError:
                        prefs[key] = raw
    return prefs


# ---------------------------------------------------------------------------
# ZoteroVerifier class
# ---------------------------------------------------------------------------

# Zotero items that are NOT attachments or notes are "regular" bibliographic items.
# In zotero.sqlite, attachments use itemType 'attachment' (itemTypeID=14 typically),
# notes use itemType 'note'. We exclude them from most item queries by joining on
# itemTypes and filtering by name.
EXCLUDE_NON_REGULAR = (
    "items.itemTypeID NOT IN "
    "(SELECT itemTypeID FROM itemTypes WHERE typeName IN ('attachment', 'note'))"
)

NOT_DELETED = "items.itemID NOT IN (SELECT itemID FROM deletedItems)"


class ZoteroVerifier:
    """Stateless verifier — each method call is independent."""

    # =========================================================================
    # Library / profile info
    # =========================================================================

    def get_data_dir(self) -> dict:
        """Return the Zotero data directory path."""
        d = _find_data_dir()
        if not d:
            return {"error": "Zotero data directory not found"}
        return {
            "path": str(d),
            "exists": d.exists(),
            "has_sqlite": (d / "zotero.sqlite").exists(),
            "has_storage": (d / "storage").exists(),
        }

    def get_library_stats(self) -> dict:
        """Top-level counts: regular items, attachments, notes, collections, tags."""
        res = {}
        for label, sql in [
            ("items", f"SELECT COUNT(*) c FROM items WHERE {EXCLUDE_NON_REGULAR} AND {NOT_DELETED}"),
            ("attachments",
             "SELECT COUNT(*) c FROM items "
             "WHERE itemTypeID IN (SELECT itemTypeID FROM itemTypes WHERE typeName='attachment') "
             "AND itemID NOT IN (SELECT itemID FROM deletedItems)"),
            ("notes",
             "SELECT COUNT(*) c FROM items "
             "WHERE itemTypeID IN (SELECT itemTypeID FROM itemTypes WHERE typeName='note') "
             "AND itemID NOT IN (SELECT itemID FROM deletedItems)"),
            ("collections", "SELECT COUNT(*) c FROM collections"),
            ("tags", "SELECT COUNT(*) c FROM tags"),
            ("deleted_items", "SELECT COUNT(*) c FROM deletedItems"),
        ]:
            rows = _query(sql)
            if rows and "error" in rows[0]:
                return rows[0]
            res[label] = rows[0]["c"] if rows else 0
        return res

    # =========================================================================
    # Collections
    # =========================================================================

    def get_collections(self) -> list[dict]:
        sql = """
            SELECT c.collectionID, c.collectionName, c.parentCollectionID,
                   c.libraryID, c.key,
                   (SELECT COUNT(*) FROM collectionItems WHERE collectionID = c.collectionID) as item_count
            FROM collections c
            ORDER BY c.collectionName
        """
        return _query(sql)

    def get_collection_items(self, collection_name: str) -> list[dict]:
        """List items belonging to a collection (by name, case-insensitive)."""
        sql = """
            SELECT items.itemID, items.key, itemTypes.typeName,
                   (SELECT idv.value FROM itemData id
                      JOIN itemDataValues idv ON id.valueID = idv.valueID
                      JOIN fields f ON id.fieldID = f.fieldID
                      WHERE id.itemID = items.itemID AND f.fieldName = 'title') AS title
            FROM collectionItems ci
            JOIN items ON ci.itemID = items.itemID
            JOIN itemTypes ON items.itemTypeID = itemTypes.itemTypeID
            JOIN collections c ON ci.collectionID = c.collectionID
            WHERE LOWER(c.collectionName) = LOWER(?)
              AND items.itemID NOT IN (SELECT itemID FROM deletedItems)
        """
        return _query(sql, (collection_name,))

    def check_collection_exists(self, name: str) -> dict:
        """Check if a collection with the given name exists."""
        rows = _query(
            "SELECT collectionID, collectionName FROM collections WHERE LOWER(collectionName) = LOWER(?)",
            (name,),
        )
        if rows and "error" in rows[0]:
            return rows[0]
        return {"exists": len(rows) > 0, "matches": rows}

    def check_collection_item_count(self, name: str, expected: int) -> dict:
        rows = self.get_collection_items(name)
        if rows and "error" in rows[0]:
            return rows[0]
        return {
            "match": len(rows) == int(expected),
            "expected": int(expected),
            "actual": len(rows),
        }

    def check_collection_contains_item(self, collection_name: str, title_substring: str) -> dict:
        """Check whether a collection contains at least one item whose title
        contains the given substring (case-insensitive)."""
        rows = self.get_collection_items(collection_name)
        if rows and "error" in rows[0]:
            return rows[0]
        q = title_substring.lower()
        matches = [r for r in rows if q in (r.get("title") or "").lower()]
        return {
            "contains": len(matches) > 0,
            "match_count": len(matches),
            "matches": matches[:5],
        }

    def check_subcollection(self, parent_name: str, child_name: str) -> dict:
        """Check if child_name is a direct subcollection of parent_name."""
        rows = _query(
            """
            SELECT c.collectionID, c.collectionName
            FROM collections c
            JOIN collections p ON c.parentCollectionID = p.collectionID
            WHERE LOWER(p.collectionName) = LOWER(?) AND LOWER(c.collectionName) = LOWER(?)
            """,
            (parent_name, child_name),
        )
        if rows and "error" in rows[0]:
            return rows[0]
        return {"is_subcollection": len(rows) > 0, "matches": rows}

    # =========================================================================
    # Items / metadata
    # =========================================================================

    def get_items(self, limit: int = 50) -> list[dict]:
        """List regular (non-attachment, non-note, non-deleted) items with title."""
        sql = f"""
            SELECT items.itemID, items.key, itemTypes.typeName,
                   (SELECT idv.value FROM itemData id
                      JOIN itemDataValues idv ON id.valueID = idv.valueID
                      JOIN fields f ON id.fieldID = f.fieldID
                      WHERE id.itemID = items.itemID AND f.fieldName = 'title') AS title,
                   items.dateAdded, items.dateModified
            FROM items
            JOIN itemTypes ON items.itemTypeID = itemTypes.itemTypeID
            WHERE {EXCLUDE_NON_REGULAR} AND {NOT_DELETED}
            ORDER BY items.dateAdded DESC
            LIMIT ?
        """
        return _query(sql, (int(limit),))

    def get_item_fields(self, title_substring: str) -> dict:
        """Return all fields for the first item whose title contains the substring."""
        items_rows = self.get_items(limit=500)
        if items_rows and "error" in items_rows[0]:
            return items_rows[0]
        q = title_substring.lower()
        match = None
        for r in items_rows:
            if q in (r.get("title") or "").lower():
                match = r
                break
        if not match:
            return {"error": f"No item matching '{title_substring}'"}

        rows = _query(
            """
            SELECT f.fieldName, idv.value
            FROM itemData id
            JOIN fields f ON id.fieldID = f.fieldID
            JOIN itemDataValues idv ON id.valueID = idv.valueID
            WHERE id.itemID = ?
            """,
            (match["itemID"],),
        )
        if rows and "error" in rows[0]:
            return rows[0]
        fields = {r["fieldName"]: r["value"] for r in rows}
        return {
            "itemID": match["itemID"],
            "key": match["key"],
            "typeName": match["typeName"],
            "title": match.get("title"),
            "fields": fields,
        }

    def check_item_exists(self, title_substring: str) -> dict:
        rows = self.get_items(limit=1000)
        if rows and "error" in rows[0]:
            return rows[0]
        q = title_substring.lower()
        matches = [r for r in rows if q in (r.get("title") or "").lower()]
        return {
            "exists": len(matches) > 0,
            "match_count": len(matches),
            "matches": [{"title": m["title"], "typeName": m["typeName"], "key": m["key"]} for m in matches[:5]],
        }

    def check_item_field(self, title_substring: str, field: str, expected: str) -> dict:
        """Check whether an item's specific metadata field equals expected (case-insensitive)."""
        info = self.get_item_fields(title_substring)
        if "error" in info:
            return info
        actual = info.get("fields", {}).get(field)
        match = (str(actual or "").lower() == str(expected).lower())
        return {
            "match": match,
            "title": info.get("title"),
            "field": field,
            "expected": expected,
            "actual": actual,
        }

    def check_item_type(self, title_substring: str, expected_type: str) -> dict:
        info = self.get_item_fields(title_substring)
        if "error" in info:
            return info
        actual = info.get("typeName")
        return {
            "match": str(actual or "").lower() == str(expected_type).lower(),
            "title": info.get("title"),
            "expected": expected_type,
            "actual": actual,
        }

    def get_item_count(self) -> dict:
        """Return the total number of regular (non-deleted) items."""
        rows = _query(
            f"SELECT COUNT(*) c FROM items WHERE {EXCLUDE_NON_REGULAR} AND {NOT_DELETED}"
        )
        if rows and "error" in rows[0]:
            return rows[0]
        return {"count": rows[0]["c"] if rows else 0}

    def check_item_count(self, expected: int) -> dict:
        res = self.get_item_count()
        if "error" in res:
            return res
        return {"match": res["count"] == int(expected), "expected": int(expected), "actual": res["count"]}

    # =========================================================================
    # Creators / authors
    # =========================================================================

    def get_item_creators(self, title_substring: str) -> list[dict]:
        """Return creators (authors etc.) for an item matched by title substring."""
        items_rows = self.get_items(limit=1000)
        if items_rows and "error" in items_rows[0]:
            return [items_rows[0]]
        q = title_substring.lower()
        match = None
        for r in items_rows:
            if q in (r.get("title") or "").lower():
                match = r
                break
        if not match:
            return [{"error": f"No item matching '{title_substring}'"}]

        return _query(
            """
            SELECT c.firstName, c.lastName, ct.creatorType, ic.orderIndex
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
            """,
            (match["itemID"],),
        )

    def check_item_has_creator(self, title_substring: str, last_name: str) -> dict:
        creators = self.get_item_creators(title_substring)
        if creators and "error" in creators[0]:
            return creators[0]
        q = last_name.lower()
        matches = [c for c in creators if q == (c.get("lastName") or "").lower()]
        return {
            "has_creator": len(matches) > 0,
            "match_count": len(matches),
            "creators": creators,
        }

    def check_item_creator_count(self, title_substring: str, expected: int) -> dict:
        creators = self.get_item_creators(title_substring)
        if creators and "error" in creators[0]:
            return creators[0]
        return {
            "match": len(creators) == int(expected),
            "expected": int(expected),
            "actual": len(creators),
        }

    # =========================================================================
    # Tags
    # =========================================================================

    def get_tags(self) -> list[dict]:
        return _query(
            """
            SELECT t.tagID, t.name,
                   (SELECT COUNT(*) FROM itemTags WHERE tagID = t.tagID) as item_count
            FROM tags t
            ORDER BY t.name
            """
        )

    def check_tag_exists(self, name: str) -> dict:
        rows = _query("SELECT tagID, name FROM tags WHERE LOWER(name) = LOWER(?)", (name,))
        if rows and "error" in rows[0]:
            return rows[0]
        return {"exists": len(rows) > 0, "matches": rows}

    def get_item_tags(self, title_substring: str) -> list[dict]:
        items_rows = self.get_items(limit=1000)
        if items_rows and "error" in items_rows[0]:
            return [items_rows[0]]
        q = title_substring.lower()
        match = None
        for r in items_rows:
            if q in (r.get("title") or "").lower():
                match = r
                break
        if not match:
            return [{"error": f"No item matching '{title_substring}'"}]
        return _query(
            """
            SELECT t.name, it.type
            FROM itemTags it
            JOIN tags t ON it.tagID = t.tagID
            WHERE it.itemID = ?
            ORDER BY t.name
            """,
            (match["itemID"],),
        )

    def check_item_has_tag(self, title_substring: str, tag_name: str) -> dict:
        tags = self.get_item_tags(title_substring)
        if tags and "error" in tags[0]:
            return tags[0]
        q = tag_name.lower()
        matches = [t for t in tags if q == (t.get("name") or "").lower()]
        return {
            "has_tag": len(matches) > 0,
            "tag_count": len(tags),
            "all_tags": [t.get("name") for t in tags],
        }

    # =========================================================================
    # Attachments / storage
    # =========================================================================

    def get_attachments(self, limit: int = 100) -> list[dict]:
        """List attachment items (with parent item title if any)."""
        sql = """
            SELECT att.itemID, att.parentItemID, att.linkMode, att.contentType, att.path,
                   parent_items.key AS parent_key,
                   (SELECT idv.value FROM itemData id
                      JOIN itemDataValues idv ON id.valueID = idv.valueID
                      JOIN fields f ON id.fieldID = f.fieldID
                      WHERE id.itemID = parent_items.itemID AND f.fieldName = 'title') AS parent_title,
                   items.key AS att_key
            FROM itemAttachments att
            JOIN items ON att.itemID = items.itemID
            LEFT JOIN items parent_items ON att.parentItemID = parent_items.itemID
            WHERE items.itemID NOT IN (SELECT itemID FROM deletedItems)
            ORDER BY att.itemID DESC
            LIMIT ?
        """
        return _query(sql, (int(limit),))

    def check_item_has_attachment(self, title_substring: str) -> dict:
        """Check whether an item (matched by title) has at least one attachment."""
        items_rows = self.get_items(limit=1000)
        if items_rows and "error" in items_rows[0]:
            return items_rows[0]
        q = title_substring.lower()
        match = None
        for r in items_rows:
            if q in (r.get("title") or "").lower():
                match = r
                break
        if not match:
            return {"error": f"No item matching '{title_substring}'"}
        rows = _query(
            "SELECT COUNT(*) c FROM itemAttachments WHERE parentItemID = ? "
            "AND itemID NOT IN (SELECT itemID FROM deletedItems)",
            (match["itemID"],),
        )
        if rows and "error" in rows[0]:
            return rows[0]
        count = rows[0]["c"] if rows else 0
        return {"has_attachment": count > 0, "count": count, "itemID": match["itemID"]}

    def check_attachment_file_exists(self, attachment_key: str) -> dict:
        """Given an attachment item key, check whether its file exists under storage/."""
        data = _find_data_dir()
        if not data:
            return {"error": "Data dir not found"}
        storage = data / "storage" / attachment_key
        if not storage.exists():
            return {"exists": False, "path": str(storage)}
        files = [f for f in storage.iterdir() if f.is_file()]
        return {
            "exists": len(files) > 0,
            "path": str(storage),
            "files": [f.name for f in files],
            "file_count": len(files),
        }

    # =========================================================================
    # Notes
    # =========================================================================

    def get_notes(self, limit: int = 100) -> list[dict]:
        sql = """
            SELECT items.itemID, items.key, n.parentItemID, n.title, n.note,
                   (SELECT idv.value FROM itemData id
                      JOIN itemDataValues idv ON id.valueID = idv.valueID
                      JOIN fields f ON id.fieldID = f.fieldID
                      WHERE id.itemID = n.parentItemID AND f.fieldName = 'title') AS parent_title
            FROM itemNotes n
            JOIN items ON n.itemID = items.itemID
            WHERE items.itemID NOT IN (SELECT itemID FROM deletedItems)
            LIMIT ?
        """
        return _query(sql, (int(limit),))

    def check_note_contains(self, text: str) -> dict:
        """Check whether any note body contains the given text."""
        notes = self.get_notes(limit=500)
        if notes and "error" in notes[0]:
            return notes[0]
        q = text.lower()
        matches = []
        for n in notes:
            body = (n.get("note") or "")
            # Strip HTML tags from note body for matching
            plain = re.sub(r"<[^>]+>", " ", body)
            if q in plain.lower():
                matches.append({
                    "itemID": n.get("itemID"),
                    "parent_title": n.get("parent_title"),
                    "snippet": plain.strip()[:200],
                })
        return {"contains": len(matches) > 0, "match_count": len(matches), "matches": matches[:5]}

    def check_item_has_note(self, title_substring: str) -> dict:
        """Whether an item has any child note."""
        items_rows = self.get_items(limit=1000)
        if items_rows and "error" in items_rows[0]:
            return items_rows[0]
        q = title_substring.lower()
        match = None
        for r in items_rows:
            if q in (r.get("title") or "").lower():
                match = r
                break
        if not match:
            return {"error": f"No item matching '{title_substring}'"}
        rows = _query(
            "SELECT COUNT(*) c FROM itemNotes WHERE parentItemID = ? "
            "AND itemID NOT IN (SELECT itemID FROM deletedItems)",
            (match["itemID"],),
        )
        if rows and "error" in rows[0]:
            return rows[0]
        return {"has_note": rows[0]["c"] > 0 if rows else False, "count": rows[0]["c"] if rows else 0}

    # =========================================================================
    # Trash / deleted items
    # =========================================================================

    def get_trash(self, limit: int = 100) -> list[dict]:
        sql = """
            SELECT items.itemID, items.key, itemTypes.typeName,
                   (SELECT idv.value FROM itemData id
                      JOIN itemDataValues idv ON id.valueID = idv.valueID
                      JOIN fields f ON id.fieldID = f.fieldID
                      WHERE id.itemID = items.itemID AND f.fieldName = 'title') AS title,
                   d.dateDeleted
            FROM deletedItems d
            JOIN items ON d.itemID = items.itemID
            JOIN itemTypes ON items.itemTypeID = itemTypes.itemTypeID
            ORDER BY d.dateDeleted DESC
            LIMIT ?
        """
        return _query(sql, (int(limit),))

    def check_item_in_trash(self, title_substring: str) -> dict:
        rows = self.get_trash(limit=500)
        if rows and "error" in rows[0]:
            return rows[0]
        q = title_substring.lower()
        matches = [r for r in rows if q in (r.get("title") or "").lower()]
        return {
            "in_trash": len(matches) > 0,
            "match_count": len(matches),
            "matches": matches[:5],
        }

    # =========================================================================
    # Preferences (prefs.js)
    # =========================================================================

    def get_preferences(self, key: str | None = None) -> Any:
        prefs = _parse_prefs()
        if not prefs:
            return {"error": "prefs.js not found or empty"}
        if key is None:
            zotero_keys = [k for k in prefs if k.startswith("extensions.zotero")]
            return {"total_prefs": len(prefs), "zotero_pref_count": len(zotero_keys),
                    "keys_sample": zotero_keys[:20]}
        if key in prefs:
            return {"key": key, "value": prefs[key]}
        return {"error": f"Preference '{key}' not found"}

    def get_preferences_matching(self, pattern: str) -> dict:
        prefs = _parse_prefs()
        if not prefs:
            return {"error": "prefs.js not found or empty"}
        p = pattern.lower()
        matches = {k: v for k, v in prefs.items() if p in k.lower()}
        return {"pattern": pattern, "count": len(matches), "matches": matches}

    def check_preference_value(self, key: str, expected: str) -> dict:
        result = self.get_preferences(key)
        if isinstance(result, dict) and "error" in result:
            return result
        actual = result.get("value")
        # String-insensitive comparison, but also accept bool/int
        actual_str = str(actual)
        match = actual_str.lower() == str(expected).lower()
        return {"match": match, "key": key, "expected": expected, "actual": actual}

    # =========================================================================
    # Exports (BibTeX, RIS, JSON)
    # =========================================================================

    def parse_bibtex(self, file_path: str) -> dict:
        """Parse a BibTeX export file into entries with their fields."""
        p = Path(file_path)
        if not p.exists():
            return {"error": f"File not found: {file_path}"}
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"error": f"Read error: {e}"}

        entries = []
        # Match @type{key, field = {value}, ...}
        for m in re.finditer(r"@(\w+)\s*\{\s*([^,]+),", text):
            entry_type = m.group(1).strip().lower()
            entry_key = m.group(2).strip()
            # Extract fields of this entry by scanning from m.end() to the matching closing brace
            start = m.end()
            depth = 1
            i = start
            while i < len(text) and depth > 0:
                c = text[i]
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                if depth == 0:
                    break
                i += 1
            body = text[start:i]

            fields: dict[str, str] = {}
            for fm in re.finditer(r"(\w+)\s*=\s*[{\"](.+?)[}\"]\s*[,}]", body, flags=re.DOTALL):
                fname = fm.group(1).strip().lower()
                fval = fm.group(2).strip()
                # collapse whitespace
                fval = re.sub(r"\s+", " ", fval)
                fields[fname] = fval
            entries.append({"type": entry_type, "key": entry_key, "fields": fields})

        return {"count": len(entries), "entries": entries, "path": str(p)}

    def check_bibtex_entry_count(self, file_path: str, expected: int) -> dict:
        res = self.parse_bibtex(file_path)
        if "error" in res:
            return res
        return {
            "match": res["count"] == int(expected),
            "expected": int(expected),
            "actual": res["count"],
        }

    def check_bibtex_contains_title(self, file_path: str, title_substring: str) -> dict:
        res = self.parse_bibtex(file_path)
        if "error" in res:
            return res
        q = title_substring.lower()
        matches = [e for e in res["entries"] if q in (e.get("fields", {}).get("title") or "").lower()]
        return {
            "contains": len(matches) > 0,
            "match_count": len(matches),
            "entries": [{"key": m["key"], "type": m["type"], "title": m["fields"].get("title")} for m in matches[:5]],
        }

    # =========================================================================
    # File I/O
    # =========================================================================

    def check_file_exists(self, file_path: str) -> dict:
        p = Path(file_path)
        if p.exists():
            stat = p.stat()
            return {
                "exists": True,
                "path": str(p),
                "size_bytes": stat.st_size,
                "is_file": p.is_file(),
                "is_dir": p.is_dir(),
            }
        return {"exists": False, "path": str(p)}


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------

COMMANDS: dict[str, tuple[str, Any]] = {
    # Library / profile
    "data-dir": ("Show Zotero data dir info", lambda v, a: v.get_data_dir()),
    "library-stats": ("Top-level counts", lambda v, a: v.get_library_stats()),

    # Collections
    "collections": ("List all collections", lambda v, a: v.get_collections()),
    "collection-items": ("List items in a collection", lambda v, a: v.get_collection_items(a[0])),
    "check-collection-exists": ("Check collection exists", lambda v, a: v.check_collection_exists(a[0])),
    "check-collection-count": ("Check collection item count", lambda v, a: v.check_collection_item_count(a[0], a[1])),
    "check-collection-contains": ("Check collection contains item", lambda v, a: v.check_collection_contains_item(a[0], a[1])),
    "check-subcollection": ("Check subcollection relation", lambda v, a: v.check_subcollection(a[0], a[1])),

    # Items
    "items": ("List regular items", lambda v, a: v.get_items(limit=int(a[0]) if a else 50)),
    "item-count": ("Count regular items", lambda v, a: v.get_item_count()),
    "item-fields": ("Show fields of an item", lambda v, a: v.get_item_fields(a[0])),
    "check-item-exists": ("Check item exists by title", lambda v, a: v.check_item_exists(a[0])),
    "check-item-field": ("Check item field value", lambda v, a: v.check_item_field(a[0], a[1], a[2])),
    "check-item-type": ("Check item type", lambda v, a: v.check_item_type(a[0], a[1])),
    "check-item-count": ("Check total item count", lambda v, a: v.check_item_count(a[0])),

    # Creators
    "item-creators": ("List creators for an item", lambda v, a: v.get_item_creators(a[0])),
    "check-item-creator": ("Check item has creator (last name)", lambda v, a: v.check_item_has_creator(a[0], a[1])),
    "check-item-creator-count": ("Check item creator count", lambda v, a: v.check_item_creator_count(a[0], a[1])),

    # Tags
    "tags": ("List all tags", lambda v, a: v.get_tags()),
    "check-tag-exists": ("Check tag exists", lambda v, a: v.check_tag_exists(a[0])),
    "item-tags": ("List tags on an item", lambda v, a: v.get_item_tags(a[0])),
    "check-item-tag": ("Check item has tag", lambda v, a: v.check_item_has_tag(a[0], a[1])),

    # Attachments
    "attachments": ("List attachments", lambda v, a: v.get_attachments(limit=int(a[0]) if a else 100)),
    "check-item-attachment": ("Check item has attachment", lambda v, a: v.check_item_has_attachment(a[0])),
    "check-attachment-file": ("Check attachment file exists", lambda v, a: v.check_attachment_file_exists(a[0])),

    # Notes
    "notes": ("List notes", lambda v, a: v.get_notes(limit=int(a[0]) if a else 100)),
    "check-note-contains": ("Check note body contains text", lambda v, a: v.check_note_contains(a[0])),
    "check-item-note": ("Check item has a note child", lambda v, a: v.check_item_has_note(a[0])),

    # Trash
    "trash": ("List trashed items", lambda v, a: v.get_trash(limit=int(a[0]) if a else 100)),
    "check-item-in-trash": ("Check item is in trash", lambda v, a: v.check_item_in_trash(a[0])),

    # Preferences
    "prefs": ("Read prefs.js (optionally by key)", lambda v, a: v.get_preferences(a[0] if a else None)),
    "prefs-matching": ("Get prefs matching a substring", lambda v, a: v.get_preferences_matching(a[0])),
    "check-pref-value": ("Check prefs key = expected", lambda v, a: v.check_preference_value(a[0], a[1])),

    # Exports / files
    "parse-bibtex": ("Parse a BibTeX file", lambda v, a: v.parse_bibtex(a[0])),
    "check-bibtex-count": ("Check BibTeX entry count", lambda v, a: v.check_bibtex_entry_count(a[0], a[1])),
    "check-bibtex-title": ("Check BibTeX contains title", lambda v, a: v.check_bibtex_contains_title(a[0], a[1])),
    "check-file-exists": ("Check file exists on disk", lambda v, a: v.check_file_exists(a[0])),
}


def _print_usage():
    print("Zotero Verifier — query Zotero state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print("\nData dir auto-detected at ~/Zotero/.")
    print("Override with ZOTERO_DATA_DIR env var.")
    print("Profile dir auto-detected at ~/.zotero/zotero/*.default/.")
    print("Override with ZOTERO_PROFILE_DIR env var.")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = ZoteroVerifier()
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


if __name__ == "__main__":
    main()
