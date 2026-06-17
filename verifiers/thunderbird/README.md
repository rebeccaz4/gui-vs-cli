# Thunderbird Verifier

Programmatic state inspection for Mozilla Thunderbird in E2B sandbox.
Used by a **check agent** to generate reward signals for RL/evaluation.

## Verification Channels

| Channel | What it reads | Pros | Cons |
|---------|--------------|------|------|
| **SQLite** (abook.sqlite) | Contacts, mailing lists | Fast, structured | May need flush |
| **SQLite** (calendar-data/local.sqlite) | Calendar events, todos | Fast, structured | — |
| **SQLite** (global-messages-db.sqlite) | Message search index | Fast full-text search | May lag behind mbox |
| **mbox files** | Email content (Drafts, Sent, Inbox, etc.) | Ground truth for messages | Slower for large mailboxes |
| **prefs.js** | User preferences | Complete settings access | Text parsing |
| **File system** | Profile structure, saved files | Always available | — |

## Prerequisites

Thunderbird must have been launched at least once to create a profile at `~/.thunderbird/<profile>.default*/`.

No special launch flags required — all verification is file/database based (no live IPC needed).

Override profile path: `THUNDERBIRD_PROFILE_DIR=/path/to/profile python3 thunderbird.py ...`

## Usage from Check Agent

```python
import json
from e2b_desktop import Sandbox

sandbox = Sandbox.create(template="desktop-all-apps")

# Check if a contact was added
result = sandbox.commands.run(
    "python3 /home/user/verifiers/thunderbird.py check-contact-exists 'John Doe'"
)
data = json.loads(result.stdout)
reward = 1.0 if data["found"] else 0.0

# Check if a calendar event was created
result = sandbox.commands.run(
    "python3 /home/user/verifiers/thunderbird.py check-event-exists 'Team Meeting'"
)
data = json.loads(result.stdout)
reward = 1.0 if data["found"] else 0.0

# Check if a draft was composed
result = sandbox.commands.run(
    "python3 /home/user/verifiers/thunderbird.py check-draft-exists 'Project Update'"
)
data = json.loads(result.stdout)
reward = 1.0 if data["found"] else 0.0
```

## Endpoint Reference

### Contacts

#### `contacts [query]`
List contacts. Optional query filters by name/email substring.
```
python3 thunderbird.py contacts
python3 thunderbird.py contacts "john"
```
Returns: `[{"uid": "...", "display_name": "John Doe", "primary_email": "john@example.com", ...}]`

#### `contact-count`
Count total contacts in address book.
```
python3 thunderbird.py contact-count
```
Returns: `{"count": 42}`

#### `mailing-lists`
List mailing lists from address book.
```
python3 thunderbird.py mailing-lists
```
Returns: `[{"uid": "...", "name": "Team", "nickName": "...", "description": "..."}]`

### Calendar

#### `calendar-events [limit]`
List calendar events, sorted by start time (newest first).
```
python3 thunderbird.py calendar-events
python3 thunderbird.py calendar-events 10
```
Returns: `[{"cal_id": "...", "title": "Meeting", "event_start": "...", "event_end": "...", ...}]`

#### `calendar-todos [limit]`
List calendar tasks/todos.
```
python3 thunderbird.py calendar-todos
```
Returns: `[{"title": "Buy groceries", "todo_due": "...", "ical_status": "...", ...}]`

#### `calendar-event-extras <event_id>`
Get extra properties for an event (attendees, location, description, etc.).
```
python3 thunderbird.py calendar-event-extras "abc-123-def"
```
Returns: `{"event_id": "...", "properties": {"LOCATION": "Room 101", "DESCRIPTION": "..."}}`

#### `calendar-count`
Count calendar events and todos.
```
python3 thunderbird.py calendar-count
```
Returns: `{"events": 5, "todos": 3}`

### Email / Messages

#### `mail-folders`
List all mail folders (mbox files) with size info.
```
python3 thunderbird.py mail-folders
```
Returns: `[{"name": "Drafts", "path": "...", "type": "local", "size_bytes": 1234}]`

#### `messages [folder] [limit]`
Read messages from a mail folder. Default: Drafts.
```
python3 thunderbird.py messages Drafts
python3 thunderbird.py messages Sent 10
python3 thunderbird.py messages Inbox 20
```
Returns: `[{"subject": "...", "from": "...", "to": "...", "body_preview": "...", ...}]`

#### `message-count [folder]`
Count messages in a folder.
```
python3 thunderbird.py message-count Drafts
```
Returns: `{"folder": "Drafts", "count": 3}`

#### `search-messages <query> [folder]`
Search messages by subject/sender/body. Searches all folders if none specified.
```
python3 thunderbird.py search-messages "meeting"
python3 thunderbird.py search-messages "invoice" Inbox
```
Returns: `[{"subject": "...", "folder": "Inbox", ...}]`

#### `message-index [query]`
Query the global message search index (faster than mbox for large mailboxes).
```
python3 thunderbird.py message-index
python3 thunderbird.py message-index "project update"
```
Returns: `[{"id": ..., "subject": "...", "sender": "...", ...}]`

### Preferences

#### `prefs [key]`
Read Thunderbird preferences. Without key: shows prefix summary. With key: returns value.
```
python3 thunderbird.py prefs
python3 thunderbird.py prefs mail.identity.id1.fullName
python3 thunderbird.py prefs font.name.serif.x-western
```
Returns (no key): `{"total_prefs": 250, "prefixes": {"mail": 120, "font": 15, ...}}`
Returns (with key): `{"key": "...", "value": "..."}`

#### `prefs-matching <pattern>`
Get all prefs matching a substring.
```
python3 thunderbird.py prefs-matching font
python3 thunderbird.py prefs-matching compose
```
Returns: `{"pattern": "font", "count": 15, "matches": {"font.name.serif.x-western": "serif", ...}}`

### Accounts

#### `accounts`
List configured mail accounts with identity details.
```
python3 thunderbird.py accounts
```
Returns: `[{"identity_id": "id1", "full_name": "John", "email": "john@example.com", ...}]`

### File I/O

#### `file-exists <path>`
Check if a file exists on disk.
```
python3 thunderbird.py file-exists /home/user/Documents/export.csv
```
Returns: `{"exists": true, "size_bytes": 1234, ...}` or `{"exists": false, ...}`

#### `profile-info`
Get Thunderbird profile directory path and contents listing.
```
python3 thunderbird.py profile-info
```
Returns: `{"profile_path": "...", "exists": true, "contents": ["abook.sqlite", "prefs.js", ...]}`

### Composite Checks (check-* endpoints)

All return a dict with a primary boolean key for direct reward signal mapping.

#### `check-contact-exists <name_or_email>`
```
python3 thunderbird.py check-contact-exists "John Doe"
python3 thunderbird.py check-contact-exists "john@example.com"
```
Returns: `{"found": true, "match_count": 1, "matches": [...]}`

#### `check-contact-field <name_or_email> <field> <expected>`
Fields: display_name, first_name, last_name, primary_email, second_email, work_phone, home_phone, company, job_title, notes, nickname
```
python3 thunderbird.py check-contact-field "John Doe" company "Acme Corp"
```
Returns: `{"match": true, "contact": {...}, ...}`

#### `check-event-exists <title_substring>`
```
python3 thunderbird.py check-event-exists "Team Meeting"
```
Returns: `{"found": true, "match_count": 1, "matches": [...]}`

#### `check-todo-exists <title_substring>`
```
python3 thunderbird.py check-todo-exists "Buy groceries"
```
Returns: `{"found": true, "match_count": 1, "matches": [...]}`

#### `check-draft-exists <subject_substring>`
```
python3 thunderbird.py check-draft-exists "Project Update"
```
Returns: `{"found": true, "match_count": 1, "matches": [...]}`

#### `check-draft-content <subject_substring> <body_text>`
```
python3 thunderbird.py check-draft-content "Project Update" "quarterly results"
```
Returns: `{"found": true, "subject": "...", "body_preview": "..."}`

#### `check-message-exists <folder> <subject_substring>`
```
python3 thunderbird.py check-message-exists Sent "Invoice"
python3 thunderbird.py check-message-exists Inbox "Welcome"
```
Returns: `{"found": true, "folder": "Sent", "match_count": 1, "matches": [...]}`

#### `check-message-to <folder> <subject_substring> <expected_to>`
```
python3 thunderbird.py check-message-to Drafts "Meeting" "boss@example.com"
```
Returns: `{"match": true, "subject": "...", "to": "..."}`

#### `check-pref-value <key> <expected>`
```
python3 thunderbird.py check-pref-value mail.identity.id1.fullName "John Doe"
python3 thunderbird.py check-pref-value font.name.serif.x-western "Times New Roman"
```
Returns: `{"match": true, "key": "...", "expected": "...", "actual": "..."}`

#### `check-account <email_substring>`
```
python3 thunderbird.py check-account "john@example.com"
```
Returns: `{"found": true, "account": {...}}`

#### `check-mailing-list <name_substring>`
```
python3 thunderbird.py check-mailing-list "Team"
```
Returns: `{"found": true, "match_count": 1, "matches": [...]}`

## Common Verification Patterns

### "Add a contact named John Doe with email john@example.com"
```python
data = run("check-contact-exists 'John Doe'")
reward = 1.0 if data["found"] else 0.0
# Bonus: verify email is correct
data2 = run("check-contact-field 'John Doe' primary_email john@example.com")
reward *= 1.0 if data2["match"] else 0.5
```

### "Create a calendar event titled 'Team Meeting' for next Monday"
```python
data = run("check-event-exists 'Team Meeting'")
reward = 1.0 if data["found"] else 0.0
```

### "Compose a draft email to boss@company.com about the Q4 report"
```python
data = run("check-draft-exists 'Q4'")
if data["found"]:
    data2 = run("check-message-to Drafts Q4 boss@company.com")
    reward = 1.0 if data2["match"] else 0.5
else:
    reward = 0.0
```

### "Change the default font to Arial"
```python
data = run("check-pref-value font.name.serif.x-western Arial")
reward = 1.0 if data["match"] else 0.0
```

### "Set your display name to 'Jane Smith'"
```python
data = run("check-pref-value mail.identity.id1.fullName 'Jane Smith'")
reward = 1.0 if data["match"] else 0.0
```

## Skipped Categories

| Category | Reason |
|----------|--------|
| UI layout / window state | No session file or API exposes sidebar/panel state |
| Navigation state | Not applicable — Thunderbird is not a browser |
| Extensions/plugins | MailExtension API requires a running extension bridge; file-based detection unreliable |
| Network/connection state | No programmatic access to IMAP/SMTP connection state |
| Keybindings | Stored in XUL overlays / no standard parseable file |
