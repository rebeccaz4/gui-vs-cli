"""
Obsidian Verifier — programmatic state inspection for Obsidian in E2B sandbox.

Verification channels (in order of preference):
  1. Markdown files on disk — notes are plain .md files, trivially readable
  2. JSON config files — .obsidian/app.json, appearance.json, hotkeys.json,
     workspace.json, community-plugins.json, core-plugins.json, bookmarks.json
  3. Global config — ~/.config/obsidian/obsidian.json

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/obsidian.py list-notes /home/user/vault")
    sandbox.commands.run("python3 /home/user/verifiers/obsidian.py get-note /home/user/vault 'My Note'")
    sandbox.commands.run("python3 /home/user/verifiers/obsidian.py check-note-contains /home/user/vault 'My Note' 'hello'")

Usage from Python (inside sandbox or via E2B):
    from verifiers.obsidian import ObsidianVerifier
    v = ObsidianVerifier("/home/user/vault")
    notes = v.list_notes()
    content = v.get_note("My Note")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - Obsidian vault directory on disk
  - No external dependencies (stdlib only)
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OBSIDIAN_CONFIG_DIR = ".obsidian"

GLOBAL_CONFIG_PATHS = [
    Path.home() / ".config" / "obsidian" / "obsidian.json",
    Path.home() / ".config" / "Obsidian" / "obsidian.json",
]


def _find_global_config() -> Path | None:
    """Find the global Obsidian config file."""
    for p in GLOBAL_CONFIG_PATHS:
        if p.exists():
            return p
    return None


def _find_vault_dir(vault_path: str) -> Path | None:
    """Validate and return the vault directory."""
    p = Path(vault_path)
    if p.exists() and p.is_dir():
        return p
    return None


# ---------------------------------------------------------------------------
# JSON / file helpers
# ---------------------------------------------------------------------------

def _read_json_file(path: Path) -> dict | list:
    """Read and parse a JSON file, returning error dict on failure."""
    if not path.exists():
        return {"error": f"File not found: {path}"}
    try:
        with open(path) as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON in {path}: {e}"}
    except OSError as e:
        return {"error": f"Cannot read {path}: {e}"}


def _parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from a Markdown file.

    Returns dict of key-value pairs. Handles simple YAML (no nested structures
    beyond lists). Returns empty dict if no frontmatter found.
    """
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end == -1:
        return {}
    yaml_block = content[3:end].strip()
    if not yaml_block:
        return {}

    result = {}
    current_key = None
    current_list = None

    for line in yaml_block.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # List item under current key
        if stripped.startswith("- ") and current_key is not None:
            if current_list is None:
                current_list = []
            item = stripped[2:].strip().strip('"').strip("'")
            current_list.append(item)
            continue

        # Save accumulated list
        if current_list is not None and current_key is not None:
            result[current_key] = current_list
            current_list = None
            current_key = None

        # Key-value pair
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                # Might be followed by a list
                current_key = key
                current_list = None
            else:
                # Remove quotes
                val = val.strip('"').strip("'")
                # Try to parse as bool/int/float
                if val.lower() in ("true", "yes"):
                    result[key] = True
                elif val.lower() in ("false", "no"):
                    result[key] = False
                else:
                    try:
                        result[key] = int(val)
                    except ValueError:
                        try:
                            result[key] = float(val)
                        except ValueError:
                            result[key] = val
                current_key = key

    # Save any trailing list
    if current_list is not None and current_key is not None:
        result[current_key] = current_list
    elif current_key is not None and current_key not in result:
        result[current_key] = None

    return result


def _extract_tags(content: str) -> list[str]:
    """Extract all tags (#tag) from note content, excluding code blocks and frontmatter."""
    # Remove frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:]

    # Remove code blocks (``` ... ```)
    content = re.sub(r"```[\s\S]*?```", "", content)
    # Remove inline code (`...`)
    content = re.sub(r"`[^`]+`", "", content)

    # Find tags: # followed by word chars, /, or -
    tags = re.findall(r"(?<!\w)#([a-zA-Z0-9_/\-]+)", content)
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def _extract_frontmatter_tags(frontmatter: dict) -> list[str]:
    """Extract tags from frontmatter 'tags' field."""
    tags_val = frontmatter.get("tags")
    if tags_val is None:
        return []
    if isinstance(tags_val, list):
        return [str(t) for t in tags_val]
    if isinstance(tags_val, str):
        # Comma-separated or space-separated
        return [t.strip().lstrip("#") for t in re.split(r"[,\s]+", tags_val) if t.strip()]
    return []


def _extract_wikilinks(content: str) -> list[dict]:
    """Extract [[wikilinks]] from note content.

    Returns list of {"target": ..., "alias": ..., "heading": ...}
    """
    # Remove code blocks
    clean = re.sub(r"```[\s\S]*?```", "", content)
    clean = re.sub(r"`[^`]+`", "", clean)

    links = []
    for match in re.finditer(r"\[\[([^\]]+)\]\]", clean):
        raw = match.group(1)
        alias = None
        heading = None
        target = raw

        # Handle alias: [[target|alias]]
        if "|" in raw:
            target, alias = raw.split("|", 1)
            target = target.strip()
            alias = alias.strip()

        # Handle heading: [[target#heading]]
        if "#" in target:
            target, heading = target.split("#", 1)
            target = target.strip()
            heading = heading.strip()

        links.append({
            "target": target,
            "alias": alias,
            "heading": heading,
        })
    return links


def _extract_headings(content: str) -> list[dict]:
    """Extract Markdown headings from note content."""
    # Remove frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:]

    # Remove code blocks
    content = re.sub(r"```[\s\S]*?```", "", content)

    headings = []
    for match in re.finditer(r"^(#{1,6})\s+(.+)$", content, re.MULTILINE):
        level = len(match.group(1))
        text = match.group(2).strip()
        headings.append({"level": level, "text": text})
    return headings


# ---------------------------------------------------------------------------
# ObsidianVerifier class
# ---------------------------------------------------------------------------

class ObsidianVerifier:
    """Stateless verifier — each method call is independent."""

    def __init__(self, vault_path: str):
        self.vault = Path(vault_path)
        self.config_dir = self.vault / OBSIDIAN_CONFIG_DIR

    def _validate_vault(self) -> dict | None:
        """Return error dict if vault doesn't exist, else None."""
        if not self.vault.exists():
            return {"error": f"Vault not found: {self.vault}"}
        if not self.vault.is_dir():
            return {"error": f"Vault path is not a directory: {self.vault}"}
        return None

    def _resolve_note_path(self, note_name: str) -> Path | None:
        """Resolve a note name to its file path.

        Accepts:
          - Full path: "folder/subfolder/My Note.md"
          - Name without extension: "My Note"
          - Name with extension: "My Note.md"
        """
        # If it already has .md extension
        if note_name.endswith(".md"):
            candidate = self.vault / note_name
            if candidate.exists():
                return candidate
        else:
            candidate = self.vault / f"{note_name}.md"
            if candidate.exists():
                return candidate
            # Also try with .md
            candidate = self.vault / note_name
            if candidate.exists() and candidate.is_file():
                return candidate

        # Search recursively
        name_with_ext = note_name if note_name.endswith(".md") else f"{note_name}.md"
        basename = Path(name_with_ext).name
        for p in self.vault.rglob("*.md"):
            if p.name == basename:
                return p
        return None

    # === Core content ===

    def get_note(self, note_name: str) -> dict:
        """Read a note's full content.

        Example:
            v.get_note("My Note")
            => {"path": "My Note.md", "content": "# My Note\n...", "size": 234}
        """
        err = self._validate_vault()
        if err:
            return err

        path = self._resolve_note_path(note_name)
        if not path:
            return {"error": f"Note not found: {note_name}"}

        try:
            content = path.read_text(encoding="utf-8")
            rel = path.relative_to(self.vault)
            return {
                "path": str(rel),
                "content": content,
                "size": len(content),
            }
        except OSError as e:
            return {"error": f"Cannot read note: {e}"}

    def get_note_frontmatter(self, note_name: str) -> dict:
        """Parse YAML frontmatter from a note.

        Example:
            v.get_note_frontmatter("My Note")
            => {"path": "My Note.md", "frontmatter": {"title": "My Note", "tags": ["work", "project"]}}
        """
        result = self.get_note(note_name)
        if "error" in result:
            return result

        fm = _parse_frontmatter(result["content"])
        return {
            "path": result["path"],
            "frontmatter": fm,
            "has_frontmatter": len(fm) > 0,
        }

    def list_notes(self, folder: str | None = None) -> dict:
        """List all notes in the vault (or a subfolder).

        Example:
            v.list_notes()
            => {"count": 5, "notes": [{"path": "Note1.md", "size": 123}, ...]}
        """
        err = self._validate_vault()
        if err:
            return err

        base = self.vault / folder if folder else self.vault
        if not base.exists():
            return {"error": f"Folder not found: {folder}"}

        notes = []
        for p in sorted(base.rglob("*.md")):
            # Skip .obsidian directory
            try:
                p.relative_to(self.config_dir)
                continue
            except ValueError:
                pass

            rel = p.relative_to(self.vault)
            notes.append({
                "path": str(rel),
                "size": p.stat().st_size,
            })

        return {"count": len(notes), "notes": notes}

    def search_notes(self, query: str, case_sensitive: bool = False) -> dict:
        """Search notes for text content.

        Example:
            v.search_notes("meeting agenda")
            => {"count": 2, "matches": [{"path": "Meetings/Monday.md", "snippets": ["...meeting agenda..."]}]}
        """
        err = self._validate_vault()
        if err:
            return err

        matches = []
        q = query if case_sensitive else query.lower()

        for p in sorted(self.vault.rglob("*.md")):
            try:
                p.relative_to(self.config_dir)
                continue
            except ValueError:
                pass

            try:
                content = p.read_text(encoding="utf-8")
            except OSError:
                continue

            search_content = content if case_sensitive else content.lower()
            if q in search_content:
                rel = str(p.relative_to(self.vault))
                # Extract snippets around matches
                snippets = []
                idx = 0
                while idx < len(search_content) and len(snippets) < 3:
                    pos = search_content.find(q, idx)
                    if pos == -1:
                        break
                    start = max(0, pos - 40)
                    end = min(len(content), pos + len(query) + 40)
                    snippets.append(content[start:end])
                    idx = pos + len(query)

                matches.append({"path": rel, "snippets": snippets})

        return {"count": len(matches), "matches": matches}

    def get_note_tags(self, note_name: str) -> dict:
        """Get all tags from a note (both inline #tags and frontmatter tags).

        Example:
            v.get_note_tags("My Note")
            => {"path": "My Note.md", "tags": ["project", "work"], "count": 2}
        """
        result = self.get_note(note_name)
        if "error" in result:
            return result

        content = result["content"]
        inline_tags = _extract_tags(content)
        fm = _parse_frontmatter(content)
        fm_tags = _extract_frontmatter_tags(fm)

        # Merge, dedup, preserve order
        all_tags = list(dict.fromkeys(fm_tags + inline_tags))

        return {
            "path": result["path"],
            "tags": all_tags,
            "count": len(all_tags),
            "inline_tags": inline_tags,
            "frontmatter_tags": fm_tags,
        }

    def get_note_links(self, note_name: str) -> dict:
        """Get all [[wikilinks]] from a note.

        Example:
            v.get_note_links("My Note")
            => {"path": "My Note.md", "links": [{"target": "Other Note", "alias": null}], "count": 1}
        """
        result = self.get_note(note_name)
        if "error" in result:
            return result

        links = _extract_wikilinks(result["content"])
        return {
            "path": result["path"],
            "links": links,
            "count": len(links),
        }

    def get_note_headings(self, note_name: str) -> dict:
        """Get all headings from a note.

        Example:
            v.get_note_headings("My Note")
            => {"path": "My Note.md", "headings": [{"level": 1, "text": "Title"}, ...]}
        """
        result = self.get_note(note_name)
        if "error" in result:
            return result

        headings = _extract_headings(result["content"])
        return {
            "path": result["path"],
            "headings": headings,
            "count": len(headings),
        }

    def get_backlinks(self, note_name: str) -> dict:
        """Find all notes that link to a given note.

        Example:
            v.get_backlinks("My Note")
            => {"target": "My Note", "backlinks": [{"path": "Other.md", "link_count": 2}], "count": 1}
        """
        err = self._validate_vault()
        if err:
            return err

        # Normalize target name (strip .md)
        target = note_name
        if target.endswith(".md"):
            target = target[:-3]
        target_basename = Path(target).name

        backlinks = []
        for p in sorted(self.vault.rglob("*.md")):
            try:
                p.relative_to(self.config_dir)
                continue
            except ValueError:
                pass

            try:
                content = p.read_text(encoding="utf-8")
            except OSError:
                continue

            links = _extract_wikilinks(content)
            matching = [l for l in links if l["target"] == target or l["target"] == target_basename]
            if matching:
                rel = str(p.relative_to(self.vault))
                backlinks.append({"path": rel, "link_count": len(matching)})

        return {
            "target": note_name,
            "backlinks": backlinks,
            "count": len(backlinks),
        }

    def get_vault_tags(self) -> dict:
        """Get all unique tags across the entire vault.

        Example:
            v.get_vault_tags()
            => {"tags": {"project": 3, "work": 5, "personal": 1}, "count": 3}
        """
        err = self._validate_vault()
        if err:
            return err

        tag_counts: dict[str, int] = {}
        for p in sorted(self.vault.rglob("*.md")):
            try:
                p.relative_to(self.config_dir)
                continue
            except ValueError:
                pass

            try:
                content = p.read_text(encoding="utf-8")
            except OSError:
                continue

            fm = _parse_frontmatter(content)
            all_tags = _extract_frontmatter_tags(fm) + _extract_tags(content)
            for tag in set(all_tags):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        return {"tags": tag_counts, "count": len(tag_counts)}

    # === Settings and configuration ===

    def get_app_settings(self, key: str | None = None) -> Any:
        """Read .obsidian/app.json settings.

        Example:
            v.get_app_settings()
            => {"spellcheck": true, "readableLineLength": true, ...}

            v.get_app_settings("spellcheck")
            => {"key": "spellcheck", "value": true}
        """
        err = self._validate_vault()
        if err:
            return err

        data = _read_json_file(self.config_dir / "app.json")
        if isinstance(data, dict) and "error" in data:
            return data

        if key is None:
            return data

        if key in data:
            return {"key": key, "value": data[key]}
        return {"error": f"Setting '{key}' not found"}

    def get_appearance(self, key: str | None = None) -> Any:
        """Read .obsidian/appearance.json.

        Example:
            v.get_appearance()
            => {"baseFontSize": 16, "theme": "obsidian", "cssTheme": "", ...}
        """
        err = self._validate_vault()
        if err:
            return err

        data = _read_json_file(self.config_dir / "appearance.json")
        if isinstance(data, dict) and "error" in data:
            return data

        if key is None:
            return data

        if key in data:
            return {"key": key, "value": data[key]}
        return {"error": f"Appearance key '{key}' not found"}

    def get_hotkeys(self) -> Any:
        """Read .obsidian/hotkeys.json — custom hotkey overrides.

        Example:
            v.get_hotkeys()
            => {"editor:toggle-bold": [{"modifiers": ["Mod"], "key": "B"}], ...}
        """
        err = self._validate_vault()
        if err:
            return err

        return _read_json_file(self.config_dir / "hotkeys.json")

    # === Plugins ===

    def get_community_plugins(self) -> dict:
        """List enabled community plugins.

        Example:
            v.get_community_plugins()
            => {"plugins": ["dataview", "templater-obsidian"], "count": 2}
        """
        err = self._validate_vault()
        if err:
            return err

        data = _read_json_file(self.config_dir / "community-plugins.json")
        if isinstance(data, dict) and "error" in data:
            return data
        if isinstance(data, list):
            return {"plugins": data, "count": len(data)}
        return {"plugins": [], "count": 0}

    def get_core_plugins(self) -> dict:
        """Get core plugin enable/disable state.

        Example:
            v.get_core_plugins()
            => {"plugins": {"file-explorer": true, "graph": true, ...}, "count": 15}
        """
        err = self._validate_vault()
        if err:
            return err

        data = _read_json_file(self.config_dir / "core-plugins.json")
        if isinstance(data, dict) and "error" in data:
            return data
        if isinstance(data, dict):
            return {"plugins": data, "count": len(data)}
        # core-plugins.json is sometimes a list of enabled plugin names
        if isinstance(data, list):
            return {"plugins": {name: True for name in data}, "count": len(data)}
        return {"plugins": {}, "count": 0}

    def get_plugin_settings(self, plugin_id: str) -> Any:
        """Read settings for a specific plugin from its data.json.

        Example:
            v.get_plugin_settings("dataview")
            => {"refreshInterval": 1000, ...}
        """
        err = self._validate_vault()
        if err:
            return err

        # Community plugins store settings in .obsidian/plugins/<id>/data.json
        plugin_data = self.config_dir / "plugins" / plugin_id / "data.json"
        return _read_json_file(plugin_data)

    # === Workspace / UI layout ===

    def get_workspace(self) -> Any:
        """Read .obsidian/workspace.json — open tabs, active file, sidebar state.

        Example:
            v.get_workspace()
            => {"main": {...}, "left": {...}, "right": {...}, "active": "..."}
        """
        err = self._validate_vault()
        if err:
            return err

        # Try workspace.json first, then workspace-v2.json (newer Obsidian versions)
        for fname in ("workspace.json", "workspace-v2.json"):
            data = _read_json_file(self.config_dir / fname)
            if isinstance(data, dict) and "error" not in data:
                return data

        return {"error": "workspace.json not found"}

    # === Bookmarks ===

    def get_bookmarks(self) -> Any:
        """Read .obsidian/bookmarks.json — starred/pinned items.

        Example:
            v.get_bookmarks()
            => {"items": [{"type": "file", "path": "Note.md"}, ...]}
        """
        err = self._validate_vault()
        if err:
            return err

        # Try bookmarks.json (modern) and starred.json (legacy)
        for fname in ("bookmarks.json", "starred.json"):
            data = _read_json_file(self.config_dir / fname)
            if isinstance(data, dict) and "error" not in data:
                return data
            if isinstance(data, list):
                return {"items": data, "count": len(data)}

        return {"items": [], "count": 0}

    # === Vault structure ===

    def list_folders(self) -> dict:
        """List all folders in the vault (excluding .obsidian).

        Example:
            v.list_folders()
            => {"count": 3, "folders": ["Daily Notes", "Projects", "Projects/Active"]}
        """
        err = self._validate_vault()
        if err:
            return err

        folders = []
        for p in sorted(self.vault.rglob("*")):
            if not p.is_dir():
                continue
            try:
                p.relative_to(self.config_dir)
                continue
            except ValueError:
                pass

            rel = str(p.relative_to(self.vault))
            folders.append(rel)

        return {"count": len(folders), "folders": folders}

    # === Global config ===

    def get_global_config(self) -> Any:
        """Read global Obsidian config (~/.config/obsidian/obsidian.json).

        Contains vault list and global preferences.
        """
        path = _find_global_config()
        if not path:
            return {"error": "Global obsidian.json not found"}
        return _read_json_file(path)

    # === File I/O ===

    def check_file_exists(self, path: str) -> dict:
        """Check if a file exists on disk.

        Example:
            v.check_file_exists("/home/user/vault/Note.md")
            => {"exists": true, "path": "...", "size": 234}
        """
        p = Path(path)
        exists = p.exists()
        result: dict[str, Any] = {"exists": exists, "path": str(p)}
        if exists:
            try:
                result["size"] = p.stat().st_size
                result["is_file"] = p.is_file()
                result["is_dir"] = p.is_dir()
            except OSError:
                pass
        return result

    # === Composite checks ===

    def check_note_exists(self, note_name: str) -> dict:
        """Check if a note exists in the vault.

        Example:
            v.check_note_exists("My Note")
            => {"exists": true, "path": "My Note.md"}
        """
        err = self._validate_vault()
        if err:
            return {**err, "exists": False}

        path = self._resolve_note_path(note_name)
        if path:
            return {"exists": True, "path": str(path.relative_to(self.vault))}
        return {"exists": False, "note_name": note_name}

    def check_note_contains(self, note_name: str, text: str) -> dict:
        """Check if a note contains specific text.

        Example:
            v.check_note_contains("My Note", "meeting agenda")
            => {"contains": true, "snippet": "...meeting agenda for Monday..."}
        """
        result = self.get_note(note_name)
        if "error" in result:
            return {**result, "contains": False}

        content = result["content"]
        found = text.lower() in content.lower()
        snippet = None
        if found:
            idx = content.lower().index(text.lower())
            start = max(0, idx - 50)
            end = min(len(content), idx + len(text) + 50)
            snippet = content[start:end]

        return {
            "contains": found,
            "path": result["path"],
            "snippet": snippet,
        }

    def check_note_has_tag(self, note_name: str, tag: str) -> dict:
        """Check if a note has a specific tag.

        Example:
            v.check_note_has_tag("My Note", "project")
            => {"has_tag": true, "tag": "project", "all_tags": ["project", "work"]}
        """
        tags_result = self.get_note_tags(note_name)
        if "error" in tags_result:
            return {**tags_result, "has_tag": False}

        # Strip leading # if present
        tag_clean = tag.lstrip("#")
        all_tags = tags_result["tags"]
        found = tag_clean in all_tags

        return {
            "has_tag": found,
            "tag": tag_clean,
            "path": tags_result["path"],
            "all_tags": all_tags,
        }

    def check_note_has_frontmatter_key(self, note_name: str, key: str, expected_value: str | None = None) -> dict:
        """Check if a note has a frontmatter key (and optionally a specific value).

        Example:
            v.check_note_has_frontmatter_key("My Note", "status", "done")
            => {"has_key": true, "match": true, "key": "status", "actual": "done"}
        """
        fm_result = self.get_note_frontmatter(note_name)
        if "error" in fm_result:
            return {**fm_result, "has_key": False, "match": False}

        fm = fm_result["frontmatter"]
        has_key = key in fm

        if not has_key:
            return {
                "has_key": False,
                "match": False,
                "key": key,
                "path": fm_result["path"],
            }

        actual = fm[key]
        if expected_value is None:
            return {
                "has_key": True,
                "match": True,
                "key": key,
                "actual": actual,
                "path": fm_result["path"],
            }

        # Parse expected value for comparison
        try:
            expected_parsed = json.loads(expected_value)
        except (json.JSONDecodeError, TypeError):
            expected_parsed = expected_value

        match = actual == expected_parsed
        return {
            "has_key": True,
            "match": match,
            "key": key,
            "expected": expected_parsed,
            "actual": actual,
            "path": fm_result["path"],
        }

    def check_note_links_to(self, note_name: str, target: str) -> dict:
        """Check if a note contains a wikilink to a target note.

        Example:
            v.check_note_links_to("My Note", "Other Note")
            => {"links_to": true, "target": "Other Note", "link_count": 1}
        """
        links_result = self.get_note_links(note_name)
        if "error" in links_result:
            return {**links_result, "links_to": False}

        target_clean = target
        if target_clean.endswith(".md"):
            target_clean = target_clean[:-3]

        matching = [l for l in links_result["links"]
                    if l["target"] == target_clean or l["target"] == Path(target_clean).name]

        return {
            "links_to": len(matching) > 0,
            "target": target,
            "path": links_result["path"],
            "link_count": len(matching),
        }

    def check_note_has_heading(self, note_name: str, heading_text: str, level: int | None = None) -> dict:
        """Check if a note has a heading with specific text (and optional level).

        Example:
            v.check_note_has_heading("My Note", "Introduction")
            => {"has_heading": true, "heading": {"level": 2, "text": "Introduction"}}
        """
        headings_result = self.get_note_headings(note_name)
        if "error" in headings_result:
            return {**headings_result, "has_heading": False}

        for h in headings_result["headings"]:
            if h["text"].lower() == heading_text.lower():
                if level is None or h["level"] == level:
                    return {
                        "has_heading": True,
                        "heading": h,
                        "path": headings_result["path"],
                    }

        return {
            "has_heading": False,
            "heading_text": heading_text,
            "path": headings_result["path"],
            "all_headings": headings_result["headings"],
        }

    def check_folder_exists(self, folder_name: str) -> dict:
        """Check if a folder exists in the vault.

        Example:
            v.check_folder_exists("Daily Notes")
            => {"exists": true, "path": "Daily Notes"}
        """
        err = self._validate_vault()
        if err:
            return {**err, "exists": False}

        p = self.vault / folder_name
        exists = p.exists() and p.is_dir()
        return {"exists": exists, "path": folder_name}

    def check_plugin_enabled(self, plugin_id: str, plugin_type: str = "community") -> dict:
        """Check if a plugin is enabled.

        Example:
            v.check_plugin_enabled("dataview", "community")
            => {"enabled": true, "plugin_id": "dataview", "type": "community"}
        """
        if plugin_type == "community":
            result = self.get_community_plugins()
            if "error" in result:
                return {**result, "enabled": False}
            enabled = plugin_id in result.get("plugins", [])
        else:
            result = self.get_core_plugins()
            if "error" in result:
                return {**result, "enabled": False}
            plugins = result.get("plugins", {})
            if isinstance(plugins, dict):
                enabled = plugins.get(plugin_id, False)
            else:
                enabled = plugin_id in plugins
        return {"enabled": enabled, "plugin_id": plugin_id, "type": plugin_type}

    def check_setting(self, key: str, expected: str) -> dict:
        """Check if an app setting matches an expected value.

        Example:
            v.check_setting("spellcheck", "true")
            => {"match": true, "key": "spellcheck", "expected": true, "actual": true}
        """
        try:
            expected_val = json.loads(expected)
        except (json.JSONDecodeError, TypeError):
            expected_val = expected

        result = self.get_app_settings(key)
        if isinstance(result, dict) and "error" in result:
            return {**result, "match": False, "key": key, "expected": expected_val}

        if isinstance(result, dict) and "value" in result:
            actual = result["value"]
        else:
            actual = result

        match = actual == expected_val
        return {"match": match, "key": key, "expected": expected_val, "actual": actual}

    def check_hotkey(self, command_id: str) -> dict:
        """Check if a hotkey is set for a command.

        Example:
            v.check_hotkey("editor:toggle-bold")
            => {"has_hotkey": true, "command": "editor:toggle-bold", "bindings": [...]}
        """
        hotkeys = self.get_hotkeys()
        if isinstance(hotkeys, dict) and "error" in hotkeys:
            return {**hotkeys, "has_hotkey": False}

        if not isinstance(hotkeys, dict):
            return {"has_hotkey": False, "error": "hotkeys.json is not a dict"}

        if command_id in hotkeys:
            return {
                "has_hotkey": True,
                "command": command_id,
                "bindings": hotkeys[command_id],
            }
        return {"has_hotkey": False, "command": command_id}

    def check_theme(self, expected_theme: str) -> dict:
        """Check if the active theme matches.

        Example:
            v.check_theme("obsidian")
            => {"match": true, "expected": "obsidian", "actual": "obsidian"}
        """
        result = self.get_appearance("cssTheme")
        if isinstance(result, dict) and "error" in result:
            # Try baseFontSize theme field
            result = self.get_appearance("theme")
            if isinstance(result, dict) and "error" in result:
                return {**result, "match": False}

        actual = result.get("value") if isinstance(result, dict) and "value" in result else result
        match = str(actual).lower() == expected_theme.lower()
        return {"match": match, "expected": expected_theme, "actual": actual}


# ---------------------------------------------------------------------------
# CLI interface — for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

# Note: vault_path is always the first CLI arg after the command.

COMMANDS = {
    # Core content
    "get-note": ("Read a note's content", 2,
                 lambda v, args: v.get_note(args[0])),
    "get-note-frontmatter": ("Parse note frontmatter", 2,
                             lambda v, args: v.get_note_frontmatter(args[0])),
    "list-notes": ("List all notes in vault", 1,
                   lambda v, args: v.list_notes(args[0] if args else None)),
    "search-notes": ("Search notes for text", 2,
                     lambda v, args: v.search_notes(args[0])),
    "get-note-tags": ("Get tags from a note", 2,
                      lambda v, args: v.get_note_tags(args[0])),
    "get-note-links": ("Get wikilinks from a note", 2,
                       lambda v, args: v.get_note_links(args[0])),
    "get-note-headings": ("Get headings from a note", 2,
                          lambda v, args: v.get_note_headings(args[0])),
    "get-backlinks": ("Find notes linking to a note", 2,
                      lambda v, args: v.get_backlinks(args[0])),
    "get-vault-tags": ("List all tags in vault", 1,
                       lambda v, args: v.get_vault_tags()),

    # Settings & config
    "app-settings": ("Read app.json (optional key)", 1,
                     lambda v, args: v.get_app_settings(args[0] if args else None)),
    "appearance": ("Read appearance.json (optional key)", 1,
                   lambda v, args: v.get_appearance(args[0] if args else None)),
    "hotkeys": ("Read hotkeys.json", 1,
                lambda v, args: v.get_hotkeys()),

    # Plugins
    "community-plugins": ("List community plugins", 1,
                          lambda v, args: v.get_community_plugins()),
    "core-plugins": ("List core plugins", 1,
                     lambda v, args: v.get_core_plugins()),
    "plugin-settings": ("Read plugin data.json", 2,
                        lambda v, args: v.get_plugin_settings(args[0])),

    # Workspace / UI
    "workspace": ("Read workspace.json", 1,
                  lambda v, args: v.get_workspace()),

    # Bookmarks
    "bookmarks": ("Read bookmarks.json", 1,
                  lambda v, args: v.get_bookmarks()),

    # Vault structure
    "list-folders": ("List folders in vault", 1,
                     lambda v, args: v.list_folders()),

    # Global config
    "global-config": ("Read global obsidian.json", 0,
                      lambda v, args: v.get_global_config()),

    # File checks
    "check-file-exists": ("Check if file exists", 1,
                          lambda v, args: v.check_file_exists(args[0])),

    # Composite checks
    "check-note-exists": ("Check if note exists", 2,
                          lambda v, args: v.check_note_exists(args[0])),
    "check-note-contains": ("Check if note has text", 3,
                            lambda v, args: v.check_note_contains(args[0], args[1])),
    "check-note-has-tag": ("Check note has tag", 3,
                           lambda v, args: v.check_note_has_tag(args[0], args[1])),
    "check-note-has-frontmatter": ("Check note frontmatter key", 3,
                                   lambda v, args: v.check_note_has_frontmatter_key(
                                       args[0], args[1], args[2] if len(args) > 2 else None)),
    "check-note-links-to": ("Check note links to target", 3,
                            lambda v, args: v.check_note_links_to(args[0], args[1])),
    "check-note-has-heading": ("Check note has heading", 3,
                               lambda v, args: v.check_note_has_heading(
                                   args[0], args[1], int(args[2]) if len(args) > 2 else None)),
    "check-folder-exists": ("Check folder exists in vault", 2,
                            lambda v, args: v.check_folder_exists(args[0])),
    "check-plugin-enabled": ("Check if plugin is enabled", 2,
                             lambda v, args: v.check_plugin_enabled(
                                 args[0], args[1] if len(args) > 1 else "community")),
    "check-setting": ("Check app setting value", 3,
                      lambda v, args: v.check_setting(args[0], args[1])),
    "check-hotkey": ("Check hotkey for command", 2,
                     lambda v, args: v.check_hotkey(args[0])),
    "check-theme": ("Check active theme", 2,
                    lambda v, args: v.check_theme(args[0])),
}


def _print_usage():
    print("Obsidian Verifier — query Obsidian vault state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> <vault_path> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name, _ in ((n, c) for n, c in COMMANDS.items()))
    for name, (desc, min_args, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print("\nAll output is JSON. <vault_path> is the root of the Obsidian vault.")
    print("Notes can be referenced by name (without .md), path relative to vault, or full path.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    desc, min_args_with_vault, handler = COMMANDS[cmd]

    # global-config doesn't need a vault path
    if cmd == "global-config":
        # No vault needed
        v = ObsidianVerifier("/tmp")
        remaining_args = sys.argv[2:]
    else:
        if len(sys.argv) < 3:
            print(json.dumps({"error": f"Missing vault_path argument for '{cmd}'"}))
            sys.exit(1)

        vault_path = sys.argv[2]
        v = ObsidianVerifier(vault_path)
        remaining_args = sys.argv[3:]

    try:
        result = handler(v, remaining_args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))
