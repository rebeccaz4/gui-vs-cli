# Blender Verifier

Programmatic state inspection for Blender .blend files in E2B sandbox.
Uses `blender -b` (headless) + `bpy` Python API for full introspection.

## Prerequisites

Blender must be installed. No running instance needed — all inspection is headless.

```bash
blender -b --version  # verify installation
```

## Verification Channel

| Channel | When to use |
|---------|------------|
| **bpy (headless)** | Everything: objects, materials, modifiers, animations, render settings |

All commands take a `.blend` file path as the first argument.

## Endpoint Reference

### Query Endpoints

#### `objects <blend_file>`
List all objects with type, location, visibility.
```bash
python3 /home/user/verifiers/blender.py objects /home/user/scene.blend
```
```json
{"objects": [{"name": "Cube", "type": "MESH", "location": [0,0,0], "visible": true}], "count": 3}
```

#### `object-info <blend_file> <object_name>`
Get detailed info: mesh data, modifiers, constraints, hierarchy.
```bash
python3 /home/user/verifiers/blender.py object-info /home/user/scene.blend Cube
```

#### `materials <blend_file>`
List all materials and their node trees.
```bash
python3 /home/user/verifiers/blender.py materials /home/user/scene.blend
```

#### `scene-info <blend_file>`
Scene metadata: render engine, resolution, frame range, active camera.
```bash
python3 /home/user/verifiers/blender.py scene-info /home/user/scene.blend
```

#### `collections <blend_file>`
List all collections and their objects.

#### `animations <blend_file> [object_name]`
Get animation keyframes for one or all objects.

#### `modifiers <blend_file> <object_name>`
Get detailed modifier info for an object. The `modifiers` list preserves stack order
(top-to-bottom) and each entry includes an `index` field. Type-specific fields:

| type | extra fields |
|------|------|
| `SUBSURF` | `levels`, `render_levels` |
| `ARRAY` | `count`, `use_relative_offset`, `use_constant_offset`, `use_object_offset`, `relative_offset_displace`, `constant_offset_displace`, `offset_object` |
| `BOOLEAN` | `operation`, `object` |
| `MIRROR` | `use_axis` (3-bool list), `mirror_object` |
| `BEVEL` | `width`, `segments`, `profile`, `limit_method`, `offset_type` |
| `ARMATURE` | `object` (target armature name), `use_vertex_groups`, `use_bone_envelopes` |
| `SOLIDIFY` | `thickness` |
| `LATTICE` | `object` |
| `NODES` | `node_group` |

#### `material-nodes <blend_file> <material_name>`
Get the node tree for a material: list of nodes (name, type, bl_idname, input default values, output linkage), and all internal links. Use to verify shader graphs (Principled BSDF inputs, Mix Shader factor, linkage to Material Output).

#### `compositor-nodes <blend_file>`
Get the scene's compositor node tree (requires `scene.use_nodes`). Returns nodes with common params (size_x/y, glare_type, blur_type, factor) + input defaults, plus links.

#### `geometry-nodes <blend_file> <object_name>`
Get all geometry-nodes (NODES) modifiers on an object, with each modifier's node group nodes and links.

#### `shape-keys <blend_file> <object_name>`
Get shape-key blocks on a mesh: name, value, slider_min/max, mute. `has_shape_keys` is false when the mesh has none.

#### `drivers <blend_file> <object_name>`
Get all drivers on an object plus its custom properties.

Returns:
- `drivers`: drivers on the object's own ID block (`obj.animation_data.drivers`). Each records `source="object"`, `data_path`, `array_index`, `expression`, `type`, and variables with their targets.
- `shape_key_drivers`: drivers on the mesh's shape-keys data block (`obj.data.shape_keys.animation_data.drivers`). Same shape as above with `source="shape_key"`. `data_path` looks like `key_blocks["Smile"].value`.
- `custom_properties`: `{prop_name: current_value}` dict.
- `custom_property_ranges`: `{prop_name: {min, max, soft_min, soft_max, default, description}}` for every custom property that has UI metadata (via `id_properties_ui`).

#### `armature-bones <blend_file> <armature_name>`
Get bones of an armature with parent chain, head/tail (local), and `use_connect`.

#### `pose-constraints <blend_file> <armature_name> <bone_name>`
Get constraints on a pose bone (IK, Copy Location, etc.) with `subtarget`, `chain_count`, `target`, `influence`.

#### `object-constraints <blend_file> <object_name>`
Get object-level constraints (Copy Rotation, Copy Location, Copy Scale, Child Of, Track To, Limit Rotation/Location/Scale, etc.). Each constraint returns:
- `name`, `type`
- `target` (name), `subtarget` (bone name for bone-targeted constraints)
- `influence`
- Copy/Limit axis toggles: `use_x`, `use_y`, `use_z`
- Child Of per-channel toggles: `use_location_x/y/z`, `use_rotation_x/y/z`, `use_scale_x/y/z`
- Limit values: `min_x/y/z`, `max_x/y/z`, `use_min_*`, `use_max_*`
- Track To: `track_axis`, `up_axis`

#### `rigid-body-info <blend_file>`
Scene gravity + `rigidbody_world` + per-object rigid body settings (type ACTIVE/PASSIVE, mass, collision_shape).

#### `particle-systems <blend_file> <object_name>`
Particle systems on an object with type (HAIR/EMITTER), count, frame range, lifetime, hair_length.

#### `cloth-settings <blend_file> <object_name>`
Lists cloth and collision modifiers on an object with cloth quality/mass.

#### `nla-tracks <blend_file> <object_name>`
NLA tracks on an object's animation_data, each with strips referencing an action and frame range; also lists all actions in file.

#### `grease-pencil <blend_file> <object_name>`
Grease Pencil object layers with frames (frame_number, stroke_count, point_counts per stroke).

#### `uv-maps <blend_file> <object_name>`
UV maps on a mesh (name, active, uv_count, nonzero_uv_count to detect unwrap).

### Composite Checks (Reward Signals)

| Command | Reward key | Example |
|---------|-----------|---------|
| `check-object-exists <file> <name>` | `exists` | `check-object-exists scene.blend Cube` |
| `check-object-type <file> <name> <type>` | `match` | `check-object-type scene.blend Cube MESH` |
| `check-object-count <file> <count>` | `match` | `check-object-count scene.blend 5` |
| `check-material-exists <file> <name>` | `exists` | `check-material-exists scene.blend Material` |
| `check-modifier-exists <file> <obj> <type>` | `exists` | `check-modifier-exists scene.blend Cube SUBSURF` |
| `check-animation-exists <file> <obj>` | `animated` | `check-animation-exists scene.blend Cube` |
| `check-render-engine <file> <engine>` | `match` | `check-render-engine scene.blend CYCLES` |
| `check-resolution <file> <w> <h>` | `match` | `check-resolution scene.blend 1920 1080` |
| `check-collection-exists <file> <name>` | `exists` | `check-collection-exists scene.blend MyCol` |
| `check-vertex-count <file> <obj> <count>` | `match` | `check-vertex-count scene.blend Cube 8` |
| `check-file-exists <path>` | `exists` | `check-file-exists /home/user/render.png` |
| `force-save-via-gui [blend_file]` | `saved` | `force-save-via-gui /home/user/scene.blend` |

## Common Verification Patterns

### Check if user added an object
```python
result = sandbox.commands.run("python3 /home/user/verifiers/blender.py check-object-exists /home/user/scene.blend Sphere")
data = json.loads(result.stdout)
reward = 1.0 if data["exists"] else 0.0
```

### Check if user applied a modifier
```python
result = sandbox.commands.run("python3 /home/user/verifiers/blender.py check-modifier-exists /home/user/scene.blend Cube SUBSURF")
data = json.loads(result.stdout)
reward = 1.0 if data["exists"] else 0.0
```

### Check if user set render resolution
```python
result = sandbox.commands.run("python3 /home/user/verifiers/blender.py check-resolution /home/user/scene.blend 1920 1080")
data = json.loads(result.stdout)
reward = 1.0 if data["match"] else 0.0
```

### Force-save before verification
```python
result = sandbox.commands.run("python3 /home/user/verifiers/blender.py force-save-via-gui /home/user/scene.blend")
data = json.loads(result.stdout)
# Run this before other check-* commands to flush the live Blender session to disk
```

### Check if user created animation
```python
result = sandbox.commands.run("python3 /home/user/verifiers/blender.py check-animation-exists /home/user/scene.blend Cube")
data = json.loads(result.stdout)
reward = 1.0 if data["animated"] else 0.0
```
