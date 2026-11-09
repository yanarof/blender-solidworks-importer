"""Import a file through the real operator, render it, extract the SolidWorks preview.

usage: blender --background --factory-startup --python blender_render_check.py -- \
           <repo dir> <cad file> <output dir> [view azimuth deg] [view elevation deg]

Writes <stem>_render.png and <stem>_preview.png (the picture SolidWorks saved in
the file) so they can be compared by eye. Read-only with respect to the CAD file.
"""

import importlib.util
import math
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1 :]
repo, cad, out = Path(args[0]), Path(args[1]), Path(args[2])
azimuth = math.radians(float(args[3])) if len(args) > 3 else math.radians(35)
elevation = math.radians(float(args[4])) if len(args) > 4 else math.radians(25)
out.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "solidworks_import", repo / "solidworks_import" / "__init__.py",
    submodule_search_locations=[str(repo / "solidworks_import")],
)
addon = importlib.util.module_from_spec(spec)
sys.modules["solidworks_import"] = addon
spec.loader.exec_module(addon)

from solidworks_import.swreader.container import find_block, read_blocks  # noqa: E402

bpy.ops.wm.read_factory_settings(use_empty=True)
addon.register()

t0 = time.time()
result = bpy.ops.import_scene.solidworks(filepath=str(cad))
print(f"IMPORT {result} in {time.time() - t0:.1f}s; "
      f"objects={len(bpy.data.objects)} meshes={len(bpy.data.meshes)} materials={len(bpy.data.materials)}")

scene = bpy.context.scene
depsgraph = bpy.context.evaluated_depsgraph_get()
lo = Vector((1e9, 1e9, 1e9))
hi = -lo
for obj in bpy.data.objects:
    if obj.type == "MESH" and not obj.hide_render:
        for corner in obj.bound_box:
            p = obj.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
center = (lo + hi) / 2
radius = (hi - lo).length / 2
print(f"BOUNDS size={tuple(round(v, 3) for v in (hi - lo))} m center={tuple(round(v, 3) for v in center)}")

camera_data = bpy.data.cameras.new("check")
camera_data.lens = 70
camera_data.clip_end = radius * 40 + 100
camera = bpy.data.objects.new("check", camera_data)
scene.collection.objects.link(camera)
direction = Vector((
    math.cos(elevation) * math.sin(azimuth),
    -math.cos(elevation) * math.cos(azimuth),
    math.sin(elevation),
))
camera.location = center + direction * radius * 4.2
camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = camera

world = bpy.data.worlds.new("check")
world.color = (1, 1, 1)
scene.world = world
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "MATERIAL"
scene.display.shading.show_cavity = False
scene.render.resolution_x = 900
scene.render.resolution_y = 700
scene.render.filepath = str(out / f"{cad.stem}_render.png")
bpy.ops.render.render(write_still=True)
print("RENDER", scene.render.filepath)

blocks = read_blocks(cad.read_bytes())
for name in ("PreviewPNG", "Preview"):
    block = find_block(blocks, name)
    if block is not None:
        data = block.inflate()
        if data.startswith(b"\x89PNG"):
            (out / f"{cad.stem}_preview.png").write_bytes(data)
            print("PREVIEW written")
            break
