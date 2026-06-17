"""
Firefox ESR Verifier — programmatic state inspection for Firefox in E2B sandbox.

Verification channels (in order of preference):
  1. Marionette protocol — real-time DOM, JS, tabs, navigation (port 2828)
  2. SQLite profile databases — persistent state: history, bookmarks, downloads
  3. File-based config — prefs.js, sessionstore

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/firefox.py tabs")
    sandbox.commands.run("python3 /home/user/verifiers/firefox.py history --query 'github'")
    sandbox.commands.run("python3 /home/user/verifiers/firefox.py eval 'document.title'")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - Firefox launched with: firefox-esr --marionette
  - sqlite3 (standard library)
  - marionette_driver (pip install marionette_driver) for live inspection
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MARIONETTE_HOST = "127.0.0.1"
MARIONETTE_PORT = 2828

# Firefox profile paths (in order of likelihood)
FIREFOX_PROFILE_DIRS = [
    Path.home() / ".mozilla" / "firefox-esr",
    Path.home() / ".mozilla" / "firefox",
]


def _find_profile_dir() -> Path | None:
    """Find the default Firefox profile directory."""
    env_dir = os.environ.get("FIREFOX_PROFILE_DIR")
    if env_dir:
        p = Path(env_dir)
        try:
            if p.exists():
                return p
        except OSError:
            pass

    # All candidate base directories to search
    all_bases = list(FIREFOX_PROFILE_DIRS) + [
        Path("/home/user/.mozilla/firefox-esr"),
        Path("/home/user/.mozilla/firefox"),
        Path("/root/.mozilla/firefox-esr"),
        Path("/root/.mozilla/firefox"),
    ]
    # De-duplicate while preserving order
    seen = set()
    unique_bases = []
    for b in all_bases:
        s = str(b)
        if s not in seen:
            seen.add(s)
            unique_bases.append(b)

    for base in unique_bases:
        try:
            if not base.exists():
                continue
            entries = list(base.iterdir())
        except OSError:
            continue
        # First priority: any directory with places.sqlite (most reliable)
        for d in sorted(entries, key=lambda x: x.name, reverse=True):
            try:
                if d.is_dir() and (d / "places.sqlite").exists():
                    return d
            except OSError:
                continue
        # Second: match by name suffix
        for suffix in (".default-esr", ".default-release", ".default"):
            for d in sorted(entries, key=lambda x: x.name, reverse=True):
                try:
                    if d.is_dir() and d.name.endswith(suffix):
                        return d
                except OSError:
                    continue

    return None


# ---------------------------------------------------------------------------
# Marionette helpers
# ---------------------------------------------------------------------------

def _get_marionette_client():
    """Create and connect a Marionette client."""
    try:
        from marionette_driver.marionette import Marionette
    except ImportError:
        return None, "marionette_driver not installed. Run: pip install marionette_driver"

    try:
        client = Marionette(host=MARIONETTE_HOST, port=MARIONETTE_PORT)
        client.start_session()
        return client, None
    except Exception as e:
        return None, f"Marionette connection failed: {e}. Is Firefox running with --marionette?"


def _with_marionette(func):
    """Execute a function with a Marionette client, handling connection lifecycle."""
    client, err = _get_marionette_client()
    if err:
        return {"error": err}
    try:
        return func(client)
    except Exception as e:
        return {"error": f"Marionette error: {e}"}
    finally:
        try:
            client.delete_session()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

def _query_sqlite(db_name: str, query: str, params: tuple = ()) -> list[dict]:
    """Query a Firefox SQLite DB safely (copies it first to avoid WAL locks)."""
    profile = _find_profile_dir()
    if not profile:
        return [{"error": "Firefox profile directory not found"}]

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
# FirefoxVerifier class
# ---------------------------------------------------------------------------

class FirefoxVerifier:
    """Stateless verifier — each method call is independent."""

    # === Marionette: Real-time state ===

    def get_tabs(self) -> list[dict]:
        """List all open tabs with URL and title.

        Example return:
        [
            {"index": 0, "url": "https://github.com", "title": "GitHub", "active": true},
            {"index": 1, "url": "about:newtab", "title": "New Tab", "active": false}
        ]
        """
        def _impl(client):
            tabs = []
            current_handle = client.current_window_handle
            handles = client.window_handles
            for i, handle in enumerate(handles):
                client.switch_to_window(handle)
                tabs.append({
                    "index": i,
                    "url": client.get_url(),
                    "title": client.title,
                    "active": handle == current_handle,
                    "handle": handle,
                })
            # Switch back to the originally active tab
            client.switch_to_window(current_handle)
            return tabs
        return _with_marionette(_impl)

    def get_tab_by_index(self, index: int = 0) -> dict:
        """Get a specific tab's info by index."""
        tabs = self.get_tabs()
        if isinstance(tabs, dict) and "error" in tabs:
            return tabs
        if isinstance(tabs, list) and tabs and "error" in tabs[0]:
            return tabs[0]
        if index >= len(tabs):
            return {"error": f"Tab index {index} out of range (have {len(tabs)} tabs)"}
        return tabs[index]

    def eval_js(self, expression: str, tab_index: int = 0, sandbox_name: str = "default") -> dict:
        """Evaluate JavaScript in a tab and return the result.

        Example:
            v.eval_js("document.title")
            => {"value": "GitHub", "type": "string"}
        """
        def _impl(client):
            handles = client.window_handles
            if tab_index >= len(handles):
                return {"error": f"Tab index {tab_index} out of range (have {len(handles)} tabs)"}
            client.switch_to_window(handles[tab_index])
            try:
                result = client.execute_script(f"return ({expression})", sandbox=sandbox_name)
                return {
                    "value": result,
                    "type": type(result).__name__ if result is not None else "null",
                }
            except Exception as e:
                return {"error": f"JS evaluation failed: {e}"}
        return _with_marionette(_impl)

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
        """Check if a CSS selector matches any elements.

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
        """Get the value of an input/textarea/select element."""
        js = f"document.querySelector({json.dumps(selector)})?.value || null"
        return self.eval_js(js, tab_index)

    def navigate(self, url: str, tab_index: int = 0, wait: float = 2.0) -> dict:
        """Navigate a tab to a URL and wait for it to load."""
        def _impl(client):
            handles = client.window_handles
            if tab_index >= len(handles):
                return {"error": f"Tab index {tab_index} out of range"}
            client.switch_to_window(handles[tab_index])
            client.navigate(url)
            if wait > 0:
                time.sleep(wait)
            return {"url": client.get_url(), "title": client.title}
        return _with_marionette(_impl)

    def take_screenshot(self, tab_index: int = 0) -> dict:
        """Capture a screenshot of the tab. Returns base64-encoded PNG."""
        def _impl(client):
            handles = client.window_handles
            if tab_index >= len(handles):
                return {"error": f"Tab index {tab_index} out of range"}
            client.switch_to_window(handles[tab_index])
            data = client.screenshot()
            return {"format": "png", "data_base64": data[:100] + "...(truncated)"}
        return _with_marionette(_impl)

    # === SQLite: Persistent state ===

    def get_history(self, query: str | None = None, limit: int = 20) -> list[dict]:
        """Search browsing history from places.sqlite.

        Example:
            v.get_history(query="github", limit=5)
            => [{"url": "https://github.com", "title": "GitHub", "visit_count": 3, ...}]
        """
        if query:
            sql = """
                SELECT p.url, p.title, p.visit_count,
                       datetime(h.visit_date/1000000, 'unixepoch') as last_visit
                FROM moz_places p
                LEFT JOIN moz_historyvisits h ON p.id = h.place_id
                WHERE p.url LIKE ? OR p.title LIKE ?
                GROUP BY p.id
                ORDER BY MAX(h.visit_date) DESC
                LIMIT ?
            """
            pattern = f"%{query}%"
            return _query_sqlite("places.sqlite", sql, (pattern, pattern, limit))
        else:
            sql = """
                SELECT p.url, p.title, p.visit_count,
                       datetime(h.visit_date/1000000, 'unixepoch') as last_visit
                FROM moz_places p
                LEFT JOIN moz_historyvisits h ON p.id = h.place_id
                WHERE p.visit_count > 0
                GROUP BY p.id
                ORDER BY MAX(h.visit_date) DESC
                LIMIT ?
            """
            return _query_sqlite("places.sqlite", sql, (limit,))

    def get_bookmarks(self, query: str | None = None) -> dict:
        """Read Firefox bookmarks from places.sqlite.

        Example:
            v.get_bookmarks(query="github")
            => {"count": 1, "matches": [{"title": "GitHub", "url": "https://github.com", "folder": "toolbar"}]}
        """
        if query:
            sql = """
                SELECT b.title, p.url,
                       (SELECT pb.title FROM moz_bookmarks pb WHERE pb.id = b.parent) as folder
                FROM moz_bookmarks b
                JOIN moz_places p ON b.fk = p.id
                WHERE b.type = 1 AND (b.title LIKE ? OR p.url LIKE ?)
                ORDER BY b.dateAdded DESC
            """
            pattern = f"%{query}%"
            rows = _query_sqlite("places.sqlite", sql, (pattern, pattern))
        else:
            sql = """
                SELECT b.title, p.url,
                       (SELECT pb.title FROM moz_bookmarks pb WHERE pb.id = b.parent) as folder
                FROM moz_bookmarks b
                JOIN moz_places p ON b.fk = p.id
                WHERE b.type = 1
                ORDER BY b.dateAdded DESC
            """
            rows = _query_sqlite("places.sqlite", sql)

        if rows and "error" in rows[0]:
            return rows[0]
        return {"count": len(rows), "matches": rows}

    def get_downloads(self, limit: int = 20) -> list[dict]:
        """List recent downloads from places.sqlite.

        Downloads are stored as annotations on places entries.
        """
        sql = """
            SELECT p.url,
                   a.content as target_path,
                   datetime(a.dateAdded/1000000, 'unixepoch') as download_date
            FROM moz_annos a
            JOIN moz_places p ON a.place_id = p.id
            JOIN moz_anno_attributes aa ON a.anno_attribute_id = aa.id
            WHERE aa.name = 'downloads/destinationFileURI'
            ORDER BY a.dateAdded DESC
            LIMIT ?
        """
        rows = _query_sqlite("places.sqlite", sql, (limit,))
        if rows and "error" in rows[0]:
            # Fallback: try the simpler downloads table (newer Firefox versions)
            sql2 = """
                SELECT p.url, p.title,
                       datetime(h.visit_date/1000000, 'unixepoch') as download_date
                FROM moz_places p
                JOIN moz_historyvisits h ON p.id = h.place_id
                WHERE h.visit_type = 7
                ORDER BY h.visit_date DESC
                LIMIT ?
            """
            return _query_sqlite("places.sqlite", sql2, (limit,))
        return rows

    def get_cookies(self, domain: str | None = None) -> dict:
        """Read cookies from cookies.sqlite.

        Example:
            v.get_cookies(domain="github.com")
        """
        if domain:
            sql = """
                SELECT name, value, host, path,
                       datetime(expiry, 'unixepoch') as expires,
                       isSecure, isHttpOnly
                FROM moz_cookies
                WHERE host LIKE ?
                ORDER BY lastAccessed DESC
            """
            rows = _query_sqlite("cookies.sqlite", sql, (f"%{domain}%",))
        else:
            sql = """
                SELECT name, value, host, path,
                       datetime(expiry, 'unixepoch') as expires,
                       isSecure, isHttpOnly
                FROM moz_cookies
                ORDER BY lastAccessed DESC
                LIMIT 50
            """
            rows = _query_sqlite("cookies.sqlite", sql)

        if rows and "error" in rows[0]:
            return rows[0]
        return {"count": len(rows), "cookies": rows}

    def get_preferences(self, key: str | None = None) -> Any:
        """Read Firefox preferences from prefs.js.

        Example:
            v.get_preferences("browser.download.dir")
            => "/home/user/Downloads"
        """
        profile = _find_profile_dir()
        if not profile:
            return {"error": "Profile not found"}

        prefs_path = profile / "prefs.js"
        if not prefs_path.exists():
            return {"error": "prefs.js not found"}

        prefs = {}
        with open(prefs_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("user_pref("):
                    # Parse: user_pref("key", value);
                    try:
                        inner = line[len("user_pref("):-2]  # strip user_pref( and );
                        comma_idx = inner.index(",")
                        k = json.loads(inner[:comma_idx].strip())
                        v = json.loads(inner[comma_idx + 1:].strip())
                        prefs[k] = v
                    except (ValueError, json.JSONDecodeError):
                        continue

        if key is None:
            return {"count": len(prefs), "keys": sorted(prefs.keys())[:50]}
        return prefs.get(key, {"error": f"Preference '{key}' not found"})

    def get_form_history(self, field_name: str | None = None, limit: int = 20) -> list[dict]:
        """Read form history from formhistory.sqlite."""
        if field_name:
            sql = """
                SELECT fieldname, value, timesUsed,
                       datetime(lastUsed/1000000, 'unixepoch') as last_used
                FROM moz_formhistory
                WHERE fieldname LIKE ?
                ORDER BY lastUsed DESC
                LIMIT ?
            """
            return _query_sqlite("formhistory.sqlite", sql, (f"%{field_name}%", limit))
        else:
            sql = """
                SELECT fieldname, value, timesUsed,
                       datetime(lastUsed/1000000, 'unixepoch') as last_used
                FROM moz_formhistory
                ORDER BY lastUsed DESC
                LIMIT ?
            """
            return _query_sqlite("formhistory.sqlite", sql, (limit,))

    # === Composite checks ===

    def check_url_visited(self, url_substring: str) -> dict:
        """Check if a URL matching the substring was visited.

        Example:
            v.check_url_visited("github.com")
            => {"visited": true, "match_count": 3, "latest": {...}}
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
            => {"found": true, "tab": {"url": "https://google.com", ...}}
        """
        tabs = self.get_tabs()
        if isinstance(tabs, dict) and "error" in tabs:
            return tabs
        if isinstance(tabs, list) and tabs and "error" in tabs[0]:
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
        if not isinstance(page_text, str):
            page_text = str(page_text) if page_text else ""
        found = text.lower() in page_text.lower()
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

    def check_cookie_set(self, name: str, domain: str | None = None) -> dict:
        """Check if a cookie with the given name exists.

        Example:
            v.check_cookie_set("session_id", domain="github.com")
            => {"exists": true, "cookie": {...}}
        """
        result = self.get_cookies(domain=domain)
        if "error" in result:
            return result

        for cookie in result.get("cookies", []):
            if cookie.get("name") == name:
                return {"exists": True, "cookie": cookie}
        return {"exists": False}

    def check_download_complete(self, filename_substring: str) -> dict:
        """Check if a file matching the name was downloaded.

        Checks both the downloads DB and the filesystem.
        """
        # Check filesystem in common download locations
        download_dirs = [
            Path.home() / "Downloads",
            Path("/tmp"),
            Path.home(),
        ]
        for d in download_dirs:
            if not d.exists():
                continue
            for f in d.iterdir():
                if filename_substring.lower() in f.name.lower() and f.is_file():
                    return {
                        "downloaded": True,
                        "file_exists": True,
                        "path": str(f),
                        "size": f.stat().st_size,
                    }
        return {"downloaded": False, "file_exists": False}

    def _get_preference_live(self, key: str) -> dict:
        """Read the *effective* preference value via Marionette (includes defaults).

        Uses the chrome-context Services.prefs API so prefs that are still at
        their built-in default (and therefore absent from prefs.js) are still
        visible. Returns one of:
            {"found": True, "value": <bool|int|str>, "source": "marionette"|"marionette-default"}
            {"found": False}
            {"error": "..."}
        """
        def _impl(client):
            try:
                try:
                    client.set_context("chrome")
                except Exception as ctx_err:
                    return {"error": f"chrome context unavailable: {ctx_err}"}
                script = (
                    "const k = arguments[0];"
                    "let svc;"
                    "if (typeof Services !== 'undefined') { svc = Services; }"
                    "else {"
                    "  try {"
                    "    const mod = ChromeUtils.importESModule('resource://gre/modules/Services.sys.mjs');"
                    "    svc = mod.Services;"
                    "  } catch (e) {"
                    "    return {found: false, error: 'Services unavailable: ' + (e && e.message ? e.message : String(e))};"
                    "  }"
                    "}"
                    "const p = svc.prefs;"
                    "const t = p.getPrefType(k);"
                    "function readAt(branch, type) {"
                    "  try {"
                    "    if (type === p.PREF_STRING) return branch.getStringPref(k);"
                    "    if (type === p.PREF_INT) return branch.getIntPref(k);"
                    "    if (type === p.PREF_BOOL) return branch.getBoolPref(k);"
                    "  } catch (e) { return undefined; }"
                    "  return undefined;"
                    "}"
                    "if (t !== p.PREF_INVALID) {"
                    "  const v = readAt(p, t);"
                    "  if (v !== undefined) return {found: true, value: v, source: 'marionette'};"
                    "}"
                    "const db = p.getDefaultBranch('');"
                    "for (const type of [p.PREF_STRING, p.PREF_INT, p.PREF_BOOL]) {"
                    "  const v = readAt(db, type);"
                    "  if (v !== undefined) return {found: true, value: v, source: 'marionette-default'};"
                    "}"
                    "return {found: false};"
                )
                result = client.execute_script(script, script_args=[key])
                return result if isinstance(result, dict) else {"found": False}
            except Exception as e:
                return {"error": f"live pref read failed: {e}"}
            finally:
                try:
                    client.set_context("content")
                except Exception:
                    pass
        return _with_marionette(_impl)

    def check_preference_set(self, key: str, expected_value: Any = None) -> dict:
        """Check if a Firefox preference is set (optionally to a specific value).

        Reads prefs.js first (user-modified prefs). If the key is not present
        there, falls back to Marionette's Services.prefs to read the live
        effective value (covering prefs still at their Firefox default).

        When comparing, the CLI-provided expected_value is coerced to the
        runtime type of the actual value so "true"/"false"/"1"/"0" match
        booleans and integer strings match ints.

        Example:
            v.check_preference_set("browser.download.dir", "/home/user/Downloads")
            => {"set": true, "match": true, "value": "/home/user/Downloads"}
        """
        actual = self.get_preferences(key)
        source = "prefs.js"
        if isinstance(actual, dict) and "error" in actual:
            # Fall back to live effective value (covers default-valued prefs).
            live = self._get_preference_live(key)
            if isinstance(live, dict) and live.get("found"):
                actual = live.get("value")
                source = live.get("source") or "marionette"
            else:
                err = actual["error"]
                if isinstance(live, dict) and "error" in live:
                    err = f"{err}; live fallback: {live['error']}"
                return {"set": False, "match": False, "error": err}

        if expected_value is None:
            return {"set": True, "value": actual, "source": source}

        coerced_expected: Any = expected_value
        match = False
        # bool must be checked before int because bool is a subclass of int in Python.
        if isinstance(actual, bool):
            if isinstance(expected_value, bool):
                coerced_expected = expected_value
            elif isinstance(expected_value, str):
                low = expected_value.strip().lower()
                if low in ("true", "1"):
                    coerced_expected = True
                elif low in ("false", "0"):
                    coerced_expected = False
            elif isinstance(expected_value, (int, float)):
                coerced_expected = bool(expected_value)
            match = (coerced_expected == actual) and isinstance(coerced_expected, bool)
        elif isinstance(actual, int):
            try:
                coerced_expected = int(expected_value)
                match = (coerced_expected == actual)
            except (ValueError, TypeError):
                match = str(actual) == str(expected_value)
        elif isinstance(actual, float):
            try:
                coerced_expected = float(expected_value)
                match = (coerced_expected == actual)
            except (ValueError, TypeError):
                match = str(actual) == str(expected_value)
        else:
            match = str(actual) == str(expected_value)

        return {
            "set": True,
            "match": match,
            "expected": coerced_expected,
            "actual": actual,
            "source": source,
        }


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

COMMANDS = {
    # Marionette real-time
    "tabs": ("List open tabs", lambda v, args: v.get_tabs()),
    "url": ("Get current tab URL", lambda v, args: v.get_page_url(int(args[0]) if args else 0)),
    "title": ("Get current tab title", lambda v, args: v.get_page_title(int(args[0]) if args else 0)),
    "text": ("Get page text content", lambda v, args: v.get_page_text(int(args[0]) if args else 0)),
    "html": ("Get page HTML (truncated)", lambda v, args: v.get_page_html(int(args[0]) if args else 0)),
    "eval": ("Evaluate JS expression", lambda v, args: v.eval_js(args[0], int(args[1]) if len(args) > 1 else 0)),
    "select": ("Query CSS selector", lambda v, args: v.query_selector(args[0], int(args[1]) if len(args) > 1 else 0)),
    "input": ("Get input field value", lambda v, args: v.get_input_value(args[0], int(args[1]) if len(args) > 1 else 0)),
    "navigate": ("Navigate to URL", lambda v, args: v.navigate(args[0], int(args[1]) if len(args) > 1 else 0)),
    "screenshot": ("Capture tab screenshot", lambda v, args: v.take_screenshot(int(args[0]) if args else 0)),

    # SQLite persistent state
    "history": ("Search browsing history", lambda v, args: v.get_history(query=args[0] if args else None)),
    "bookmarks": ("Search bookmarks", lambda v, args: v.get_bookmarks(query=args[0] if args else None)),
    "downloads": ("List downloads", lambda v, args: v.get_downloads()),
    "cookies": ("Get cookies", lambda v, args: v.get_cookies(domain=args[0] if args else None)),
    "prefs": ("Read preference", lambda v, args: v.get_preferences(args[0] if args else None)),
    "form-history": ("Search form history", lambda v, args: v.get_form_history(field_name=args[0] if args else None)),

    # Composite checks
    "check-url-visited": ("Check if URL was visited", lambda v, args: v.check_url_visited(args[0])),
    "check-tab-open": ("Check if tab is open", lambda v, args: v.check_tab_open(url_substring=args[0])),
    "check-page-contains": ("Check if page has text", lambda v, args: v.check_page_contains(args[0], int(args[1]) if len(args) > 1 else 0)),
    "check-element-exists": ("Check CSS selector match", lambda v, args: v.check_element_exists(args[0], int(args[1]) if len(args) > 1 else 0)),
    "check-bookmark": ("Check bookmark exists", lambda v, args: v.check_bookmark_exists(args[0])),
    "check-cookie": ("Check cookie exists", lambda v, args: v.check_cookie_set(args[0], args[1] if len(args) > 1 else None)),
    "check-download": ("Check download completed", lambda v, args: v.check_download_complete(args[0])),
    "check-pref": ("Check preference value", lambda v, args: v.check_preference_set(args[0], args[1] if len(args) > 1 else None)),
}


def _print_usage():
    print("Firefox ESR Verifier — query Firefox state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nMarionette requires Firefox running with --marionette (port {MARIONETTE_PORT})")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = FirefoxVerifier()
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
