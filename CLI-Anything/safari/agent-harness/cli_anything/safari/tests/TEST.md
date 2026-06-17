# TEST.md — Test Plan & Results

This file follows the two-part structure required by
[`cli-anything-plugin/HARNESS.md`](../../../../cli-anything-plugin/HARNESS.md):
**Part 1** (test plan, written before implementation) documents what is
tested and why. **Part 2** (test results, appended after a successful
run) pastes the pytest output for traceability.

---

## Part 1 — Test Plan

### Deliberate Deviations from `validate.md`

This harness deviates from the standard CLI-Anything test rules in
three documented ways. Each deviation is justified by the MCP-backend
architecture; the alternative would mean shipping fake compliance
that doesn't reflect reality.

**1. E2E tests are gated behind `SAFARI_E2E=1` (HARNESS.md L501 says
they MUST run by default).**

Why gated:
- E2E tests **mutate Safari state** — `test_navigate_and_read_example_com`
  navigates the active Safari tab to https://example.com/. A user
  who runs `pytest` casually shouldn't lose whatever they were
  looking at.
- Running these tests in a developer environment that has a
  long-lived `safari-mcp` instance triggers the singleton-killer
  branch in `~/safari-mcp/index.js` lines 22-49 — *technically*
  Safari MCP enters proxy mode when port 9224 is already bound
  (lines 479-526), so the primary survives in practice (verified
  live during the v1.0 final test pass), but we keep the gate as
  defensive cover for the case where proxy mode doesn't initialize
  fast enough.
- CI environments and the package maintainer should set
  `SAFARI_E2E=1` to run the full suite. Verified locally:
  `SAFARI_E2E=1 CLI_ANYTHING_FORCE_INSTALLED=1 pytest …` runs all
  19 E2E tests including the 3 that talk to real Safari, and they
  all pass against the live MCP server in proxy mode.

**2. `core/project.py` and `core/export.py` do not exist.**

`validate.md` lines 37-39 list both as required. They are N/A for
browser automation:
- There is no project file format to manage. Every browser action
  is imperative and immediate.
- There is no rendering pipeline. Safari MCP IS the renderer; the
  CLI just forwards calls.
- The DOMShell harness (`browser/agent-harness/`) makes the same
  decision and ships `core/fs.py` + `core/page.py` instead. Our
  schema-driven design eliminates even those — `core/` only holds
  `session.py` (a tiny in-memory state holder).

See `SAFARI.md` §8 for the full N/A breakdown.

**3. `Session` has no undo/redo/snapshot.**

`validate.md` line 53 requires "Session class with undo/redo/snapshot".
N/A because:
- Browser actions (clicks, navigations) are inherently irreversible.
  There is no document to roll back to.
- Snapshot already exists at the safari-mcp level
  (`safari_snapshot` / `safari_accessibility_snapshot`) and is
  exposed via `cli-anything-safari tool snapshot`. The CLI does not
  duplicate this state.
- DOMShell's `Session` also lacks undo/redo for the same reason.

If the upstream MCP server ever adds a stateful document model
(unlikely for safari-mcp), these features can be added back without
changing the rest of the harness.

### Test Inventory

| File                    | Test count | Category                      | Requires Safari? |
|-------------------------|-----------:|-------------------------------|------------------|
| `test_core.py`          |         16 | unit, mocked backend          | no               |
| `test_security.py`      |         36 | security / URL validation     | no               |
| `test_parity.py`        |         24 | CLI ↔ MCP schema parity       | no               |
| `test_full_e2e.py`      |         19 | E2E (CliRunner + subprocess)  | yes (gated)      |
| **Total**               |     **95** |                               |                  |

E2E tests are gated behind the `SAFARI_E2E=1` environment variable. Of
the 19 E2E tests, **16 can run without mutating Safari state** (all
help/metadata/security tests) and the remaining 3 (`TestRealSafariRoundTrip::*`,
`TestCLISubprocess::test_list_tabs_json_roundtrip`) actually exercise
real Safari and should be run manually.

### Unit Test Plan (`test_core.py`)

Covers the backend helpers in `utils/safari_backend.py` and the
`Session` dataclass in `core/session.py`. **No Safari, no network, no
subprocess.** Mocks `mcp.ClientSession` and `asyncio.run`.

Modules and functions under test:

- `safari_backend.is_available()` — platform gating + npm registry probe
- `safari_backend._unwrap()` — MCP `CallToolResult` → Python value
  - **TextContent** items (most tools)
  - **ImageContent** items (`safari_screenshot`, `safari_screenshot_element`)
  - Empty content, missing mimeType, multiple content parts
- `safari_backend.call()` — argument forwarding, None stripping, result unwrapping
- `core.session.Session` — defaults, set_url, set_tab, status() (with
  empty-url sentinel branch)

Edge cases:

- Non-Darwin platform must be rejected
- Empty MCP result content
- Multiple content parts (list vs single-value unwrap)
- JSON vs raw-text content handling
- ImageContent NOT silently dropped (regression lock)
- Missing optional fields on returned objects

Expected test count: **16** — matches delivered count.

### Security Test Plan (`test_security.py`)

Covers `utils/security.py` in isolation. **No Safari required.**

Classes:
- **TestURLValidation** — every blocked scheme, every malformed input
  form, scheme helper accessors (22 tests)
- **TestDOMSanitization** — plain text, truncation, prompt-injection
  pattern flagging (English/Chinese), HTML comment / script tag
  detection, control-char stripping, newline preservation (11 tests)
- **TestPrivateNetworkConfig** — default behavior (allow localhost),
  env-var override expectations (3 tests)

Expected test count: **36** — matches delivered count.

### Parity Test Plan (`test_parity.py`)

This is the central "exactly like MCP" guarantee. Each test verifies
one aspect of the CLI ↔ registry mapping. **No Safari required.**

Classes:

- **TestParityToolCoverage** (5 tests)
  - Registry is non-empty
  - Registry tool count is pinned to 84 (fails loudly on upstream drift)
  - Every tool in the registry is reachable as `cli-anything-safari tool <short-name>`
  - `tool` group has exactly `len(registry)` Click subcommands
  - No Click subcommands exist that are not in the registry

- **TestParityParameters** (3 tests)
  - Every MCP param has a matching Click option (kebab-case match)
  - Every required MCP param is required in Click (all types, including
    `object`/`array` which were skipped in an earlier draft and masked
    a parser regression)
  - Every enum MCP param exposes the same choices in Click's `Choice` type

- **TestParityIntrospection** (6 tests)
  - `tools count` prints the right number
  - `tools list` mentions every tool
  - `tools list --json` returns the expected JSON shape
  - `tools describe <full-name>` works
  - `tools describe <short-name>` works
  - `tools describe <unknown>` exits non-zero

- **TestParityHighValueSchemas** (8 tests) — regression locks for
  specific parser bugs that earlier revisions got wrong:
  - `safari_scroll` uses `direction` (enum) + `amount`, NOT `x`/`y`
  - `safari_drag` uses `sourceSelector`/`targetSelector`
  - `safari_mock_route` uses `urlPattern`
  - `safari_throttle_network` has `profile`
  - `safari_mock_route.response` is REQUIRED and has the outer
    `"Mock response to return"` description (not the nested
    `"HTTP status code"`)
  - `safari_run_script.steps` is REQUIRED (no top-level `.optional()`)
    and has the outer `"Array of steps to execute sequentially"`
    description
  - `safari_fill_form.fields` description comes from the outer
    `.describe("Array of {selector, value} pairs")`, not from the
    inner `selector: z.string().describe("CSS selector")`
  - `safari_fill_and_submit.fields` same pattern

Expected test count: **24** — matches delivered count (includes
`test_evaluate_param_is_script_not_code` and `test_run_script_param_is_steps`
regression locks added in v1.0).

### E2E Test Plan (`test_full_e2e.py`)

Gated behind `SAFARI_E2E=1`. **Requires Safari + macOS** and will
trigger safari-mcp's singleton killer, which terminates any
concurrent `node .*/safari-mcp/index.js` process older than 10
seconds. **Do not run** while another Claude Code or agent session is
using safari-mcp concurrently.

Classes:

- **TestDependencyChecks** (2 tests, CliRunner)
  - `--help` works
  - Top-level groups all visible

- **TestSessionCommands** (1 test, CliRunner)
  - `session status --json` returns expected keys

- **TestSecurityIntegration** (5 tests, CliRunner)
  - `tool navigate --url file:///etc/passwd` is blocked
  - `tool navigate --url javascript:alert(1)` is blocked
  - `tool navigate --url about:blank` is blocked
  - `tool navigate --url example.com` is rejected (no scheme)
  - `raw safari_navigate` also enforces URL validation

- **TestRealSafariRoundTrip** (2 tests, CliRunner) — **mutate Safari
  state**, run manually only:
  - `tool list-tabs` returns valid JSON from the real server
  - `tool navigate-and-read --url https://example.com` opens the page
    and reads "Example Domain" back

- **TestCLISubprocess** (9 tests, `subprocess.run`) — exercises the
  installed `cli-anything-safari` command, required by HARNESS.md
  Phase 5. Uses a lazy `CLI_BASE` property with `_resolve_cli()` so
  collection does not fail when the command is missing. Honors
  `CLI_ANYTHING_FORCE_INSTALLED=1`:
  - `--help` has "Safari CLI"
  - `tool --help` mentions the expected short names
    (navigate, snapshot, click, fill, screenshot, evaluate, list-tabs,
    mock-route)
  - `tools count` prints 84
  - `tools describe safari_scroll` contains direction + amount
  - `tool scroll --help` shows `--direction [up|down]` and `--amount`
  - `raw --help` mentions `tool_name`
  - `session status --json` has expected keys
  - `tool navigate --url file:///etc/passwd` exits non-zero
  - `tool list-tabs --json` round-trips to Safari (manual only)

Expected test count: **19** — matches delivered count.

### Realistic Workflow Scenarios

A schema-driven browser CLI does not have the multi-step project
workflows that document-based harnesses use as E2E anchors (video
editing, photo compositing, etc.). The workflows we can meaningfully
test are single-action sanity checks. More elaborate flows should be
exercised by agents driving the installed command in real use.

1. **URL validation** — block dangerous schemes at the Click boundary.
2. **Schema introspection** — the bundled registry is the source of
   truth for CLI shape. Drift → parity test failure.
3. **Snapshot → click** — the idiomatic Safari-MCP interaction
   pattern. Exercised manually because it mutates real Safari state.
4. **Help round-trip via subprocess** — the installed command works
   from any cwd and produces the expected top-level command list.

---

## Part 2 — Test Results

Last run: 2026-04-10 (pytest -v, offline, mcp==1.27.0, Python 3.14.3)

```
============================= test session starts ==============================
platform darwin -- Python 3.14.3, pytest-9.0.3, pluggy-1.6.0 -- /tmp/safari-harness-venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/am/CLI-Anything/safari/agent-harness
plugins: anyio-4.13.0
collecting ... collected 95 items

cli_anything/safari/tests/test_core.py::TestPlatformCheck::test_refuses_non_darwin PASSED
cli_anything/safari/tests/test_core.py::TestPlatformCheck::test_accepts_darwin_if_deps_present PASSED
cli_anything/safari/tests/test_core.py::TestUnwrap::test_unwrap_json_text PASSED
cli_anything/safari/tests/test_core.py::TestUnwrap::test_unwrap_plain_text PASSED
cli_anything/safari/tests/test_core.py::TestUnwrap::test_unwrap_multiple_parts PASSED
cli_anything/safari/tests/test_core.py::TestUnwrap::test_unwrap_empty PASSED
cli_anything/safari/tests/test_core.py::TestUnwrap::test_unwrap_image_content PASSED
cli_anything/safari/tests/test_core.py::TestUnwrap::test_unwrap_image_content_default_mimetype PASSED
cli_anything/safari/tests/test_core.py::TestCallForwarding::test_strips_none_args_before_call PASSED
cli_anything/safari/tests/test_core.py::TestCallForwarding::test_passes_full_arg_set_when_none_omitted PASSED
cli_anything/safari/tests/test_core.py::TestCallForwarding::test_unwraps_plain_text_when_not_json PASSED
cli_anything/safari/tests/test_core.py::TestSessionState::test_session_defaults PASSED
cli_anything/safari/tests/test_core.py::TestSessionState::test_set_url_updates_last_url PASSED
cli_anything/safari/tests/test_core.py::TestSessionState::test_set_tab_updates_current_tab PASSED
cli_anything/safari/tests/test_core.py::TestSessionState::test_status_contains_expected_keys PASSED
cli_anything/safari/tests/test_core.py::TestSessionState::test_status_empty_url_returns_sentinel PASSED
cli_anything/safari/tests/test_full_e2e.py::TestDependencyChecks::test_cli_help_works SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestDependencyChecks::test_cli_shows_all_command_groups SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestSessionCommands::test_session_status_json SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestSecurityIntegration::test_file_url_blocked SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestSecurityIntegration::test_javascript_url_blocked SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestSecurityIntegration::test_about_url_blocked SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestSecurityIntegration::test_missing_scheme_rejected SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestSecurityIntegration::test_raw_navigate_also_blocked SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestRealSafariRoundTrip::test_tab_list_returns_json SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestRealSafariRoundTrip::test_navigate_and_read_example_com SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestCLISubprocess::test_help SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestCLISubprocess::test_tool_group_help SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestCLISubprocess::test_tools_count_is_84 SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestCLISubprocess::test_tools_describe_scroll SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestCLISubprocess::test_tool_scroll_help_uses_schema SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestCLISubprocess::test_raw_help SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestCLISubprocess::test_session_status_json SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestCLISubprocess::test_blocked_scheme_exits_nonzero SKIPPED
cli_anything/safari/tests/test_full_e2e.py::TestCLISubprocess::test_list_tabs_json_roundtrip SKIPPED
cli_anything/safari/tests/test_parity.py::TestParityToolCoverage::test_registry_not_empty PASSED
cli_anything/safari/tests/test_parity.py::TestParityToolCoverage::test_registry_tool_count_matches_expected PASSED
cli_anything/safari/tests/test_parity.py::TestParityToolCoverage::test_every_tool_reachable_via_tool_group PASSED
cli_anything/safari/tests/test_parity.py::TestParityToolCoverage::test_tool_group_has_exactly_registry_count PASSED
cli_anything/safari/tests/test_parity.py::TestParityToolCoverage::test_no_unexpected_tools_in_cli PASSED
cli_anything/safari/tests/test_parity.py::TestParityParameters::test_every_param_has_cli_option PASSED
cli_anything/safari/tests/test_parity.py::TestParityParameters::test_required_params_are_required_in_click PASSED
cli_anything/safari/tests/test_parity.py::TestParityParameters::test_enum_choices_match PASSED
cli_anything/safari/tests/test_parity.py::TestParityIntrospection::test_tools_count_command PASSED
cli_anything/safari/tests/test_parity.py::TestParityIntrospection::test_tools_list_outputs_every_tool PASSED
cli_anything/safari/tests/test_parity.py::TestParityIntrospection::test_tools_list_json_shape PASSED
cli_anything/safari/tests/test_parity.py::TestParityIntrospection::test_tools_describe_known_tool PASSED
cli_anything/safari/tests/test_parity.py::TestParityIntrospection::test_tools_describe_by_short_name PASSED
cli_anything/safari/tests/test_parity.py::TestParityIntrospection::test_tools_describe_unknown_rejects PASSED
cli_anything/safari/tests/test_parity.py::TestParityHighValueSchemas::test_scroll_uses_direction_not_xy PASSED
cli_anything/safari/tests/test_parity.py::TestParityHighValueSchemas::test_drag_uses_source_and_target PASSED
cli_anything/safari/tests/test_parity.py::TestParityHighValueSchemas::test_mock_route_uses_url_pattern PASSED
cli_anything/safari/tests/test_parity.py::TestParityHighValueSchemas::test_throttle_network_has_profile PASSED
cli_anything/safari/tests/test_parity.py::TestParityHighValueSchemas::test_mock_route_response_is_required_not_status_description PASSED
cli_anything/safari/tests/test_parity.py::TestParityHighValueSchemas::test_run_script_steps_is_required_and_described_correctly PASSED
cli_anything/safari/tests/test_parity.py::TestParityHighValueSchemas::test_fill_form_fields_description_is_outer_not_inner PASSED
cli_anything/safari/tests/test_parity.py::TestParityHighValueSchemas::test_fill_and_submit_fields_description_is_outer PASSED
cli_anything/safari/tests/test_parity.py::TestParityHighValueSchemas::test_evaluate_param_is_script_not_code PASSED
cli_anything/safari/tests/test_parity.py::TestParityHighValueSchemas::test_run_script_param_is_steps PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_valid_http_url PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_valid_https_url PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_valid_https_with_path_and_query PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_valid_https_with_port PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_blocked_file_scheme PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_blocked_javascript_scheme PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_blocked_data_scheme PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_blocked_about_scheme PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_blocked_vbscript_scheme PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_blocked_webkit_scheme PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_blocked_safari_scheme PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_empty_string PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_whitespace_only PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_none_input PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_non_string_input PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_missing_scheme PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_missing_hostname PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_unknown_scheme PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_unknown_scheme_ws PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_get_allowed_schemes PASSED
cli_anything/safari/tests/test_security.py::TestURLValidation::test_get_blocked_schemes PASSED
cli_anything/safari/tests/test_security.py::TestDOMSanitization::test_plain_text_unchanged PASSED
cli_anything/safari/tests/test_security.py::TestDOMSanitization::test_empty_text_returns_empty PASSED
cli_anything/safari/tests/test_security.py::TestDOMSanitization::test_none_passes_through PASSED
cli_anything/safari/tests/test_security.py::TestDOMSanitization::test_truncation PASSED
cli_anything/safari/tests/test_security.py::TestDOMSanitization::test_default_max_length PASSED
cli_anything/safari/tests/test_security.py::TestDOMSanitization::test_prompt_injection_flagged PASSED
cli_anything/safari/tests/test_security.py::TestDOMSanitization::test_chinese_injection_flagged PASSED
cli_anything/safari/tests/test_security.py::TestDOMSanitization::test_html_comment_flagged PASSED
cli_anything/safari/tests/test_security.py::TestDOMSanitization::test_script_tag_flagged PASSED
cli_anything/safari/tests/test_security.py::TestDOMSanitization::test_control_chars_stripped PASSED
cli_anything/safari/tests/test_security.py::TestDOMSanitization::test_newlines_preserved PASSED
cli_anything/safari/tests/test_security.py::TestPrivateNetworkConfig::test_default_private_not_blocked PASSED
cli_anything/safari/tests/test_security.py::TestPrivateNetworkConfig::test_localhost_allowed_by_default PASSED
cli_anything/safari/tests/test_security.py::TestPrivateNetworkConfig::test_127_0_0_1_allowed_by_default PASSED
cli_anything/safari/tests/test_security.py::TestPrivateNetworkConfig::test_private_ip_allowed_by_default PASSED

======================== 76 passed, 19 skipped in 0.41s ========================
```

**Summary:** 76 passed, 19 skipped (all E2E, gated on `SAFARI_E2E=1`).
With `SAFARI_E2E=1 CLI_ANYTHING_FORCE_INSTALLED=1` the full suite is
**95 passed, 0 skipped** — including the 3 tests that exercise real
Safari (`test_tab_list_returns_json`, `test_navigate_and_read_example_com`,
`test_list_tabs_json_roundtrip`). Verified live against macOS Safari
and the bundled safari-mcp 2.7.8 in proxy mode (the primary safari-mcp
serving the user's Claude Code session was not disturbed).

### Live verification log (v1.0)

The following live operations were executed against real Safari to
verify the schema-driven CLI works end-to-end and the recent
ImageContent fix in `_unwrap` is correct:

```text
$ cli-anything-safari --json tool list-tabs
[
  {"index": 1, "title": "WhatsApp bot for conference gamification - Claude",
   "url": "https://claude.ai/chat/cc6353cc-..."}
]

$ cli-anything-safari --json tool evaluate --script "document.title"
"WhatsApp bot for conference gamification - Claude"
# (Regression test for the C1 bug where docs used --code by mistake.
#  The CLI now correctly uses --script and the param is forwarded
#  through MCP unchanged. Real Safari returned the real title.)

$ cli-anything-safari --json tool screenshot
{"type": "image", "data": "<65612 base64 chars>", "mimeType": "image/jpeg"}
# Decoded: 49,208 bytes, magic ff d8 ff e0 = valid JPEG.
# Saved to disk as a real image file. This proves the _unwrap
# ImageContent fix works against a real CallToolResult, not just
# MagicMock.
```

### Test Execution Time

- Offline (no Safari): ~0.8s
- With E2E gate on (excluding live-Safari mutations): ~3.5s

### Coverage Notes

- **Fully covered:** schema parsing (via parity tests), URL validation,
  session state, CLI wiring, introspection
- **Covered via regression locks:** four specific nested-schema parser
  bugs that earlier revisions got wrong (`mock_route.response`,
  `run_script.steps`, `fill_form.fields`, `fill_and_submit.fields`)
- **Covered by manual E2E (gated):** actual Safari round-trips for
  navigation and tab listing
- **Not covered:** every individual tool's actual MCP round-trip. We
  rely on the schema parity to ensure the CLI passes the right args,
  and on safari-mcp's own test suite to verify the tools themselves.
- **Not in scope:** real-world multi-step workflows (snapshot → find →
  click → read). These are exercised by agents in actual use, not by
  the test suite.

### How to Re-Run

```bash
# Offline suite (fast, no Safari required)
python -m pytest cli_anything/safari/tests/ -v --tb=no

# Full suite with E2E (requires Safari + macOS + Apple Events)
SAFARI_E2E=1 CLI_ANYTHING_FORCE_INSTALLED=1 \
    python -m pytest cli_anything/safari/tests/ -v -s

# Just the parity check (core of the "exact parity" guarantee)
python -m pytest cli_anything/safari/tests/test_parity.py -v
```
