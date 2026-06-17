# SAFARI.md — Software-Specific Analysis

> **Disclosure:** This harness was contributed by the maintainer of
> `safari-mcp`.

Software: **[safari-mcp](https://github.com/achiya-automation/safari-mcp)** (npm: `safari-mcp`)

Target: **Safari on macOS** via safari-mcp's Node.js MCP server.

This document covers the Phase 1 codebase analysis, command map, and
rendering-gap assessment required by the CLI-Anything methodology
(see [`../cli-anything-plugin/HARNESS.md`](../cli-anything-plugin/HARNESS.md)).

---

## 1. Codebase Analysis

### Backend engine

Safari MCP is a Node.js MCP server that wraps Safari on macOS. It has
two execution engines:

1. **Safari Web Extension** — HTTP polling transport, loaded when the
   extension is installed.
2. **AppleScript + Swift daemon** — always available, no extension
   required. Default path for most users.

The server uses `extensionOrFallback()` internally to select the
engine per call — the CLI does not need to expose engine selection.

### Multi-instance behavior (proxy mode)

`safari-mcp` defends against duplicate instances in two complementary
ways (see `~/safari-mcp/index.js`):

1. **Singleton check** (lines 22-49) — at startup, `pgrep` for other
   `node …/safari-mcp/index.js` processes; SIGTERM any older than 10s.
2. **Proxy mode** (lines 479-526) — when starting fresh and finding
   port 9224 already bound (because the singleton check didn't fire,
   typically because the primary is owned by another agent's process
   tree), the new instance switches to proxy mode and forwards all
   commands to the primary via HTTP. The primary keeps running.

In practice, when this CLI runs alongside an existing safari-mcp (e.g.
one serving Claude Code), proxy mode kicks in within ~2 seconds and
the primary survives. This was verified live during v1.0 testing —
all 19 E2E tests pass with the user's existing safari-mcp instance
still alive afterward.

### Transport

`safari-mcp` exposes its tools over **stdio** (`StdioServerTransport`),
which is the transport this harness uses. The server does not publish
an HTTP or WebSocket interface.

### Data model

Safari MCP is **stateless from a document perspective** — there are no
project files, no scenes, no timelines. Every tool call acts on the
**currently active Safari tab** (with per-session tab ownership
enforcement) and returns its result as JSON text wrapped in MCP's
standard `{content: [{type:"text", text: ...}]}` envelope.

The closest thing to "state" is:
- **Tab set** — which tabs exist, which is active
- **Snapshot refs** — ref IDs returned by `safari_snapshot` that expire
  on the next snapshot (`0_xx → 1_xx → 2_xx...`)
- **Session tab ownership** — safari-mcp tracks which tabs the current
  MCP session opened, and blocks modifications to tabs the session did
  not open (prevents an agent from mangling the user's active work)

### GUI-to-API mapping

Safari MCP already IS the API. There is no GUI-to-API mapping phase for
this harness — the server's `server.tool()` calls are the API, and we
extract them directly with
[`scripts/extract_tools.py`](scripts/extract_tools.py) rather than
reverse-engineering GUI actions.

### Existing CLI tools

Safari MCP has **no native CLI**. It is a pure MCP stdio server — it
does not respond to `--version` or `--help` on the command line. Our
availability check uses `npm view safari-mcp version` instead of
`npx safari-mcp --version` because the latter would hang waiting for
stdin.

### Command/undo system

Safari MCP has no undo/redo. Browser actions are inherently
imperative and irreversible (clicks can't be un-clicked). The CLI
inherits this and does not attempt to fake history.

---

## 2. Command Map

Safari MCP exposes **84 tools**. The CLI generates one Click subcommand
per tool automatically from the bundled tool schema — there is **no
hand-written mapping**. Run `cli-anything-safari tools list` for the
complete set; the short table below groups them by purpose.

| Purpose                        | Representative tools                                         |
|--------------------------------|--------------------------------------------------------------|
| Navigation                     | `navigate`, `go-back`, `go-forward`, `reload`                |
| Page content                   | `read-page`, `snapshot`, `get-source`, `accessibility-snapshot`, `extract-tables`, `extract-meta`, `extract-links`, `extract-images`, `analyze-page`, `detect-forms` |
| Click                          | `click`, `click-and-read`, `click-and-wait`, `double-click`, `right-click`, `native-click` |
| Form input                     | `fill`, `clear-field`, `select-option`, `fill-form`, `fill-and-submit`, `press-key`, `type-text`, `replace-editor` |
| Screenshots + PDF              | `screenshot`, `screenshot-element`, `save-pdf`               |
| Scroll                         | `scroll`, `scroll-to`, `scroll-to-element`                   |
| Tab management                 | `list-tabs`, `new-tab`, `close-tab`, `switch-tab`, `wait-for-new-tab` |
| Waits                          | `wait`, `wait-for`                                           |
| JavaScript                     | `evaluate`, `run-script`                                     |
| Storage — cookies              | `get-cookies`, `set-cookie`, `delete-cookies`                |
| Storage — localStorage         | `local-storage`, `set-local-storage`, `delete-local-storage` |
| Storage — sessionStorage       | `session-storage`, `set-session-storage`, `delete-session-storage` |
| Storage — IndexedDB            | `list-indexed-dbs`, `get-indexed-db`                         |
| Storage — import/export        | `export-storage`, `import-storage`                           |
| Network monitoring             | `network`, `start-network-capture`, `network-details`, `clear-network` |
| Network shaping                | `mock-route`, `clear-mocks`, `throttle-network`              |
| Performance                    | `performance-metrics`, `css-coverage`                        |
| Console                        | `start-console`, `get-console`, `console-filter`, `clear-console` |
| Mouse / drag                   | `hover`, `drag`                                              |
| Files                          | `upload-file`, `paste-image`                                 |
| Dialogs                        | `handle-dialog`                                              |
| Clipboard                      | `clipboard-read`, `clipboard-write`                          |
| Device / viewport              | `emulate`, `reset-emulation`, `resize`, `override-geolocation` |
| Computed style                 | `get-computed-style`                                         |
| Single-element read            | `get-element`, `query-all`                                   |

Every one of these is reachable as `cli-anything-safari tool <short-name>`
with the full MCP schema driving the Click options (argument names,
types, enum choices, required/optional, and descriptions).

---

## 3. Rendering-Gap Assessment

**Status: N/A.**

The "rendering gap" pitfall in HARNESS.md applies to apps where the CLI
builds a project file (MLT XML, ODF, .blend, etc.) and then has to hand
it off to a renderer. Browser automation has no rendering step — every
tool call is synchronous and its output is the final answer.

Safari MCP IS the renderer. We call it, it runs the action against the
real Safari, and the result is final. There is no intermediate project
format for us to translate.

## 4. Filter Translation

**Status: N/A.**

No effect/filter system in browser automation. The
[`filter-translation.md`](../cli-anything-plugin/guides/filter-translation.md)
guide does not apply.

## 5. Timecode Precision

**Status: N/A.**

No video/audio in browser automation. The
[`timecode-precision.md`](../cli-anything-plugin/guides/timecode-precision.md)
guide does not apply.

## 6. Session Locking

**Status: N/A (no persistent session).**

Unlike document-based harnesses, this harness does not persist session
state to disk. The [`session-locking.md`](../cli-anything-plugin/guides/session-locking.md)
pattern (`_locked_save_json` with `fcntl.flock`) is not needed because
there are no session JSON saves. The in-memory `Session` object holds
only the last URL and current tab index for REPL display, both of
which are reset on every CLI invocation.

---

## 7. "Use the Real Software" Compliance

HARNESS.md's #1 rule: **Use the real software — don't reimplement it.**

This harness complies: every `cli-anything-safari tool <name>` call
spawns `npx -y safari-mcp` as a subprocess and routes the call through
the real safari-mcp server, which in turn drives the real Safari
application. There is no pure-Python fallback, no "mock Safari", and no
attempt to reimplement DOM interaction in Python.

- **Hard dependency:** Node.js 18+, macOS (Darwin), Safari. The
  `is_available()` check refuses to run if any of these are missing and
  prints install instructions.
- **No graceful degradation:** Tool calls raise `RuntimeError` with
  clear install instructions if safari-mcp cannot be spawned or Safari
  is not reachable.
- **No reimplementation:** Every tool call goes through the MCP stdio
  client → safari-mcp → Safari. The CLI owns presentation (Click
  commands, REPL, JSON output, URL validation) and nothing else.

---

## 8. Validator Checklist — Why Some Items Are N/A

The [`validate.md`](../cli-anything-plugin/commands/validate.md) checklist
lists a few "required files" that do not apply to this harness:

| Required by validate.md  | Status    | Reason                                             |
|--------------------------|-----------|----------------------------------------------------|
| `core/project.py`        | N/A       | No project file format — browser is stateless     |
| `core/export.py`         | N/A       | No rendering step — safari-mcp IS the backend     |
| `--project` CLI flag     | N/A       | No project file to operate on                     |
| Session undo/redo        | N/A       | Browser actions are irreversible by design        |
| Session snapshot         | N/A       | No document state to snapshot                     |
| Filter translation       | N/A       | No effect pipeline                                 |
| Rendering verification   | N/A       | No rendered output to verify                       |
| Session locking          | N/A       | No persistent session state                        |

The sibling DOMShell harness (`browser/agent-harness/`) makes the same
choices — it has `core/fs.py` and `core/page.py` instead of
`core/project.py` and `core/export.py`, because the "project/export"
pattern is for document-based apps (LibreOffice, GIMP, Blender,
Shotcut), not for interactive browsers.

---

## 9. Architecture Decisions Unique to This Harness

Unlike every other CLI-Anything harness, this one is **schema-driven**:

1. **Schema extraction** (offline): [`scripts/extract_tools.py`](scripts/extract_tools.py)
   parses safari-mcp's Zod source with a depth-aware scanner and
   produces [`cli_anything/safari/resources/tools.json`](cli_anything/safari/resources/tools.json).
2. **Dynamic Click registration**: [`cli_anything/safari/safari_cli.py`](cli_anything/safari/safari_cli.py)
   loads `tools.json` at import time and calls `_build_tool_command`
   for every tool, producing a Click command with option names, types,
   choices, and required/optional flags pulled from the schema.
3. **Parity test**: [`cli_anything/safari/tests/test_parity.py`](cli_anything/safari/tests/test_parity.py)
   iterates the registry and verifies every tool is reachable via
   Click with the correct shape. It pins the expected tool count (84)
   so upstream drift fails loudly.

The alternative — hand-wrapping 84 tools in Python — would be ~1,500
lines of boilerplate that duplicates schema information already
present in safari-mcp's source. The schema-driven approach stays
correct without manual synchronization when safari-mcp adds tools.

---

## 10. References

- [safari-mcp GitHub](https://github.com/achiya-automation/safari-mcp)
- [safari-mcp on npm](https://www.npmjs.com/package/safari-mcp)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [CLI-Anything HARNESS.md](../cli-anything-plugin/HARNESS.md)
- [MCP Backend Pattern Guide](../cli-anything-plugin/guides/mcp-backend.md)
- [Sibling: browser/agent-harness (DOMShell/Chrome)](../browser/agent-harness/)
- [Local HARNESS.md](HARNESS.md) — harness-specific deep dive
