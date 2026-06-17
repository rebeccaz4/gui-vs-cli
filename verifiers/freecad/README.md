# FreeCAD Verifier

Programmatic state inspection for FreeCAD `.FCStd` files and FreeCAD
user config in an E2B sandbox. Uses **stdlib** (`zipfile`,
`xml.etree.ElementTree`, `struct`) for everything — no running FreeCAD
instance is required.

## Verification Channels

| Channel | Used for |
|---|---|
| ZIP + XML parsing of `.FCStd` | objects, types, parameters, labels, placements, document metadata, thumbnails |
| XML parsing of `~/.config/FreeCAD/user.cfg` | preferences (units, theme, default workbench, auto-save) |
| Binary + text parsing of exported files | STL, STEP, IGES, OBJ |

### Skipped categories

- **UI layout / window state** — FreeCAD has no on-disk session file that
  reliably reflects the current sidebar/panel/tab layout from outside the
  process. Not verifiable.
- **Keybindings / macros** — These live in user macros directories and
  cannot be round-tripped deterministically in the sandbox. Not exposed.
- **Live geometry (BREP) inspection** — The BREP blobs in the FCStd zip
  encode face/edge counts but require FreeCAD's compiled Part module to
  decode. We instead rely on object parameters (Length/Width/Radius) and
  exported STL/OBJ triangle/vertex counts.

## Prerequisites

None at verification time. Fixtures inside the sandbox can be generated
with `freecadcmd` but the verifier itself only needs `python3`.

## Endpoint Reference

### Document & object queries

#### `document-info <fcstd>`
Returns `program_version`, `file_version`, `schema_version`,
`properties` (document-level), `archive_files`, `object_count`,
`has_thumbnail`.

#### `objects <fcstd>`
Returns `{"objects": [...], "count": N}` where each object has
`name`, `type`, and `properties` (full parameter dict).

#### `object-info <fcstd> <name>`
Return one object's details.

#### `object-types <fcstd>`
Group objects by `type` and return `{"counts": {...}, "total": N}`.

#### `parameter <fcstd> <name> <parameter>`
Read one parameter of one object. Returns `{object, parameter, type, value}`.

#### `label <fcstd> <name>`
Return the `Label` property value.

#### `placement <fcstd> <name>`
Return the `Placement` property value (attribute dict).

### Preferences

#### `preferences [cfg_path]`
Return all FreeCAD preferences as a flat dict keyed
`"Group1/Group2/ParameterName"`. If `cfg_path` is omitted, uses
`~/.config/FreeCAD/user.cfg`.

#### `preference <key> [cfg_path]`
Read one preference by its slash path. If an exact match isn't found, a
suffix match is attempted.

### Exported file parsers

#### `parse-stl <path>`
Return `{format: ascii|binary, triangles, size}`.

#### `parse-step <path>`
Return `{is_step, entities, size, file_name_header}`.

#### `parse-iges <path>`
Return `{is_iges, sections: {S,G,D,P,T}, size}`.

#### `parse-obj <path>`
Return `{vertices, faces, objects, groups, size}`.

### Composite checks (reward signals)

| Command | Primary key | Example |
|---|---|---|
| `check-file-exists <path>` | `exists` | `check-file-exists /home/user/a.FCStd` |
| `check-object-exists <fcstd> <name>` | `exists` | `check-object-exists a.FCStd Box` |
| `check-object-type <fcstd> <name> <type>` | `match` | `check-object-type a.FCStd Box Part::Box` |
| `check-object-count <fcstd> <n>` | `match` | `check-object-count a.FCStd 3` |
| `check-object-type-count <fcstd> <type> <n>` | `match` | `check-object-type-count a.FCStd Part::Box 2` |
| `check-parameter-value <fcstd> <name> <param> <value>` | `match` | `check-parameter-value a.FCStd Box Length 20` |
| `check-label <fcstd> <name> <label>` | `match` | `check-label a.FCStd Box RedBox` |
| `check-document-property <fcstd> <prop> <value>` | `match` | `check-document-property a.FCStd Comment 'hello'` |
| `check-preference <key> <value> [cfg]` | `match` | `check-preference BaseApp/Preferences/General/ThemeName Dark` |
| `check-stl-triangles <path> <n>` | `match` | `check-stl-triangles box.stl 12` |
| `check-stl-min-triangles <path> <n>` | `match` | `check-stl-min-triangles box.stl 1` |
| `check-step-valid <path>` | `valid` | `check-step-valid box.step` |
| `check-obj-min-vertices <path> <n>` | `match` | `check-obj-min-vertices box.obj 8` |
| `check-has-thumbnail <fcstd>` | `has_thumbnail` | `check-has-thumbnail a.FCStd` |

Every `check-*` endpoint returns a dict with one primary boolean key plus
context. Errors are reported as `{"match": false, "error": "..."}` so that
checks fail closed rather than crashing.

## Common Verification Patterns

### Check if the agent created an object with the right parameters
```python
r = sandbox.commands.run(
    "python3 /home/user/verifiers/freecad.py "
    "check-parameter-value /home/user/design.FCStd Box Length 25"
)
data = json.loads(r.stdout)
reward = 1.0 if data["match"] else 0.0
```

### Check that the agent exported an STL
```python
r = sandbox.commands.run(
    "python3 /home/user/verifiers/freecad.py check-stl-min-triangles "
    "/home/user/exports/part.stl 12"
)
reward = 1.0 if json.loads(r.stdout)["match"] else 0.0
```

### Check that a FreeCAD preference was changed
```python
r = sandbox.commands.run(
    "python3 /home/user/verifiers/freecad.py check-preference "
    "BaseApp/Preferences/General/ThemeName Dark"
)
reward = 1.0 if json.loads(r.stdout)["match"] else 0.0
```
