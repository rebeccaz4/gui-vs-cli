# Verifiers

Programmatic state inspection modules for each app in the E2B sandbox.
Used by a **check agent** to generate reward signals for RL/evaluation.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Check Agent (outside sandbox)                           │
│                                                          │
│  result = sandbox.commands.run(                          │
│      "python3 /home/user/verifiers/chrome.py             │
│       check-tab-open github.com"                         │
│  )                                                       │
│  data = json.loads(result.stdout)                        │
│  reward = 1.0 if data["found"] else 0.0                 │
└────────────────────┬─────────────────────────────────────┘
                     │ sandbox.commands.run()
                     ▼
┌──────────────────────────────────────────────────────────┐
│  E2B Sandbox                                             │
│                                                          │
│  /home/user/verifiers/                                   │
│  ├── chrome.py        CDP + SQLite + file checks         │
│  ├── firefox.py       Marionette + SQLite                │
│  ├── libreoffice.py   UNO API + ODF XML parsing          │
│  ├── blender.py       bpy headless scripting             │
│  └── ...                                                 │
│                                                          │
│  Each verifier:                                          │
│  1. CLI: `python3 verifier.py <command> [args]`          │
│  2. Output: JSON to stdout                               │
│  3. Python: `from verifiers.chrome import ChromeVerifier` │
└──────────────────────────────────────────────────────────┘
```

## Usage from Check Agent

```python
import json
from e2b_desktop import Sandbox

sandbox = Sandbox.create(template="desktop-all-apps")

# --- Launch Chrome with CDP enabled ---
sandbox.commands.run(
    "google-chrome --remote-debugging-port=9222 --no-first-run &",
    timeout=5
)

# --- CLI style (simple, one-off checks) ---
result = sandbox.commands.run("python3 /home/user/verifiers/chrome.py tabs")
tabs = json.loads(result.stdout)

result = sandbox.commands.run(
    "python3 /home/user/verifiers/chrome.py check-url-visited github.com"
)
data = json.loads(result.stdout)
reward = 1.0 if data["visited"] else 0.0

# --- Composite checks ---
result = sandbox.commands.run(
    'python3 /home/user/verifiers/chrome.py check-page-contains "Sign in"'
)
data = json.loads(result.stdout)

result = sandbox.commands.run(
    "python3 /home/user/verifiers/chrome.py check-download report.pdf"
)
data = json.loads(result.stdout)
assert data["downloaded"] and data["file_exists"]
```

## Verifier Pattern

Each `<app>.py` follows the same structure:

1. **`<App>Verifier` class** — stateless, each method returns a dict/list
2. **Raw state methods** — `get_tabs()`, `get_history()`, `eval_js()` etc.
3. **`check_*` methods** — composite boolean checks for common RL tasks
4. **CLI `__main__`** — subcommand dispatcher, prints JSON to stdout
5. **Zero external deps** — uses only stdlib + what's already in the sandbox

## Command Categories

| Category | Purpose | Example |
|----------|---------|---------|
| Raw state | Read current app state | `tabs`, `history`, `bookmarks` |
| Eval/query | Run queries inside the app | `eval <js>`, `select <css>` |
| `check-*` | Boolean verification for RL | `check-tab-open`, `check-page-contains` |

All `check-*` commands return a dict with a primary boolean key
(`found`, `visited`, `exists`, `contains`, `downloaded`, `all_match`, etc.)
that maps directly to a reward signal.
