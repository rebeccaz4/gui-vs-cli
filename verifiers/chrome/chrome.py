"""
Chrome Verifier — programmatic state inspection for Google Chrome in E2B sandbox.

Verification channels (in order of preference):
  1. CDP (Chrome DevTools Protocol) — real-time DOM, JS, network, cookies, tabs
  2. SQLite profile databases — persistent state: history, bookmarks, downloads, cookies
  3. File-based config — preferences, local storage, extensions

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/chrome.py tabs")
    sandbox.commands.run("python3 /home/user/verifiers/chrome.py history --query 'github'")
    sandbox.commands.run("python3 /home/user/verifiers/chrome.py eval 'document.title'")

Usage from Python (inside sandbox or via E2B):
    from verifiers.chrome import ChromeVerifier
    v = ChromeVerifier()
    tabs = v.get_tabs()
    title = v.eval_js("document.title", tab_index=0)

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - Chrome launched with: google-chrome --remote-debugging-port=9222
  - sqlite3 (standard library)
  - urllib (standard library)
"""

import json
import sqlite3
import os
import shutil
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
CDP_BASE = f"http://{CDP_HOST}:{CDP_PORT}"

# Chrome profile paths (in order of likelihood).
# Override with CHROME_PROFILE_DIR env var to point to a custom --user-data-dir.
CHROME_PROFILE_DIRS = [
    Path.home() / ".config" / "google-chrome" / "Default",
    Path.home() / ".config" / "google-chrome-stable" / "Default",
    Path.home() / ".config" / "chromium" / "Default",
]


def _find_profile_dir() -> Path | None:
    # Allow override via environment variable
    env_dir = os.environ.get("CHROME_PROFILE_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.exists():
            return p
        # Try appending /Default if user pointed to the --user-data-dir root
        default = p / "Default"
        if default.exists():
            return default
    for d in CHROME_PROFILE_DIRS:
        if d.exists():
            return d
    # Also search /tmp for Chrome profiles (common in sandboxes)
    for d in Path("/tmp").glob("chrome-*/Default"):
        if d.exists():
            return d
    return None


# ---------------------------------------------------------------------------
# CDP helpers
# ---------------------------------------------------------------------------

def _cdp_get(path: str, timeout: float = 5.0) -> Any:
    """GET a CDP HTTP endpoint, return parsed JSON."""
    url = f"{CDP_BASE}{path}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        return {"error": f"CDP connection failed: {e}. Is Chrome running with --remote-debugging-port={CDP_PORT}?"}


def _cdp_send(ws_url: str, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
    """Send a CDP command over WebSocket and return the result.

    Uses a minimal WebSocket implementation via the `websocket` module if
    available, otherwise falls back to a subprocess call to a helper.
    """
    try:
        import websocket
    except ImportError:
        # Fallback: use the CDP HTTP evaluate endpoint if available,
        # or report that websocket module is needed
        return {"error": "websocket-client not installed. Run: pip install websocket-client"}

    msg_id = 1
    payload = json.dumps({"id": msg_id, "method": method, "params": params or {}})

    ws = websocket.create_connection(ws_url, timeout=timeout)
    try:
        ws.send(payload)
        while True:
            raw = ws.recv()
            data = json.loads(raw)
            if data.get("id") == msg_id:
                return data.get("result", data)
    finally:
        ws.close()


# ---------------------------------------------------------------------------
# SQLite helpers (copy DB to avoid locking issues with running Chrome)
# ---------------------------------------------------------------------------

def _query_sqlite(db_name: str, query: str, params: tuple = ()) -> list[dict]:
    """Query a Chrome SQLite DB safely (copies it first to avoid WAL locks)."""
    profile = _find_profile_dir()
    if not profile:
        return [{"error": "Chrome profile directory not found"}]

    db_path = profile / db_name
    if not db_path.exists():
        return [{"error": f"{db_name} not found at {db_path}"}]

    # Copy to temp file to avoid locking the live DB
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        shutil.copy2(db_path, tmp.name)
        # Also copy WAL/SHM if they exist
        for ext in ("-wal", "-shm"):
            wal = Path(str(db_path) + ext)
            if wal.exists():
                shutil.copy2(wal, tmp.name + ext)

        conn = sqlite3.connect(tmp.name)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    finally:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)


# ---------------------------------------------------------------------------
# ChromeVerifier class
# ---------------------------------------------------------------------------

class ChromeVerifier:
    """Stateless verifier — each method call is independent."""

    # === CDP: Real-time state ===

    def get_tabs(self) -> list[dict]:
        """List all open tabs with their URL, title, and type.

        Example return:
        [
            {"id": "ABC123", "url": "https://github.com", "title": "GitHub", "type": "page"},
            {"id": "DEF456", "url": "chrome://newtab/", "title": "New Tab", "type": "page"}
        ]
        """
        result = _cdp_get("/json")
        if isinstance(result, dict) and "error" in result:
            return [result]
        return [
            {
                "id": tab.get("id"),
                "url": tab.get("url"),
                "title": tab.get("title"),
                "type": tab.get("type"),
            }
            for tab in result
        ]

    def get_tab_by_index(self, index: int = 0) -> dict:
        """Get a specific tab's CDP info by index (0 = most recent).

        Filters to only include 'page' type tabs (excludes background_page,
        service_worker, etc.) so that operations target real browser tabs.
        """
        tabs = _cdp_get("/json")
        if isinstance(tabs, dict) and "error" in tabs:
            return tabs
        # Filter to real page tabs only
        page_tabs = [t for t in tabs if t.get("type") == "page"]
        if not page_tabs:
            return {"error": f"No page tabs found (have {len(tabs)} total entries)"}
        if index >= len(page_tabs):
            return {"error": f"Tab index {index} out of range (have {len(page_tabs)} page tabs)"}
        return page_tabs[index]

    def eval_js(self, expression: str, tab_index: int = 0) -> dict:
        """Evaluate JavaScript in a tab and return the result.

        Example:
            v.eval_js("document.title")
            => {"type": "string", "value": "GitHub"}

            v.eval_js("document.querySelectorAll('a').length")
            => {"type": "number", "value": 42}
        """
        tab = self.get_tab_by_index(tab_index)
        if "error" in tab:
            return tab
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            return {"error": "No WebSocket URL for this tab"}

        result = _cdp_send(ws_url, "Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
        })
        if "error" in result:
            return result

        remote_obj = result.get("result", {})
        return {
            "type": remote_obj.get("type"),
            "value": remote_obj.get("value"),
            "description": remote_obj.get("description"),
        }

    def get_page_url(self, tab_index: int = 0) -> dict:
        """Get the current URL of a tab."""
        return self.eval_js("window.location.href", tab_index)

    def get_page_title(self, tab_index: int = 0) -> dict:
        """Get the document title of a tab."""
        return self.eval_js("document.title", tab_index)

    def get_page_text(self, tab_index: int = 0) -> dict:
        """Get the visible text content of the page body."""
        return self.eval_js("document.body?.innerText?.substring(0, 5000) || ''", tab_index)

    def get_page_html(self, tab_index: int = 0) -> dict:
        """Get the outerHTML of the page (truncated to 10KB)."""
        return self.eval_js("document.documentElement.outerHTML.substring(0, 10000)", tab_index)

    def query_selector(self, selector: str, tab_index: int = 0) -> dict:
        """Check if a CSS selector matches any elements, return count and first match text.

        Example:
            v.query_selector("h1.title")
            => {"count": 1, "first_text": "Welcome", "first_tag": "H1"}
        """
        js = f"""
        (() => {{
            const els = document.querySelectorAll({json.dumps(selector)});
            const first = els[0];
            return {{
                count: els.length,
                first_text: first?.innerText?.substring(0, 500) || null,
                first_tag: first?.tagName || null,
                first_id: first?.id || null,
                first_class: first?.className || null,
            }};
        }})()
        """
        return self.eval_js(js, tab_index)

    def get_input_value(self, selector: str, tab_index: int = 0) -> dict:
        """Get the value of an input/textarea/select element.

        Example:
            v.get_input_value("input[name='q']")
            => {"type": "string", "value": "E2B sandbox"}
        """
        js = f"document.querySelector({json.dumps(selector)})?.value || null"
        return self.eval_js(js, tab_index)

    def get_cookies(self, tab_index: int = 0) -> dict:
        """Get all cookies for the current page via CDP."""
        tab = self.get_tab_by_index(tab_index)
        if "error" in tab:
            return tab
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            return {"error": "No WebSocket URL"}

        result = _cdp_send(ws_url, "Network.getCookies")
        if "error" in result:
            return result
        return {"cookies": result.get("cookies", [])}

    def take_screenshot(self, tab_index: int = 0, format: str = "png") -> dict:
        """Capture a screenshot of the tab via CDP. Returns base64-encoded image.

        Useful for visual comparison reward signals.
        """
        tab = self.get_tab_by_index(tab_index)
        if "error" in tab:
            return tab
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            return {"error": "No WebSocket URL"}

        result = _cdp_send(ws_url, "Page.captureScreenshot", {"format": format})
        if "error" in result:
            return result
        return {"format": format, "data_base64": result.get("data", "")[:100] + "...(truncated)"}

    def navigate(self, url: str, tab_index: int = 0, wait: float = 2.0) -> dict:
        """Navigate a tab to a URL and wait for it to load."""
        tab = self.get_tab_by_index(tab_index)
        if "error" in tab:
            return tab
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            return {"error": "No WebSocket URL"}

        result = _cdp_send(ws_url, "Page.navigate", {"url": url})
        if wait > 0:
            time.sleep(wait)
        return result

    # === SQLite: Persistent state ===

    def get_history(self, query: str | None = None, limit: int = 20) -> list[dict]:
        """Search browsing history. Returns URLs, titles, visit counts, and timestamps.

        Example:
            v.get_history(query="github", limit=5)
            => [{"url": "https://github.com", "title": "GitHub", "visit_count": 3, ...}]
        """
        if query:
            sql = """
                SELECT u.url, u.title, u.visit_count,
                       datetime(u.last_visit_time/1000000-11644473600, 'unixepoch') as last_visit
                FROM urls u
                WHERE u.url LIKE ? OR u.title LIKE ?
                ORDER BY u.last_visit_time DESC
                LIMIT ?
            """
            pattern = f"%{query}%"
            return _query_sqlite("History", sql, (pattern, pattern, limit))
        else:
            sql = """
                SELECT u.url, u.title, u.visit_count,
                       datetime(u.last_visit_time/1000000-11644473600, 'unixepoch') as last_visit
                FROM urls u
                ORDER BY u.last_visit_time DESC
                LIMIT ?
            """
            return _query_sqlite("History", sql, (limit,))

    def get_downloads(self, limit: int = 20) -> list[dict]:
        """List recent downloads with path, URL, and state.

        State values: 0=in_progress, 1=complete, 2=cancelled, 3=interrupted
        """
        sql = """
            SELECT target_path, tab_url, total_bytes, received_bytes, state,
                   mime_type,
                   datetime(start_time/1000000-11644473600, 'unixepoch') as start_time
            FROM downloads
            ORDER BY start_time DESC
            LIMIT ?
        """
        return _query_sqlite("History", sql, (limit,))

    def get_bookmarks(self, query: str | None = None) -> dict:
        """Read Chrome bookmarks from the Bookmarks JSON file.

        Example:
            v.get_bookmarks(query="github")
            => {"matches": [{"name": "GitHub", "url": "https://github.com", "folder": "bookmark_bar"}]}
        """
        profile = _find_profile_dir()
        if not profile:
            return {"error": "Profile not found"}

        bm_path = profile / "Bookmarks"
        if not bm_path.exists():
            return {"error": "Bookmarks file not found"}

        with open(bm_path) as f:
            data = json.load(f)

        results = []

        def _walk(node, folder=""):
            if node.get("type") == "url":
                entry = {"name": node.get("name", ""), "url": node.get("url", ""), "folder": folder}
                if query is None or query.lower() in entry["name"].lower() or query.lower() in entry["url"].lower():
                    results.append(entry)
            for child in node.get("children", []):
                _walk(child, folder=node.get("name", folder))

        for root_key in ("bookmark_bar", "other", "synced"):
            root = data.get("roots", {}).get(root_key)
            if root:
                _walk(root, folder=root_key)

        return {"count": len(results), "matches": results}

    def get_extensions(self) -> list[dict]:
        """List installed Chrome extensions."""
        profile = _find_profile_dir()
        if not profile:
            return [{"error": "Profile not found"}]

        ext_dir = profile.parent / "Extensions"  # Extensions is sibling to Default
        if not ext_dir.exists():
            # Try inside profile
            ext_dir = profile / "Extensions"
        if not ext_dir.exists():
            return []

        extensions = []
        for ext_id in ext_dir.iterdir():
            if not ext_id.is_dir():
                continue
            # Find the latest version folder
            versions = sorted(ext_id.iterdir(), reverse=True)
            if not versions:
                continue
            manifest_path = versions[0] / "manifest.json"
            if manifest_path.exists():
                with open(manifest_path) as f:
                    manifest = json.load(f)
                extensions.append({
                    "id": ext_id.name,
                    "name": manifest.get("name", ""),
                    "version": manifest.get("version", ""),
                    "description": manifest.get("description", "")[:200],
                })
        return extensions

    def get_preferences(self, key_path: str | None = None) -> Any:
        """Read Chrome Preferences JSON. Optionally extract a nested key.

        Example:
            v.get_preferences("download.default_directory")
            => "/home/user/Downloads"

            v.get_preferences("profile.name")
            => "Default"
        """
        profile = _find_profile_dir()
        if not profile:
            return {"error": "Profile not found"}

        prefs_path = profile / "Preferences"
        if not prefs_path.exists():
            return {"error": "Preferences file not found"}

        with open(prefs_path) as f:
            prefs = json.load(f)

        if key_path is None:
            # Return top-level keys only (full prefs is huge)
            return {"keys": list(prefs.keys())}

        # Navigate nested path like "download.default_directory"
        obj = prefs
        for key in key_path.split("."):
            if isinstance(obj, dict):
                obj = obj.get(key)
            else:
                return {"error": f"Key '{key_path}' not found (stopped at '{key}')"}
        return obj

    def get_local_storage(self, origin: str | None = None) -> dict:
        """Query Local Storage LevelDB entries.

        Note: LevelDB is not trivially queryable from Python without extra deps.
        This returns the storage directory info and suggests alternatives.
        """
        profile = _find_profile_dir()
        if not profile:
            return {"error": "Profile not found"}

        ls_dir = profile / "Local Storage" / "leveldb"
        if not ls_dir.exists():
            return {"error": "Local Storage directory not found"}

        # List .log and .ldb files
        files = list(ls_dir.glob("*"))
        return {
            "path": str(ls_dir),
            "file_count": len(files),
            "note": "Use CDP Runtime.evaluate with localStorage API for reliable access",
            "cdp_example": 'eval_js("JSON.stringify(localStorage)")',
        }

    # === Composite checks (common RL verification patterns) ===

    def check_url_visited(self, url_substring: str) -> dict:
        """Check if a URL matching the substring was visited.

        Example:
            v.check_url_visited("github.com")
            => {"visited": true, "match_count": 3, "latest": {"url": "...", "title": "..."}}
        """
        results = self.get_history(query=url_substring, limit=5)
        if results and "error" in results[0]:
            return results[0]
        return {
            "visited": len(results) > 0,
            "match_count": len(results),
            "latest": results[0] if results else None,
        }

    def check_tab_open(self, url_substring: str | None = None, title_substring: str | None = None) -> dict:
        """Check if a tab matching URL or title is currently open.

        Example:
            v.check_tab_open(url_substring="google.com")
            => {"found": true, "tab": {"url": "https://google.com", "title": "Google"}}
        """
        tabs = self.get_tabs()
        if tabs and "error" in tabs[0]:
            return tabs[0]

        for tab in tabs:
            if url_substring and url_substring.lower() in (tab.get("url") or "").lower():
                return {"found": True, "tab": tab}
            if title_substring and title_substring.lower() in (tab.get("title") or "").lower():
                return {"found": True, "tab": tab}
        return {"found": False, "tabs_checked": len(tabs)}

    def check_page_contains(self, text: str, tab_index: int = 0) -> dict:
        """Check if the current page contains specific text.

        Example:
            v.check_page_contains("Sign in")
            => {"contains": true, "snippet": "...Sign in to your account..."}
        """
        result = self.get_page_text(tab_index)
        if "error" in result:
            return result
        page_text = result.get("value", "")
        found = text.lower() in page_text.lower()
        # Extract a snippet around the match
        snippet = None
        if found:
            idx = page_text.lower().index(text.lower())
            start = max(0, idx - 50)
            end = min(len(page_text), idx + len(text) + 50)
            snippet = page_text[start:end]
        return {"contains": found, "snippet": snippet}

    def check_element_exists(self, selector: str, tab_index: int = 0) -> dict:
        """Check if a CSS selector matches any element on the page.

        Example:
            v.check_element_exists("button.submit")
            => {"exists": true, "count": 1, "first_text": "Submit"}
        """
        result = self.query_selector(selector, tab_index)
        if "error" in result:
            return result
        val = result.get("value", {})
        if isinstance(val, dict):
            return {"exists": val.get("count", 0) > 0, **val}
        return result

    def check_download_complete(self, filename_substring: str) -> dict:
        """Check if a file matching the name was downloaded successfully.

        Example:
            v.check_download_complete("report.pdf")
            => {"downloaded": true, "path": "/home/user/Downloads/report.pdf", "size": 12345}
        """
        downloads = self.get_downloads(limit=50)
        if downloads and "error" in downloads[0]:
            return downloads[0]

        for dl in downloads:
            path = dl.get("target_path", "")
            if filename_substring.lower() in path.lower():
                file_exists = os.path.exists(path)
                return {
                    "downloaded": dl.get("state") == 1,
                    "file_exists": file_exists,
                    "path": path,
                    "size": dl.get("total_bytes"),
                    "mime_type": dl.get("mime_type"),
                }
        return {"downloaded": False, "match": None}

    def check_bookmark_exists(self, url_or_name: str) -> dict:
        """Check if a bookmark matching URL or name exists.

        Example:
            v.check_bookmark_exists("GitHub")
            => {"exists": true, "count": 1, "matches": [...]}
        """
        result = self.get_bookmarks(query=url_or_name)
        if "error" in result:
            return result
        return {
            "exists": result["count"] > 0,
            "count": result["count"],
            "matches": result["matches"][:5],
        }

    def check_cookie_set(self, name: str, domain: str | None = None, tab_index: int = 0) -> dict:
        """Check if a cookie with the given name exists.

        Example:
            v.check_cookie_set("session_id", domain="github.com")
            => {"exists": true, "cookie": {"name": "session_id", "value": "abc...", "domain": ".github.com"}}
        """
        result = self.get_cookies(tab_index)
        if "error" in result:
            return result

        for cookie in result.get("cookies", []):
            if cookie.get("name") == name:
                if domain is None or domain in cookie.get("domain", ""):
                    return {"exists": True, "cookie": cookie}
        return {"exists": False}

    def check_form_filled(self, fields: dict[str, str], tab_index: int = 0) -> dict:
        """Check if form fields have expected values.

        Example:
            v.check_form_filled({"input[name='email']": "user@test.com", "input[name='name']": "John"})
            => {"all_match": true, "results": {"input[name='email']": {"expected": "...", "actual": "...", "match": true}}}
        """
        results = {}
        all_match = True
        for selector, expected in fields.items():
            result = self.get_input_value(selector, tab_index)
            actual = result.get("value")
            match = actual == expected
            if not match:
                all_match = False
            results[selector] = {"expected": expected, "actual": actual, "match": match}
        return {"all_match": all_match, "results": results}

    def check_file_exists(self, path: str) -> dict:
        """Check if a file exists on the filesystem.

        This is a general-purpose file check that works regardless of how
        the file was created (Chrome download, curl, wget, or any other method).

        Example:
            v.check_file_exists("/home/user/Downloads/image.png")
            => {"exists": true, "path": "/home/user/Downloads/image.png", "is_file": true, "size": 12345}

            v.check_file_exists("/home/user/Downloads")
            => {"exists": true, "path": "/home/user/Downloads", "is_file": false, "is_dir": true}
        """
        p = Path(path)
        if not p.exists():
            return {"exists": False, "path": path}
        stat = p.stat()
        return {
            "exists": True,
            "path": str(p.absolute()),
            "is_file": p.is_file(),
            "is_dir": p.is_dir(),
            "size": stat.st_size if p.is_file() else None,
        }

    def check_file_contains(self, path: str, text: str) -> dict:
        """Check if a file contains specific text.

        This enables CLI agents to save responses (via curl, wget, etc.) and verify
        content without requiring a browser. Works for both GUI and CLI agents.

        Example:
            v.check_file_contains("/home/user/form_response.json", "Elena Rodriguez")
            => {"contains": true, "path": "/home/user/form_response.json", "search_text": "Elena Rodriguez"}

            v.check_file_contains("/home/user/data.txt", "123-4567")
            => {"contains": false, "path": "/home/user/data.txt", "search_text": "123-4567"}
        """
        p = Path(path)
        if not p.exists():
            return {"contains": False, "path": path, "search_text": text, "error": "File not found"}

        if not p.is_file():
            return {"contains": False, "path": path, "search_text": text, "error": "Path is not a file"}

        try:
            with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            found = text.lower() in content.lower()

            # Extract a snippet around the match if found
            snippet = None
            if found:
                idx = content.lower().index(text.lower())
                start = max(0, idx - 50)
                end = min(len(content), idx + len(text) + 50)
                snippet = content[start:end]

            return {
                "contains": found,
                "path": str(p.absolute()),
                "search_text": text,
                "snippet": snippet,
            }
        except Exception as e:
            return {"contains": False, "path": path, "search_text": text, "error": str(e)}


# ---------------------------------------------------------------------------
# CLI interface — for use via sandbox.commands.run()
# ---------------------------------------------------------------------------

COMMANDS = {
    # CDP real-time
    "tabs": ("List open tabs", lambda v, args: v.get_tabs()),
    "url": ("Get current tab URL", lambda v, args: v.get_page_url(int(args[0]) if args else 0)),
    "title": ("Get current tab title", lambda v, args: v.get_page_title(int(args[0]) if args else 0)),
    "text": ("Get page text content", lambda v, args: v.get_page_text(int(args[0]) if args else 0)),
    "html": ("Get page HTML (truncated)", lambda v, args: v.get_page_html(int(args[0]) if args else 0)),
    "eval": ("Evaluate JS expression", lambda v, args: v.eval_js(args[0], int(args[1]) if len(args) > 1 else 0)),
    "select": ("Query CSS selector", lambda v, args: v.query_selector(args[0], int(args[1]) if len(args) > 1 else 0)),
    "input": ("Get input field value", lambda v, args: v.get_input_value(args[0], int(args[1]) if len(args) > 1 else 0)),
    "cookies": ("Get page cookies", lambda v, args: v.get_cookies(int(args[0]) if args else 0)),
    "screenshot": ("Capture tab screenshot", lambda v, args: v.take_screenshot(int(args[0]) if args else 0)),
    "navigate": ("Navigate to URL", lambda v, args: v.navigate(args[0], int(args[1]) if len(args) > 1 else 0)),

    # SQLite persistent state
    "history": ("Search browsing history", lambda v, args: v.get_history(query=args[0] if args else None)),
    "downloads": ("List downloads", lambda v, args: v.get_downloads()),
    "bookmarks": ("Search bookmarks", lambda v, args: v.get_bookmarks(query=args[0] if args else None)),
    "extensions": ("List installed extensions", lambda v, args: v.get_extensions()),
    "prefs": ("Read preferences key", lambda v, args: v.get_preferences(args[0] if args else None)),

    # Composite checks (return {check_name: true/false, ...})
    "check-url-visited": ("Check if URL was visited", lambda v, args: v.check_url_visited(args[0])),
    "check-tab-open": ("Check if tab is open", lambda v, args: v.check_tab_open(url_substring=args[0])),
    "check-page-contains": ("Check if page has text", lambda v, args: v.check_page_contains(args[0], int(args[1]) if len(args) > 1 else 0)),
    "check-element-exists": ("Check CSS selector match", lambda v, args: v.check_element_exists(args[0], int(args[1]) if len(args) > 1 else 0)),
    "check-download": ("Check download completed", lambda v, args: v.check_download_complete(args[0])),
    "check-bookmark": ("Check bookmark exists", lambda v, args: v.check_bookmark_exists(args[0])),
    "check-cookie": ("Check cookie exists", lambda v, args: v.check_cookie_set(args[0], args[1] if len(args) > 1 else None)),
    "check-file-exists": ("Check if file exists on filesystem", lambda v, args: v.check_file_exists(args[0])),
    "check-file-contains": ("Check if file contains text", lambda v, args: v.check_file_contains(args[0], args[1])),
}


def _print_usage():
    print("Chrome Verifier — query Chrome state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nAll output is JSON. CDP requires Chrome running with --remote-debugging-port={CDP_PORT}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = ChromeVerifier()
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
