"""
Gedit Verifier — programmatic state inspection for gedit in E2B sandbox.

Verification channels (in order of preference):
  1. File system — read saved files directly (primary method)
  2. gsettings — read editor preferences via subprocess
  3. D-Bus (limited) — org.gnome.gedit.CommandLine for open files detection
  4. dconf — read all gedit settings

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/gedit.py file-content /tmp/test.txt")
    sandbox.commands.run("python3 /home/user/verifiers/gedit.py settings")
    sandbox.commands.run("python3 /home/user/verifiers/gedit.py check-file-contains /tmp/test.txt 'hello'")

Usage from Python (inside sandbox or via E2B):
    from verifiers.gedit import GeditVerifier
    v = GeditVerifier()
    content = v.get_file_content("/tmp/test.txt")
    settings = v.get_settings()

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - gsettings / dconf (standard on GNOME desktops)
  - chardet (optional, for encoding detection)
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_cmd(cmd: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    """Run a subprocess and return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return 1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 1, "", f"Command timed out after {timeout}s"


def _gsettings_get(schema: str, key: str) -> dict:
    """Read a single gsettings key."""
    code, stdout, stderr = _run_cmd(["gsettings", "get", schema, key])
    if code != 0:
        return {"error": f"gsettings get failed: {stderr.strip()}"}
    return {"schema": schema, "key": key, "value": stdout.strip()}


def _gsettings_list(schema: str) -> list[dict]:
    """List all keys in a gsettings schema recursively."""
    code, stdout, stderr = _run_cmd(["gsettings", "list-recursively", schema])
    if code != 0:
        return [{"error": f"gsettings list failed: {stderr.strip()}"}]
    results = []
    for line in stdout.strip().splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 3:
            results.append({"schema": parts[0], "key": parts[1], "value": parts[2]})
        elif len(parts) == 2:
            results.append({"schema": parts[0], "key": parts[1], "value": ""})
    return results


def _detect_encoding(file_path: str) -> str:
    """Detect file encoding. Uses chardet if available, otherwise tries common encodings."""
    try:
        import chardet
        with open(file_path, "rb") as f:
            raw = f.read()
        result = chardet.detect(raw)
        return result.get("encoding", "unknown") or "unknown"
    except ImportError:
        pass

    # Fallback: try common encodings in order
    for enc in ("utf-8", "ascii", "latin-1", "utf-16", "cp1252"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                f.read()
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return "unknown"


# ---------------------------------------------------------------------------
# GeditVerifier class
# ---------------------------------------------------------------------------

class GeditVerifier:
    """Stateless verifier — each method call is independent."""

    # === File system: Primary verification channel ===

    def get_file_content(self, file_path: str) -> dict:
        """Read file content and return it.

        Example:
            v.get_file_content("/tmp/test.txt")
            => {"path": "/tmp/test.txt", "content": "Hello world\\n", "size": 12}
        """
        p = Path(file_path)
        if not p.exists():
            return {"error": f"File not found: {file_path}"}
        if not p.is_file():
            return {"error": f"Not a file: {file_path}"}
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            return {"path": str(p), "content": content, "size": p.stat().st_size}
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}

    def get_file_info(self, file_path: str) -> dict:
        """Get file stats: size, modified time, permissions, encoding guess.

        Example:
            v.get_file_info("/tmp/test.txt")
            => {"path": "/tmp/test.txt", "size": 12, "modified": "2026-03-29T10:00:00", ...}
        """
        p = Path(file_path)
        if not p.exists():
            return {"error": f"File not found: {file_path}"}
        try:
            stat = p.stat()
            encoding = _detect_encoding(file_path) if p.is_file() else None
            return {
                "path": str(p),
                "exists": True,
                "is_file": p.is_file(),
                "is_dir": p.is_dir(),
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "permissions": oct(stat.st_mode),
                "encoding": encoding,
            }
        except Exception as e:
            return {"error": f"Failed to get file info: {e}"}

    def get_file_encoding(self, file_path: str) -> dict:
        """Detect file encoding.

        Example:
            v.get_file_encoding("/tmp/test.txt")
            => {"path": "/tmp/test.txt", "encoding": "utf-8"}
        """
        p = Path(file_path)
        if not p.exists():
            return {"error": f"File not found: {file_path}"}
        if not p.is_file():
            return {"error": f"Not a file: {file_path}"}
        encoding = _detect_encoding(file_path)
        return {"path": str(p), "encoding": encoding}

    def get_file_line_count(self, file_path: str) -> dict:
        """Count lines in a file.

        Example:
            v.get_file_line_count("/tmp/test.txt")
            => {"path": "/tmp/test.txt", "line_count": 42}
        """
        p = Path(file_path)
        if not p.exists():
            return {"error": f"File not found: {file_path}"}
        if not p.is_file():
            return {"error": f"Not a file: {file_path}"}
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            line_count = len(content.splitlines())
            return {"path": str(p), "line_count": line_count}
        except Exception as e:
            return {"error": f"Failed to count lines: {e}"}

    def get_file_word_count(self, file_path: str) -> dict:
        """Count words in a file.

        Example:
            v.get_file_word_count("/tmp/test.txt")
            => {"path": "/tmp/test.txt", "word_count": 100}
        """
        p = Path(file_path)
        if not p.exists():
            return {"error": f"File not found: {file_path}"}
        if not p.is_file():
            return {"error": f"Not a file: {file_path}"}
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            word_count = len(content.split())
            return {"path": str(p), "word_count": word_count}
        except Exception as e:
            return {"error": f"Failed to count words: {e}"}

    def get_recent_files(self) -> dict:
        """List recently opened files from GtkRecentManager.

        Reads ~/.local/share/recently-used.xbel for gedit entries.
        """
        recent_path = Path.home() / ".local" / "share" / "recently-used.xbel"
        if not recent_path.exists():
            return {"error": "recently-used.xbel not found", "files": []}

        try:
            content = recent_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"error": f"Failed to read recent files: {e}", "files": []}

        # Parse XBEL for gedit entries (simple regex approach to avoid XML dep issues)
        import re
        files = []
        # Find all bookmark entries
        bookmarks = re.findall(
            r'<bookmark\s+href="([^"]+)"[^>]*>.*?</bookmark>',
            content,
            re.DOTALL,
        )
        for href in bookmarks:
            # Filter to file:// URIs that were opened by gedit
            if href.startswith("file://"):
                file_path = href.replace("file://", "")
                # URL-decode common patterns
                file_path = file_path.replace("%20", " ")
                files.append(file_path)

        # Also check for gedit-specific entries by looking for exec attribute
        gedit_files = []
        gedit_blocks = re.findall(
            r'<bookmark\s+href="(file://[^"]+)"[^>]*>.*?org\.gnome\.gedit.*?</bookmark>',
            content,
            re.DOTALL,
        )
        for href in gedit_blocks:
            file_path = href.replace("file://", "").replace("%20", " ")
            gedit_files.append(file_path)

        return {
            "all_recent_files": files[-20:],
            "gedit_recent_files": gedit_files[-20:],
            "total_count": len(files),
            "gedit_count": len(gedit_files),
        }

    # === gsettings: Editor preferences ===

    def get_settings(self, schema: str | None = None) -> list[dict]:
        """Read gsettings for gedit preferences.

        Example:
            v.get_settings()  # all editor settings
            v.get_settings("org.gnome.gedit.preferences.ui")
        """
        if schema is None:
            schema = "org.gnome.gedit.preferences.editor"
        # If schema doesn't start with org.gnome.gedit, prefix it
        if not schema.startswith("org.gnome.gedit"):
            schema = f"org.gnome.gedit.preferences.{schema}"
        return _gsettings_list(schema)

    def get_setting(self, key: str) -> dict:
        """Read a specific gsettings key.

        The key can be:
          - Full: "org.gnome.gedit.preferences.editor tab-size"
          - Short: "tab-size" (defaults to org.gnome.gedit.preferences.editor)

        Example:
            v.get_setting("org.gnome.gedit.preferences.editor tab-size")
            => {"schema": "org.gnome.gedit.preferences.editor", "key": "tab-size", "value": "uint32 4"}
        """
        parts = key.rsplit(" ", 1)
        if len(parts) == 2 and parts[0].startswith("org.gnome"):
            schema, setting_key = parts
        else:
            schema = "org.gnome.gedit.preferences.editor"
            setting_key = key
        return _gsettings_get(schema, setting_key)

    # === Composite checks ===

    def check_file_exists(self, file_path: str) -> dict:
        """Check if a file exists.

        Example:
            v.check_file_exists("/tmp/test.txt")
            => {"exists": true, "path": "/tmp/test.txt"}
        """
        p = Path(file_path)
        exists = p.exists() and p.is_file()
        result = {"exists": exists, "path": str(p)}
        if exists:
            result["size"] = p.stat().st_size
        return result

    def check_file_contains(self, file_path: str, text: str) -> dict:
        """Check if a file contains specific text.

        Example:
            v.check_file_contains("/tmp/test.txt", "hello")
            => {"contains": true, "path": "/tmp/test.txt", "occurrences": 2}
        """
        p = Path(file_path)
        if not p.exists():
            return {"error": f"File not found: {file_path}", "contains": False}
        if not p.is_file():
            return {"error": f"Not a file: {file_path}", "contains": False}
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            occurrences = content.count(text)
            contains = occurrences > 0
            result: dict[str, Any] = {
                "contains": contains,
                "path": str(p),
                "occurrences": occurrences,
            }
            if contains:
                idx = content.index(text)
                start = max(0, idx - 50)
                end = min(len(content), idx + len(text) + 50)
                result["snippet"] = content[start:end]
            return result
        except Exception as e:
            return {"error": f"Failed to read file: {e}", "contains": False}

    def check_file_line(self, file_path: str, line_num: int, expected_text: str) -> dict:
        """Check if a specific line in a file matches expected text.

        Line numbers are 1-based.

        Example:
            v.check_file_line("/tmp/test.txt", 1, "Hello world")
            => {"matches": true, "line_num": 1, "actual": "Hello world", "expected": "Hello world"}
        """
        p = Path(file_path)
        if not p.exists():
            return {"error": f"File not found: {file_path}", "matches": False}
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            if line_num < 1 or line_num > len(lines):
                return {
                    "error": f"Line {line_num} out of range (file has {len(lines)} lines)",
                    "matches": False,
                    "total_lines": len(lines),
                }
            actual = lines[line_num - 1]
            matches = actual.strip() == expected_text.strip()
            return {
                "matches": matches,
                "line_num": line_num,
                "actual": actual,
                "expected": expected_text,
                "path": str(p),
            }
        except Exception as e:
            return {"error": f"Failed to read file: {e}", "matches": False}

    def check_file_line_count(self, file_path: str, count: int) -> dict:
        """Check if a file has a specific number of lines.

        Example:
            v.check_file_line_count("/tmp/test.txt", 10)
            => {"matches": true, "expected": 10, "actual": 10}
        """
        result = self.get_file_line_count(file_path)
        if "error" in result:
            return {**result, "matches": False}
        actual = result["line_count"]
        return {
            "matches": actual == count,
            "expected": count,
            "actual": actual,
            "path": file_path,
        }

    def check_file_encoding(self, file_path: str, encoding: str) -> dict:
        """Check if a file has a specific encoding.

        Example:
            v.check_file_encoding("/tmp/test.txt", "utf-8")
            => {"matches": true, "expected": "utf-8", "actual": "utf-8"}
        """
        result = self.get_file_encoding(file_path)
        if "error" in result:
            return {**result, "matches": False}
        actual = result["encoding"].lower()
        expected = encoding.lower()
        return {
            "matches": actual == expected,
            "expected": expected,
            "actual": actual,
            "path": file_path,
        }

    def check_setting_value(self, schema_key: str, expected_value: str) -> dict:
        """Check if a gsettings value matches expected.

        schema_key format: "org.gnome.gedit.preferences.editor tab-size"

        Example:
            v.check_setting_value("org.gnome.gedit.preferences.editor tab-size", "uint32 4")
            => {"matches": true, "expected": "uint32 4", "actual": "uint32 4"}
        """
        result = self.get_setting(schema_key)
        if "error" in result:
            return {**result, "matches": False}
        actual = result["value"]
        # Compare normalized: gsettings may return quoted strings, etc.
        matches = actual.strip() == expected_value.strip()
        return {
            "matches": matches,
            "expected": expected_value,
            "actual": actual,
            "schema": result.get("schema", ""),
            "key": result.get("key", ""),
        }

    def check_tab_size(self, expected: int) -> dict:
        """Check if the gedit tab-size setting matches expected value.

        Example:
            v.check_tab_size(4)
            => {"matches": true, "expected": 4, "actual": 4}
        """
        result = _gsettings_get("org.gnome.gedit.preferences.editor", "tab-size")
        if "error" in result:
            return {**result, "matches": False}
        raw = result["value"]
        # gsettings returns e.g. "uint32 4" — extract the number
        try:
            actual = int(raw.split()[-1])
        except (ValueError, IndexError):
            return {"error": f"Could not parse tab-size value: {raw}", "matches": False}
        return {
            "matches": actual == expected,
            "expected": expected,
            "actual": actual,
            "raw_value": raw,
        }

    def check_file_saved(self, file_path: str, min_size: int = 0) -> dict:
        """Check if a file exists and has at least the specified minimum size.

        Example:
            v.check_file_saved("/tmp/test.txt", 10)
            => {"saved": true, "path": "/tmp/test.txt", "size": 42}
        """
        p = Path(file_path)
        if not p.exists():
            return {"saved": False, "path": str(p), "error": "File not found"}
        if not p.is_file():
            return {"saved": False, "path": str(p), "error": "Not a file"}
        size = p.stat().st_size
        saved = size >= min_size
        return {
            "saved": saved,
            "path": str(p),
            "size": size,
            "min_size": min_size,
        }


# ---------------------------------------------------------------------------
# CLI interface — for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

COMMANDS = {
    # Query: File system
    "file-content": ("Read file content", lambda v, args: v.get_file_content(args[0])),
    "file-info": ("Get file stats (size, modified, permissions, encoding)", lambda v, args: v.get_file_info(args[0])),
    "file-encoding": ("Detect file encoding", lambda v, args: v.get_file_encoding(args[0])),
    "file-line-count": ("Count lines in file", lambda v, args: v.get_file_line_count(args[0])),
    "file-word-count": ("Count words in file", lambda v, args: v.get_file_word_count(args[0])),
    "recent-files": ("List recently opened files", lambda v, args: v.get_recent_files()),

    # Query: gsettings
    "settings": ("Read gsettings for gedit preferences", lambda v, args: v.get_settings(args[0] if args else None)),
    "setting": ("Read specific gsetting", lambda v, args: v.get_setting(args[0])),

    # Check: File system
    "check-file-exists": ("Check if file exists", lambda v, args: v.check_file_exists(args[0])),
    "check-file-contains": ("Check if file contains text", lambda v, args: v.check_file_contains(args[0], " ".join(args[1:]))),
    "check-file-line": ("Check specific line content", lambda v, args: v.check_file_line(args[0], int(args[1]), " ".join(args[2:]))),
    "check-file-line-count": ("Check file line count", lambda v, args: v.check_file_line_count(args[0], int(args[1]))),
    "check-file-encoding": ("Check file encoding", lambda v, args: v.check_file_encoding(args[0], args[1])),
    "check-file-saved": ("Check file exists with min size", lambda v, args: v.check_file_saved(args[0], int(args[1]) if len(args) > 1 else 0)),

    # Check: gsettings
    "check-setting-value": ("Check gsetting matches value", lambda v, args: v.check_setting_value(args[0], " ".join(args[1:]))),
    "check-tab-size": ("Check tab size setting", lambda v, args: v.check_tab_size(int(args[0]))),
}


def _print_usage():
    print("Gedit Verifier — query gedit state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print("\nAll output is JSON.")
    print("Primary verification is via saved files on disk and gsettings.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = GeditVerifier()
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
