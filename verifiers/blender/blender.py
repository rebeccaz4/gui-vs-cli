"""
Blender Verifier — programmatic state inspection for Blender files in E2B sandbox.

Verification channel:
  bpy Python API in headless mode — full access to scene, objects, materials,
  modifiers, keyframes, render settings, and geometry.

Usage from outside the sandbox:
    sandbox.commands.run("python3 /home/user/verifiers/blender.py objects /path/to/file.blend")
    sandbox.commands.run("python3 /home/user/verifiers/blender.py check-object-exists Cube /path/to/file.blend")

Because bpy can only be imported inside the Blender Python runtime, this verifier
works by generating a Python script and executing it with `blender -b --python`.
The script writes JSON to a temp file which is then read and printed to stdout.

Requires:
  - blender (installed in sandbox)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Helper: run bpy script inside Blender headless
# ---------------------------------------------------------------------------

def _run_bpy(blend_file: str, script: str, timeout: int = 30) -> dict | list:
    """Run a Python script inside Blender headless and return parsed JSON output."""
    if not os.path.exists(blend_file):
        return {"error": f"File not found: {blend_file}"}

    # Write the bpy script to a temp file
    output_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    output_file.close()

    script_file = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
    # Wrap the user script to write JSON output
    full_script = f"""
import bpy
import json
import sys

OUTPUT_FILE = {json.dumps(output_file.name)}

try:
    result = None
{_indent(script, 4)}
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(result, f, default=str)
except Exception as e:
    with open(OUTPUT_FILE, 'w') as f:
        json.dump({{"error": str(e)}}, f)
"""
    script_file.write(full_script)
    script_file.close()

    try:
        proc = subprocess.run(
            ["blender", "-b", blend_file, "--python", script_file.name],
            capture_output=True, text=True, timeout=timeout
        )
        if not os.path.exists(output_file.name) or os.path.getsize(output_file.name) == 0:
            return {"error": f"Blender script produced no output. stderr: {proc.stderr[:500]}"}

        with open(output_file.name) as f:
            return json.load(f)
    except subprocess.TimeoutExpired:
        return {"error": f"Blender script timed out after {timeout}s"}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON from Blender script: {e}"}
    except FileNotFoundError:
        return {"error": "blender not found. Is it installed?"}
    finally:
        os.unlink(script_file.name)
        if os.path.exists(output_file.name):
            os.unlink(output_file.name)


def _indent(text: str, spaces: int) -> str:
    """Indent each line of text."""
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.splitlines())


# ---------------------------------------------------------------------------
# BlenderVerifier class
# ---------------------------------------------------------------------------

class BlenderVerifier:
    """Stateless verifier for Blender .blend files."""

    def get_objects(self, blend_file: str) -> dict:
        """List all objects in the scene with type, location, visibility.

        Example return:
        {"objects": [{"name": "Cube", "type": "MESH", "location": [0,0,0], "visible": true}], "count": 3}
        """
        script = """
result = {
    "objects": [],
    "count": len(bpy.data.objects),
}
for obj in bpy.data.objects:
    result["objects"].append({
        "name": obj.name,
        "type": obj.type,
        "location": list(obj.location),
        "rotation": list(obj.rotation_euler),
        "scale": list(obj.scale),
        "visible": not obj.hide_viewport,
        "parent": obj.parent.name if obj.parent else None,
    })
"""
        return _run_bpy(blend_file, script)

    def get_object_info(self, blend_file: str, object_name: str) -> dict:
        """Get detailed info about a specific object."""
        script = f"""
name = {json.dumps(object_name)}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"error": f"Object '{{name}}' not found"}}
else:
    info = {{
        "name": obj.name,
        "type": obj.type,
        "location": list(obj.location),
        "rotation_euler": list(obj.rotation_euler),
        "scale": list(obj.scale),
        "dimensions": list(obj.dimensions),
        "visible": not obj.hide_viewport,
        "parent": obj.parent.name if obj.parent else None,
        "children": [c.name for c in obj.children],
        "modifiers": [{{
            "name": m.name,
            "type": m.type,
        }} for m in obj.modifiers],
        "constraints": [{{
            "name": c.name,
            "type": c.type,
        }} for c in obj.constraints],
    }}
    if obj.type == 'MESH' and obj.data:
        mesh = obj.data
        info["mesh"] = {{
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "faces": len(mesh.polygons),
            "materials": [m.name if m else None for m in mesh.materials],
        }}
    result = info
"""
        return _run_bpy(blend_file, script)

    def get_materials(self, blend_file: str) -> dict:
        """List all materials in the file."""
        script = """
result = {
    "materials": [],
    "count": len(bpy.data.materials),
}
for mat in bpy.data.materials:
    info = {
        "name": mat.name,
        "use_nodes": mat.use_nodes,
    }
    if mat.use_nodes and mat.node_tree:
        info["nodes"] = [{"name": n.name, "type": n.type} for n in mat.node_tree.nodes]
    result["materials"].append(info)
"""
        return _run_bpy(blend_file, script)

    def get_scene_info(self, blend_file: str) -> dict:
        """Get scene metadata: render settings, frame range, active camera."""
        script = """
scene = bpy.context.scene
render = scene.render
result = {
    "name": scene.name,
    "frame_start": scene.frame_start,
    "frame_end": scene.frame_end,
    "frame_current": scene.frame_current,
    "fps": scene.render.fps,
    "resolution_x": render.resolution_x,
    "resolution_y": render.resolution_y,
    "resolution_percentage": render.resolution_percentage,
    "engine": render.engine,
    "film_transparent": render.film_transparent,
    "output_path": render.filepath,
    "file_format": render.image_settings.file_format,
    "active_camera": scene.camera.name if scene.camera else None,
    "world": scene.world.name if scene.world else None,
    "object_count": len(scene.objects),
}
"""
        return _run_bpy(blend_file, script)

    def get_collections(self, blend_file: str) -> dict:
        """List all collections and their objects."""
        script = """
result = {"collections": [], "count": len(bpy.data.collections)}
for col in bpy.data.collections:
    result["collections"].append({
        "name": col.name,
        "objects": [o.name for o in col.objects],
        "children": [c.name for c in col.children],
        "hide_viewport": col.hide_viewport,
    })
"""
        return _run_bpy(blend_file, script)

    def get_animations(self, blend_file: str, object_name: str | None = None) -> dict:
        """Get animation data (keyframes) for an object or all objects."""
        if object_name:
            script = f"""
name = {json.dumps(object_name)}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"error": f"Object '{{name}}' not found"}}
elif not obj.animation_data or not obj.animation_data.action:
    result = {{"object": name, "animated": False, "keyframes": []}}
else:
    action = obj.animation_data.action
    kfs = []
    for fc in action.fcurves:
        for kp in fc.keyframe_points:
            kfs.append({{
                "data_path": fc.data_path,
                "array_index": fc.array_index,
                "frame": kp.co[0],
                "value": kp.co[1],
            }})
    result = {{"object": name, "animated": True, "action": action.name, "keyframe_count": len(kfs), "keyframes": kfs[:100]}}
"""
        else:
            script = """
animated_objects = []
for obj in bpy.data.objects:
    if obj.animation_data and obj.animation_data.action:
        action = obj.animation_data.action
        animated_objects.append({
            "object": obj.name,
            "action": action.name,
            "fcurve_count": len(action.fcurves),
            "frame_range": list(action.frame_range),
        })
result = {"animated_objects": animated_objects, "count": len(animated_objects)}
"""
        return _run_bpy(blend_file, script)

    def get_modifiers(self, blend_file: str, object_name: str) -> dict:
        """Get detailed modifier info for an object."""
        script = f"""
name = {json.dumps(object_name)}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"error": f"Object '{{name}}' not found"}}
else:
    mods = []
    for idx, m in enumerate(obj.modifiers):
        mod_info = {{"name": m.name, "type": m.type, "index": idx, "show_viewport": m.show_viewport, "show_render": m.show_render}}
        # Add type-specific properties
        if m.type == 'SUBSURF':
            mod_info["levels"] = m.levels
            mod_info["render_levels"] = m.render_levels
        elif m.type == 'ARRAY':
            mod_info["count"] = m.count
            mod_info["use_relative_offset"] = bool(getattr(m, "use_relative_offset", False))
            mod_info["use_constant_offset"] = bool(getattr(m, "use_constant_offset", False))
            mod_info["use_object_offset"] = bool(getattr(m, "use_object_offset", False))
            if hasattr(m, "relative_offset_displace"):
                mod_info["relative_offset_displace"] = [float(x) for x in m.relative_offset_displace]
            if hasattr(m, "constant_offset_displace"):
                mod_info["constant_offset_displace"] = [float(x) for x in m.constant_offset_displace]
            if hasattr(m, "offset_object") and m.offset_object:
                mod_info["offset_object"] = m.offset_object.name
        elif m.type == 'BOOLEAN':
            mod_info["operation"] = m.operation
            mod_info["object"] = m.object.name if m.object else None
        elif m.type == 'MIRROR':
            mod_info["use_axis"] = [m.use_axis[0], m.use_axis[1], m.use_axis[2]]
            if hasattr(m, "mirror_object") and m.mirror_object:
                mod_info["mirror_object"] = m.mirror_object.name
        elif m.type == 'BEVEL':
            mod_info["width"] = float(getattr(m, "width", 0.0))
            mod_info["segments"] = int(getattr(m, "segments", 0))
            mod_info["profile"] = float(getattr(m, "profile", 0.5))
            mod_info["limit_method"] = str(getattr(m, "limit_method", ""))
            if hasattr(m, "offset_type"):
                mod_info["offset_type"] = str(m.offset_type)
        elif m.type == 'ARMATURE':
            mod_info["object"] = m.object.name if m.object else None
            mod_info["use_vertex_groups"] = bool(getattr(m, "use_vertex_groups", False))
            mod_info["use_bone_envelopes"] = bool(getattr(m, "use_bone_envelopes", False))
        elif m.type == 'SOLIDIFY':
            mod_info["thickness"] = float(getattr(m, "thickness", 0.0))
        elif m.type == 'LATTICE':
            mod_info["object"] = m.object.name if m.object else None
        elif m.type == 'NODES':
            if hasattr(m, "node_group") and m.node_group:
                mod_info["node_group"] = m.node_group.name
        mods.append(mod_info)
    result = {{"object": name, "modifiers": mods, "count": len(mods)}}
"""
        return _run_bpy(blend_file, script)

    # === Composite checks ===

    def check_object_exists(self, blend_file: str, object_name: str) -> dict:
        """Check if an object with the given name exists."""
        script = f"""
name = {json.dumps(object_name)}
obj = bpy.data.objects.get(name)
if obj:
    result = {{"exists": True, "name": obj.name, "type": obj.type, "location": list(obj.location)}}
else:
    result = {{"exists": False, "name": name}}
"""
        return _run_bpy(blend_file, script)

    def check_object_type(self, blend_file: str, object_name: str, expected_type: str) -> dict:
        """Check if an object has the expected type (MESH, CAMERA, LIGHT, etc.)."""
        script = f"""
name = {json.dumps(object_name)}
expected = {json.dumps(expected_type.upper())}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"match": False, "error": f"Object '{{name}}' not found"}}
else:
    result = {{"match": obj.type == expected, "object": name, "expected": expected, "actual": obj.type}}
"""
        return _run_bpy(blend_file, script)

    def check_object_count(self, blend_file: str, expected_count: int) -> dict:
        """Check the total number of objects in the scene."""
        script = f"""
expected = {expected_count}
actual = len(bpy.data.objects)
result = {{"match": actual == expected, "expected": expected, "actual": actual}}
"""
        return _run_bpy(blend_file, script)

    def check_material_exists(self, blend_file: str, material_name: str) -> dict:
        """Check if a material with the given name exists."""
        script = f"""
name = {json.dumps(material_name)}
mat = bpy.data.materials.get(name)
result = {{"exists": mat is not None, "name": name}}
if mat:
    result["use_nodes"] = mat.use_nodes
"""
        return _run_bpy(blend_file, script)

    def check_modifier_exists(self, blend_file: str, object_name: str, modifier_type: str) -> dict:
        """Check if an object has a modifier of the given type."""
        script = f"""
obj_name = {json.dumps(object_name)}
mod_type = {json.dumps(modifier_type.upper())}
obj = bpy.data.objects.get(obj_name)
if obj is None:
    result = {{"exists": False, "error": f"Object '{{obj_name}}' not found"}}
else:
    found = [m for m in obj.modifiers if m.type == mod_type]
    result = {{"exists": len(found) > 0, "object": obj_name, "modifier_type": mod_type, "count": len(found)}}
    if found:
        result["modifier_name"] = found[0].name
"""
        return _run_bpy(blend_file, script)

    def check_animation_exists(self, blend_file: str, object_name: str) -> dict:
        """Check if an object has animation data."""
        script = f"""
name = {json.dumps(object_name)}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"animated": False, "error": f"Object '{{name}}' not found"}}
else:
    has_anim = obj.animation_data is not None and obj.animation_data.action is not None
    result = {{"animated": has_anim, "object": name}}
    if has_anim:
        result["action"] = obj.animation_data.action.name
        result["frame_range"] = list(obj.animation_data.action.frame_range)
"""
        return _run_bpy(blend_file, script)

    def check_render_engine(self, blend_file: str, expected_engine: str) -> dict:
        """Check if the render engine matches (BLENDER_EEVEE, CYCLES, etc.)."""
        script = f"""
expected = {json.dumps(expected_engine.upper())}
actual = bpy.context.scene.render.engine
result = {{"match": actual == expected, "expected": expected, "actual": actual}}
"""
        return _run_bpy(blend_file, script)

    def check_resolution(self, blend_file: str, width: int, height: int) -> dict:
        """Check render resolution."""
        script = f"""
r = bpy.context.scene.render
result = {{
    "match": r.resolution_x == {width} and r.resolution_y == {height},
    "expected": [{width}, {height}],
    "actual": [r.resolution_x, r.resolution_y],
}}
"""
        return _run_bpy(blend_file, script)

    def check_collection_exists(self, blend_file: str, collection_name: str) -> dict:
        """Check if a collection exists."""
        script = f"""
name = {json.dumps(collection_name)}
col = bpy.data.collections.get(name)
result = {{"exists": col is not None, "name": name}}
if col:
    result["objects"] = [o.name for o in col.objects]
    result["object_count"] = len(col.objects)
"""
        return _run_bpy(blend_file, script)

    def check_vertex_count(self, blend_file: str, object_name: str, expected_count: int) -> dict:
        """Check vertex count of a mesh object."""
        script = f"""
name = {json.dumps(object_name)}
expected = {expected_count}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"match": False, "error": f"Object '{{name}}' not found"}}
elif obj.type != 'MESH':
    result = {{"match": False, "error": f"Object '{{name}}' is type {{obj.type}}, not MESH"}}
else:
    actual = len(obj.data.vertices)
    result = {{"match": actual == expected, "object": name, "expected": expected, "actual": actual}}
"""
        return _run_bpy(blend_file, script)

    def get_material_nodes(self, blend_file: str, material_name: str) -> dict:
        """Detailed node graph for a material: node types, input values, links."""
        script = f"""
mname = {json.dumps(material_name)}
mat = bpy.data.materials.get(mname)
if mat is None:
    result = {{"error": f"Material '{{mname}}' not found"}}
elif not mat.use_nodes or not mat.node_tree:
    result = {{"name": mname, "use_nodes": bool(mat.use_nodes), "nodes": [], "links": []}}
else:
    nt = mat.node_tree
    nodes = []
    for n in nt.nodes:
        entry = {{"name": n.name, "type": n.type, "bl_idname": n.bl_idname, "inputs": {{}}, "outputs_connected": {{}}}}
        for inp in n.inputs:
            try:
                val = inp.default_value
                if hasattr(val, "__len__"):
                    val = list(val)
                entry["inputs"][inp.name] = val
            except Exception:
                entry["inputs"][inp.name] = None
        for out in n.outputs:
            entry["outputs_connected"][out.name] = bool(out.is_linked)
        nodes.append(entry)
    links = []
    for l in nt.links:
        links.append({{
            "from_node": l.from_node.name, "from_socket": l.from_socket.name,
            "to_node": l.to_node.name, "to_socket": l.to_socket.name,
        }})
    result = {{"name": mname, "use_nodes": True, "nodes": nodes, "links": links}}
"""
        return _run_bpy(blend_file, script)

    def get_compositor_nodes(self, blend_file: str) -> dict:
        """Get compositor node tree: nodes with params, links, use_nodes flag."""
        script = """
scene = bpy.context.scene
result = {"use_nodes": bool(scene.use_nodes), "nodes": [], "links": []}
nt = scene.node_tree
if scene.use_nodes and nt is not None:
    for n in nt.nodes:
        entry = {"name": n.name, "type": n.type, "bl_idname": n.bl_idname}
        # common params
        for attr in ("size_x", "size_y", "glare_type", "blur_type", "filter_type", "factor"):
            if hasattr(n, attr):
                try:
                    v = getattr(n, attr)
                    entry[attr] = v if not hasattr(v, "__len__") else list(v)
                except Exception:
                    pass
        entry["inputs"] = {}
        for inp in n.inputs:
            try:
                v = inp.default_value
                if hasattr(v, "__len__"):
                    v = list(v)
                entry["inputs"][inp.name] = v
            except Exception:
                entry["inputs"][inp.name] = None
        result["nodes"].append(entry)
    for l in nt.links:
        result["links"].append({
            "from_node": l.from_node.name, "from_socket": l.from_socket.name,
            "to_node": l.to_node.name, "to_socket": l.to_socket.name,
        })
"""
        return _run_bpy(blend_file, script)

    def get_geometry_nodes(self, blend_file: str, object_name: str) -> dict:
        """Get geometry-nodes modifiers and their node trees on an object."""
        script = f"""
name = {json.dumps(object_name)}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"error": f"Object '{{name}}' not found"}}
else:
    out = []
    for m in obj.modifiers:
        if m.type != 'NODES':
            continue
        ng = m.node_group
        entry = {{"modifier_name": m.name, "node_group": ng.name if ng else None, "nodes": [], "links": []}}
        if ng is not None:
            for n in ng.nodes:
                ne = {{"name": n.name, "type": n.type, "bl_idname": n.bl_idname, "inputs": {{}}}}
                for inp in n.inputs:
                    try:
                        v = inp.default_value
                        if hasattr(v, "__len__"):
                            v = list(v)
                        ne["inputs"][inp.name] = v
                    except Exception:
                        ne["inputs"][inp.name] = None
                entry["nodes"].append(ne)
            for l in ng.links:
                entry["links"].append({{"from_node": l.from_node.name, "from_socket": l.from_socket.name, "to_node": l.to_node.name, "to_socket": l.to_socket.name}})
        out.append(entry)
    result = {{"object": name, "geometry_modifiers": out, "count": len(out)}}
"""
        return _run_bpy(blend_file, script)

    def get_shape_keys(self, blend_file: str, object_name: str) -> dict:
        """Get shape keys (basis + keys) on a mesh object."""
        script = f"""
name = {json.dumps(object_name)}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"error": f"Object '{{name}}' not found"}}
elif not hasattr(obj.data, "shape_keys") or obj.data.shape_keys is None:
    result = {{"object": name, "has_shape_keys": False, "keys": []}}
else:
    sk = obj.data.shape_keys
    keys = []
    for kb in sk.key_blocks:
        keys.append({{"name": kb.name, "value": kb.value, "slider_min": kb.slider_min, "slider_max": kb.slider_max, "mute": kb.mute}})
    result = {{"object": name, "has_shape_keys": True, "reference": sk.reference_key.name if sk.reference_key else None, "keys": keys}}
"""
        return _run_bpy(blend_file, script)

    def get_drivers(self, blend_file: str, object_name: str) -> dict:
        """Get drivers on an object (ID data-block + shape-key drivers) and
        custom properties with their UI ranges (min, max, soft_min, soft_max)."""
        script = f"""
name = {json.dumps(object_name)}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"error": f"Object '{{name}}' not found"}}
else:
    def _serialize_driver_fc(fc, source):
        d = fc.driver
        variables = []
        for var in d.variables:
            vinfo = {{"name": var.name, "type": var.type, "targets": []}}
            for tgt in var.targets:
                tinfo = {{
                    "id_type": getattr(tgt, "id_type", None),
                    "id": tgt.id.name if tgt.id else None,
                    "data_path": tgt.data_path,
                }}
                vinfo["targets"].append(tinfo)
            variables.append(vinfo)
        return {{
            "source": source,
            "data_path": fc.data_path,
            "array_index": fc.array_index,
            "expression": d.expression,
            "type": d.type,
            "variables": variables,
        }}

    drv_list = []
    ad = obj.animation_data
    if ad is not None:
        for fc in ad.drivers:
            drv_list.append(_serialize_driver_fc(fc, "object"))

    # Shape-key drivers live on obj.data.shape_keys.animation_data
    shape_key_drivers = []
    if getattr(obj, "data", None) is not None and hasattr(obj.data, "shape_keys"):
        sk = obj.data.shape_keys
        if sk is not None and sk.animation_data is not None:
            for fc in sk.animation_data.drivers:
                shape_key_drivers.append(_serialize_driver_fc(fc, "shape_key"))

    custom_props = {{}}
    custom_prop_ranges = {{}}
    for k in obj.keys():
        if k == "_RNA_UI":
            continue
        try:
            v = obj[k]
            if hasattr(v, "__len__") and not isinstance(v, str):
                v = list(v)
            custom_props[k] = v
        except Exception:
            custom_props[k] = None
        # Range / metadata (Blender 3.x: id_properties_ui)
        try:
            if hasattr(obj, "id_properties_ui"):
                ui = obj.id_properties_ui(k)
                if ui is not None:
                    meta = ui.as_dict() if hasattr(ui, "as_dict") else {{}}
                    clean = {{}}
                    for mk in ("min", "max", "soft_min", "soft_max", "default", "description", "subtype"):
                        if mk in meta:
                            mv = meta[mk]
                            if hasattr(mv, "__len__") and not isinstance(mv, str):
                                mv = list(mv)
                            clean[mk] = mv
                    custom_prop_ranges[k] = clean
        except Exception:
            pass

    result = {{
        "object": name,
        "drivers": drv_list,
        "shape_key_drivers": shape_key_drivers,
        "custom_properties": custom_props,
        "custom_property_ranges": custom_prop_ranges,
    }}
"""
        return _run_bpy(blend_file, script)

    def get_armature_bones(self, blend_file: str, armature_name: str) -> dict:
        """List bones of an armature with parent relations and head/tail."""
        script = f"""
name = {json.dumps(armature_name)}
obj = bpy.data.objects.get(name)
if obj is None or obj.type != 'ARMATURE':
    result = {{"error": f"Armature '{{name}}' not found"}}
else:
    arm = obj.data
    bones = []
    for b in arm.bones:
        bones.append({{
            "name": b.name,
            "parent": b.parent.name if b.parent else None,
            "head": list(b.head_local),
            "tail": list(b.tail_local),
            "use_connect": b.use_connect,
        }})
    result = {{"armature": name, "bones": bones, "count": len(bones)}}
"""
        return _run_bpy(blend_file, script)

    def get_pose_constraints(self, blend_file: str, armature_name: str, bone_name: str) -> dict:
        """Get constraints on a pose bone."""
        script = f"""
aname = {json.dumps(armature_name)}
bname = {json.dumps(bone_name)}
obj = bpy.data.objects.get(aname)
if obj is None or obj.type != 'ARMATURE':
    result = {{"error": f"Armature '{{aname}}' not found"}}
else:
    pb = obj.pose.bones.get(bname)
    if pb is None:
        result = {{"error": f"Pose bone '{{bname}}' not found"}}
    else:
        cons = []
        for c in pb.constraints:
            entry = {{"name": c.name, "type": c.type}}
            for attr in ("subtarget", "chain_count", "influence", "target_space", "owner_space"):
                if hasattr(c, attr):
                    try:
                        v = getattr(c, attr)
                        entry[attr] = v.name if hasattr(v, "name") else v
                    except Exception:
                        pass
            if hasattr(c, "target"):
                entry["target"] = c.target.name if c.target else None
            cons.append(entry)
        result = {{"armature": aname, "bone": bname, "constraints": cons}}
"""
        return _run_bpy(blend_file, script)

    def get_object_constraints(self, blend_file: str, object_name: str) -> dict:
        """Get object-level constraints (Copy Rotation, Child Of, Track To, Limit*, etc.)
        analogous to pose-constraints but reading obj.constraints instead of pose bone's."""
        script = f"""
name = {json.dumps(object_name)}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"error": f"Object '{{name}}' not found"}}
else:
    cons = []
    for c in obj.constraints:
        entry = {{"name": c.name, "type": c.type}}
        # Target object + subtarget (bone)
        if hasattr(c, "target"):
            entry["target"] = c.target.name if c.target else None
        for attr in ("subtarget", "chain_count", "influence", "track_axis", "up_axis",
                     "target_space", "owner_space"):
            if hasattr(c, attr):
                try:
                    v = getattr(c, attr)
                    entry[attr] = v.name if hasattr(v, "name") else v
                except Exception:
                    pass
        # Copy Rotation / Copy Location / Copy Scale axis toggles
        for axis_attr in ("use_x", "use_y", "use_z"):
            if hasattr(c, axis_attr):
                try:
                    entry[axis_attr] = bool(getattr(c, axis_attr))
                except Exception:
                    pass
        # Child Of: per-channel enables (use_location_x etc., use_rotation_x etc., use_scale_x etc.)
        for ch in ("location", "rotation", "scale"):
            for ax in ("x", "y", "z"):
                a = f"use_{{ch}}_{{ax}}"
                if hasattr(c, a):
                    try:
                        entry[a] = bool(getattr(c, a))
                    except Exception:
                        pass
        # Limit constraints: min/max per axis
        for attr in ("min_x", "min_y", "min_z", "max_x", "max_y", "max_z",
                     "use_min_x", "use_min_y", "use_min_z",
                     "use_max_x", "use_max_y", "use_max_z"):
            if hasattr(c, attr):
                try:
                    v = getattr(c, attr)
                    entry[attr] = bool(v) if isinstance(v, bool) else float(v)
                except Exception:
                    pass
        cons.append(entry)
    result = {{"object": name, "constraints": cons, "count": len(cons)}}
"""
        return _run_bpy(blend_file, script)

    def get_rigid_body_info(self, blend_file: str) -> dict:
        """Rigid body per-object settings + scene gravity + rigid_body_world."""
        script = """
scene = bpy.context.scene
result = {"gravity": list(scene.gravity)}
rbw = scene.rigidbody_world
if rbw is None:
    result["rigidbody_world"] = None
else:
    pc = rbw.point_cache
    result["rigidbody_world"] = {
        "enabled": rbw.enabled,
        "frame_start": pc.frame_start if pc else None,
        "frame_end": pc.frame_end if pc else None,
    }
result["objects"] = []
for obj in bpy.data.objects:
    rb = obj.rigid_body
    if rb is None:
        continue
    result["objects"].append({
        "name": obj.name,
        "type": rb.type,
        "mass": rb.mass,
        "collision_shape": rb.collision_shape,
        "enabled": rb.enabled,
        "kinematic": rb.kinematic,
    })
"""
        return _run_bpy(blend_file, script)

    def get_particle_systems(self, blend_file: str, object_name: str) -> dict:
        """Get particle systems on an object."""
        script = f"""
name = {json.dumps(object_name)}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"error": f"Object '{{name}}' not found"}}
else:
    systems = []
    for ps in obj.particle_systems:
        s = ps.settings
        systems.append({{
            "name": ps.name,
            "settings_name": s.name,
            "type": s.type,
            "count": s.count,
            "frame_start": s.frame_start,
            "frame_end": s.frame_end,
            "lifetime": s.lifetime,
            "hair_length": getattr(s, "hair_length", None),
        }})
    result = {{"object": name, "particle_systems": systems, "count": len(systems)}}
"""
        return _run_bpy(blend_file, script)

    def get_cloth_settings(self, blend_file: str, object_name: str) -> dict:
        """Get cloth modifier settings on an object."""
        script = f"""
name = {json.dumps(object_name)}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"error": f"Object '{{name}}' not found"}}
else:
    out = []
    for m in obj.modifiers:
        if m.type == 'CLOTH':
            s = m.settings
            out.append({{"modifier_name": m.name, "type": "CLOTH", "quality": s.quality, "mass": s.mass, "tension_stiffness": getattr(s, "tension_stiffness", None)}})
        elif m.type == 'COLLISION':
            out.append({{"modifier_name": m.name, "type": "COLLISION"}})
    result = {{"object": name, "cloth_or_collision": out}}
"""
        return _run_bpy(blend_file, script)

    def get_nla_tracks(self, blend_file: str, object_name: str) -> dict:
        """Get NLA tracks and strips on an object's animation_data."""
        script = f"""
name = {json.dumps(object_name)}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"error": f"Object '{{name}}' not found"}}
elif obj.animation_data is None:
    result = {{"object": name, "nla_tracks": []}}
else:
    tracks = []
    for t in obj.animation_data.nla_tracks:
        strips = []
        for s in t.strips:
            strips.append({{"name": s.name, "action": s.action.name if s.action else None, "frame_start": s.frame_start, "frame_end": s.frame_end}})
        tracks.append({{"name": t.name, "strips": strips, "mute": t.mute}})
    actions = [a.name for a in bpy.data.actions]
    result = {{"object": name, "nla_tracks": tracks, "actions_in_file": actions}}
"""
        return _run_bpy(blend_file, script)

    def get_grease_pencil(self, blend_file: str, object_name: str) -> dict:
        """Get grease pencil layers/frames/strokes on a GPENCIL object."""
        script = f"""
name = {json.dumps(object_name)}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"error": f"Object '{{name}}' not found"}}
elif obj.type != 'GPENCIL':
    result = {{"error": f"Object '{{name}}' not GPENCIL (type={{obj.type}})"}}
else:
    gp = obj.data
    layers = []
    for L in gp.layers:
        frames = []
        for f in L.frames:
            frames.append({{"frame_number": f.frame_number, "stroke_count": len(f.strokes), "point_counts": [len(s.points) for s in f.strokes]}})
        layers.append({{"name": L.info, "frames": frames}})
    result = {{"object": name, "type": "GPENCIL", "layers": layers}}
"""
        return _run_bpy(blend_file, script)

    def get_uv_maps(self, blend_file: str, object_name: str) -> dict:
        """Get UV maps on a mesh object."""
        script = f"""
name = {json.dumps(object_name)}
obj = bpy.data.objects.get(name)
if obj is None:
    result = {{"error": f"Object '{{name}}' not found"}}
elif obj.type != 'MESH':
    result = {{"error": f"Object '{{name}}' is not MESH"}}
else:
    me = obj.data
    maps = []
    active_name = me.uv_layers.active.name if me.uv_layers.active else None
    for u in me.uv_layers:
        # Count nonzero UVs to detect unwrapped
        nonzero = 0
        for d in u.data:
            if d.uv[0] != 0.0 or d.uv[1] != 0.0:
                nonzero += 1
        maps.append({{"name": u.name, "active": (u.name == active_name), "uv_count": len(u.data), "nonzero_uv_count": nonzero}})
    result = {{"object": name, "uv_maps": maps, "active": active_name}}
"""
        return _run_bpy(blend_file, script)

    def force_save_via_gui(self, blend_file: str = None) -> dict:
        """Send Ctrl+S to the running Blender window via xdotool to flush session to disk."""
        import time

        pre_mtime = None
        if blend_file and os.path.exists(blend_file):
            pre_mtime = os.path.getmtime(blend_file)

        try:
            find = subprocess.run(
                ["xdotool", "search", "--name", "Blender"],
                capture_output=True, text=True, timeout=5,
            )
            windows = [w for w in find.stdout.strip().split("\n") if w.strip()]
            if not windows:
                return {"saved": False, "error": "No Blender window found"}

            wid = windows[0]
            subprocess.run(["xdotool", "windowactivate", "--sync", wid], timeout=5)
            time.sleep(0.5)
            subprocess.run(["xdotool", "key", "ctrl+s"], timeout=5)
            time.sleep(3)

            result = {"saved": True, "window_id": wid}
            if blend_file and os.path.exists(blend_file):
                post_mtime = os.path.getmtime(blend_file)
                result["mtime_changed"] = pre_mtime is not None and post_mtime > pre_mtime
            return result
        except FileNotFoundError:
            return {"saved": False, "error": "xdotool not found"}
        except Exception as e:
            return {"saved": False, "error": str(e)}

    def check_file_exists(self, file_path: str) -> dict:
        """Check if a file exists on disk."""
        p = Path(file_path)
        if p.exists():
            return {"exists": True, "path": str(p), "size": p.stat().st_size}
        return {"exists": False, "path": str(p)}


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

COMMANDS = {
    # Query endpoints (all require blend_file as first arg)
    "objects": ("List all objects", lambda v, a: v.get_objects(a[0])),
    "object-info": ("Get object details", lambda v, a: v.get_object_info(a[0], a[1])),
    "materials": ("List all materials", lambda v, a: v.get_materials(a[0])),
    "scene-info": ("Get scene metadata", lambda v, a: v.get_scene_info(a[0])),
    "collections": ("List collections", lambda v, a: v.get_collections(a[0])),
    "animations": ("Get animation data", lambda v, a: v.get_animations(a[0], a[1] if len(a) > 1 else None)),
    "modifiers": ("Get object modifiers", lambda v, a: v.get_modifiers(a[0], a[1])),
    "material-nodes": ("Get material node tree", lambda v, a: v.get_material_nodes(a[0], a[1])),
    "compositor-nodes": ("Get compositor node tree", lambda v, a: v.get_compositor_nodes(a[0])),
    "geometry-nodes": ("Get object's geometry node modifiers", lambda v, a: v.get_geometry_nodes(a[0], a[1])),
    "shape-keys": ("Get mesh shape keys", lambda v, a: v.get_shape_keys(a[0], a[1])),
    "drivers": ("Get drivers + custom props on object", lambda v, a: v.get_drivers(a[0], a[1])),
    "armature-bones": ("Get armature bones", lambda v, a: v.get_armature_bones(a[0], a[1])),
    "pose-constraints": ("Get pose bone constraints", lambda v, a: v.get_pose_constraints(a[0], a[1], a[2])),
    "object-constraints": ("Get object-level constraints (Copy Rot, Child Of, Track To, ...)", lambda v, a: v.get_object_constraints(a[0], a[1])),
    "rigid-body-info": ("Get rigid body + gravity info", lambda v, a: v.get_rigid_body_info(a[0])),
    "particle-systems": ("Get particle systems on object", lambda v, a: v.get_particle_systems(a[0], a[1])),
    "cloth-settings": ("Get cloth / collision modifier settings", lambda v, a: v.get_cloth_settings(a[0], a[1])),
    "nla-tracks": ("Get NLA tracks/strips on object", lambda v, a: v.get_nla_tracks(a[0], a[1])),
    "grease-pencil": ("Get grease pencil data", lambda v, a: v.get_grease_pencil(a[0], a[1])),
    "uv-maps": ("Get UV maps on mesh", lambda v, a: v.get_uv_maps(a[0], a[1])),

    # Check endpoints (blend_file first, then check-specific args)
    "check-object-exists": ("Check object exists", lambda v, a: v.check_object_exists(a[0], a[1])),
    "check-object-type": ("Check object type", lambda v, a: v.check_object_type(a[0], a[1], a[2])),
    "check-object-count": ("Check object count", lambda v, a: v.check_object_count(a[0], int(a[1]))),
    "check-material-exists": ("Check material exists", lambda v, a: v.check_material_exists(a[0], a[1])),
    "check-modifier-exists": ("Check modifier on object", lambda v, a: v.check_modifier_exists(a[0], a[1], a[2])),
    "check-animation-exists": ("Check object animated", lambda v, a: v.check_animation_exists(a[0], a[1])),
    "check-render-engine": ("Check render engine", lambda v, a: v.check_render_engine(a[0], a[1])),
    "check-resolution": ("Check render resolution", lambda v, a: v.check_resolution(a[0], int(a[1]), int(a[2]))),
    "check-collection-exists": ("Check collection exists", lambda v, a: v.check_collection_exists(a[0], a[1])),
    "check-vertex-count": ("Check mesh vertex count", lambda v, a: v.check_vertex_count(a[0], a[1], int(a[2]))),
    "check-file-exists": ("Check file exists", lambda v, a: v.check_file_exists(a[0])),
    "force-save-via-gui": ("Force-save Blender via Ctrl+S", lambda v, a: v.force_save_via_gui(a[0] if a else None)),
}


def _print_usage():
    print("Blender Verifier — inspect .blend files for RL/evaluation reward signals")
    print(f"\nUsage: python3 {sys.argv[0]} <command> <blend_file> [args...]\n")
    print("Commands:")
    mx = max(len(n) for n in COMMANDS)
    for n, (d, _) in COMMANDS.items():
        print(f"  {n:<{mx + 2}} {d}")
    print("\nAll commands require a .blend file path as the first argument.")
    print("Uses blender -b (headless) + bpy Python API.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {cmd}"}))
        sys.exit(1)

    v = BlenderVerifier()
    _, handler = COMMANDS[cmd]

    try:
        result = handler(v, args)
    except IndexError:
        print(json.dumps({"error": f"Missing required argument for '{cmd}'"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))
