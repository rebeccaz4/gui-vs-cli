# LibreOffice Draw Verifier

Programmatic state inspection for LibreOffice Draw documents in E2B sandbox.
Used by a **check agent** to generate reward signals for RL/evaluation.

## Prerequisites

Launch LibreOffice Draw with UNO socket listener enabled:

```bash
soffice --draw --accept="socket,host=localhost,port=2002;urp;" --norestore &
```

For file-based verification (ODF parsing), no running instance is needed — just a saved `.odg` file.

## Verification Channels

| Channel | When to use | Needs running LO? |
|---------|-------------|-------------------|
| **UNO API** | Live pages, shapes, connectors, layers, text | Yes |
| **ODF parsing** | Saved file content, offline verification | No |
| **File checks** | File existence, save state | No |

## Endpoint Reference

### UNO Live State

#### `pages`
List all pages with name and shape count.
```bash
python3 /home/user/verifiers/libreoffice_draw.py pages
```
```json
{"pages": [{"index": 0, "name": "page1", "shape_count": 5}], "count": 1}
```

#### `page-shapes [index]`
Get all shapes on a page with properties (type, position, size, text, fill).
```bash
python3 /home/user/verifiers/libreoffice_draw.py page-shapes 0
```
```json
{"index": 0, "shapes": [{"name": "rect1", "type": "RectangleShape", "width": 5000, "height": 3000, "text": "Box 1"}], "count": 3}
```

For shapes drawn via Draw's toolbar Ellipse/Rectangle/etc. buttons the native `type`
is `CustomShape` (they are `com.sun.star.drawing.CustomShape` instances). The
geometric subtype is exposed as `custom_shape_type` (e.g. `"ellipse"`,
`"rectangle"`, `"round-rectangle"`), read from the shape's `CustomShapeGeometry`
property.

#### `page-text [index]`
Get all text from shapes on a page.
```bash
python3 /home/user/verifiers/libreoffice_draw.py page-text 0
```
```json
{"index": 0, "texts": ["Box 1", "Label"], "full_text": "Box 1\nLabel"}
```

#### `page-size`
Get page dimensions.
```bash
python3 /home/user/verifiers/libreoffice_draw.py page-size
```
```json
{"width": 28000, "height": 21000}
```

#### `doc-info`
Get document metadata.
```bash
python3 /home/user/verifiers/libreoffice_draw.py doc-info
```
```json
{"path": "file:///home/user/test.odg", "title": "test.odg", "page_count": 3, "modified": true}
```

#### `layers`
List all layers.
```bash
python3 /home/user/verifiers/libreoffice_draw.py layers
```
```json
{"layers": [{"index": 0, "name": "Layout", "visible": true, "printable": true, "locked": false}], "count": 3}
```

#### `connectors [page_index]`
List all connector shapes on a page.
```bash
python3 /home/user/verifiers/libreoffice_draw.py connectors 0
```
```json
{"connectors": [{"name": "conn1", "start_shape": "rect1", "end_shape": "rect2"}], "count": 1}
```

### ODF File Parsing (Offline)

#### `parse-pages [file_path]`
List pages from an ODG file.
```bash
python3 /home/user/verifiers/libreoffice_draw.py parse-pages /home/user/test.odg
```

#### `parse-page-text [index] [file_path]`
Get text from a page in an ODG file.
```bash
python3 /home/user/verifiers/libreoffice_draw.py parse-page-text 0 /home/user/test.odg
```

### Composite Checks (Reward Signals)

#### `check-page-count <expected>`
**Reward key:** `match`
```bash
python3 /home/user/verifiers/libreoffice_draw.py check-page-count 3
```

#### `check-shape-count <page_index> <expected>`
**Reward key:** `match`
```bash
python3 /home/user/verifiers/libreoffice_draw.py check-shape-count 0 5
```

#### `check-shape-exists <page_index> [type]`
**Reward key:** `exists`
```bash
python3 /home/user/verifiers/libreoffice_draw.py check-shape-exists 0 RectangleShape
```

Matches against both the native shape type (e.g. `RectangleShape`,
`EllipseShape`) and the CustomShape geometric subtype. `RectangleShape` also
matches CustomShape geometry `rectangle` / `round-rectangle`; `EllipseShape`
matches geometry `ellipse`. Passing the literal geometry token
(`rectangle`, `ellipse`, …) also works. This covers shapes inserted via Draw's
default toolbar buttons, which produce `com.sun.star.drawing.CustomShape`
instances rather than native `RectangleShape`/`EllipseShape`.

#### `check-page-contains <page_index> <text>`
**Reward key:** `contains`
```bash
python3 /home/user/verifiers/libreoffice_draw.py check-page-contains 0 "Hello"
```

#### `check-connector-exists <page_index> [start_name] [end_name]`
**Reward key:** `exists`
```bash
python3 /home/user/verifiers/libreoffice_draw.py check-connector-exists 0 rect1 rect2
```

#### `check-layer-exists <layer_name>`
**Reward key:** `exists`
```bash
python3 /home/user/verifiers/libreoffice_draw.py check-layer-exists Layout
```

#### `check-file-exists <path>`
**Reward key:** `exists`

#### `check-file-saved`
**Reward key:** `saved`

### Preferences / Settings (registrymodifications.xcu)

These read `~/.config/libreoffice/4/user/registrymodifications.xcu`, written by LibreOffice on clean shutdown.
**Important:** tasks must close LibreOffice before verification, otherwise the file may not have the new values.

#### `draw-prefs`
Dump all known Draw preferences (measurement unit, grid, snap, default save filter, autosave…) plus a `raw` list of every prop/value seen.

```bash
python3 /home/user/verifiers/libreoffice_draw.py draw-prefs
```

#### `check-draw-pref <key> <expected>`
**Reward key:** `match`
Supported keys: `measurement_unit_draw`, `default_tab_stop_draw`, `default_save_filter_draw`,
`autosave_enabled`, `autosave_interval`, `backup_enabled`, `grid_visible_draw`, `snap_to_grid_draw`,
`grid_resolution_x`, `grid_resolution_y`, `grid_subdivision_x`, `grid_subdivision_y`,
`snap_to_page_margins`, `snap_to_object_frame`.

```bash
python3 /home/user/verifiers/libreoffice_draw.py check-draw-pref measurement_unit_draw 2
```

Known enum for `measurement_unit_draw` (MeasureKind): 0=1/100 mm, 1=mm, 2=cm, 3=meter, 4=km, 5=twip,
6=point, 7=pica, 8=inch, 9=foot, 10=mile.

#### `check-registry-key <path_substring> <prop_name> <expected>`
**Reward key:** `match`
Generic fallback for settings not in the known keys list.

### Offline page-level properties

#### `parse-page-props [file_path]`
Parse every page's name, master-page, width/height (cm), margins (cm) and background-fill color from a saved `.odg`.

```bash
python3 /home/user/verifiers/libreoffice_draw.py parse-page-props /home/user/Documents/report.odg
```

#### `check-page-property <index> <key> <expected> [file_path]`
**Reward key:** `match`
Keys: `name`, `width_cm`, `height_cm`, `margin_top_cm`, `margin_bottom_cm`, `margin_left_cm`,
`margin_right_cm`, `master_page`, `background_fill_style`, `background_fill_color` (hex without `#`).

### Shape hyperlinks (offline)

#### `parse-shape-hyperlinks <page_index> [file_path]`
Return every `<draw:a>`/`<text:a>` hyperlink anchor on a page.

#### `check-shape-hyperlink <page_index> <href_substring> [text_substring] [file_path]`
**Reward key:** `exists`

### PDF inspection (stdlib-only)

#### `parse-pdf-info <file_path>`
Return `page_count` and list of outline (`bookmarks`) titles.

#### `check-pdf-page-count <file_path> <expected>`
**Reward key:** `match`

#### `check-pdf-bookmark <file_path> <title_substring>`
**Reward key:** `exists`

## Common Verification Patterns

### Check if user drew shapes on a page
```python
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_draw.py check-shape-count 0 5")
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

### Check if user added a rectangle
```python
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_draw.py check-shape-exists 0 RectangleShape")
data = json.loads(result.stdout)
reward = 1.0 if data["exists"] else 0.0
```

### Check if user added text to a shape
```python
result = sandbox.commands.run('python3 /home/user/verifiers/libreoffice_draw.py check-page-contains 0 "Label"')
data = json.loads(result.stdout)
reward = 1.0 if data["contains"] else 0.0
```

### Check if shapes are connected
```python
result = sandbox.commands.run("python3 /home/user/verifiers/libreoffice_draw.py check-connector-exists 0 rect1 rect2")
data = json.loads(result.stdout)
reward = 1.0 if data["exists"] else 0.0
```
