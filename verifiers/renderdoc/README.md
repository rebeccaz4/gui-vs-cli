# RenderDoc Verifier

Programmatic state inspection for RenderDoc in the `desktop-all-apps` E2B
sandbox. qrenderdoc (the Qt GUI) does not launch reliably in the headless
sandbox, so this verifier never assumes the GUI is running. It reads state
through three independent channels that all work without a display:

## Verification Channels

| Channel | Source | Used for |
|---------|--------|----------|
| UI.config JSON | `~/.local/share/qrenderdoc/UI.config` | Theme, font scale, recent captures, toggle settings |
| `.rdc` header parsing | first 32 bytes of any `.rdc` file | Validity, serialise version, prog version, file size |
| `renderdoccmd` subprocess | `renderdoccmd version / extract / thumb / convert` | Build info, embedded sections, thumbnails, structured XML dump |
| `.cap` capture-settings JSON | `.cap` files (JSON) written by qrenderdoc | executable, commandLine, workingDir, options, environment |
| Install tree inspection | `/opt/renderdoc*/share/renderdoc/plugins`, Vulkan implicit layer JSON | Plugin inventory, layer registration |
| Filesystem stats | `pathlib` over arbitrary paths | File/dir existence, size, capture counts |

`UI.config` looks like a Qt `.config` file but is actually a flat JSON object
written by qrenderdoc (`SaveToJSON` in `qrenderdoc/Code/QRDUtils.cpp`). Every
`CONFIG_SETTING_VAL(...)` macro in `PersistantConfig.h` becomes a top-level
key such as `Font_GlobalScale`, `UIStyle`, `RecentCaptureFiles`, or
`TextureViewer_ResetRange`.

`.rdc` capture files begin with a 32-byte `FileHeader` (see
`renderdoc/serialise/rdcfile.cpp`):

```
offset  size  field
0       8     magic       uint64 little-endian; low 4 bytes = b"RDOC"
8       4     version     uint32 (0x00000102 at v1.36)
12      4     headerLength uint32
16     16     progVersion char[16] (e.g. b"v1.36 abcdef\0\0\0")
```

This is enough to verify authenticity and version without needing the (not
shipped) Python `renderdoc` module.

## Skipped Categories

The verifier intentionally does not cover these areas because no headless
channel reliably exposes them:

- **Live GUI state / docks / window layout** — qrenderdoc cannot launch, and
  layout state is only persisted as opaque Qt byte blobs.
- **Full replay-time state (shader disassembly, texture pixels, draw state)**
  — requires loading the capture into a GPU replay context. The headless
  `renderdoccmd convert` flow exposes structured metadata (chunks, events,
  resources, API) but not full replay details.
- **Keybindings / custom shortcuts** — qrenderdoc does not expose custom
  keybindings in `UI.config`.
- **Live Python extensions** — enumerating loaded Python extensions requires
  a running qrenderdoc instance. The install-tree plugin directory (`amd`,
  `android`, `spirv`) IS exposed via `rdcmd-plugins`.

Document any new task that needs those surfaces back to the task generator
with "unverifiable — no endpoint" rather than silently accepting.

## Prerequisites

None on the sandbox side. The verifier is pure stdlib Python. Upload it to
`/home/user/verifiers/renderdoc.py` and call it with `python3`.

If you want to test against a real UI.config/ .rdc, write them yourself (the
tests do exactly that) — do **not** rely on qrenderdoc generating them, it
crashes on launch.

## Endpoint Reference

All endpoints print JSON to stdout. Failures return `{"error": "..."}`.
`check-*` endpoints additionally include **one primary boolean key** (`match`,
`valid`, `exists`, `found`) that is the reward signal.

UI.config parsing is tolerant to stray non-whitespace control characters that
GUI text editors (gedit, etc.) sometimes leave in the file after Find/Replace
edits. `_read_json_file` first tries `json.loads(content, strict=False)` and,
on `JSONDecodeError`, retries once after stripping any character whose
`ord() < 0x20` that is not `\t`, `\n`, or `\r`. Only if the sanitized retry
also fails does it return `{"error": "Invalid JSON ..."}`.

### `config [key]`
Read UI.config in full, or a single key.
```bash
python3 /home/user/verifiers/renderdoc.py config
python3 /home/user/verifiers/renderdoc.py config Font_GlobalScale
```
```json
{"key": "Font_GlobalScale", "value": 1.5}
```

### `config-keys`
List all top-level keys in UI.config.
```json
{"keys": ["Font_GlobalScale", "RecentCaptureFiles", "UIStyle"], "count": 3}
```

### `check-setting <key> <expected>`
Check a UI.config key matches an expected value. The expected value is parsed
as JSON first (so `true`/`false`, integers, floats, and quoted strings all
work). Returns `match`.
```bash
python3 /home/user/verifiers/renderdoc.py check-setting Font_GlobalScale 1.5
python3 /home/user/verifiers/renderdoc.py check-setting TextureViewer_ResetRange true
python3 /home/user/verifiers/renderdoc.py check-setting UIStyle '"Dark"'
```

### `check-setting-exists <key>`
Check whether a key is present in UI.config at all.

### `theme` / `check-theme <expected>`
Shortcut for `UIStyle`. Valid renderdoc values include `""`, `"Default"`,
`"Light"`, `"Dark"`.

### `font-scale` / `check-font-scale <expected>`
Shortcut for `Font_GlobalScale`. Float comparison with 1e-6 tolerance.

### `recent-captures`
Return the `RecentCaptureFiles` list.
```json
{"files": ["/home/user/captures/triangle.rdc"], "count": 1}
```

### `check-recent-capture <substring>`
Check that at least one entry in `RecentCaptureFiles` contains the substring.
Returns `found`.

### `recent-settings`
Return the `RecentCaptureSettings` list (`.cap` capture-settings files).

### `rdc-header <path>`
Parse the first 32 bytes of a `.rdc` file. Returns magic, serialise_version,
header_length, prog_version, size. Includes `valid: true` on success.

### `check-rdc-valid <path>`
One-shot validity check on a `.rdc` file. Returns `valid`.

### `check-rdc-version <path> <expected_version>`
Check `serialise_version` of a capture. Accepts decimal (`258`) or hex (`0x102`).

### `list-captures <directory>`
List every `.rdc` file in a directory, with per-file validity.

### `check-capture-count <directory> <expected_int>`
Check the number of `.rdc` files in a directory.

### `check-file-exists <path>` / `file-info <path>`
Generic filesystem helper. Returns `exists`, `is_file`, `is_dir`, `size`.

### `rdcmd-available`
Check whether `renderdoccmd` can be found on PATH or under `/opt/renderdoc*`.
```json
{"available": true, "path": "/usr/local/bin/renderdoccmd"}
```

### `rdcmd-version`
Run `renderdoccmd version` and parse out `version`, `git_sha`, supported APIs.
```json
{"version": "1.36", "git_sha": "abcdef0", "apis": ["GL", "GLES", "Vulkan"], ...}
```

### `check-rdcmd-version <expected>`
Checks the parsed version **starts with** the expected prefix (e.g. `1.36`).

### `rdcmd-plugins`
Enumerate the plugin subdirectories shipped with the renderdoc install
(`amd`, `android`, `spirv` on 1.36).

### `check-rdcmd-plugin <name>`
Check a specific plugin directory is present.

### `vulkan-layer-status`
Return any `renderdoc_capture.json` implicit-layer JSON files found under
`/opt`, `/usr/share`, `/etc`, or `~/.local/share/vulkan`.

### `rdc-sections <path>`
Run `renderdoccmd extract --list-sections PATH`; returns the list of
embedded section names (`Thumbnail`, `ResolveDatabase`, `EmbeddedLogs`, ...).

### `check-rdc-has-section <path> <name>`
Case-insensitive substring match on `rdc-sections` output.

### `rdc-thumb <path> <out_path>`
Extract the embedded thumbnail to `<out_path>`. Returns `extracted`, `size`,
and sniffed `format` (`png` / `jpg` / `bmp`).

### `check-rdc-has-thumbnail <path>`
Boolean wrapper around `rdc-thumb` using a temp output path.

### `rdc-convert-xml <path> [out_path]`
Run `renderdoccmd convert -c xml` and summarise the XML. Returns counts for
`chunks`, `events`, `resources`, `actions` plus the detected `api`.

### `check-rdc-api <path> <expected>`
Parse the structured XML; match the capture's API (case-insensitive).
Accepts `Vulkan`, `GL`, `GLES`, `D3D11`, `D3D12`, `OpenGL`.

### `check-rdc-min-chunks <path> <minimum>`
Assert the capture has at least `<minimum>` `<chunk>` entries in its XML.

### `cap-parse <path>`
Parse a qrenderdoc `.cap` capture-settings JSON file. Returns
`executable`, `workingDir`, `commandLine`, `environment`, `options`,
`autoStart`, `queueFrameCap`, `numQueuedFrames`, plus the raw JSON.

### `check-cap-executable <path> <expected>`
### `check-cap-working-dir <path> <expected>`
### `check-cap-command-line <path> <substring>`
### `check-cap-option <path> <key> <expected>`
Exact-match checks on `.cap` fields. For `check-cap-option`, the `<expected>`
arg is parsed as JSON (so `true`/`false`/numbers/quoted strings all work).

### `check-cap-env <path> <var_name>`
Check whether a named environment variable is set in the `environment` list
(supports both dict-form entries `{"name": "VAR", ...}` and `VAR=VALUE` strings).

## Common Verification Patterns

### "The user changed the dark theme"
```json
{"command": "check-theme Dark", "key": "match", "expected": true}
```

### "The user set font scaling to 1.5"
```json
{"command": "check-font-scale 1.5", "key": "match", "expected": true}
```

### "The user enabled TextureViewer_ResetRange"
```json
{"command": "check-setting TextureViewer_ResetRange true", "key": "match", "expected": true}
```

### "The user opened (or recently-added) a specific capture"
```json
{"command": "check-recent-capture triangle.rdc", "key": "found", "expected": true}
```

### "The capture file exists and is a real .rdc"
```json
{"command": "check-rdc-valid /home/user/captures/frame.rdc", "key": "valid", "expected": true}
```

### "There are exactly 3 captures in the project directory"
```json
{"command": "check-capture-count /home/user/captures 3", "key": "match", "expected": true}
```

### "The user installed renderdoc 1.36 successfully"
```json
{"command": "check-rdcmd-version 1.36", "key": "match", "expected": true}
```

### "A .cap preset was saved for /usr/bin/glxgears"
```json
{"command": "check-cap-executable /home/user/captures/gears.cap /usr/bin/glxgears", "key": "match", "expected": true}
```

### "The user enabled API validation in the capture preset"
```json
{"command": "check-cap-option /home/user/captures/preset.cap APIValidation true", "key": "match", "expected": true}
```

### "The capture contains an embedded thumbnail"
```json
{"command": "check-rdc-has-thumbnail /home/user/captures/frame.rdc", "key": "has_thumbnail", "expected": true}
```

### "The capture was recorded against Vulkan"
```json
{"command": "check-rdc-api /home/user/captures/frame.rdc Vulkan", "key": "match", "expected": true}
```

### "The vulkan capture layer is registered"
```json
{"command": "vulkan-layer-status", "key": "registered", "expected": true}
```
