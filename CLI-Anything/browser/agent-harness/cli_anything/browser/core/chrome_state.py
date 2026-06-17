"""Chrome state helpers for verifier-compatible browser automation.

This module complements the DOMShell accessibility-tree harness with direct
Chrome DevTools Protocol and profile-file operations. The verifier reads these
surfaces directly, so commands here write or query the same persisted state.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


CDP_HOST = os.environ.get("CHROME_CDP_HOST", "127.0.0.1")
CDP_PORT = int(os.environ.get("CHROME_CDP_PORT", "9222"))
CDP_BASE = f"http://{CDP_HOST}:{CDP_PORT}"


def chrome_time(now: float | None = None) -> int:
    """Return Chrome/WebKit timestamp microseconds since 1601-01-01."""
    return int((now if now is not None else time.time()) * 1_000_000 + 11644473600 * 1_000_000)


def profile_dir(create: bool = False, profile: str | None = None) -> Path:
    """Resolve the Chrome Default profile directory used by verifier code."""
    raw = profile or os.environ.get("CHROME_PROFILE_DIR")
    candidates: list[Path] = []
    if raw:
        p = Path(raw).expanduser()
        candidates.extend([p, p / "Default"])
    candidates.extend([
        Path.home() / ".config" / "google-chrome" / "Default",
        Path.home() / ".config" / "google-chrome-stable" / "Default",
        Path.home() / ".config" / "chromium" / "Default",
    ])

    for candidate in candidates:
        if candidate.exists() or create:
            if candidate.name == "Default":
                target = candidate
            else:
                target = candidate / "Default"
            if create:
                target.mkdir(parents=True, exist_ok=True)
            return target
    raise FileNotFoundError("Chrome profile directory not found; set CHROME_PROFILE_DIR")


def cdp_get(path: str, timeout: float = 5.0) -> Any:
    req = urllib.request.Request(f"{CDP_BASE}{path}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        return {"error": f"CDP connection failed: {e}"}


def cdp_send(ws_url: str, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
    try:
        import websocket
    except ImportError:
        return {"error": "websocket-client not installed"}

    payload = json.dumps({"id": 1, "method": method, "params": params or {}})
    ws = websocket.create_connection(ws_url, timeout=timeout)
    try:
        ws.send(payload)
        while True:
            data = json.loads(ws.recv())
            if data.get("id") == 1:
                return data.get("result", data)
    finally:
        ws.close()


def page_tab(index: int = 0) -> dict:
    tabs = cdp_get("/json")
    if isinstance(tabs, dict) and "error" in tabs:
        return tabs
    pages = [tab for tab in tabs if tab.get("type") == "page"]
    if not pages:
        return {"error": "No page tabs found"}
    if index >= len(pages):
        return {"error": f"Tab index {index} out of range"}
    return pages[index]


def tabs() -> list[dict] | dict:
    result = cdp_get("/json")
    if isinstance(result, dict) and "error" in result:
        return result
    return [
        {
            "id": tab.get("id"),
            "url": tab.get("url"),
            "title": tab.get("title"),
            "type": tab.get("type"),
        }
        for tab in result
    ]


def eval_js(expression: str, tab_index: int = 0) -> dict:
    tab = page_tab(tab_index)
    if "error" in tab:
        return tab
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return {"error": "No WebSocket URL for tab"}
    result = cdp_send(ws_url, "Runtime.evaluate", {"expression": expression, "returnByValue": True})
    if "error" in result:
        return result
    remote = result.get("result", {})
    return {
        "type": remote.get("type"),
        "value": remote.get("value"),
        "description": remote.get("description"),
    }


def query_selector(selector: str, tab_index: int = 0) -> dict:
    js = f"""
    (() => {{
      const els = document.querySelectorAll({json.dumps(selector)});
      const first = els[0];
      return {{
        count: els.length,
        first_text: first?.innerText?.substring(0, 500) || null,
        first_tag: first?.tagName || null,
        first_id: first?.id || null,
        first_class: first?.className || null
      }};
    }})()
    """
    return eval_js(js, tab_index)


def input_value(selector: str, tab_index: int = 0) -> dict:
    return eval_js(f"document.querySelector({json.dumps(selector)})?.value || null", tab_index)


def fill_input(selector: str, value: str, tab_index: int = 0) -> dict:
    js = f"""
    (() => {{
      const el = document.querySelector({json.dumps(selector)});
      if (!el) return {{ok: false, error: "selector not found"}};
      el.focus();
      el.value = {json.dumps(value)};
      el.dispatchEvent(new Event("input", {{bubbles: true}}));
      el.dispatchEvent(new Event("change", {{bubbles: true}}));
      return {{ok: true, value: el.value}};
    }})()
    """
    return eval_js(js, tab_index)


def cookies(tab_index: int = 0) -> dict:
    tab = page_tab(tab_index)
    if "error" in tab:
        return tab
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return {"error": "No WebSocket URL for tab"}
    result = cdp_send(ws_url, "Network.getCookies")
    if "error" in result:
        return result
    return {"cookies": result.get("cookies", [])}


def set_cookie(name: str, value: str, url: str | None = None, domain: str | None = None, path: str = "/", tab_index: int = 0) -> dict:
    tab = page_tab(tab_index)
    if "error" in tab:
        return tab
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return {"error": "No WebSocket URL for tab"}
    params: dict[str, Any] = {"name": name, "value": value, "path": path}
    if url:
        params["url"] = url
    if domain:
        params["domain"] = domain
    result = cdp_send(ws_url, "Network.setCookie", params)
    return result if "error" in result else {"success": bool(result.get("success", False)), **result}


def screenshot(tab_index: int = 0, image_format: str = "png") -> dict:
    tab = page_tab(tab_index)
    if "error" in tab:
        return tab
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return {"error": "No WebSocket URL for tab"}
    result = cdp_send(ws_url, "Page.captureScreenshot", {"format": image_format})
    if "error" in result:
        return result
    data = result.get("data", "")
    return {"format": image_format, "data_base64": data[:100] + "...(truncated)"}


def navigate(url: str, tab_index: int = 0, wait: float = 2.0) -> dict:
    tab = page_tab(tab_index)
    if "error" in tab:
        return tab
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return {"error": "No WebSocket URL for tab"}
    result = cdp_send(ws_url, "Page.navigate", {"url": url})
    if wait > 0:
        time.sleep(wait)
    return result


def _history_db(profile: Path) -> Path:
    profile.mkdir(parents=True, exist_ok=True)
    db = profile / "History"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS urls ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, url LONGVARCHAR, title LONGVARCHAR, "
            "visit_count INTEGER DEFAULT 0, typed_count INTEGER DEFAULT 0, "
            "last_visit_time INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS downloads ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, target_path LONGVARCHAR, tab_url LONGVARCHAR, "
            "total_bytes INTEGER DEFAULT 0, received_bytes INTEGER DEFAULT 0, "
            "state INTEGER DEFAULT 1, mime_type VARCHAR, start_time INTEGER DEFAULT 0)"
        )
        conn.commit()
    finally:
        conn.close()
    return db


def add_history(url: str, title: str = "", visit_count: int = 1, profile: str | None = None) -> dict:
    prof = profile_dir(create=True, profile=profile)
    db = _history_db(prof)
    now = chrome_time()
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO urls (url, title, visit_count, typed_count, last_visit_time, hidden) VALUES (?, ?, ?, 0, ?, 0)",
            (url, title, visit_count, now),
        )
        conn.commit()
    finally:
        conn.close()
    return {"profile": str(prof), "history": str(db), "url": url, "title": title}


def add_download(path: str, tab_url: str = "", mime_type: str = "application/octet-stream", state: int = 1, profile: str | None = None) -> dict:
    prof = profile_dir(create=True, profile=profile)
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(b"")
    size = target.stat().st_size
    db = _history_db(prof)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO downloads (target_path, tab_url, total_bytes, received_bytes, state, mime_type, start_time) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(target), tab_url, size, size, state, mime_type, chrome_time()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"profile": str(prof), "path": str(target), "state": state, "size": size}


def _read_json(path: Path, default: dict) -> dict:
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return default


def add_bookmark(name: str, url: str, folder: str = "bookmark_bar", profile: str | None = None) -> dict:
    prof = profile_dir(create=True, profile=profile)
    path = prof / "Bookmarks"
    data = _read_json(path, {
        "checksum": "",
        "roots": {
            "bookmark_bar": {"children": [], "name": "Bookmarks bar", "type": "folder"},
            "other": {"children": [], "name": "Other bookmarks", "type": "folder"},
            "synced": {"children": [], "name": "Mobile bookmarks", "type": "folder"},
        },
        "version": 1,
    })
    roots = data.setdefault("roots", {})
    root = roots.setdefault(folder, {"children": [], "name": folder, "type": "folder"})
    children = root.setdefault("children", [])
    next_id = str(max([int(node.get("id", "0")) for node in children if str(node.get("id", "0")).isdigit()] + [0]) + 1)
    children.append({"id": next_id, "name": name, "type": "url", "url": url})
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"profile": str(prof), "bookmarks": str(path), "name": name, "url": url, "folder": folder}


def set_preference(key_path: str, value: Any, profile: str | None = None) -> dict:
    prof = profile_dir(create=True, profile=profile)
    path = prof / "Preferences"
    prefs = _read_json(path, {})
    obj = prefs
    parts = key_path.split(".")
    for key in parts[:-1]:
        obj = obj.setdefault(key, {})
    obj[parts[-1]] = value
    path.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    return {"profile": str(prof), "preferences": str(path), "key": key_path, "value": value}


def install_extension(ext_id: str, name: str, version: str = "1.0.0", description: str = "", profile: str | None = None) -> dict:
    prof = profile_dir(create=True, profile=profile)
    ext_dir = prof.parent / "Extensions" / ext_id / version
    ext_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifest_version": 3,
        "name": name,
        "version": version,
        "description": description,
    }
    manifest_path = ext_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"profile": str(prof), "manifest": str(manifest_path), "id": ext_id, "name": name, "version": version}
