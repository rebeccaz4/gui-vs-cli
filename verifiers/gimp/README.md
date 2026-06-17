# GIMP Verifier

Programmatic state inspection for GIMP in the E2B desktop sandbox. Uses two verification channels:

1. **Script-Fu TCP server** — real-time inspection of open images, layers, channels, pixel colors, resolution (requires GIMP running with Script-Fu server)
2. **PIL (Pillow)** — offline inspection of exported/saved image files on disk (dimensions, format, mode, pixel colors)
3. **Config file parsing** — read gimprc preferences

## Prerequisites

Launch GIMP with Script-Fu server enabled on port 10008:

```bash
gimp -b '(plug-in-script-fu-server RUN-NONINTERACTIVE "127.0.0.1" 10008 "")' &
```

Wait for GIMP to fully load (~5-10 seconds) before running verifier commands.

File-based endpoints (`file-info`, `check-file-*`, `pixel-color-file`) do **not** require the Script-Fu server — they work on saved files via PIL.

## Endpoint Reference

### Live State Endpoints (Script-Fu)

These require GIMP running with the Script-Fu server.

---

#### `images`

List all open images.

```bash
python3 /home/user/verifiers/gimp.py images
```

Returns:
```json
[
  {"id": 1, "name": "photo.png", "width": 800, "height": 600, "mode": "RGB", "has_alpha": false}
]
```

---

#### `image-info [image_index]`

Detailed info about one image. `image_index` defaults to 0 (most recently opened).

```bash
python3 /home/user/verifiers/gimp.py image-info 0
```

Returns:
```json
{
  "id": 1, "name": "photo.png",
  "width": 800, "height": 600,
  "mode": "RGB", "has_alpha": false,
  "x_resolution": 300.0, "y_resolution": 300.0,
  "num_layers": 3, "num_channels": 0,
  "filename": "/home/user/photo.png",
  "is_dirty": true
}
```

---

#### `layers [image_index]`

List all layers with properties.

```bash
python3 /home/user/verifiers/gimp.py layers 0
```

Returns:
```json
[
  {"id": 5, "name": "Background", "visible": true, "opacity": 100.0,
   "width": 800, "height": 600, "has_alpha": false, "offsets": [0, 0], "blend_mode": 28},
  {"id": 6, "name": "Text Layer", "visible": true, "opacity": 80.0,
   "width": 200, "height": 50, "has_alpha": true, "offsets": [10, 20], "blend_mode": 28}
]
```

---

#### `channels [image_index]`

List custom channels (not built-in RGB channels).

```bash
python3 /home/user/verifiers/gimp.py channels 0
```

Returns:
```json
[
  {"id": 10, "name": "Selection Mask", "visible": true, "opacity": 50.0}
]
```

---

#### `active-layer [image_index]`

Get the currently active layer.

```bash
python3 /home/user/verifiers/gimp.py active-layer 0
```

Returns:
```json
{"id": 5, "name": "Background", "width": 800, "height": 600, "opacity": 100.0, "visible": true}
```

---

#### `pixel-color <x> <y> [image_index]`

Get pixel color at coordinates from the active drawable in a live image.

```bash
python3 /home/user/verifiers/gimp.py pixel-color 100 200
```

Returns:
```json
{"r": 255, "g": 128, "b": 0, "a": 255, "num_channels": 4}
```

---

### File-Based Endpoints

These do **not** require the Script-Fu server. They read files from disk using PIL.

---

#### `file-info <path>`

Get image file metadata: dimensions, format, mode, file size.

```bash
python3 /home/user/verifiers/gimp.py file-info /home/user/output.png
```

Returns:
```json
{
  "path": "/home/user/output.png", "exists": true, "size_bytes": 54321,
  "width": 800, "height": 600, "format": "PNG", "mode": "RGBA"
}
```

---

#### `pixel-color-file <path> <x> <y>`

Get pixel color at coordinates from a file on disk.

```bash
python3 /home/user/verifiers/gimp.py pixel-color-file /home/user/output.png 0 0
```

Returns:
```json
{"r": 255, "g": 0, "b": 0, "mode": "RGB"}
```

---

#### `preferences [key]`

Read GIMP preferences from gimprc. Without a key, returns all top-level keys.

```bash
python3 /home/user/verifiers/gimp.py preferences
python3 /home/user/verifiers/gimp.py preferences default-brush
```

---

### Check Endpoints — Live (Script-Fu)

All check endpoints return a dict with one primary boolean key for reward signals.

---

#### `check-image-open <filename>`

Check if an image matching the filename substring is open.

```bash
python3 /home/user/verifiers/gimp.py check-image-open photo.png
```

Returns: `{"found": true, "image": {...}}` or `{"found": false, ...}`

Primary key: **`found`**

---

#### `check-layer-exists <layer_name> [image_index]`

Check if a layer with the exact name exists.

```bash
python3 /home/user/verifiers/gimp.py check-layer-exists Background
```

Returns: `{"exists": true, "layer": {...}}` or `{"exists": false, ...}`

Primary key: **`exists`**

---

#### `check-layer-count <count> [image_index]`

Check if the image has exactly N layers.

```bash
python3 /home/user/verifiers/gimp.py check-layer-count 3
```

Returns: `{"match": true, "expected": 3, "actual": 3}`

Primary key: **`match`**

---

#### `check-image-mode <mode> [image_index]`

Check color mode: `RGB`, `GRAY`, or `INDEXED`.

```bash
python3 /home/user/verifiers/gimp.py check-image-mode GRAY
```

Returns: `{"match": true, "expected": "GRAY", "actual": "GRAY"}`

Primary key: **`match`**

---

#### `check-has-alpha [image_index]`

Check if the active layer has an alpha channel.

```bash
python3 /home/user/verifiers/gimp.py check-has-alpha
```

Returns: `{"has_alpha": true}`

Primary key: **`has_alpha`**

---

#### `check-resolution <xdpi> <ydpi> [image_index]`

Check if image DPI matches expected values (tolerance: 0.5).

```bash
python3 /home/user/verifiers/gimp.py check-resolution 300 300
```

Returns: `{"match": true, "expected": [300.0, 300.0], "actual": [300.0, 300.0]}`

Primary key: **`match`**

---

#### `check-image-size <width> <height> [image_index]`

Check if image dimensions match.

```bash
python3 /home/user/verifiers/gimp.py check-image-size 1920 1080
```

Returns: `{"match": true, "expected": [1920, 1080], "actual": [1920, 1080]}`

Primary key: **`match`**

---

### Check Endpoints — File-Based (PIL)

---

#### `check-file-exists <path>`

Check if a file exists on disk.

```bash
python3 /home/user/verifiers/gimp.py check-file-exists /home/user/output.png
```

Returns: `{"exists": true, "path": "...", "size_bytes": 54321}`

Primary key: **`exists`**

---

#### `check-file-dimensions <path> <width> <height>`

Check exported image dimensions.

```bash
python3 /home/user/verifiers/gimp.py check-file-dimensions /home/user/output.png 800 600
```

Returns: `{"match": true, "expected": [800, 600], "actual": [800, 600]}`

Primary key: **`match`**

---

#### `check-file-format <path> <format>`

Check file format. Supported: `PNG`, `JPEG`, `BMP`, `TIFF`, `GIF`, `WEBP`.

```bash
python3 /home/user/verifiers/gimp.py check-file-format /home/user/output.jpg JPEG
```

Returns: `{"match": true, "expected": "JPEG", "actual": "JPEG"}`

Primary key: **`match`**

---

#### `check-file-mode <path> <mode>`

Check PIL color mode: `RGB`, `RGBA`, `L` (grayscale), `LA`, `P` (palette), etc.

```bash
python3 /home/user/verifiers/gimp.py check-file-mode /home/user/output.png RGBA
```

Returns: `{"match": true, "expected": "RGBA", "actual": "RGBA"}`

Primary key: **`match`**

---

#### `check-pixel-color-file <path> <x> <y> <r> <g> <b> [tolerance]`

Check if a pixel in a file matches expected RGB color. Default tolerance: 5.

```bash
python3 /home/user/verifiers/gimp.py check-pixel-color-file /home/user/output.png 0 0 255 0 0
python3 /home/user/verifiers/gimp.py check-pixel-color-file /home/user/output.png 0 0 255 0 0 10
```

Returns: `{"match": true, "expected": [255, 0, 0], "actual": [255, 0, 0], "tolerance": 5}`

Primary key: **`match`**

---

## Common Verification Patterns

### Check if agent resized and exported an image

```python
# Verify exported file dimensions
result = sandbox.commands.run(
    "python3 /home/user/verifiers/gimp.py check-file-dimensions /home/user/output.png 400 300"
)
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

### Check if agent converted image to grayscale

```python
result = sandbox.commands.run(
    "python3 /home/user/verifiers/gimp.py check-file-mode /home/user/output.png L"
)
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

### Check if agent added a new layer

```python
result = sandbox.commands.run(
    "python3 /home/user/verifiers/gimp.py check-layer-exists 'Text Layer'"
)
data = json.loads(result.stdout)
reward = 1.0 if data["exists"] else 0.0
```

### Check if agent saved file in specific format

```python
# First check file exists
result1 = sandbox.commands.run(
    "python3 /home/user/verifiers/gimp.py check-file-exists /home/user/output.bmp"
)
# Then check format
result2 = sandbox.commands.run(
    "python3 /home/user/verifiers/gimp.py check-file-format /home/user/output.bmp BMP"
)
```

### Check pixel color after applying a filter

```python
result = sandbox.commands.run(
    "python3 /home/user/verifiers/gimp.py check-pixel-color-file /home/user/output.png 50 50 255 255 255"
)
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

## Skipped Categories

- **Keybindings**: GIMP keybindings are stored in `menurc` but the format is complex GTK accelerator maps. No endpoint provided.
- **Extensions/plugins**: GIMP plugin listing requires Script-Fu queries to `gimp-pdb-dump-args` which is unreliable. Skipped.
- **UI layout**: GIMP session layout is in `sessionrc` but the format is not reliably parseable for verification. Skipped.
- **History/recent files**: GIMP stores recent files in `recent-documents.xbel` but this is not useful for RL task verification. Skipped.
- **Bookmarks**: GIMP does not have a bookmarks concept. Skipped.
- **Network**: GIMP has no network features. Skipped.

## Error Handling

All endpoints return `{"error": "..."}` on failure, never crash. Common errors:

- `"Cannot connect to Script-Fu server"` — GIMP not running or server not started
- `"No images open in GIMP"` — no image loaded
- `"File not found: ..."` — file path doesn't exist
- `"Pillow not installed"` — PIL not available for file-based checks
