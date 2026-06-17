# CloudCompare Verifier

Programmatic inspection of point cloud / mesh files produced or consumed by
CloudCompare, plus the CloudCompare user INI config. Deliberately file-based:
CloudCompare does not expose a headless Python API, so this verifier parses
common interchange formats with the Python stdlib (no third-party deps).

## Prerequisites

- CloudCompare binary only needs to be installed if a task asks the agent to
  convert, export, or save a file via the GUI/CLI. Verification itself never
  launches CloudCompare — all checks read files from disk.
- CloudCompare is launched by the eval runner when a task file of a supported
  type is passed as `env.files[0].sandbox_path`. Save operations go back to
  that same path.

## Verification Channels

| Channel | Used for |
|---|---|
| PLY header + body parsing (stdlib `struct`) | `.ply` (ASCII, binary little- and big-endian) point counts, face counts, color/normal/intensity detection, bounding box |
| ASCII column parsing | `.xyz` / `.asc` / `.txt` / `.pts` / `.csv` — point count, column channels, bounding box |
| OBJ text parsing | `.obj` vertex / face / normal / texcoord counts, bounding box |
| INI (Qt `configparser`) | `~/.config/CCorp/CloudCompare.conf` — settings, recent files |
| Filesystem | file existence and size for exports |

## Endpoint Reference

All commands return a single JSON object on stdout. Errors are returned as
`{"error": "..."}`. `check-*` endpoints return a dict whose primary key is the
reward boolean.

Run as:
```bash
python3 /home/user/verifiers/cloudcompare.py <command> [args...]
```

### Query endpoints

| Command | Args | Returns |
|---|---|---|
| `cloud-info` | `<path>` | Parsed info for a PLY / OBJ / ASCII file: format, vertex/face counts, bbox, channel flags. |
| `ply-header` | `<path>` | Parsed PLY header (elements and properties). |
| `settings` | `[conf_path]` | All sections/keys/values from the CloudCompare INI. |
| `recent-files` | `[conf_path]` | List of recent files extracted from the INI. |

Example:
```bash
python3 /home/user/verifiers/cloudcompare.py cloud-info /home/user/Documents/scan.ply
```

### File checks

| Command | Args | Primary key |
|---|---|---|
| `check-file-exists` | `<path>` | `exists` |
| `check-file-size` | `<path> <min_bytes>` | `match` |

### Count checks

| Command | Args | Primary key |
|---|---|---|
| `check-point-count` | `<path> <expected>` | `match` |
| `check-point-count-at-least` | `<path> <min>` | `match` |
| `check-face-count` | `<path> <expected>` | `match` |

For ASCII files `points` is used; for PLY/OBJ `vertex_count` is used; the
endpoint transparently picks the right field.

### Bounding box

| Command | Args | Primary key |
|---|---|---|
| `check-bbox-within` | `<path> <xmin> <ymin> <zmin> <xmax> <ymax> <zmax>` | `match` |
| `check-bbox-min-extent` | `<path> <axis> <min>` | `match` |

`axis` is one of `x`, `y`, `z`.

### Channels / format

| Command | Args | Primary key |
|---|---|---|
| `check-has-color` | `<path>` | `has_color` |
| `check-has-intensity` | `<path>` | `has_intensity` |
| `check-has-normals` | `<path>` | `has_normals` |
| `check-ply-format` | `<path> <ascii\|binary_little_endian\|binary_big_endian>` | `match` |
| `check-format` | `<path> <ply\|obj\|ascii>` | `match` |
| `check-is-mesh` | `<path>` | `is_mesh` |

### Config (Qt INI)

| Command | Args | Primary key |
|---|---|---|
| `check-setting` | `<section> <key> <expected> [conf_path]` | `match` |
| `check-recent-file` | `<filename> [conf_path]` | `match` |

`check-recent-file` uses substring matching so either a full path or just a
basename works. `check-setting` strips surrounding single / double quotes that
Qt INI sometimes adds to string values.

## Common Verification Patterns

### Verify the agent exported a point cloud with the right number of points

```json
{"command": "check-file-exists /home/user/Documents/export.xyz", "key": "exists", "expected": true},
{"command": "check-point-count /home/user/Documents/export.xyz 1000", "key": "match", "expected": true}
```

### Verify a PLY was converted from binary to ASCII

```json
{"command": "check-ply-format /home/user/Documents/out.ply ascii", "key": "match", "expected": true}
```

### Verify a color channel was added / preserved

```json
{"command": "check-has-color /home/user/Documents/colored.ply", "key": "has_color", "expected": true}
```

### Verify a cloud was cropped to within a box

```json
{"command": "check-bbox-within /home/user/Documents/cropped.ply 0 0 0 10 10 10", "key": "match", "expected": true}
```

### Verify a setting was changed in the CloudCompare config

```json
{"command": "check-setting Console showDialogOnError false", "key": "match", "expected": true}
```

## Skipped / Unsupported Categories

CloudCompare has a much thinner programmatically inspectable surface than apps
like Blender (`bpy`) or Krita. The following categories are intentionally not
covered:

- **Live scene graph / tree state.** CloudCompare does not expose a headless
  Python API. There is no way to inspect the in-memory DB-tree (current cloud
  selection, active filters, scalar fields currently displayed) without
  running the GUI.
- **Visual / display state.** No reliable channel to read current camera,
  rendering shader, point size, background color from a running instance.
  Some of these leak into the INI after quitting, but not dependably.
- **Scalar field values / stats beyond bbox.** Parsing full scalar field
  histograms from binary PLY or BIN files is out of scope. Checks are limited
  to the presence of `intensity` / color properties.
- **`.bin` (CloudCompare native) parsing.** The `.bin` format is proprietary
  binary with no public schema; this verifier cannot parse it. Tasks must
  export through an interchange format (PLY / XYZ / OBJ / ASC).
- **LAS / LAZ parsing.** Requires `laspy` / binary format knowledge; out of
  scope for stdlib-only parsing. Tasks should avoid LAS as the final output
  format.
- **Plugins / extensions.** CloudCompare plugins are managed through the
  installer and are not part of user config; nothing to verify per task.
- **Keybindings.** CloudCompare does not expose user-customizable keybindings
  through the INI in a stable form.
- **History / undo stack.** Not persisted to disk.

Task generators should stick to tasks that can be verified through the
channels above.
