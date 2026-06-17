"""
Test Obsidian verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (bad args, missing vault, missing notes)
  - Core content endpoints (get-note, list-notes, search-notes)
  - Frontmatter parsing
  - Tags (inline + frontmatter, code block exclusion)
  - Links and backlinks (wikilinks, aliases, code block exclusion)
  - Headings extraction
  - Settings and appearance
  - Hotkeys
  - Plugins (community, core, plugin settings)
  - Workspace
  - Bookmarks
  - Vault structure (folders)
  - Composite check-* endpoints (positive and negative cases)
  - JSON validity sweep for all commands

Setup:
  Creates a mock Obsidian vault with notes, folders, and .obsidian config
  files inside the sandbox.

Usage:
    python verifiers/obsidian/test_obsidian.py
"""

import json
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "obsidian.py"
VERIFIER_REMOTE = "/home/user/verifiers/obsidian.py"
V = f"python3 {VERIFIER_REMOTE}"
VAULT = "/home/user/test-vault"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

passed = 0
failed = 0
errors: list[str] = []


class CmdResult:
    """Minimal wrapper to normalize both success and CommandExitException results."""
    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def run(sandbox: Sandbox, cmd: str, timeout: int = 30) -> dict | list:
    """Run a verifier CLI command, parse JSON output."""
    r = run_raw(sandbox, cmd, timeout)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


def run_raw(sandbox: Sandbox, cmd: str, timeout: int = 30) -> CmdResult:
    """Run a command and return a CmdResult (never throws on non-zero exit)."""
    try:
        result = sandbox.commands.run(f"{V} {cmd}", timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def check(name: str, condition: bool, detail: str = ""):
    """Record a test result."""
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
# Sandbox setup: create mock vault
# ---------------------------------------------------------------------------

WELCOME_NOTE = """---
title: Welcome to My Vault
tags:
  - getting-started
  - documentation
date: 2024-01-15
author: Test User
---

# Welcome

This is the welcome note for the test vault.

## Getting Started

Check out [[Project Alpha]] for the main project.
Also see [[Daily/2024-01-15|today's daily note]].

Some inline tags: #welcome #vault-setup

## Resources

- [[Templates/Meeting]] template
- [[Project Beta#Overview]] for the beta project

This is a test note with enough content for searching.
"""

PROJECT_ALPHA_NOTE = """---
title: Project Alpha
status: active
priority: 1
tags:
  - project
  - alpha
---

# Project Alpha

## Overview

This is the main project for the team.

## Tasks

- [ ] Complete the design document
- [x] Set up the repository

## Team

See [[Welcome]] for getting started.
See [[Project Beta]] for related work.

#project #active-work
"""

PROJECT_BETA_NOTE = """# Project Beta

## Overview

A secondary project linked to [[Project Alpha]].

This project has no frontmatter.

#beta
"""

DAILY_NOTE = """---
date: 2024-01-15
tags: daily, journal
mood: productive
---

# Daily Note - January 15

## Morning

Worked on [[Project Alpha]] tasks.

## Afternoon

Reviewed [[Project Beta#Overview]].

#daily #work
"""

MEETING_TEMPLATE = """# {{title}}

## Date: {{date}}

## Attendees
-

## Agenda
1.

## Action Items
- [ ]

## Notes

"""

EMPTY_NOTE = ""

CODE_EXAMPLES_NOTE = """# Code Examples

This note has tags and links in code blocks that should be excluded.

Regular tag: #real-tag

```python
# This should NOT be extracted as a tag: #fake-tag
link = "[[Not A Real Link]]"
```

Another real link: [[Welcome]]

`#inline-code-tag` should also be excluded.

Real link after code: [[Project Alpha]]
"""


def setup_mock_vault(sandbox: Sandbox):
    """Create mock Obsidian vault with notes and config."""
    print("Setting up mock Obsidian vault...")

    obs = f"{VAULT}/.obsidian"

    # Create directories
    sandbox.commands.run(
        f"mkdir -p {VAULT}/Projects/Active && "
        f"mkdir -p {VAULT}/Daily && "
        f"mkdir -p {VAULT}/Templates && "
        f"mkdir -p {obs}/plugins/dataview"
    )

    # Write notes
    sandbox.files.write(f"{VAULT}/Welcome.md", WELCOME_NOTE)
    sandbox.files.write(f"{VAULT}/Projects/Project Alpha.md", PROJECT_ALPHA_NOTE)
    sandbox.files.write(f"{VAULT}/Projects/Project Beta.md", PROJECT_BETA_NOTE)
    sandbox.files.write(f"{VAULT}/Daily/2024-01-15.md", DAILY_NOTE)
    sandbox.files.write(f"{VAULT}/Templates/Meeting.md", MEETING_TEMPLATE)
    sandbox.files.write(f"{VAULT}/Empty Note.md", EMPTY_NOTE)
    sandbox.files.write(f"{VAULT}/Code Examples.md", CODE_EXAMPLES_NOTE)

    # Write .obsidian config files
    sandbox.files.write(f"{obs}/app.json", json.dumps({
        "spellcheck": True,
        "readableLineLength": True,
        "strictLineBreaks": False,
        "foldHeading": True,
        "showFrontmatter": True,
    }, indent=2))

    sandbox.files.write(f"{obs}/appearance.json", json.dumps({
        "baseFontSize": 16,
        "theme": "obsidian",
        "cssTheme": "Minimal",
        "accentColor": "#7C3AED",
        "translucency": False,
    }, indent=2))

    sandbox.files.write(f"{obs}/hotkeys.json", json.dumps({
        "editor:toggle-bold": [{"modifiers": ["Mod"], "key": "B"}],
        "app:go-back": [{"modifiers": ["Alt"], "key": "ArrowLeft"}],
        "editor:toggle-italic": [{"modifiers": ["Mod"], "key": "I"}],
    }, indent=2))

    sandbox.files.write(f"{obs}/community-plugins.json", json.dumps([
        "dataview", "templater-obsidian", "calendar"
    ]))

    sandbox.files.write(f"{obs}/core-plugins.json", json.dumps({
        "file-explorer": True,
        "graph": True,
        "search": True,
        "tag-pane": False,
        "daily-notes": True,
    }, indent=2))

    sandbox.files.write(f"{obs}/workspace.json", json.dumps({
        "main": {"type": "split", "children": [
            {"type": "leaf", "state": {"type": "markdown", "state": {"file": "Welcome.md"}}}
        ]},
        "left": {"collapsed": False, "type": "split"},
        "right": {"collapsed": True, "type": "split"},
        "active": "Welcome.md",
    }, indent=2))

    sandbox.files.write(f"{obs}/bookmarks.json", json.dumps({
        "items": [
            {"type": "file", "path": "Welcome.md"},
            {"type": "file", "path": "Projects/Project Alpha.md"},
        ]
    }, indent=2))

    sandbox.files.write(f"{obs}/plugins/dataview/data.json", json.dumps({
        "refreshInterval": 1000,
        "renderNullAs": "\\-",
        "enableDataviewJs": True,
    }, indent=2))

    print("  Mock vault created.")


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    """--help should print usage and exit 0."""
    print("\n=== Group 1: Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
    check("help mentions commands", "Commands:" in result.stdout, result.stdout[:100])
    check("help mentions Obsidian", "Obsidian" in result.stdout, result.stdout[:100])


def test_errors_bad_args(sandbox: Sandbox):
    """Missing/invalid arguments should return error JSON, not crash."""
    print("\n=== Group 2: Errors (bad args) ===")

    # Unknown command
    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Missing vault path
    result = run_raw(sandbox, "list-notes")
    check("missing vault exits 1", result.exit_code == 1)
    check("missing vault valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Missing note name for get-note
    result = run_raw(sandbox, f"get-note {VAULT}")
    check("missing note arg exits 1", result.exit_code == 1)
    check("missing note arg valid JSON", is_valid_json(result.stdout), result.stdout[:100])

    # Missing args for check commands
    result = run_raw(sandbox, f"check-note-contains {VAULT}")
    check("missing check args exits 1", result.exit_code == 1)
    check("missing check args valid JSON", is_valid_json(result.stdout), result.stdout[:100])


def test_errors_missing_vault(sandbox: Sandbox):
    """Operations on non-existent vault should return error JSON."""
    print("\n=== Group 3: Errors (missing vault) ===")

    fake = "/nonexistent/vault/12345"

    data = run(sandbox, f"list-notes {fake}")
    check("missing vault returns error", "error" in data, str(data)[:100])

    data = run(sandbox, f"get-note {fake} Welcome")
    check("missing vault get-note error", "error" in data, str(data)[:100])

    data = run(sandbox, f"check-note-exists {fake} Welcome")
    check("missing vault check returns exists=false",
          data.get("exists") is False, str(data)[:100])

    # Note not found in valid vault
    data = run(sandbox, f"get-note {VAULT} 'Nonexistent Note 12345'")
    check("missing note returns error", "error" in data, str(data)[:100])

    data = run(sandbox, f"app-settings {fake}")
    check("missing vault settings error", "error" in data, str(data)[:100])


def test_notes(sandbox: Sandbox):
    """Test core content endpoints: get-note, list-notes, search-notes."""
    print("\n=== Group 4: Core Content — Notes ===")

    # get-note by name (no extension)
    data = run(sandbox, f"get-note {VAULT} Welcome")
    check("get-note returns content", "content" in data, str(data.keys()))
    check("get-note has path", data.get("path") == "Welcome.md", str(data.get("path")))
    check("get-note content not empty", len(data.get("content", "")) > 0)
    check("get-note has welcome text", "welcome note" in data.get("content", "").lower())

    # get-note in subfolder
    data = run(sandbox, f"get-note {VAULT} 'Project Alpha'")
    check("get-note subfolder", "Projects/Project Alpha.md" in data.get("path", ""),
          str(data.get("path")))

    # get-note with .md extension
    data = run(sandbox, f"get-note {VAULT} Welcome.md")
    check("get-note with .md", "content" in data, str(data.keys()))

    # get-note empty note
    data = run(sandbox, f"get-note {VAULT} 'Empty Note'")
    check("get-note empty note", data.get("content") == "", str(data.get("content", "?")))

    # list-notes (all)
    data = run(sandbox, f"list-notes {VAULT}")
    check("list-notes returns count", "count" in data, str(data.keys()))
    check("list-notes has 7 notes", data.get("count") == 7,
          f"got {data.get('count')}")
    check("list-notes has notes list", isinstance(data.get("notes"), list))

    # list-notes (subfolder)
    data = run(sandbox, f"list-notes {VAULT} Projects")
    check("list-notes subfolder", data.get("count") == 2, f"got {data.get('count')}")

    # search-notes
    data = run(sandbox, f"search-notes {VAULT} 'welcome note'")
    check("search finds match", data.get("count", 0) > 0, str(data)[:100])
    check("search has snippets",
          len(data.get("matches", [{}])[0].get("snippets", [])) > 0 if data.get("matches") else False,
          str(data)[:100])

    # search-notes no match
    data = run(sandbox, f"search-notes {VAULT} 'xyzzy12345nonexistent'")
    check("search no match count=0", data.get("count") == 0, str(data)[:100])


def test_frontmatter(sandbox: Sandbox):
    """Test frontmatter parsing."""
    print("\n=== Group 5: Frontmatter ===")

    # Note with frontmatter
    data = run(sandbox, f"get-note-frontmatter {VAULT} Welcome")
    check("frontmatter has_frontmatter=true", data.get("has_frontmatter") is True)
    fm = data.get("frontmatter", {})
    check("frontmatter title", fm.get("title") == "Welcome to My Vault",
          str(fm.get("title")))
    check("frontmatter tags is list", isinstance(fm.get("tags"), list),
          str(type(fm.get("tags"))))
    check("frontmatter date", fm.get("date") == "2024-01-15",
          str(fm.get("date")))

    # Note without frontmatter
    data = run(sandbox, f"get-note-frontmatter {VAULT} 'Project Beta'")
    check("no frontmatter has_frontmatter=false", data.get("has_frontmatter") is False)

    # Note with numeric frontmatter value
    data = run(sandbox, f"get-note-frontmatter {VAULT} 'Project Alpha'")
    fm = data.get("frontmatter", {})
    check("frontmatter numeric priority=1", fm.get("priority") == 1,
          str(fm.get("priority")))


def test_tags(sandbox: Sandbox):
    """Test tag extraction."""
    print("\n=== Group 6: Tags ===")

    # Note with both inline and frontmatter tags
    data = run(sandbox, f"get-note-tags {VAULT} Welcome")
    check("tags count > 0", data.get("count", 0) > 0, str(data)[:100])
    all_tags = data.get("tags", [])
    check("has frontmatter tag 'getting-started'", "getting-started" in all_tags,
          str(all_tags))
    check("has inline tag 'welcome'", "welcome" in all_tags, str(all_tags))
    check("has inline tag 'vault-setup'", "vault-setup" in all_tags, str(all_tags))
    check("frontmatter_tags populated", len(data.get("frontmatter_tags", [])) > 0)

    # Vault-wide tags
    data = run(sandbox, f"get-vault-tags {VAULT}")
    check("vault tags count > 0", data.get("count", 0) > 0, str(data)[:100])
    tag_dict = data.get("tags", {})
    check("vault tags has 'project'", "project" in tag_dict, str(list(tag_dict.keys())[:10]))

    # Code block exclusion
    data = run(sandbox, f"get-note-tags {VAULT} 'Code Examples'")
    all_tags = data.get("tags", [])
    check("real-tag included", "real-tag" in all_tags, str(all_tags))
    check("fake-tag excluded from code block", "fake-tag" not in all_tags,
          str(all_tags))


def test_links(sandbox: Sandbox):
    """Test link and backlink extraction."""
    print("\n=== Group 7: Links and Backlinks ===")

    # Note with various link types
    data = run(sandbox, f"get-note-links {VAULT} Welcome")
    check("links count > 0", data.get("count", 0) > 0, str(data)[:100])
    links = data.get("links", [])
    targets = [l["target"] for l in links]
    check("links to Project Alpha", "Project Alpha" in targets, str(targets))

    # Check alias link
    alias_links = [l for l in links if l.get("alias")]
    check("has alias link", len(alias_links) > 0, str(links))
    if alias_links:
        check("alias link target", alias_links[0]["target"] == "Daily/2024-01-15",
              str(alias_links[0]))

    # Check heading link
    heading_links = [l for l in links if l.get("heading")]
    check("has heading link", len(heading_links) > 0, str(links))
    if heading_links:
        check("heading link has heading field", heading_links[0]["heading"] == "Overview",
              str(heading_links[0]))

    # Backlinks
    data = run(sandbox, f"get-backlinks {VAULT} 'Project Alpha'")
    check("backlinks count > 0", data.get("count", 0) > 0, str(data)[:100])
    backlink_paths = [b["path"] for b in data.get("backlinks", [])]
    check("Welcome links to Project Alpha", "Welcome.md" in backlink_paths,
          str(backlink_paths))

    # Code block link exclusion
    data = run(sandbox, f"get-note-links {VAULT} 'Code Examples'")
    links = data.get("links", [])
    targets = [l["target"] for l in links]
    check("real links included", "Welcome" in targets, str(targets))
    check("code block link excluded", "Not A Real Link" not in targets, str(targets))

    # Note with no links
    data = run(sandbox, f"get-note-links {VAULT} 'Empty Note'")
    check("empty note has 0 links", data.get("count") == 0, str(data)[:100])


def test_headings(sandbox: Sandbox):
    """Test heading extraction."""
    print("\n=== Group 8: Headings ===")

    data = run(sandbox, f"get-note-headings {VAULT} Welcome")
    check("headings count > 0", data.get("count", 0) > 0, str(data)[:100])
    headings = data.get("headings", [])
    h_texts = [h["text"] for h in headings]
    check("has H1 Welcome", "Welcome" in h_texts, str(h_texts))
    check("has H2 Getting Started", "Getting Started" in h_texts, str(h_texts))
    # Check levels
    h1s = [h for h in headings if h["level"] == 1]
    check("h1 count correct", len(h1s) >= 1, str(h1s))

    # Empty note has no headings
    data = run(sandbox, f"get-note-headings {VAULT} 'Empty Note'")
    check("empty note 0 headings", data.get("count") == 0, str(data)[:100])


def test_settings(sandbox: Sandbox):
    """Test app settings and appearance endpoints."""
    print("\n=== Group 9: Settings and Appearance ===")

    # Full settings
    data = run(sandbox, f"app-settings {VAULT}")
    check("app-settings returns dict", isinstance(data, dict))
    check("app-settings has spellcheck", "spellcheck" in data, str(data.keys()))
    check("spellcheck is true", data.get("spellcheck") is True)

    # Specific key
    data = run(sandbox, f"app-settings {VAULT} spellcheck")
    check("setting key value", data.get("value") is True, str(data)[:100])

    # Non-existent key
    data = run(sandbox, f"app-settings {VAULT} nonexistent_key_12345")
    check("missing setting returns error", "error" in data, str(data)[:100])

    # Appearance
    data = run(sandbox, f"appearance {VAULT}")
    check("appearance returns dict", isinstance(data, dict))
    check("appearance has baseFontSize", data.get("baseFontSize") == 16,
          str(data.get("baseFontSize")))

    # Appearance specific key
    data = run(sandbox, f"appearance {VAULT} cssTheme")
    check("appearance key value", data.get("value") == "Minimal",
          str(data)[:100])

    # Appearance non-existent key
    data = run(sandbox, f"appearance {VAULT} nonexistent_key_12345")
    check("missing appearance key error", "error" in data, str(data)[:100])

    # Appearance theme field
    data = run(sandbox, f"appearance {VAULT} theme")
    check("appearance theme value", data.get("value") == "obsidian",
          str(data)[:100])


def test_hotkeys(sandbox: Sandbox):
    """Test hotkeys endpoint."""
    print("\n=== Group 10: Hotkeys ===")

    data = run(sandbox, f"hotkeys {VAULT}")
    check("hotkeys returns dict", isinstance(data, dict))
    check("hotkeys has toggle-bold", "editor:toggle-bold" in data, str(data.keys()))
    bindings = data.get("editor:toggle-bold", [])
    check("toggle-bold has binding", len(bindings) > 0 and bindings[0].get("key") == "B",
          str(bindings))


def test_plugins(sandbox: Sandbox):
    """Test plugin endpoints."""
    print("\n=== Group 11: Plugins ===")

    # Community plugins
    data = run(sandbox, f"community-plugins {VAULT}")
    check("community plugins has list", isinstance(data.get("plugins"), list))
    check("community plugins count=3", data.get("count") == 3, str(data.get("count")))
    check("has dataview", "dataview" in data.get("plugins", []))

    # Core plugins
    data = run(sandbox, f"core-plugins {VAULT}")
    check("core plugins has dict", isinstance(data.get("plugins"), dict))
    plugins = data.get("plugins", {})
    check("core file-explorer enabled", plugins.get("file-explorer") is True)
    check("core tag-pane disabled", plugins.get("tag-pane") is False)

    # Plugin settings
    data = run(sandbox, f"plugin-settings {VAULT} dataview")
    check("plugin settings has refreshInterval",
          data.get("refreshInterval") == 1000, str(data)[:100])


def test_workspace(sandbox: Sandbox):
    """Test workspace endpoint."""
    print("\n=== Group 12: Workspace ===")

    data = run(sandbox, f"workspace {VAULT}")
    check("workspace returns dict", isinstance(data, dict))
    check("workspace has main", "main" in data, str(data.keys()))
    check("workspace has active", data.get("active") == "Welcome.md",
          str(data.get("active")))


def test_bookmarks(sandbox: Sandbox):
    """Test bookmarks endpoint."""
    print("\n=== Group 13: Bookmarks ===")

    data = run(sandbox, f"bookmarks {VAULT}")
    check("bookmarks returns dict", isinstance(data, dict))
    check("bookmarks has items", isinstance(data.get("items"), list))
    items = data.get("items", [])
    check("bookmarks has 2 items", len(items) == 2, str(len(items)))


def test_folders(sandbox: Sandbox):
    """Test vault structure endpoint."""
    print("\n=== Group 14: Vault Structure ===")

    data = run(sandbox, f"list-folders {VAULT}")
    check("folders returns count", "count" in data, str(data.keys()))
    folders = data.get("folders", [])
    check("has Projects folder", "Projects" in folders, str(folders))
    check("has Daily folder", "Daily" in folders, str(folders))
    check(".obsidian excluded", ".obsidian" not in folders and
          not any(".obsidian" in f for f in folders), str(folders))


def test_checks_positive(sandbox: Sandbox):
    """Composite check-* endpoints — positive cases."""
    print("\n=== Group 15: Checks (positive) ===")

    # check-note-exists
    data = run(sandbox, f"check-note-exists {VAULT} Welcome")
    check("check-note-exists exists=true", data.get("exists") is True, str(data)[:100])

    # check-note-contains
    data = run(sandbox, f"check-note-contains {VAULT} Welcome 'welcome note'")
    check("check-note-contains contains=true", data.get("contains") is True, str(data)[:100])
    check("check-note-contains has snippet", data.get("snippet") is not None)

    # check-note-has-tag
    data = run(sandbox, f"check-note-has-tag {VAULT} Welcome getting-started")
    check("check-note-has-tag has_tag=true", data.get("has_tag") is True, str(data)[:100])

    # check-note-has-frontmatter (key exists)
    data = run(sandbox, f"check-note-has-frontmatter {VAULT} Welcome title")
    check("check-fm has_key=true", data.get("has_key") is True, str(data)[:100])

    # check-note-has-frontmatter (key + value match)
    data = run(sandbox, f"check-note-has-frontmatter {VAULT} 'Project Alpha' status active")
    check("check-fm match=true", data.get("match") is True, str(data)[:100])

    # check-note-links-to
    data = run(sandbox, f"check-note-links-to {VAULT} Welcome 'Project Alpha'")
    check("check-links-to links_to=true", data.get("links_to") is True, str(data)[:100])

    # check-note-has-heading
    data = run(sandbox, f"check-note-has-heading {VAULT} Welcome 'Getting Started'")
    check("check-heading has_heading=true", data.get("has_heading") is True, str(data)[:100])

    # check-folder-exists
    data = run(sandbox, f"check-folder-exists {VAULT} Projects")
    check("check-folder exists=true", data.get("exists") is True, str(data)[:100])

    # check-plugin-enabled (community)
    data = run(sandbox, f"check-plugin-enabled {VAULT} dataview")
    check("check-plugin enabled=true", data.get("enabled") is True, str(data)[:100])

    # check-plugin-enabled (core)
    data = run(sandbox, f"check-plugin-enabled {VAULT} file-explorer core")
    check("check-core-plugin enabled=true", data.get("enabled") is True, str(data)[:100])

    # check-setting
    data = run(sandbox, f"check-setting {VAULT} spellcheck true")
    check("check-setting match=true", data.get("match") is True, str(data)[:100])

    # check-hotkey
    data = run(sandbox, f"check-hotkey {VAULT} editor:toggle-bold")
    check("check-hotkey has_hotkey=true", data.get("has_hotkey") is True, str(data)[:100])
    check("check-hotkey has bindings", len(data.get("bindings", [])) > 0)

    # check-theme
    data = run(sandbox, f"check-theme {VAULT} Minimal")
    check("check-theme match=true", data.get("match") is True, str(data)[:100])

    # check-file-exists
    data = run(sandbox, f"check-file-exists {VAULT} {VAULT}/Welcome.md")
    check("check-file-exists exists=true", data.get("exists") is True, str(data)[:100])


def test_checks_negative(sandbox: Sandbox):
    """Composite check-* endpoints — negative cases."""
    print("\n=== Group 16: Checks (negative) ===")

    # check-note-exists — non-existent note
    data = run(sandbox, f"check-note-exists {VAULT} 'Nonexistent Note 12345'")
    check("check-note-exists exists=false", data.get("exists") is False, str(data)[:100])

    # check-note-contains — text not in note
    data = run(sandbox, f"check-note-contains {VAULT} Welcome 'xyzzy12345nonexistent'")
    check("check-note-contains contains=false", data.get("contains") is False, str(data)[:100])
    check("check-note-contains snippet=None", data.get("snippet") is None)

    # check-note-has-tag — tag not present
    data = run(sandbox, f"check-note-has-tag {VAULT} Welcome nonexistent-tag-12345")
    check("check-note-has-tag has_tag=false", data.get("has_tag") is False, str(data)[:100])

    # check-note-has-frontmatter — missing key
    data = run(sandbox, f"check-note-has-frontmatter {VAULT} Welcome nonexistent_key")
    check("check-fm has_key=false", data.get("has_key") is False, str(data)[:100])

    # check-note-has-frontmatter — wrong value
    data = run(sandbox, f"check-note-has-frontmatter {VAULT} 'Project Alpha' status completed")
    check("check-fm match=false (wrong value)", data.get("match") is False, str(data)[:100])

    # check-note-links-to — not linked
    data = run(sandbox, f"check-note-links-to {VAULT} Welcome 'Nonexistent Target 12345'")
    check("check-links-to links_to=false", data.get("links_to") is False, str(data)[:100])

    # check-note-has-heading — heading not present
    data = run(sandbox, f"check-note-has-heading {VAULT} Welcome 'Nonexistent Heading 12345'")
    check("check-heading has_heading=false", data.get("has_heading") is False, str(data)[:100])
    check("check-heading shows all headings", "all_headings" in data, str(data.keys()))

    # check-folder-exists — non-existent folder
    data = run(sandbox, f"check-folder-exists {VAULT} 'Nonexistent Folder 12345'")
    check("check-folder exists=false", data.get("exists") is False, str(data)[:100])

    # check-plugin-enabled — not installed
    data = run(sandbox, f"check-plugin-enabled {VAULT} nonexistent-plugin-12345")
    check("check-plugin enabled=false", data.get("enabled") is False, str(data)[:100])

    # check-plugin-enabled (core disabled)
    data = run(sandbox, f"check-plugin-enabled {VAULT} tag-pane core")
    check("check-core-plugin disabled=false", data.get("enabled") is False, str(data)[:100])

    # check-setting — wrong value
    data = run(sandbox, f"check-setting {VAULT} spellcheck false")
    check("check-setting match=false", data.get("match") is False, str(data)[:100])
    check("check-setting shows actual", "actual" in data, str(data.keys()))

    # check-hotkey — no binding
    data = run(sandbox, f"check-hotkey {VAULT} nonexistent:command-12345")
    check("check-hotkey has_hotkey=false", data.get("has_hotkey") is False, str(data)[:100])

    # check-theme — wrong theme
    data = run(sandbox, f"check-theme {VAULT} 'Nonexistent Theme 12345'")
    check("check-theme match=false", data.get("match") is False, str(data)[:100])

    # check-file-exists — non-existent file
    data = run(sandbox, f"check-file-exists {VAULT} /nonexistent/file/12345.md")
    check("check-file-exists exists=false", data.get("exists") is False, str(data)[:100])

    # check-note-has-heading — right text, wrong level
    data = run(sandbox, f"check-note-has-heading {VAULT} Welcome Welcome 3")
    check("check-heading wrong level", data.get("has_heading") is False, str(data)[:100])


def test_all_commands_return_json(sandbox: Sandbox):
    """Every CLI command should output valid JSON."""
    print("\n=== Group 17: JSON Validity (all commands) ===")

    # No-arg commands (just vault path)
    no_arg_cmds = [
        "list-notes", "get-vault-tags", "app-settings", "appearance",
        "hotkeys", "community-plugins", "core-plugins", "workspace",
        "bookmarks", "list-folders",
    ]
    for cmd in no_arg_cmds:
        result = run_raw(sandbox, f"{cmd} {VAULT}")
        valid = is_valid_json(result.stdout)
        check(f"{cmd} valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # global-config (no vault needed)
    result = run_raw(sandbox, "global-config")
    valid = is_valid_json(result.stdout)
    check("global-config valid JSON", valid,
          f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # Commands with note arg
    note_cmds = [
        ("get-note", "Welcome"),
        ("get-note-frontmatter", "Welcome"),
        ("get-note-tags", "Welcome"),
        ("get-note-links", "Welcome"),
        ("get-note-headings", "Welcome"),
        ("get-backlinks", "Welcome"),
        ("search-notes", "meeting"),
    ]
    for cmd, arg in note_cmds:
        result = run_raw(sandbox, f"{cmd} {VAULT} {arg}")
        valid = is_valid_json(result.stdout)
        check(f"{cmd} {arg} valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # Commands with key arg
    key_cmds = [
        ("app-settings", "spellcheck"),
        ("appearance", "baseFontSize"),
        ("plugin-settings", "dataview"),
    ]
    for cmd, arg in key_cmds:
        result = run_raw(sandbox, f"{cmd} {VAULT} {arg}")
        valid = is_valid_json(result.stdout)
        check(f"{cmd} {arg} valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # Check commands
    check_cmds = [
        "check-note-exists Welcome",
        "check-note-contains Welcome hello",
        "check-note-has-tag Welcome getting-started",
        "check-note-has-frontmatter Welcome title",
        f"check-note-links-to Welcome 'Project Alpha'",
        "check-note-has-heading Welcome Welcome",
        "check-folder-exists Projects",
        "check-plugin-enabled dataview",
        "check-setting spellcheck true",
        "check-hotkey editor:toggle-bold",
        "check-theme Minimal",
        f"check-file-exists {VAULT}/Welcome.md",
    ]
    for cmd_args in check_cmds:
        result = run_raw(sandbox, f"{cmd_args.split()[0]} {VAULT} {' '.join(cmd_args.split()[1:])}")
        valid = is_valid_json(result.stdout)
        check(f"{cmd_args.split()[0]} valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed

    print("=" * 60)
    print("Obsidian Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # Set up mock vault
        setup_mock_vault(sandbox)

        # --- Run tests ---
        test_help(sandbox)
        test_errors_bad_args(sandbox)
        test_errors_missing_vault(sandbox)
        test_notes(sandbox)
        test_frontmatter(sandbox)
        test_tags(sandbox)
        test_links(sandbox)
        test_headings(sandbox)
        test_settings(sandbox)
        test_hotkeys(sandbox)
        test_plugins(sandbox)
        test_workspace(sandbox)
        test_bookmarks(sandbox)
        test_folders(sandbox)
        test_checks_positive(sandbox)
        test_checks_negative(sandbox)
        test_all_commands_return_json(sandbox)

    except Exception:
        traceback.print_exc()
        failed += 1
        errors.append(f"Unhandled exception: {traceback.format_exc()}")

    finally:
        sandbox.kill()
        print("\nSandbox killed.")

    # --- Summary ---
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
