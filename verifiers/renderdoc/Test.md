# RenderDoc Verifier Test Plan

## Module Overview

`verifiers/renderdoc/renderdoc.py` is a **multi-channel** verifier. It reads:

1. `~/.local/share/qrenderdoc/UI.config` — a flat JSON object written by
   qrenderdoc, containing keys like `UIStyle`, `Font_GlobalScale`,
   `RecentCaptureFiles`, `RecentCaptureSettings`, and many boolean toggles
   (`TextureViewer_ResetRange`, `Comments_ShowOnLoad`, ...).
2. `.rdc` capture files — parsed with `struct` over the first 32 bytes
   (FOURCC magic `RDOC`, serialise version, header length, progVersion),
   and via `renderdoccmd extract/thumb/convert` for structured inspection.
3. `.cap` capture-settings JSON — qrenderdoc writes these as JSON with
   `executable`, `workingDir`, `commandLine`, `environment`, `options`.
4. `renderdoccmd` subprocess — headless CLI that works without a display.
5. Install tree — plugin directory, Vulkan implicit layer registration.
6. Arbitrary filesystem paths — pathlib only.

The verifier never assumes qrenderdoc (the Qt GUI) can run. All fixtures are
synthesised by the test setup; qrenderdoc is not launched. Running on a
live sandbox is required because the tests invoke the verifier over
`sandbox.commands.run`.

Prerequisites: upload `renderdoc.py` to `/home/user/verifiers/renderdoc.py`
inside the `desktop-all-apps` template. `renderdoccmd` is already installed
at `/usr/local/bin/renderdoccmd` (v1.36) and needs no extra setup.

## Test Groups

### Group 1 — Help / Usage
- `renderdoc.py --help` exits 0 and prints "RenderDoc" banner.
- Expected assertions: 2.

### Group 2 — Errors: unknown command
- Unknown subcommand returns `{"error": ...}` and exits 1.
- Expected assertions: 2.

### Group 3 — Errors: missing arguments
- Subcommands with required args (`check-setting`, `check-rdc-valid`,
  `check-rdc-version`, `rdc-header`, `config-keys` is arg-less so skip,
  `check-theme`, `check-font-scale`, `check-recent-capture`,
  `list-captures`, `check-capture-count`, `check-file-exists`) return
  JSON error and exit 1 when called with no args.
- Expected assertions: 2 per command x ~10 commands = 20.

### Group 4 — UI.config query endpoints
- `config` full → dict containing `Font_GlobalScale`, `UIStyle`.
- `config Font_GlobalScale` → `{"key": "Font_GlobalScale", "value": 1.5}`.
- `config nonexistent_key` → error.
- `config-keys` → `count >= 8`.
- `theme` → `{"theme": "Dark"}`.
- `font-scale` → `{"scale": 1.5}`.
- `recent-captures` → `count >= 1`, list contains the fixture capture.
- `recent-settings` → list with `count >= 1`.
- Expected assertions: ~14.

### Group 5 — Check-setting positives
- `check-setting Font_GlobalScale 1.5` → match true (float parsed via JSON).
- `check-setting UIStyle "\"Dark\""` → match true (JSON-quoted string).
- `check-setting TextureViewer_ResetRange true` → match true (bool).
- `check-setting EventBrowser_AddFake false` → match true (bool override).
- `check-setting-exists Font_GlobalScale` → exists true.
- `check-theme Dark` → match true.
- `check-font-scale 1.5` → match true.
- `check-recent-capture triangle.rdc` → found true.
- Expected assertions: 8.

### Group 6 — Check-setting negatives
- `check-setting Font_GlobalScale 2.0` → match false, actual 1.5.
- `check-setting UIStyle "\"Light\""` → match false.
- `check-setting TextureViewer_ResetRange false` → match false.
- `check-setting-exists NonExistentKey` → exists false.
- `check-theme Light` → match false.
- `check-font-scale 2.0` → match false.
- `check-recent-capture not_a_real_capture_xyz` → found false.
- Expected assertions: 7.

### Group 7 — `.rdc` header parsing
- `rdc-header /home/user/captures/triangle.rdc` → `valid: true`, magic `RDOC`,
  serialise_version == 258, header_length == 32, prog_version contains `v1.`.
- `rdc-header /home/user/captures/corrupt.bin` → error (bad magic).
- `rdc-header /home/user/captures/tiny.rdc` → error (file too short).
- `rdc-header /nonexistent/missing.rdc` → error.
- Expected assertions: 9.

### Group 8 — `check-rdc-valid` positive + negative
- Valid capture → `valid: true`.
- Corrupt file → `valid: false`.
- Missing file → `valid: false`.
- Empty-file edge → `valid: false`.
- Expected assertions: 4.

### Group 9 — `check-rdc-version`
- Valid capture with version `258` → match true.
- Valid capture with version `0x102` → match true.
- Valid capture with version `999` → match false.
- Valid capture with version `notanumber` → match false + error.
- Expected assertions: 4.

### Group 10 — Directory listing / capture counting
- `list-captures /home/user/captures` → count 2 (triangle.rdc + second.rdc),
  corrupt.bin excluded because extension != .rdc; per-entry valid flag set
  correctly.
- `check-capture-count /home/user/captures 2` → match true.
- `check-capture-count /home/user/captures 5` → match false.
- `check-capture-count /nonexistent/dir 0` → match false + error.
- `list-captures /nonexistent/dir` → error.
- Expected assertions: 7.

### Group 11 — File existence helpers
- `check-file-exists /home/user/captures/triangle.rdc` → exists true, is_file true.
- `check-file-exists /home/user/captures` → exists true, is_dir true.
- `check-file-exists /nope/missing` → exists false.
- `file-info /home/user/captures/triangle.rdc` → same shape.
- Expected assertions: 7.

### Group 12 — renderdoccmd (install metadata)
- `rdcmd-available` → `available: true`, path under `/usr/local/bin` or `/opt`.
- `rdcmd-version` → parses `version` matching `1.xx`, `apis` non-empty list.
- `check-rdcmd-version 1.` → match true (prefix match tolerant of any 1.x).
- `check-rdcmd-version 99.9` → match false.
- `rdcmd-plugins` → `count >= 1` OR `plugins_dir is None` (install-layout
  dependent; accept either, but shape must always be a dict with `count`).
- `check-rdcmd-plugin spirv` → either `present: true` (if the plugin dir is
  present) or `present: false` (gracefully); not a crash.
- `vulkan-layer-status` → dict with `registered` boolean, `layer_files` list.
- Expected assertions: ~9.

### Group 13 — .rdc structured inspection (synthetic captures)
The fixtures in this suite are header-only synthetic captures; `renderdoccmd`
refuses to fully decode them, so every endpoint should return an **error**
dict (graceful) rather than crash:
- `rdc-sections /home/user/captures/triangle.rdc` → either returns `sections`
  list with `count >= 0` OR `error` key; must be valid JSON.
- `rdc-convert-xml /home/user/captures/triangle.rdc` → `error` set (not a
  crash), still valid JSON.
- `check-rdc-api /home/user/captures/triangle.rdc Vulkan` → `match: false`,
  no crash.
- `check-rdc-min-chunks /home/user/captures/triangle.rdc 1` → `match: false`,
  no crash.
- `check-rdc-has-thumbnail /home/user/captures/triangle.rdc` →
  `has_thumbnail: false`, no crash.
- `check-rdc-has-section /home/user/captures/triangle.rdc Thumbnail` →
  shape has `present` key (likely false), no crash.
- `rdc-thumb /home/user/captures/triangle.rdc /tmp/_t.png` → `extracted: false`
  but returns a dict (no crash).
- Expected assertions: ~10.

### Group 14 — .cap capture-settings JSON
Fixture `preset.cap` at `/home/user/captures/preset.cap` contains:
```
{"rdocCaptureSettings": 1, "settings": {"executable": "/usr/bin/glxgears",
 "workingDir": "/home/user", "commandLine": "--iters 100",
 "environment": [{"name": "VK_LAYER_PATH", "value": "/tmp", "separator": "Platform",
                  "mod": "Replace"}],
 "options": {"APIValidation": true, "CaptureCallstacks": false,
             "CaptureAllCmdLists": true, "DebugOutputMute": false,
             "HookIntoChildren": true, "RefAllResources": false},
 "autoStart": true, "queueFrameCap": 0, "numQueuedFrames": 0}}
```
- `cap-parse` → returns correct `executable`, `workingDir`, `commandLine`.
- `check-cap-executable /usr/bin/glxgears` → match true.
- `check-cap-executable /bin/wrong` → match false.
- `check-cap-working-dir /home/user` → match true.
- `check-cap-command-line --iters` → match true (substring).
- `check-cap-command-line no-such-arg` → match false.
- `check-cap-option APIValidation true` → match true.
- `check-cap-option APIValidation false` → match false.
- `check-cap-option CaptureCallstacks false` → match true (bool false).
- `check-cap-option NotARealOption true` → match false + error.
- `check-cap-env VK_LAYER_PATH` → present true.
- `check-cap-env NOT_SET` → present false.
- `cap-parse /nope/missing.cap` → error.
- Expected assertions: ~14.

### Group 15 — JSON validity sweep
- Every CLI command (with realistic args where needed) outputs parseable JSON
  regardless of exit code.
- Expected assertions: ~20 (one per command).

## Test Fixtures

All fixtures are created inside the sandbox during setup. No external files
or downloads. Paths below are absolute on the sandbox.

| Path | Format | Purpose |
|---|---|---|
| `/home/user/.local/share/qrenderdoc/UI.config` | JSON (top-level flat dict) | Exercises all UI.config endpoints. Contains `rdocConfigData: 1`, `Font_GlobalScale: 1.5`, `UIStyle: "Dark"`, `TextureViewer_ResetRange: true`, `EventBrowser_AddFake: false`, `Comments_ShowOnLoad: true`, `Font_PreferMonospaced: false`, `RecentCaptureFiles: ["/home/user/captures/triangle.rdc", "/home/user/captures/second.rdc"]`, `RecentCaptureSettings: ["/home/user/captures/triangle.cap"]`. |
| `/home/user/captures/triangle.rdc` | 64-byte synthetic RDC | Magic `RDOC`, version `0x102`, headerLength 32, progVersion `v1.36 abcdef`. 32 extra bytes after header as padding. Used for `rdc-header`, `check-rdc-valid`, `check-rdc-version`, list-captures (valid entry). |
| `/home/user/captures/second.rdc` | 40-byte synthetic RDC | Same format, different progVersion, to assert list-captures counts two. |
| `/home/user/captures/corrupt.bin` | 64 bytes of `0xFF` | Wrong magic, wrong extension — should not appear in list-captures. |
| `/home/user/captures/tiny.rdc` | 8 random bytes | File shorter than 32-byte header, tests "too short" error. Included in list-captures (extension matches) with `valid: false`. |
| `/home/user/captures/triangle.cap` | 8 bytes | Dummy capture-settings file referenced by UI.config (validates `file-info` only). |
| `/home/user/captures/preset.cap` | JSON | Full capture-settings fixture; drives every `cap-*` and `check-cap-*` endpoint. |

## Edge Cases & Error Handling Matrix

| Scenario | Endpoint(s) | Expected |
|---|---|---|
| UI.config missing | `config`, `config-keys`, `check-setting`, `theme`, `font-scale`, `recent-captures` | `{"error": ...}`, no crash |
| UI.config not JSON | `config` | `{"error": "Invalid JSON..."}` |
| Unknown config key | `config <key>`, `check-setting-exists` | `exists: false` / error dict |
| Path not a file | `rdc-header`, `check-rdc-valid` | error |
| Path is directory | `check-file-exists` | `exists: true, is_dir: true` |
| Nonexistent directory | `list-captures`, `check-capture-count` | `{"error": ...}` with match false |
| Bad version argument | `check-rdc-version` | `match: false`, error message |
| Float comparison sentinel | `check-font-scale` | float tolerance 1e-6 |
| Unknown subcommand | any | exit 1, valid JSON error |
| Missing required arg | any arg-taking command | exit 1, valid JSON error |
| Empty UI.config file | `config` | returns `{}` (no error) |

## Positive / Negative Case Pairs

| Endpoint | Positive | Negative |
|---|---|---|
| `check-setting` | `Font_GlobalScale 1.5` → true | `Font_GlobalScale 2.0` → false |
| `check-setting-exists` | `Font_GlobalScale` → true | `NotAKey` → false |
| `check-theme` | `Dark` → true | `Light` → false |
| `check-font-scale` | `1.5` → true | `2.0` → false |
| `check-recent-capture` | `triangle.rdc` → true | `xyz_missing` → false |
| `check-rdc-valid` | `triangle.rdc` → true | `corrupt.bin` → false |
| `check-rdc-version` | `triangle.rdc 258` → true | `triangle.rdc 999` → false |
| `check-capture-count` | `<dir> 3` → true (triangle+second+tiny) | `<dir> 99` → false |
| `check-file-exists` | `triangle.rdc` → true | `/nope/missing` → false |

Note on capture-count: `list-captures` matches `*.rdc` extensions, so
`triangle.rdc`, `second.rdc`, and `tiny.rdc` all count (3). `corrupt.bin` is
excluded.

## JSON Validity Sweep

Commands exercised in the final sweep (all must output parseable JSON):

- `config`
- `config Font_GlobalScale`
- `config-keys`
- `check-setting Font_GlobalScale 1.5`
- `check-setting-exists Font_GlobalScale`
- `theme`
- `check-theme Dark`
- `font-scale`
- `check-font-scale 1.5`
- `recent-captures`
- `check-recent-capture triangle.rdc`
- `recent-settings`
- `rdc-header /home/user/captures/triangle.rdc`
- `check-rdc-valid /home/user/captures/triangle.rdc`
- `check-rdc-version /home/user/captures/triangle.rdc 258`
- `list-captures /home/user/captures`
- `check-capture-count /home/user/captures 3`
- `check-file-exists /home/user/captures/triangle.rdc`
- `file-info /home/user/captures/triangle.rdc`
- `nonexistent-command` (must still emit JSON error)

## Summary

| Metric | Count |
|---|---|
| Test groups | 12 |
| Total assertions | ~110 |
| Test fixtures (files generated) | 6 |
| `check-*` endpoints with pos+neg pairs | 9 |
| Error scenarios covered | 11 |
