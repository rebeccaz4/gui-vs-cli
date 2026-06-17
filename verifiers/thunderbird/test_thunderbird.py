"""
Test Thunderbird verifier endpoints in a live E2B sandbox.

Covers:
  - Help/usage output
  - Error cases (no profile, bad args)
  - Profile detection
  - Contacts (SQLite abook.sqlite)
  - Calendar (SQLite local.sqlite)
  - Email/mbox (Drafts, Sent)
  - Preferences (prefs.js)
  - Accounts
  - Composite check-* endpoints (positive and negative)
  - JSON validity sweep
  - File I/O

Usage:
    python verifiers/thunderbird/test_thunderbird.py
"""

import json
import sys
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "thunderbird.py"
VERIFIER_REMOTE = "/home/user/verifiers/thunderbird.py"
V = f"python3 {VERIFIER_REMOTE}"

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
            msg += f"  — {detail}"
        print(msg)
        errors.append(f"{name}: {detail}")


def is_valid_json(stdout: str) -> bool:
    try:
        json.loads(stdout)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


def sbx_run(sandbox: Sandbox, cmd: str, timeout: int = 30) -> str:
    """Run a raw shell command in the sandbox, return stdout."""
    try:
        result = sandbox.commands.run(cmd, timeout=timeout)
        return result.stdout
    except CommandExitException as e:
        return e.stdout


# ---------------------------------------------------------------------------
# Fixture creation helpers
# ---------------------------------------------------------------------------

def create_contacts_fixture(sandbox: Sandbox, profile_dir: str):
    """Create abook.sqlite with test contacts and a mailing list."""
    abook_path = f"{profile_dir}/abook.sqlite"
    script = f'''import sqlite3
conn = sqlite3.connect("{abook_path}")
conn.execute("CREATE TABLE IF NOT EXISTS properties (card TEXT, name TEXT, value TEXT)")
conn.execute("CREATE TABLE IF NOT EXISTS lists (uid TEXT, name TEXT, nickName TEXT, description TEXT)")
data = [
    ("card-alice", "DisplayName", "Alice Johnson"),
    ("card-alice", "FirstName", "Alice"),
    ("card-alice", "LastName", "Johnson"),
    ("card-alice", "PrimaryEmail", "alice@example.com"),
    ("card-alice", "Company", "Acme Corp"),
    ("card-alice", "WorkPhone", "555-0101"),
    ("card-bob", "DisplayName", "Bob Smith"),
    ("card-bob", "FirstName", "Bob"),
    ("card-bob", "LastName", "Smith"),
    ("card-bob", "PrimaryEmail", "bob@example.com"),
    ("card-bob", "Company", "Widgets Inc"),
    ("card-bob", "JobTitle", "Engineer"),
    ("card-charlie", "DisplayName", "Charlie Brown"),
    ("card-charlie", "FirstName", "Charlie"),
    ("card-charlie", "LastName", "Brown"),
    ("card-charlie", "PrimaryEmail", "charlie@example.com"),
    ("card-charlie", "Notes", "VIP client"),
]
conn.executemany("INSERT INTO properties VALUES (?,?,?)", data)
conn.execute("INSERT INTO lists VALUES (?,?,?,?)", ("list-team", "Project Team", "team", "The project team list"))
conn.commit()
conn.close()
print("OK")
'''
    sandbox.files.write("/tmp/create_abook.py", script)
    out = sbx_run(sandbox, f"python3 /tmp/create_abook.py")
    print(f"  abook fixture: {out.strip()}")


def create_calendar_fixture(sandbox: Sandbox, profile_dir: str):
    """Create calendar-data/local.sqlite with test events and todos."""
    cal_dir = f"{profile_dir}/calendar-data"
    sbx_run(sandbox, f"mkdir -p {cal_dir}")
    cal_db = f"{cal_dir}/local.sqlite"

    script = f'''import sqlite3
conn = sqlite3.connect("{cal_db}")
conn.execute("""CREATE TABLE IF NOT EXISTS cal_events (
    cal_id TEXT, id TEXT, title TEXT,
    event_start TEXT, event_end TEXT, event_start_tz TEXT, event_end_tz TEXT,
    flags INTEGER, ical_status TEXT,
    recurrence_id TEXT, recurrence_id_tz TEXT,
    alarm_last_ack TEXT
)""")
conn.execute("""CREATE TABLE IF NOT EXISTS cal_todos (
    cal_id TEXT, id TEXT, title TEXT,
    todo_entry TEXT, todo_due TEXT, todo_completed TEXT, todo_complete INTEGER,
    ical_status TEXT, priority INTEGER
)""")
conn.execute("CREATE TABLE IF NOT EXISTS cal_properties (item_id TEXT, key TEXT, value TEXT)")

events = [
    ("cal1", "evt-meeting", "Team Meeting", "1712160000000000", "1712163600000000", "UTC", "UTC", 0, "CONFIRMED", None, None, None),
    ("cal1", "evt-lunch", "Lunch Break", "1712170800000000", "1712174400000000", "UTC", "UTC", 0, "CONFIRMED", None, None, None),
    ("cal1", "evt-deadline", "Project Deadline", "1712250000000000", "1712253600000000", "UTC", "UTC", 0, "TENTATIVE", None, None, None),
]
conn.executemany("INSERT INTO cal_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", events)

todos = [
    ("cal1", "todo-supplies", "Buy supplies", "1712160000000000", "1712250000000000", None, 0, "NEEDS-ACTION", 5),
    ("cal1", "todo-review", "Review PR", "1712160000000000", "1712200000000000", None, 0, "IN-PROCESS", 1),
]
conn.executemany("INSERT INTO cal_todos VALUES (?,?,?,?,?,?,?,?,?)", todos)

props = [
    ("evt-meeting", "LOCATION", "Conference Room A"),
    ("evt-meeting", "DESCRIPTION", "Weekly team sync to discuss progress"),
]
conn.executemany("INSERT INTO cal_properties VALUES (?,?,?)", props)

conn.commit()
conn.close()
print("OK")
'''
    sandbox.files.write("/tmp/create_calendar.py", script)
    out = sbx_run(sandbox, f"python3 /tmp/create_calendar.py")
    print(f"  calendar fixture: {out.strip()}")


def create_mbox_fixtures(sandbox: Sandbox, profile_dir: str):
    """Create mbox files for Drafts and Sent folders."""
    local_folders = f"{profile_dir}/Mail/Local Folders"
    sbx_run(sandbox, f"mkdir -p '{local_folders}'")

    # Drafts mbox with 2 messages
    drafts_mbox = """From - Thu Apr 03 12:00:00 2025
From: testuser@example.com
To: boss@company.com
Subject: Q4 Report
Date: Thu, 03 Apr 2025 12:00:00 +0000
Content-Type: text/plain; charset=UTF-8
Message-ID: <draft-001@example.com>
X-Mozilla-Status: 0000
X-Mozilla-Draft-Info: internal/draft; vcard=0; receipt=0; DSN=0; uuencode=0; attachmentreminder=0; deliveryformat=4

Here are the quarterly results for Q4. Revenue increased by 15% and we exceeded targets in all regions.

From - Thu Apr 03 13:00:00 2025
From: testuser@example.com
To: team@company.com
Subject: Party Invite
Date: Thu, 03 Apr 2025 13:00:00 +0000
Content-Type: text/plain; charset=UTF-8
Message-ID: <draft-002@example.com>
X-Mozilla-Status: 0000

You're invited to the celebration next Friday at 6 PM. Please RSVP by Wednesday.

"""
    sandbox.files.write(f"{local_folders}/Drafts", drafts_mbox)

    # Sent mbox with 1 message
    sent_mbox = """From - Wed Apr 02 10:00:00 2025
From: testuser@example.com
To: client@example.com
Subject: Invoice #1234
Date: Wed, 02 Apr 2025 10:00:00 +0000
Content-Type: text/plain; charset=UTF-8
Message-ID: <sent-001@example.com>
X-Mozilla-Status: 0001

Please find attached the invoice for March services. Payment is due within 30 days.

"""
    sandbox.files.write(f"{local_folders}/Sent", sent_mbox)

    # Empty Inbox mbox (just the file, no messages)
    sandbox.files.write(f"{local_folders}/Inbox", "")


def create_prefs_fixture(sandbox: Sandbox, profile_dir: str):
    """Create prefs.js with test preferences (identity id1 with OpenPGP,
    identity id2 with S/MIME, identity id3 with neither)."""
    prefs_content = """// Mozilla User Preferences
user_pref("mail.identity.id1.fullName", "Test User");
user_pref("mail.identity.id1.useremail", "testuser@example.com");
user_pref("mail.identity.id1.smtpServer", "smtp1");
user_pref("mail.identity.id1.compose_html", true);
user_pref("mail.identity.id1.reply_to", "");
user_pref("mail.identity.id1.organization", "Test Org");
user_pref("mail.identity.id1.openpgp_key_id", "0xABCDEF0123456789");
user_pref("mail.identity.id1.sign_mail", true);
user_pref("mail.identity.id1.encryptionpolicy", 1);
user_pref("mail.identity.id2.fullName", "SMIME User");
user_pref("mail.identity.id2.useremail", "smime@example.com");
user_pref("mail.identity.id2.signing_cert_name", "CN=SMIME User,O=Example");
user_pref("mail.identity.id2.encryption_cert_name", "CN=SMIME User,O=Example");
user_pref("mail.identity.id2.sign_mail", true);
user_pref("mail.identity.id2.encryptionpolicy", 2);
user_pref("mail.identity.id3.fullName", "Plain User");
user_pref("mail.identity.id3.useremail", "plain@example.com");
user_pref("mail.server.server1.hostname", "mail.example.com");
user_pref("mail.server.server1.type", "imap");
user_pref("mail.server.server1.port", 993);
user_pref("font.name.serif.x-western", "Times New Roman");
user_pref("mail.compose.font_size", 14);
user_pref("mail.startup.enabledMailCheckOnce", true);
user_pref("mailnews.default_sort_type", 18);
user_pref("mail.biff.play_sound", false);
user_pref("mail.rights.version", 1);
"""
    sandbox.files.write(f"{profile_dir}/prefs.js", prefs_content)


def create_filter_fixture(sandbox: Sandbox, profile_dir: str):
    """Create msgFilterRules.dat with move/tag/forward/mark-read actions."""
    local_folders = f"{profile_dir}/Mail/Local Folders"
    sbx_run(sandbox, f"mkdir -p '{local_folders}'")
    filter_rules = '''version="9"
logging="no"
name="Move newsletter to Archive"
enabled="yes"
type="17"
action="Move to folder"
actionValue="mailbox://nobody@Local%20Folders/Archive"
condition="AND (subject,contains,Newsletter)"
name="Tag VIP clients"
enabled="yes"
type="17"
action="AddTag"
actionValue="$label1"
condition="AND (from,contains,vip@)"
name="Forward support tickets"
enabled="yes"
type="17"
action="Forward"
actionValue="support-lead@example.com"
condition="AND (to,contains,support@example.com)"
name="Mark as read from boss"
enabled="no"
type="17"
action="Mark read"
condition="AND (from,contains,boss@company.com)"
'''
    sandbox.files.write(f"{local_folders}/msgFilterRules.dat", filter_rules)


def create_virtual_folders_fixture(sandbox: Sandbox, profile_dir: str):
    """Create virtualFolders.dat with saved-search folders."""
    local_folders = f"{profile_dir}/Mail/Local Folders"
    sbx_run(sandbox, f"mkdir -p '{local_folders}'")
    vf_content = '''version=1
uri=mailbox://nobody@Local%20Folders/UnreadImportant
scope=mailbox://nobody@Local%20Folders/Inbox
terms=AND (subject,contains,Important) AND (status,is,Unread)
searchStr=AND (subject,contains,Important) AND (status,is,Unread)
searchOnline=false
uri=mailbox://nobody@Local%20Folders/Flagged
scope=mailbox://nobody@Local%20Folders/Inbox|mailbox://nobody@Local%20Folders/Sent
terms=AND (flagged,is,true)
searchStr=AND (flagged,is,true)
searchOnline=false
'''
    sandbox.files.write(f"{local_folders}/virtualFolders.dat", vf_content)


def create_feeds_fixture(sandbox: Sandbox, profile_dir: str):
    """Create feeds.json with multiple RSS subscriptions."""
    feeds_dir = f"{profile_dir}/Mail/Feeds"
    sbx_run(sandbox, f"mkdir -p '{feeds_dir}'")
    feeds_payload = [
        {"url": "https://example.com/rss.xml", "title": "Example News",
         "quickMode": False, "options": {}},
        {"url": "https://blog.python.org/feeds/posts/default",
         "title": "Python Blog", "quickMode": True, "options": {}},
        {"url": "https://news.ycombinator.com/rss", "title": "Hacker News",
         "quickMode": False, "options": {}},
    ]
    sandbox.files.write(f"{feeds_dir}/feeds.json", json.dumps(feeds_payload))


def create_subscriptions_fixture(sandbox: Sandbox, profile_dir: str):
    """Create Subscriptions.dat with IMAP folder list."""
    server_dir = f"{profile_dir}/ImapMail/mail.example.com"
    sbx_run(sandbox, f"mkdir -p '{server_dir}'")
    subscriptions = "INBOX\nINBOX/Work\nINBOX/Personal\nINBOX/Archive\nSent\nDrafts\n"
    sandbox.files.write(f"{server_dir}/Subscriptions.dat", subscriptions)


def create_folder_tree_fixture(sandbox: Sandbox, profile_dir: str):
    """Create a nested Local Folders tree: Projects/Atlas/Active, plus
    Archive at top level. Creates a physical directory for
    check-directory-exists positive case."""
    local_folders = f"{profile_dir}/Mail/Local Folders"
    sbx_run(sandbox, f"mkdir -p '{local_folders}/Projects.sbd/Atlas.sbd'")
    sandbox.files.write(f"{local_folders}/Projects.sbd/Atlas.sbd/Active", "")
    sandbox.files.write(f"{local_folders}/Projects.sbd/Atlas.sbd/Active.msf", "")
    sandbox.files.write(f"{local_folders}/Archive", "")
    sbx_run(sandbox, "mkdir -p /home/user/Attachments")


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_help(sandbox: Sandbox):
    """--help should print usage and exit 0."""
    print("\n=== Group 1: Help ===")
    result = run_raw(sandbox, "--help")
    check("help exits 0", result.exit_code == 0, f"got exit_code={result.exit_code}")
    check("help mentions Commands", "Commands:" in result.stdout, result.stdout[:100])


def test_errors_no_profile(sandbox: Sandbox):
    """Endpoints should return error JSON when no profile exists."""
    print("\n=== Group 2: Errors (no profile) ===")

    # Temporarily set env to a nonexistent profile
    prefix = "THUNDERBIRD_PROFILE_DIR=/tmp/nonexistent_profile"

    for cmd_name, cmd in [
        ("contacts", "contacts"),
        ("calendar-events", "calendar-events"),
        ("calendar-todos", "calendar-todos"),
        ("prefs", "prefs"),
        ("accounts", "accounts"),
        ("messages", "messages"),
        ("mail-folders", "mail-folders"),
        ("profile-info", "profile-info"),
    ]:
        r = run_raw(sandbox, cmd)
        # Override: run with nonexistent profile env var
        try:
            result = sandbox.commands.run(
                f"{prefix} {V} {cmd}", timeout=30
            )
            stdout = result.stdout
            exit_code = result.exit_code
        except CommandExitException as e:
            stdout = e.stdout
            exit_code = e.exit_code

        # Should either exit 1 with error JSON, or return error in JSON
        valid = is_valid_json(stdout)
        if valid:
            data = json.loads(stdout)
            if isinstance(data, list) and data:
                data = data[0]
            has_error = isinstance(data, dict) and "error" in data
        else:
            has_error = False

        check(f"{cmd_name} no-profile: error or valid JSON",
              (exit_code != 0 and valid) or has_error or valid,
              f"exit={exit_code} json_valid={valid} stdout={stdout[:80]}")


def test_errors_bad_args(sandbox: Sandbox):
    """Missing/invalid arguments should return error JSON."""
    print("\n=== Group 3: Errors (bad args) ===")

    # Missing required arg
    for cmd in ["check-contact-exists", "check-event-exists", "check-todo-exists", "check-draft-exists"]:
        result = run_raw(sandbox, cmd)
        check(f"{cmd} missing arg exits 1", result.exit_code == 1,
              f"got exit_code={result.exit_code}")
        check(f"{cmd} missing arg valid JSON", is_valid_json(result.stdout),
              result.stdout[:100])

    # check-contact-field needs 3 args, give 1
    result = run_raw(sandbox, "check-contact-field test")
    check("check-contact-field partial args exits 1", result.exit_code == 1,
          f"got exit_code={result.exit_code}")
    check("check-contact-field partial args valid JSON", is_valid_json(result.stdout),
          result.stdout[:100])

    # Unknown command
    result = run_raw(sandbox, "nonexistent-command")
    check("unknown cmd exits 1", result.exit_code == 1)
    check("unknown cmd valid JSON", is_valid_json(result.stdout), result.stdout[:100])


def test_profile_detection(sandbox: Sandbox, profile_dir: str):
    """After profile exists, profile-info should work."""
    print("\n=== Group 4: Profile Detection ===")

    data = run(sandbox, "profile-info")
    check("profile-info returns dict", isinstance(data, dict), str(type(data)))
    check("profile-info has path", "profile_path" in data, str(data)[:100])
    check("profile-info exists=true", data.get("exists") is True, str(data)[:100])
    check("profile-info selects populated install default profile",
          data.get("profile_path") == profile_dir,
          str(data))


def test_contacts(sandbox: Sandbox):
    """Test contact endpoints."""
    print("\n=== Group 5: Contacts ===")

    # All contacts
    data = run(sandbox, "contacts")
    check("contacts returns list", isinstance(data, list), str(type(data)))
    check("contacts has 3 entries", len(data) == 3, f"got {len(data)}")
    if data and "error" not in data[0]:
        check("contact has display_name", "display_name" in data[0], str(data[0].keys()))
        check("contact has primary_email", "primary_email" in data[0], str(data[0].keys()))

    # Query contacts
    data = run(sandbox, "contacts alice")
    check("contacts query returns list", isinstance(data, list))
    check("contacts query finds Alice", len(data) == 1 and "Alice" in str(data),
          f"got {len(data)} results: {str(data)[:100]}")

    # Query with no matches
    data = run(sandbox, "contacts zzzznonexistent")
    check("contacts query no match empty", isinstance(data, list) and len(data) == 0,
          f"got {len(data) if isinstance(data, list) else data}")

    # Contact count
    data = run(sandbox, "contact-count")
    check("contact-count returns dict", isinstance(data, dict))
    check("contact-count is 3", data.get("count") == 3, f"got {data.get('count')}")

    # Mailing lists
    data = run(sandbox, "mailing-lists")
    check("mailing-lists returns list", isinstance(data, list))
    if data and "error" not in data[0]:
        check("mailing-lists has 1 entry", len(data) == 1, f"got {len(data)}")


def test_calendar(sandbox: Sandbox):
    """Test calendar endpoints."""
    print("\n=== Group 6: Calendar ===")

    # Events
    data = run(sandbox, "calendar-events")
    check("calendar-events returns list", isinstance(data, list), str(type(data)))
    check("calendar-events has 3 entries", len(data) == 3, f"got {len(data)}")
    if data and "error" not in data[0]:
        check("event has title", "title" in data[0], str(data[0].keys()))
        check("event has event_start", "event_start" in data[0], str(data[0].keys()))

    # Events with limit
    data = run(sandbox, "calendar-events 2")
    check("calendar-events limit=2", len(data) == 2, f"got {len(data)}")

    # Todos
    data = run(sandbox, "calendar-todos")
    check("calendar-todos returns list", isinstance(data, list))
    check("calendar-todos has 2 entries", len(data) == 2, f"got {len(data)}")
    if data and "error" not in data[0]:
        check("todo has title", "title" in data[0], str(data[0].keys()))

    # Event extras
    data = run(sandbox, "calendar-event-extras evt-meeting")
    check("event-extras returns dict", isinstance(data, dict))
    check("event-extras has properties", "properties" in data, str(data.keys()))
    if "properties" in data:
        check("event-extras has LOCATION", data["properties"].get("LOCATION") == "Conference Room A",
              str(data["properties"]))

    # Calendar count
    data = run(sandbox, "calendar-count")
    check("calendar-count returns dict", isinstance(data, dict))
    check("calendar-count events=3", data.get("events") == 3, f"got {data.get('events')}")
    check("calendar-count todos=2", data.get("todos") == 2, f"got {data.get('todos')}")


def test_email(sandbox: Sandbox):
    """Test email/mbox endpoints."""
    print("\n=== Group 7: Email/mbox ===")

    # Mail folders
    data = run(sandbox, "mail-folders")
    check("mail-folders returns list", isinstance(data, list), str(type(data)))
    check("mail-folders has entries", len(data) >= 3, f"got {len(data)}")
    folder_names = [f.get("name") for f in data if isinstance(f, dict)]
    check("mail-folders has Drafts", "Drafts" in folder_names, str(folder_names))
    check("mail-folders has Sent", "Sent" in folder_names, str(folder_names))

    # Messages from Drafts
    data = run(sandbox, "messages Drafts")
    check("messages Drafts returns list", isinstance(data, list))
    check("messages Drafts has 2 entries", len(data) == 2, f"got {len(data)}")
    if data and "error" not in data[0]:
        check("message has subject", "subject" in data[0], str(data[0].keys()))
        check("message has from", "from" in data[0], str(data[0].keys()))
        check("message has body_preview", "body_preview" in data[0], str(data[0].keys()))

    # Messages from Sent
    data = run(sandbox, "messages Sent")
    check("messages Sent has 1 entry", len(data) == 1, f"got {len(data)}")

    # Message count
    data = run(sandbox, "message-count Drafts")
    check("message-count Drafts", isinstance(data, dict) and data.get("count") == 2,
          str(data))

    # Nonexistent folder
    data = run(sandbox, "messages NonexistentFolder")
    check("messages nonexistent folder error",
          isinstance(data, list) and data and "error" in data[0],
          str(data)[:100])

    # Search messages
    data = run(sandbox, "search-messages invoice")
    check("search-messages returns list", isinstance(data, list))
    check("search-messages finds invoice", len(data) >= 1, f"got {len(data)}")

    # Search with no matches
    data = run(sandbox, "search-messages zzzznonexistent")
    check("search-messages no match empty", isinstance(data, list) and len(data) == 0,
          f"got {len(data) if isinstance(data, list) else data}")

    # Empty inbox
    data = run(sandbox, "messages Inbox")
    check("messages empty Inbox", isinstance(data, list) and len(data) == 0,
          f"got {len(data) if isinstance(data, list) else data}")


def test_preferences(sandbox: Sandbox):
    """Test preferences endpoints."""
    print("\n=== Group 8: Preferences ===")

    # Prefs overview (no key)
    data = run(sandbox, "prefs")
    check("prefs returns dict", isinstance(data, dict))
    check("prefs has total_prefs", "total_prefs" in data, str(data.keys()))
    check("prefs has prefixes", "prefixes" in data, str(data.keys()))

    # Prefs with key
    data = run(sandbox, "prefs mail.identity.id1.fullName")
    check("prefs key returns value", data.get("value") == "Test User",
          f"got {data}")

    # Nonexistent key
    data = run(sandbox, "prefs nonexistent.key.here")
    check("prefs nonexistent key error", "error" in data, str(data)[:100])

    # Prefs matching
    data = run(sandbox, "prefs-matching font")
    check("prefs-matching returns dict", isinstance(data, dict))
    check("prefs-matching has matches", data.get("count", 0) >= 1,
          f"got count={data.get('count')}")
    if "matches" in data:
        check("prefs-matching has font key",
              "font.name.serif.x-western" in data["matches"],
              str(list(data["matches"].keys())[:5]))

    # Prefs matching with no matches
    data = run(sandbox, "prefs-matching zzzznonexistent")
    check("prefs-matching no match", data.get("count") == 0, str(data))


def test_accounts(sandbox: Sandbox):
    """Test accounts endpoint."""
    print("\n=== Group 9: Accounts ===")

    data = run(sandbox, "accounts")
    check("accounts returns list", isinstance(data, list), str(type(data)))
    check("accounts has entries", len(data) >= 1, f"got {len(data)}")
    if data and "error" not in data[0] and "info" not in data[0]:
        check("account has email", "email" in data[0], str(data[0].keys()))
        check("account email correct", "testuser@example.com" in str(data[0].get("email", "")),
              str(data[0]))


def test_checks_positive(sandbox: Sandbox):
    """Composite check-* endpoints — positive cases."""
    print("\n=== Group 10: Checks (positive) ===")

    # check-contact-exists
    data = run(sandbox, "check-contact-exists 'Alice Johnson'")
    check("check-contact-exists found=true", data.get("found") is True, str(data)[:100])

    # check-contact-field
    data = run(sandbox, "check-contact-field 'Alice Johnson' company 'Acme Corp'")
    check("check-contact-field match=true", data.get("match") is True, str(data)[:100])

    # check-event-exists
    data = run(sandbox, "check-event-exists 'Team Meeting'")
    check("check-event-exists found=true", data.get("found") is True, str(data)[:100])

    # check-todo-exists
    data = run(sandbox, "check-todo-exists 'Buy supplies'")
    check("check-todo-exists found=true", data.get("found") is True, str(data)[:100])

    # check-draft-exists
    data = run(sandbox, "check-draft-exists 'Q4 Report'")
    check("check-draft-exists found=true", data.get("found") is True, str(data)[:100])

    # check-draft-content
    data = run(sandbox, "check-draft-content 'Q4 Report' 'quarterly results'")
    check("check-draft-content found=true", data.get("found") is True, str(data)[:100])

    # check-message-exists
    data = run(sandbox, "check-message-exists Sent 'Invoice'")
    check("check-message-exists found=true", data.get("found") is True, str(data)[:100])

    # check-message-to
    data = run(sandbox, "check-message-to Drafts 'Q4 Report' 'boss@company.com'")
    check("check-message-to match=true", data.get("match") is True, str(data)[:100])

    # check-pref-value
    data = run(sandbox, "check-pref-value mail.identity.id1.fullName 'Test User'")
    check("check-pref-value match=true", data.get("match") is True, str(data)[:100])

    # check-account
    data = run(sandbox, "check-account testuser@example.com")
    check("check-account found=true", data.get("found") is True, str(data)[:100])

    # check-mailing-list
    data = run(sandbox, "check-mailing-list 'Project Team'")
    check("check-mailing-list found=true", data.get("found") is True, str(data)[:100])


def test_checks_negative(sandbox: Sandbox):
    """Composite check-* endpoints — negative cases."""
    print("\n=== Group 11: Checks (negative) ===")

    data = run(sandbox, "check-contact-exists 'Nonexistent Person ZZZZZ'")
    check("check-contact-exists found=false", data.get("found") is False, str(data)[:100])

    data = run(sandbox, "check-contact-field 'Alice Johnson' company 'Wrong Corp'")
    check("check-contact-field match=false", data.get("match") is False, str(data)[:100])

    data = run(sandbox, "check-event-exists 'Nonexistent Event ZZZZZ'")
    check("check-event-exists found=false", data.get("found") is False, str(data)[:100])

    data = run(sandbox, "check-todo-exists 'Nonexistent Todo ZZZZZ'")
    check("check-todo-exists found=false", data.get("found") is False, str(data)[:100])

    data = run(sandbox, "check-draft-exists 'Nonexistent Draft ZZZZZ'")
    check("check-draft-exists found=false", data.get("found") is False, str(data)[:100])

    data = run(sandbox, "check-draft-content 'Q4 Report' 'text absolutely not in the body ZZZZZ'")
    check("check-draft-content found=false", data.get("found") is False, str(data)[:100])

    data = run(sandbox, "check-message-exists Sent 'Nonexistent Subject ZZZZZ'")
    check("check-message-exists found=false", data.get("found") is False, str(data)[:100])

    data = run(sandbox, "check-message-to Drafts 'Q4 Report' 'wrong@email.com'")
    check("check-message-to match=false", data.get("match") is False, str(data)[:100])

    data = run(sandbox, "check-pref-value mail.identity.id1.fullName 'Wrong Name'")
    check("check-pref-value match=false", data.get("match") is False, str(data)[:100])

    data = run(sandbox, "check-account nobody@nowhere.com")
    check("check-account found=false", data.get("found") is False, str(data)[:100])

    data = run(sandbox, "check-mailing-list 'Nonexistent List ZZZZZ'")
    check("check-mailing-list found=false", data.get("found") is False, str(data)[:100])


def test_json_validity(sandbox: Sandbox):
    """Every CLI subcommand produces valid JSON output."""
    print("\n=== Group 12: JSON Validity Sweep ===")

    # No-arg commands
    no_arg_cmds = [
        "contacts", "contact-count", "mailing-lists",
        "calendar-events", "calendar-todos", "calendar-count",
        "mail-folders", "messages", "prefs", "accounts", "profile-info",
        "filters",
    ]

    for cmd in no_arg_cmds:
        result = run_raw(sandbox, cmd)
        valid = is_valid_json(result.stdout)
        check(f"{cmd} valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")

    # With-arg commands
    arg_cmds = [
        ("contacts", "alice"),
        ("calendar-events", "5"),
        ("calendar-event-extras", "evt-meeting"),
        ("messages", "Drafts"),
        ("messages", "Sent 5"),
        ("message-count", "Drafts"),
        ("search-messages", "test"),
        ("message-index",),
        ("prefs", "mail.identity.id1.fullName"),
        ("prefs-matching", "font"),
        ("file-exists", "/tmp/nonexistent_file_test"),
        ("check-contact-exists", "test"),
        ("check-contact-field", "test company test"),
        ("check-event-exists", "test"),
        ("check-todo-exists", "test"),
        ("check-draft-exists", "test"),
        ("check-draft-content", "test body"),
        ("check-message-exists", "Drafts test"),
        ("check-message-to", "Drafts test test@test.com"),
        ("check-pref-value", "test.key test"),
        ("check-account", "test"),
        ("check-mailing-list", "test"),
        ("check-filter-exists", "test"),
        ("check-filter-action", "test AddTag"),
        ("check-filter-condition", "test subject"),
        ("check-folder-exists", "test"),
        ("check-virtual-folder-exists", "test"),
        ("check-virtual-folder-terms", "test flagged"),
        ("check-feed-subscription", "test"),
        ("check-subscribed-folder", "mail.example.com INBOX"),
        ("check-directory-exists", "/tmp"),
        ("check-openpgp-configured", "id1"),
        ("check-smime-configured", "id2"),
    ]

    for parts in arg_cmds:
        cmd_str = " ".join(parts)
        result = run_raw(sandbox, cmd_str)
        valid = is_valid_json(result.stdout)
        check(f"{cmd_str} valid JSON", valid,
              f"exit={result.exit_code} stdout={result.stdout[:80]}" if not valid else "")


def test_filters(sandbox: Sandbox):
    """Test message-filter endpoints (positive + negative)."""
    print("\n=== Group 14: Filters ===")

    data = run(sandbox, "filters")
    check("filters returns list", isinstance(data, list), str(type(data)))
    check("filters has 4 entries", len(data) == 4, f"got {len(data)}")
    if data and isinstance(data[0], dict) and "error" not in data[0]:
        check("filter has name", "name" in data[0], str(data[0].keys()))
        check("filter has action", "action" in data[0], str(data[0].keys()))
        check("filter has condition", "condition" in data[0], str(data[0].keys()))

    data = run(sandbox, "check-filter-exists newsletter")
    check("check-filter-exists found=true", data.get("found") is True, str(data)[:150])

    data = run(sandbox, "check-filter-exists 'Nonexistent Filter ZZZZZ'")
    check("check-filter-exists found=false", data.get("found") is False, str(data)[:150])

    data = run(sandbox, "check-filter-action newsletter 'Move to folder' Archive")
    check("check-filter-action move match=true", data.get("match") is True, str(data)[:200])

    data = run(sandbox, "check-filter-action VIP AddTag")
    check("check-filter-action tag match=true", data.get("match") is True, str(data)[:200])

    data = run(sandbox, "check-filter-action support Forward support-lead@example.com")
    check("check-filter-action forward match=true", data.get("match") is True, str(data)[:200])

    data = run(sandbox, "check-filter-action newsletter 'Delete'")
    check("check-filter-action wrong action match=false",
          data.get("match") is False, str(data)[:200])

    data = run(sandbox, "check-filter-action newsletter 'Move to folder' WrongTargetFolder")
    check("check-filter-action wrong value match=false",
          data.get("match") is False, str(data)[:200])

    data = run(sandbox, "check-filter-action NonexistentFilter AddTag")
    check("check-filter-action no filter match=false",
          data.get("match") is False, str(data)[:200])

    data = run(sandbox, "check-filter-condition newsletter 'subject,contains,Newsletter'")
    check("check-filter-condition match=true", data.get("match") is True, str(data)[:200])

    data = run(sandbox, "check-filter-condition newsletter 'subject,contains,TotallyUnrelated'")
    check("check-filter-condition wrong match=false",
          data.get("match") is False, str(data)[:200])

    data = run(sandbox, "check-filter-condition NonexistentFilter anything")
    check("check-filter-condition no filter match=false",
          data.get("match") is False, str(data)[:200])


def test_folder_existence(sandbox: Sandbox):
    """Test check-folder-exists (nested local folder path parsing)."""
    print("\n=== Group 15: Folder Existence ===")

    data = run(sandbox, "check-folder-exists 'Projects/Atlas/Active'")
    check("check-folder-exists nested=true", data.get("exists") is True, str(data)[:200])

    data = run(sandbox, "check-folder-exists Archive")
    check("check-folder-exists top-level=true", data.get("exists") is True, str(data)[:200])

    data = run(sandbox, "check-folder-exists 'Missing/Nested/Leaf'")
    check("check-folder-exists missing intermediate=false",
          data.get("exists") is False, str(data)[:200])

    data = run(sandbox, "check-folder-exists 'Projects/Atlas/Nonexistent'")
    check("check-folder-exists missing leaf=false",
          data.get("exists") is False, str(data)[:200])


def test_virtual_folders(sandbox: Sandbox):
    """Test check-virtual-folder-exists / check-virtual-folder-terms."""
    print("\n=== Group 16: Virtual Folders ===")

    data = run(sandbox, "check-virtual-folder-exists UnreadImportant")
    check("check-virtual-folder-exists found=true",
          data.get("found") is True, str(data)[:200])

    data = run(sandbox, "check-virtual-folder-exists Flagged")
    check("check-virtual-folder-exists Flagged found=true",
          data.get("found") is True, str(data)[:200])

    data = run(sandbox, "check-virtual-folder-exists NonexistentVirtual")
    check("check-virtual-folder-exists found=false",
          data.get("found") is False, str(data)[:200])

    data = run(sandbox, "check-virtual-folder-terms UnreadImportant 'subject,contains,Important'")
    check("check-virtual-folder-terms match=true",
          data.get("match") is True, str(data)[:250])

    data = run(sandbox, "check-virtual-folder-terms UnreadImportant 'subject,contains,Unrelated'")
    check("check-virtual-folder-terms wrong match=false",
          data.get("match") is False, str(data)[:250])

    data = run(sandbox, "check-virtual-folder-terms NonexistentVirtual anything")
    check("check-virtual-folder-terms no vf match=false",
          data.get("match") is False, str(data)[:200])


def test_feeds(sandbox: Sandbox):
    """Test check-feed-subscription."""
    print("\n=== Group 17: Feeds ===")

    data = run(sandbox, "check-feed-subscription example.com/rss.xml")
    check("check-feed-subscription example found=true",
          data.get("found") is True, str(data)[:250])

    data = run(sandbox, "check-feed-subscription ycombinator")
    check("check-feed-subscription ycombinator found=true",
          data.get("found") is True, str(data)[:250])

    data = run(sandbox, "check-feed-subscription nonexistent-feed-zzzz.com")
    check("check-feed-subscription found=false",
          data.get("found") is False, str(data)[:250])


def test_subscribed_folders(sandbox: Sandbox):
    """Test check-subscribed-folder."""
    print("\n=== Group 18: Subscribed IMAP Folders ===")

    data = run(sandbox, "check-subscribed-folder mail.example.com INBOX/Work")
    check("check-subscribed-folder INBOX/Work subscribed=true",
          data.get("subscribed") is True, str(data)[:200])

    data = run(sandbox, "check-subscribed-folder mail.example.com INBOX")
    check("check-subscribed-folder INBOX subscribed=true",
          data.get("subscribed") is True, str(data)[:200])

    data = run(sandbox, "check-subscribed-folder mail.example.com INBOX/Nonexistent")
    check("check-subscribed-folder missing subscribed=false",
          data.get("subscribed") is False, str(data)[:200])

    data = run(sandbox, "check-subscribed-folder no.such.server INBOX/TotallyMissingZZZ")
    check("check-subscribed-folder bad server subscribed=false",
          data.get("subscribed") is False, str(data)[:200])


def test_directory_exists(sandbox: Sandbox):
    """Test check-directory-exists."""
    print("\n=== Group 19: Directory Exists ===")

    data = run(sandbox, "check-directory-exists /home/user/Attachments")
    check("check-directory-exists positive", data.get("exists") is True, str(data)[:200])

    data = run(sandbox, "check-directory-exists /home/user/NonexistentDirZZZZ")
    check("check-directory-exists nonexistent", data.get("exists") is False, str(data)[:200])

    data = run(sandbox, "check-directory-exists /home/user/test_export.csv")
    check("check-directory-exists file-not-dir",
          data.get("exists") is False, str(data)[:200])


def test_openpgp_smime(sandbox: Sandbox):
    """Test check-openpgp-configured and check-smime-configured."""
    print("\n=== Group 20: OpenPGP / S/MIME ===")

    data = run(sandbox, "check-openpgp-configured id1")
    check("check-openpgp id1 configured=true",
          data.get("configured") is True, str(data)[:250])
    check("check-openpgp id1 key_id present",
          data.get("openpgp_key_id") == "0xABCDEF0123456789", str(data)[:250])

    data = run(sandbox, "check-openpgp-configured id3")
    check("check-openpgp id3 configured=false",
          data.get("configured") is False, str(data)[:250])

    data = run(sandbox, "check-openpgp-configured id2")
    check("check-openpgp id2 configured=false",
          data.get("configured") is False, str(data)[:250])

    data = run(sandbox, "check-smime-configured id2")
    check("check-smime id2 configured=true",
          data.get("configured") is True, str(data)[:250])
    check("check-smime id2 signing cert present",
          "SMIME User" in (data.get("signing_cert_name") or ""), str(data)[:250])

    data = run(sandbox, "check-smime-configured id1")
    check("check-smime id1 configured=false",
          data.get("configured") is False, str(data)[:250])

    data = run(sandbox, "check-smime-configured id3")
    check("check-smime id3 configured=false",
          data.get("configured") is False, str(data)[:250])


def test_file_io(sandbox: Sandbox):
    """Test file-exists endpoint."""
    print("\n=== Group 13: File I/O ===")

    # Create test file
    sandbox.files.write("/home/user/test_export.csv", "name,email\nAlice,alice@example.com\n")

    # File exists
    data = run(sandbox, "file-exists /home/user/test_export.csv")
    check("file-exists existing file", data.get("exists") is True, str(data)[:100])
    check("file-exists has size", data.get("size_bytes", 0) > 0, str(data)[:100])

    # File does not exist
    data = run(sandbox, "file-exists /home/user/nonexistent_file_zzzzz.csv")
    check("file-exists nonexistent", data.get("exists") is False, str(data)[:100])

    # Directory check
    data = run(sandbox, "file-exists /home/user")
    check("file-exists directory", data.get("exists") is True and data.get("is_dir") is True,
          str(data)[:100])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global passed, failed

    print("=" * 60)
    print("Thunderbird Verifier Test Suite")
    print("=" * 60)

    print("\nCreating sandbox from desktop-all-apps...")
    sandbox = Sandbox.create(template="desktop-all-apps", timeout=600)

    try:
        # Upload verifier
        print(f"Uploading {VERIFIER_LOCAL} -> {VERIFIER_REMOTE}")
        sandbox.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sandbox.files.write(VERIFIER_REMOTE, f.read())

        # --- Tests before Thunderbird profile exists ---
        test_help(sandbox)
        test_errors_bad_args(sandbox)

        # --- Create a Thunderbird profile manually ---
        # (We don't need to launch TB — just create the profile structure)
        print("\nCreating Thunderbird profile structure...")

        # Find or create profile dir
        profile_dir = "/home/user/.thunderbird/test.default-release"
        sandbox.commands.run("mkdir -p /home/user/.thunderbird/empty.default")
        sandbox.commands.run(f"mkdir -p {profile_dir}")

        # Mirror real Thunderbird layouts where an install-linked profile may
        # differ from the [ProfileX] section marked Default=1.
        profiles_ini = """[Profile0]
Name=default
IsRelative=1
Path=empty.default
Default=1

[InstallFDC34C9F024745EB]
Default=test.default-release
Locked=1

[Profile1]
Name=default-release
IsRelative=1
Path=test.default-release
"""
        sandbox.files.write("/home/user/.thunderbird/profiles.ini", profiles_ini)

        # --- Create all fixtures ---
        print("Creating test fixtures...")
        create_contacts_fixture(sandbox, profile_dir)
        create_calendar_fixture(sandbox, profile_dir)
        create_mbox_fixtures(sandbox, profile_dir)
        create_prefs_fixture(sandbox, profile_dir)
        create_filter_fixture(sandbox, profile_dir)
        create_virtual_folders_fixture(sandbox, profile_dir)
        create_feeds_fixture(sandbox, profile_dir)
        create_subscriptions_fixture(sandbox, profile_dir)
        create_folder_tree_fixture(sandbox, profile_dir)

        # --- Tests with profile and fixtures ---
        test_errors_no_profile(sandbox)
        test_profile_detection(sandbox, profile_dir)
        test_contacts(sandbox)
        test_calendar(sandbox)
        test_email(sandbox)
        test_preferences(sandbox)
        test_accounts(sandbox)
        test_checks_positive(sandbox)
        test_checks_negative(sandbox)
        test_file_io(sandbox)
        test_filters(sandbox)
        test_folder_existence(sandbox)
        test_virtual_folders(sandbox)
        test_feeds(sandbox)
        test_subscribed_folders(sandbox)
        test_directory_exists(sandbox)
        test_openpgp_smime(sandbox)
        test_json_validity(sandbox)

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
