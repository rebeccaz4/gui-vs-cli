# darktable Verifier

Programmatic state inspection for darktable in E2B desktop sandboxes. Designed for RL/evaluation reward signals in GUI task synthesis.

## Verification Channels

| Channel | What it covers | Reliability |
|---------|---------------|-------------|
| **SQLite** (`library.db`) | Images, metadata, tags, collections | High — persistent ground truth |
| **SQLite** (`data.db`) | Styles, presets | High |
| **XMP sidecar** | Full edit history, ratings, operations | High — XML per-image |
| **darktable-cli** | Export verification | Medium — requires darktable installed |
| **PIL/Pillow** | Exported image dimensions, format | High — for output validation |

## Usage

### CLI (via E2B sandbox)

```bash
# Upload to sandbox
sandbox.files.write("/home/user/verifiers/darktable.py", open("darktable.py").read())

# Query endpoints
sandbox.commands.run("python3 /home/user/verifiers/darktable.py library-images")
sandbox.commands.run("python3 /home/user/verifiers/darktable.py image-info 1")
sandbox.commands.run("python3 /home/user/verifiers/darktable.py tags landscape")
sandbox.commands.run("python3 /home/user/verifiers/darktable.py xmp-history /home/user/photos/img.CR2.xmp")

# Check endpoints (return boolean result)
sandbox.commands.run("python3 /home/user/verifiers/darktable.py check-image-imported sunset.CR2")
sandbox.commands.run("python3 /home/user/verifiers/darktable.py check-tag-exists landscape")
sandbox.commands.run("python3 /home/user/verifiers/darktable.py check-image-tagged 1 landscape")
sandbox.commands.run("python3 /home/user/verifiers/darktable.py check-xmp-has-operation photo.xmp exposure")
```

### Python API

```python
from verifiers.darktable import DarktableVerifier

v = DarktableVerifier()

# Query
images = v.library_images("sunset")
info = v.image_info(1)
tags = v.tags()
history = v.xmp_history("/path/to/photo.CR2.xmp")

# Check
result = v.check_image_imported("sunset.CR2")    # {"imported": True, "image_id": 1, ...}
result = v.check_tag_exists("landscape")          # {"exists": True, "tag_id": 1}
result = v.check_image_tagged(1, "landscape")     # {"tagged": True, "tag_id": 1}
result = v.check_xmp_has_operation("f.xmp", "exposure")  # {"has_operation": True, "count": 2}
```

## Commands Reference

### Query Commands

| Command | Args | Description |
|---------|------|-------------|
| `library-images` | `[query]` | List images from library.db, optional filename filter |
| `image-info` | `<image_id>` | Detailed info for a specific image |
| `tags` | `[query]` | List all tags, optional name filter |
| `image-tags` | `<image_id>` | Tags assigned to a specific image |
| `styles` | | List styles from data.db |
| `presets` | | List presets from data.db |
| `collections` | | List film rolls/collections |
| `xmp-history` | `<xmp_file>` | Parse XMP sidecar for edit operations |
| `xmp-rating` | `<xmp_file>` | Get star rating from XMP |
| `export-info` | `<file>` | Exported file info (dimensions, format via PIL) |

### Check Commands

All check commands return a primary boolean field.

| Command | Args | Returns |
|---------|------|---------|
| `check-file-exists` | `<path>` | `{"exists": bool}` |
| `check-image-imported` | `<filename>` | `{"imported": bool}` |
| `check-tag-exists` | `<tag_name>` | `{"exists": bool}` |
| `check-image-tagged` | `<image_id> <tag_name>` | `{"tagged": bool}` |
| `check-image-tagged-by-filename` | `<filename> <tag_name>` | `{"tagged": bool, "image_id": int}` |
| `check-image-exported` | `<output_path>` | `{"exported": bool, "valid_image": bool}` |
| `check-xmp-has-operation` | `<xmp_file> <operation>` | `{"has_operation": bool}` |
| `check-db-has-operation` | `<filename> <operation>` | `{"has_operation": bool, "count": int}` |
| `check-image-rating` | `<image_id> <rating>` | `{"matches": bool}` |
| `check-image-rating-by-filename` | `<filename> <rating>` | `{"matches": bool, "image_id": int}` |
| `check-style-exists` | `<style_name>` | `{"exists": bool}` |

## darktable Internals

### library.db Schema (key tables)

- `images` — id, film_id, filename, width, height, datetime_taken, flags (rating in bits 0-2), maker, model, lens, exposure, aperture, iso, focal_length
- `tagged_images` — imgid, tagid (tagid references `data.tags.id`)
- `film_rolls` — id, folder

### data.db Schema (key tables)

- `tags` — id, name (moved from library.db in modern darktable; queried via an ATTACH of data.db alongside library.db for tag-related checks)
- `styles` — id, name, description
- `presets` — name, operation, op_version, enabled, description

### XMP Sidecar Structure

darktable stores edit history in XMP sidecars using parallel Bag/Seq elements under the `darktable:` namespace:

- `darktable:history_operation` — operation names (exposure, colorbalancergb, etc.)
- `darktable:history_enabled` — whether each operation is active
- `darktable:history_params` — base64-encoded parameters
- `darktable:history_modversion` — module version numbers

Ratings are stored as `xmp:Rating` attributes on the `rdf:Description` element.

### Config Location

Default: `~/.config/darktable/`
Override: set `DARKTABLE_CONFIG_DIR` environment variable.

## Dependencies

- Python 3.10+ (for `X | Y` union types)
- `sqlite3` (standard library)
- `xml.etree.ElementTree` (standard library)
- `PIL` / `Pillow` (optional, for export-info dimensions)

## Testing

```bash
python verifiers/darktable/test_darktable.py
```

Tests run in an E2B desktop sandbox. They create synthetic library.db, data.db, XMP files, and test images, then exercise all endpoints with positive and negative cases.
