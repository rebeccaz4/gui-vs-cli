# Zotero Verifier — Test Plan

## Module Overview

`verifiers/zotero/zotero.py` inspects Zotero's SQLite DB (`~/Zotero/zotero.sqlite`),
file attachments (`~/Zotero/storage/`), and Mozilla prefs
(`~/.zotero/zotero/*.default*/prefs.js`). It also parses BibTeX export files.

Prerequisites for tests:
- `desktop-all-apps` E2B template (Zotero installed at `/opt/zotero/zotero`).
- The tests do **not** launch Zotero. Instead they construct a Zotero-compatible
  SQLite fixture programmatically by running `CREATE TABLE` + `INSERT` via
  stdlib `sqlite3`, and write a minimal `prefs.js`. This avoids the fragile step
  of headless-launching a XUL app.

## Test Groups

### Group 1: Help / Usage
- `--help`, `help`, no-args all print usage and exit 0.
- 2 assertions.

### Group 2: Errors (no data dir)
- Before creating the fixture, every SQLite-based endpoint returns `{"error":
  ...}` (with `ZOTERO_DATA_DIR` pointing to a nonexistent path).
- Covers: `library-stats`, `collections`, `items`, `tags`, `attachments`,
  `notes`, `trash`, `prefs`, `data-dir`.
- ~9 assertions.

### Group 3: Errors (bad args)
- Missing required args: `check-item-exists`, `check-item-field`,
  `check-collection-contains`, `check-subcollection`, `check-pref-value` etc.
- Unknown command.
- ~6 assertions.

### Group 4: Data dir detection
- After fixture created at `~/Zotero/zotero.sqlite`, `data-dir` returns
  `{exists=true, has_sqlite=true, has_storage=true}`.
- 3 assertions.

### Group 5: Library stats
- `library-stats` returns the expected counts for the fixture (items=4,
  attachments=2, notes=1, collections=3, tags=3, deleted_items=1).
- 6 assertions.

### Group 6: Collections
- `collections` returns 3 collections.
- `collection-items` for "Transformers" returns 2 items.
- `check-collection-exists` positive + negative.
- `check-collection-count` positive + negative.
- `check-collection-contains` positive + negative.
- `check-subcollection` positive (Transformers is child of AI) + negative.
- ~10 assertions.

### Group 7: Items
- `items` returns list with title/typeName.
- `item-count` returns 4.
- `item-fields` for a known item returns DOI, date, publicationTitle.
- `check-item-exists` positive + negative.
- `check-item-field` positive (DOI match) + negative.
- `check-item-type` positive + negative.
- `check-item-count` positive + negative.
- ~12 assertions.

### Group 8: Creators
- `item-creators` returns 3 authors for the Transformer paper.
- `check-item-creator` positive (Vaswani) + negative.
- `check-item-creator-count` positive + negative.
- ~6 assertions.

### Group 9: Tags
- `tags` returns 3 tags.
- `check-tag-exists` positive + negative.
- `item-tags` returns 2 tags for the Transformer item.
- `check-item-tag` positive + negative.
- ~6 assertions.

### Group 10: Attachments
- `attachments` returns 2 attachments.
- `check-item-attachment` positive + negative (item with no attachment).
- `check-attachment-file` positive (storage file created) + negative.
- ~6 assertions.

### Group 11: Notes
- `notes` returns 1 note.
- `check-note-contains` positive + negative.
- `check-item-note` positive + negative.
- ~5 assertions.

### Group 12: Trash
- `trash` returns 1 deleted item.
- `check-item-in-trash` positive + negative.
- ~3 assertions.

### Group 13: Preferences
- `prefs` no-arg returns overview.
- `prefs <key>` returns value.
- `prefs nonexistent.key` returns error.
- `prefs-matching` returns matches for substring.
- `check-pref-value` positive + negative.
- ~6 assertions.

### Group 14: BibTeX / file I/O
- `check-file-exists` positive + negative.
- `parse-bibtex` returns expected entries.
- `check-bibtex-count` positive + negative.
- `check-bibtex-title` positive + negative.
- ~6 assertions.

### Group 15: JSON validity sweep
- Every CLI command returns valid JSON (no tracebacks on stdout).
- ~35 assertions (one per command).

## Test Fixtures

All fixtures live in the sandbox at runtime and are created via `sandbox.files.write`
or `sandbox.commands.run` with a small Python helper script.

| Path | Format | Purpose |
|---|---|---|
| `/home/user/Zotero/zotero.sqlite` | SQLite (hand-built) | Library DB — 4 items, 2 attachments, 1 note, 3 collections, 3 tags, 1 deleted item, 5 creators |
| `/home/user/Zotero/storage/ABC12345/paper.pdf` | PDF bytes (stub) | Attachment file for Transformer paper |
| `/home/user/Zotero/storage/DEF67890/book.pdf` | PDF bytes (stub) | Attachment file for "Deep Learning" book |
| `/home/user/.zotero/zotero/xyz.default/prefs.js` | Mozilla prefs | Zotero preferences for tests |
| `/home/user/export_test.bib` | BibTeX | For export parsing tests — 3 entries |

### SQLite fixture contents

Items (4 regular):
1. "Attention Is All You Need" — journalArticle — authors: Vaswani, Shazeer, Parmar — DOI 10.48550/arXiv.1706.03762, date 2017, publicationTitle "arXiv"
2. "Deep Learning" — book — authors: Goodfellow, Bengio — publisher MIT Press, date 2016
3. "BERT: Pre-training of Deep Bidirectional Transformers" — journalArticle — author: Devlin — DOI 10.18653/v1/N19-1423, date 2018
4. "A Survey of RL Methods" — journalArticle — author: Sutton — date 2020

Attachments (2):
- paper.pdf attached to item 1 (key ABC12345)
- book.pdf attached to item 2 (key DEF67890)

Note (1):
- Attached to item 1: body "Seminal paper introducing the Transformer architecture"

Collections:
- "AI Research" (parent)
- "Transformers" (child of AI Research) — contains items 1, 3
- "Reinforcement Learning" — contains item 4

Tags: "important", "nlp", "survey"

Item tags:
- item 1 tagged "important", "nlp"
- item 3 tagged "nlp"
- item 4 tagged "survey"

Deleted items:
- item 5: "Old Draft Note" (placed in deletedItems)

### BibTeX fixture contents

```
@article{vaswani2017,
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
```

## Edge Cases & Error Handling Matrix

| Scenario | Endpoint(s) | Expected |
|---|---|---|
| Data dir missing | all SQLite endpoints | `{"error": "..."}` |
| Missing required arg | `check-*` endpoints | exit 1 + valid JSON |
| Unknown subcommand | any | exit 1 + valid JSON |
| Nonexistent BibTeX path | `parse-bibtex`, `check-bibtex-*` | `{"error": "..."}` |
| Nonexistent pref key | `prefs key` | `{"error": "..."}` |
| Nonexistent file | `check-file-exists` | `{exists: false}` |
| Empty collection | `collection-items` | `[]` |
| Title substring with no matches | `check-item-*` | `{"error": "..."}` or `{found: false}` |

## Positive / Negative Pairs

Every `check-*` endpoint has explicit positive and negative cases listed in
the group descriptions above. Highlights:

| Endpoint | Positive | Negative |
|---|---|---|
| check-item-exists | "Attention Is All You Need" | "Nonexistent ZZZ" |
| check-item-field | DOI on item 1 = real DOI | DOI on item 1 vs "WRONG" |
| check-item-type | item 1 → journalArticle | item 1 → book |
| check-collection-exists | "AI Research" | "Nonexistent" |
| check-collection-contains | "Transformers" contains "BERT" | contains "Unrelated" |
| check-subcollection | Transformers under AI Research | Reinforcement under Transformers |
| check-item-creator | item 1 has Vaswani | item 1 has Nonexistent |
| check-tag-exists | "nlp" | "nonexistent" |
| check-item-tag | item 1 has "nlp" | item 1 has "survey" |
| check-item-attachment | item 1 has attachment | item 3 has attachment (none) |
| check-attachment-file | ABC12345 exists | ZZZ999 does not |
| check-item-note | item 1 has note | item 3 has note (none) |
| check-note-contains | "Transformer architecture" | "not in any note" |
| check-item-in-trash | "Old Draft Note" | "Attention Is All You Need" |
| check-pref-value | existing pref value | wrong value |
| check-bibtex-count | 3 == 3 | 3 != 10 |
| check-bibtex-title | "Deep Learning" | "Nonexistent Book" |

## JSON Validity Sweep

Every CLI subcommand is invoked with representative args (dummy when needed)
and the stdout is parsed with `json.loads`. Non-parsable stdout is a failure.

## Summary

| Metric | Count |
|---|---|
| Test groups | 15 |
| Total assertions | ~120 |
| Test fixture files | 5 (SQLite DB, 2 PDFs, prefs.js, BibTeX) |
| `check-*` with pos+neg pairs | 17 |
| Error scenarios | 8 |
