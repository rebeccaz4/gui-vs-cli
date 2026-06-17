# CloudCompare Verifier Test Plan

## Module Overview

`cloudcompare.py` reads point cloud / mesh files and the CloudCompare Qt INI.
All verification is file-based — no running CloudCompare instance needed. The
file parsers use stdlib only (`struct` for binary PLY, `configparser` for INI,
text parsing for OBJ/ASCII).

Tests run against a live E2B sandbox (`desktop-all-apps`). The test script
creates multiple fixtures in `/home/user/` and runs every endpoint against
them.

## Test Groups

### G1 — Help / Usage
- `--help`, `-h`, `help`, no args prints usage and exits 0.
- **Expected assertions**: 2

### G2 — Error handling
- Unknown command → exit 1, valid JSON with `error`.
- Missing required argument → exit 1, valid JSON.
- Nonexistent file → JSON with `error`.
- Malformed PLY header → JSON with `error`.
- **Expected assertions**: 6

### G3 — Query endpoints on ASCII PLY
- `cloud-info ascii.ply` returns vertex/face count, bbox, properties.
- `ply-header ascii.ply` returns elements list.
- **Expected assertions**: 8

### G4 — Query endpoints on binary PLY
- `cloud-info bin.ply` returns correct counts and bbox (exercises struct parsing).
- `check-ply-format` reports `binary_little_endian`.
- **Expected assertions**: 6

### G5 — Query endpoints on rich PLY (colors + normals)
- `cloud-info` flags has_color, has_normal.
- `check-has-color`, `check-has-normals` true.
- **Expected assertions**: 6

### G6 — XYZ ASCII cloud parsing
- `cloud-info xyz.xyz` with 3-col file: counts, bbox, no color/intensity.
- `cloud-info rgb.xyz` with 6-col file: has_color true.
- `cloud-info intensity.xyz` with 4-col file: has_intensity true.
- **Expected assertions**: 10

### G7 — OBJ parsing
- `cloud-info mesh.obj` returns vertex/face/normal counts.
- `check-is-mesh` true.
- **Expected assertions**: 6

### G8 — Check-* positive cases
- check-file-exists true
- check-file-size match true
- check-point-count exact match
- check-point-count-at-least true
- check-face-count exact match
- check-bbox-within true (loose box)
- check-bbox-min-extent true
- check-has-color true on rgb fixture
- check-has-intensity true on intensity fixture
- check-has-normals true on OBJ
- check-ply-format ascii true
- check-ply-format binary_little_endian true
- check-format ply true
- check-format obj true
- check-format ascii true
- check-is-mesh true for PLY with faces
- check-is-mesh true for OBJ
- **Expected assertions**: 17

### G9 — Check-* negative cases
- check-file-exists false for nonexistent
- check-point-count wrong number false
- check-point-count-at-least too large false
- check-face-count wrong false
- check-bbox-within tight box false
- check-bbox-min-extent with huge min false
- check-has-color false on plain cloud
- check-has-intensity false on plain cloud
- check-has-normals false on plain PLY
- check-ply-format ascii false on binary file
- check-format ply false on .obj file
- check-is-mesh false for pure cloud
- **Expected assertions**: 12

### G10 — Config / recent files
- Write a fake `~/.config/CCorp/CloudCompare.conf` with a few sections and
  `recentFile0..3` entries.
- `settings` returns all sections.
- `check-setting` matches for known key, false for wrong value.
- `recent-files` lists expected files.
- `check-recent-file` positive and negative.
- **Expected assertions**: 10

### G11 — JSON validity sweep
- Every listed CLI command must produce JSON parseable by `json.loads`.
- **Expected assertions**: ~25

## Test Fixtures

| File | Format | Contents | Used by |
|---|---|---|---|
| `/home/user/cc_fixtures/ascii.ply` | ASCII PLY | 100 vertices in a diagonal line (0..99), no color, 50 faces forming a strip | G3, G8, G9, G11 |
| `/home/user/cc_fixtures/bin.ply` | Binary PLY little-endian | 64 vertices in a 4x4x4 grid, no color, no faces | G4, G8, G9, G11 |
| `/home/user/cc_fixtures/rich.ply` | ASCII PLY | 25 vertices with RGB color + normals, no faces | G5, G8, G9, G11 |
| `/home/user/cc_fixtures/plain.xyz` | ASCII XYZ 3-col | 20 points along random coords | G6, G8, G9, G11 |
| `/home/user/cc_fixtures/rgb.xyz` | ASCII XYZ 6-col | 20 points with RGB | G6, G8, G11 |
| `/home/user/cc_fixtures/intensity.xyz` | ASCII XYZ 4-col | 20 points with intensity | G6, G8, G11 |
| `/home/user/cc_fixtures/mesh.obj` | OBJ | 8 vertices forming a cube + 12 triangle faces + normals | G7, G8, G9, G11 |
| `/home/user/cc_fixtures/broken.ply` | Garbage | file that does not start with "ply" | G2 |
| `~/.config/CCorp/CloudCompare.conf` | Qt INI | Synthetic INI with `[General]` and recent files | G10, G11 |

## Edge Case / Error Matrix

| Scenario | Endpoint | Expected |
|---|---|---|
| App not running | (irrelevant — file-based) | n/a |
| Missing file argument | any query | exit 1 + error JSON |
| Nonexistent path | cloud-info | `{"error": "File not found: ..."}` |
| Broken PLY magic | cloud-info, ply-header | `{"error": "Not a PLY ..."}` |
| Unknown command | any | exit 1 + error JSON |
| Wrong numeric arg type | check-point-count foo bar | exit 1 + error JSON |
| Config missing | settings | `{"exists": false, "sections": {}}` |
| Config section missing | check-setting | `{"match": false, "error": "Section not found..."}` |

## Positive / Negative pairs

Every `check-*` endpoint has both a positive and a negative case, using
either a different fixture or a different argument, as enumerated in G8/G9.

## Summary

| Metric | Count |
|---|---|
| Test groups | 11 |
| Total assertions | ~108 |
| Test fixtures | 9 |
| check-* endpoints with pos+neg pairs | 15 |
| Error scenarios covered | 6 |
