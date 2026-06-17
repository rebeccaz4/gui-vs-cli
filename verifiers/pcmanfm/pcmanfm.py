"""
PCManFM Verifier — programmatic state inspection for PCManFM file manager in E2B sandbox.

Verification channels (in order of preference):
  1. Filesystem — ground truth for file/directory operations (ls, stat, readlink)
  2. Config files — ~/.config/pcmanfm/default/pcmanfm.conf (INI format)
  3. GTK Bookmarks — ~/.config/gtk-3.0/bookmarks (plain text, one URI per line)
  4. Recent files — ~/.local/share/recently-used.xbel (XML)
  5. Process state — pgrep, /proc

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/pcmanfm.py list-directory /home/user")
    sandbox.commands.run("python3 /home/user/verifiers/pcmanfm.py check-file-exists /home/user/test.txt")
    sandbox.commands.run("python3 /home/user/verifiers/pcmanfm.py get-bookmarks")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - pcmanfm installed (apt install pcmanfm)
  - No special launch flags needed for verification (filesystem is ground truth)
"""

import configparser
import grp
import json
import os
import pwd
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

# ---------------------------------------------------------------------------
# Config paths
# ---------------------------------------------------------------------------

PCMANFM_CONFIG_DIR = Path.home() / ".config" / "pcmanfm" / "default"
PCMANFM_CONF = PCMANFM_CONFIG_DIR / "pcmanfm.conf"
GTK_BOOKMARKS = Path.home() / ".config" / "gtk-3.0" / "bookmarks"
RECENT_XBEL = Path.home() / ".local" / "share" / "recently-used.xbel"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_cmd(cmd: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"


def _format_permissions(mode: int) -> str:
    """Convert numeric mode to rwx string like 'rwxr-xr-x'."""
    perms = ""
    for shift in (6, 3, 0):
        bits = (mode >> shift) & 0o7
        perms += "r" if bits & 4 else "-"
        perms += "w" if bits & 2 else "-"
        perms += "x" if bits & 1 else "-"
    return perms


def _stat_to_dict(path: str) -> dict:
    """Get comprehensive stat info for a path."""
    p = Path(path)
    try:
        st = p.lstat()  # lstat to not follow symlinks
    except FileNotFoundError:
        return {"error": f"Path not found: {path}"}
    except PermissionError:
        return {"error": f"Permission denied: {path}"}

    file_type = "file"
    if stat.S_ISDIR(st.st_mode):
        file_type = "directory"
    elif stat.S_ISLNK(st.st_mode):
        file_type = "symlink"
    elif stat.S_ISFIFO(st.st_mode):
        file_type = "fifo"
    elif stat.S_ISSOCK(st.st_mode):
        file_type = "socket"
    elif stat.S_ISBLK(st.st_mode):
        file_type = "block_device"
    elif stat.S_ISCHR(st.st_mode):
        file_type = "char_device"

    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner = str(st.st_uid)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)

    info = {
        "path": str(p.resolve()) if not p.is_symlink() else str(p),
        "name": p.name,
        "type": file_type,
        "size": st.st_size,
        "permissions_octal": oct(stat.S_IMODE(st.st_mode)),
        "permissions": _format_permissions(stat.S_IMODE(st.st_mode)),
        "owner": owner,
        "group": group,
        "uid": st.st_uid,
        "gid": st.st_gid,
        "modified": st.st_mtime,
        "accessed": st.st_atime,
        "created": st.st_ctime,
    }

    if file_type == "symlink":
        try:
            info["link_target"] = os.readlink(str(p))
            info["link_target_exists"] = Path(os.readlink(str(p))).exists() if os.path.isabs(os.readlink(str(p))) else (p.parent / os.readlink(str(p))).exists()
        except OSError:
            info["link_target"] = None
            info["link_target_exists"] = False

    return info


def _parse_config() -> dict | None:
    """Parse pcmanfm.conf (INI format) and return as nested dict."""
    if not PCMANFM_CONF.exists():
        return None
    config = configparser.ConfigParser()
    try:
        config.read(str(PCMANFM_CONF))
        result = {}
        for section in config.sections():
            result[section] = dict(config[section])
        return result
    except Exception:
        return None


def _parse_bookmarks() -> list[dict]:
    """Parse GTK bookmarks file. Each line is: URI [optional label]."""
    if not GTK_BOOKMARKS.exists():
        return []
    bookmarks = []
    with open(GTK_BOOKMARKS, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ", 1)
            uri = parts[0]
            label = parts[1] if len(parts) > 1 else None
            # Convert file:// URI to path
            parsed = urlparse(uri)
            if parsed.scheme == "file":
                path = unquote(parsed.path)
            else:
                path = uri
            bookmarks.append({
                "uri": uri,
                "path": path,
                "label": label,
                "exists": os.path.exists(path) if parsed.scheme == "file" else None,
            })
    return bookmarks


def _parse_recent_files(limit: int = 50) -> list[dict]:
    """Parse recently-used.xbel (XML) and return recent files."""
    if not RECENT_XBEL.exists():
        return []
    try:
        tree = ET.parse(str(RECENT_XBEL))
        root = tree.getroot()
    except ET.ParseError:
        return []

    ns = {"bookmark": "http://www.freedesktop.org/standards/desktop-bookmarks"}
    items = []
    for bookmark in root.findall("bookmark"):
        href = bookmark.get("href", "")
        modified = bookmark.get("modified", "")
        visited = bookmark.get("visited", "")
        added = bookmark.get("added", "")

        # Get mime type from info/metadata
        mime_type = None
        info = bookmark.find("info")
        if info is not None:
            for metadata in info.findall("metadata"):
                mime_node = metadata.find("{http://www.freedesktop.org/standards/shared-mime-info}mime-type")
                if mime_node is not None:
                    mime_type = mime_node.get("type")

        parsed = urlparse(href)
        path = unquote(parsed.path) if parsed.scheme == "file" else href

        items.append({
            "uri": href,
            "path": path,
            "modified": modified,
            "visited": visited,
            "added": added,
            "mime_type": mime_type,
        })

    # Sort by modified date descending, return limited
    items.sort(key=lambda x: x.get("modified", ""), reverse=True)
    return items[:limit]


# ---------------------------------------------------------------------------
# PCManFMVerifier class
# ---------------------------------------------------------------------------

class PCManFMVerifier:
    """Stateless verifier — each method call is independent."""

    # === Filesystem: Core content / directory state ===

    def list_directory(self, path: str, show_hidden: bool = False) -> dict:
        """List files and directories in a path.

        Returns:
            {"path": "/home/user", "count": 5, "entries": [{name, type, size, permissions, ...}, ...]}
        """
        p = Path(path)
        if not p.exists():
            return {"error": f"Path not found: {path}"}
        if not p.is_dir():
            return {"error": f"Not a directory: {path}"}

        entries = []
        try:
            for item in sorted(p.iterdir(), key=lambda x: x.name):
                if not show_hidden and item.name.startswith("."):
                    continue
                info = _stat_to_dict(str(item))
                if "error" not in info:
                    entries.append(info)
        except PermissionError:
            return {"error": f"Permission denied: {path}"}

        return {
            "path": str(p.resolve()),
            "count": len(entries),
            "entries": entries,
        }

    def get_file_info(self, path: str) -> dict:
        """Get detailed stat information for a file or directory.

        Returns:
            {"path": "...", "name": "...", "type": "file", "size": 1234,
             "permissions": "rwxr-xr-x", "permissions_octal": "0o755",
             "owner": "user", "group": "user", ...}
        """
        return _stat_to_dict(path)

    def get_file_content(self, path: str, max_bytes: int = 10000) -> dict:
        """Read text file contents (up to max_bytes).

        Returns:
            {"path": "...", "content": "...", "size": 1234, "truncated": false}
        """
        p = Path(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}
        if not p.is_file():
            return {"error": f"Not a regular file: {path}"}
        try:
            size = p.stat().st_size
            with open(p, "r", errors="replace") as f:
                content = f.read(max_bytes)
            return {
                "path": str(p.resolve()),
                "content": content,
                "size": size,
                "truncated": size > max_bytes,
            }
        except PermissionError:
            return {"error": f"Permission denied: {path}"}

    def get_tree(self, path: str, max_depth: int = 3, show_hidden: bool = False) -> dict:
        """Get a recursive directory tree.

        Returns:
            {"path": "...", "tree": {"name": "dir", "type": "directory",
             "children": [{"name": "file.txt", "type": "file", "size": 100}, ...]}}
        """
        p = Path(path)
        if not p.exists():
            return {"error": f"Path not found: {path}"}
        if not p.is_dir():
            return {"error": f"Not a directory: {path}"}

        def _build_tree(current: Path, depth: int) -> dict:
            info = _stat_to_dict(str(current))
            if "error" in info:
                return info
            node = {
                "name": current.name or str(current),
                "type": info["type"],
            }
            if info["type"] == "file":
                node["size"] = info["size"]
            elif info["type"] == "symlink":
                node["link_target"] = info.get("link_target")
            if info["type"] == "directory" and depth < max_depth:
                children = []
                try:
                    for child in sorted(current.iterdir(), key=lambda x: x.name):
                        if not show_hidden and child.name.startswith("."):
                            continue
                        children.append(_build_tree(child, depth + 1))
                except PermissionError:
                    node["error"] = "Permission denied"
                node["children"] = children
            return node

        return {"path": str(p.resolve()), "tree": _build_tree(p, 0)}

    def get_disk_usage(self, path: str) -> dict:
        """Get disk usage for a path using du.

        Returns:
            {"path": "...", "size_bytes": 12345, "size_human": "12K"}
        """
        p = Path(path)
        if not p.exists():
            return {"error": f"Path not found: {path}"}
        code, stdout, stderr = _run_cmd(["du", "-sb", str(p)])
        if code != 0:
            return {"error": f"du failed: {stderr}"}
        parts = stdout.split("\t")
        size_bytes = int(parts[0]) if parts else 0
        # Human-readable
        code2, stdout2, _ = _run_cmd(["du", "-sh", str(p)])
        size_human = stdout2.split("\t")[0] if code2 == 0 else str(size_bytes)
        return {"path": str(p), "size_bytes": size_bytes, "size_human": size_human}

    # === Settings / Preferences / Configuration ===

    def get_config(self) -> dict:
        """Read the full pcmanfm.conf configuration.

        Returns:
            {"config_path": "...", "sections": {"ui": {"view_mode": "list", ...}, ...}}
        """
        config = _parse_config()
        if config is None:
            return {"error": f"Config not found at {PCMANFM_CONF}"}
        return {"config_path": str(PCMANFM_CONF), "sections": config}

    def get_config_key(self, section: str, key: str) -> dict:
        """Read a specific key from pcmanfm.conf.

        Example:
            get_config_key("ui", "view_mode")
            => {"section": "ui", "key": "view_mode", "value": "list"}
        """
        config = _parse_config()
        if config is None:
            return {"error": f"Config not found at {PCMANFM_CONF}"}
        sect = config.get(section)
        if sect is None:
            return {"error": f"Section '{section}' not found. Available: {list(config.keys())}"}
        val = sect.get(key)
        if val is None:
            return {"error": f"Key '{key}' not found in [{section}]. Available: {list(sect.keys())}"}
        return {"section": section, "key": key, "value": val}

    def get_sort_settings(self) -> dict:
        """Get file sorting preferences from config.

        Returns:
            {"sort_by": "name", "sort_order": "ascending", "folders_first": true}
        """
        config = _parse_config()
        if config is None:
            return {"error": f"Config not found at {PCMANFM_CONF}"}

        # PCManFM stores sort settings in various sections
        ui = config.get("ui", {})
        return {
            "sort_by": ui.get("sort_type", ui.get("sort", "name")),
            "sort_order": ui.get("sort_order", "ascending"),
            "folders_first": ui.get("sort_folder_first", ui.get("folder_first", "1")) == "1",
        }

    def get_view_mode(self) -> dict:
        """Get the current view mode (icon/list/compact/thumbnail).

        Returns:
            {"view_mode": "list", "show_hidden": false}
        """
        config = _parse_config()
        if config is None:
            return {"error": f"Config not found at {PCMANFM_CONF}"}
        ui = config.get("ui", {})
        return {
            "view_mode": ui.get("view_mode", "icon"),
            "show_hidden": ui.get("show_hidden", "0") == "1",
        }

    # === Bookmarks ===

    def get_bookmarks(self) -> dict:
        """List all GTK bookmarks (used by PCManFM sidebar).

        Returns:
            {"bookmarks_path": "...", "count": 3, "bookmarks": [{uri, path, label, exists}, ...]}
        """
        bookmarks = _parse_bookmarks()
        return {
            "bookmarks_path": str(GTK_BOOKMARKS),
            "count": len(bookmarks),
            "bookmarks": bookmarks,
        }

    # === Recent files ===

    def get_recent_files(self, limit: int = 50) -> dict:
        """List recently accessed files from the XBEL database.

        Returns:
            {"count": 5, "files": [{uri, path, modified, mime_type}, ...]}
        """
        files = _parse_recent_files(limit)
        return {"count": len(files), "files": files}

    # === Process state ===

    def status(self) -> dict:
        """Check if PCManFM is running.

        Returns:
            {"running": true, "pid": "1234", "process_count": 1}
        """
        code, stdout, _ = _run_cmd(["pgrep", "-x", "pcmanfm"])
        pids = [p.strip() for p in stdout.split("\n") if p.strip()] if code == 0 else []
        return {
            "running": code == 0 and len(pids) > 0,
            "pid": pids[0] if pids else None,
            "pids": pids,
            "process_count": len(pids),
        }

    # === Composite checks (RL verification patterns) ===

    def check_file_exists(self, path: str) -> dict:
        """Check if a file exists at the given path.

        Returns:
            {"exists": true, "type": "file", "size": 1234, "permissions": "rw-r--r--"}
        """
        p = Path(path)
        if not p.exists() and not p.is_symlink():
            return {"exists": False, "path": path}
        info = _stat_to_dict(path)
        if "error" in info:
            return {"exists": False, "path": path, "error": info["error"]}
        return {
            "exists": True,
            "path": path,
            "type": info["type"],
            "size": info.get("size"),
            "permissions": info.get("permissions"),
        }

    def check_dir_exists(self, path: str) -> dict:
        """Check if a directory exists at the given path.

        Returns:
            {"exists": true, "is_directory": true, "entry_count": 5}
        """
        p = Path(path)
        exists = p.exists()
        is_dir = p.is_dir() if exists else False
        entry_count = None
        if is_dir:
            try:
                entry_count = len(list(p.iterdir()))
            except PermissionError:
                entry_count = -1
        return {
            "exists": exists,
            "is_directory": is_dir,
            "path": path,
            "entry_count": entry_count,
        }

    def check_file_contains(self, path: str, text: str) -> dict:
        """Check if a text file contains the given string.

        Returns:
            {"contains": true, "path": "...", "occurrences": 2, "snippet": "...context..."}
        """
        p = Path(path)
        if not p.exists():
            return {"contains": False, "path": path, "error": "File not found"}
        if not p.is_file():
            return {"contains": False, "path": path, "error": "Not a regular file"}
        try:
            content = p.read_text(errors="replace")
        except PermissionError:
            return {"contains": False, "path": path, "error": "Permission denied"}

        lower_content = content.lower()
        lower_text = text.lower()
        found = lower_text in lower_content
        occurrences = lower_content.count(lower_text)

        snippet = None
        if found:
            idx = lower_content.index(lower_text)
            start = max(0, idx - 50)
            end = min(len(content), idx + len(text) + 50)
            snippet = content[start:end]

        return {
            "contains": found,
            "path": path,
            "occurrences": occurrences,
            "snippet": snippet,
        }

    def check_permissions(self, path: str, expected: str) -> dict:
        """Check if a file has the expected permissions (octal string like '755' or '0644').

        Returns:
            {"match": true, "expected": "755", "actual": "755", "actual_rwx": "rwxr-xr-x"}
        """
        p = Path(path)
        if not p.exists() and not p.is_symlink():
            return {"match": False, "path": path, "error": "Path not found"}

        try:
            st = p.lstat()
        except PermissionError:
            return {"match": False, "path": path, "error": "Permission denied"}

        actual_mode = stat.S_IMODE(st.st_mode)
        # Normalize expected: strip leading '0o' or '0' prefix
        expected_clean = expected.lstrip("0o").lstrip("0") or "0"
        actual_octal = oct(actual_mode).replace("0o", "")

        # Compare numeric values
        try:
            expected_int = int(expected_clean, 8)
        except ValueError:
            return {"match": False, "error": f"Invalid octal permission: {expected}"}

        return {
            "match": actual_mode == expected_int,
            "path": path,
            "expected": expected_clean,
            "actual": actual_octal,
            "actual_rwx": _format_permissions(actual_mode),
        }

    def check_symlink(self, path: str, expected_target: str | None = None) -> dict:
        """Check if a path is a symlink, optionally verifying its target.

        Returns:
            {"is_symlink": true, "target": "/home/user/real_file",
             "target_exists": true, "target_matches": true}
        """
        p = Path(path)
        if not p.is_symlink():
            exists = p.exists()
            return {
                "is_symlink": False,
                "path": path,
                "exists": exists,
                "type": "directory" if p.is_dir() else ("file" if p.is_file() else "missing"),
            }

        target = os.readlink(str(p))
        # Resolve relative targets against parent dir
        if not os.path.isabs(target):
            target_abs = str((p.parent / target).resolve())
        else:
            target_abs = target
        target_exists = os.path.exists(target_abs)

        result = {
            "is_symlink": True,
            "path": path,
            "target": target,
            "target_exists": target_exists,
        }
        if expected_target is not None:
            result["target_matches"] = (target == expected_target or
                                         target_abs == expected_target or
                                         os.path.realpath(str(p)) == os.path.realpath(expected_target))
        return result

    def check_owner(self, path: str, expected_owner: str) -> dict:
        """Check if a file/directory is owned by the expected user.

        Returns:
            {"match": true, "expected": "user", "actual": "user"}
        """
        info = _stat_to_dict(path)
        if "error" in info:
            return {"match": False, "path": path, "error": info["error"]}
        return {
            "match": info["owner"] == expected_owner,
            "path": path,
            "expected": expected_owner,
            "actual": info["owner"],
        }

    def check_bookmark_exists(self, path_or_label: str) -> dict:
        """Check if a path or label exists in GTK bookmarks.

        Returns:
            {"exists": true, "bookmark": {uri, path, label}}
        """
        bookmarks = _parse_bookmarks()
        for bm in bookmarks:
            if (path_or_label == bm["path"] or
                path_or_label == bm.get("label") or
                path_or_label == bm["uri"] or
                path_or_label in bm["path"]):
                return {"exists": True, "bookmark": bm}
        return {"exists": False, "bookmarks_checked": len(bookmarks)}

    def check_recent_file(self, path_substring: str) -> dict:
        """Check if a file matching the substring is in recent files.

        Returns:
            {"found": true, "match": {uri, path, modified, mime_type}}
        """
        files = _parse_recent_files(limit=200)
        for f in files:
            if path_substring.lower() in f.get("path", "").lower():
                return {"found": True, "match": f}
        return {"found": False, "files_checked": len(files)}

    def check_file_count(self, path: str, expected_count: int, show_hidden: bool = False) -> dict:
        """Check if a directory contains exactly the expected number of entries.

        Returns:
            {"match": true, "expected": 5, "actual": 5}
        """
        p = Path(path)
        if not p.exists():
            return {"match": False, "path": path, "error": "Path not found"}
        if not p.is_dir():
            return {"match": False, "path": path, "error": "Not a directory"}
        try:
            entries = list(p.iterdir())
            if not show_hidden:
                entries = [e for e in entries if not e.name.startswith(".")]
            actual = len(entries)
        except PermissionError:
            return {"match": False, "path": path, "error": "Permission denied"}

        return {
            "match": actual == expected_count,
            "path": path,
            "expected": expected_count,
            "actual": actual,
        }

    def check_extension_match(self, path: str, expected_extension: str) -> dict:
        """Check if files in a directory all have the expected extension.

        Returns:
            {"all_match": true, "total": 5, "matching": 5, "non_matching": []}
        """
        p = Path(path)
        if not p.exists():
            return {"all_match": False, "error": "Path not found"}
        if not p.is_dir():
            return {"all_match": False, "error": "Not a directory"}

        ext = expected_extension if expected_extension.startswith(".") else f".{expected_extension}"
        try:
            files = [f for f in p.iterdir() if f.is_file()]
        except PermissionError:
            return {"all_match": False, "error": "Permission denied"}

        matching = [f.name for f in files if f.suffix == ext]
        non_matching = [f.name for f in files if f.suffix != ext]
        return {
            "all_match": len(non_matching) == 0 and len(matching) > 0,
            "total": len(files),
            "matching": len(matching),
            "non_matching": non_matching[:20],
        }

    def check_config_value(self, section: str, key: str, expected_value: str) -> dict:
        """Check if a pcmanfm.conf key matches the expected value.

        Returns:
            {"match": true, "section": "ui", "key": "view_mode",
             "expected": "list", "actual": "list"}
        """
        result = self.get_config_key(section, key)
        if "error" in result:
            return {"match": False, **result}
        actual = result["value"]
        return {
            "match": str(actual) == str(expected_value),
            "section": section,
            "key": key,
            "expected": expected_value,
            "actual": actual,
        }


# ---------------------------------------------------------------------------
# CLI interface — for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

COMMANDS = {
    # Filesystem: core content
    "list-directory": ("List files in a directory", lambda v, args: v.list_directory(args[0], show_hidden="--hidden" in args)),
    "file-info": ("Get file/directory stat info", lambda v, args: v.get_file_info(args[0])),
    "file-content": ("Read text file contents", lambda v, args: v.get_file_content(args[0], int(args[1]) if len(args) > 1 else 10000)),
    "tree": ("Recursive directory tree", lambda v, args: v.get_tree(args[0], int(args[1]) if len(args) > 1 else 3)),
    "disk-usage": ("Get disk usage for a path", lambda v, args: v.get_disk_usage(args[0])),

    # Settings / preferences
    "get-config": ("Read full pcmanfm.conf", lambda v, args: v.get_config()),
    "get-config-key": ("Read specific config key", lambda v, args: v.get_config_key(args[0], args[1])),
    "get-sort-settings": ("Get sort preferences", lambda v, args: v.get_sort_settings()),
    "get-view-mode": ("Get view mode setting", lambda v, args: v.get_view_mode()),

    # Bookmarks
    "get-bookmarks": ("List GTK bookmarks", lambda v, args: v.get_bookmarks()),

    # Recent files
    "get-recent-files": ("List recently accessed files", lambda v, args: v.get_recent_files(int(args[0]) if args else 50)),

    # Process state
    "status": ("Check if PCManFM is running", lambda v, args: v.status()),

    # Composite checks
    "check-file-exists": ("Check if file exists", lambda v, args: v.check_file_exists(args[0])),
    "check-dir-exists": ("Check if directory exists", lambda v, args: v.check_dir_exists(args[0])),
    "check-file-contains": ("Check if file contains text", lambda v, args: v.check_file_contains(args[0], args[1])),
    "check-permissions": ("Check file permissions", lambda v, args: v.check_permissions(args[0], args[1])),
    "check-symlink": ("Check symlink and target", lambda v, args: v.check_symlink(args[0], args[1] if len(args) > 1 else None)),
    "check-owner": ("Check file owner", lambda v, args: v.check_owner(args[0], args[1])),
    "check-bookmark-exists": ("Check if path is bookmarked", lambda v, args: v.check_bookmark_exists(args[0])),
    "check-recent-file": ("Check if file is in recent", lambda v, args: v.check_recent_file(args[0])),
    "check-file-count": ("Check directory entry count", lambda v, args: v.check_file_count(args[0], int(args[1]), show_hidden="--hidden" in args)),
    "check-extension-match": ("Check files match extension", lambda v, args: v.check_extension_match(args[0], args[1])),
    "check-config-value": ("Check config key value", lambda v, args: v.check_config_value(args[0], args[1], args[2])),
}


def _print_usage():
    print("PCManFM Verifier — query PCManFM / filesystem state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nAll output is JSON. Filesystem is ground truth; config at {PCMANFM_CONF}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = PCManFMVerifier()
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
