---
name: "cli-anything-browser"
description: "Browser automation CLI for Chrome using DOMShell plus CDP and profile-state commands."
---

# cli-anything-browser

Use `cli-anything-browser` to automate Chrome pages, inspect live browser state through CDP, and create verifier-readable Chrome profile artifacts.

## Prerequisites

- Python 3.10+ for the installed package.
- DOMShell commands require Node.js, `npx`, Chrome/Chromium, the DOMShell extension, and `DOMSHELL_TOKEN`.
- CDP commands require Chrome/Chromium running with remote debugging on port 9222, or `CHROME_CDP_HOST`/`CHROME_CDP_PORT`.
- CDP cookie, screenshot, and JavaScript commands require `websocket-client`.

## Command Groups

### `page` - Page Navigation

| Command | Description |
| --- | --- |
| `page open <url>` | Navigate to an HTTP/HTTPS URL. |
| `page reload` | Reload the current page. |
| `page back` | Navigate back in history. |
| `page forward` | Navigate forward in history. |
| `page info` | Show session URL and accessibility-tree path. |

### `fs` - Accessibility Tree

| Command | Description |
| --- | --- |
| `fs ls [path]` | List elements at a DOMShell path. |
| `fs cd <path>` | Change accessibility-tree working directory. |
| `fs cat [path]` | Read element content. |
| `fs grep <pattern> [path]` | Search element text. |
| `fs pwd` | Print current accessibility-tree path. |

### `act` - Element Actions

| Command | Description |
| --- | --- |
| `act click <path>` | Click an element by DOMShell path. |
| `act type <path> <text>` | Type text into an element by DOMShell path. |

### `cdp` - Chrome DevTools Protocol

| Command | Description |
| --- | --- |
| `cdp tabs` | List open Chrome tabs. |
| `cdp url [tab_index]` | Get current tab URL. |
| `cdp title [tab_index]` | Get current tab title. |
| `cdp text [tab_index]` | Get visible page text. |
| `cdp html [tab_index]` | Get page HTML. |
| `cdp eval <expression> [tab_index]` | Evaluate JavaScript in a tab. |
| `cdp select <selector> [tab_index]` | Query a CSS selector. |
| `cdp input <selector> [tab_index]` | Get an input value by CSS selector. |
| `cdp fill <selector> <value> [tab_index]` | Set an input value by CSS selector. |
| `cdp cookies [tab_index]` | List page cookies. |
| `cdp set-cookie <name> <value> [--url URL] [--domain DOMAIN] [--path PATH] [--tab-index N]` | Set a cookie. |
| `cdp screenshot [tab_index] [--format png|jpeg|webp]` | Capture a tab screenshot. |
| `cdp navigate <url> [tab_index] [--wait SECONDS]` | Navigate a tab through CDP. |

### `profile` - Chrome Profile State

| Command | Description |
| --- | --- |
| `profile dir [--create] [--profile PATH]` | Show resolved profile directory. |
| `profile set-pref <key_path> <value> [--profile PATH]` | Set a Chrome Preferences key. |
| `profile add-history <url> [--title TITLE] [--visit-count N] [--profile PATH]` | Add a History URL row. |
| `profile add-download <path> [--tab-url URL] [--mime-type TYPE] [--state N] [--profile PATH]` | Add a completed download row and ensure the target file exists. |
| `profile add-bookmark <name> <url> [--folder ROOT] [--profile PATH]` | Add a bookmark. |
| `profile install-extension <ext_id> <name> [--version VERSION] [--description TEXT] [--profile PATH]` | Create an extension manifest in the profile. |

### `session` - Session Management

| Command | Description |
| --- | --- |
| `session status` | Show session state. |
| `session daemon-start` | Start persistent DOMShell daemon mode. |
| `session daemon-stop` | Stop DOMShell daemon mode. |

## Examples

```bash
cli-anything-browser page open https://example.com
cli-anything-browser fs ls /
cli-anything-browser fs grep "Login"
cli-anything-browser act click /main/button[0]
```

```bash
cli-anything-browser cdp tabs
cli-anything-browser cdp eval "document.title"
cli-anything-browser cdp select "input[name='q']"
cli-anything-browser cdp fill "input[name='q']" "search text"
cli-anything-browser cdp set-cookie session_id abc --url https://example.com
```

```bash
cli-anything-browser profile add-history https://example.com --title "Example"
cli-anything-browser profile add-download /home/user/Downloads/report.txt --tab-url https://example.com/report --mime-type text/plain
cli-anything-browser profile add-bookmark "Example" https://example.com
cli-anything-browser profile set-pref download.default_directory '"/home/user/Downloads"'
```

Use `--json` before the command group for machine-readable output:

```bash
cli-anything-browser --json cdp tabs
```

Run without a subcommand to start the interactive REPL:

```bash
cli-anything-browser
```

## Path Syntax

DOMShell paths are filesystem-like:

```text
/
/main
/main/div[0]
/main/div[0]/button[2]
```

Array indices are 0-based. Use `/` for root and `..` to go up one level.

## Security Notes

`page open` validates URLs and allows HTTP/HTTPS by default. Set `CLI_ANYTHING_BROWSER_ALLOWED_SCHEMES` to change allowed schemes. Set `CLI_ANYTHING_BROWSER_BLOCK_PRIVATE=true` to block localhost and private-network access.
