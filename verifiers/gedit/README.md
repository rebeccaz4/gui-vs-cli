# Gedit Verifier

Programmatic state inspection for gedit (GNOME Text Editor) in E2B desktop sandboxes.

## Verification Channels

| Channel | Reliability | Notes |
|---------|------------|-------|
| **File system** | Primary | Read saved files directly — most reliable |
| **gsettings** | High | Read editor preferences (tab-size, font, etc.) |
| **D-Bus** | Limited | `org.gnome.gedit.CommandLine` — open file detection |
| **dconf** | High | Read all gedit settings directly |
| **AT-SPI** | Good | GTK app — full access to editor text and cursor |

## Usage

### CLI (via sandbox.commands.run)

```bash
# Query endpoints
python3 /home/user/verifiers/gedit.py file-content /tmp/test.txt
python3 /home/user/verifiers/gedit.py file-info /tmp/test.txt
python3 /home/user/verifiers/gedit.py file-encoding /tmp/test.txt
python3 /home/user/verifiers/gedit.py file-line-count /tmp/test.txt
python3 /home/user/verifiers/gedit.py file-word-count /tmp/test.txt
python3 /home/user/verifiers/gedit.py recent-files
python3 /home/user/verifiers/gedit.py settings
python3 /home/user/verifiers/gedit.py settings org.gnome.gedit.preferences.ui
python3 /home/user/verifiers/gedit.py setting tab-size
python3 /home/user/verifiers/gedit.py setting "org.gnome.gedit.preferences.editor tab-size"

# Check endpoints
python3 /home/user/verifiers/gedit.py check-file-exists /tmp/test.txt
python3 /home/user/verifiers/gedit.py check-file-contains /tmp/test.txt "hello world"
python3 /home/user/verifiers/gedit.py check-file-line /tmp/test.txt 1 "first line"
python3 /home/user/verifiers/gedit.py check-file-line-count /tmp/test.txt 10
python3 /home/user/verifiers/gedit.py check-file-encoding /tmp/test.txt utf-8
python3 /home/user/verifiers/gedit.py check-setting-value "org.gnome.gedit.preferences.editor tab-size" "uint32 4"
python3 /home/user/verifiers/gedit.py check-tab-size 4
python3 /home/user/verifiers/gedit.py check-file-saved /tmp/test.txt 10
```

### Python API

```python
from verifiers.gedit import GeditVerifier

v = GeditVerifier()

# Query
content = v.get_file_content("/tmp/test.txt")
info = v.get_file_info("/tmp/test.txt")
settings = v.get_settings()
tab_setting = v.get_setting("tab-size")

# Check
v.check_file_exists("/tmp/test.txt")
v.check_file_contains("/tmp/test.txt", "hello")
v.check_file_line("/tmp/test.txt", 1, "first line")
v.check_file_line_count("/tmp/test.txt", 10)
v.check_file_encoding("/tmp/test.txt", "utf-8")
v.check_tab_size(4)
v.check_file_saved("/tmp/test.txt", 10)
```

## Output Format

All output is JSON. Query endpoints return data dicts/lists. Check endpoints return dicts with a boolean key (`exists`, `contains`, `matches`, `saved`) plus supporting details.

```json
{"contains": true, "path": "/tmp/test.txt", "occurrences": 2, "snippet": "...hello world..."}
```

```json
{"matches": false, "expected": 8, "actual": 4, "raw_value": "uint32 4"}
```

## Endpoints

### Query

| Command | Args | Description |
|---------|------|-------------|
| `file-content` | `<path>` | Read file content |
| `file-info` | `<path>` | File stats (size, modified, permissions, encoding) |
| `file-encoding` | `<path>` | Detect file encoding |
| `file-line-count` | `<path>` | Count lines in file |
| `file-word-count` | `<path>` | Count words in file |
| `recent-files` | | Recently opened files from GtkRecentManager |
| `settings` | `[schema]` | gsettings for gedit preferences |
| `setting` | `<key>` | Specific gsetting value |

### Check

| Command | Args | Description |
|---------|------|-------------|
| `check-file-exists` | `<path>` | File exists |
| `check-file-contains` | `<path> <text>` | File contains text |
| `check-file-line` | `<path> <line_num> <text>` | Specific line matches |
| `check-file-line-count` | `<path> <count>` | Line count matches |
| `check-file-encoding` | `<path> <encoding>` | Encoding matches |
| `check-setting-value` | `<schema.key> <value>` | gsetting matches value |
| `check-tab-size` | `<expected>` | Tab size setting matches |
| `check-file-saved` | `<path> [min_size]` | File exists with min size |

## Running Tests

```bash
python verifiers/gedit/test_gedit.py
```

Requires `e2b_desktop` and a `desktop-all-apps` sandbox template.
