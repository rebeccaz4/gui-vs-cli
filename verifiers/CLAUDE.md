# syn_env — RL/Evaluation Desktop Sandbox Environment

## What This Folder Does

Provides **verifier modules** (`verifiers/<app>/`) that a verification agent can call to check whether a GUI task was completed correctly.

## Existing Files

- `gui_agent.py` — LLM agent loop (Claude computer-use + E2B sandbox)
- `computer_env/backends/e2b/sandbox_cli.py` — CLI to create/resume sandboxes from snapshots
- `computer_env/provision/e2b/build_all_apps_template.py` — builds the `desktop-all-apps` E2B template
- `apps_to_include.json` — app inventory
- `app_verifiability_report.md` — per-app verification channels and APIs
- `verifiers/` — verifier modules (one folder per app)

## Building a Verifier Module

Each verifier lives at `verifiers/<app>/` and contains:

```
verifiers/<app>/
├── <app>.py      # The verifier — CLI endpoints + Python class
├── README.md     # Documentation for the verification agent
├── Test.md       # Test plan — coverage matrix, fixtures, edge cases
└── test_<app>.py # Tests that run in a live E2B sandbox
```

### 1. Generate Endpoints (`<app>.py`)

The verifier is a Python script that runs **inside the sandbox** via `sandbox.commands.run()`. It exposes CLI subcommands that return JSON. Each subcommand is an endpoint.

The verification agent calls them like:
```python
result = sandbox.commands.run("python3 /home/user/verifiers/chrome.py check-tab-open github.com")
data = json.loads(result.stdout)
reward = 1.0 if data["found"] else 0.0
```

Key requirements:
- Every endpoint returns JSON to stdout
- Errors are returned as `{"error": "..."}`, not crashes
- `check-*` endpoints return a dict with **one primary boolean key** (the reward signal) plus context
- Use the best verification channel available for the app, prefer to use existing tools than writing your own tool (CDP, D-Bus, UNO, file parsing, etc.)
- Prefer stdlib. Copy SQLite DBs before reading (apps lock them)

Use `verifiers/chrome/chrome.py` as the reference implementation.

#### Endpoint Categories

A verifier should be as comprehensive as possible. Don't just cover the app's primary function — cover every inspectable surface that an RL task might ask an agent to change. Think about what a human QA tester would check after completing a task.

Design endpoints across **all** of the following categories that apply to the app:

**1. Core content / document state** — The app's primary data. Spreadsheet cells, browser page content, editor text buffers, image layers, playlist items, note content, etc. Include both live queries (via IPC) and offline file parsing (reading saved files directly) when the app supports both channels.

**2. Settings, preferences, and configuration** — Almost every app has user-configurable settings. These are high-value RL tasks ("change the font size to 14", "enable dark mode", "set auto-save to 5 minutes"). Expose endpoints to read individual settings and list all settings. Cover:
  - User preferences
  - Per-workspace / per-project settings if the app has them
  - Theme and appearance settings
  - Editor behavior settings (tab size, word wrap, line numbers, auto-save)
  - Privacy/security settings (do-not-track, cookie policies, telemetry toggles)
  - Accessibility settings (font scaling, high contrast, screen reader support)

**3. Keybindings and shortcuts** — Apps with customizable keybindings (VS Code, Sublime, terminal emulators, etc.) should expose endpoints to read and verify keybinding configurations. Tasks like "set Ctrl+Shift+P to open terminal" are common.

**4. Extensions, plugins, and packages** — If the app has an extension/plugin system, expose listing installed extensions and checking whether a specific one is installed/enabled. Covers browser extensions, editor packages, GIMP plugins, etc.

**5. UI layout and window state** — Current window/tab arrangement, sidebar visibility, panel positions, split views, zoom level, fullscreen state. Inspect via session files, window manager hints, or the app's own API.

**6. Navigation and history** — Browser history, recently opened files/projects, undo history, command history. These are often stored in SQLite databases or flat files in the app's profile directory.

**7. Bookmarks and favorites** — Browser bookmarks, file manager bookmarks (GTK bookmarks), editor project bookmarks, note pinning. Both listing all bookmarks and checking if a specific one exists.

**8. File I/O and persistence** — Check whether a file was saved, what format it's in, when it was last modified. Verify file exists on disk, check file contents, compare file size. Relevant for nearly every app.

**9. Network and connection state** — For apps with network features: cookies, active connections, download status, sync state, proxy settings, remote debugging ports.

**10. Project / workspace structure** — IDE workspace folders, open projects, task/launch configurations, build systems, associated files. These define multi-file task contexts.

**11. Media and playback state** — For media apps: current position, volume, playback speed, loaded media, playlist order, A/V format details, audio tracks, subtitles. Query via HTTP API, D-Bus/MPRIS, or direct file probing (ffprobe).

**12. Visual / graphical state** — Image dimensions, color mode, resolution/DPI, layer count and names, pixel colors, color profiles, histograms. For drawing apps: shape types, positions, text content, connector relationships, page/slide counts.

**13. Metadata and properties** — Document properties (title, author, creation date), EXIF/XMP data on images, ID3 tags on audio, file-level metadata the app exposes.

Not every category applies to every app — a calculator doesn't need history endpoints, and a media player doesn't need document state. But use this list as a checklist and consciously decide which categories are relevant. The most commonly missed categories are **settings/preferences** and **UI layout** — these power a large class of RL tasks that don't involve the app's primary document content.

**Skip categories the app cannot expose.** Some apps simply don't provide a way to read certain state programmatically — no API, no config file on disk, no D-Bus interface, no parseable session file. If the app's available verification channels (CDP, D-Bus, UNO, file parsing, AT-SPI, etc.) cannot access a category of state, do not build endpoints for it. An endpoint that can't reliably read the actual app state is worse than no endpoint — it produces false verification results. Before implementing a category, confirm that at least one verification channel can actually reach the data. Document skipped categories and the reason (e.g. "UI layout: skipped — no session file or API exposes sidebar/panel state") in the README so the task generator knows not to create tasks for those areas.

### 2. Generate Documentation (`README.md`)

This is what the verification agent reads to know what endpoints are available and how to use them. It must include:

- **Prerequisites**: how to launch the app with inspection enabled (e.g. `--remote-debugging-port=9222`)
- **Endpoint reference**: every subcommand with its arguments, what it returns, and an example
- **Common verification patterns**: copy-paste examples for typical RL tasks (e.g. "check if user navigated to X", "check if file was saved")

The README should be complete enough that an agent can use the verifier without reading the source code.

### 3. Generate Test Plan (`Test.md`)

Before writing any test code, create a `Test.md` planning document in `verifiers/<app>/`. This ensures comprehensive coverage by forcing you to think through all scenarios before implementation.

The file structure becomes:

```
verifiers/<app>/
├── <app>.py
├── README.md
├── Test.md        # Test plan (this step)
└── test_<app>.py  # Test code (next step)
```

`Test.md` must contain the following sections:

#### 3a. Module Overview

State what the verifier does, which verification channels it uses (CDP, D-Bus, UNO, file parsing, etc.), and any prerequisites (e.g. app must be launched with specific flags).

#### 3b. Test Groups

For each logical group of tests, describe:

- **Group name** — e.g. "Help/Usage", "Error Handling (app not running)", "CDP Endpoints", "Check-* Positive Cases"
- **What is being tested** — the specific endpoints or behaviors under test
- **Edge cases to cover** — invalid inputs, missing arguments, boundary conditions, app not running, wrong types, nonexistent paths/IDs, empty state, etc.
- **Expected test count** — how many individual `check()` assertions the group will contain

#### 3c. Test Fixtures

**Generate many, comprehensive test files.** Test quality is directly limited by the richness of the test data. A single simple fixture is not enough — you need enough files to cover the full surface area of every endpoint. Plan fixtures that are dense with varied content so each file exercises as many code paths as possible.

List every file, directory structure, config, or in-sandbox artifact that tests will create. For each fixture:

- **File path** in the sandbox (e.g. `/home/user/test_verifier.odg`)
- **Format and contents** — what the file contains and why (e.g. "ODG with 2 pages, 3 shapes on page 0, 1 shape on page 1 — tests multi-page and shape counting")
- **Which test groups use it** — so you can verify every fixture is actually exercised

If the app uses file-based verification (parsing ODF, SQLite DBs, config files, etc.), the fixtures should include multiple formats or content variations that exercise different code paths.

**Fixture richness guidelines:**
- Each fixture file should pack in as many **distinct data types, content variations, and structural features** as is realistic for the format. For example, a spreadsheet fixture shouldn't just have a few text cells — it should include strings, integers, floats, dates, booleans, formulas, empty cells, merged cells, cells with comments, hyperlinks, styled cells, conditional formatting, named ranges, etc.
- Create **multiple fixture files** when a single file can't cover all scenarios — e.g. one document in the app's native format, one in an import format, one that is empty/minimal, one that is large/complex.
- Fixtures should include content that supports **both positive and negative test cases** for every `check-*` endpoint. If a check verifies whether bold formatting exists, the fixture needs both bold and non-bold text.
- Think of fixtures as the **training data for the test suite** — if the fixture is shallow, the tests will be shallow, and real bugs will slip through.

#### 3d. Edge Cases & Error Handling Matrix

A table or list covering every error scenario:

| Scenario | Endpoint(s) | Expected behavior |
|---|---|---|
| App not running | all live endpoints | `{"error": "..."}`, no crash |
| Missing required argument | `check-*` endpoints | exit 1 + valid error JSON |
| Unknown subcommand | any | exit 1 + valid error JSON |
| Nonexistent file/path | file-based endpoints | `{"error": "..."}` |
| Wrong argument type | endpoints with numeric args | `{"error": "..."}` or graceful coercion |
| Empty state | list/query endpoints | empty list/dict, not crash |

#### 3e. Positive / Negative Case Pairs

Every `check-*` endpoint must list both:

- **Positive case**: what input makes it return `true`, and what fixture provides that state
- **Negative case**: what input makes it return `false`, and why it's a meaningful negative (not just "wrong random string" — also things like checking a file that exists but is a directory, checking for content that's close but not exact, etc.)

#### 3f. JSON Validity Sweep

List all CLI subcommands (with and without arguments) that will be tested for valid JSON output. This should be an exhaustive list of every endpoint the verifier exposes.

#### 3g. Summary

| Metric | Count |
|---|---|
| Test groups | N |
| Total assertions | N |
| Test fixtures (files generated) | N |
| `check-*` endpoints with pos+neg pairs | N |
| Error scenarios covered | N |

This planning document ensures comprehensive test coverage before writing code. Review it against the endpoint list in `README.md` — every endpoint must appear in at least one test group, and every `check-*` endpoint must have both positive and negative cases.

### 4. Generate Tests and Fix Until Passing (`test_<app>.py`)

Implement the test plan from `Test.md`. Every test group, fixture, and edge case described in the plan must appear in the test code. If you discover gaps during implementation, update `Test.md` first, then write the code.

Tests run against a **live E2B sandbox**. They must:

- Create a sandbox from `desktop-all-apps`
- Upload the verifier to `/home/user/verifiers/<app>.py`
- Launch the app with the right flags
- Test every endpoint: raw state, queries, and `check-*` methods
- Test both positive cases (check returns true) and negative cases (check returns false)
- Test error cases (app not running, bad arguments)
- Verify all output is valid JSON
- Clean up (kill sandbox)

Run with: `python verifiers/<app>/test_<app>.py`

**Critical: debug-fix-retry loop.** After running tests, if any test fails:

1. Read the error output carefully (stderr, wrong JSON shape, unexpected values, connection refused, etc.)
2. Diagnose the root cause — is it the endpoint code, the app launch flags, a missing dep, a wrong path, a timing issue?
3. Fix the endpoint in `<app>.py` (and update `README.md` if the interface changed)
4. Re-run the failing tests
5. Repeat until all tests pass, or repeated until maximum 5 times retry.

Do NOT move on to the next app until the current verifier's tests are all green. The endpoints are useless to the verification agent if they don't actually work in the sandbox environment.

### Test Design Guidelines

#### Test against the live app, not just offline parsing

If the verifier has multiple channels (e.g. live API + file parsing), test both. The live app may return different types, enums, or data shapes than what offline parsing produces. Always test with the app actually running in the sandbox.

#### Use the same file formats agents will use

Test with the file formats that tasks will actually provide. Different formats can have different internal structures, reference syntax, and parser behavior. Don't assume a fallback channel handles all formats.

#### Never assume IPC return types

App APIs (D-Bus, UNO, WebSocket, AT-SPI, CDP) may return wrapper types (Enums, proxy objects) instead of plain Python types. Don't compare with `== int` or call `int()` on them — convert via `str()` and match on the string, or use documented accessor methods. Always handle the actual runtime types, not what the docs say they should be.

#### Test every CLI argument combination

If an endpoint accepts optional parameters, wire them all through the CLI dispatch and test them from the command line. A working Python API method is useless if the CLI layer doesn't pass arguments through correctly.

#### Generate diverse, data-rich test fixtures

The number-one cause of weak test suites is thin test data. **Invest heavily in fixture generation** — create files that are dense with varied content, not minimal toy examples. The goal is to exercise every code path in every endpoint with realistic, heterogeneous data.

Create test data that exercises multiple code paths — not just the happy path. Include:
- Multiple documents / containers / tabs (not just one)
- Mixed data types in the same context (e.g. for a word processor: paragraphs, headings, lists, tables, images, footnotes, headers/footers, page breaks, comments, tracked changes, hyperlinks, bookmarks, fields, styled and unstyled text, multiple fonts/sizes/colors)
- Computed / derived state (formulas, macros, linked content) — not just static values
- Both styled and unstyled elements
- Cross-reference between containers
- Edge cases: empty state, minimal input, boundary values
- **Multiple file formats** where the app supports them (native, import, export)
- **Documents at different scales** — an empty document, a typical document, and a complex multi-page/multi-sheet document

If generating fixtures programmatically (e.g. via UNO, python-docx, openpyxl), take advantage of the API to insert a wide variety of content types in a single fixture. Don't settle for a file with three cells or two paragraphs when the API lets you build a rich document in a few extra lines of code.

#### Test both positive and negative cases

Every `check-*` endpoint needs tests where the condition is true AND where it's false. A check that always returns true (or always returns false) is a bug that only shows up if you test both sides.
