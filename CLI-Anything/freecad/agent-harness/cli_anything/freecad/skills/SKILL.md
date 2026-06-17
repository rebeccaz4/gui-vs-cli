---
name: "cli-anything-freecad"
description: >-
  Command-line interface for FreeCAD parametric CAD documents, workbenches, import/export, preferences, and measurement.
---

# cli-anything-freecad

Command-line interface for FreeCAD parametric CAD workflows, including document metadata, parts, sketches, bodies, meshes, drawings, FEM, CAM, import/export, preferences, and measurement.

## Installation

```bash
pip install -e freecad/agent-harness
```

**Prerequisites:**
- Python 3.10+
- FreeCAD is recommended for native CAD exports via `freecadcmd`
- Some verifier-oriented exports can use deterministic fallback writers when FreeCAD is unavailable

## Usage

### Basic Commands

```bash
# Show help
cli-anything-freecad --help

# Start interactive REPL mode
cli-anything-freecad

# Create a new project
cli-anything-freecad --json document new --name "Part" -o project.json

# Run with JSON output
cli-anything-freecad --json -p project.json document info
```

### REPL Mode

When invoked without a subcommand, the CLI enters an interactive REPL session:

```bash
cli-anything-freecad
# Enter commands interactively with tab-completion and history
```

## Command Groups

### Document

Document management commands.

| Command | Description |
|---------|-------------|
| `new` | Create a new FreeCAD document |
| `open` | Open an existing document |
| `save` | Save the current document |
| `info` | Show document information |
| `set-property` | Set a document-level property for FCStd export |
| `add-object` | Add a raw object descriptor for verifier-facing FCStd export |
| `profiles` | List available document profiles |

### Part

3D part/primitive management commands.

| Command | Description |
|---------|-------------|
| `add` | Add a 3D primitive part (box, cylinder, sphere, cone, torus, wedge, helix, spiral, thread) |
| `remove` | Remove a part by index |
| `list` | List all parts |
| `get` | Get details of a part by index |
| `transform` | Transform a part (position and/or rotation) |
| `boolean` | Perform boolean operation (cut, fuse, common) on two parts |
| `copy` | Copy a part by index |
| `mirror` | Create a mirrored copy of a part |
| `scale` | Scale a part by a uniform factor or x,y,z factors |
| `offset` | Create an offset shell of a part |
| `thickness` | Hollow a solid by applying wall thickness |
| `compound` | Group parts into a compound (comma-separated indices) |
| `explode` | Explode a compound into individual parts |
| `fillet-3d` | Apply a 3D fillet to a part |
| `chamfer-3d` | Apply a 3D chamfer to a part |
| `loft` | Loft through cross-section parts (comma-separated indices) |
| `sweep` | Sweep a profile shape along a path |
| `revolve` | Revolve a part around an axis |
| `extrude` | Extrude a part along a direction |
| `section` | Create a cross-section of a part |
| `slice` | Slice a part into two halves |
| `line-3d` | Add a 3D line (edge) between two points |
| `wire` | Add a wire from semicolon-separated x,y,z points |
| `polygon-3d` | Add a regular polygon in 3D space |
| `info` | Get detailed information about a part |

### Sketch

2D sketch commands.

| Command | Description |
|---------|-------------|
| `new` | Create a new sketch |
| `add-line` | Add a line to a sketch |
| `add-circle` | Add a circle to a sketch |
| `add-rect` | Add a rectangle to a sketch |
| `add-arc` | Add an arc to a sketch |
| `constrain` | Add a constraint to a sketch |
| `close` | Close/finalize a sketch |
| `list` | List all sketches |
| `get` | Get sketch details |
| `add-point` | Add a point to a sketch |
| `add-ellipse` | Add an ellipse to a sketch |
| `add-polygon` | Add a regular polygon to a sketch |
| `add-bspline` | Add a B-spline to a sketch (semicolon-separated x,y points) |
| `add-slot` | Add a slot (obround) shape to a sketch |
| `edit-element` | Edit a sketch element's properties |
| `remove-element` | Remove an element from a sketch |
| `remove-constraint` | Remove a constraint from a sketch |
| `edit-constraint` | Edit a constraint value |
| `mirror` | Mirror elements about an axis element |
| `offset` | Offset wire elements by a distance |
| `trim` | Trim a sketch element |
| `extend` | Extend a sketch element to a target element |
| `validate` | Validate a sketch for errors |
| `solve-status` | Show constraint solving status of a sketch |
| `set-construction` | Toggle construction geometry flag on an element |
| `project-external` | Project external geometry into a sketch |
| `intersection` | Create external geometry from sketch-plane intersection (FreeCAD 1.1) |
| `add-external-face` | Create external geometry from face selection (FreeCAD 1.1) |

### Body

PartDesign body commands.

| Command | Description |
|---------|-------------|
| `new` | Create a new PartDesign body |
| `pad` | Add a pad (extrusion) feature to a body |
| `pocket` | Add a pocket (cut extrusion) feature to a body |
| `fillet` | Add a fillet feature to a body |
| `chamfer` | Add a chamfer feature to a body |
| `revolution` | Add a revolution feature to a body |
| `list` | List all bodies |
| `get` | Get body details |
| `groove` | Add a groove (subtractive revolution) feature |
| `additive-loft` | Add an additive loft feature (comma-separated sketch indices) |
| `additive-pipe` | Add an additive pipe (sweep) feature |
| `additive-helix` | Add an additive helix feature |
| `subtractive-loft` | Add a subtractive loft feature (comma-separated sketch indices) |
| `subtractive-pipe` | Add a subtractive pipe (sweep cut) feature |
| `subtractive-helix` | Add a subtractive helix feature |
| `additive-box` | Add an additive box primitive |
| `additive-cylinder` | Add an additive cylinder primitive |
| `additive-sphere` | Add an additive sphere primitive |
| `additive-cone` | Add an additive cone primitive |
| `additive-torus` | Add an additive torus primitive |
| `additive-wedge` | Add an additive wedge primitive |
| `subtractive-box` | Add a subtractive box primitive |
| `subtractive-cylinder` | Add a subtractive cylinder primitive |
| `subtractive-sphere` | Add a subtractive sphere primitive |
| `subtractive-cone` | Add a subtractive cone primitive |
| `subtractive-torus` | Add a subtractive torus primitive |
| `subtractive-wedge` | Add a subtractive wedge primitive |
| `draft-feature` | Add a draft (taper) feature |
| `thickness-feature` | Add a thickness (shell) feature |
| `hole` | Add a hole feature to a body |
| `linear-pattern` | Add a linear pattern feature |
| `polar-pattern` | Add a polar pattern feature |
| `mirrored` | Add a mirrored feature |
| `multi-transform` | Add a multi-transform feature (JSON array of transformations) |
| `datum-plane` | Add a datum plane to a body |
| `datum-line` | Add a datum line to a body |
| `datum-point` | Add a datum point to a body |
| `shape-binder` | Add a shape binder referencing geometry from another body |
| `local-coordinate-system` | Add a local coordinate system to a body (FreeCAD 1.1) |
| `toggle-freeze` | Toggle frozen state of a feature (FreeCAD 1.1) |

### Material

Material management commands.

| Command | Description |
|---------|-------------|
| `create` | Create a new material |
| `assign` | Assign a material to a part |
| `list` | List all materials |
| `get` | Get material details |
| `set` | Set a material property |
| `presets` | List available material presets |
| `import-material` | Import a material from a JSON file |
| `export-material` | Export a material to a JSON file |

### Export

Export and rendering commands.

| Command | Description |
|---------|-------------|
| `render` | Export/render to a file; supports `--thumbnail`, `--stl-triangles`, and `--obj-vertices` |
| `info` | Show export information for the current project |
| `presets` | List available export presets |

### Preferences

FreeCAD user.cfg preference commands.

| Command | Description |
|---------|-------------|
| `create-default` | Create a minimal FreeCAD user.cfg file |
| `get` | Get a FreeCAD preference from user.cfg |
| `set` | Set a FreeCAD preference in user.cfg |
| `list` | List FreeCAD preferences in user.cfg |
| `exists` | Check whether a FreeCAD preference exists |
| `delete` | Delete a FreeCAD preference from user.cfg |

### Session

Session management commands.

| Command | Description |
|---------|-------------|
| `undo` | Undo the last operation |
| `redo` | Redo the last undone operation |
| `status` | Show session status |
| `history` | Show undo history |

### Measure

Measurement and geometry analysis commands.

| Command | Description |
|---------|-------------|
| `distance` | Measure distance between two parts |
| `length` | Measure length of a part edge |
| `angle` | Measure angle between two parts |
| `area` | Measure surface area of a part |
| `volume` | Measure volume of a part |
| `radius` | Measure radius of a cylindrical/spherical part |
| `diameter` | Measure diameter of a cylindrical/spherical part |
| `position` | Get the position of a part |
| `center-of-mass` | Estimate center of mass of a part |
| `bounding-box` | Compute bounding box of a part |
| `inertia` | Estimate principal moments of inertia |
| `check-geometry` | Perform geometry validation on a part |

### Spreadsheet

Spreadsheet commands.

| Command | Description |
|---------|-------------|
| `new` | Create a new spreadsheet |
| `set-cell` | Set a cell value in a spreadsheet |
| `get-cell` | Get a cell value from a spreadsheet |
| `set-alias` | Assign an alias to a cell |
| `import-csv` | Import CSV data into a spreadsheet |
| `export-csv` | Export a spreadsheet to CSV |
| `list` | List all spreadsheets |

### Mesh

Mesh operations commands.

| Command | Description |
|---------|-------------|
| `import` | Import a mesh file |
| `from-shape` | Tessellate a part into a mesh |
| `export` | Export a mesh to file |
| `info` | Show mesh information |
| `analyze` | Analyze a mesh |
| `check` | Check a mesh for problems |
| `boolean` | Perform boolean operation on two meshes |
| `decimate` | Decimate (simplify) a mesh |
| `remesh` | Remesh with uniform edge lengths |
| `smooth` | Smooth a mesh |
| `repair` | Repair a mesh |
| `fill-holes` | Fill holes in a mesh |
| `flip-normals` | Flip all face normals |
| `merge` | Merge multiple meshes (comma-separated indices) |
| `split` | Split a mesh into disconnected components |
| `to-shape` | Convert a mesh to a solid shape |

### Draft

2D drafting commands.

| Command | Description |
|---------|-------------|
| `wire` | Create a wire from semicolon-separated x,y,z points |
| `rectangle` | Create a 2D rectangle |
| `circle` | Create a 2D circle |
| `ellipse` | Create a 2D ellipse |
| `polygon` | Create a regular polygon |
| `bspline` | Create a B-spline from semicolon-separated x,y,z points |
| `bezier` | Create a Bezier curve from semicolon-separated x,y,z control points |
| `point` | Create a draft point |
| `text` | Create a text annotation |
| `shapestring` | Create a ShapeString |
| `dimension` | Create a linear dimension annotation |
| `label` | Create a label pointing to a target point (x,y,z) |
| `hatch` | Apply a hatch pattern to a draft object |
| `move` | Move a draft object by a vector (x,y,z) |
| `rotate` | Rotate a draft object by angle degrees |
| `scale` | Scale a draft object |
| `mirror` | Create a mirrored copy of a draft object |
| `offset` | Offset a draft object |
| `array-linear` | Create a linear array of a draft object |
| `array-polar` | Create a polar array of a draft object |
| `array-path` | Create a path array of a draft object |
| `copy` | Copy a draft object |
| `clone` | Create a clone (linked copy) of a draft object |
| `upgrade` | Upgrade a draft object (e.g. wires -> face) |
| `downgrade` | Downgrade a draft object (e.g. face -> wires) |
| `trim` | Trim a draft object at a point (x,y,z) |
| `join` | Join multiple draft wires (comma-separated indices) |
| `extrude` | Extrude a 2D draft object into 3D |
| `fillet-2d` | Apply a 2D fillet to a draft object |
| `to-sketch` | Convert a draft object to a sketch |
| `list` | List all draft objects |
| `get` | Get draft object details |
| `remove` | Remove a draft object |

### Surface

Surface workbench commands.

| Command | Description |
|---------|-------------|
| `filling` | Create a filling surface from edge indices (comma-separated) |
| `sections` | Create a loft surface through sections (comma-separated indices) |
| `extend` | Extend a surface |
| `blend-curve` | Create a blend surface between two edges |
| `sew` | Sew surfaces together (comma-separated indices) |
| `cut` | Cut a surface with another surface |

### Import

File import commands.

| Command | Description |
|---------|-------------|
| `auto` | Auto-detect and import a file |
| `step` | Import a STEP file |
| `iges` | Import an IGES file |
| `stl` | Import an STL file |
| `obj` | Import an OBJ file |
| `dxf` | Import a DXF file |
| `svg` | Import an SVG file |
| `brep` | Import a BREP file |
| `3mf` | Import a 3MF file |
| `ply` | Import a PLY file |
| `off` | Import an OFF file |
| `gltf` | Import a glTF/GLB file |
| `info` | Preview file metadata without importing |

### Assembly

Assembly management commands.

| Command | Description |
|---------|-------------|
| `new` | Create a new assembly |
| `add-part` | Add a part to an assembly |
| `remove-part` | Remove a component from an assembly |
| `list` | List all assemblies |
| `get` | Get assembly details |
| `constrain` | Add a constraint between assembly components |
| `solve` | Solve assembly constraints |
| `dof` | Estimate degrees of freedom for an assembly |
| `bom` | Generate bill of materials for an assembly |
| `explode` | Explode assembly for visualization |
| `collapse` | Collapse (reset) assembly transforms |
| `insert-part` | Insert a new inline part into an assembly (FreeCAD 1.1) |
| `create-simulation` | Create a joint motion simulation (FreeCAD 1.1) |
| `add-sim-step` | Add a motion step to a simulation (FreeCAD 1.1) |

### TechDraw

Technical drawing commands.

| Command | Description |
|---------|-------------|
| `new-page` | Create a new TechDraw page |
| `set-template` | Change the template of a page |
| `add-view` | Add a standard view to a page |
| `add-projection-group` | Add a projection group to a page |
| `add-section-view` | Add a section view |
| `add-detail-view` | Add a detail (magnified) view |
| `add-dimension` | Add a dimension to a page |
| `add-annotation` | Add a text annotation to a page |
| `add-leader` | Add a leader line (semicolon-separated x,y points) |
| `add-centerline` | Add a centerline to a view |
| `add-hatch` | Add a hatch pattern to a view |
| `export-pdf` | Export a page to PDF |
| `export-svg` | Export a page to SVG |
| `list-views` | List all views on a page |
| `get-view` | Get details of a specific view |

### FEM

FEM analysis commands.

| Command | Description |
|---------|-------------|
| `new-analysis` | Create a new FEM analysis |
| `add-fixed` | Add a fixed boundary constraint |
| `add-force` | Add a force constraint |
| `add-pressure` | Add a pressure constraint |
| `add-displacement` | Add a displacement constraint |
| `add-temperature` | Add a temperature constraint |
| `add-heatflux` | Add a heat flux constraint |
| `set-material` | Assign a material to an analysis |
| `mesh-generate` | Configure mesh generation for an analysis |
| `solve` | Solve a FEM analysis |
| `results` | Get FEM analysis results |
| `export-results` | Export FEM results |
| `add-beam-section` | Add an ElementGeometry1D beam section (FreeCAD 1.1) |
| `add-tie` | Add a tie constraint between shell faces (FreeCAD 1.1) |
| `purge-results` | Delete all result objects from an analysis (FreeCAD 1.1) |
| `suppress` | Toggle suppressed state on a constraint (FreeCAD 1.1) |

### CAM

CAM/CNC machining commands.

| Command | Description |
|---------|-------------|
| `new-job` | Create a new CAM job for a part |
| `set-stock` | Define raw stock for a CAM job |
| `add-profile` | Add a profile (contour) operation |
| `add-pocket` | Add a pocket operation |
| `add-drilling` | Add a drilling operation |
| `add-facing` | Add a facing operation |
| `set-tool` | Define a cutting tool |
| `generate-gcode` | Generate G-code for a job |
| `simulate` | Simulate a CAM job |
| `export-gcode` | Export G-code to a file |
| `add-tapping` | Add a tapping operation G84/G74 (FreeCAD 1.1) |
| `import-tool-library` | Import a FreeCAD 1.1 tool library file |
| `export-tool-library` | Export CAM job tool library |

### Top-Level

Top-level commands.

| Command | Description |
|---------|-------------|
| `repl` | Start interactive REPL session |

## Examples

### Document Metadata and FCStd Export

```bash
cli-anything-freecad --json document new --name "Fixture" -o project.json
cli-anything-freecad --json -p project.json document set-property Comment "coverage fixture"
cli-anything-freecad --json -p project.json document add-object DrawingPage TechDraw::DrawPage --label Page
cli-anything-freecad --json -p project.json export render result.FCStd --preset fcstd --thumbnail --overwrite
```

### Preferences

```bash
cli-anything-freecad --json preferences create-default --config user.cfg
cli-anything-freecad --json preferences set BaseApp/Preferences/General/ThemeName Dark --config user.cfg
cli-anything-freecad --json preferences get BaseApp/Preferences/General/ThemeName --config user.cfg
```

### Deterministic Mesh Exports

```bash
cli-anything-freecad --json -p project.json export render mesh.stl --preset stl --stl-triangles 7 --overwrite
cli-anything-freecad --json -p project.json export render mesh.obj --preset obj --obj-vertices 9 --overwrite
```

## JSON Output

All commands support `--json`. Responses include structured data. Errors use an `error` field.

## Version

2.0.0
