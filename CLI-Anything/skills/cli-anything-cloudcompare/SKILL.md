---
name: "cli-anything-cloudcompare"
description: >-
  Command-line interface for CloudCompare project management, point-cloud and mesh processing, verifier-readable inspection, fixture generation, and config state.
---

# cli-anything-cloudcompare

Agent-friendly command-line harness for CloudCompare point-cloud and mesh workflows. It supports project/session management, CloudCompare processing commands, pure-Python file inspection, deterministic fixture generation, and CloudCompare config editing.

## Installation

```bash
pip install cli-anything-cloudcompare
```

**Prerequisites:**
- Python 3.10+
- CloudCompare is required for processing commands in `cloud`, `mesh`, `distance`, `transform`, and `export`
- `fixture`, `inspect`, and `config` commands do not require the CloudCompare binary

## Usage

### Basic Commands

```bash
# Show help
cli-anything-cloudcompare --help

# Start interactive REPL mode
cli-anything-cloudcompare

# Create a new project
cli-anything-cloudcompare project new -o project.json

# Run with JSON output
cli-anything-cloudcompare --json inspect cloud-info scan.ply
```

## Command Groups

### Project

Project management commands.

| Command | Description |
|---------|-------------|
| `new` | Create a new project |
| `info` | Show project information |
| `status` | Show quick project status |

### Cloud

Point cloud operations.

| Command | Description |
|---------|-------------|
| `add` | Add a cloud to the project |
| `list` | List project clouds |
| `convert` | Convert a cloud from one format to another |
| `subsample` | Subsample a cloud |
| `crop` | Crop a cloud to a bounding box |
| `normals` | Compute normals |
| `invert-normals` | Flip normals |
| `roughness` | Compute roughness scalar field |
| `density` | Compute density scalar field |
| `curvature` | Compute curvature scalar field |
| `filter-sor` | Run statistical outlier removal |
| `noise-filter` | Run PCL noise filtering |
| `filter-csf` | Run CSF ground filtering |
| `sf-from-coord` | Convert a coordinate axis to a scalar field |
| `filter-sf` | Filter by scalar field value range |
| `sf-filter-z` | Filter by Z height range |
| `sf-to-rgb` | Convert scalar field to RGB |
| `rgb-to-sf` | Convert RGB to scalar field |
| `segment-cc` | Extract connected components |
| `mesh-delaunay` | Build a Delaunay mesh |
| `merge` | Merge all project clouds |

### Inspect

Verifier-readable file inspection commands.

| Command | Description |
|---------|-------------|
| `cloud-info` | Parse PLY, OBJ, or ASCII cloud metadata |
| `ply-header` | Parse a PLY header |
| `file-exists` | Check file existence and size |
| `file-size` | Check minimum file size |
| `point-count` | Check exact point or vertex count |
| `point-count-at-least` | Check minimum point or vertex count |
| `face-count` | Check exact face count |
| `bbox-within` | Check bbox containment |
| `bbox-min-extent` | Check bbox extent on an axis |
| `has-color` | Check color channel or property |
| `has-intensity` | Check intensity channel or property |
| `has-normals` | Check normal channel or property |
| `ply-format` | Check PLY encoding |
| `format` | Check actual file format |
| `is-mesh` | Check whether a file contains faces |

### Fixture

Deterministic artifact generation commands.

| Command | Description |
|---------|-------------|
| `ascii-cloud` | Write an ASCII XYZ/ASC/TXT cloud |
| `ply-cloud` | Write a PLY cloud or simple mesh |
| `obj-mesh` | Write an OBJ mesh |

### Config

CloudCompare config file commands.

| Command | Description |
|---------|-------------|
| `settings` | Dump config settings |
| `set` | Set a config value |
| `check-setting` | Check a config value |
| `recent-files` | List recent files |
| `add-recent` | Add a recent-file entry |
| `check-recent-file` | Check recent-file membership |

### Distance

Distance computation commands.

| Command | Description |
|---------|-------------|
| `c2c` | Compute cloud-to-cloud distances |
| `c2m` | Compute cloud-to-mesh distances |

### Transform

Transformation and registration commands.

| Command | Description |
|---------|-------------|
| `icp` | Run ICP alignment |
| `apply` | Apply a 4x4 transform matrix |

### Mesh

Mesh operations.

| Command | Description |
|---------|-------------|
| `add` | Add a mesh to the project |
| `list` | List project meshes |
| `sample` | Sample a point cloud from a mesh |

### Export

Export commands.

| Command | Description |
|---------|-------------|
| `cloud` | Export a cloud |
| `mesh` | Export a mesh |
| `batch` | Export all project clouds |
| `formats` | List export presets |

### Session

Session management commands.

| Command | Description |
|---------|-------------|
| `save` | Save the current project |
| `history` | Show operation history |
| `undo` | Soft undo the last operation |
| `set-format` | Set default export formats |

### Other

| Command | Description |
|---------|-------------|
| `info` | Show CloudCompare installation information |
| `repl` | Start interactive REPL mode |

## Examples

```bash
cli-anything-cloudcompare fixture ascii-cloud /tmp/intensity.xyz --count 20 --intensity

cli-anything-cloudcompare --project survey.json cloud add scan.ply -l scan
```

## Output Formats

All commands support human-readable output by default and machine-readable JSON with `--json`:

```bash
cli-anything-cloudcompare --json inspect cloud-info scan.ply
```
