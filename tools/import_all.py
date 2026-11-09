"""Import every given file through the real operator, in one Blender process.

usage: blender --background --factory-startup --python import_all.py -- <repo dir> <list file>
The list file holds one CAD path per line. Prints one RESULT line per file.
"""

import importlib.util
import sys
import time
import traceback
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1 :]
repo, listing = Path(args[0]), Path(args[1])

spec = importlib.util.spec_from_file_location(
    "solidworks_import", repo / "solidworks_import" / "__init__.py",
    submodule_search_locations=[str(repo / "solidworks_import")],
)
addon = importlib.util.module_from_spec(spec)
sys.modules["solidworks_import"] = addon
spec.loader.exec_module(addon)

for line in listing.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon.register()
    started = time.time()
    try:
        result = bpy.ops.import_scene.solidworks(filepath=line)
        print(f"RESULT {result} {Path(line).name} objects={len(bpy.data.objects)} "
              f"meshes={len(bpy.data.meshes)} materials={len(bpy.data.materials)} "
              f"{time.time() - started:.1f}s", flush=True)
    except Exception:
        print(f"RESULT FAIL {Path(line).name}\n{traceback.format_exc()}", flush=True)
    addon.unregister()
