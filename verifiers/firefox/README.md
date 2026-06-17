# Firefox ESR Verifier

Programmatic state inspection for Firefox ESR in E2B sandbox.
Used by a **check agent** to generate reward signals for RL/evaluation.

## Prerequisites

Launch Firefox with Marionette protocol enabled:

```bash
firefox-esr --marionette &
```

Install the Marionette driver for live inspection:

```bash
pip install marionette_driver
```

For SQLite-based verification (history, bookmarks, cookies), no running instance is needed — just an existing profile.

## Verification Channels

| Channel | When to use | Needs running Firefox? |
|---------|-------------|----------------------|
| **Marionette** | Live tabs, DOM, JS eval, navigation | Yes |
| **SQLite (places.sqlite)** | History, bookmarks | No |
| **SQLite (cookies.sqlite)** | Cookies | No |
| **SQLite (formhistory.sqlite)** | Form autofill data | No |
| **File (prefs.js)** | Preferences | No |

## Endpoint Reference

### Marionette Live State

#### `tabs`
List all open tabs with URL, title, and active status.
```bash
python3 /home/user/verifiers/firefox.py tabs
```
```json
[{"index": 0, "url": "https://github.com", "title": "GitHub", "active": true, "handle": "abc123"}]
```

#### `url [tab_index]`
Get the current URL of a tab.
```bash
python3 /home/user/verifiers/firefox.py url
python3 /home/user/verifiers/firefox.py url 1
```
```json
{"value": "https://github.com", "type": "string"}
```

#### `title [tab_index]`
Get the document title of a tab.
```bash
python3 /home/user/verifiers/firefox.py title
```
```json
{"value": "GitHub", "type": "string"}
```

#### `text [tab_index]`
Get the visible text content of the page body (truncated to 5KB).
```bash
python3 /home/user/verifiers/firefox.py text
```
```json
{"value": "Welcome to GitHub...", "type": "string"}
```

#### `html [tab_index]`
Get the outerHTML of the page (truncated to 10KB).
```bash
python3 /home/user/verifiers/firefox.py html
```

#### `eval <expression> [tab_index]`
Evaluate JavaScript in a tab and return the result.
```bash
python3 /home/user/verifiers/firefox.py eval "document.title"
python3 /home/user/verifiers/firefox.py eval "document.querySelectorAll('a').length" 0
```
```json
{"value": "GitHub", "type": "str"}
```

#### `select <css_selector> [tab_index]`
Query a CSS selector and return match count and first element info.
```bash
python3 /home/user/verifiers/firefox.py select "h1.title"
```
```json
{"count": 1, "first_text": "Welcome", "first_tag": "H1", "first_id": "", "first_class": "title"}
```

#### `input <css_selector> [tab_index]`
Get the value of an input/textarea/select element.
```bash
python3 /home/user/verifiers/firefox.py input "input[name='q']"
```
```json
{"value": "search term", "type": "str"}
```

#### `navigate <url> [tab_index]`
Navigate a tab to a URL.
```bash
python3 /home/user/verifiers/firefox.py navigate "https://example.com"
```
```json
{"url": "https://example.com/", "title": "Example Domain"}
```

#### `screenshot [tab_index]`
Capture a screenshot (base64 PNG, truncated in output).
```bash
python3 /home/user/verifiers/firefox.py screenshot
```

### SQLite Persistent State

#### `history [query]`
Search browsing history. Returns URLs, titles, visit counts.
```bash
python3 /home/user/verifiers/firefox.py history
python3 /home/user/verifiers/firefox.py history github
```
```json
[{"url": "https://github.com", "title": "GitHub", "visit_count": 3, "last_visit": "2025-01-15 10:30:00"}]
```

#### `bookmarks [query]`
Search bookmarks.
```bash
python3 /home/user/verifiers/firefox.py bookmarks
python3 /home/user/verifiers/firefox.py bookmarks github
```
```json
{"count": 1, "matches": [{"title": "GitHub", "url": "https://github.com", "folder": "toolbar"}]}
```

#### `downloads`
List recent downloads.
```bash
python3 /home/user/verifiers/firefox.py downloads
```

#### `cookies [domain]`
Read cookies, optionally filtered by domain.
```bash
python3 /home/user/verifiers/firefox.py cookies
python3 /home/user/verifiers/firefox.py cookies github.com
```
```json
{"count": 5, "cookies": [{"name": "session", "value": "abc", "host": ".github.com", ...}]}
```

#### `prefs [key]`
Read Firefox preferences.
```bash
python3 /home/user/verifiers/firefox.py prefs
python3 /home/user/verifiers/firefox.py prefs browser.download.dir
```

#### `form-history [field_name]`
Search form autofill history.
```bash
python3 /home/user/verifiers/firefox.py form-history searchbar-history
```

### Composite Checks (Reward Signals)

#### `check-url-visited <url_substring>`
```bash
python3 /home/user/verifiers/firefox.py check-url-visited github.com
```
```json
{"visited": true, "match_count": 3, "latest": {"url": "...", "title": "..."}}
```
**Reward key:** `visited`

#### `check-tab-open <url_substring>`
```bash
python3 /home/user/verifiers/firefox.py check-tab-open google.com
```
```json
{"found": true, "tab": {"url": "https://google.com", "title": "Google"}}
```
**Reward key:** `found`

#### `check-page-contains <text> [tab_index]`
```bash
python3 /home/user/verifiers/firefox.py check-page-contains "Sign in"
```
```json
{"contains": true, "snippet": "...Sign in to your account..."}
```
**Reward key:** `contains`

#### `check-element-exists <css_selector> [tab_index]`
```bash
python3 /home/user/verifiers/firefox.py check-element-exists "button.submit"
```
```json
{"exists": true, "count": 1, "first_text": "Submit"}
```
**Reward key:** `exists`

#### `check-bookmark <url_or_name>`
```bash
python3 /home/user/verifiers/firefox.py check-bookmark GitHub
```
```json
{"exists": true, "count": 1, "matches": [...]}
```
**Reward key:** `exists`

#### `check-cookie <name> [domain]`
```bash
python3 /home/user/verifiers/firefox.py check-cookie session_id github.com
```
```json
{"exists": true, "cookie": {...}}
```
**Reward key:** `exists`

#### `check-download <filename_substring>`
```bash
python3 /home/user/verifiers/firefox.py check-download report.pdf
```
```json
{"downloaded": true, "file_exists": true, "path": "/home/user/Downloads/report.pdf", "size": 12345}
```
**Reward key:** `downloaded`

#### `check-pref <key> [expected_value]`
```bash
python3 /home/user/verifiers/firefox.py check-pref browser.download.dir /home/user/Downloads
python3 /home/user/verifiers/firefox.py check-pref browser.newtabpage.enabled false
python3 /home/user/verifiers/firefox.py check-pref browser.startup.page 1
```
```json
{"set": true, "match": true, "expected": "/home/user/Downloads", "actual": "/home/user/Downloads", "source": "prefs.js"}
```
**Reward key:** `match` (if expected given) or `set`

Reads `prefs.js` first. If the preference is not user-modified (i.e. still at
Firefox's default), falls back to Marionette's `Services.prefs` to read the
live effective value — so checks succeed even when the agent legitimately left
a default-valued pref alone. Requires Firefox launched with `--marionette` for
the fallback path; prefs.js-only reads work without it.

The live fallback:
- Switches Marionette to chrome context (surfaces a clear error if chrome
  context is unavailable, rather than silently reading in content context
  where `ChromeUtils` is not defined).
- Uses the magic `Services` global if present, otherwise imports via
  `ChromeUtils.importESModule('resource://gre/modules/Services.sys.mjs')`
  (the legacy `.jsm` import was removed in modern ESR).
- If the pref has no user-set value, falls back to
  `Services.prefs.getDefaultBranch('')` so built-in defaults (e.g.
  `browser.startup.page=1`) still resolve.

The `source` field in the response indicates which channel provided the
value:
- `"prefs.js"` — user-modified pref read from disk
- `"marionette"` — live pref read from the user branch
- `"marionette-default"` — live pref read from the default branch (still at
  Firefox's built-in default)

The CLI-provided `expected_value` is coerced to the runtime type of the actual
value before comparison:
- Booleans: `"true"`/`"1"` → `True`, `"false"`/`"0"` → `False`
- Integers: `int(expected_value)` on the string
- Strings: compared as strings

## Common Verification Patterns

### Check if user navigated to a URL
```python
result = sandbox.commands.run("python3 /home/user/verifiers/firefox.py check-url-visited github.com")
data = json.loads(result.stdout)
reward = 1.0 if data["visited"] else 0.0
```

### Check if user has a specific tab open
```python
result = sandbox.commands.run("python3 /home/user/verifiers/firefox.py check-tab-open google.com")
data = json.loads(result.stdout)
reward = 1.0 if data["found"] else 0.0
```

### Check if page contains expected text
```python
result = sandbox.commands.run('python3 /home/user/verifiers/firefox.py check-page-contains "Welcome"')
data = json.loads(result.stdout)
reward = 1.0 if data["contains"] else 0.0
```

### Check if user bookmarked a page
```python
result = sandbox.commands.run("python3 /home/user/verifiers/firefox.py check-bookmark GitHub")
data = json.loads(result.stdout)
reward = 1.0 if data["exists"] else 0.0
```

### Check if user changed a preference
```python
result = sandbox.commands.run("python3 /home/user/verifiers/firefox.py check-pref browser.download.dir /tmp")
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```
