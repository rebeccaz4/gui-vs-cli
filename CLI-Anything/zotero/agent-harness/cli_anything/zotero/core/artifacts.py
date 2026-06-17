from __future__ import annotations

import json
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cli_anything.zotero.core.discovery import RuntimeContext
from cli_anything.zotero.utils import zotero_sqlite


DEFAULT_ITEM_TYPES = (
    "journalArticle",
    "book",
    "webpage",
    "conferencePaper",
    "thesis",
    "report",
    "document",
    "attachment",
    "note",
)
DEFAULT_CREATOR_TYPES = ("author", "editor", "contributor")
DEFAULT_FIELDS = (
    "title",
    "date",
    "DOI",
    "publicationTitle",
    "publisher",
    "abstractNote",
    "url",
    "pages",
    "volume",
    "issue",
    "place",
    "ISBN",
    "ISSN",
    "language",
    "edition",
    "shortTitle",
)
PDF_STUB = b"%PDF-1.4\n% cli-anything-zotero attachment\n"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _connect(sqlite_path: Path) -> sqlite3.Connection:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _insert(conn: sqlite3.Connection, table: str, values: dict[str, Any]) -> None:
    table_columns = _columns(conn, table)
    filtered = {key: value for key, value in values.items() if key in table_columns}
    if not filtered:
        return
    names = list(filtered)
    placeholders = ", ".join("?" for _ in names)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(names)}) VALUES ({placeholders})",
        [filtered[name] for name in names],
    )


def _insert_or_replace(conn: sqlite3.Connection, table: str, values: dict[str, Any]) -> None:
    table_columns = _columns(conn, table)
    filtered = {key: value for key, value in values.items() if key in table_columns}
    if not filtered:
        return
    names = list(filtered)
    placeholders = ", ".join("?" for _ in names)
    conn.execute(
        f"INSERT OR REPLACE INTO {table} ({', '.join(names)}) VALUES ({placeholders})",
        [filtered[name] for name in names],
    )


def _next_id(conn: sqlite3.Connection, table: str, column: str) -> int:
    row = conn.execute(f"SELECT COALESCE(MAX({column}), 0) + 1 AS next_id FROM {table}").fetchone()
    return int(row["next_id"]) if row else 1


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS libraries (
            libraryID INTEGER PRIMARY KEY,
            type TEXT,
            editable INTEGER,
            filesEditable INTEGER,
            version INTEGER DEFAULT 0,
            storageVersion INTEGER DEFAULT 0,
            lastSync INTEGER DEFAULT 0,
            archived INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS itemTypes (
            itemTypeID INTEGER PRIMARY KEY,
            typeName TEXT NOT NULL,
            templateItemTypeID INTEGER,
            display INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS creatorTypes (
            creatorTypeID INTEGER PRIMARY KEY,
            creatorType TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fields (
            fieldID INTEGER PRIMARY KEY,
            fieldName TEXT NOT NULL,
            fieldFormatID INTEGER
        );
        CREATE TABLE IF NOT EXISTS itemDataValues (
            valueID INTEGER PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS items (
            itemID INTEGER PRIMARY KEY,
            itemTypeID INTEGER NOT NULL,
            dateAdded TEXT,
            dateModified TEXT,
            clientDateModified TEXT,
            libraryID INTEGER NOT NULL DEFAULT 1,
            key TEXT NOT NULL,
            version INTEGER DEFAULT 0,
            synced INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS itemData (
            itemID INTEGER,
            fieldID INTEGER,
            valueID INTEGER
        );
        CREATE TABLE IF NOT EXISTS creators (
            creatorID INTEGER PRIMARY KEY,
            firstName TEXT,
            lastName TEXT,
            fieldMode INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS itemCreators (
            itemID INTEGER NOT NULL,
            creatorID INTEGER NOT NULL,
            creatorTypeID INTEGER NOT NULL,
            orderIndex INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS collections (
            collectionID INTEGER PRIMARY KEY,
            collectionName TEXT NOT NULL,
            parentCollectionID INTEGER,
            clientDateModified TEXT,
            libraryID INTEGER NOT NULL DEFAULT 1,
            key TEXT NOT NULL,
            version INTEGER DEFAULT 0,
            synced INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS collectionItems (
            collectionID INTEGER NOT NULL,
            itemID INTEGER NOT NULL,
            orderIndex INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS tags (
            tagID INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS itemTags (
            itemID INTEGER NOT NULL,
            tagID INTEGER NOT NULL,
            type INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS itemAttachments (
            itemID INTEGER PRIMARY KEY,
            parentItemID INTEGER,
            linkMode INTEGER,
            contentType TEXT,
            charsetID INTEGER,
            path TEXT,
            syncState INTEGER DEFAULT 0,
            storageModTime INTEGER,
            storageHash TEXT,
            lastProcessedModificationTime INTEGER
        );
        CREATE TABLE IF NOT EXISTS itemNotes (
            itemID INTEGER PRIMARY KEY,
            parentItemID INTEGER,
            note TEXT,
            title TEXT
        );
        CREATE TABLE IF NOT EXISTS itemAnnotations (
            itemID INTEGER PRIMARY KEY,
            parentItemID INTEGER,
            type INTEGER,
            authorName TEXT,
            text TEXT,
            comment TEXT,
            color TEXT,
            pageLabel TEXT,
            sortIndex TEXT,
            position TEXT,
            isExternal INTEGER
        );
        CREATE TABLE IF NOT EXISTS deletedItems (
            itemID INTEGER PRIMARY KEY,
            dateDeleted TEXT
        );
        """
    )
    if conn.execute("SELECT 1 FROM libraries WHERE libraryID = 1").fetchone() is None:
        _insert(
            conn,
            "libraries",
            {
                "libraryID": 1,
                "type": "user",
                "editable": 1,
                "filesEditable": 1,
                "version": 0,
                "storageVersion": 0,
                "lastSync": 0,
                "archived": 0,
            },
        )
    for type_name in DEFAULT_ITEM_TYPES:
        _item_type_id(conn, type_name)
    for creator_type in DEFAULT_CREATOR_TYPES:
        _creator_type_id(conn, creator_type)
    for field_name in DEFAULT_FIELDS:
        _field_id(conn, field_name)


def _clear_verifier_tables(conn: sqlite3.Connection) -> None:
    for table in (
        "deletedItems",
        "collectionItems",
        "itemTags",
        "itemCreators",
        "itemData",
        "itemDataValues",
        "itemAttachments",
        "itemNotes",
        "items",
        "collections",
        "tags",
        "creators",
    ):
        conn.execute(f"DELETE FROM {table}")


def _item_type_id(conn: sqlite3.Connection, type_name: str) -> int:
    row = conn.execute("SELECT itemTypeID FROM itemTypes WHERE typeName = ?", (type_name,)).fetchone()
    if row:
        return int(row["itemTypeID"])
    item_type_id = _next_id(conn, "itemTypes", "itemTypeID")
    _insert(conn, "itemTypes", {"itemTypeID": item_type_id, "typeName": type_name, "display": 1})
    return item_type_id


def _creator_type_id(conn: sqlite3.Connection, creator_type: str) -> int:
    row = conn.execute("SELECT creatorTypeID FROM creatorTypes WHERE creatorType = ?", (creator_type,)).fetchone()
    if row:
        return int(row["creatorTypeID"])
    creator_type_id = _next_id(conn, "creatorTypes", "creatorTypeID")
    _insert(conn, "creatorTypes", {"creatorTypeID": creator_type_id, "creatorType": creator_type})
    return creator_type_id


def _field_id(conn: sqlite3.Connection, field_name: str) -> int:
    row = conn.execute("SELECT fieldID FROM fields WHERE fieldName = ?", (field_name,)).fetchone()
    if row:
        return int(row["fieldID"])
    field_id = _next_id(conn, "fields", "fieldID")
    _insert(conn, "fields", {"fieldID": field_id, "fieldName": field_name, "fieldFormatID": 0})
    return field_id


def _value_id(conn: sqlite3.Connection, value: Any) -> int:
    value_text = "" if value is None else str(value)
    row = conn.execute("SELECT valueID FROM itemDataValues WHERE value = ?", (value_text,)).fetchone()
    if row:
        return int(row["valueID"])
    value_id = _next_id(conn, "itemDataValues", "valueID")
    _insert(conn, "itemDataValues", {"valueID": value_id, "value": value_text})
    return value_id


def _set_item_field(conn: sqlite3.Connection, item_id: int, field_name: str, value: Any) -> None:
    field_id = _field_id(conn, field_name)
    value_id = _value_id(conn, value)
    conn.execute("DELETE FROM itemData WHERE itemID = ? AND fieldID = ?", (item_id, field_id))
    _insert(conn, "itemData", {"itemID": item_id, "fieldID": field_id, "valueID": value_id})


def _collection_by_ref(conn: sqlite3.Connection, ref: Any, library_id: int = 1) -> sqlite3.Row | None:
    if ref is None:
        return None
    text = str(ref)
    if text.isdigit():
        return conn.execute("SELECT * FROM collections WHERE collectionID = ?", (int(text),)).fetchone()
    return conn.execute(
        "SELECT * FROM collections WHERE libraryID = ? AND (key = ? OR collectionName = ?)",
        (library_id, text, text),
    ).fetchone()


def _item_by_ref(conn: sqlite3.Connection, ref: Any, library_id: int = 1) -> sqlite3.Row | None:
    if ref is None:
        return None
    text = str(ref)
    if text.isdigit():
        return conn.execute("SELECT * FROM items WHERE itemID = ?", (int(text),)).fetchone()
    return conn.execute(
        "SELECT * FROM items WHERE libraryID = ? AND key = ?",
        (library_id, text),
    ).fetchone()


def _ensure_collection(conn: sqlite3.Connection, raw: dict[str, Any], library_id: int = 1) -> dict[str, Any]:
    name = str(raw.get("name") or raw.get("collectionName") or "").strip()
    if not name:
        raise RuntimeError("Collection name is required")
    library_id = int(raw.get("libraryID", library_id))
    existing = _collection_by_ref(conn, raw.get("key") or name, library_id)
    parent = _collection_by_ref(conn, raw.get("parent") or raw.get("parentCollection"), library_id)
    parent_id = int(parent["collectionID"]) if parent else raw.get("parentCollectionID")
    if existing:
        collection_id = int(existing["collectionID"])
        conn.execute(
            "UPDATE collections SET collectionName = ?, parentCollectionID = ?, libraryID = ? WHERE collectionID = ?",
            (name, parent_id, library_id, collection_id),
        )
        key = existing["key"]
    else:
        collection_id = int(raw.get("collectionID") or _next_id(conn, "collections", "collectionID"))
        key = str(raw.get("key") or zotero_sqlite.generate_object_key())
        _insert(
            conn,
            "collections",
            {
                "collectionID": collection_id,
                "collectionName": name,
                "parentCollectionID": parent_id,
                "clientDateModified": _timestamp(),
                "libraryID": library_id,
                "key": key,
                "version": 0,
                "synced": 0,
            },
        )
    return {"collectionID": collection_id, "collectionName": name, "key": key, "libraryID": library_id}


def _ensure_creator(conn: sqlite3.Connection, raw: dict[str, Any]) -> int:
    first_name = str(raw.get("firstName") or raw.get("first") or "").strip()
    last_name = str(raw.get("lastName") or raw.get("last") or raw.get("name") or "").strip()
    row = conn.execute(
        "SELECT creatorID FROM creators WHERE firstName = ? AND lastName = ?",
        (first_name, last_name),
    ).fetchone()
    if row:
        return int(row["creatorID"])
    creator_id = _next_id(conn, "creators", "creatorID")
    _insert(conn, "creators", {"creatorID": creator_id, "firstName": first_name, "lastName": last_name, "fieldMode": 0})
    return creator_id


def _ensure_tag(conn: sqlite3.Connection, name: str) -> int:
    name = name.strip()
    if not name:
        raise RuntimeError("Tag name must not be empty")
    row = conn.execute("SELECT tagID FROM tags WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row["tagID"])
    tag_id = _next_id(conn, "tags", "tagID")
    _insert(conn, "tags", {"tagID": tag_id, "name": name})
    return tag_id


def _safe_filename(path: str | None, fallback: str) -> str:
    name = Path(path or fallback).name or fallback
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or fallback
    if "." not in name:
        name += ".pdf"
    return name


def _write_attachment_file(data_dir: Path, attachment_key: str, raw: dict[str, Any]) -> str:
    source = raw.get("path") or raw.get("source")
    filename = _safe_filename(str(source) if source else raw.get("filename"), "attachment.pdf")
    storage_dir = data_dir / "storage" / attachment_key
    storage_dir.mkdir(parents=True, exist_ok=True)
    target = storage_dir / filename
    if source:
        shutil.copy2(Path(str(source)).expanduser(), target)
    else:
        content = raw.get("content")
        if isinstance(content, str):
            target.write_bytes(content.encode("utf-8"))
        else:
            target.write_bytes(PDF_STUB)
    return filename


def _ensure_item(conn: sqlite3.Connection, raw: dict[str, Any], *, data_dir: Path, library_id: int = 1) -> dict[str, Any]:
    library_id = int(raw.get("libraryID", library_id))
    key = str(raw.get("key") or zotero_sqlite.generate_object_key())
    item_type = str(raw.get("type") or raw.get("itemType") or "journalArticle")
    fields = dict(raw.get("fields") or {})
    title = raw.get("title")
    if title is not None:
        fields["title"] = title

    existing = _item_by_ref(conn, key, library_id)
    if existing:
        item_id = int(existing["itemID"])
        conn.execute(
            "UPDATE items SET itemTypeID = ?, dateModified = ?, clientDateModified = ?, libraryID = ? WHERE itemID = ?",
            (_item_type_id(conn, item_type), _timestamp(), _timestamp(), library_id, item_id),
        )
        conn.execute("DELETE FROM itemCreators WHERE itemID = ?", (item_id,))
        conn.execute("DELETE FROM itemTags WHERE itemID = ?", (item_id,))
        conn.execute("DELETE FROM collectionItems WHERE itemID = ?", (item_id,))
    else:
        item_id = int(raw.get("itemID") or _next_id(conn, "items", "itemID"))
        _insert(
            conn,
            "items",
            {
                "itemID": item_id,
                "itemTypeID": _item_type_id(conn, item_type),
                "dateAdded": _timestamp(),
                "dateModified": _timestamp(),
                "clientDateModified": _timestamp(),
                "libraryID": library_id,
                "key": key,
                "version": 0,
                "synced": 0,
            },
        )

    for field_name, value in fields.items():
        if value is not None:
            _set_item_field(conn, item_id, str(field_name), value)

    for order_index, creator in enumerate(raw.get("creators") or []):
        creator_id = _ensure_creator(conn, creator)
        creator_type = str(creator.get("creatorType") or creator.get("type") or "author")
        _insert(
            conn,
            "itemCreators",
            {
                "itemID": item_id,
                "creatorID": creator_id,
                "creatorTypeID": _creator_type_id(conn, creator_type),
                "orderIndex": order_index,
            },
        )

    for tag_name in raw.get("tags") or []:
        tag_id = _ensure_tag(conn, str(tag_name))
        _insert_or_replace(conn, "itemTags", {"itemID": item_id, "tagID": tag_id, "type": 0})

    for collection_ref in raw.get("collections") or []:
        collection = _collection_by_ref(conn, collection_ref, library_id)
        if collection is None:
            collection = _ensure_collection(conn, {"name": str(collection_ref), "libraryID": library_id}, library_id)
            collection_id = int(collection["collectionID"])
        else:
            collection_id = int(collection["collectionID"])
        order_row = conn.execute(
            "SELECT COALESCE(MAX(orderIndex), -1) + 1 AS next_order FROM collectionItems WHERE collectionID = ?",
            (collection_id,),
        ).fetchone()
        _insert_or_replace(
            conn,
            "collectionItems",
            {"collectionID": collection_id, "itemID": item_id, "orderIndex": int(order_row["next_order"]) if order_row else 0},
        )

    if raw.get("deleted") or raw.get("trash"):
        _insert_or_replace(conn, "deletedItems", {"itemID": item_id, "dateDeleted": _timestamp()})
    else:
        conn.execute("DELETE FROM deletedItems WHERE itemID = ?", (item_id,))

    for note in raw.get("notes") or []:
        _ensure_note(conn, note, parent_item_id=item_id, library_id=library_id)
    for attachment in raw.get("attachments") or []:
        _ensure_attachment(conn, attachment, parent_item_id=item_id, library_id=library_id, data_dir=data_dir)

    return {"itemID": item_id, "key": key, "title": fields.get("title"), "typeName": item_type}


def _ensure_note(conn: sqlite3.Connection, raw: dict[str, Any] | str, *, parent_item_id: int, library_id: int) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = {"text": raw}
    note_html = str(raw.get("html") or raw.get("note") or f"<p>{raw.get('text', '')}</p>")
    title = str(raw.get("title") or "Note")
    key = str(raw.get("key") or zotero_sqlite.generate_object_key())
    existing = _item_by_ref(conn, key, library_id)
    item_id = int(existing["itemID"]) if existing else int(raw.get("itemID") or _next_id(conn, "items", "itemID"))
    if not existing:
        _insert(
            conn,
            "items",
            {
                "itemID": item_id,
                "itemTypeID": _item_type_id(conn, "note"),
                "dateAdded": _timestamp(),
                "dateModified": _timestamp(),
                "clientDateModified": _timestamp(),
                "libraryID": library_id,
                "key": key,
                "version": 0,
                "synced": 0,
            },
        )
    _insert_or_replace(conn, "itemNotes", {"itemID": item_id, "parentItemID": parent_item_id, "note": note_html, "title": title})
    return {"itemID": item_id, "key": key, "parentItemID": parent_item_id}


def _ensure_attachment(
    conn: sqlite3.Connection,
    raw: dict[str, Any],
    *,
    parent_item_id: int,
    library_id: int,
    data_dir: Path,
) -> dict[str, Any]:
    key = str(raw.get("key") or zotero_sqlite.generate_object_key())
    existing = _item_by_ref(conn, key, library_id)
    item_id = int(existing["itemID"]) if existing else int(raw.get("itemID") or _next_id(conn, "items", "itemID"))
    filename = _write_attachment_file(data_dir, key, raw)
    if not existing:
        _insert(
            conn,
            "items",
            {
                "itemID": item_id,
                "itemTypeID": _item_type_id(conn, "attachment"),
                "dateAdded": _timestamp(),
                "dateModified": _timestamp(),
                "clientDateModified": _timestamp(),
                "libraryID": library_id,
                "key": key,
                "version": 0,
                "synced": 0,
            },
        )
    if raw.get("title"):
        _set_item_field(conn, item_id, "title", raw["title"])
    _insert_or_replace(
        conn,
        "itemAttachments",
        {
            "itemID": item_id,
            "parentItemID": parent_item_id,
            "linkMode": int(raw.get("linkMode", 1)),
            "contentType": raw.get("contentType") or "application/pdf",
            "charsetID": None,
            "path": f"storage:{filename}",
            "syncState": 0,
            "storageModTime": 0,
            "storageHash": "",
            "lastProcessedModificationTime": 0,
        },
    )
    return {"itemID": item_id, "key": key, "path": str(data_dir / "storage" / key / filename)}


def seed_from_json(runtime: RuntimeContext, path: str | Path, *, clear: bool = False) -> dict[str, Any]:
    spec_path = Path(path).expanduser()
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Zotero seed JSON must be an object")
    sqlite_path = runtime.environment.sqlite_path
    backup = zotero_sqlite.backup_database(sqlite_path) if sqlite_path.exists() else None
    data_dir = runtime.environment.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "storage").mkdir(exist_ok=True)

    with closing(_connect(sqlite_path)) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            _ensure_schema(conn)
            if clear or bool(payload.get("clear")):
                _clear_verifier_tables(conn)
                _ensure_schema(conn)
            for library in payload.get("libraries") or []:
                _insert_or_replace(
                    conn,
                    "libraries",
                    {
                        "libraryID": int(library.get("libraryID", 1)),
                        "type": library.get("type", "user"),
                        "editable": int(library.get("editable", 1)),
                        "filesEditable": int(library.get("filesEditable", 1)),
                        "version": int(library.get("version", 0)),
                        "storageVersion": int(library.get("storageVersion", 0)),
                        "lastSync": int(library.get("lastSync", 0)),
                        "archived": int(library.get("archived", 0)),
                    },
                )
            collections = [_ensure_collection(conn, raw) for raw in payload.get("collections") or []]
            items = [_ensure_item(conn, raw, data_dir=data_dir) for raw in payload.get("items") or []]
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "action": "library_seed_json",
        "path": str(spec_path),
        "sqlite_path": str(sqlite_path),
        "backupPath": str(backup) if backup else None,
        "collections": len(collections),
        "items": len(items),
        "clear": bool(clear or payload.get("clear")),
    }


def _encode_pref_value(value: str, value_type: str) -> str:
    value_type = value_type.lower()
    if value_type == "bool":
        return "true" if str(value).lower() in {"1", "true", "yes", "on"} else "false"
    if value_type == "int":
        return str(int(value))
    if value_type == "float":
        return str(float(value))
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def set_preference(runtime: RuntimeContext, key: str, value: str, *, value_type: str = "string") -> dict[str, Any]:
    profile_dir = runtime.environment.profile_dir
    if profile_dir is None:
        raise RuntimeError("Zotero profile directory could not be resolved")
    profile_dir.mkdir(parents=True, exist_ok=True)
    prefs_path = profile_dir / "prefs.js"
    existing = prefs_path.read_text(encoding="utf-8") if prefs_path.exists() else ""
    line = f'user_pref("{key}", {_encode_pref_value(value, value_type)});'
    pattern = re.compile(rf'^user_pref\("{re.escape(key)}",\s*.+?\);\s*$', re.MULTILINE)
    if pattern.search(existing):
        updated = pattern.sub(line, existing)
    else:
        updated = existing.rstrip()
        if updated:
            updated += "\n"
        updated += line + "\n"
    prefs_path.write_text(updated, encoding="utf-8")
    return {"action": "preference_set", "path": str(prefs_path), "key": key, "value": value, "type": value_type}


def _bibtex_escape(value: Any) -> str:
    return str(value or "").replace("{", "\\{").replace("}", "\\}")


def _bibtex_key(item: dict[str, Any]) -> str:
    title = str(item.get("title") or item.get("key") or "item")
    slug = re.sub(r"[^A-Za-z0-9]+", "", title.title()) or str(item.get("key") or "item")
    return f"{slug}{item.get('itemID')}"


def _is_deleted(sqlite_path: Path, item_id: int) -> bool:
    with closing(zotero_sqlite.connect_readonly(sqlite_path)) as conn:
        row = conn.execute("SELECT 1 FROM deletedItems WHERE itemID = ?", (int(item_id),)).fetchone()
    return row is not None


def export_bibtex(
    runtime: RuntimeContext,
    output_path: str | Path,
    *,
    collection: str | None = None,
    title: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    sqlite_path = runtime.environment.sqlite_path
    if not sqlite_path.exists():
        raise FileNotFoundError(f"Zotero SQLite database not found: {sqlite_path}")
    library_id = zotero_sqlite.default_library_id(sqlite_path)
    collection_id = None
    if collection:
        resolved = zotero_sqlite.resolve_collection(sqlite_path, collection, library_id=library_id)
        if not resolved:
            raise RuntimeError(f"Collection not found: {collection}")
        collection_id = int(resolved["collectionID"])
    if title:
        items = zotero_sqlite.find_items_by_title(sqlite_path, title, library_id=library_id, collection_id=collection_id, limit=limit or 100)
    else:
        items = zotero_sqlite.fetch_items(sqlite_path, library_id=library_id, collection_id=collection_id, limit=limit)
    entries = []
    for item in items:
        if _is_deleted(sqlite_path, int(item["itemID"])):
            continue
        full = zotero_sqlite.resolve_item(sqlite_path, item["key"], library_id=int(item["libraryID"]))
        if not full:
            continue
        fields = full.get("fields") or {}
        entry_type = "book" if full.get("typeName") == "book" else "article"
        lines = [f"@{entry_type}{{{_bibtex_key(full)},"]
        if full.get("title"):
            lines.append(f"  title = {{{_bibtex_escape(full['title'])}}},")
        if full.get("creators"):
            author = " and ".join(
                " ".join(part for part in (creator.get("firstName"), creator.get("lastName")) if part)
                for creator in full["creators"]
            )
            lines.append(f"  author = {{{_bibtex_escape(author)}}},")
        for source, target in (("date", "year"), ("DOI", "doi"), ("publicationTitle", "journal"), ("publisher", "publisher"), ("url", "url")):
            if fields.get(source):
                lines.append(f"  {target} = {{{_bibtex_escape(fields[source])}}},")
        if lines[-1].endswith(","):
            lines[-1] = lines[-1][:-1]
        lines.append("}")
        entries.append("\n".join(lines))
    output = Path(output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n\n".join(entries) + ("\n" if entries else ""), encoding="utf-8")
    return {"action": "export_bibtex", "path": str(output), "entry_count": len(entries)}
