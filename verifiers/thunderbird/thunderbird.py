"""
Thunderbird Verifier — programmatic state inspection for Mozilla Thunderbird in E2B sandbox.

Verification channels (in order of preference):
  1. SQLite databases — contacts (abook.sqlite), calendar (local.sqlite),
     message index (global-messages-db.sqlite)
  2. mbox files — raw email content (Drafts, Sent, Inbox, Templates, Trash)
  3. prefs.js — user preferences (key=value pairs)
  4. File-based config — profile directory structure, account settings

Usage from outside the sandbox (via sandbox.commands.run):
    sandbox.commands.run("python3 /home/user/verifiers/thunderbird.py contacts")
    sandbox.commands.run("python3 /home/user/verifiers/thunderbird.py check-contact-exists 'John Doe'")
    sandbox.commands.run("python3 /home/user/verifiers/thunderbird.py calendar-events")

All public methods return dicts/lists serializable as JSON.
The CLI prints JSON to stdout for easy parsing by a check agent.

Requires:
  - Thunderbird profile at ~/.thunderbird/<profile>.default*
  - sqlite3 (standard library)
  - No external dependencies
"""

import email
import email.policy
import glob
import json
import mailbox
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _find_profile_dir() -> Path | None:
    """Find the active Thunderbird profile directory."""
    env_dir = os.environ.get("THUNDERBIRD_PROFILE_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.exists():
            return p

    tb_dir = Path.home() / ".thunderbird"
    if not tb_dir.exists():
        return None

    # Try profiles.ini to find the default profile
    profiles_ini = tb_dir / "profiles.ini"
    if profiles_ini.exists():
        install_default_path = None
        profile_default = None
        current_section_path = None
        current_section_is_relative = True
        current_section_is_default = False
        current_section_name = None

        def resolve_profile_path(path_str: str | None, is_relative: bool) -> Path | None:
            if not path_str:
                return None
            return (tb_dir / path_str) if is_relative else Path(path_str)

        def flush_profile_section() -> None:
            if not current_section_name or not current_section_name.startswith("Profile"):
                return
            if not current_section_is_default:
                return

            nonlocal profile_default
            if profile_default is None:
                profile_default = (current_section_path, current_section_is_relative)

        with open(profiles_ini) as f:
            for line in f:
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    flush_profile_section()
                    current_section_name = line[1:-1]
                    current_section_path = None
                    current_section_is_relative = True
                    current_section_is_default = False
                elif "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    if current_section_name and current_section_name.startswith("Install"):
                        if key == "Default":
                            install_default_path = val
                        continue
                    if key == "Path":
                        current_section_path = val
                    elif key == "IsRelative":
                        current_section_is_relative = val == "1"
                    elif key == "Default" and val == "1":
                        current_section_is_default = True

            flush_profile_section()

            if install_default_path:
                p = resolve_profile_path(install_default_path, True)
                if p and p.exists():
                    return p

            profile_default_path, profile_default_is_relative = profile_default or (None, True)
            p = resolve_profile_path(profile_default_path, profile_default_is_relative)
            if p and p.exists():
                return p

    # Fallback: glob for profile directories
    for pattern in ["*.default-release", "*.default"]:
        matches = sorted(tb_dir.glob(pattern))
        if matches:
            return matches[0]

    # Last resort: any directory that looks like a profile
    for d in sorted(tb_dir.iterdir()):
        if d.is_dir() and (d / "prefs.js").exists():
            return d

    return None


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

def _query_sqlite(db_path: Path, query: str, params: tuple = ()) -> list[dict]:
    """Query a SQLite DB safely (copies it first to avoid WAL locks)."""
    if not db_path.exists():
        return [{"error": f"Database not found: {db_path}"}]

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


def _query_sqlite_abs(db_path: str, query: str, params: tuple = ()) -> list[dict]:
    """Query a SQLite DB by absolute path string."""
    return _query_sqlite(Path(db_path), query, params)


# ---------------------------------------------------------------------------
# mbox helpers
# ---------------------------------------------------------------------------

def _find_mail_folder(profile: Path, folder_name: str) -> Path | None:
    """Find an mbox file for a mail folder (e.g. 'Drafts', 'Sent', 'Inbox').

    Thunderbird stores mail in:
      <profile>/Mail/Local Folders/<FolderName>  (local)
      <profile>/ImapMail/<server>/<FolderName>   (IMAP)
    The mbox file has no extension. There may also be a .msf index file.
    """
    # Search local folders first
    local_folders = profile / "Mail" / "Local Folders"
    if local_folders.exists():
        candidate = local_folders / folder_name
        if candidate.exists() and candidate.is_file():
            return candidate

    # Search IMAP folders
    imap_dir = profile / "ImapMail"
    if imap_dir.exists():
        for server_dir in imap_dir.iterdir():
            if server_dir.is_dir():
                candidate = server_dir / folder_name
                if candidate.exists() and candidate.is_file():
                    return candidate

    return None


def _parse_mbox(mbox_path: Path, limit: int = 50) -> list[dict]:
    """Parse an mbox file and return message summaries."""
    if not mbox_path.exists():
        return []

    messages = []
    try:
        mbox_file = mailbox.mbox(str(mbox_path))
        for i, msg in enumerate(mbox_file):
            if i >= limit:
                break
            # Extract body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ct = part.get_content_type()
                    if ct == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="replace")[:2000]
                            break
                    elif ct == "text/html" and not body:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="replace")[:2000]
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")[:2000]

            messages.append({
                "index": i,
                "from": msg.get("From", ""),
                "to": msg.get("To", ""),
                "cc": msg.get("Cc", ""),
                "subject": msg.get("Subject", ""),
                "date": msg.get("Date", ""),
                "message_id": msg.get("Message-ID", ""),
                "content_type": msg.get_content_type(),
                "body_preview": body[:500],
            })
        mbox_file.close()
    except Exception as e:
        return [{"error": f"Failed to parse mbox: {e}"}]

    return messages


def _list_mail_folders(profile: Path) -> list[dict]:
    """List all mail folders (mbox files) in the profile."""
    folders = []

    for base_name, base_dir in [("Local Folders", profile / "Mail" / "Local Folders"),
                                  ("ImapMail", profile / "ImapMail")]:
        if not base_dir.exists():
            continue

        if base_name == "Local Folders":
            for f in sorted(base_dir.iterdir()):
                if f.is_file() and not f.suffix == ".msf":
                    folders.append({
                        "name": f.name,
                        "path": str(f),
                        "type": "local",
                        "size_bytes": f.stat().st_size,
                    })
        else:
            for server_dir in sorted(base_dir.iterdir()):
                if not server_dir.is_dir():
                    continue
                for f in sorted(server_dir.iterdir()):
                    if f.is_file() and not f.suffix == ".msf":
                        folders.append({
                            "name": f.name,
                            "path": str(f),
                            "type": "imap",
                            "server": server_dir.name,
                            "size_bytes": f.stat().st_size,
                        })

    return folders


# ---------------------------------------------------------------------------
# Preferences helpers
# ---------------------------------------------------------------------------

def _parse_prefs_js(profile: Path) -> dict[str, Any]:
    """Parse prefs.js into a dict of key -> value."""
    prefs_path = profile / "prefs.js"
    if not prefs_path.exists():
        return {}

    prefs = {}
    with open(prefs_path) as f:
        for line in f:
            line = line.strip()
            # user_pref("key", value);
            m = re.match(r'user_pref\("([^"]+)",\s*(.+)\);', line)
            if m:
                key = m.group(1)
                raw_val = m.group(2).strip()
                # Parse value
                if raw_val == "true":
                    prefs[key] = True
                elif raw_val == "false":
                    prefs[key] = False
                elif raw_val.startswith('"') and raw_val.endswith('"'):
                    prefs[key] = raw_val[1:-1]
                else:
                    try:
                        prefs[key] = int(raw_val)
                    except ValueError:
                        try:
                            prefs[key] = float(raw_val)
                        except ValueError:
                            prefs[key] = raw_val
    return prefs


# ---------------------------------------------------------------------------
# ThunderbirdVerifier class
# ---------------------------------------------------------------------------

class ThunderbirdVerifier:
    """Stateless verifier — each method call is independent."""

    def __init__(self):
        self._profile = _find_profile_dir()

    def _require_profile(self) -> Path:
        if not self._profile:
            raise FileNotFoundError("Thunderbird profile directory not found")
        return self._profile

    # === Contacts (abook.sqlite) ===

    def get_contacts(self, query: str | None = None) -> list[dict]:
        """List contacts from the address book.

        Returns list of contacts with fields: uid, name, email, etc.
        Optional query filters by name or email (case-insensitive substring).
        """
        profile = self._require_profile()

        # Thunderbird 102+ uses abook.sqlite; older versions use abook.mab
        abook_path = profile / "abook.sqlite"
        if not abook_path.exists():
            # Check for alternative location
            abook_path = profile / "history.sqlite"
            if not abook_path.exists():
                return [{"error": "Address book database not found (abook.sqlite)"}]

        # abook.sqlite schema: tables 'lists' and 'properties'
        # Properties table: card (uid), name, value
        # Common properties: PrimaryEmail, DisplayName, FirstName, LastName,
        #   SecondEmail, WorkPhone, HomePhone, Company, Notes

        rows = _query_sqlite(abook_path, """
            SELECT card, name, value FROM properties
            ORDER BY card, name
        """)

        if rows and "error" in rows[0]:
            return rows

        # Group by card UID
        cards: dict[str, dict] = {}
        for row in rows:
            uid = row["card"]
            if uid not in cards:
                cards[uid] = {"uid": uid}
            cards[uid][row["name"]] = row["value"]

        contacts = []
        for uid, props in cards.items():
            contact = {
                "uid": uid,
                "display_name": props.get("DisplayName", ""),
                "first_name": props.get("FirstName", ""),
                "last_name": props.get("LastName", ""),
                "primary_email": props.get("PrimaryEmail", ""),
                "second_email": props.get("SecondEmail", ""),
                "work_phone": props.get("WorkPhone", ""),
                "home_phone": props.get("HomePhone", ""),
                "company": props.get("Company", ""),
                "job_title": props.get("JobTitle", ""),
                "notes": props.get("Notes", ""),
                "nickname": props.get("NickName", ""),
            }

            if query:
                q = query.lower()
                searchable = f"{contact['display_name']} {contact['first_name']} {contact['last_name']} {contact['primary_email']} {contact['second_email']}".lower()
                if q not in searchable:
                    continue

            contacts.append(contact)

        return contacts

    def get_contact_count(self) -> dict:
        """Get the total number of contacts in the address book."""
        contacts = self.get_contacts()
        if contacts and isinstance(contacts[0], dict) and "error" in contacts[0]:
            return contacts[0]
        return {"count": len(contacts)}

    def get_mailing_lists(self) -> list[dict]:
        """List mailing lists from the address book."""
        profile = self._require_profile()
        abook_path = profile / "abook.sqlite"
        if not abook_path.exists():
            return [{"error": "Address book database not found"}]

        rows = _query_sqlite(abook_path, """
            SELECT uid, name, nickName, description FROM lists
        """)
        return rows

    # === Calendar (calendar-data/local.sqlite) ===

    def get_calendar_events(self, limit: int = 50) -> list[dict]:
        """List calendar events.

        Returns events with title, start/end time, location, description, etc.
        """
        profile = self._require_profile()
        cal_db = profile / "calendar-data" / "local.sqlite"
        if not cal_db.exists():
            return [{"error": f"Calendar database not found at {cal_db}"}]

        rows = _query_sqlite(cal_db, """
            SELECT
                cal_id, id, title,
                event_start, event_end, event_start_tz, event_end_tz,
                flags, ical_status,
                recurrence_id, recurrence_id_tz,
                alarm_last_ack
            FROM cal_events
            ORDER BY event_start DESC
            LIMIT ?
        """, (limit,))
        return rows

    def get_calendar_todos(self, limit: int = 50) -> list[dict]:
        """List calendar tasks/todos."""
        profile = self._require_profile()
        cal_db = profile / "calendar-data" / "local.sqlite"
        if not cal_db.exists():
            return [{"error": f"Calendar database not found at {cal_db}"}]

        rows = _query_sqlite(cal_db, """
            SELECT
                cal_id, id, title,
                todo_entry, todo_due, todo_completed, todo_complete,
                ical_status, priority
            FROM cal_todos
            ORDER BY todo_due DESC
            LIMIT ?
        """, (limit,))
        return rows

    def get_calendar_event_extras(self, event_id: str) -> dict:
        """Get extra properties (attendees, location, description, etc.) for an event."""
        profile = self._require_profile()
        cal_db = profile / "calendar-data" / "local.sqlite"
        if not cal_db.exists():
            return {"error": f"Calendar database not found at {cal_db}"}

        # cal_properties stores per-item extra data
        rows = _query_sqlite(cal_db, """
            SELECT key, value FROM cal_properties
            WHERE item_id = ?
        """, (event_id,))

        if rows and "error" in rows[0]:
            return rows[0]

        props = {}
        for row in rows:
            props[row["key"]] = row["value"]
        return {"event_id": event_id, "properties": props}

    def get_calendar_count(self) -> dict:
        """Count calendar events and todos."""
        profile = self._require_profile()
        cal_db = profile / "calendar-data" / "local.sqlite"
        if not cal_db.exists():
            return {"error": f"Calendar database not found at {cal_db}"}

        events = _query_sqlite(cal_db, "SELECT COUNT(*) as cnt FROM cal_events")
        todos = _query_sqlite(cal_db, "SELECT COUNT(*) as cnt FROM cal_todos")

        event_count = events[0]["cnt"] if events and "error" not in events[0] else 0
        todo_count = todos[0]["cnt"] if todos and "error" not in todos[0] else 0

        return {"events": event_count, "todos": todo_count}

    # === Email / mbox ===

    def get_mail_folders(self) -> list[dict]:
        """List all mail folders (mbox files) in the profile."""
        profile = self._require_profile()
        return _list_mail_folders(profile)

    def get_messages(self, folder: str = "Drafts", limit: int = 50) -> list[dict]:
        """Read messages from a mail folder (mbox format).

        Common folders: Inbox, Drafts, Sent, Templates, Trash, Archives
        """
        profile = self._require_profile()
        mbox_path = _find_mail_folder(profile, folder)
        if not mbox_path:
            return [{"error": f"Mail folder '{folder}' not found"}]
        return _parse_mbox(mbox_path, limit)

    def get_message_count(self, folder: str = "Drafts") -> dict:
        """Count messages in a mail folder."""
        profile = self._require_profile()
        mbox_path = _find_mail_folder(profile, folder)
        if not mbox_path:
            return {"error": f"Mail folder '{folder}' not found"}

        try:
            mbox_file = mailbox.mbox(str(mbox_path))
            count = len(mbox_file)
            mbox_file.close()
            return {"folder": folder, "count": count}
        except Exception as e:
            return {"error": f"Failed to read mbox: {e}"}

    def search_messages(self, query: str, folder: str | None = None, limit: int = 20) -> list[dict]:
        """Search messages by subject, sender, or body content.

        If folder is None, searches all folders.
        """
        profile = self._require_profile()
        results = []

        if folder:
            folders_to_search = [folder]
        else:
            mail_folders = _list_mail_folders(profile)
            folders_to_search = [f["name"] for f in mail_folders]

        q = query.lower()
        for fname in folders_to_search:
            mbox_path = _find_mail_folder(profile, fname)
            if not mbox_path:
                continue
            messages = _parse_mbox(mbox_path, limit=200)
            for msg in messages:
                if "error" in msg:
                    continue
                searchable = f"{msg.get('subject', '')} {msg.get('from', '')} {msg.get('to', '')} {msg.get('body_preview', '')}".lower()
                if q in searchable:
                    msg["folder"] = fname
                    results.append(msg)
                    if len(results) >= limit:
                        return results

        return results

    # === Message index (global-messages-db.sqlite) ===

    def get_message_index(self, query: str | None = None, limit: int = 50) -> list[dict]:
        """Query the global message index (global-messages-db.sqlite).

        This is Thunderbird's full-text search index. Faster than parsing mbox
        for large mailboxes, but may not reflect very recent changes.
        """
        profile = self._require_profile()
        db_path = profile / "global-messages-db.sqlite"
        if not db_path.exists():
            return [{"error": "global-messages-db.sqlite not found"}]

        if query:
            sql = """
                SELECT m.id, m.folderID, m.messageKey, m.conversationID,
                       json_extract(m.jsonAttributes, '$.subject') as subject,
                       json_extract(m.jsonAttributes, '$.from') as sender,
                       json_extract(m.jsonAttributes, '$.date') as date
                FROM messagesText_content mt
                JOIN messages m ON mt.rowid = m.id
                WHERE messagesText_content MATCH ?
                ORDER BY m.id DESC
                LIMIT ?
            """
            return _query_sqlite(db_path, sql, (query, limit))
        else:
            sql = """
                SELECT id, folderID, messageKey, conversationID,
                       json_extract(jsonAttributes, '$.subject') as subject,
                       json_extract(jsonAttributes, '$.from') as sender,
                       json_extract(jsonAttributes, '$.date') as date
                FROM messages
                ORDER BY id DESC
                LIMIT ?
            """
            return _query_sqlite(db_path, sql, (limit,))

    # === Preferences (prefs.js) ===

    def get_preferences(self, key: str | None = None) -> Any:
        """Read Thunderbird preferences from prefs.js.

        Without key: returns all preference keys (grouped by prefix).
        With key: returns the value for that specific preference.

        Common keys:
          mail.identity.id1.fullName — account display name
          mail.identity.id1.useremail — account email
          mail.server.server1.hostname — server hostname
          font.name.serif.x-western — serif font
          mail.compose.font_size — compose font size
          mailnews.default_sort_type — sort type
          mail.startup.enabledMailCheckOnce — check mail on startup
        """
        profile = self._require_profile()
        prefs = _parse_prefs_js(profile)

        if not prefs:
            return {"error": "prefs.js not found or empty"}

        if key is None:
            # Group by prefix for readability
            prefixes: dict[str, int] = {}
            for k in prefs:
                prefix = k.split(".")[0] if "." in k else k
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
            return {"total_prefs": len(prefs), "prefixes": prefixes}

        if key in prefs:
            return {"key": key, "value": prefs[key]}
        return {"error": f"Preference '{key}' not found"}

    def get_preferences_matching(self, pattern: str) -> dict:
        """Get all preferences matching a substring pattern.

        Example: get_preferences_matching("font") returns all font-related prefs.
        """
        profile = self._require_profile()
        prefs = _parse_prefs_js(profile)

        if not prefs:
            return {"error": "prefs.js not found or empty"}

        p = pattern.lower()
        matches = {k: v for k, v in prefs.items() if p in k.lower()}
        return {"pattern": pattern, "count": len(matches), "matches": matches}

    # === Accounts ===

    def get_accounts(self) -> list[dict]:
        """List configured mail accounts from prefs.js.

        Returns account details: name, email, server, type.
        """
        profile = self._require_profile()
        prefs = _parse_prefs_js(profile)

        if not prefs:
            return [{"error": "prefs.js not found or empty"}]

        # Parse identity and server info
        identities = {}
        servers = {}

        for key, value in prefs.items():
            # mail.identity.id1.fullName, mail.identity.id1.useremail, etc.
            m = re.match(r"mail\.identity\.(id\d+)\.(.+)", key)
            if m:
                ident_id = m.group(1)
                field = m.group(2)
                if ident_id not in identities:
                    identities[ident_id] = {"id": ident_id}
                identities[ident_id][field] = value
                continue

            # mail.server.server1.hostname, mail.server.server1.type, etc.
            m = re.match(r"mail\.server\.(server\d+)\.(.+)", key)
            if m:
                srv_id = m.group(1)
                field = m.group(2)
                if srv_id not in servers:
                    servers[srv_id] = {"id": srv_id}
                servers[srv_id][field] = value

        # Build account list
        accounts = []
        for ident_id, ident in identities.items():
            accounts.append({
                "identity_id": ident_id,
                "full_name": ident.get("fullName", ""),
                "email": ident.get("useremail", ""),
                "smtp_server": ident.get("smtpServer", ""),
                "reply_to": ident.get("reply_to", ""),
                "organization": ident.get("organization", ""),
                "compose_html": ident.get("compose_html", ""),
                "sig_file": ident.get("sig_file", ""),
            })

        return accounts if accounts else [{"info": "No identities configured", "servers": list(servers.values())}]

    # === File I/O ===

    def check_file_exists(self, file_path: str) -> dict:
        """Check if a file exists on disk.

        Useful for verifying file save/export tasks.
        """
        p = Path(file_path)
        if p.exists():
            stat = p.stat()
            return {
                "exists": True,
                "path": str(p),
                "size_bytes": stat.st_size,
                "is_file": p.is_file(),
                "is_dir": p.is_dir(),
            }
        return {"exists": False, "path": str(p)}

    def get_profile_info(self) -> dict:
        """Get Thunderbird profile directory info."""
        profile = self._require_profile()
        return {
            "profile_path": str(profile),
            "exists": profile.exists(),
            "contents": sorted([f.name for f in profile.iterdir()])[:50] if profile.exists() else [],
        }

    # === Composite checks ===

    def check_contact_exists(self, name_or_email: str) -> dict:
        """Check if a contact matching the name or email exists.

        Returns {"found": true/false, ...}
        """
        contacts = self.get_contacts(query=name_or_email)
        if contacts and isinstance(contacts[0], dict) and "error" in contacts[0]:
            return contacts[0]
        return {
            "found": len(contacts) > 0,
            "match_count": len(contacts),
            "matches": contacts[:5],
        }

    def check_contact_field(self, name_or_email: str, field: str, expected: str) -> dict:
        """Check if a contact has a specific field value.

        Fields: display_name, first_name, last_name, primary_email,
                second_email, work_phone, home_phone, company, job_title, notes, nickname
        """
        contacts = self.get_contacts(query=name_or_email)
        if contacts and isinstance(contacts[0], dict) and "error" in contacts[0]:
            return contacts[0]

        if not contacts:
            return {"match": False, "reason": f"No contact matching '{name_or_email}'"}

        for contact in contacts:
            actual = contact.get(field, "")
            if str(actual).lower() == str(expected).lower():
                return {"match": True, "contact": contact, "field": field, "expected": expected, "actual": actual}

        return {
            "match": False,
            "field": field,
            "expected": expected,
            "actual_values": [c.get(field, "") for c in contacts[:5]],
        }

    def check_calendar_event_exists(self, title_substring: str) -> dict:
        """Check if a calendar event matching the title exists.

        Returns {"found": true/false, ...}
        """
        events = self.get_calendar_events(limit=200)
        if events and "error" in events[0]:
            return events[0]

        q = title_substring.lower()
        matches = [e for e in events if q in (e.get("title") or "").lower()]
        return {
            "found": len(matches) > 0,
            "match_count": len(matches),
            "matches": matches[:5],
        }

    def check_calendar_todo_exists(self, title_substring: str) -> dict:
        """Check if a calendar todo matching the title exists."""
        todos = self.get_calendar_todos(limit=200)
        if todos and "error" in todos[0]:
            return todos[0]

        q = title_substring.lower()
        matches = [t for t in todos if q in (t.get("title") or "").lower()]
        return {
            "found": len(matches) > 0,
            "match_count": len(matches),
            "matches": matches[:5],
        }

    def check_draft_exists(self, subject_substring: str) -> dict:
        """Check if a draft email with matching subject exists."""
        messages = self.get_messages(folder="Drafts", limit=200)
        if messages and "error" in messages[0]:
            return messages[0]

        q = subject_substring.lower()
        matches = [m for m in messages if q in (m.get("subject") or "").lower()]
        return {
            "found": len(matches) > 0,
            "match_count": len(matches),
            "matches": [{
                "subject": m.get("subject"),
                "to": m.get("to"),
                "from": m.get("from"),
                "body_preview": m.get("body_preview", "")[:200],
            } for m in matches[:5]],
        }

    def check_draft_content(self, subject_substring: str, body_text: str) -> dict:
        """Check if a draft with the given subject contains specific body text."""
        messages = self.get_messages(folder="Drafts", limit=200)
        if messages and "error" in messages[0]:
            return messages[0]

        q_subj = subject_substring.lower()
        q_body = body_text.lower()

        for m in messages:
            if q_subj in (m.get("subject") or "").lower():
                if q_body in (m.get("body_preview") or "").lower():
                    return {
                        "found": True,
                        "subject": m.get("subject"),
                        "body_preview": m.get("body_preview", "")[:300],
                    }

        return {"found": False, "subject_query": subject_substring, "body_query": body_text}

    def check_message_exists(self, folder: str, subject_substring: str) -> dict:
        """Check if a message with matching subject exists in a specific folder."""
        messages = self.get_messages(folder=folder, limit=200)
        if messages and "error" in messages[0]:
            return messages[0]

        q = subject_substring.lower()
        matches = [m for m in messages if q in (m.get("subject") or "").lower()]
        return {
            "found": len(matches) > 0,
            "folder": folder,
            "match_count": len(matches),
            "matches": [{
                "subject": m.get("subject"),
                "to": m.get("to"),
                "from": m.get("from"),
            } for m in matches[:5]],
        }

    def check_message_to(self, folder: str, subject_substring: str, expected_to: str) -> dict:
        """Check if a message has the expected recipient."""
        messages = self.get_messages(folder=folder, limit=200)
        if messages and "error" in messages[0]:
            return messages[0]

        q_subj = subject_substring.lower()
        q_to = expected_to.lower()

        for m in messages:
            if q_subj in (m.get("subject") or "").lower():
                if q_to in (m.get("to") or "").lower():
                    return {
                        "match": True,
                        "subject": m.get("subject"),
                        "to": m.get("to"),
                    }

        return {"match": False, "subject_query": subject_substring, "expected_to": expected_to}

    def check_preference_value(self, key: str, expected: str) -> dict:
        """Check if a Thunderbird preference has the expected value.

        Comparison is string-based (expected is compared as string).
        """
        result = self.get_preferences(key)
        if "error" in result:
            return result

        actual = result.get("value")
        actual_str = str(actual)
        match = actual_str.lower() == str(expected).lower()
        return {
            "match": match,
            "key": key,
            "expected": expected,
            "actual": actual,
        }

    def check_account_configured(self, email_substring: str) -> dict:
        """Check if a mail account with the given email is configured."""
        accounts = self.get_accounts()
        if accounts and "error" in accounts[0]:
            return accounts[0]

        q = email_substring.lower()
        for acct in accounts:
            if q in (acct.get("email") or "").lower():
                return {"found": True, "account": acct}

        return {"found": False, "email_query": email_substring}

    # ------------------------------------------------------------------
    # Gap endpoints: filters, folders, virtual folders, feeds,
    # subscriptions, OpenPGP/S/MIME, attachment policy helpers
    # ------------------------------------------------------------------

    def _iter_filter_files(self) -> list[Path]:
        """Return all msgFilterRules.dat files under Mail/ and ImapMail/."""
        profile = self._require_profile()
        found: list[Path] = []
        for base in [profile / "Mail", profile / "ImapMail"]:
            if not base.exists():
                continue
            for p in base.rglob("msgFilterRules.dat"):
                found.append(p)
        return found

    def _parse_filter_file(self, path: Path) -> list[dict]:
        """Parse a msgFilterRules.dat file into a list of filter dicts."""
        try:
            text = path.read_text(errors="replace")
        except Exception as e:
            return [{"error": f"read failed: {e}"}]
        filters: list[dict] = []
        current: dict | None = None
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            m = re.match(r'(\w+)="(.*)"$', line)
            if not m:
                continue
            k, v = m.group(1), m.group(2)
            if k == "name":
                if current is not None:
                    filters.append(current)
                current = {"name": v, "enabled": None, "type": None,
                           "action": [], "actionValue": [],
                           "condition": None, "source_file": str(path)}
            elif current is not None:
                if k == "enabled":
                    current["enabled"] = (v == "yes")
                elif k == "type":
                    current["type"] = v
                elif k == "action":
                    current["action"].append(v)
                elif k == "actionValue":
                    current["actionValue"].append(v)
                elif k == "condition":
                    current["condition"] = v
        if current is not None:
            filters.append(current)
        return filters

    def list_filters(self) -> list[dict]:
        out: list[dict] = []
        for f in self._iter_filter_files():
            out.extend(self._parse_filter_file(f))
        return out

    def check_filter_exists(self, name_substring: str) -> dict:
        name_substring = name_substring.lower()
        filters = self.list_filters()
        matches = [f for f in filters
                   if isinstance(f, dict) and name_substring in (f.get("name") or "").lower()]
        return {
            "found": len(matches) > 0,
            "match_count": len(matches),
            "matches": matches[:5],
        }

    def check_filter_action(self, name_substring: str, action: str,
                            action_value_substring: str | None = None) -> dict:
        """Check a filter has a given action (e.g. 'Move to folder', 'AddTag')
        and optionally that its action value contains a substring."""
        res = self.check_filter_exists(name_substring)
        if not res.get("found"):
            return {"match": False, "reason": "filter not found", "query": name_substring}
        for f in res["matches"]:
            actions = [a.lower() for a in f.get("action") or []]
            action_values = f.get("actionValue") or []
            if action.lower() in actions:
                if action_value_substring is None:
                    return {"match": True, "filter": f["name"], "action": action}
                for av in action_values:
                    if action_value_substring.lower() in (av or "").lower():
                        return {"match": True, "filter": f["name"],
                                "action": action, "action_value": av}
        return {"match": False, "reason": "action not present",
                "query": name_substring, "action": action}

    def check_filter_condition(self, name_substring: str, condition_substring: str) -> dict:
        res = self.check_filter_exists(name_substring)
        if not res.get("found"):
            return {"match": False, "reason": "filter not found"}
        q = condition_substring.lower()
        for f in res["matches"]:
            if q in (f.get("condition") or "").lower():
                return {"match": True, "filter": f["name"], "condition": f["condition"]}
        return {"match": False, "reason": "condition substring not present"}

    # Folder existence -------------------------------------------------

    def check_folder_exists(self, folder_rel_path: str, account: str = "Local Folders") -> dict:
        """Check a local folder exists in Mail/Local Folders/<sub/path>.
        folder_rel_path uses forward slashes (e.g. 'Projects/Atlas/Active').
        Subfolders on disk use the `.sbd` suffix convention.
        """
        profile = self._require_profile()
        if account == "Local Folders":
            base = profile / "Mail" / "Local Folders"
        else:
            # allow arbitrary account dir via explicit path-like 'ImapMail/<server>'
            base = profile / account
        parts = [p for p in folder_rel_path.split("/") if p]
        if not parts:
            return {"exists": False, "reason": "empty path"}
        # Walk: each non-leaf must have a .sbd directory.
        cur = base
        for i, name in enumerate(parts):
            if i < len(parts) - 1:
                sbd = cur / f"{name}.sbd"
                if not sbd.is_dir():
                    return {"exists": False, "missing_at": name, "looked_for": str(sbd)}
                cur = sbd
            else:
                mbox = cur / name
                msf = cur / f"{name}.msf"
                return {
                    "exists": mbox.exists() or msf.exists(),
                    "mbox_path": str(mbox),
                    "msf_path": str(msf),
                    "has_mbox": mbox.exists(),
                    "has_msf": msf.exists(),
                }
        return {"exists": False}

    # Virtual / saved search folders -----------------------------------

    def _parse_virtual_folders(self) -> list[dict]:
        profile = self._require_profile()
        results: list[dict] = []
        for base in [profile / "Mail", profile / "ImapMail"]:
            if not base.exists():
                continue
            for vf_file in base.rglob("virtualFolders.dat"):
                try:
                    text = vf_file.read_text(errors="replace")
                except Exception:
                    continue
                cur: dict | None = None
                for raw_line in text.splitlines():
                    line = raw_line.rstrip("\r")
                    if line.startswith("uri="):
                        if cur is not None:
                            results.append(cur)
                        cur = {"uri": line[4:], "source_file": str(vf_file)}
                    elif cur is not None and "=" in line:
                        k, _, v = line.partition("=")
                        cur[k.strip()] = v
                if cur is not None:
                    results.append(cur)
        return results

    def check_virtual_folder_exists(self, name_substring: str) -> dict:
        vfs = self._parse_virtual_folders()
        q = name_substring.lower()
        matches = [vf for vf in vfs if q in (vf.get("uri") or "").lower()]
        return {
            "found": len(matches) > 0,
            "match_count": len(matches),
            "matches": matches[:5],
        }

    def check_virtual_folder_terms(self, name_substring: str, terms_substring: str) -> dict:
        res = self.check_virtual_folder_exists(name_substring)
        if not res.get("found"):
            return {"match": False, "reason": "virtual folder not found"}
        q = terms_substring.lower()
        for vf in res["matches"]:
            if q in (vf.get("searchStr") or "").lower():
                return {"match": True, "uri": vf["uri"], "searchStr": vf.get("searchStr")}
        return {"match": False, "reason": "searchStr substring not present"}

    # Feeds (RSS) ------------------------------------------------------

    def _read_feeds_json(self) -> Any:
        profile = self._require_profile()
        for name in ("feeds.json", "feeds.rdf"):
            p = profile / "Mail" / "Feeds" / name
            if p.exists():
                try:
                    if p.suffix == ".json":
                        return json.loads(p.read_text())
                    return {"_raw_rdf": p.read_text(errors="replace")}
                except Exception as e:
                    return {"error": str(e)}
        # Also search across Feeds directories
        for cand in profile.rglob("feeds.json"):
            try:
                return json.loads(cand.read_text())
            except Exception:
                pass
        return None

    def check_feed_subscription(self, url_substring: str) -> dict:
        data = self._read_feeds_json()
        if data is None:
            return {"found": False, "reason": "no feeds.json"}
        if isinstance(data, dict) and "error" in data:
            return {"found": False, "error": data["error"]}
        q = url_substring.lower()
        hits = []
        # feeds.json is typically a list of subscription dicts
        items = data if isinstance(data, list) else data.get("feeds") or []
        for item in items:
            url = (item.get("url") or "") if isinstance(item, dict) else ""
            if q in url.lower():
                hits.append(item)
        return {"found": len(hits) > 0, "match_count": len(hits), "matches": hits[:5]}

    # Subscribed / offline folders -------------------------------------

    def check_subscribed_folder(self, server_key: str, folder_path: str) -> dict:
        """Parse <server_key>.rc or the account's .msf/folderCache to check
        that the given IMAP folder is in the subscribed list. server_key is
        like 'server1'. folder_path uses '/' (e.g. 'INBOX/Work')."""
        profile = self._require_profile()
        rc = profile / "ImapMail" / server_key / "Subscriptions.dat"
        if not rc.exists():
            # Thunderbird stores subscriptions per server dir; try glob
            for cand in (profile / "ImapMail").glob("*/Subscriptions.dat") if (profile / "ImapMail").exists() else []:
                rc = cand
                break
        if not rc.exists():
            return {"subscribed": False, "reason": "Subscriptions.dat not found",
                    "looked": str(rc)}
        try:
            text = rc.read_text(errors="replace")
        except Exception as e:
            return {"subscribed": False, "error": str(e)}
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        return {
            "subscribed": folder_path in lines,
            "folder": folder_path,
            "file": str(rc),
            "total_subscribed": len(lines),
        }

    # Attachment / directory helpers -----------------------------------

    def check_directory_exists(self, dir_path: str) -> dict:
        p = Path(dir_path)
        return {"exists": p.exists() and p.is_dir(), "path": dir_path}

    # OpenPGP / S-MIME indicators --------------------------------------

    def check_openpgp_configured(self, identity_key: str = "id1") -> dict:
        """Check pgp prefs for a given identity (e.g. id1)."""
        profile = self._require_profile()
        prefs = _parse_prefs_js(profile)
        key = f"mail.identity.{identity_key}.openpgp_key_id"
        sign = f"mail.identity.{identity_key}.sign_mail"
        policy = f"mail.identity.{identity_key}.encryptionpolicy"
        return {
            "configured": bool(prefs.get(key)),
            "openpgp_key_id": prefs.get(key),
            "sign_mail": prefs.get(sign),
            "encryptionpolicy": prefs.get(policy),
        }

    def check_smime_configured(self, identity_key: str = "id1") -> dict:
        profile = self._require_profile()
        prefs = _parse_prefs_js(profile)
        sign_cert = f"mail.identity.{identity_key}.signing_cert_name"
        enc_cert = f"mail.identity.{identity_key}.encryption_cert_name"
        sign = f"mail.identity.{identity_key}.sign_mail"
        policy = f"mail.identity.{identity_key}.encryptionpolicy"
        return {
            "configured": bool(prefs.get(sign_cert) or prefs.get(enc_cert)),
            "signing_cert_name": prefs.get(sign_cert),
            "encryption_cert_name": prefs.get(enc_cert),
            "sign_mail": prefs.get(sign),
            "encryptionpolicy": prefs.get(policy),
        }

    def check_mailing_list_exists(self, name_substring: str) -> dict:
        """Check if a mailing list with the given name exists."""
        lists = self.get_mailing_lists()
        if lists and isinstance(lists[0], dict) and "error" in lists[0]:
            return lists[0]

        q = name_substring.lower()
        matches = [ml for ml in lists if q in (ml.get("name") or "").lower()]
        return {
            "found": len(matches) > 0,
            "match_count": len(matches),
            "matches": matches[:5],
        }


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

COMMANDS = {
    # Contacts
    "contacts": ("List all contacts", lambda v, args: v.get_contacts(query=args[0] if args else None)),
    "contact-count": ("Count contacts", lambda v, args: v.get_contact_count()),
    "mailing-lists": ("List mailing lists", lambda v, args: v.get_mailing_lists()),

    # Calendar
    "calendar-events": ("List calendar events", lambda v, args: v.get_calendar_events(limit=int(args[0]) if args else 50)),
    "calendar-todos": ("List calendar todos", lambda v, args: v.get_calendar_todos(limit=int(args[0]) if args else 50)),
    "calendar-event-extras": ("Get event extra properties", lambda v, args: v.get_calendar_event_extras(args[0])),
    "calendar-count": ("Count events and todos", lambda v, args: v.get_calendar_count()),

    # Email / mbox
    "mail-folders": ("List mail folders", lambda v, args: v.get_mail_folders()),
    "messages": ("Read messages from folder", lambda v, args: v.get_messages(folder=args[0] if args else "Drafts", limit=int(args[1]) if len(args) > 1 else 50)),
    "message-count": ("Count messages in folder", lambda v, args: v.get_message_count(folder=args[0] if args else "Drafts")),
    "search-messages": ("Search messages", lambda v, args: v.search_messages(args[0], folder=args[1] if len(args) > 1 else None)),
    "message-index": ("Query global message index", lambda v, args: v.get_message_index(query=args[0] if args else None)),

    # Preferences
    "prefs": ("Read preferences", lambda v, args: v.get_preferences(key=args[0] if args else None)),
    "prefs-matching": ("Get prefs matching pattern", lambda v, args: v.get_preferences_matching(args[0])),

    # Accounts
    "accounts": ("List mail accounts", lambda v, args: v.get_accounts()),

    # File I/O
    "file-exists": ("Check if file exists", lambda v, args: v.check_file_exists(args[0])),
    "profile-info": ("Get profile directory info", lambda v, args: v.get_profile_info()),

    # Composite checks
    "check-contact-exists": ("Check contact exists", lambda v, args: v.check_contact_exists(args[0])),
    "check-contact-field": ("Check contact field value", lambda v, args: v.check_contact_field(args[0], args[1], args[2])),
    "check-event-exists": ("Check calendar event exists", lambda v, args: v.check_calendar_event_exists(args[0])),
    "check-todo-exists": ("Check calendar todo exists", lambda v, args: v.check_calendar_todo_exists(args[0])),
    "check-draft-exists": ("Check draft exists", lambda v, args: v.check_draft_exists(args[0])),
    "check-draft-content": ("Check draft has body text", lambda v, args: v.check_draft_content(args[0], args[1])),
    "check-message-exists": ("Check message in folder", lambda v, args: v.check_message_exists(args[0], args[1])),
    "check-message-to": ("Check message recipient", lambda v, args: v.check_message_to(args[0], args[1], args[2])),
    "check-pref-value": ("Check preference value", lambda v, args: v.check_preference_value(args[0], args[1])),
    "check-account": ("Check account configured", lambda v, args: v.check_account_configured(args[0])),
    "check-mailing-list": ("Check mailing list exists", lambda v, args: v.check_mailing_list_exists(args[0])),

    # Gap endpoints
    "filters": ("List message filters", lambda v, args: v.list_filters()),
    "check-filter-exists": ("Check message filter exists", lambda v, args: v.check_filter_exists(args[0])),
    "check-filter-action": ("Check filter has action (and optional value substring)",
                              lambda v, args: v.check_filter_action(args[0], args[1], args[2] if len(args) > 2 else None)),
    "check-filter-condition": ("Check filter condition substring",
                                 lambda v, args: v.check_filter_condition(args[0], args[1])),
    "check-folder-exists": ("Check local folder path exists (Local Folders)",
                              lambda v, args: v.check_folder_exists(args[0], account=args[1] if len(args) > 1 else "Local Folders")),
    "check-virtual-folder-exists": ("Check saved-search (virtual) folder exists",
                                       lambda v, args: v.check_virtual_folder_exists(args[0])),
    "check-virtual-folder-terms": ("Check virtual folder has search terms substring",
                                      lambda v, args: v.check_virtual_folder_terms(args[0], args[1])),
    "check-feed-subscription": ("Check an RSS feed subscription URL exists",
                                  lambda v, args: v.check_feed_subscription(args[0])),
    "check-subscribed-folder": ("Check IMAP folder subscription",
                                  lambda v, args: v.check_subscribed_folder(args[0], args[1])),
    "check-directory-exists": ("Check directory exists on disk",
                                 lambda v, args: v.check_directory_exists(args[0])),
    "check-openpgp-configured": ("Check OpenPGP configured for identity",
                                    lambda v, args: v.check_openpgp_configured(args[0] if args else "id1")),
    "check-smime-configured": ("Check S/MIME configured for identity",
                                  lambda v, args: v.check_smime_configured(args[0] if args else "id1")),
}


def _print_usage():
    print("Thunderbird Verifier — query Thunderbird state for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> [args...]\n")
    print("Commands:")
    max_name = max(len(name) for name in COMMANDS)
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:<{max_name + 2}} {desc}")
    print(f"\nProfile auto-detected from ~/.thunderbird/")
    print(f"Override with THUNDERBIRD_PROFILE_DIR env var.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}. Run with --help for usage."}))
        sys.exit(1)

    v = ThunderbirdVerifier()
    _, handler = COMMANDS[cmd]

    try:
        result = handler(v, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except FileNotFoundError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))
