# PCManFM Verifier — Test Plan

## Module Overview

The PCManFM verifier inspects filesystem state, PCManFM configuration, GTK bookmarks, and recent files. The primary verification channel is the **filesystem itself** (ground truth). Secondary channels are INI config parsing (`~/.config/pcmanfm/default/pcmanfm.conf`), GTK bookmarks (`~/.config/gtk-3.0/bookmarks`), and recent files XBEL (`~/.local/share/recently-used.xbel`).

**Prerequisites:** PCManFM installed (`apt install pcmanfm`). No special launch flags needed for most endpoints. Process status checks require PCManFM to be running.

---

## Test Groups

### Group 1: Help / Usage
- **What:** `--help`, `help`, `-h`, and no-args invocation
- **Edge cases:** None
- **Expected assertions:** 4 (each flag variant produces non-empty output and exit 0)

### Group 2: Error Handling — Unknown Commands
- **What:** Unknown subcommand returns valid JSON error and exit 1
- **Edge cases:** Empty string, random string, typos of real commands
- **Expected assertions:** 2

### Group 3: Error Handling — Missing Arguments
- **What:** Commands that require arguments called without them
- **Edge cases:** `check-file-exists`, `check-permissions` (needs 2 args), `check-file-contains` (needs 2 args), `get-config-key` (needs 2 args)
- **Expected assertions:** 4

### Group 4: Filesystem Query Endpoints
- **What:** `list-directory`, `file-info`, `file-content`, `tree`, `disk-usage`
- **Edge cases:** Nonexistent path, not-a-directory for `list-directory`, not-a-file for `file-content`, hidden files with `--hidden` flag, empty directory
- **Expected assertions:** 15
  - `list-directory` on test dir (count correct, entries present)
  - `list-directory` with `--hidden` (hidden files appear)
  - `list-directory` on nonexistent path (error)
  - `list-directory` on a file (error — not a directory)
  - `file-info` on file (type, size, permissions present)
  - `file-info` on directory (type = directory)
  - `file-info` on symlink (type = symlink, link_target present)
  - `file-info` on nonexistent (error)
  - `file-content` on text file (content matches)
  - `file-content` on nonexistent (error)
  - `file-content` on directory (error — not a file)
  - `tree` on test dir (recursive children present)
  - `tree` on nonexistent (error)
  - `disk-usage` on test dir (size_bytes > 0)
  - `disk-usage` on nonexistent (error)

### Group 5: Config Endpoints
- **What:** `get-config`, `get-config-key`, `get-sort-settings`, `get-view-mode`
- **Edge cases:** Config file missing, nonexistent section, nonexistent key
- **Expected assertions:** 7
  - `get-config` returns sections dict (or error if no config)
  - `get-config-key` with valid section/key returns value
  - `get-config-key` with bad section returns error
  - `get-config-key` with bad key returns error
  - `get-sort-settings` returns sort_by and sort_order keys
  - `get-view-mode` returns view_mode key
  - `check-config-value` positive and negative

### Group 6: Bookmark Endpoints
- **What:** `get-bookmarks`, `check-bookmark-exists`
- **Edge cases:** No bookmarks file, bookmark exists vs. doesn't
- **Expected assertions:** 4
  - `get-bookmarks` returns list (possibly empty)
  - `check-bookmark-exists` positive (after adding bookmark)
  - `check-bookmark-exists` negative (nonexistent path)
  - Bookmark with label

### Group 7: Recent Files Endpoints
- **What:** `get-recent-files`, `check-recent-file`
- **Edge cases:** No XBEL file, empty recent list
- **Expected assertions:** 3
  - `get-recent-files` returns list
  - `check-recent-file` negative (random string)
  - `get-recent-files` with limit arg

### Group 8: Process Status
- **What:** `status`
- **Edge cases:** PCManFM not running, PCManFM running
- **Expected assertions:** 2
  - `status` when not running: `running` = false
  - `status` when running: `running` = true

### Group 9: Check Endpoints — Positive Cases
- **What:** Every `check-*` endpoint with input that returns true
- **Expected assertions:** 10
  - `check-file-exists` on existing file → `exists` = true
  - `check-dir-exists` on existing dir → `exists` = true, `is_directory` = true
  - `check-file-contains` on file with known text → `contains` = true
  - `check-permissions` with correct octal → `match` = true
  - `check-symlink` on symlink → `is_symlink` = true
  - `check-symlink` with correct target → `target_matches` = true
  - `check-owner` with correct owner → `match` = true
  - `check-file-count` with correct count → `match` = true
  - `check-extension-match` on dir with uniform extensions → `all_match` = true
  - `check-bookmark-exists` on bookmarked path → `exists` = true

### Group 10: Check Endpoints — Negative Cases
- **What:** Every `check-*` endpoint with input that returns false
- **Expected assertions:** 10
  - `check-file-exists` on missing file → `exists` = false
  - `check-dir-exists` on file (not dir) → `is_directory` = false
  - `check-file-contains` on file without text → `contains` = false
  - `check-permissions` with wrong octal → `match` = false
  - `check-symlink` on regular file → `is_symlink` = false
  - `check-symlink` with wrong target → `target_matches` = false
  - `check-owner` with wrong owner → `match` = false
  - `check-file-count` with wrong count → `match` = false
  - `check-extension-match` on dir with mixed extensions → `all_match` = false
  - `check-bookmark-exists` on non-bookmarked path → `exists` = false

### Group 11: JSON Validity Sweep
- **What:** Every CLI subcommand produces valid JSON output
- **Expected assertions:** 22 (one per subcommand with valid args)

---

## Test Fixtures

### 1. Test directory structure: `/home/user/test_pcmanfm/`

```
/home/user/test_pcmanfm/
├── file1.txt          (contains "Hello World\nTest content line 2")
├── file2.txt          (contains "Another file for testing")
├── .hidden_file       (hidden file, contains "secret")
├── script.sh          (mode 0755, contains "#!/bin/bash\necho test")
├── readonly.txt       (mode 0444, contains "read only content")
├── subdir/
│   ├── nested.txt     (contains "nested file content")
│   └── deep/
│       └── bottom.txt (contains "deepest file")
├── images/
│   ├── photo1.png     (empty file with .png extension)
│   ├── photo2.png     (empty file with .png extension)
│   └── photo3.png     (empty file with .png extension)
├── mixed/
│   ├── doc.txt        (empty)
│   ├── pic.png        (empty)
│   └── data.csv       (empty)
├── link_to_file1.txt  -> file1.txt (relative symlink)
└── broken_link        -> /nonexistent/path (broken symlink)
```

**Used by:** Groups 4, 9, 10, 11

### 2. PCManFM config file: `~/.config/pcmanfm/default/pcmanfm.conf`

```ini
[ui]
view_mode=list
show_hidden=0
sort_type=name
sort_order=ascending
sort_folder_first=1

[volume]
mount_on_startup=1
mount_removable=1
autorun=1
```

**Used by:** Groups 5, 9, 10

### 3. GTK bookmarks file: `~/.config/gtk-3.0/bookmarks`

```
file:///home/user/Documents Documents
file:///home/user/test_pcmanfm TestDir
file:///tmp Temp
```

**Used by:** Groups 6, 9, 10

---

## Edge Cases & Error Handling Matrix

| Scenario | Endpoint(s) | Expected behavior |
|---|---|---|
| Unknown subcommand | any | `{"error": "Unknown command: ..."}`, exit 1 |
| Missing required argument | `check-file-exists`, `check-permissions`, etc. | `{"error": "Missing required argument..."}`, exit 1 |
| Nonexistent file/path | `file-info`, `file-content`, `check-*` | `{"error": "...not found..."}` or `exists`/`contains` = false |
| Not a directory | `list-directory` on file | `{"error": "Not a directory: ..."}` |
| Not a file | `file-content` on directory | `{"error": "Not a regular file: ..."}` |
| Config file missing | `get-config`, `get-config-key` | `{"error": "Config not found..."}` |
| Config section missing | `get-config-key` with bad section | `{"error": "Section '...' not found..."}` |
| Config key missing | `get-config-key` with bad key | `{"error": "Key '...' not found..."}` |
| No bookmarks file | `get-bookmarks` | `{"count": 0, "bookmarks": []}` |
| Broken symlink | `check-symlink` | `is_symlink` = true, `target_exists` = false |
| Invalid octal permissions | `check-permissions` | `{"match": false, "error": "Invalid octal..."}` |
| App not running | `status` | `{"running": false, ...}` |
| Empty directory | `list-directory`, `check-file-count` | `count` = 0, `entries` = [] |

---

## Positive / Negative Case Pairs

| Endpoint | Positive Input | Negative Input |
|---|---|---|
| `check-file-exists` | `/home/user/test_pcmanfm/file1.txt` | `/home/user/test_pcmanfm/nonexistent.txt` |
| `check-dir-exists` | `/home/user/test_pcmanfm/subdir` | `/home/user/test_pcmanfm/file1.txt` (exists but not dir) |
| `check-file-contains` | `file1.txt` + `"Hello World"` | `file1.txt` + `"NONEXISTENT_STRING_xyz"` |
| `check-permissions` | `script.sh` + `"755"` | `script.sh` + `"644"` |
| `check-symlink` | `link_to_file1.txt` | `file1.txt` (regular file) |
| `check-symlink` (target) | `link_to_file1.txt` + `file1.txt` | `link_to_file1.txt` + `/wrong/target` |
| `check-owner` | `file1.txt` + `"user"` | `file1.txt` + `"root"` |
| `check-file-count` | `images/` + `3` | `images/` + `99` |
| `check-extension-match` | `images/` + `.png` | `mixed/` + `.png` |
| `check-bookmark-exists` | `/home/user/Documents` | `/home/user/nonexistent_bookmark_dir` |
| `check-config-value` | `ui view_mode list` | `ui view_mode icon` |

---

## JSON Validity Sweep

All commands tested with valid arguments for JSON output:

1. `list-directory /home/user/test_pcmanfm`
2. `list-directory /home/user/test_pcmanfm --hidden`
3. `file-info /home/user/test_pcmanfm/file1.txt`
4. `file-content /home/user/test_pcmanfm/file1.txt`
5. `tree /home/user/test_pcmanfm`
6. `disk-usage /home/user/test_pcmanfm`
7. `get-config`
8. `get-config-key ui view_mode`
9. `get-sort-settings`
10. `get-view-mode`
11. `get-bookmarks`
12. `get-recent-files`
13. `status`
14. `check-file-exists /home/user/test_pcmanfm/file1.txt`
15. `check-dir-exists /home/user/test_pcmanfm/subdir`
16. `check-file-contains /home/user/test_pcmanfm/file1.txt "Hello"`
17. `check-permissions /home/user/test_pcmanfm/file1.txt 644`
18. `check-symlink /home/user/test_pcmanfm/link_to_file1.txt`
19. `check-owner /home/user/test_pcmanfm/file1.txt user`
20. `check-bookmark-exists /home/user/Documents`
21. `check-recent-file test`
22. `check-file-count /home/user/test_pcmanfm/images 3`
23. `check-extension-match /home/user/test_pcmanfm/images .png`
24. `check-config-value ui view_mode list`

---

## Summary

| Metric | Count |
|---|---|
| Test groups | 11 |
| Total assertions | ~81 |
| Test fixtures (files/dirs generated) | 3 (dir tree + config + bookmarks) |
| `check-*` endpoints with pos+neg pairs | 11 |
| Error scenarios covered | 13 |
