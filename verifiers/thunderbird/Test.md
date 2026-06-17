# Thunderbird Verifier — Test Plan

## Module Overview

The Thunderbird verifier inspects state via:
1. **SQLite databases** — contacts (abook.sqlite), calendar (calendar-data/local.sqlite), message index (global-messages-db.sqlite)
2. **mbox files** — email content parsing (Drafts, Sent, Inbox, etc.)
3. **prefs.js** — user preference key-value parsing
4. **File system** — profile directory, file existence checks

**Prerequisites:** Thunderbird must have been launched at least once to create a profile. No special launch flags needed — all verification is offline/file-based.

---

## Test Groups

### Group 1: Help/Usage
- **What:** `--help` prints usage and exits 0
- **Edge cases:** None
- **Expected assertions:** 2

### Group 2: Error Handling — No Profile
- **What:** All endpoints should return error JSON when no Thunderbird profile exists (before launching Thunderbird)
- **Endpoints:** contacts, calendar-events, calendar-todos, prefs, accounts, messages, mail-folders, profile-info
- **Edge cases:** Profile directory doesn't exist at all
- **Expected assertions:** 8

### Group 3: Error Handling — Bad Arguments
- **What:** Missing/invalid arguments return error JSON, not crashes
- **Endpoints:** check-contact-exists (no arg), check-event-exists (no arg), check-draft-content (1 arg instead of 2), check-contact-field (1 arg instead of 3), unknown-command
- **Edge cases:** Unknown subcommand, wrong argument count
- **Expected assertions:** 8

### Group 4: Profile Detection
- **What:** After launching Thunderbird, profile-info should find the profile and list contents
- **Expected assertions:** 3

### Group 5: Contacts — Create and Query
- **What:** Create contacts via direct SQLite insertion into abook.sqlite, then query via verifier endpoints
- **Endpoints:** contacts, contacts (with query), contact-count, mailing-lists
- **Edge cases:** Query with no matches, empty address book before insertion
- **Expected assertions:** 10

### Group 6: Calendar — Create and Query
- **What:** Create calendar events and todos via direct SQLite insertion into local.sqlite, then query
- **Endpoints:** calendar-events, calendar-todos, calendar-event-extras, calendar-count
- **Edge cases:** Empty calendar, nonexistent event_id for extras
- **Expected assertions:** 12

### Group 7: Email/mbox — Create and Query
- **What:** Create mbox files with test messages (Drafts, Sent), then query via verifier
- **Endpoints:** mail-folders, messages, message-count, search-messages
- **Edge cases:** Empty folder, nonexistent folder, search with no matches
- **Expected assertions:** 14

### Group 8: Preferences
- **What:** Write a test prefs.js with known values, then query
- **Endpoints:** prefs (no key), prefs (with key), prefs-matching
- **Edge cases:** Nonexistent key, pattern with no matches
- **Expected assertions:** 8

### Group 9: Accounts
- **What:** Write account-related prefs to prefs.js, then query accounts endpoint
- **Endpoints:** accounts
- **Expected assertions:** 4

### Group 10: Check-* Positive Cases
- **What:** All check-* endpoints return true for data that exists
- **Endpoints:** check-contact-exists, check-contact-field, check-event-exists, check-todo-exists, check-draft-exists, check-draft-content, check-message-exists, check-message-to, check-pref-value, check-account, check-mailing-list
- **Expected assertions:** 11

### Group 11: Check-* Negative Cases
- **What:** All check-* endpoints return false for data that doesn't exist
- **Endpoints:** Same as Group 10
- **Edge cases:** Close-but-not-exact matches, nonexistent folders, wrong field values
- **Expected assertions:** 11

### Group 12: JSON Validity Sweep
- **What:** Every CLI subcommand produces valid JSON output (no tracebacks)
- **Expected assertions:** ~30 (one per subcommand variant)

### Group 13: File I/O
- **What:** file-exists for existing and nonexistent files
- **Endpoints:** file-exists
- **Expected assertions:** 4

### Group 14: Filters (msgFilterRules.dat)
- **What:** List filters and verify filter existence / action / condition substring matching.
- **Endpoints:** filters, check-filter-exists, check-filter-action, check-filter-condition
- **Edge cases:** filter not found, wrong action, wrong action-value substring, wrong condition substring
- **Expected assertions:** ~16

### Group 15: Folder Existence (Local Folders tree)
- **What:** Verify check-folder-exists walks `Foo.sbd/Bar.sbd/Leaf` correctly.
- **Endpoints:** check-folder-exists
- **Edge cases:** missing intermediate .sbd, missing leaf, top-level folder
- **Expected assertions:** 4

### Group 16: Virtual Folders (virtualFolders.dat)
- **What:** Saved-search folder existence + searchStr substring matching.
- **Endpoints:** check-virtual-folder-exists, check-virtual-folder-terms
- **Edge cases:** virtual folder not found, terms substring absent
- **Expected assertions:** 6

### Group 17: Feeds (feeds.json)
- **What:** RSS subscription URL substring matching.
- **Endpoints:** check-feed-subscription
- **Edge cases:** URL not present
- **Expected assertions:** 3

### Group 18: Subscribed IMAP Folders (Subscriptions.dat)
- **What:** Verify IMAP folder is listed in Subscriptions.dat for a server.
- **Endpoints:** check-subscribed-folder
- **Edge cases:** folder missing, server_key unknown (falls back to glob)
- **Expected assertions:** 4

### Group 19: Directory Exists (attachments/save-dir)
- **What:** check-directory-exists for a dir, missing path, and a path that is a file.
- **Endpoints:** check-directory-exists
- **Expected assertions:** 3

### Group 20: OpenPGP / S/MIME (prefs.js identity blocks)
- **What:** Confirm per-identity PGP key_id and S/MIME cert prefs.
- **Endpoints:** check-openpgp-configured, check-smime-configured
- **Edge cases:** identity with neither (id3), identity with the other scheme only (id1 vs id2)
- **Expected assertions:** 8

---

## Test Fixtures

### Fixture 1: abook.sqlite (contacts)
- **Path:** `<profile>/abook.sqlite`
- **Contents:** SQLite DB with `properties` table containing 3 contacts:
  - Contact 1: "Alice Johnson", alice@example.com, Company: "Acme Corp", Phone: "555-0101"
  - Contact 2: "Bob Smith", bob@example.com, Company: "Widgets Inc", Title: "Engineer"
  - Contact 3: "Charlie Brown", charlie@example.com, Notes: "VIP client"
- **Also:** `lists` table with 1 mailing list: "Project Team"
- **Used by:** Groups 5, 10, 11

### Fixture 2: calendar-data/local.sqlite (calendar)
- **Path:** `<profile>/calendar-data/local.sqlite`
- **Contents:** SQLite DB with:
  - `cal_events` table: 3 events ("Team Meeting", "Lunch Break", "Project Deadline")
  - `cal_todos` table: 2 todos ("Buy supplies", "Review PR")
  - `cal_properties` table: location + description for "Team Meeting"
- **Used by:** Groups 6, 10, 11

### Fixture 3: Drafts mbox
- **Path:** `<profile>/Mail/Local Folders/Drafts`
- **Contents:** mbox file with 2 draft messages:
  - Draft 1: Subject "Q4 Report", To: boss@company.com, Body: "Here are the quarterly results..."
  - Draft 2: Subject "Party Invite", To: team@company.com, Body: "You're invited to the celebration..."
- **Used by:** Groups 7, 10, 11

### Fixture 4: Sent mbox
- **Path:** `<profile>/Mail/Local Folders/Sent`
- **Contents:** mbox file with 1 sent message:
  - Sent 1: Subject "Invoice #1234", To: client@example.com, Body: "Please find attached..."
- **Used by:** Groups 7, 10, 11

### Fixture 5: prefs.js
- **Path:** `<profile>/prefs.js`
- **Contents:** Thunderbird preferences including:
  - `mail.identity.id1.fullName` = "Test User"
  - `mail.identity.id1.useremail` = "testuser@example.com"
  - `mail.server.server1.hostname` = "mail.example.com"
  - `mail.server.server1.type` = "imap"
  - `font.name.serif.x-western` = "Times New Roman"
  - `mail.compose.font_size` = 14
  - `mail.startup.enabledMailCheckOnce` = true
  - `mailnews.default_sort_type` = 18
- **Used by:** Groups 8, 9, 10, 11

### Fixture 6: Test file for file-exists
- **Path:** `/home/user/test_export.csv`
- **Contents:** Simple CSV: "name,email\nAlice,alice@example.com"
- **Used by:** Group 13

### Fixture 7: msgFilterRules.dat
- **Path:** `<profile>/Mail/Local Folders/msgFilterRules.dat`
- **Contents:** 4 filters with distinct actions:
  - "Move newsletter to Archive" — action `Move to folder`, actionValue targets Archive
  - "Tag VIP clients" — action `AddTag`, actionValue `$label1`
  - "Forward support tickets" — action `Forward`, actionValue `support-lead@example.com`
  - "Mark as read from boss" — action `Mark read` (disabled)
- **Used by:** Group 14

### Fixture 8: virtualFolders.dat
- **Path:** `<profile>/Mail/Local Folders/virtualFolders.dat`
- **Contents:** 2 saved-search folders:
  - `UnreadImportant` — searchStr with `subject,contains,Important` + `status,is,Unread`
  - `Flagged` — searchStr with `flagged,is,true`
- **Used by:** Group 16

### Fixture 9: feeds.json
- **Path:** `<profile>/Mail/Feeds/feeds.json`
- **Contents:** JSON list with 3 RSS subscriptions (Example News, Python Blog, Hacker News)
- **Used by:** Group 17

### Fixture 10: Subscriptions.dat
- **Path:** `<profile>/ImapMail/mail.example.com/Subscriptions.dat`
- **Contents:** 6 subscribed folders (`INBOX`, `INBOX/Work`, `INBOX/Personal`, `INBOX/Archive`, `Sent`, `Drafts`)
- **Used by:** Group 18

### Fixture 11: Nested Local Folders tree
- **Path:** `<profile>/Mail/Local Folders/Projects.sbd/Atlas.sbd/Active` (+ `.msf`), plus top-level `Archive`
- **Used by:** Group 15

### Fixture 12: Attachments directory
- **Path:** `/home/user/Attachments` (empty dir)
- **Used by:** Group 19

### Fixture 13: prefs.js identity blocks (PGP + S/MIME)
- **Path:** `<profile>/prefs.js` (extends Fixture 5)
- **Contents:**
  - `mail.identity.id1.openpgp_key_id` = "0xABCDEF0123456789" (OpenPGP only)
  - `mail.identity.id2.signing_cert_name` / `encryption_cert_name` (S/MIME only)
  - `mail.identity.id3.*` — plain identity with neither
- **Used by:** Group 20

---

## Edge Cases & Error Handling Matrix

| Scenario | Endpoint(s) | Expected behavior |
|---|---|---|
| No Thunderbird profile | All endpoints | `{"error": "..."}`, no crash |
| Missing required argument | check-* endpoints | exit 1 + valid error JSON |
| Unknown subcommand | any | exit 1 + valid error JSON |
| Nonexistent mail folder | messages, message-count | `{"error": "Mail folder '...' not found"}` |
| Nonexistent pref key | prefs | `{"error": "Preference '...' not found"}` |
| Empty address book | contacts, contact-count | empty list / `{"count": 0}` |
| Empty calendar | calendar-events, calendar-todos, calendar-count | empty list / `{"events": 0, "todos": 0}` |
| Empty mbox file | messages, message-count | empty list / `{"count": 0}` |
| Nonexistent file path | file-exists | `{"exists": false}` |
| Search with no matches | contacts (query), search-messages | empty list |
| Wrong argument count for check-contact-field | check-contact-field | exit 1 + error JSON |

---

## Positive / Negative Case Pairs

| Endpoint | Positive case | Negative case |
|---|---|---|
| check-contact-exists | "Alice Johnson" (fixture contact) | "Nonexistent Person" |
| check-contact-field | "Alice Johnson" company "Acme Corp" | "Alice Johnson" company "Wrong Corp" |
| check-event-exists | "Team Meeting" (fixture event) | "Nonexistent Event" |
| check-todo-exists | "Buy supplies" (fixture todo) | "Nonexistent Todo" |
| check-draft-exists | "Q4 Report" (fixture draft) | "Nonexistent Draft" |
| check-draft-content | "Q4 Report" + "quarterly results" | "Q4 Report" + "text not in body" |
| check-message-exists | Sent + "Invoice" (fixture) | Sent + "Nonexistent Subject" |
| check-message-to | Drafts + "Q4 Report" + "boss@company.com" | Drafts + "Q4 Report" + "wrong@email.com" |
| check-pref-value | mail.identity.id1.fullName = "Test User" | mail.identity.id1.fullName = "Wrong Name" |
| check-account | "testuser@example.com" | "nobody@nowhere.com" |
| check-mailing-list | "Project Team" | "Nonexistent List" |
| check-filter-exists | "newsletter" | "Nonexistent Filter ZZZZZ" |
| check-filter-action | "newsletter" + "Move to folder" + "Archive" | "newsletter" + "Delete" (wrong action) or wrong actionValue substring |
| check-filter-condition | "newsletter" + "subject,contains,Newsletter" | "newsletter" + "subject,contains,TotallyUnrelated" |
| check-folder-exists | "Projects/Atlas/Active" (nested .sbd tree) | "Missing/Nested/Leaf" (intermediate .sbd missing) |
| check-virtual-folder-exists | "UnreadImportant" | "NonexistentVirtual" |
| check-virtual-folder-terms | "UnreadImportant" + "subject,contains,Important" | "UnreadImportant" + "subject,contains,Unrelated" |
| check-feed-subscription | "example.com/rss.xml" | "nonexistent-feed-zzzz.com" |
| check-subscribed-folder | "mail.example.com" + "INBOX/Work" | same server + "INBOX/Nonexistent" |
| check-directory-exists | "/home/user/Attachments" | "/home/user/test_export.csv" (file, not dir) |
| check-openpgp-configured | "id1" (has openpgp_key_id) | "id2" (S/MIME only) and "id3" (neither) |
| check-smime-configured | "id2" (has signing/encryption cert) | "id1" (PGP only) and "id3" (neither) |

---

## JSON Validity Sweep

All CLI subcommands tested for valid JSON output:

**No-arg commands:**
- contacts, contact-count, mailing-lists
- calendar-events, calendar-todos, calendar-count
- mail-folders, messages, prefs, accounts, profile-info

**With-arg commands:**
- contacts "alice"
- calendar-events 5
- calendar-event-extras "test-id"
- messages Drafts
- messages Sent 5
- message-count Drafts
- search-messages "test"
- message-index
- prefs mail.identity.id1.fullName
- prefs-matching font
- file-exists /tmp/nonexistent
- check-contact-exists "test"
- check-contact-field "test" "company" "test"
- check-event-exists "test"
- check-todo-exists "test"
- check-draft-exists "test"
- check-draft-content "test" "test"
- check-message-exists Drafts "test"
- check-message-to Drafts "test" "test@test.com"
- check-pref-value "test.key" "test"
- check-account "test"
- check-mailing-list "test"

---

## Summary

| Metric | Count |
|---|---|
| Test groups | 20 |
| Total assertions | ~195 |
| Test fixtures (files generated) | 13 |
| `check-*` endpoints with pos+neg pairs | 22 |
| Error scenarios covered | 11 |
