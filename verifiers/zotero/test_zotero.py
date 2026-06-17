"""
Test Zotero verifier endpoints in a live E2B sandbox.

The test builds a Zotero-compatible SQLite fixture programmatically (avoiding
the complexity of launching Zotero headless to seed data). The verifier reads
the fixture exactly as it would read a real ~/Zotero/zotero.sqlite.

Usage:
    python verifiers/zotero/test_zotero.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "zotero.py"
VERIFIER_REMOTE = "/home/user/verifiers/zotero.py"
V = f"python3 {VERIFIER_REMOTE}"

DATA_DIR = "/home/user/Zotero"
PROFILE_DIR = "/home/user/.zotero/zotero/xyz.default"
BIBTEX_PATH = "/home/user/export_test.bib"

passed = 0
failed = 0
errors: list[str] = []


class CmdResult:
    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def run_raw(sandbox: Sandbox, cmd: str, timeout: int = 30, env_prefix: str = "") -> CmdResult:
    try:
        full = f"{env_prefix} {V} {cmd}".strip()
        result = sandbox.commands.run(full, timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def run(sandbox: Sandbox, cmd: str, timeout: int = 30, env_prefix: str = "") -> dict | list:
    r = run_raw(sandbox, cmd, timeout, env_prefix)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        msg = f"  FAIL  {name}"
        if detail:
            msg += f"  -- {detail}"
        print(msg)
        errors.append(f"{name}: {detail}")


def is_valid_json(stdout: str) -> bool:
    try:
        json.loads(stdout)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Fixture creation
# ---------------------------------------------------------------------------

FIXTURE_SCRIPT = r'''
import os, sqlite3, pathlib
data_dir = pathlib.Path("{data_dir}")
data_dir.mkdir(parents=True, exist_ok=True)
(data_dir / "storage").mkdir(exist_ok=True)
(data_dir / "storage" / "ABC12345").mkdir(exist_ok=True)
(data_dir / "storage" / "DEF67890").mkdir(exist_ok=True)
(data_dir / "storage" / "ABC12345" / "paper.pdf").write_bytes(b"%PDF-1.4\n%stub\n")
(data_dir / "storage" / "DEF67890" / "book.pdf").write_bytes(b"%PDF-1.4\n%stub\n")

db = data_dir / "zotero.sqlite"
if db.exists():
    db.unlink()
conn = sqlite3.connect(str(db))
cur = conn.cursor()

# Minimal subset of Zotero's schema that the verifier queries.
cur.executescript("""
CREATE TABLE libraries (
    libraryID INTEGER PRIMARY KEY,
    type TEXT,
    editable INTEGER,
    filesEditable INTEGER,
    version INTEGER DEFAULT 0,
    storageVersion INTEGER DEFAULT 0,
    lastSync INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE itemTypes (
    itemTypeID INTEGER PRIMARY KEY,
    typeName TEXT NOT NULL,
    templateItemTypeID INT,
    display INT DEFAULT 1
);

CREATE TABLE creatorTypes (
    creatorTypeID INTEGER PRIMARY KEY,
    creatorType TEXT NOT NULL
);

CREATE TABLE fields (
    fieldID INTEGER PRIMARY KEY,
    fieldName TEXT NOT NULL,
    fieldFormatID INT
);

CREATE TABLE itemDataValues (
    valueID INTEGER PRIMARY KEY,
    value TEXT
);

CREATE TABLE items (
    itemID INTEGER PRIMARY KEY,
    itemTypeID INT NOT NULL,
    dateAdded TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dateModified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    clientDateModified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    libraryID INT NOT NULL DEFAULT 1,
    key TEXT NOT NULL,
    version INT NOT NULL DEFAULT 0,
    synced INT NOT NULL DEFAULT 0
);

CREATE TABLE itemData (
    itemID INT,
    fieldID INT,
    valueID INT,
    PRIMARY KEY (itemID, fieldID)
);

CREATE TABLE creators (
    creatorID INTEGER PRIMARY KEY,
    firstName TEXT,
    lastName TEXT,
    fieldMode INT
);

CREATE TABLE itemCreators (
    itemID INT NOT NULL,
    creatorID INT NOT NULL,
    creatorTypeID INT NOT NULL,
    orderIndex INT NOT NULL DEFAULT 0,
    PRIMARY KEY (itemID, creatorID, creatorTypeID, orderIndex)
);

CREATE TABLE collections (
    collectionID INTEGER PRIMARY KEY,
    collectionName TEXT NOT NULL,
    parentCollectionID INT DEFAULT NULL,
    libraryID INT NOT NULL DEFAULT 1,
    key TEXT NOT NULL,
    version INT NOT NULL DEFAULT 0,
    synced INT NOT NULL DEFAULT 0
);

CREATE TABLE collectionItems (
    collectionID INT NOT NULL,
    itemID INT NOT NULL,
    orderIndex INT NOT NULL DEFAULT 0,
    PRIMARY KEY (collectionID, itemID)
);

CREATE TABLE tags (
    tagID INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE itemTags (
    itemID INT NOT NULL,
    tagID INT NOT NULL,
    type INT NOT NULL DEFAULT 0,
    PRIMARY KEY (itemID, tagID)
);

CREATE TABLE itemAttachments (
    itemID INTEGER PRIMARY KEY,
    parentItemID INT,
    linkMode INT,
    contentType TEXT,
    charsetID INT,
    path TEXT,
    syncState INT DEFAULT 0,
    storageModTime INT,
    storageHash TEXT
);

CREATE TABLE itemNotes (
    itemID INTEGER PRIMARY KEY,
    parentItemID INT,
    note TEXT,
    title TEXT
);

CREATE TABLE deletedItems (
    itemID INTEGER PRIMARY KEY,
    dateDeleted TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
""")

# libraries
cur.execute("INSERT INTO libraries (libraryID, type, editable, filesEditable) VALUES (1, 'user', 1, 1)")

# itemTypes
item_types = [
    (1, 'journalArticle'),
    (2, 'book'),
    (3, 'webpage'),
    (14, 'attachment'),
    (15, 'note'),
]
cur.executemany("INSERT INTO itemTypes (itemTypeID, typeName) VALUES (?, ?)", item_types)

# creatorTypes
creator_types = [
    (1, 'author'),
    (2, 'editor'),
    (3, 'contributor'),
]
cur.executemany("INSERT INTO creatorTypes (creatorTypeID, creatorType) VALUES (?, ?)", creator_types)

# fields (the ones we use)
fields = [
    (1, 'title'),
    (2, 'date'),
    (3, 'DOI'),
    (4, 'publicationTitle'),
    (5, 'publisher'),
    (6, 'abstractNote'),
    (7, 'url'),
    (8, 'pages'),
]
cur.executemany("INSERT INTO fields (fieldID, fieldName) VALUES (?, ?)", fields)

# itemDataValues (deduped values)
values = [
    (1, 'Attention Is All You Need'),
    (2, '2017'),
    (3, '10.48550/arXiv.1706.03762'),
    (4, 'arXiv'),
    (5, 'Deep Learning'),
    (6, '2016'),
    (7, 'MIT Press'),
    (8, 'BERT: Pre-training of Deep Bidirectional Transformers'),
    (9, '2018'),
    (10, '10.18653/v1/N19-1423'),
    (11, 'NAACL'),
    (12, 'A Survey of RL Methods'),
    (13, '2020'),
    (14, 'JMLR'),
    (15, 'Old Draft Note'),
]
cur.executemany("INSERT INTO itemDataValues (valueID, value) VALUES (?, ?)", values)

# items (1-4 regular, 5 deleted, 6-7 attachments, 8 note)
items = [
    (1, 1, 'ITEMKEY0001'),   # journalArticle
    (2, 2, 'ITEMKEY0002'),   # book
    (3, 1, 'ITEMKEY0003'),   # journalArticle
    (4, 1, 'ITEMKEY0004'),   # journalArticle
    (5, 1, 'ITEMKEY0005'),   # journalArticle (to be deleted)
    (6, 14, 'ABC12345'),     # attachment (child of 1)
    (7, 14, 'DEF67890'),     # attachment (child of 2)
    (8, 15, 'NOTEKEY0001'),  # note (child of 1)
]
for iid, tid, key in items:
    cur.execute(
        "INSERT INTO items (itemID, itemTypeID, libraryID, key) VALUES (?, ?, 1, ?)",
        (iid, tid, key),
    )

# itemData (item, field, value)
itemdata = [
    # item 1: Attention Is All You Need
    (1, 1, 1),   # title
    (1, 2, 2),   # date
    (1, 3, 3),   # DOI
    (1, 4, 4),   # publicationTitle
    # item 2: Deep Learning
    (2, 1, 5),
    (2, 2, 6),
    (2, 5, 7),   # publisher
    # item 3: BERT
    (3, 1, 8),
    (3, 2, 9),
    (3, 3, 10),
    (3, 4, 11),
    # item 4: A Survey of RL Methods
    (4, 1, 12),
    (4, 2, 13),
    (4, 4, 14),
    # item 5: Old Draft Note
    (5, 1, 15),
]
cur.executemany("INSERT INTO itemData (itemID, fieldID, valueID) VALUES (?, ?, ?)", itemdata)

# creators
creators = [
    (1, 'Ashish', 'Vaswani'),
    (2, 'Noam', 'Shazeer'),
    (3, 'Niki', 'Parmar'),
    (4, 'Ian', 'Goodfellow'),
    (5, 'Yoshua', 'Bengio'),
    (6, 'Jacob', 'Devlin'),
    (7, 'Richard', 'Sutton'),
]
for cid, fn, ln in creators:
    cur.execute(
        "INSERT INTO creators (creatorID, firstName, lastName, fieldMode) VALUES (?, ?, ?, 0)",
        (cid, fn, ln),
    )

# itemCreators (item 1 has 3 authors, item 2 has 2 authors, item 3 has 1, item 4 has 1)
icreators = [
    (1, 1, 1, 0),
    (1, 2, 1, 1),
    (1, 3, 1, 2),
    (2, 4, 1, 0),
    (2, 5, 1, 1),
    (3, 6, 1, 0),
    (4, 7, 1, 0),
]
cur.executemany(
    "INSERT INTO itemCreators (itemID, creatorID, creatorTypeID, orderIndex) VALUES (?, ?, ?, ?)",
    icreators,
)

# collections
cols = [
    (1, 'AI Research', None, 'COLLKEY001'),
    (2, 'Transformers', 1, 'COLLKEY002'),
    (3, 'Reinforcement Learning', None, 'COLLKEY003'),
]
for cid, name, parent, key in cols:
    cur.execute(
        "INSERT INTO collections (collectionID, collectionName, parentCollectionID, libraryID, key) VALUES (?, ?, ?, 1, ?)",
        (cid, name, parent, key),
    )

# collectionItems
colitems = [
    (2, 1),  # Transformers contains Attention Is All You Need
    (2, 3),  # Transformers contains BERT
    (3, 4),  # RL contains survey
]
cur.executemany("INSERT INTO collectionItems (collectionID, itemID) VALUES (?, ?)", colitems)

# tags
tags = [(1, 'important'), (2, 'nlp'), (3, 'survey')]
cur.executemany("INSERT INTO tags (tagID, name) VALUES (?, ?)", tags)

# itemTags
itags = [(1, 1), (1, 2), (3, 2), (4, 3)]
cur.executemany("INSERT INTO itemTags (itemID, tagID) VALUES (?, ?)", itags)

# itemAttachments (item 6 -> parent 1, item 7 -> parent 2)
cur.execute(
    "INSERT INTO itemAttachments (itemID, parentItemID, linkMode, contentType, path) VALUES (6, 1, 1, 'application/pdf', 'storage:paper.pdf')"
)
cur.execute(
    "INSERT INTO itemAttachments (itemID, parentItemID, linkMode, contentType, path) VALUES (7, 2, 1, 'application/pdf', 'storage:book.pdf')"
)

# itemNotes
cur.execute(
    "INSERT INTO itemNotes (itemID, parentItemID, note, title) VALUES (8, 1, '<p>Seminal paper introducing the Transformer architecture.</p>', 'Note on Attention')"
)

# deletedItems (item 5 is in trash)
cur.execute("INSERT INTO deletedItems (itemID) VALUES (5)")

conn.commit()
conn.close()
print("OK")
'''


PREFS_JS = '''// Mozilla User Preferences
user_pref("extensions.zotero.dataDir", "/home/user/Zotero");
user_pref("extensions.zotero.lastViewedFolder", "L1");
user_pref("extensions.zotero.export.quickCopy.setting", "bibliography=http://www.zotero.org/styles/apa");
user_pref("extensions.zotero.export.bibliographyLocale", "en-US");
user_pref("extensions.zotero.note.fontSize", 14);
user_pref("extensions.zotero.recursiveCollections", true);
user_pref("extensions.zotero.sync.autoSync", false);
user_pref("extensions.zotero.translators.attachSupplementary", true);
user_pref("intl.locale.requested", "en-US");
'''


BIBTEX = '''@article{vaswani2017,
  title = {Attention Is All You Need},
  author = {Vaswani, Ashish and others},
  year = {2017},
}

@book{goodfellow2016,
  title = {Deep Learning},
  author = {Goodfellow, Ian and Bengio, Yoshua},
  year = {2016},
}

@article{devlin2018,
  title = {BERT: Pre-training Transformers},
  author = {Devlin, Jacob},
  year = {2018},
}
'''


def create_fixtures(sandbox: Sandbox):
    print("Creating Zotero fixtures...")
    script = FIXTURE_SCRIPT.replace("{data_dir}", DATA_DIR)
    sandbox.files.write("/tmp/create_zotero_fixture.py", script)
    try:
        r = sandbox.commands.run("python3 /tmp/create_zotero_fixture.py", timeout=60)
        print(f"  sqlite fixture: {r.stdout.strip()} {r.stderr.strip()}")
    except CommandExitException as e:
        print(f"  FAILED: exit={e.exit_code} stderr={e.stderr}")
        raise

    sandbox.commands.run(f"mkdir -p {PROFILE_DIR}", timeout=5)
    sandbox.files.write(f"{PROFILE_DIR}/prefs.js", PREFS_JS)
    sandbox.files.write(BIBTEX_PATH, BIBTEX)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    print("\n=== Group 1: Help ===")
    r = run_raw(sandbox, "--help")
    check("help exits 0", r.exit_code == 0, f"got {r.exit_code}")
    check("help mentions Commands", "Commands:" in r.stdout)


def test_errors_no_data_dir(sandbox: Sandbox):
    print("\n=== Group 2: Errors (no data dir) ===")
    prefix = "ZOTERO_DATA_DIR=/tmp/nonexistent_zotero"
    cmds = [
        "library-stats",
        "collections",
        "items",
        "tags",
        "attachments",
        "notes",
        "trash",
    ]
    for cmd in cmds:
        data = run(sandbox, cmd, env_prefix=prefix)
        # either a dict with error or a list with error inside
        if isinstance(data, list):
            data_first = data[0] if data else {}
        else:
            data_first = data
        has_err = isinstance(data_first, dict) and "error" in data_first
        check(f"{cmd} no data dir -> error", has_err, str(data)[:120])

    # data-dir returns a dict with error
    data = run(sandbox, "data-dir", env_prefix=prefix)
    check("data-dir no data dir -> error", isinstance(data, dict) and "error" in data, str(data)[:120])


def test_errors_bad_args(sandbox: Sandbox):
    print("\n=== Group 3: Errors (bad args) ===")
    for cmd in ["check-item-exists", "check-collection-exists", "check-tag-exists",
                "check-note-contains", "check-item-in-trash"]:
        r = run_raw(sandbox, cmd)
        check(f"{cmd} missing arg exit 1", r.exit_code == 1)
        check(f"{cmd} missing arg valid JSON", is_valid_json(r.stdout), r.stdout[:100])

    r = run_raw(sandbox, "nonexistent-cmd")
    check("unknown cmd exit 1", r.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(r.stdout), r.stdout[:100])


def test_data_dir(sandbox: Sandbox):
    print("\n=== Group 4: Data dir detection ===")
    data = run(sandbox, "data-dir")
    check("data-dir returns dict", isinstance(data, dict))
    check("data-dir exists=True", data.get("exists") is True, str(data))
    check("data-dir has_sqlite", data.get("has_sqlite") is True, str(data))


def test_library_stats(sandbox: Sandbox):
    print("\n=== Group 5: Library stats ===")
    data = run(sandbox, "library-stats")
    check("library-stats dict", isinstance(data, dict))
    check("items=4", data.get("items") == 4, str(data))
    check("attachments=2", data.get("attachments") == 2, str(data))
    check("notes=1", data.get("notes") == 1, str(data))
    check("collections=3", data.get("collections") == 3, str(data))
    check("tags=3", data.get("tags") == 3, str(data))


def test_collections(sandbox: Sandbox):
    print("\n=== Group 6: Collections ===")
    data = run(sandbox, "collections")
    check("collections returns list", isinstance(data, list))
    check("collections count 3", len(data) == 3, str(data))

    data = run(sandbox, "collection-items Transformers")
    check("collection-items returns list", isinstance(data, list))
    check("Transformers has 2 items", len(data) == 2, str(data))

    data = run(sandbox, "check-collection-exists 'AI Research'")
    check("check-collection-exists positive", data.get("exists") is True, str(data)[:120])

    data = run(sandbox, "check-collection-exists 'NonexistentZZZ'")
    check("check-collection-exists negative", data.get("exists") is False, str(data)[:120])

    data = run(sandbox, "check-collection-count Transformers 2")
    check("check-collection-count positive", data.get("match") is True, str(data)[:120])

    data = run(sandbox, "check-collection-count Transformers 5")
    check("check-collection-count negative", data.get("match") is False, str(data)[:120])

    data = run(sandbox, "check-collection-contains Transformers BERT")
    check("check-collection-contains positive", data.get("contains") is True, str(data)[:120])

    data = run(sandbox, "check-collection-contains Transformers NonexistentZZZ")
    check("check-collection-contains negative", data.get("contains") is False, str(data)[:120])

    data = run(sandbox, "check-subcollection 'AI Research' Transformers")
    check("check-subcollection positive", data.get("is_subcollection") is True, str(data)[:120])

    data = run(sandbox, "check-subcollection Transformers 'Reinforcement Learning'")
    check("check-subcollection negative", data.get("is_subcollection") is False, str(data)[:120])


def test_items(sandbox: Sandbox):
    print("\n=== Group 7: Items ===")
    data = run(sandbox, "items")
    check("items returns list", isinstance(data, list))
    check("items has 4", len(data) == 4, str(data)[:200])

    data = run(sandbox, "item-count")
    check("item-count=4", data.get("count") == 4, str(data))

    data = run(sandbox, "item-fields Attention")
    check("item-fields returns dict", isinstance(data, dict))
    check("item-fields has DOI", data.get("fields", {}).get("DOI") == "10.48550/arXiv.1706.03762", str(data)[:200])
    check("item-fields has date", data.get("fields", {}).get("date") == "2017", str(data)[:200])

    data = run(sandbox, "check-item-exists Attention")
    check("check-item-exists positive", data.get("exists") is True, str(data)[:100])

    data = run(sandbox, "check-item-exists NonexistentZZZ")
    check("check-item-exists negative", data.get("exists") is False, str(data)[:100])

    data = run(sandbox, "check-item-field Attention DOI 10.48550/arXiv.1706.03762")
    check("check-item-field positive", data.get("match") is True, str(data)[:150])

    data = run(sandbox, "check-item-field Attention DOI WRONG")
    check("check-item-field negative", data.get("match") is False, str(data)[:150])

    data = run(sandbox, "check-item-type Attention journalArticle")
    check("check-item-type positive", data.get("match") is True, str(data)[:150])

    data = run(sandbox, "check-item-type Attention book")
    check("check-item-type negative", data.get("match") is False, str(data)[:150])

    data = run(sandbox, "check-item-count 4")
    check("check-item-count positive", data.get("match") is True, str(data))

    data = run(sandbox, "check-item-count 10")
    check("check-item-count negative", data.get("match") is False, str(data))


def test_creators(sandbox: Sandbox):
    print("\n=== Group 8: Creators ===")
    data = run(sandbox, "item-creators Attention")
    check("item-creators returns list", isinstance(data, list))
    check("item-creators has 3", len(data) == 3, str(data)[:200])

    data = run(sandbox, "check-item-creator Attention Vaswani")
    check("check-item-creator positive", data.get("has_creator") is True, str(data)[:150])

    data = run(sandbox, "check-item-creator Attention NonexistentZZZ")
    check("check-item-creator negative", data.get("has_creator") is False, str(data)[:150])

    data = run(sandbox, "check-item-creator-count Attention 3")
    check("check-item-creator-count positive", data.get("match") is True, str(data))

    data = run(sandbox, "check-item-creator-count Attention 99")
    check("check-item-creator-count negative", data.get("match") is False, str(data))


def test_tags(sandbox: Sandbox):
    print("\n=== Group 9: Tags ===")
    data = run(sandbox, "tags")
    check("tags returns list", isinstance(data, list))
    check("tags has 3", len(data) == 3, str(data)[:200])

    data = run(sandbox, "check-tag-exists nlp")
    check("check-tag-exists positive", data.get("exists") is True, str(data)[:100])

    data = run(sandbox, "check-tag-exists NonexistentZZZ")
    check("check-tag-exists negative", data.get("exists") is False, str(data)[:100])

    data = run(sandbox, "item-tags Attention")
    check("item-tags returns list", isinstance(data, list))
    check("item-tags has 2", len(data) == 2, str(data)[:200])

    data = run(sandbox, "check-item-tag Attention nlp")
    check("check-item-tag positive", data.get("has_tag") is True, str(data)[:100])

    data = run(sandbox, "check-item-tag Attention survey")
    check("check-item-tag negative", data.get("has_tag") is False, str(data)[:100])


def test_attachments(sandbox: Sandbox):
    print("\n=== Group 10: Attachments ===")
    data = run(sandbox, "attachments")
    check("attachments returns list", isinstance(data, list))
    check("attachments has 2", len(data) == 2, str(data)[:200])

    data = run(sandbox, "check-item-attachment Attention")
    check("check-item-attachment positive", data.get("has_attachment") is True, str(data)[:150])

    data = run(sandbox, "check-item-attachment BERT")
    check("check-item-attachment negative", data.get("has_attachment") is False, str(data)[:150])

    data = run(sandbox, "check-attachment-file ABC12345")
    check("check-attachment-file positive", data.get("exists") is True, str(data)[:150])

    data = run(sandbox, "check-attachment-file ZZZ99999")
    check("check-attachment-file negative", data.get("exists") is False, str(data)[:150])


def test_notes(sandbox: Sandbox):
    print("\n=== Group 11: Notes ===")
    data = run(sandbox, "notes")
    check("notes returns list", isinstance(data, list))
    check("notes has 1", len(data) == 1, str(data)[:200])

    data = run(sandbox, "check-note-contains 'Transformer architecture'")
    check("check-note-contains positive", data.get("contains") is True, str(data)[:150])

    data = run(sandbox, "check-note-contains 'NonexistentZZZ'")
    check("check-note-contains negative", data.get("contains") is False, str(data)[:150])

    data = run(sandbox, "check-item-note Attention")
    check("check-item-note positive", data.get("has_note") is True, str(data)[:150])

    data = run(sandbox, "check-item-note BERT")
    check("check-item-note negative", data.get("has_note") is False, str(data)[:150])


def test_trash(sandbox: Sandbox):
    print("\n=== Group 12: Trash ===")
    data = run(sandbox, "trash")
    check("trash returns list", isinstance(data, list))
    check("trash has 1", len(data) == 1, str(data)[:200])

    data = run(sandbox, "check-item-in-trash 'Old Draft'")
    check("check-item-in-trash positive", data.get("in_trash") is True, str(data)[:150])

    data = run(sandbox, "check-item-in-trash Attention")
    check("check-item-in-trash negative", data.get("in_trash") is False, str(data)[:150])


def test_preferences(sandbox: Sandbox):
    print("\n=== Group 13: Preferences ===")
    env = f"ZOTERO_PROFILE_DIR={PROFILE_DIR}"

    data = run(sandbox, "prefs", env_prefix=env)
    check("prefs overview dict", isinstance(data, dict))
    check("prefs has total_prefs", "total_prefs" in data, str(data)[:200])

    data = run(sandbox, "prefs extensions.zotero.note.fontSize", env_prefix=env)
    check("prefs key returns value", data.get("value") == 14, str(data)[:150])

    data = run(sandbox, "prefs nonexistent.pref.key", env_prefix=env)
    check("prefs missing key error", "error" in data, str(data)[:150])

    data = run(sandbox, "prefs-matching bibliography", env_prefix=env)
    check("prefs-matching returns matches", data.get("count", 0) >= 1, str(data)[:200])

    data = run(sandbox, "check-pref-value extensions.zotero.note.fontSize 14", env_prefix=env)
    check("check-pref-value positive", data.get("match") is True, str(data)[:150])

    data = run(sandbox, "check-pref-value extensions.zotero.note.fontSize 99", env_prefix=env)
    check("check-pref-value negative", data.get("match") is False, str(data)[:150])


def test_bibtex_and_files(sandbox: Sandbox):
    print("\n=== Group 14: BibTeX / file I/O ===")
    data = run(sandbox, f"check-file-exists {BIBTEX_PATH}")
    check("check-file-exists positive", data.get("exists") is True, str(data)[:150])

    data = run(sandbox, "check-file-exists /home/user/zzznonexistent.bib")
    check("check-file-exists negative", data.get("exists") is False, str(data)[:150])

    data = run(sandbox, f"parse-bibtex {BIBTEX_PATH}")
    check("parse-bibtex returns dict", isinstance(data, dict))
    check("parse-bibtex count=3", data.get("count") == 3, str(data)[:200])

    data = run(sandbox, f"check-bibtex-count {BIBTEX_PATH} 3")
    check("check-bibtex-count positive", data.get("match") is True, str(data)[:150])

    data = run(sandbox, f"check-bibtex-count {BIBTEX_PATH} 10")
    check("check-bibtex-count negative", data.get("match") is False, str(data)[:150])

    data = run(sandbox, f"check-bibtex-title {BIBTEX_PATH} 'Deep Learning'")
    check("check-bibtex-title positive", data.get("contains") is True, str(data)[:150])

    data = run(sandbox, f"check-bibtex-title {BIBTEX_PATH} NonexistentZZZ")
    check("check-bibtex-title negative", data.get("contains") is False, str(data)[:150])


def test_json_validity(sandbox: Sandbox):
    print("\n=== Group 15: JSON validity sweep ===")
    env = f"ZOTERO_PROFILE_DIR={PROFILE_DIR}"
    cmds = [
        ("data-dir", ""),
        ("library-stats", ""),
        ("collections", ""),
        ("collection-items", "Transformers"),
        ("check-collection-exists", "'AI Research'"),
        ("check-collection-count", "Transformers 2"),
        ("check-collection-contains", "Transformers BERT"),
        ("check-subcollection", "'AI Research' Transformers"),
        ("items", ""),
        ("items", "10"),
        ("item-count", ""),
        ("item-fields", "Attention"),
        ("check-item-exists", "Attention"),
        ("check-item-field", "Attention DOI x"),
        ("check-item-type", "Attention journalArticle"),
        ("check-item-count", "4"),
        ("item-creators", "Attention"),
        ("check-item-creator", "Attention Vaswani"),
        ("check-item-creator-count", "Attention 3"),
        ("tags", ""),
        ("check-tag-exists", "nlp"),
        ("item-tags", "Attention"),
        ("check-item-tag", "Attention nlp"),
        ("attachments", ""),
        ("check-item-attachment", "Attention"),
        ("check-attachment-file", "ABC12345"),
        ("notes", ""),
        ("check-note-contains", "test"),
        ("check-item-note", "Attention"),
        ("trash", ""),
        ("check-item-in-trash", "test"),
        ("prefs", ""),
        ("prefs-matching", "bib"),
        ("check-pref-value", "extensions.zotero.note.fontSize 14"),
        ("parse-bibtex", BIBTEX_PATH),
        ("check-bibtex-count", f"{BIBTEX_PATH} 3"),
        ("check-bibtex-title", f"{BIBTEX_PATH} Deep"),
        ("check-file-exists", BIBTEX_PATH),
    ]
    for cmd, args in cmds:
        # For prefs commands, set the profile env
        env_prefix = env if "pref" in cmd else ""
        full = f"{cmd} {args}".strip()
        r = run_raw(sandbox, full, env_prefix=env_prefix)
        valid = is_valid_json(r.stdout)
        check(f"{full} valid JSON", valid,
              f"exit={r.exit_code} stdout={r.stdout[:80]}" if not valid else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed
    print("=" * 60)
    print("Zotero Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # Pre-fixture tests
        test_help(sandbox)
        test_errors_no_data_dir(sandbox)
        test_errors_bad_args(sandbox)

        # Fixtures
        create_fixtures(sandbox)

        # Post-fixture tests
        test_data_dir(sandbox)
        test_library_stats(sandbox)
        test_collections(sandbox)
        test_items(sandbox)
        test_creators(sandbox)
        test_tags(sandbox)
        test_attachments(sandbox)
        test_notes(sandbox)
        test_trash(sandbox)
        test_preferences(sandbox)
        test_bibtex_and_files(sandbox)
        test_json_validity(sandbox)

    except Exception:
        traceback.print_exc()
        failed += 1
        errors.append(f"Unhandled: {traceback.format_exc()}")

    finally:
        sandbox.kill()
        print("\nSandbox killed.")

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  - {e}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
