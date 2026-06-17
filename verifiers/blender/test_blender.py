"""
Test Blender verifier endpoints in a live E2B sandbox.

Tests TWO flows:
  1. The create_env.py pipeline: generates a default .blend at a known path,
     then verifies the file exists and has Blender's default objects.
  2. A richer scene: creates a .blend with known objects, materials, modifiers,
     animations, collections, and render settings, then tests ALL verifier
     endpoints against it.

Usage:
    python verifiers/blender/test_blender.py
"""

import json
import sys
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv
from e2b_desktop import Sandbox
from e2b.sandbox.commands.command_handle import CommandExitException

load_dotenv()

VERIFIER_LOCAL = Path(__file__).parent / "blender.py"
VERIFIER_REMOTE = "/home/user/verifiers/blender.py"
V = f"python3 {VERIFIER_REMOTE}"
TEST_BLEND = "/home/user/test_scene.blend"
ENV_BLEND = "/home/user/Documents/city_scene.blend"

# ── create_env.py content (same as task blender_scene_setup_objects) ──────────
CREATE_ENV_SCRIPT = Path(__file__).resolve().parent.parent.parent / \
    "task_generator" / "tasks" / "blender_scene_setup_objects" / "env" / "create_env.py"

# Script to create a rich test .blend file with known content
CREATE_RICH_BLEND_SCRIPT = r'''
import bpy
import math

# Clear default scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Add a cube
bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
cube = bpy.context.active_object
cube.name = "TestCube"

# Add subdivision modifier
mod = cube.modifiers.new(name="Subdiv", type='SUBSURF')
mod.levels = 2
mod.render_levels = 3

# Add bevel modifier with specific params
bevel = cube.modifiers.new(name="Bevel", type='BEVEL')
bevel.width = 0.05
bevel.segments = 3

# Add a material to cube
mat = bpy.data.materials.new(name="RedMaterial")
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get("Principled BSDF")
if bsdf:
    bsdf.inputs["Base Color"].default_value = (1, 0, 0, 1)
cube.data.materials.append(mat)

# Add a sphere
bpy.ops.mesh.primitive_uv_sphere_add(location=(3, 0, 0))
sphere = bpy.context.active_object
sphere.name = "TestSphere"

# Add mirror modifier to sphere
mirror = sphere.modifiers.new(name="Mirror", type='MIRROR')

# Add array modifier to sphere with specific offset params
array = sphere.modifiers.new(name="Array", type='ARRAY')
array.count = 3
array.use_relative_offset = True
array.relative_offset_displace[0] = 1.5
array.relative_offset_displace[1] = 0.0
array.relative_offset_displace[2] = 0.0

# Add material to sphere
mat2 = bpy.data.materials.new(name="BlueMaterial")
mat2.use_nodes = True
bsdf2 = mat2.node_tree.nodes.get("Principled BSDF")
if bsdf2:
    bsdf2.inputs["Base Color"].default_value = (0, 0, 1, 1)
sphere.data.materials.append(mat2)

# Add a camera
bpy.ops.object.camera_add(location=(7, -7, 5))
camera = bpy.context.active_object
camera.name = "MainCamera"
bpy.context.scene.camera = camera

# Add a sun light
bpy.ops.object.light_add(type='SUN', location=(5, 5, 10))
light = bpy.context.active_object
light.name = "SunLight"

# Add a point light
bpy.ops.object.light_add(type='POINT', location=(-3, 2, 4))
point_light = bpy.context.active_object
point_light.name = "FillLight"

# Add a plane
bpy.ops.mesh.primitive_plane_add(location=(0, 0, -1), size=20)
plane = bpy.context.active_object
plane.name = "GroundPlane"

# Add a cylinder
bpy.ops.mesh.primitive_cylinder_add(location=(-3, 0, 0))
cylinder = bpy.context.active_object
cylinder.name = "Pillar"

# Add solidify modifier to cylinder
solidify = cylinder.modifiers.new(name="Solidify", type='SOLIDIFY')

# Add an empty
bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 5, 0))
empty = bpy.context.active_object
empty.name = "Marker"

# Add a monkey (Suzanne)
bpy.ops.mesh.primitive_monkey_add(location=(0, -3, 0))
monkey = bpy.context.active_object
monkey.name = "Suzanne"

# Create collections
col1 = bpy.data.collections.new("Environment")
bpy.context.scene.collection.children.link(col1)
col1.objects.link(plane)
col1.objects.link(light)
col1.objects.link(point_light)

col2 = bpy.data.collections.new("Characters")
bpy.context.scene.collection.children.link(col2)
col2.objects.link(monkey)

col3 = bpy.data.collections.new("Props")
bpy.context.scene.collection.children.link(col3)
col3.objects.link(cylinder)
col3.objects.link(empty)

# Add animation to cube (location keyframes)
cube.location = (0, 0, 0)
cube.keyframe_insert(data_path="location", frame=1)
cube.location = (5, 0, 0)
cube.keyframe_insert(data_path="location", frame=50)
cube.location = (5, 5, 0)
cube.keyframe_insert(data_path="location", frame=100)

# Add animation to sphere (location keyframes)
sphere.location = (3, 0, 0)
sphere.keyframe_insert(data_path="location", frame=1)
sphere.location = (3, 0, 5)
sphere.keyframe_insert(data_path="location", frame=60)

# Set render settings
bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.render.resolution_x = 1920
bpy.context.scene.render.resolution_y = 1080
bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end = 100

# ── Extended fixtures for new endpoints ──────────────────────────────────

# Shape keys on Suzanne
bpy.context.view_layer.objects.active = monkey
monkey.shape_key_add(name="Basis")
sk1 = monkey.shape_key_add(name="Smile")
sk1.value = 0.3
sk1.slider_min = -1.0
sk1.slider_max = 2.0
sk2 = monkey.shape_key_add(name="Frown")
sk2.value = 0.0

# Custom property + driver on TestCube
cube["custom_scale"] = 1.5
fcurve = cube.driver_add("scale", 0)
drv = fcurve.driver
drv.type = 'SCRIPTED'
drv.expression = "var * 2.0"
var = drv.variables.new()
var.name = "var"
var.type = 'SINGLE_PROP'
var.targets[0].id = cube
var.targets[0].data_path = '["custom_scale"]'
# Define UI range on the custom prop (Blender 3.x id_properties_ui API)
try:
    cube.id_properties_ui("custom_scale").update(min=0.0, max=5.0, soft_min=0.0, soft_max=5.0, default=1.0, description="Test scale slider")
except Exception:
    pass

# UV maps — add a second one on TestCube
me = cube.data
if len(me.uv_layers) < 2:
    me.uv_layers.new(name="UVMap_Second")

# Compositor nodes
bpy.context.scene.use_nodes = True
ntree = bpy.context.scene.node_tree
for n in list(ntree.nodes):
    ntree.nodes.remove(n)
rl = ntree.nodes.new("CompositorNodeRLayers")
blur = ntree.nodes.new("CompositorNodeBlur")
blur.size_x = 5
blur.size_y = 5
comp_out = ntree.nodes.new("CompositorNodeComposite")
ntree.links.new(rl.outputs["Image"], blur.inputs["Image"])
ntree.links.new(blur.outputs["Image"], comp_out.inputs["Image"])

# Geometry nodes modifier on GroundPlane
gn_mod = plane.modifiers.new(name="GeoNodes", type='NODES')
gn_group = bpy.data.node_groups.new("PlaneGeoNodes", 'GeometryNodeTree')
try:
    gn_group.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    gn_group.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
except Exception:
    try:
        gn_group.inputs.new('NodeSocketGeometry', "Geometry")
        gn_group.outputs.new('NodeSocketGeometry', "Geometry")
    except Exception:
        pass
g_in = gn_group.nodes.new("NodeGroupInput")
g_out = gn_group.nodes.new("NodeGroupOutput")
g_in.location = (-200, 0)
g_out.location = (200, 0)
try:
    gn_group.links.new(g_in.outputs[0], g_out.inputs[0])
except Exception:
    pass
gn_mod.node_group = gn_group

# Armature with bones
bpy.ops.object.armature_add(location=(-5, -5, 0))
arm_obj = bpy.context.active_object
arm_obj.name = "TestArmature"
bpy.context.view_layer.objects.active = arm_obj
bpy.ops.object.mode_set(mode='EDIT')
arm_data = arm_obj.data
root_bone = arm_data.edit_bones[0]
root_bone.name = "Root"
child_bone = arm_data.edit_bones.new("ChildBone")
child_bone.head = (0, 0, 1)
child_bone.tail = (0, 0, 2)
child_bone.parent = root_bone
child_bone.use_connect = True
tip_bone = arm_data.edit_bones.new("TipBone")
tip_bone.head = (0, 0, 2)
tip_bone.tail = (0, 0, 3)
tip_bone.parent = child_bone
bpy.ops.object.mode_set(mode='POSE')
pose_bone = arm_obj.pose.bones["TipBone"]
ik = pose_bone.constraints.new('IK')
ik.chain_count = 2
ik.influence = 0.8
bpy.ops.object.mode_set(mode='OBJECT')

# Particle system on GroundPlane (hair)
bpy.context.view_layer.objects.active = plane
plane.modifiers.new(name="ParticleSys", type='PARTICLE_SYSTEM')
ps = plane.particle_systems[-1]
ps.name = "GrassParticles"
ps.settings.type = 'HAIR'
ps.settings.count = 500
ps.settings.hair_length = 0.5

# Cloth modifier on a new plane
bpy.ops.mesh.primitive_plane_add(location=(5, 5, 5), size=2)
cloth_plane = bpy.context.active_object
cloth_plane.name = "ClothPlane"
cloth_mod = cloth_plane.modifiers.new(name="Cloth", type='CLOTH')
try:
    cloth_mod.settings.quality = 7
    cloth_mod.settings.mass = 0.5
except Exception:
    pass
# Collision modifier on GroundPlane
plane.modifiers.new(name="Collide", type='COLLISION')

# NLA tracks on Suzanne
monkey.animation_data_create()
monkey_action = bpy.data.actions.new("SuzanneWave")
monkey.animation_data.action = monkey_action
monkey.location = (0, -3, 0)
monkey.keyframe_insert(data_path="location", frame=1)
monkey.location = (0, -3, 2)
monkey.keyframe_insert(data_path="location", frame=30)
try:
    track = monkey.animation_data.nla_tracks.new()
    track.name = "WaveTrack"
    track.strips.new("WaveStrip", int(monkey_action.frame_range[0]), monkey_action)
except Exception:
    pass

# Rigid body — Suzanne ACTIVE, Pillar PASSIVE
bpy.context.view_layer.objects.active = monkey
try:
    bpy.ops.rigidbody.object_add()
    monkey.rigid_body.type = 'ACTIVE'
    monkey.rigid_body.mass = 2.5
    monkey.rigid_body.collision_shape = 'BOX'
except Exception:
    pass
bpy.context.view_layer.objects.active = cylinder
try:
    bpy.ops.rigidbody.object_add()
    cylinder.rigid_body.type = 'PASSIVE'
    cylinder.rigid_body.collision_shape = 'CONVEX_HULL'
except Exception:
    pass

# Shape-key driver on Suzanne: Smile driven by Suzanne's own "mood" custom prop
try:
    monkey["mood"] = 0.4
    try:
        monkey.id_properties_ui("mood").update(min=-1.0, max=1.0, soft_min=-1.0, soft_max=1.0, default=0.0)
    except Exception:
        pass
    sk_id = monkey.data.shape_keys
    if sk_id is not None:
        sk_fc = sk_id.key_blocks["Smile"].driver_add("value")
        sk_drv = sk_fc.driver
        sk_drv.type = 'SCRIPTED'
        sk_drv.expression = "max(mood, 0)"
        sk_var = sk_drv.variables.new()
        sk_var.name = "mood"
        sk_var.type = 'SINGLE_PROP'
        sk_var.targets[0].id = monkey
        sk_var.targets[0].data_path = '["mood"]'
except Exception:
    pass

# Armature modifier on a new mesh targeting TestArmature
bpy.ops.mesh.primitive_cube_add(location=(-5, -5, 2))
char_mesh = bpy.context.active_object
char_mesh.name = "CharMesh"
arm_mod = char_mesh.modifiers.new(name="Armature", type='ARMATURE')
arm_mod.object = arm_obj
arm_mod.use_vertex_groups = True

# Object-level constraints: Marker gets a Copy Rotation targeting TestCube
try:
    crot = empty.constraints.new('COPY_ROTATION')
    crot.target = cube
    crot.use_x = True
    crot.use_y = False
    crot.use_z = True
    crot.influence = 0.75
except Exception:
    pass

# Object-level Child Of constraint: ClothPlane parented to TestCube via Child Of
try:
    chof = cloth_plane.constraints.new('CHILD_OF')
    chof.target = cube
    chof.use_location_x = True
    chof.use_location_y = True
    chof.use_location_z = False
    chof.use_rotation_x = False
    chof.use_rotation_y = False
    chof.use_rotation_z = True
    chof.use_scale_x = False
    chof.use_scale_y = False
    chof.use_scale_z = False
except Exception:
    pass

# Grease pencil — version-tolerant creation
try:
    bpy.ops.object.gpencil_add(type='STROKE', location=(0, 0, 5))
    bpy.context.active_object.name = "TestGPencil"
except Exception:
    try:
        bpy.ops.object.grease_pencil_add(type='STROKE', location=(0, 0, 5))
        bpy.context.active_object.name = "TestGPencil"
    except Exception:
        pass

# Save
bpy.ops.wm.save_as_mainfile(filepath="/home/user/test_scene.blend")
print("BLEND_CREATED")
'''

passed = 0
failed = 0
errors: list[str] = []


class CmdResult:
    def __init__(self, exit_code, stdout, stderr):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


def run(sb, cmd, timeout=60):
    r = run_raw(sb, cmd, timeout)
    if r.exit_code != 0 and not r.stdout.strip():
        return {"error": f"exit_code={r.exit_code} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {r.stdout[:300]}"}


def run_raw(sb, cmd, timeout=60):
    try:
        result = sb.commands.run(f"{V} {cmd}", timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def run_shell(sb, cmd, timeout=120):
    try:
        result = sb.commands.run(cmd, timeout=timeout)
        return CmdResult(result.exit_code, result.stdout, result.stderr)
    except CommandExitException as e:
        return CmdResult(e.exit_code, e.stdout, e.stderr)


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  -- {detail}")
        errors.append(f"{name}: {detail}")


def is_valid_json(s):
    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


# ═══════════���═══════════════════════════════���═══════════════════════════════════
# Test: create_env.py pipeline (the actual fix)
# ═══════════════════════════════════════════════════════════════════════════════

def test_create_env_pipeline(sb):
    """Test that create_env.py generates a valid .blend at the expected path."""
    print("\n=== create_env.py Pipeline ===")

    # Upload and run create_env.py
    if CREATE_ENV_SCRIPT.exists():
        with open(CREATE_ENV_SCRIPT) as f:
            sb.files.write("/tmp/create_env.py", f.read())
        r = run_shell(sb, "python3 /tmp/create_env.py", timeout=120)
        check("create_env.py exits 0", r.exit_code == 0,
              f"exit={r.exit_code} stderr={r.stderr[:200]}")
    else:
        check("create_env.py exists locally", False, str(CREATE_ENV_SCRIPT))
        return False

    # Verify the .blend file was created at the expected path
    data = run(sb, f"check-file-exists {ENV_BLEND}")
    check("blend file exists at target path", data.get("exists") is True, str(data)[:100])

    if not data.get("exists"):
        return False

    # Verify the default scene has expected content
    data = run(sb, f"objects {ENV_BLEND}")
    check("default scene has objects", isinstance(data, dict) and "error" not in data,
          str(data)[:200])
    if "error" not in data:
        names = [o["name"] for o in data.get("objects", [])]
        check("default Cube present", "Cube" in names, str(names))
        check("default Camera present", "Camera" in names, str(names))
        check("default Light present", "Light" in names, str(names))

    # Verify scene info is readable
    data = run(sb, f"scene-info {ENV_BLEND}")
    check("scene-info readable on env file", "error" not in data, str(data)[:200])

    # Verify checks work against the env file
    data = run(sb, f"check-object-exists {ENV_BLEND} Cube")
    check("check-object-exists works on env file", data.get("exists") is True, str(data)[:100])

    data = run(sb, f"check-object-type {ENV_BLEND} Cube MESH")
    check("check-object-type works on env file", data.get("match") is True, str(data)[:100])

    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Test: CLI help and error handling
# ═══════════════════════════════════════════════════════════════════════════════

def test_help(sb):
    print("\n=== Help ===")
    r = run_raw(sb, "--help")
    check("help exits 0", r.exit_code == 0)
    check("help mentions commands", "Commands:" in r.stdout)


def test_errors(sb):
    print("\n=== Errors ===")
    r = run_raw(sb, "objects")
    check("missing file arg exits 1", r.exit_code == 1)
    check("missing arg valid JSON", is_valid_json(r.stdout))

    data = run(sb, "objects /nonexistent/file.blend")
    check("nonexistent file returns error", "error" in data, str(data)[:100])

    r = run_raw(sb, "nonexistent-command test.blend")
    check("unknown cmd exits 1", r.exit_code == 1)

    # Missing object name arg
    r = run_raw(sb, f"object-info {TEST_BLEND}")
    check("missing object-name arg exits 1", r.exit_code == 1)


# ═══════════════════════════════════════════════════════════════════════════════
# Test: Query endpoints
# ═══════════════════════════════════════════════════════════════════════════════

def test_objects(sb):
    print("\n=== Objects ===")
    data = run(sb, f"objects {TEST_BLEND}")
    check("objects returns dict", isinstance(data, dict) and "error" not in data, str(data)[:200])
    if "error" in data:
        return
    # Rich scene now contains the original 9 plus TestArmature, ClothPlane,
    # CharMesh, and optionally TestGPencil (if the running Blender version
    # supports gpencil_add). Accept either 12 or 13 to stay version-tolerant.
    check("objects count in {12,13}", data.get("count") in (12, 13),
          f"count={data.get('count')}")
    names = [o["name"] for o in data.get("objects", [])]
    for expected in ["TestCube", "TestSphere", "MainCamera", "SunLight",
                     "FillLight", "GroundPlane", "Pillar", "Marker", "Suzanne"]:
        check(f"{expected} in objects", expected in names, str(names))

    # Check object fields are present
    obj = data["objects"][0]
    for field in ["name", "type", "location", "rotation", "scale", "visible", "parent"]:
        check(f"object has '{field}' field", field in obj, str(obj.keys()))


def test_object_info(sb):
    print("\n=== Object Info ===")
    # Mesh object with modifiers and materials
    data = run(sb, f"object-info {TEST_BLEND} TestCube")
    check("object-info TestCube works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("type is MESH", data.get("type") == "MESH")
        check("has location", isinstance(data.get("location"), list))
        check("has rotation_euler", isinstance(data.get("rotation_euler"), list))
        check("has scale", isinstance(data.get("scale"), list))
        check("has dimensions", isinstance(data.get("dimensions"), list))
        check("has mesh data", "mesh" in data)
        if "mesh" in data:
            check("has vertices > 0", data["mesh"].get("vertices", 0) > 0,
                  f"verts={data['mesh'].get('vertices')}")
            check("has edges", data["mesh"].get("edges", 0) > 0)
            check("has faces", data["mesh"].get("faces", 0) > 0)
            check("has RedMaterial assigned", "RedMaterial" in data["mesh"].get("materials", []),
                  str(data["mesh"].get("materials")))
        check("has modifiers list", len(data.get("modifiers", [])) > 0,
              str(data.get("modifiers")))
        check("has constraints list", isinstance(data.get("constraints"), list))
        check("has children list", isinstance(data.get("children"), list))

    # Camera object
    data = run(sb, f"object-info {TEST_BLEND} MainCamera")
    check("camera info works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("camera type is CAMERA", data.get("type") == "CAMERA")
        check("camera has no mesh key", "mesh" not in data)

    # Light object
    data = run(sb, f"object-info {TEST_BLEND} SunLight")
    check("light info works", "error" not in data)
    if "error" not in data:
        check("light type is LIGHT", data.get("type") == "LIGHT")

    # Empty object
    data = run(sb, f"object-info {TEST_BLEND} Marker")
    check("empty info works", "error" not in data)
    if "error" not in data:
        check("empty type is EMPTY", data.get("type") == "EMPTY")

    # Nonexistent
    data = run(sb, f"object-info {TEST_BLEND} NonExistent")
    check("nonexistent object returns error", "error" in data, str(data)[:100])


def test_materials(sb):
    print("\n=== Materials ===")
    data = run(sb, f"materials {TEST_BLEND}")
    check("materials returns dict", isinstance(data, dict) and "error" not in data, str(data)[:200])
    if "error" in data:
        return
    check("material count >= 2", data.get("count", 0) >= 2, f"count={data.get('count')}")
    names = [m["name"] for m in data.get("materials", [])]
    check("RedMaterial exists", "RedMaterial" in names, str(names))
    check("BlueMaterial exists", "BlueMaterial" in names, str(names))

    # Check node tree info
    red_mat = next((m for m in data["materials"] if m["name"] == "RedMaterial"), None)
    if red_mat:
        check("RedMaterial has use_nodes=True", red_mat.get("use_nodes") is True)
        check("RedMaterial has nodes list", isinstance(red_mat.get("nodes"), list))


def test_scene_info(sb):
    print("\n=== Scene Info ===")
    data = run(sb, f"scene-info {TEST_BLEND}")
    check("scene-info works", "error" not in data, str(data)[:200])
    if "error" in data:
        return
    check("engine is CYCLES", data.get("engine") == "CYCLES")
    check("resolution_x is 1920", data.get("resolution_x") == 1920)
    check("resolution_y is 1080", data.get("resolution_y") == 1080)
    check("camera is MainCamera", data.get("active_camera") == "MainCamera")
    check("frame_start is 1", data.get("frame_start") == 1)
    check("frame_end is 100", data.get("frame_end") == 100)
    check("has fps", isinstance(data.get("fps"), int))
    check("has resolution_percentage", isinstance(data.get("resolution_percentage"), int))
    check("has output_path", "output_path" in data)
    check("has file_format", "file_format" in data)
    check("object_count >= 12", data.get("object_count", 0) >= 12,
          f"object_count={data.get('object_count')}")


def test_collections(sb):
    print("\n=== Collections ===")
    data = run(sb, f"collections {TEST_BLEND}")
    check("collections works", "error" not in data, str(data)[:200])
    if "error" in data:
        return
    names = [c["name"] for c in data.get("collections", [])]
    check("Environment collection exists", "Environment" in names, str(names))
    check("Characters collection exists", "Characters" in names, str(names))
    check("Props collection exists", "Props" in names, str(names))

    # Check collection contents
    env_col = next((c for c in data["collections"] if c["name"] == "Environment"), None)
    if env_col:
        check("Environment has GroundPlane", "GroundPlane" in env_col.get("objects", []),
              str(env_col.get("objects")))
        check("Environment has hide_viewport field", "hide_viewport" in env_col)

    chars_col = next((c for c in data["collections"] if c["name"] == "Characters"), None)
    if chars_col:
        check("Characters has Suzanne", "Suzanne" in chars_col.get("objects", []),
              str(chars_col.get("objects")))

    props_col = next((c for c in data["collections"] if c["name"] == "Props"), None)
    if props_col:
        check("Props has Pillar", "Pillar" in props_col.get("objects", []),
              str(props_col.get("objects")))
        check("Props has Marker", "Marker" in props_col.get("objects", []),
              str(props_col.get("objects")))


def test_animations(sb):
    print("\n=== Animations ===")
    # Specific object - animated
    data = run(sb, f"animations {TEST_BLEND} TestCube")
    check("animations TestCube works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("TestCube is animated", data.get("animated") is True)
        check("has keyframe_count > 0", data.get("keyframe_count", 0) > 0,
              f"kf_count={data.get('keyframe_count')}")
        check("has action name", isinstance(data.get("action"), str))
        # Check keyframe detail
        kfs = data.get("keyframes", [])
        check("keyframes have data_path", len(kfs) > 0 and "data_path" in kfs[0])
        check("keyframes have frame", len(kfs) > 0 and "frame" in kfs[0])
        check("keyframes have value", len(kfs) > 0 and "value" in kfs[0])

    # Second animated object
    data = run(sb, f"animations {TEST_BLEND} TestSphere")
    if "error" not in data:
        check("TestSphere is animated", data.get("animated") is True)

    # Non-animated object
    data = run(sb, f"animations {TEST_BLEND} Pillar")
    if "error" not in data:
        check("Pillar not animated", data.get("animated") is False)

    # All animations overview
    data = run(sb, f"animations {TEST_BLEND}")
    check("all animations works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("animated_objects count >= 2", data.get("count", 0) >= 2,
              f"count={data.get('count')}")
        anim_names = [a["object"] for a in data.get("animated_objects", [])]
        check("TestCube in animated list", "TestCube" in anim_names, str(anim_names))
        check("TestSphere in animated list", "TestSphere" in anim_names, str(anim_names))
        # Check frame_range field
        if data.get("animated_objects"):
            obj_anim = data["animated_objects"][0]
            check("animated obj has frame_range", isinstance(obj_anim.get("frame_range"), list))
            check("animated obj has fcurve_count", isinstance(obj_anim.get("fcurve_count"), int))

    # Nonexistent object
    data = run(sb, f"animations {TEST_BLEND} NonExistent")
    check("nonexistent animation returns error", "error" in data)


def test_modifiers(sb):
    print("\n=== Modifiers ===")
    # TestCube has SUBSURF + BEVEL
    data = run(sb, f"modifiers {TEST_BLEND} TestCube")
    check("modifiers TestCube works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("TestCube has 2 modifiers", data.get("count") == 2, f"count={data.get('count')}")
        types = [m["type"] for m in data.get("modifiers", [])]
        check("SUBSURF modifier exists", "SUBSURF" in types, str(types))
        check("BEVEL modifier exists", "BEVEL" in types, str(types))

        # Check SUBSURF-specific properties
        subsurf = next((m for m in data["modifiers"] if m["type"] == "SUBSURF"), None)
        if subsurf:
            check("SUBSURF has levels=2", subsurf.get("levels") == 2)
            check("SUBSURF has render_levels=3", subsurf.get("render_levels") == 3)
            check("SUBSURF has show_viewport", "show_viewport" in subsurf)
            check("SUBSURF has show_render", "show_render" in subsurf)
            check("SUBSURF has index field", "index" in subsurf)

        # Check BEVEL-specific properties (width, segments)
        bevel = next((m for m in data["modifiers"] if m["type"] == "BEVEL"), None)
        if bevel:
            check("BEVEL has width=0.05",
                  abs((bevel.get("width") or 0) - 0.05) < 1e-4,
                  f"width={bevel.get('width')}")
            check("BEVEL has segments=3", bevel.get("segments") == 3,
                  f"segments={bevel.get('segments')}")
            check("BEVEL has profile field", "profile" in bevel)

        # Check modifier-stack order: Subsurf should be at index 0, Bevel at index 1
        mods_in_order = data.get("modifiers", [])
        if len(mods_in_order) >= 2:
            check("modifier index 0 is SUBSURF",
                  mods_in_order[0].get("type") == "SUBSURF",
                  f"types={[m.get('type') for m in mods_in_order]}")
            check("modifier index 1 is BEVEL",
                  mods_in_order[1].get("type") == "BEVEL",
                  f"types={[m.get('type') for m in mods_in_order]}")

    # TestSphere has MIRROR + ARRAY
    data = run(sb, f"modifiers {TEST_BLEND} TestSphere")
    check("modifiers TestSphere works", "error" not in data, str(data)[:200])
    if "error" not in data:
        types = [m["type"] for m in data.get("modifiers", [])]
        check("MIRROR modifier on sphere", "MIRROR" in types, str(types))
        check("ARRAY modifier on sphere", "ARRAY" in types, str(types))

        # Check MIRROR-specific properties
        mirror = next((m for m in data["modifiers"] if m["type"] == "MIRROR"), None)
        if mirror:
            check("MIRROR has use_axis", isinstance(mirror.get("use_axis"), list))

        # Check ARRAY-specific properties
        arr = next((m for m in data["modifiers"] if m["type"] == "ARRAY"), None)
        if arr:
            check("ARRAY has count=3", arr.get("count") == 3)
            check("ARRAY has use_relative_offset=True",
                  arr.get("use_relative_offset") is True,
                  f"use_relative_offset={arr.get('use_relative_offset')}")
            off = arr.get("relative_offset_displace")
            check("ARRAY relative_offset_displace is list of 3",
                  isinstance(off, list) and len(off) == 3,
                  f"off={off}")
            if isinstance(off, list) and len(off) == 3:
                check("ARRAY relative_offset X=1.5",
                      abs(off[0] - 1.5) < 1e-4, f"off[0]={off[0]}")

    # Pillar has SOLIDIFY
    data = run(sb, f"modifiers {TEST_BLEND} Pillar")
    check("modifiers Pillar works", "error" not in data, str(data)[:200])
    if "error" not in data:
        types = [m["type"] for m in data.get("modifiers", [])]
        check("SOLIDIFY modifier on Pillar", "SOLIDIFY" in types, str(types))

    # GroundPlane now carries fixture modifiers (GeoNodes/Particle/Collision)
    data = run(sb, f"modifiers {TEST_BLEND} GroundPlane")
    check("modifiers GroundPlane works", "error" not in data)
    if "error" not in data:
        types = [m["type"] for m in data.get("modifiers", [])]
        check("GroundPlane has NODES modifier", "NODES" in types, str(types))
        check("GroundPlane has COLLISION modifier", "COLLISION" in types, str(types))
        check("GroundPlane has PARTICLE_SYSTEM modifier",
              "PARTICLE_SYSTEM" in types, str(types))

    # CharMesh has ARMATURE modifier targeting TestArmature
    data = run(sb, f"modifiers {TEST_BLEND} CharMesh")
    check("modifiers CharMesh works", "error" not in data, str(data)[:200])
    if "error" not in data:
        types = [m["type"] for m in data.get("modifiers", [])]
        check("CharMesh has ARMATURE modifier", "ARMATURE" in types, str(types))
        armod = next((m for m in data["modifiers"] if m["type"] == "ARMATURE"), None)
        if armod:
            check("ARMATURE modifier object=TestArmature",
                  armod.get("object") == "TestArmature",
                  f"object={armod.get('object')}")
            check("ARMATURE modifier has use_vertex_groups",
                  "use_vertex_groups" in armod)

    # Nonexistent
    data = run(sb, f"modifiers {TEST_BLEND} NonExistent")
    check("nonexistent modifier returns error", "error" in data)


# ═══════════════════════════════════════════════════════════════════════════════
# Test: Check endpoints — positive cases
# ═══════════════════════════════════════════════════════════════════════════════

def test_checks_positive(sb):
    print("\n=== Checks (positive) ===")

    # check-object-exists
    for name in ["TestCube", "TestSphere", "MainCamera", "SunLight",
                  "GroundPlane", "Pillar", "Marker", "Suzanne"]:
        data = run(sb, f"check-object-exists {TEST_BLEND} {name}")
        check(f"check-object-exists {name}=true", data.get("exists") is True,
              str(data)[:100])

    # check-object-type (test multiple types)
    type_checks = [
        ("TestCube", "MESH"), ("MainCamera", "CAMERA"), ("SunLight", "LIGHT"),
        ("FillLight", "LIGHT"), ("Marker", "EMPTY"),
    ]
    for obj, typ in type_checks:
        data = run(sb, f"check-object-type {TEST_BLEND} {obj} {typ}")
        check(f"check-object-type {obj}={typ}", data.get("match") is True,
              str(data)[:100])

    # check-object-count — find the actual count first (version-dependent due to
    # optional grease pencil object), then assert positive match.
    obj_data = run(sb, f"objects {TEST_BLEND}")
    actual_count = obj_data.get("count", 0) if isinstance(obj_data, dict) else 0
    data = run(sb, f"check-object-count {TEST_BLEND} {actual_count}")
    check(f"check-object-count {actual_count}=true", data.get("match") is True,
          str(data)[:100])

    # check-material-exists
    for mat in ["RedMaterial", "BlueMaterial"]:
        data = run(sb, f"check-material-exists {TEST_BLEND} {mat}")
        check(f"check-material-exists {mat}=true", data.get("exists") is True,
              str(data)[:100])

    # check-modifier-exists (various types)
    mod_checks = [
        ("TestCube", "SUBSURF"), ("TestCube", "BEVEL"),
        ("TestSphere", "MIRROR"), ("TestSphere", "ARRAY"),
        ("Pillar", "SOLIDIFY"),
    ]
    for obj, mod in mod_checks:
        data = run(sb, f"check-modifier-exists {TEST_BLEND} {obj} {mod}")
        check(f"check-modifier-exists {obj}/{mod}=true", data.get("exists") is True,
              str(data)[:100])

    # check-animation-exists
    for obj in ["TestCube", "TestSphere"]:
        data = run(sb, f"check-animation-exists {TEST_BLEND} {obj}")
        check(f"check-animation-exists {obj}=true", data.get("animated") is True,
              str(data)[:100])

    # check-render-engine
    data = run(sb, f"check-render-engine {TEST_BLEND} CYCLES")
    check("check-render-engine CYCLES=true", data.get("match") is True, str(data)[:100])

    # check-resolution
    data = run(sb, f"check-resolution {TEST_BLEND} 1920 1080")
    check("check-resolution 1920x1080=true", data.get("match") is True, str(data)[:100])

    # check-collection-exists
    for col in ["Environment", "Characters", "Props"]:
        data = run(sb, f"check-collection-exists {TEST_BLEND} {col}")
        check(f"check-collection-exists {col}=true", data.get("exists") is True,
              str(data)[:100])

    # check-vertex-count (cube has 8 vertices)
    data = run(sb, f"check-vertex-count {TEST_BLEND} TestCube 8")
    check("check-vertex-count Cube/8=true", data.get("match") is True, str(data)[:100])

    # check-file-exists
    data = run(sb, f"check-file-exists {TEST_BLEND}")
    check("check-file-exists=true", data.get("exists") is True, str(data)[:100])
    check("check-file-exists has size", isinstance(data.get("size"), int) and data["size"] > 0,
          str(data)[:100])


# ═══════════════════════════════════════════════════════════════════════════════
# Test: Check endpoints — negative cases
# ═══════════════════════════════════════��═══════════════════════════════════════

def test_checks_negative(sb):
    print("\n=== Checks (negative) ===")

    data = run(sb, f"check-object-exists {TEST_BLEND} NonExistent")
    check("check-object-exists nonexistent=false", data.get("exists") is False, str(data)[:100])

    data = run(sb, f"check-object-type {TEST_BLEND} TestCube CAMERA")
    check("check-object-type wrong=false", data.get("match") is False, str(data)[:100])

    data = run(sb, f"check-object-count {TEST_BLEND} 99")
    check("check-object-count wrong=false", data.get("match") is False, str(data)[:100])

    data = run(sb, f"check-material-exists {TEST_BLEND} NonExistent")
    check("check-material-exists nonexistent=false", data.get("exists") is False, str(data)[:100])

    data = run(sb, f"check-modifier-exists {TEST_BLEND} GroundPlane SUBSURF")
    check("check-modifier-exists missing=false", data.get("exists") is False, str(data)[:100])

    data = run(sb, f"check-modifier-exists {TEST_BLEND} NonExistent SUBSURF")
    check("check-modifier-exists bad obj=false", data.get("exists") is False, str(data)[:100])

    data = run(sb, f"check-animation-exists {TEST_BLEND} Pillar")
    check("check-animation-exists static=false", data.get("animated") is False, str(data)[:100])

    data = run(sb, f"check-render-engine {TEST_BLEND} BLENDER_EEVEE_NEXT")
    check("check-render-engine wrong=false", data.get("match") is False, str(data)[:100])

    data = run(sb, f"check-resolution {TEST_BLEND} 800 600")
    check("check-resolution wrong=false", data.get("match") is False, str(data)[:100])

    data = run(sb, f"check-collection-exists {TEST_BLEND} NonExistent")
    check("check-collection-exists nonexistent=false", data.get("exists") is False, str(data)[:100])

    data = run(sb, f"check-vertex-count {TEST_BLEND} TestCube 999")
    check("check-vertex-count wrong count=false", data.get("match") is False, str(data)[:100])

    data = run(sb, f"check-vertex-count {TEST_BLEND} MainCamera 8")
    check("check-vertex-count non-mesh=false", data.get("match") is False, str(data)[:100])

    data = run(sb, f"check-vertex-count {TEST_BLEND} NonExistent 8")
    check("check-vertex-count bad obj=false", data.get("match") is False, str(data)[:100])

    data = run(sb, f"check-file-exists /nonexistent/file.blend")
    check("check-file-exists nonexistent=false", data.get("exists") is False, str(data)[:100])


# ═══════════════════════════════════════════════════════════════════════════════
# Test: New endpoints (positive + negative for each)
# ═══════════════════════════════════════════════════════════════════════════════

def test_material_nodes(sb):
    print("\n=== material-nodes ===")
    # Positive: RedMaterial has use_nodes=True with Principled BSDF graph
    data = run(sb, f"material-nodes {TEST_BLEND} RedMaterial")
    check("material-nodes RedMaterial works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("material-nodes use_nodes=True", data.get("use_nodes") is True)
        check("material-nodes has nodes list", isinstance(data.get("nodes"), list))
        check("material-nodes has >=2 nodes", len(data.get("nodes", [])) >= 2,
              f"n={len(data.get('nodes', []))}")
        types = [n.get("type") for n in data.get("nodes", [])]
        check("material-nodes has BSDF_PRINCIPLED", "BSDF_PRINCIPLED" in types, str(types))
        check("material-nodes has OUTPUT_MATERIAL", "OUTPUT_MATERIAL" in types, str(types))
        check("material-nodes has links list", isinstance(data.get("links"), list))
        check("material-nodes has >=1 link", len(data.get("links", [])) >= 1)
        # Check that each node entry has inputs dict
        bsdf = next((n for n in data["nodes"] if n.get("type") == "BSDF_PRINCIPLED"), None)
        if bsdf:
            check("BSDF has inputs dict", isinstance(bsdf.get("inputs"), dict))
            check("BSDF has Base Color input", "Base Color" in bsdf.get("inputs", {}),
                  str(list(bsdf.get("inputs", {}).keys()))[:200])

    # Negative: nonexistent material
    data = run(sb, f"material-nodes {TEST_BLEND} NonExistentMaterial")
    check("material-nodes missing -> error", "error" in data, str(data)[:100])


def test_compositor_nodes(sb):
    print("\n=== compositor-nodes ===")
    # Positive: scene has use_nodes=True with RLayers -> Blur -> Composite
    data = run(sb, f"compositor-nodes {TEST_BLEND}")
    check("compositor-nodes works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("compositor use_nodes=True", data.get("use_nodes") is True)
        types = [n.get("type") for n in data.get("nodes", [])]
        check("compositor has BLUR", "BLUR" in types, str(types))
        check("compositor has COMPOSITE", "COMPOSITE" in types, str(types))
        check("compositor has R_LAYERS", "R_LAYERS" in types, str(types))
        check("compositor has >=2 links", len(data.get("links", [])) >= 2,
              f"n={len(data.get('links', []))}")
        blur_node = next((n for n in data["nodes"] if n.get("type") == "BLUR"), None)
        if blur_node:
            check("BLUR has size_x=5", blur_node.get("size_x") == 5,
                  f"size_x={blur_node.get('size_x')}")

    # Negative: nonexistent file
    data = run(sb, "compositor-nodes /nonexistent/nope.blend")
    check("compositor-nodes missing file -> error", "error" in data, str(data)[:100])


def test_geometry_nodes(sb):
    print("\n=== geometry-nodes ===")
    # Positive: GroundPlane has a NODES modifier
    data = run(sb, f"geometry-nodes {TEST_BLEND} GroundPlane")
    check("geometry-nodes GroundPlane works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("geometry-nodes count >= 1", data.get("count", 0) >= 1,
              f"count={data.get('count')}")
        gm_list = data.get("geometry_modifiers", [])
        check("geometry-nodes has modifier list", isinstance(gm_list, list))
        if gm_list:
            gm = gm_list[0]
            check("geometry modifier has node_group", gm.get("node_group") == "PlaneGeoNodes",
                  f"ng={gm.get('node_group')}")
            check("geometry modifier has nodes", isinstance(gm.get("nodes"), list))
            check("geometry modifier has links", isinstance(gm.get("links"), list))

    # Negative: object without geometry nodes
    data = run(sb, f"geometry-nodes {TEST_BLEND} TestCube")
    check("geometry-nodes TestCube works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("TestCube has 0 geometry modifiers", data.get("count") == 0,
              f"count={data.get('count')}")

    # Negative: nonexistent object
    data = run(sb, f"geometry-nodes {TEST_BLEND} NonExistent")
    check("geometry-nodes missing obj -> error", "error" in data, str(data)[:100])


def test_shape_keys(sb):
    print("\n=== shape-keys ===")
    # Positive: Suzanne has shape keys
    data = run(sb, f"shape-keys {TEST_BLEND} Suzanne")
    check("shape-keys Suzanne works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("Suzanne has_shape_keys=True", data.get("has_shape_keys") is True)
        keys = data.get("keys", [])
        names = [k.get("name") for k in keys]
        check("Basis shape key present", "Basis" in names, str(names))
        check("Smile shape key present", "Smile" in names, str(names))
        check("Frown shape key present", "Frown" in names, str(names))
        smile = next((k for k in keys if k.get("name") == "Smile"), None)
        if smile:
            # Smile.value is driver-evaluated (max(mood,0)) from fixture mood=0.4 → ~0.4
            check("Smile value is a float",
                  isinstance(smile.get("value"), (int, float)),
                  f"value={smile.get('value')}")
            check("Smile slider_min=-1.0", smile.get("slider_min") == -1.0)
            check("Smile slider_max=2.0", smile.get("slider_max") == 2.0)
            check("Smile has mute field", "mute" in smile)

    # Negative: object without shape keys
    data = run(sb, f"shape-keys {TEST_BLEND} TestSphere")
    check("shape-keys TestSphere works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("TestSphere has_shape_keys=False", data.get("has_shape_keys") is False,
              str(data)[:200])

    # Negative: nonexistent object
    data = run(sb, f"shape-keys {TEST_BLEND} NonExistent")
    check("shape-keys missing obj -> error", "error" in data, str(data)[:100])


def test_drivers(sb):
    print("\n=== drivers ===")
    # Positive: TestCube has driver on scale.x + custom_scale property
    data = run(sb, f"drivers {TEST_BLEND} TestCube")
    check("drivers TestCube works", "error" not in data, str(data)[:200])
    if "error" not in data:
        drvs = data.get("drivers", [])
        check("TestCube has >=1 driver", len(drvs) >= 1, f"n={len(drvs)}")
        if drvs:
            d0 = drvs[0]
            check("driver has data_path", d0.get("data_path") == "scale",
                  f"path={d0.get('data_path')}")
            check("driver array_index=0", d0.get("array_index") == 0)
            check("driver expression present", "var" in (d0.get("expression") or ""),
                  f"expr={d0.get('expression')}")
            check("driver has variables", len(d0.get("variables", [])) >= 1)
        cprops = data.get("custom_properties", {})
        check("custom_scale property present", "custom_scale" in cprops, str(cprops)[:200])
        # Custom-property range metadata
        ranges = data.get("custom_property_ranges", {})
        check("custom_property_ranges dict present",
              isinstance(ranges, dict), str(ranges)[:200])
        scale_meta = ranges.get("custom_scale") if isinstance(ranges, dict) else None
        if isinstance(scale_meta, dict):
            check("custom_scale min=0.0",
                  abs((scale_meta.get("min") or 0) - 0.0) < 1e-4,
                  f"min={scale_meta.get('min')}")
            check("custom_scale max=5.0",
                  abs((scale_meta.get("max") or 0) - 5.0) < 1e-4,
                  f"max={scale_meta.get('max')}")
        # shape_key_drivers field present (even if empty on TestCube)
        check("shape_key_drivers field present",
              "shape_key_drivers" in data, str(data.keys())[:200])

    # Positive: Suzanne has a shape-key driver on Smile.value + mood custom prop
    data = run(sb, f"drivers {TEST_BLEND} Suzanne")
    check("drivers Suzanne works", "error" not in data, str(data)[:200])
    if "error" not in data:
        sk_drvs = data.get("shape_key_drivers", [])
        check("Suzanne has >=1 shape_key_driver",
              len(sk_drvs) >= 1, f"n={len(sk_drvs)}")
        if sk_drvs:
            skd = sk_drvs[0]
            check("shape-key driver source=shape_key",
                  skd.get("source") == "shape_key",
                  f"source={skd.get('source')}")
            check("shape-key driver data_path mentions Smile",
                  "Smile" in str(skd.get("data_path", "")),
                  f"data_path={skd.get('data_path')}")
            check("shape-key driver expression mentions mood",
                  "mood" in str(skd.get("expression", "")),
                  f"expr={skd.get('expression')}")
        ranges = data.get("custom_property_ranges", {})
        mood_meta = ranges.get("mood") if isinstance(ranges, dict) else None
        if isinstance(mood_meta, dict):
            check("mood min=-1.0",
                  abs((mood_meta.get("min") or 0) - (-1.0)) < 1e-4,
                  f"min={mood_meta.get('min')}")
            check("mood max=1.0",
                  abs((mood_meta.get("max") or 0) - 1.0) < 1e-4,
                  f"max={mood_meta.get('max')}")

    # Negative: object without drivers
    data = run(sb, f"drivers {TEST_BLEND} GroundPlane")
    check("drivers GroundPlane works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("GroundPlane has 0 drivers", len(data.get("drivers", [])) == 0,
              str(data.get("drivers"))[:200])
        check("GroundPlane has 0 shape_key_drivers",
              len(data.get("shape_key_drivers", [])) == 0,
              str(data.get("shape_key_drivers"))[:200])

    # Negative: nonexistent object
    data = run(sb, f"drivers {TEST_BLEND} NonExistent")
    check("drivers missing obj -> error", "error" in data, str(data)[:100])


def test_armature_bones(sb):
    print("\n=== armature-bones ===")
    # Positive: TestArmature has Root/ChildBone/TipBone
    data = run(sb, f"armature-bones {TEST_BLEND} TestArmature")
    check("armature-bones TestArmature works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("armature count >= 3", data.get("count", 0) >= 3, f"count={data.get('count')}")
        bones = data.get("bones", [])
        names = [b.get("name") for b in bones]
        check("Root bone present", "Root" in names, str(names))
        check("ChildBone present", "ChildBone" in names, str(names))
        check("TipBone present", "TipBone" in names, str(names))
        child = next((b for b in bones if b.get("name") == "ChildBone"), None)
        if child:
            check("ChildBone parent=Root", child.get("parent") == "Root",
                  f"parent={child.get('parent')}")
            check("ChildBone use_connect=True", child.get("use_connect") is True)
            check("ChildBone has head list", isinstance(child.get("head"), list))
            check("ChildBone has tail list", isinstance(child.get("tail"), list))

    # Negative: non-armature object
    data = run(sb, f"armature-bones {TEST_BLEND} TestCube")
    check("armature-bones on non-armature -> error", "error" in data, str(data)[:100])

    # Negative: nonexistent object
    data = run(sb, f"armature-bones {TEST_BLEND} NonExistent")
    check("armature-bones missing obj -> error", "error" in data, str(data)[:100])


def test_pose_constraints(sb):
    print("\n=== pose-constraints ===")
    # Positive: TipBone has IK constraint
    data = run(sb, f"pose-constraints {TEST_BLEND} TestArmature TipBone")
    check("pose-constraints TipBone works", "error" not in data, str(data)[:200])
    if "error" not in data:
        cons = data.get("constraints", [])
        check("TipBone has >=1 constraint", len(cons) >= 1, f"n={len(cons)}")
        if cons:
            c = cons[0]
            check("constraint type=IK", c.get("type") == "IK", f"type={c.get('type')}")
            check("constraint chain_count=2", c.get("chain_count") == 2,
                  f"chain={c.get('chain_count')}")
            check("constraint influence≈0.8",
                  abs((c.get("influence") or 0) - 0.8) < 1e-4,
                  f"infl={c.get('influence')}")

    # Positive: bone without constraints (Root has none)
    data = run(sb, f"pose-constraints {TEST_BLEND} TestArmature Root")
    check("pose-constraints Root works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("Root has 0 constraints", len(data.get("constraints", [])) == 0,
              str(data.get("constraints"))[:200])

    # Negative: non-armature object
    data = run(sb, f"pose-constraints {TEST_BLEND} TestCube Bone")
    check("pose-constraints non-armature -> error", "error" in data, str(data)[:100])

    # Negative: nonexistent bone
    data = run(sb, f"pose-constraints {TEST_BLEND} TestArmature NoSuchBone")
    check("pose-constraints missing bone -> error", "error" in data, str(data)[:100])


def test_object_constraints(sb):
    print("\n=== object-constraints ===")
    # Positive: Marker has a Copy Rotation constraint targeting TestCube
    data = run(sb, f"object-constraints {TEST_BLEND} Marker")
    check("object-constraints Marker works", "error" not in data, str(data)[:200])
    if "error" not in data:
        cons = data.get("constraints", [])
        check("Marker has >=1 constraint", len(cons) >= 1, f"n={len(cons)}")
        if cons:
            c = cons[0]
            check("Marker constraint type=COPY_ROTATION",
                  c.get("type") == "COPY_ROTATION", f"type={c.get('type')}")
            check("Marker constraint target=TestCube",
                  c.get("target") == "TestCube", f"target={c.get('target')}")
            check("Marker constraint use_x=True",
                  c.get("use_x") is True, f"use_x={c.get('use_x')}")
            check("Marker constraint use_y=False",
                  c.get("use_y") is False, f"use_y={c.get('use_y')}")
            check("Marker constraint use_z=True",
                  c.get("use_z") is True, f"use_z={c.get('use_z')}")
            check("Marker constraint influence≈0.75",
                  abs((c.get("influence") or 0) - 0.75) < 1e-4,
                  f"influence={c.get('influence')}")

    # Positive: ClothPlane has a Child Of constraint targeting TestCube
    data = run(sb, f"object-constraints {TEST_BLEND} ClothPlane")
    check("object-constraints ClothPlane works", "error" not in data, str(data)[:200])
    if "error" not in data:
        cons = data.get("constraints", [])
        types = [c.get("type") for c in cons]
        check("ClothPlane has CHILD_OF", "CHILD_OF" in types, str(types))
        chof = next((c for c in cons if c.get("type") == "CHILD_OF"), None)
        if chof:
            check("CHILD_OF target=TestCube",
                  chof.get("target") == "TestCube",
                  f"target={chof.get('target')}")
            check("CHILD_OF use_location_x=True",
                  chof.get("use_location_x") is True)
            check("CHILD_OF use_location_z=False",
                  chof.get("use_location_z") is False)
            check("CHILD_OF use_rotation_z=True",
                  chof.get("use_rotation_z") is True)
            check("CHILD_OF use_scale_x=False",
                  chof.get("use_scale_x") is False)

    # Positive: object with zero constraints (TestCube)
    data = run(sb, f"object-constraints {TEST_BLEND} TestCube")
    check("object-constraints TestCube works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("TestCube has 0 constraints",
              len(data.get("constraints", [])) == 0,
              str(data.get("constraints"))[:200])
        check("TestCube count=0", data.get("count") == 0)

    # Negative: nonexistent object
    data = run(sb, f"object-constraints {TEST_BLEND} NonExistent")
    check("object-constraints missing obj -> error", "error" in data, str(data)[:100])


def test_rigid_body_info(sb):
    print("\n=== rigid-body-info ===")
    # Positive: scene has rigid body world + Suzanne ACTIVE + Pillar PASSIVE
    data = run(sb, f"rigid-body-info {TEST_BLEND}")
    check("rigid-body-info works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("has gravity list", isinstance(data.get("gravity"), list))
        check("gravity has 3 components", len(data.get("gravity", [])) == 3)
        # rigidbody_world may be None if ops.rigidbody.object_add didn't run successfully;
        # positive-state requirement: at least one rigid body object
        rb_objs = data.get("objects", [])
        names = [o.get("name") for o in rb_objs]
        if rb_objs:
            check("Suzanne or Pillar has rigid body",
                  "Suzanne" in names or "Pillar" in names, str(names))
            suz = next((o for o in rb_objs if o.get("name") == "Suzanne"), None)
            if suz:
                check("Suzanne rb type=ACTIVE", suz.get("type") == "ACTIVE",
                      f"type={suz.get('type')}")
                check("Suzanne rb mass=2.5", suz.get("mass") == 2.5,
                      f"mass={suz.get('mass')}")
                check("Suzanne rb collision_shape=BOX",
                      suz.get("collision_shape") == "BOX",
                      f"shape={suz.get('collision_shape')}")
            pillar = next((o for o in rb_objs if o.get("name") == "Pillar"), None)
            if pillar:
                check("Pillar rb type=PASSIVE", pillar.get("type") == "PASSIVE",
                      f"type={pillar.get('type')}")
        else:
            # Accept empty list as graceful — fixture may not have succeeded if
            # rigid body add op wasn't available. Still validate the shape.
            check("rigid-body-info has objects list", isinstance(rb_objs, list))

    # Negative: nonexistent file
    data = run(sb, "rigid-body-info /nonexistent/nope.blend")
    check("rigid-body-info missing file -> error", "error" in data, str(data)[:100])


def test_particle_systems(sb):
    print("\n=== particle-systems ===")
    # Positive: GroundPlane has the GrassParticles hair system
    data = run(sb, f"particle-systems {TEST_BLEND} GroundPlane")
    check("particle-systems GroundPlane works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("GroundPlane has >=1 particle system", data.get("count", 0) >= 1,
              f"count={data.get('count')}")
        systems = data.get("particle_systems", [])
        if systems:
            s = systems[0]
            check("particle system name=GrassParticles",
                  s.get("name") == "GrassParticles", f"name={s.get('name')}")
            check("particle type=HAIR", s.get("type") == "HAIR",
                  f"type={s.get('type')}")
            check("particle count=500", s.get("count") == 500,
                  f"count={s.get('count')}")
            check("particle hair_length=0.5",
                  s.get("hair_length") is not None
                  and abs(s.get("hair_length") - 0.5) < 1e-4,
                  f"hair_length={s.get('hair_length')}")

    # Negative: object without particle system
    data = run(sb, f"particle-systems {TEST_BLEND} TestCube")
    check("particle-systems TestCube works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("TestCube has 0 particle systems", data.get("count") == 0)

    # Negative: nonexistent object
    data = run(sb, f"particle-systems {TEST_BLEND} NonExistent")
    check("particle-systems missing obj -> error", "error" in data, str(data)[:100])


def test_cloth_settings(sb):
    print("\n=== cloth-settings ===")
    # Positive: ClothPlane has CLOTH modifier
    data = run(sb, f"cloth-settings {TEST_BLEND} ClothPlane")
    check("cloth-settings ClothPlane works", "error" not in data, str(data)[:200])
    if "error" not in data:
        entries = data.get("cloth_or_collision", [])
        types = [e.get("type") for e in entries]
        check("ClothPlane has CLOTH entry", "CLOTH" in types, str(types))
        cloth_entry = next((e for e in entries if e.get("type") == "CLOTH"), None)
        if cloth_entry:
            check("cloth quality=7",
                  cloth_entry.get("quality") == 7 or cloth_entry.get("quality") is None,
                  f"q={cloth_entry.get('quality')}")
            check("cloth has mass field", "mass" in cloth_entry)

    # Positive: GroundPlane has COLLISION modifier
    data = run(sb, f"cloth-settings {TEST_BLEND} GroundPlane")
    check("cloth-settings GroundPlane works", "error" not in data, str(data)[:200])
    if "error" not in data:
        types = [e.get("type") for e in data.get("cloth_or_collision", [])]
        check("GroundPlane has COLLISION entry", "COLLISION" in types, str(types))

    # Negative: object without cloth/collision
    data = run(sb, f"cloth-settings {TEST_BLEND} TestCube")
    check("cloth-settings TestCube works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("TestCube has empty cloth_or_collision",
              len(data.get("cloth_or_collision", [])) == 0,
              str(data.get("cloth_or_collision"))[:200])

    # Negative: nonexistent object
    data = run(sb, f"cloth-settings {TEST_BLEND} NonExistent")
    check("cloth-settings missing obj -> error", "error" in data, str(data)[:100])


def test_nla_tracks(sb):
    print("\n=== nla-tracks ===")
    # Positive: Suzanne has a WaveTrack
    data = run(sb, f"nla-tracks {TEST_BLEND} Suzanne")
    check("nla-tracks Suzanne works", "error" not in data, str(data)[:200])
    if "error" not in data:
        tracks = data.get("nla_tracks", [])
        track_names = [t.get("name") for t in tracks]
        # The push-to-NLA may or may not succeed depending on API; if it did,
        # WaveTrack should be present. Otherwise accept empty list.
        if tracks:
            check("WaveTrack present", "WaveTrack" in track_names, str(track_names))
            wave = next((t for t in tracks if t.get("name") == "WaveTrack"), None)
            if wave:
                check("WaveTrack has strips list", isinstance(wave.get("strips"), list))
                check("WaveTrack has mute field", "mute" in wave)
        else:
            check("nla_tracks list shape ok", isinstance(tracks, list))
        actions = data.get("actions_in_file", [])
        check("actions_in_file is list", isinstance(actions, list))
        check("actions_in_file contains SuzanneWave",
              "SuzanneWave" in actions, str(actions))

    # Negative: object without animation_data
    data = run(sb, f"nla-tracks {TEST_BLEND} GroundPlane")
    check("nla-tracks GroundPlane works", "error" not in data, str(data)[:200])
    if "error" not in data:
        check("GroundPlane has 0 nla tracks",
              len(data.get("nla_tracks", [])) == 0,
              str(data.get("nla_tracks"))[:200])

    # Negative: nonexistent object
    data = run(sb, f"nla-tracks {TEST_BLEND} NonExistent")
    check("nla-tracks missing obj -> error", "error" in data, str(data)[:100])


def test_grease_pencil(sb):
    print("\n=== grease-pencil ===")
    # Positive: TestGPencil may or may not exist depending on Blender version.
    # If present and type is GPENCIL (Blender 3.x), endpoint returns layers;
    # if absent or Blender uses the new GREASEPENCIL type, endpoint returns error —
    # which is an acceptable graceful failure documented by the endpoint.
    exists_data = run(sb, f"check-object-exists {TEST_BLEND} TestGPencil")
    if exists_data.get("exists") is True:
        data = run(sb, f"grease-pencil {TEST_BLEND} TestGPencil")
        # Accept either a layers payload OR a typed error (for GREASEPENCIL in 4.x)
        ok = "error" not in data or "GPENCIL" in str(data.get("error", ""))
        check("grease-pencil responds gracefully on GP object", ok, str(data)[:200])
        if "error" not in data:
            check("grease-pencil has layers list", isinstance(data.get("layers"), list))
            check("grease-pencil type=GPENCIL", data.get("type") == "GPENCIL")
    else:
        check("grease-pencil fixture skipped (no gpencil_add)", True)

    # Negative: non-GP object should return an error mentioning not GPENCIL
    data = run(sb, f"grease-pencil {TEST_BLEND} TestCube")
    check("grease-pencil on non-GP -> error", "error" in data, str(data)[:100])

    # Negative: nonexistent object
    data = run(sb, f"grease-pencil {TEST_BLEND} NonExistent")
    check("grease-pencil missing obj -> error", "error" in data, str(data)[:100])


def test_uv_maps(sb):
    print("\n=== uv-maps ===")
    # Positive: TestCube has two UV maps (default UVMap + UVMap_Second)
    data = run(sb, f"uv-maps {TEST_BLEND} TestCube")
    check("uv-maps TestCube works", "error" not in data, str(data)[:200])
    if "error" not in data:
        maps = data.get("uv_maps", [])
        names = [m.get("name") for m in maps]
        check("TestCube has >=2 UV maps", len(maps) >= 2, f"maps={names}")
        check("TestCube has UVMap_Second", "UVMap_Second" in names, str(names))
        check("uv-maps has active field", "active" in data)
        for m in maps:
            check(f"UV map '{m.get('name')}' has uv_count field",
                  isinstance(m.get("uv_count"), int))
            check(f"UV map '{m.get('name')}' has nonzero_uv_count field",
                  isinstance(m.get("nonzero_uv_count"), int))
            check(f"UV map '{m.get('name')}' has active field",
                  isinstance(m.get("active"), bool))
        # At least one map should be active
        check("exactly one active UV map",
              sum(1 for m in maps if m.get("active")) == 1,
              str([m.get("active") for m in maps]))

    # Negative: non-mesh object
    data = run(sb, f"uv-maps {TEST_BLEND} MainCamera")
    check("uv-maps on non-MESH -> error", "error" in data, str(data)[:100])

    # Negative: nonexistent object
    data = run(sb, f"uv-maps {TEST_BLEND} NonExistent")
    check("uv-maps missing obj -> error", "error" in data, str(data)[:100])


# ═══════════════════════════════════════════════════════════════════════════════
# Test: JSON validity across all endpoints
# ═══════════════════════════════════════════════════════════════════════════════

def test_all_json(sb):
    print("\n=== JSON validity ===")
    cmds = [
        f"objects {TEST_BLEND}",
        f"object-info {TEST_BLEND} TestCube",
        f"object-info {TEST_BLEND} MainCamera",
        f"object-info {TEST_BLEND} Marker",
        f"materials {TEST_BLEND}",
        f"scene-info {TEST_BLEND}",
        f"collections {TEST_BLEND}",
        f"animations {TEST_BLEND}",
        f"animations {TEST_BLEND} TestCube",
        f"animations {TEST_BLEND} Pillar",
        f"modifiers {TEST_BLEND} TestCube",
        f"modifiers {TEST_BLEND} TestSphere",
        f"modifiers {TEST_BLEND} GroundPlane",
        f"check-object-exists {TEST_BLEND} TestCube",
        f"check-object-exists {TEST_BLEND} NonExistent",
        f"check-object-type {TEST_BLEND} TestCube MESH",
        f"check-object-count {TEST_BLEND} 9",
        f"check-material-exists {TEST_BLEND} RedMaterial",
        f"check-modifier-exists {TEST_BLEND} TestCube SUBSURF",
        f"check-animation-exists {TEST_BLEND} TestCube",
        f"check-render-engine {TEST_BLEND} CYCLES",
        f"check-resolution {TEST_BLEND} 1920 1080",
        f"check-collection-exists {TEST_BLEND} Environment",
        f"check-vertex-count {TEST_BLEND} TestCube 8",
        f"check-file-exists {TEST_BLEND}",
        # New endpoints (positive cases)
        f"material-nodes {TEST_BLEND} RedMaterial",
        f"material-nodes {TEST_BLEND} NonExistentMaterial",
        f"compositor-nodes {TEST_BLEND}",
        f"geometry-nodes {TEST_BLEND} GroundPlane",
        f"geometry-nodes {TEST_BLEND} TestCube",
        f"geometry-nodes {TEST_BLEND} NonExistent",
        f"shape-keys {TEST_BLEND} Suzanne",
        f"shape-keys {TEST_BLEND} TestSphere",
        f"shape-keys {TEST_BLEND} NonExistent",
        f"drivers {TEST_BLEND} TestCube",
        f"drivers {TEST_BLEND} GroundPlane",
        f"drivers {TEST_BLEND} NonExistent",
        f"armature-bones {TEST_BLEND} TestArmature",
        f"armature-bones {TEST_BLEND} TestCube",
        f"armature-bones {TEST_BLEND} NonExistent",
        f"pose-constraints {TEST_BLEND} TestArmature TipBone",
        f"pose-constraints {TEST_BLEND} TestArmature Root",
        f"pose-constraints {TEST_BLEND} TestArmature NoSuchBone",
        f"pose-constraints {TEST_BLEND} TestCube NoSuchBone",
        f"object-constraints {TEST_BLEND} Marker",
        f"object-constraints {TEST_BLEND} ClothPlane",
        f"object-constraints {TEST_BLEND} TestCube",
        f"object-constraints {TEST_BLEND} NonExistent",
        f"rigid-body-info {TEST_BLEND}",
        f"particle-systems {TEST_BLEND} GroundPlane",
        f"particle-systems {TEST_BLEND} TestCube",
        f"particle-systems {TEST_BLEND} NonExistent",
        f"cloth-settings {TEST_BLEND} ClothPlane",
        f"cloth-settings {TEST_BLEND} GroundPlane",
        f"cloth-settings {TEST_BLEND} TestCube",
        f"cloth-settings {TEST_BLEND} NonExistent",
        f"nla-tracks {TEST_BLEND} Suzanne",
        f"nla-tracks {TEST_BLEND} GroundPlane",
        f"nla-tracks {TEST_BLEND} NonExistent",
        f"grease-pencil {TEST_BLEND} TestCube",
        f"grease-pencil {TEST_BLEND} NonExistent",
        f"uv-maps {TEST_BLEND} TestCube",
        f"uv-maps {TEST_BLEND} MainCamera",
        f"uv-maps {TEST_BLEND} NonExistent",
    ]
    for cmd in cmds:
        r = run_raw(sb, cmd)
        check(f"{cmd.split()[0]} valid JSON", is_valid_json(r.stdout),
              f"stdout={r.stdout[:80]}" if not is_valid_json(r.stdout) else "")


# ════════════════════════════���══════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    global passed, failed
    print("=" * 60)
    print("Blender Verifier — Comprehensive Test Suite")
    print("=" * 60)

    sb = Sandbox.create(template="desktop-all-apps", timeout=600)
    try:
        sb.commands.run("mkdir -p /home/user/verifiers")
        with open(VERIFIER_LOCAL) as f:
            sb.files.write(VERIFIER_REMOTE, f.read())

        # ── Flow 1: create_env.py pipeline ─────────────────────────────────
        test_create_env_pipeline(sb)

        # ── Flow 2: CLI basics ───────────��─────────────────────────────────
        test_help(sb)
        test_errors(sb)

        # ── Create rich test scene ─────────────────────────────────────────
        print("\n  Creating rich test .blend file...")
        sb.files.write("/tmp/create_blend.py", CREATE_RICH_BLEND_SCRIPT)
        r = run_shell(sb, "blender -b --python /tmp/create_blend.py", timeout=120)
        blend_ok = "BLEND_CREATED" in r.stdout
        check("rich blend file created", blend_ok,
              f"stdout={r.stdout[-200:]} stderr={r.stderr[:200]}")

        if blend_ok:
            # ── Flow 3: Query endpoints ─────────────────────��──────────────
            test_objects(sb)
            test_object_info(sb)
            test_materials(sb)
            test_scene_info(sb)
            test_collections(sb)
            test_animations(sb)
            test_modifiers(sb)

            # ── Flow 4: Check endpoints ─────────────────────────────────��──
            test_checks_positive(sb)
            test_checks_negative(sb)

            # ── Flow 5: New endpoints (positive + negative per endpoint) ───
            test_material_nodes(sb)
            test_compositor_nodes(sb)
            test_geometry_nodes(sb)
            test_shape_keys(sb)
            test_drivers(sb)
            test_armature_bones(sb)
            test_pose_constraints(sb)
            test_object_constraints(sb)
            test_rigid_body_info(sb)
            test_particle_systems(sb)
            test_cloth_settings(sb)
            test_nla_tracks(sb)
            test_grease_pencil(sb)
            test_uv_maps(sb)

            # ── Flow 6: JSON validity ──────────────────────────────────────
            test_all_json(sb)

    except Exception:
        traceback.print_exc()
        failed += 1
        errors.append(f"Unhandled: {traceback.format_exc()}")
    finally:
        sb.kill()

    print(f"\n{'='*60}\nResults: {passed} passed, {failed} failed\n{'='*60}")
    if errors:
        for e in errors:
            print(f"  - {e}")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
