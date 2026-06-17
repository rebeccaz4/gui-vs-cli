from __future__ import annotations

import textwrap
import time

from ..base import AppContext, AppSpec
from ..utils import build_command, check_process_ready, with_log_redirect

LEGACY_CHECK_SCRIPT = textwrap.dedent(
    """
    import os
    import sqlite3
    import sys

    path = os.path.expanduser("~/Zotero/zotero.sqlite")
    if not os.path.exists(path):
        print("missing")
        sys.exit(0)

    conn = sqlite3.connect(path)
    cur = conn.cursor()

    def has_table(name):
        row = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return bool(row)

    legacy = not has_table("version")
    if has_table("collections"):
        cols = {row[1] for row in cur.execute("PRAGMA table_info(collections)")}
        if "clientDateModified" not in cols:
            legacy = True

    if has_table("libraries"):
        cols = {row[1] for row in cur.execute("PRAGMA table_info(libraries)")}
        if "archived" not in cols:
            legacy = True

    print("legacy" if legacy else "compatible")
    """
).strip()


LEGACY_REPAIR_SCRIPT = textwrap.dedent(
    """
    import os
    import sqlite3
    import time

    LEGACY_DB = "/tmp/zotero-legacy/legacy.sqlite"
    FRESH_DB = os.path.expanduser("~/Zotero/zotero.sqlite")

    if not os.path.exists(LEGACY_DB):
        raise SystemExit("Missing legacy Zotero DB")
    if not os.path.exists(FRESH_DB):
        raise SystemExit("Missing fresh Zotero DB")

    legacy = sqlite3.connect(LEGACY_DB)
    fresh = sqlite3.connect(FRESH_DB)
    legacy.row_factory = sqlite3.Row
    fresh.row_factory = sqlite3.Row

    for conn in (legacy, fresh):
        conn.execute("PRAGMA foreign_keys=OFF")

    def has_table(conn, name):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return bool(row)

    def table_columns(conn, name):
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({name})")}

    def rows(conn, sql, params=()):
        return conn.execute(sql, params).fetchall()

    def update_existing_columns(conn, table, values, where_clause, where_params=()):
        existing = table_columns(conn, table)
        assignments = [(col, value) for col, value in values.items() if col in existing]
        if not assignments:
            return
        sql = (
            f"UPDATE {table} SET "
            + ", ".join(f"{col}=?" for col, _ in assignments)
            + f" WHERE {where_clause}"
        )
        params = [value for _, value in assignments] + list(where_params)
        conn.execute(sql, params)

    def clear_user_data(conn):
        for table in [
            "fulltextItemWords",
            "fulltextItems",
            "itemAnnotations",
            "itemRelations",
            "collectionRelations",
            "collectionItems",
            "itemCreators",
            "itemTags",
            "itemAttachments",
            "itemNotes",
            "itemData",
            "deletedItems",
            "itemDataValues",
            "tags",
            "collections",
            "creators",
            "items",
        ]:
            if has_table(conn, table):
                conn.execute(f"DELETE FROM {table}")

    clear_user_data(fresh)

    fresh_item_types = {
        row["typeName"]: row["itemTypeID"]
        for row in rows(fresh, "SELECT itemTypeID, typeName FROM itemTypes")
    }
    fresh_fields = {
        row["fieldName"]: row["fieldID"]
        for row in rows(fresh, "SELECT fieldID, fieldName FROM fields")
    }
    fresh_creator_types = {
        row["creatorType"]: row["creatorTypeID"]
        for row in rows(fresh, "SELECT creatorTypeID, creatorType FROM creatorTypes")
    }

    legacy_item_types = {
        row["itemTypeID"]: row["typeName"]
        for row in rows(legacy, "SELECT itemTypeID, typeName FROM itemTypes")
    }
    legacy_fields = {
        row["fieldID"]: row["fieldName"]
        for row in rows(legacy, "SELECT fieldID, fieldName FROM fields")
    }
    legacy_creator_types = {
        row["creatorTypeID"]: row["creatorType"]
        for row in rows(legacy, "SELECT creatorTypeID, creatorType FROM creatorTypes")
    }

    update_existing_columns(
        fresh,
        "libraries",
        {
            "editable": 1,
            "filesEditable": 1,
            "version": 0,
            "storageVersion": 0,
            "lastSync": 0,
            "archived": 0,
            "isAdmin": 0,
        },
        "libraryID=?",
        (1,),
    )

    if has_table(legacy, "creators"):
        for row in rows(
            legacy,
            "SELECT creatorID, firstName, lastName, fieldMode FROM creators ORDER BY creatorID",
        ):
            fresh.execute(
                "INSERT INTO creators (creatorID, firstName, lastName, fieldMode) VALUES (?, ?, ?, ?)",
                (row["creatorID"], row["firstName"], row["lastName"], row["fieldMode"]),
            )

    if has_table(legacy, "itemDataValues"):
        for row in rows(
            legacy,
            "SELECT valueID, value FROM itemDataValues ORDER BY valueID",
        ):
            fresh.execute(
                "INSERT INTO itemDataValues (valueID, value) VALUES (?, ?)",
                (row["valueID"], row["value"]),
            )

    if has_table(legacy, "items"):
        for row in rows(
            legacy,
            "SELECT itemID, itemTypeID, dateAdded, dateModified, clientDateModified, "
            "libraryID, key, version, synced FROM items ORDER BY itemID",
        ):
            type_name = legacy_item_types[row["itemTypeID"]]
            fresh.execute(
                "INSERT INTO items (itemID, itemTypeID, dateAdded, dateModified, clientDateModified, "
                "libraryID, key, version, synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["itemID"],
                    fresh_item_types[type_name],
                    row["dateAdded"],
                    row["dateModified"],
                    row["clientDateModified"],
                    row["libraryID"],
                    row["key"],
                    row["version"],
                    row["synced"],
                ),
            )

    if has_table(legacy, "itemData"):
        for row in rows(
            legacy,
            "SELECT itemID, fieldID, valueID FROM itemData ORDER BY itemID, fieldID",
        ):
            field_name = legacy_fields[row["fieldID"]]
            fresh.execute(
                "INSERT INTO itemData (itemID, fieldID, valueID) VALUES (?, ?, ?)",
                (row["itemID"], fresh_fields[field_name], row["valueID"]),
            )

    if has_table(legacy, "collections"):
        legacy_collection_cols = table_columns(legacy, "collections")
        has_client_date = "clientDateModified" in legacy_collection_cols
        query = (
            "SELECT collectionID, collectionName, parentCollectionID, "
            + ("clientDateModified, " if has_client_date else "")
            + "libraryID, key, version, synced FROM collections ORDER BY collectionID"
        )
        for row in rows(legacy, query):
            client_date = row["clientDateModified"] if has_client_date else time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            fresh.execute(
                "INSERT INTO collections (collectionID, collectionName, parentCollectionID, "
                "clientDateModified, libraryID, key, version, synced) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["collectionID"],
                    row["collectionName"],
                    row["parentCollectionID"],
                    client_date,
                    row["libraryID"],
                    row["key"],
                    row["version"],
                    row["synced"],
                ),
            )

    if has_table(legacy, "collectionItems"):
        for row in rows(
            legacy,
            "SELECT collectionID, itemID, COALESCE(orderIndex, 0) AS orderIndex "
            "FROM collectionItems ORDER BY collectionID, itemID",
        ):
            fresh.execute(
                "INSERT INTO collectionItems (collectionID, itemID, orderIndex) VALUES (?, ?, ?)",
                (row["collectionID"], row["itemID"], row["orderIndex"]),
            )

    if has_table(legacy, "tags"):
        for row in rows(legacy, "SELECT tagID, name FROM tags ORDER BY tagID"):
            fresh.execute(
                "INSERT INTO tags (tagID, name) VALUES (?, ?)",
                (row["tagID"], row["name"]),
            )

    if has_table(legacy, "itemTags"):
        for row in rows(
            legacy,
            "SELECT itemID, tagID, COALESCE(type, 0) AS type FROM itemTags ORDER BY itemID, tagID",
        ):
            fresh.execute(
                "INSERT INTO itemTags (itemID, tagID, type) VALUES (?, ?, ?)",
                (row["itemID"], row["tagID"], row["type"]),
            )

    if has_table(legacy, "itemCreators"):
        for row in rows(
            legacy,
            "SELECT itemID, creatorID, creatorTypeID, orderIndex "
            "FROM itemCreators ORDER BY itemID, orderIndex",
        ):
            creator_type_name = legacy_creator_types[row["creatorTypeID"]]
            fresh.execute(
                "INSERT INTO itemCreators (itemID, creatorID, creatorTypeID, orderIndex) "
                "VALUES (?, ?, ?, ?)",
                (
                    row["itemID"],
                    row["creatorID"],
                    fresh_creator_types[creator_type_name],
                    row["orderIndex"],
                ),
            )

    if has_table(legacy, "itemAttachments"):
        attachment_columns = table_columns(fresh, "itemAttachments")
        for row in rows(
            legacy,
            "SELECT itemID, parentItemID, linkMode, contentType, charsetID, path, "
            "COALESCE(syncState, 0) AS syncState, storageModTime, storageHash "
            "FROM itemAttachments ORDER BY itemID",
        ):
            attachment_values = {
                "itemID": row["itemID"],
                "parentItemID": row["parentItemID"],
                "linkMode": row["linkMode"],
                "contentType": row["contentType"],
                "charsetID": row["charsetID"],
                "path": row["path"],
                "syncState": row["syncState"],
                "storageModTime": row["storageModTime"],
                "storageHash": row["storageHash"],
                "lastProcessedModificationTime": None,
                "lastRead": None,
            }
            insert_columns = [col for col in attachment_values if col in attachment_columns]
            fresh.execute(
                "INSERT INTO itemAttachments ("
                + ", ".join(insert_columns)
                + ") VALUES ("
                + ", ".join("?" for _ in insert_columns)
                + ")",
                tuple(attachment_values[col] for col in insert_columns),
            )

    if has_table(legacy, "itemNotes"):
        for row in rows(
            legacy,
            "SELECT itemID, parentItemID, note, title FROM itemNotes ORDER BY itemID",
        ):
            fresh.execute(
                "INSERT INTO itemNotes (itemID, parentItemID, note, title) VALUES (?, ?, ?, ?)",
                (row["itemID"], row["parentItemID"], row["note"], row["title"]),
            )

    if has_table(legacy, "deletedItems"):
        for row in rows(
            legacy,
            "SELECT itemID, COALESCE(dateDeleted, CURRENT_TIMESTAMP) AS dateDeleted "
            "FROM deletedItems ORDER BY itemID",
        ):
            fresh.execute(
                "INSERT INTO deletedItems (itemID, dateDeleted) VALUES (?, ?)",
                (row["itemID"], row["dateDeleted"]),
            )

    fresh.commit()
    legacy.close()
    fresh.close()
    print("repaired")
    """
).strip()


def _run_python(sandbox, script: str, timeout: int = 30):
    return sandbox.commands.run(
        f"python3 - <<'PY'\n{script}\nPY",
        timeout=timeout,
    )


def _wait_for_fresh_db(sandbox, timeout: int = 60) -> bool:
    probe = textwrap.dedent(
        """
        import os

        path = os.path.expanduser("~/Zotero/zotero.sqlite")
        if not os.path.exists(path):
            print("waiting")
            raise SystemExit(1)
        if os.path.getsize(path) <= 0:
            print("waiting")
            raise SystemExit(1)
        print("ready")
        """
    ).strip()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = _run_python(sandbox, probe, timeout=15)
        except Exception:
            time.sleep(1)
            continue
        if "ready" in result.stdout:
            return True
        time.sleep(1)
    return False


def _prepare_zotero_keyring(sandbox) -> None:
    sandbox.commands.run(
        "bash -lc '"
        "mkdir -p /home/user/.local/share/keyrings && "
        "touch /home/user/.local/share/keyrings/login.keyring "
        "/home/user/.local/share/keyrings/Default_keyring.keyring && "
        "if command -v gnome-keyring-daemon >/dev/null 2>&1; then "
        "  timeout 5s sh -lc '\\''printf \"\\\\n\" | "
        "gnome-keyring-daemon --unlock --replace --components=secrets "
        "> /tmp/zotero-keyring.log 2>&1'\\'' || true; "
        "fi && "
        "chown -R user:user /home/user/.local/share/keyrings 2>/dev/null || true"
        "'",
        timeout=10,
    )


def maybe_repair_zotero_db(sandbox, logger=print) -> bool:
    try:
        status = _run_python(sandbox, LEGACY_CHECK_SCRIPT, timeout=20).stdout.strip()
    except Exception:
        return False

    if status != "legacy":
        return False

    logger("  Repairing legacy Zotero fixture for current Zotero schema...")
    sandbox.commands.run("pkill -x zotero-bin || true; pkill -x zotero || true", timeout=15)
    _prepare_zotero_keyring(sandbox)
    sandbox.commands.run(
        "mkdir -p /tmp/zotero-legacy /home/user/Zotero && "
        "mv /home/user/Zotero/zotero.sqlite /tmp/zotero-legacy/legacy.sqlite && "
        "rm -f /home/user/Zotero/zotero.sqlite-journal "
        "/home/user/Zotero/zotero.sqlite-wal /home/user/Zotero/zotero.sqlite-shm && "
        "rm -rf /home/user/.zotero",
        timeout=20,
    )

    sandbox.commands.run(
        "bash -lc 'export DISPLAY=:0; zotero > /tmp/zotero-bootstrap.log 2>&1'",
        background=True,
        timeout=0,
    )
    if not _wait_for_fresh_db(sandbox):
        raise RuntimeError("Timed out bootstrapping a fresh Zotero profile")

    sandbox.commands.run("pkill -x zotero-bin || true; pkill -x zotero || true", timeout=20)
    sandbox.commands.run("find /home/user/.zotero -name .parentlock -delete || true", timeout=10)
    sandbox.files.write("/home/user/repair_zotero_legacy.py", LEGACY_REPAIR_SCRIPT)
    sandbox.commands.run("python3 /home/user/repair_zotero_legacy.py", timeout=120)
    sandbox.commands.run("find /home/user/.zotero -name .parentlock -delete || true", timeout=10)
    logger("  Zotero fixture repaired.")
    return True


def _prepare_zotero_task(ctx: AppContext) -> None:
    maybe_repair_zotero_db(ctx.sandbox)


def _prepare_zotero_profile(ctx: AppContext) -> None:
    _prepare_zotero_keyring(ctx.sandbox)


def build_zotero_spec(verifier_local, verifier_remote) -> AppSpec:
    def build_launch_command(ctx: AppContext) -> str:
        command = build_command("zotero")
        return with_log_redirect(command, ctx.log_path("zotero"))

    return AppSpec(
        app_id="zotero",
        verifier_local=verifier_local,
        verifier_remote=verifier_remote,
        canonical_launcher="zotero",
        build_launch_command=build_launch_command,
        ready_check=lambda sandbox: check_process_ready(sandbox, "zotero-bin", "zotero"),
        prepare_task_hooks=(_prepare_zotero_task,),
        prepare_profile_hooks=(_prepare_zotero_profile,),
    )
