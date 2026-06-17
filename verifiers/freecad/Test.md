# FreeCAD Verifier — Test Plan

## Module Overview

`verifiers/freecad/freecad.py` verifies FreeCAD `.FCStd` files and FreeCAD
runtime state. Its verification channels are:

- **ZIP + XML parsing** (stdlib `zipfile` + `xml.etree.ElementTree`) for
  `Document.xml` inside an `.FCStd`. This gives us objects, parameters,
  labels, placements, and document metadata — no running FreeCAD required.
- **`~/.config/FreeCAD/user.cfg` XML parsing** for preferences
  (default workbench, units system, theme, recent files, etc.).
- **Exported-file parsing**: STL (ASCII/binary triangle count), STEP
  (ISO-10303-21 header + entity count), IGES (section line counts),
  OBJ (vertex/face counts).
- **Thumbnail presence** inside the FCStd archive.

Test fixtures are generated inside the sandbox using `freecadcmd` + a Python
script that builds a Part-workbench document, then exports STL / STEP / OBJ.

The verifier does **not** expose live GUI state (sidebar/panel visibility,
open document tabs). FreeCAD's GUI state is not reliably reachable from
outside the running process, so those categories are deliberately skipped
and documented in the README.

## Test Groups

### Group 1 — CLI help and error handling
- Verifies `-h/--help` prints usage and exits 0.
- Missing required args returns exit 1 + valid error JSON.
- Unknown subcommand returns exit 1 + valid error JSON.
- Nonexistent FCStd path returns `{"error": ...}`.
- Passing a non-zip file returns an error (not a crash).
- Expected assertions: ~10

### Group 2 — Document / object queries
- `document-info`, `objects`, `object-info`, `object-types` against a rich
  FCStd with a Box, Cylinder, Cut, Sphere, Cone, and a Part::Compound.
- Covers: total object count, name list, type grouping, archive listing,
  thumbnail detection.
- Edge cases: query a nonexistent object name.
- Expected assertions: ~25

### Group 3 — Parameters / labels / placement
- `parameter`, `label`, `placement` for Box Length/Width/Height and for
  Cylinder Radius/Height.
- Verifies values match what the fixture set.
- Edge cases: nonexistent parameter, nonexistent object.
- Expected assertions: ~15

### Group 4 — Preferences
- `preferences`, `preference` against a hand-written `user.cfg` fixture.
- Verifies flattened slash-path keys work and values are typed correctly.
- Edge cases: missing cfg path, nonexistent key.
- Expected assertions: ~10

### Group 5 — Exported file parsers
- `parse-stl` on a binary STL and an ASCII STL.
- `parse-step` on a file produced by FreeCAD's STEP export.
- `parse-obj` on an OBJ produced by FreeCAD's OBJ export.
- `parse-iges` on an IGES export if available (optional — skip cleanly if
  the STEP/IGES export isn't produced).
- Expected assertions: ~12

### Group 6 — check-* positive cases
- check-file-exists, check-object-exists, check-object-type,
  check-object-count, check-object-type-count, check-parameter-value,
  check-label, check-document-property, check-preference,
  check-stl-triangles, check-stl-min-triangles, check-step-valid,
  check-obj-min-vertices, check-has-thumbnail.
- Expected assertions: ~20

### Group 7 — check-* negative cases
- Each check-* endpoint also tested with a value/name that should return
  `false` (wrong value, wrong object, nonexistent STL).
- Expected assertions: ~15

### Group 8 — JSON validity sweep
- Every endpoint called at least once with its inputs; stdout must parse
  as JSON.
- Expected assertions: ~25

## Test Fixtures

| File | Path in sandbox | What it contains | Used by |
|---|---|---|---|
| Rich FCStd | `/home/user/test.FCStd` | Part::Box (Length=20, Width=15, Height=10, Label="RedBox"), Part::Cylinder (Radius=5, Height=20), Part::Sphere, Part::Cone, Part::Cut (Box − Cylinder), Part::Compound. Document Comment="verifier fixture". | Groups 2,3,6,7,8 |
| `user.cfg` | `/home/user/.config/FreeCAD/user.cfg` | Fake FreeCAD prefs with BaseApp/Preferences/Units/UserSchema=1, BaseApp/Preferences/General/ThemeName=Dark, BaseApp/Preferences/Mod/StartWorkbench=PartDesignWorkbench, AutoSaveEnabled=true, AutoSaveInterval=300. | Group 4,6,7,8 |
| binary STL | `/home/user/exports/box.stl` | Binary STL exported from the Box. | Group 5,6,7 |
| ASCII STL | `/home/user/exports/box_ascii.stl` | Small ASCII STL hand-written (1 triangle). | Group 5 |
| STEP file | `/home/user/exports/box.step` | STEP export of Box via FreeCAD. | Group 5,6 |
| OBJ file | `/home/user/exports/box.obj` | OBJ export of Box via FreeCAD. | Group 5,6 |

All FreeCAD-driven fixtures are built with `freecadcmd -c "..."` executed
inside the sandbox. The `user.cfg` and tiny ASCII STL are written directly.

## Edge Cases & Error Handling Matrix

| Scenario | Endpoint | Expected |
|---|---|---|
| Missing FCStd path | any `.FCStd` endpoint | `{"error": "File not found: ..."}` |
| Path is non-zip | any `.FCStd` endpoint | `{"error": "Not a valid FCStd ..."}` |
| Nonexistent object name | `object-info`, `parameter`, `label` | `{"error": "Object ... not found"}` |
| Missing CLI arg | all | exit 1 + valid error JSON |
| Unknown subcommand | dispatch | exit 1 + valid error JSON |
| Preference missing | `preference` | `{"error": "Preference ..."}` |
| STL missing | `parse-stl` | `{"error": "File not found: ..."}` |
| Non-STL passed to `parse-stl` | `parse-stl` | `{"error": "..."}` |

## Positive / Negative Case Pairs

| check-* | Positive | Negative |
|---|---|---|
| check-file-exists | fixture FCStd path | `/no/such/file.FCStd` |
| check-object-exists | `Box` in fixture | `Ghost` |
| check-object-type | `Box` = `Part::Box` | `Box` = `Part::Cylinder` |
| check-object-count | real count | wrong count |
| check-object-type-count | real type count | wrong number |
| check-parameter-value | `Box.Length = 20` | `Box.Length = 999` |
| check-label | `Box.Label = "RedBox"` | wrong label |
| check-document-property | `Comment = "verifier fixture"` | wrong value |
| check-preference | theme = Dark | theme = Light |
| check-stl-triangles | actual count | wrong count |
| check-stl-min-triangles | minimum <= actual | unreachably-high minimum |
| check-step-valid | real STEP file | binary STL file |
| check-obj-min-vertices | feasible min | unreachable min |
| check-has-thumbnail | FCStd with thumbnail | FCStd without thumbnail |

## JSON Validity Sweep

Subcommands tested for JSON output:
`document-info`, `objects`, `object-info`, `object-types`, `parameter`,
`label`, `placement`, `preferences`, `preference`, `parse-stl`, `parse-step`,
`parse-obj`, `parse-iges`, `check-file-exists`, `check-object-exists`,
`check-object-type`, `check-object-count`, `check-object-type-count`,
`check-parameter-value`, `check-label`, `check-document-property`,
`check-preference`, `check-stl-triangles`, `check-stl-min-triangles`,
`check-step-valid`, `check-obj-min-vertices`, `check-has-thumbnail`.

## Summary

| Metric | Count |
|---|---|
| Test groups | 8 |
| Total assertions | ~130 |
| Test fixtures | 6 |
| check-* endpoints with pos+neg pairs | 14 |
| Error scenarios covered | 8 |
