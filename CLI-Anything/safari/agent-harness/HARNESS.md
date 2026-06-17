# Safari Harness: safari-mcp MCP Integration

> **Disclosure:** This harness was contributed by the maintainer of
> `safari-mcp`. It wraps the upstream MCP server as a CLI; no code
> from safari-mcp is vendored or modified.

## Purpose

This harness provides Safari browser automation on macOS by wrapping
[`safari-mcp`](https://github.com/achiya-automation/safari-mcp) — a
Node.js MCP server — in a Python Click CLI.

It follows the MCP backend pattern documented in
[`cli-anything-plugin/guides/mcp-backend.md`](../cli-anything-plugin/guides/mcp-backend.md).

## Architecture Overview

```
┌──────────────────────┐     ┌──────────────────────┐
│  Click command       │────▶│  safari_backend.call │
│  (auto-generated     │     │  (MCP stdio client)  │
│   from tool schema)  │     └───────────┬──────────┘
└──────────┬───────────┘                 │
           │                             ▼
           │                  ┌──────────────────────┐
           │                  │  Spawn npx subprocess│
           │                  │  npx -y safari-mcp   │
           │                  └──────────┬───────────┘
           │                             │
           │                             ▼
           │                  ┌──────────────────────┐
           │                  │  safari-mcp server   │
           │                  │  (Node.js, stdio)    │
           │                  └──────────┬───────────┘
           │                             │
           │                             ▼
           │                 ┌──────────────────────┐
           │                 │  Dual engine:        │
           │                 │  1. Safari Extension │
           │                 │  2. AppleScript/Swift│
           │                 └──────────┬───────────┘
           │                            │
           ▼                            ▼
  ┌─────────────────┐         ┌──────────────────────┐
  │ resources/      │         │  Safari (macOS)      │
  │ tools.json      │         └──────────────────────┘
  │ (84 schemas)    │
  └─────────────────┘
```

## Key Design Decision: Schema-Driven CLI

**Every Click command is auto-generated from the bundled MCP tool schema.**
Feature parity with safari-mcp is guaranteed because there is no manual
mapping between MCP tools and Click commands — the CLI reads the schema
at import time and registers one subcommand per tool, with option names,
types, descriptions, enum choices, and required flags pulled straight
from the source.

### Why not manual wrappers?

The DOMShell harness hand-wraps ~10 tools as explicit Python functions.
That works for a small tool surface but breaks down at scale:

- Safari MCP has **84 tools** — ~1,500 lines of manual boilerplate
- Argument names drift (`--source-selector` vs `sourceSelector`)
- Descriptions fall out of date with upstream
- New tools upstream require manual addition here

Instead, this harness ships a single dynamic command group and generates
every command at import time from `resources/tools.json`.

### How the schema is sourced

The schema is extracted **offline** from `safari-mcp`'s JavaScript source
by [`scripts/extract_tools.py`](scripts/extract_tools.py). The extractor
is a hand-written parser that walks the Zod schema definitions with
depth-aware modifier detection so nested schemas (`z.array(z.object({...}))
.describe("outer")`) don't confuse it.

Regenerate the schema whenever `safari-mcp` upgrades:

```bash
python scripts/extract_tools.py \
    /path/to/safari-mcp/index.js \
    cli_anything/safari/resources/tools.json
```

The parser produces JSON with a top-level `tool_count`, `source_version`,
`source_basename`, and a `tools` array. The `test_parity.py` suite pins
the expected tool count and locks the nested-schema shapes that were
previously miscounted.

## Parity Guarantee

Three layers enforce CLI ↔ MCP parity:

1. **Schema extraction** — `extract_tools.py` parses every
   `server.tool(...)` block in `safari-mcp`'s source and emits a JSON
   Schema fragment per tool.
2. **Runtime generation** — `safari_cli.py._register_all_tools()` loads
   `tools.json` and calls `_build_tool_command(tool)` for every tool,
   producing a Click command with options derived from the schema.
3. **Parity tests** — `test_parity.py` holds the two halves accountable:
   - Every tool in the registry must be reachable as a Click subcommand
   - Every MCP parameter must have a matching Click option
   - Required MCP params must be required in Click (covers all types,
     including object/array)
   - Enum choices must match exactly
   - Plus regression locks for specific nested-schema bugs that the
     parser previously got wrong

## Structure

```
safari/agent-harness/
├── HARNESS.md                          this file
├── setup.py                            find_namespace_packages + bundles tools.json
├── scripts/
│   └── extract_tools.py                offline parser → tools.json
└── cli_anything/                       PEP 420 namespace (NO __init__.py)
    └── safari/
        ├── __init__.py
        ├── __main__.py                 python -m cli_anything.safari
        ├── README.md                   user-facing docs
        ├── safari_cli.py               dynamic Click CLI
        ├── core/
        │   └── session.py              in-memory state (last URL, tab)
        ├── utils/
        │   ├── safari_backend.py       MCP stdio client (sync wrapper)
        │   ├── security.py             URL validation
        │   ├── tool_registry.py        loads tools.json, normalizes names
        │   └── repl_skin.py            (copied verbatim from plugin)
        ├── resources/
        │   └── tools.json              bundled MCP tool registry (84 tools)
        ├── skills/
        │   └── SKILL.md                agent-discovery manifest
        └── tests/
            ├── test_core.py            unit tests, no Safari required
            ├── test_security.py        URL validation
            ├── test_parity.py          CLI ↔ registry parity + regression locks
            └── test_full_e2e.py        CliRunner + subprocess E2E (gated by SAFARI_E2E)
```

## Command Structure

Five top-level commands:

| Command   | Purpose                                                         |
|-----------|-----------------------------------------------------------------|
| `tool`    | Call any safari-mcp tool by its short name                      |
| `tools`   | Inspect the bundled registry (`list`, `describe`, `count`)      |
| `raw`     | Escape hatch — call a tool by full MCP name with JSON args      |
| `session` | In-memory session state (last URL, current tab)                 |
| `repl`    | Interactive REPL (default when run with no subcommand)          |

The `tool` group contains exactly 84 subcommands, one per MCP tool, with
the `safari_` prefix stripped and underscores converted to hyphens:

```
tool navigate --url https://example.com
tool click --ref 0_5
tool scroll --direction down --amount 500
tool fill-form --fields '[{"selector":"#email","value":"a@b.com"}]'
```

## URL Validation

Navigation tools (anything with a `url` param whose name is literally
`"url"`) pass the URL through `utils/security.py` before calling MCP.
Blocked schemes include `file`, `javascript`, `data`, `vbscript`, `about`,
browser-internal schemes (`chrome:`, `safari:`, `webkit:`, `opera:`),
and `x-apple:`. Allowed schemes default to `http` and `https`.

The `raw` command **also** enforces this check for tools in the
navigation set. The set is computed dynamically at startup from the
registry so new URL-taking tools added upstream are automatically
protected.

### Configuration

- `CLI_ANYTHING_SAFARI_ALLOWED_SCHEMES` — comma-separated scheme list
- `CLI_ANYTHING_SAFARI_BLOCK_PRIVATE` — set to `1` to block private IPs

See [`cli_anything/safari/utils/security.py`](cli_anything/safari/utils/security.py)
for the full scheme and private-network lists.

## Error Handling

### Dependency Checks

```python
available, message = is_available()
if not available:
    print(f"Error: {message}")
```

Error messages the CLI surfaces on startup:
- `Not macOS` → harness refuses; use DOMShell (Chrome) instead
- `npx not found` → install Node.js 18+
- `safari-mcp package not found on npm registry` → network/npm issue

### MCP Tool Failures

MCP tool failures raise `RuntimeError` with Safari-specific context
including the enable-Apple-Events reminder. Both the dynamic `tool`
commands and the `raw` command catch exceptions at the top of their
handlers and route them through `_handle_error`, which honors the global
`--json` flag and the REPL mode.

## Session State (Not Persistent)

`Session` keeps two in-memory fields for REPL display only:
- `last_url: str` — the last URL the CLI navigated to
- `current_tab_index: Optional[int]` — last known active tab index

There is no state persistence between CLI invocations and no daemon
mode. Daemon mode was considered and rejected because a sync Python
wrapper around an async MCP client cannot cleanly hold an `asyncio`
session across `asyncio.run()` calls without a background event-loop
thread — a v2 concern, not v1.

## Performance Characteristics

Each CLI invocation spawns a fresh `npx safari-mcp` subprocess. This
adds ~2.9s of overhead per call (npx resolution, Node startup, MCP
handshake). For latency-sensitive workflows, users should drive the
Python API directly (`from cli_anything.safari.utils.safari_backend
import call`) or use `safari-mcp` over MCP stdio.

The CLI targets use cases where MCP is not available: non-MCP agent
frameworks, bash pipelines, CI/cron, and terminal debugging.

## Testing Strategy

### Unit Tests (`tests/test_core.py`)

Unit tests for the backend helpers with mocked MCP calls. No Safari, no
network, no subprocess. Covers:
- Platform gating (Darwin-only)
- MCP result unwrapping (JSON vs raw text)
- Argument cleaning (None stripping)
- Session state

### Security Tests (`tests/test_security.py`)

Covers `validate_url` in isolation:
- Blocked schemes (`file`, `javascript`, `data`, `about`, `vbscript`,
  `webkit`, `safari`)
- Malformed inputs (empty, whitespace, None, missing scheme/host)
- Enum-style scheme helpers
- Private-network env var behavior

### Parity Tests (`tests/test_parity.py`)

The linchpin for the "exactly like MCP" guarantee:
- Registry size pinned to 84
- Every tool reachable as a Click subcommand
- No unexpected Click subcommands not in the registry
- Every MCP param has a matching Click option
- Required MCP params are required in Click (**all** types, including
  object/array — regression fix from early drafts that skipped those)
- Enum choices match exactly
- Introspection commands (`tools list/describe/count`) return the
  expected shapes
- Regression locks for four specific nested-schema bugs that a past
  version of the parser got wrong (see
  `TestParityHighValueSchemas`)

### E2E Tests (`tests/test_full_e2e.py`)

Gated behind the `SAFARI_E2E` environment variable. The original
concern was that spawning `npx safari-mcp` would trigger the
singleton-killer branch (lines 22-49 of `~/safari-mcp/index.js`) and
terminate any active safari-mcp serving a concurrent Claude Code
session. In practice, **safari-mcp's proxy mode** (lines 479-526)
takes over before the killer fires when port 9224 is already bound,
and the primary survives — verified live during v1.0 testing. The
gate is kept as defensive cover and to avoid mutating Safari state
during a casual `pytest` run (some tests open or navigate tabs).
Five classes:

- `TestDependencyChecks` — `--help` works, all groups visible
- `TestSessionCommands` — session status via CliRunner
- `TestSecurityIntegration` — URL validation at the CLI boundary
- `TestRealSafariRoundTrip` — actually talks to Safari, mutates state
- `TestCLISubprocess` — invokes the installed `cli-anything-safari`
  binary via `subprocess.run`, using `_resolve_cli()` to honor the
  `CLI_ANYTHING_FORCE_INSTALLED` env var. `CLI_BASE` is a lazy class
  property so collection does not fail when the command is missing
  and E2E is disabled.

To run E2E locally (will kill any concurrent safari-mcp):

```bash
SAFARI_E2E=1 CLI_ANYTHING_FORCE_INSTALLED=1 \
    python -m pytest cli_anything/safari/tests/test_full_e2e.py -v -s
```

## Performance

### Per-Command Overhead

Each command spawns a fresh `npx -y safari-mcp`:
- **Cold start**: 500ms–2s on first run (npx resolution + package fetch)
- **Warm start**: ~200–500ms (package cached)

There is no daemon mode. For latency-sensitive workflows, drive the
CLI from a long-lived Python script that imports
`cli_anything.safari.utils.safari_backend.call()` directly, which still
spawns per call but at least avoids the Python interpreter startup.

### Response Sizes

- `tool snapshot` → typically 5–50 KB of structured text
- `tool screenshot --full-page` → 100 KB – several MB (image)
- `tool get-source` → up to 200 KB (configurable `--max-length`)

**Prefer `tool snapshot` over `tool screenshot`** — structured text is
orders of magnitude smaller and carries the ref IDs needed for
interaction.


## Future Enhancements

**Not in scope for v1:**
- Daemon mode (requires a background event-loop thread)
- Multi-browser coverage (Firefox via WebDriver BiDi)
- WebSocket transport (currently stdio)
- Headless Safari mode (doesn't exist on macOS)
- Recursive array/object item schema extraction in the parser (current
  output carries the outer `.describe()` text but not the nested shape)
- Persistent state across CLI invocations

## Applying This Pattern

The MCP backend pattern with schema-driven Click generation can be
applied to any software that exposes an MCP server. Steps:

1. Identify the MCP server and count its tool surface
2. Write or adapt `extract_tools.py` for the server's source format
3. Generate a `tools.json` and bundle it as `package_data`
4. Create a `tool_registry.py` that loads and normalizes the schema
5. Register a dynamic Click group that walks the registry
6. Add URL / path / file validation hooks for state-changing tools
7. Write parity tests that compare the CLI surface against the registry
   with regression locks for any nested-schema quirks
8. Add SKILL.md with examples drawn from the most common tools

## References

- [safari-mcp GitHub](https://github.com/achiya-automation/safari-mcp)
- [safari-mcp on npm](https://www.npmjs.com/package/safari-mcp)
- [CLI-Anything plugin HARNESS.md](../cli-anything-plugin/HARNESS.md)
- [MCP Backend Pattern Guide](../cli-anything-plugin/guides/mcp-backend.md)
- [Sibling: browser/agent-harness (DOMShell / Chrome)](../browser/agent-harness/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
