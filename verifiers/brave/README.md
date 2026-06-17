# Brave Browser Verifier

Programmatic state inspection for Brave browser in E2B sandbox.
Brave is Chromium-based — uses CDP and same profile structure as Chrome.

## Prerequisites

```bash
brave-browser --remote-debugging-port=9222 --force-renderer-accessibility --no-sandbox &
pip install websocket-client  # for CDP WebSocket
```

## Verification Channels

| Channel | When to use | Needs running Brave? |
|---------|-------------|---------------------|
| **CDP** | Live DOM, JS eval, tabs, cookies, screenshots | Yes |
| **SQLite (History)** | Browsing history, downloads | No |
| **JSON (Bookmarks)** | Bookmarks | No |
| **JSON (Preferences)** | Settings | No |

## Endpoint Reference

### CDP Live State

#### `tabs` — List open tabs
```bash
python3 /home/user/verifiers/brave.py tabs
```

#### `url [tab_index]` — Get current tab URL
#### `title [tab_index]` — Get tab title
#### `text [tab_index]` — Get page text (5KB)
#### `html [tab_index]` — Get page HTML (10KB)

#### `eval <expression> [tab_index]` — Evaluate JavaScript
```bash
python3 /home/user/verifiers/brave.py eval "document.title"
```

#### `select <css_selector> [tab_index]` — Query CSS selector
#### `input <css_selector> [tab_index]` — Get input value
#### `cookies [tab_index]` — Get page cookies via CDP
#### `screenshot [tab_index]` — Capture screenshot
#### `navigate <url> [tab_index]` — Navigate to URL

### SQLite Persistent State

#### `history [query]` — Search browsing history
#### `downloads` — List recent downloads
#### `bookmarks [query]` — Search bookmarks
#### `extensions` — List installed extensions
#### `prefs [key_path]` — Read preferences

### Composite Checks (Reward Signals)

| Command | Reward key | Example |
|---------|-----------|---------|
| `check-url-visited <url>` | `visited` | `check-url-visited github.com` |
| `check-tab-open <url>` | `found` | `check-tab-open google.com` |
| `check-page-contains <text> [tab]` | `contains` | `check-page-contains "Sign in"` |
| `check-element-exists <sel> [tab]` | `exists` | `check-element-exists "button.submit"` |
| `check-download <filename>` | `downloaded` | `check-download report.pdf` |
| `check-bookmark <url_or_name>` | `exists` | `check-bookmark GitHub` |
| `check-cookie <name> [domain]` | `exists` | `check-cookie session_id github.com` |

## Common Verification Patterns

```python
result = sandbox.commands.run("python3 /home/user/verifiers/brave.py check-tab-open github.com")
data = json.loads(result.stdout)
reward = 1.0 if data["found"] else 0.0
```
