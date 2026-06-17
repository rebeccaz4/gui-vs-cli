# LibreOffice Impress Verifier

Programmatic state inspection for LibreOffice Impress presentations in E2B sandbox.
Used by a **check agent** to generate reward signals for RL/evaluation.

## Prerequisites

Launch LibreOffice Impress with UNO socket listener enabled:

```bash
soffice --impress --accept="socket,host=localhost,port=2002;urp;" --norestore &
```

For file-based verification (ODF parsing), no running instance is needed — just a saved `.odp` file.

## Verification Channels

| Channel | When to use | Needs running LO? |
|---------|-------------|-------------------|
| **UNO API** | Live slides, shapes, text, transitions, notes | Yes |
| **ODF parsing** | Saved file content, offline verification | No |
| **File checks** | File existence, save state | No |

## Endpoint Reference

### UNO Live State

#### `slides`
List all slides with name and shape count.
```bash
python3 /home/user/verifiers/libreoffice_impress.py slides
```
```json
{"slides": [{"index": 0, "name": "Slide1", "shape_count": 3}], "count": 5}
```

#### `slide-text [index]`
Get all text content from a slide.
```bash
python3 /home/user/verifiers/libreoffice_impress.py slide-text 0
```
```json
{"index": 0, "texts": ["Title", "Body text"], "full_text": "Title\nBody text", "name": "Slide1"}
```

#### `slide-shapes [index]`
Get all shapes on a slide with properties.
```bash
python3 /home/user/verifiers/libreoffice_impress.py slide-shapes 0
```
```json
{"index": 0, "shapes": [{"name": "Title", "type": "TitleTextShape", "text": "Hello", "width": 20000, "height": 3000}], "count": 2}
```

#### `slide-layout [index]`
Get layout type and master page of a slide.
```bash
python3 /home/user/verifiers/libreoffice_impress.py slide-layout 0
```
```json
{"index": 0, "layout": 0, "master_page": "Default", "name": "Slide1"}
```

#### `doc-info`
Get document metadata.
```bash
python3 /home/user/verifiers/libreoffice_impress.py doc-info
```
```json
{"path": "file:///home/user/test.odp", "title": "test.odp", "slide_count": 5, "modified": true}
```

#### `notes [index]`
Get speaker notes for a slide.
```bash
python3 /home/user/verifiers/libreoffice_impress.py notes 0
```
```json
{"index": 0, "notes": "Remember to explain this slide"}
```

#### `transition [index]`
Get transition effect for a slide.
```bash
python3 /home/user/verifiers/libreoffice_impress.py transition 0
```
```json
{"index": 0, "type": 1, "subtype": 0, "duration": 2.0}
```

#### `slide-size`
Get slide dimensions.
```bash
python3 /home/user/verifiers/libreoffice_impress.py slide-size
```
```json
{"width": 25400, "height": 19050}
```

#### `master-slides`
List all master slides.
```bash
python3 /home/user/verifiers/libreoffice_impress.py master-slides
```
```json
{"masters": [{"index": 0, "name": "Default"}], "count": 1}
```

### ODF File Parsing (Offline)

#### `parse-slides [file_path]`
List slides from an ODP file.
```bash
python3 /home/user/verifiers/libreoffice_impress.py parse-slides /home/user/test.odp
```
```json
{"slides": [{"index": 0, "name": "Slide1", "shape_count": 2}], "count": 3}
```

#### `parse-slide-text [index] [file_path]`
Get slide text from an ODP file.
```bash
python3 /home/user/verifiers/libreoffice_impress.py parse-slide-text 0 /home/user/test.odp
```
```json
{"index": 0, "texts": ["Title", "Body"], "full_text": "Title\nBody"}
```

### Composite Checks (Reward Signals)

#### `check-slide-count <expected>`
**Reward key:** `match`
```bash
python3 /home/user/verifiers/libreoffice_impress.py check-slide-count 5
```

#### `check-slide-title <index> <title>`
**Reward key:** `match`
```bash
python3 /home/user/verifiers/libreoffice_impress.py check-slide-title 0 "Introduction"
```

#### `check-slide-contains <index> <text>`
**Reward key:** `contains`
```bash
python3 /home/user/verifiers/libreoffice_impress.py check-slide-contains 0 "Hello"
```

#### `check-shape-exists <index> [type]`
**Reward key:** `exists`
```bash
python3 /home/user/verifiers/libreoffice_impress.py check-shape-exists 0 TitleTextShape
```

#### `check-shape-count <index> <expected>`
**Reward key:** `match`
```bash
python3 /home/user/verifiers/libreoffice_impress.py check-shape-count 0 3
```

#### `check-notes-contain <index> <text>`
**Reward key:** `contains`
```bash
python3 /home/user/verifiers/libreoffice_impress.py check-notes-contain 0 "important"
```

#### `check-has-transition <index>`
**Reward key:** `has_transition`
```bash
python3 /home/user/verifiers/libreoffice_impress.py check-has-transition 0
```

#### `check-file-exists <path>`
**Reward key:** `exists`

#### `check-file-saved`
**Reward key:** `saved`

### Extended File-Parsing Endpoints

These all work on saved ODP files (no UNO needed) and cover slide page layout,
header/footer, animations, hyperlinks, shape click-actions, and LibreOffice
user-profile preferences.

#### `parse-slide-size <file>`
Read page width/height from `styles.xml`. Returns `width_cm`, `height_cm`,
`width_inch`, `height_inch`, `orientation`.

#### `check-slide-size <file> <width_inch> <height_inch> [tolerance]`
**Reward key:** `match`
Check slide width/height in inches match expected (default tolerance 0.02).

#### `parse-header-footer <file>`
Return `declarations` (footers/headers/dates by name) plus per-page
`use_footer`, `use_header`, `use_date_time`, `visibility`.

#### `check-footer-on-slide <file> <slide_index> [expected_text]`
**Reward key:** `match`
Check that the given slide has a footer enabled, and (optionally) that the
footer text contains `expected_text`.

#### `check-slide-number-on-slide <file> <slide_index>`
**Reward key:** `match`
Check that the slide contains at least one `<text:page-number/>` element.

#### `parse-animations <file> <slide_index>`
List the names of all `<anim:*>` elements inside a slide.

#### `check-has-animation <file> <slide_index>`
**Reward key:** `has_animation`
True if the slide has at least one animation element attached.

#### `parse-hyperlinks <file>`
List all `<text:a>` hyperlinks in the presentation: `[{href, text}, ...]`.

#### `check-hyperlink-exists <file> <href_substring> [link_text]`
**Reward key:** `exists`
True if a hyperlink exists whose `href` contains `href_substring`, and
optionally whose visible text contains `link_text` (both case-insensitive).

#### `parse-shape-actions <file> <slide_index>`
List shape `<presentation:event-listener>` records on a slide.

#### `check-shape-jumps-to-slide <file> <slide_index> <shape_text> <target_slide_name>`
**Reward key:** `match`
True if a shape on `slide_index` whose text contains `shape_text` has a click
action pointing to the slide named `target_slide_name` (href `#<name>`).

#### `parse-registry-value <item_path> [prop_name] [config_path]`
Read entries from `~/.config/libreoffice/4/user/registrymodifications.xcu`
for a given `oor:path` item (e.g. `/org.openoffice.Office.Common/Save/Document`).

#### `check-registry-value <item_path> <prop_name> <expected> [config_path]`
**Reward key:** `match`
Case-insensitive exact match of a registry prop's value.

#### `check-registry-prop-exists <item_path> <prop_name> [config_path]`
**Reward key:** `exists`
Check that a registry prop entry exists at all (value-agnostic).

## Common Verification Patterns

### Check if user created enough slides
```python
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_impress.py check-slide-count 5")
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

### Check if user added a title to a slide
```python
result = sandbox.commands.run('python3 /home/user/verifiers/libreoffice_impress.py check-slide-title 0 "Introduction"')
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

### Check if slide has specific content
```python
result = sandbox.commands.run('python3 /home/user/verifiers/libreoffice_impress.py check-slide-contains 0 "Revenue Growth"')
data = json.loads(result.stdout)
reward = 1.0 if data["contains"] else 0.0
```
