"""
Brave Browser Verifier — programmatic state inspection for Brave in E2B sandbox.

Verification channels (in order of preference):
  1. CDP (Chrome DevTools Protocol) — real-time DOM, JS, network, cookies, tabs
  2. SQLite profile databases — persistent state: history, bookmarks, downloads
  3. File-based config — preferences, local storage

Brave is Chromium-based and uses the same CDP and profile structure as Chrome,
with different profile directory paths.

Usage from outside the sandbox:
    sandbox.commands.run("python3 /home/user/verifiers/brave.py tabs")
    sandbox.commands.run("python3 /home/user/verifiers/brave.py check-tab-open github.com")

Requires:
  - Brave launched with: brave-browser --remote-debugging-port=9222
  - websocket-client (pip install websocket-client) for CDP WebSocket
"""

import json
import os
import shutil
import sqlite3
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

BRAVE_PROFILE_DIRS = [
    Path.home() / ".config" / "BraveSoftware" / "Brave-Browser" / "Default",
    Path.home() / ".config" / "BraveSoftware" / "Brave-Browser-Stable" / "Default",
]


def _find_profile_dir() -> Path | None:
    env_dir = os.environ.get("BRAVE_PROFILE_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.exists():
            return p
        default = p / "Default"
        if default.exists():
            return default
    for d in BRAVE_PROFILE_DIRS:
        if d.exists():
            return d
    # Also search /tmp for Brave profiles (common in sandboxes launched with
    # --user-data-dir=/tmp/brave-*)
    for d in Path("/tmp").glob("brave-*/Default"):
        if d.exists():
            return d
    return None


# ---------------------------------------------------------------------------
# CDP helpers
# ---------------------------------------------------------------------------

def _cdp_get(path: str, timeout: float = 5.0) -> Any:
    url = f"{CDP_BASE}{path}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        return {"error": f"CDP connection failed: {e}. Is Brave running with --remote-debugging-port={CDP_PORT}?"}


def _cdp_send(ws_url: str, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
    try:
        import websocket
    except ImportError:
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
# SQLite helpers
# ---------------------------------------------------------------------------

def _query_sqlite(db_name: str, query: str, params: tuple = ()) -> list[dict]:
    profile = _find_profile_dir()
    if not profile:
        return [{"error": "Brave profile directory not found"}]

    db_path = profile / db_name
    if not db_path.exists():
        return [{"error": f"{db_name} not found at {db_path}"}]

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        shutil.copy2(db_path, tmp.name)
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
# BraveVerifier class
# ---------------------------------------------------------------------------

class BraveVerifier:
    """Stateless verifier for Brave browser."""

    # === CDP: Real-time state ===

    def get_tabs(self) -> list[dict]:
        """List all open tabs."""
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
        """Get a specific tab by index (0 = most recent). Filters to page type."""
        tabs = _cdp_get("/json")
        if isinstance(tabs, dict) and "error" in tabs:
            return tabs
        page_tabs = [t for t in tabs if t.get("type") == "page"]
        if not page_tabs:
            return {"error": f"No page tabs found (have {len(tabs)} total entries)"}
        if index >= len(page_tabs):
            return {"error": f"Tab index {index} out of range (have {len(page_tabs)} page tabs)"}
        return page_tabs[index]

    def eval_js(self, expression: str, tab_index: int = 0) -> dict:
        """Evaluate JavaScript in a tab."""
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
        return self.eval_js("window.location.href", tab_index)

    def get_page_title(self, tab_index: int = 0) -> dict:
        return self.eval_js("document.title", tab_index)

    def get_page_text(self, tab_index: int = 0) -> dict:
        return self.eval_js("document.body?.innerText?.substring(0, 5000) || ''", tab_index)

    def get_page_html(self, tab_index: int = 0) -> dict:
        return self.eval_js("document.documentElement.outerHTML.substring(0, 10000)", tab_index)

    def query_selector(self, selector: str, tab_index: int = 0) -> dict:
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
        js = f"document.querySelector({json.dumps(selector)})?.value || null"
        return self.eval_js(js, tab_index)

    def get_cookies(self, tab_index: int = 0) -> dict:
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
        if query:
            sql = """
                SELECT u.url, u.title, u.visit_count,
                       datetime(u.last_visit_time/1000000-11644473600, 'unixepoch') as last_visit
                FROM urls u
                WHERE u.url LIKE ? OR u.title LIKE ?
                ORDER BY u.last_visit_time DESC LIMIT ?
            """
            pattern = f"%{query}%"
            return _query_sqlite("History", sql, (pattern, pattern, limit))
        else:
            sql = """
                SELECT u.url, u.title, u.visit_count,
                       datetime(u.last_visit_time/1000000-11644473600, 'unixepoch') as last_visit
                FROM urls u ORDER BY u.last_visit_time DESC LIMIT ?
            """
            return _query_sqlite("History", sql, (limit,))

    def get_downloads(self, limit: int = 20) -> list[dict]:
        sql = """
            SELECT target_path, tab_url, total_bytes, received_bytes, state, mime_type,
                   datetime(start_time/1000000-11644473600, 'unixepoch') as start_time
            FROM downloads ORDER BY start_time DESC LIMIT ?
        """
        return _query_sqlite("History", sql, (limit,))

    def get_bookmarks(self, query: str | None = None) -> dict:
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
        profile = _find_profile_dir()
        if not profile:
            return [{"error": "Profile not found"}]
        ext_dir = profile.parent / "Extensions"
        if not ext_dir.exists():
            ext_dir = profile / "Extensions"
        if not ext_dir.exists():
            return []

        extensions = []
        for ext_id in ext_dir.iterdir():
            if not ext_id.is_dir():
                continue
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
        profile = _find_profile_dir()
        if not profile:
            return {"error": "Profile not found"}
        prefs_path = profile / "Preferences"
        if not prefs_path.exists():
            return {"error": "Preferences file not found"}

        with open(prefs_path) as f:
            prefs = json.load(f)

        if key_path is None:
            return {"keys": list(prefs.keys())}

        obj = prefs
        for key in key_path.split("."):
            if isinstance(obj, dict):
                obj = obj.get(key)
            else:
                return {"error": f"Key '{key_path}' not found"}
        return obj

    # === Composite checks ===

    def check_url_visited(self, url_substring: str) -> dict:
        # Brave writes history asynchronously; retry to avoid false negatives
        # right after task completion.
        for attempt in range(4):
            results = self.get_history(query=url_substring, limit=5)
            if results and "error" in results[0]:
                return results[0]
            out = {
                "visited": len(results) > 0,
                "match_count": len(results),
                "latest": results[0] if results else None,
            }
            if out["visited"] or attempt == 3:
                return out
            time.sleep(1.5)
        return out

    def check_tab_open(self, url_substring: str | None = None, title_substring: str | None = None) -> dict:
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
        result = self.get_page_text(tab_index)
        if "error" in result:
            return result
        page_text = result.get("value", "")
        found = text.lower() in page_text.lower()
        snippet = None
        if found:
            idx = page_text.lower().index(text.lower())
            start = max(0, idx - 50)
            end = min(len(page_text), idx + len(text) + 50)
            snippet = page_text[start:end]
        return {"contains": found, "snippet": snippet}

    def check_element_exists(self, selector: str, tab_index: int = 0) -> dict:
        result = self.query_selector(selector, tab_index)
        if "error" in result:
            return result
        val = result.get("value", {})
        if isinstance(val, dict):
            return {"exists": val.get("count", 0) > 0, **val}
        return result

    def check_download_complete(self, filename_substring: str) -> dict:
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
                }
        return {"downloaded": False, "match": None}

    def check_bookmark_exists(self, url_or_name: str) -> dict:
        # Brave writes the Bookmarks JSON file asynchronously; retry to avoid
        # false negatives right after a bookmark is added.
        for attempt in range(4):
            result = self.get_bookmarks(query=url_or_name)
            if "error" in result:
                return result
            out = {
                "exists": result["count"] > 0,
                "count": result["count"],
                "matches": result["matches"][:5],
            }
            if out["exists"] or attempt == 3:
                return out
            time.sleep(1.5)
        return out

    def check_cookie_set(self, name: str, domain: str | None = None, tab_index: int = 0) -> dict:
        result = self.get_cookies(tab_index)
        if "error" in result:
            return result
        for cookie in result.get("cookies", []):
            if cookie.get("name") == name:
                if domain is None or domain in cookie.get("domain", ""):
                    return {"exists": True, "cookie": cookie}
        return {"exists": False}


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

COMMANDS = {
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
    "history": ("Search browsing history", lambda v, args: v.get_history(query=args[0] if args else None)),
    "downloads": ("List downloads", lambda v, args: v.get_downloads()),
    "bookmarks": ("Search bookmarks", lambda v, args: v.get_bookmarks(query=args[0] if args else None)),
    "extensions": ("List installed extensions", lambda v, args: v.get_extensions()),
    "prefs": ("Read preferences key", lambda v, args: v.get_preferences(args[0] if args else None)),
    "check-url-visited": ("Check if URL was visited", lambda v, args: v.check_url_visited(args[0])),
    "check-tab-open": ("Check if tab is open", lambda v, args: v.check_tab_open(url_substring=args[0])),
    "check-page-contains": ("Check if page has text", lambda v, args: v.check_page_contains(args[0], int(args[1]) if len(args) > 1 else 0)),
    "check-element-exists": ("Check CSS selector match", lambda v, args: v.check_element_exists(args[0], int(args[1]) if len(args) > 1 else 0)),
    "check-download": ("Check download completed", lambda v, args: v.check_download_complete(args[0])),
    "check-bookmark": ("Check bookmark exists", lambda v, args: v.check_bookmark_exists(args[0])),
    "check-cookie": ("Check cookie exists", lambda v, args: v.check_cookie_set(args[0], args[1] if len(args) > 1 else None)),
}


def _print_usage():
    print("Brave Browser Verifier — query Brave state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nCDP requires Brave running with --remote-debugging-port={CDP_PORT}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = BraveVerifier()
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
