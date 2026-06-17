# cli-anything-safari

A command-line interface for Safari browser automation on macOS via
[`safari-mcp`](https://github.com/achiya-automation/safari-mcp).

Every one of the 84 MCP tools is auto-generated as a Click command
from the bundled tool schema.

> **Note:** Each CLI invocation spawns a fresh subprocess. If your
> agent supports MCP natively, using `safari-mcp` directly will be
> faster. This CLI targets non-MCP agent frameworks, bash pipelines,
> CI/cron, and terminal debugging.

## Installation

### Prerequisites

1. **macOS** (Darwin) — Safari MCP is macOS-only
2. **Node.js 18+** — `brew install node` or https://nodejs.org/
3. **Python 3.10+**
4. **Safari** with `Develop → Allow JavaScript from Apple Events` enabled

### Install

```bash
cd safari/agent-harness
pip install -e .
```

The first `tool` call downloads the `safari-mcp` npm package (a few MB).

## Quick Start

```bash
# Discover the tool surface
cli-anything-safari tools count
# → 84

cli-anything-safari tools list
cli-anything-safari tools describe safari_click

# Call any tool
cli-anything-safari tool navigate --url https://example.com
cli-anything-safari --json tool snapshot
cli-anything-safari tool click --ref 0_5
cli-anything-safari tool fill --selector "#email" --value "user@example.com"
cli-anything-safari --json tool screenshot --full-page \
    | python3 -c "import sys,json,base64; d=json.load(sys.stdin); open('/tmp/shot.jpg','wb').write(base64.b64decode(d['data']))"
cli-anything-safari tool evaluate --script "document.title"

# Interactive REPL
cli-anything-safari
```

## Command Structure

| Command   | Purpose                                                           |
|-----------|-------------------------------------------------------------------|
| `tool`    | Call any of safari-mcp's 84 tools (dynamic, schema-driven)        |
| `tools`   | Inspect the bundled tool registry (`list`, `describe`, `count`)   |
| `raw`     | Escape hatch — call a tool by full name with raw JSON args        |
| `session` | In-memory session state (last URL, current tab)                   |
| `repl`    | Interactive REPL (default when no subcommand given)               |

Run `cli-anything-safari <command> --help` for details.

## JSON Output

```bash
cli-anything-safari --json tool snapshot
cli-anything-safari --json tools list
```

## Environment Variables

Passed through to `safari-mcp`:

| Variable                | Purpose                                      |
|-------------------------|----------------------------------------------|
| `SAFARI_PROFILE`        | Safari profile name (e.g. "Automation")      |
| `MCP_MAX_TABS`          | Max tabs per session (default 6)             |
| `MCP_MEMORY_CHECK_MS`   | Memory check interval (default 60000)        |
| `MCP_WEBKIT_LIMIT_MB`   | WebKit memory limit (default 3000)           |

Consumed by the CLI itself:

| Variable                              | Purpose                             |
|---------------------------------------|-------------------------------------|
| `CLI_ANYTHING_SAFARI_BLOCK_PRIVATE`   | Set to `1` to block private IPs     |
| `CLI_ANYTHING_SAFARI_ALLOWED_SCHEMES` | Override allowed URL schemes        |
| `CLI_ANYTHING_FORCE_INSTALLED`        | Test mode: require installed CLI    |

## Snapshot-Driven Workflow (Recommended)

Snapshots return structured text with **ref IDs** for every interactive
element. Clicking by ref is cheaper and more reliable than by CSS selector.

```bash
cli-anything-safari --json tool snapshot > /tmp/snap.json
# Agent reads /tmp/snap.json, finds "Submit" button with ref "3_12"
cli-anything-safari tool click --ref 3_12
```

**Refs expire** after each new snapshot (`5_xx → 6_xx`). Snapshot → click in
close succession.

## Troubleshooting

### "npx not found"

Install Node.js 18+: `brew install node`.

### "safari-mcp package not found on npm registry"

Check your internet connection, then try:

```bash
npm view safari-mcp version
```

### "AppleScript execution failed"

Enable `Safari → Develop → Allow JavaScript from Apple Events`.

### "Tool cannot operate on tab it did not open"

This is the tab ownership guard. Open a fresh tab first:

```bash
cli-anything-safari tool new-tab --url https://example.com
cli-anything-safari tool click --selector "#button"
```

## Security

- **Tab isolation** — upstream safari-mcp enforces per-session tab ownership
- **URL validation** — navigation tools validate URLs and block dangerous
  schemes (`file`, `javascript`, `data`, `about`, browser-internal, etc.)
  both through the `tool` group and via the `raw` escape hatch
- **Profile separation** — use `SAFARI_PROFILE` to keep automation data
  separate from the user's main browsing

### ⚠️ Singleton-killer warning

Safari MCP enforces a single active instance by killing any other
`node …/safari-mcp/index.js` process older than 10 seconds at startup.
This means **running `cli-anything-safari` (or any other safari-mcp
client) will terminate any concurrent safari-mcp instance** — including
one serving Claude Code, Cursor, or another agent session on the same
machine. Plan your usage accordingly:

- Don't run two CLI invocations in parallel from different shells
- Don't run this CLI while another agent (Claude Code, etc.) is
  actively using safari-mcp via MCP transport
- The E2E test suite is gated behind `SAFARI_E2E=1` precisely because
  running it would kill any active safari-mcp instance

## Regenerating the tool registry

After upgrading `safari-mcp`, regenerate the bundled schema:

```bash
python scripts/extract_tools.py \
    /path/to/safari-mcp/index.js \
    cli_anything/safari/resources/tools.json
```

Then run `python -m pytest cli_anything/safari/tests/test_parity.py` —
update the pinned tool count if safari-mcp changed.

## Links

- [safari-mcp GitHub](https://github.com/achiya-automation/safari-mcp)
- [safari-mcp on npm](https://www.npmjs.com/package/safari-mcp)
- [CLI-Anything](https://github.com/HKUDS/CLI-Anything)
- [Harness architecture deep-dive](https://github.com/HKUDS/CLI-Anything/blob/main/safari/agent-harness/HARNESS.md)
- [Safari-specific analysis](https://github.com/HKUDS/CLI-Anything/blob/main/safari/agent-harness/SAFARI.md)
- [Test plan & results](https://github.com/HKUDS/CLI-Anything/blob/main/safari/agent-harness/cli_anything/safari/tests/TEST.md)
