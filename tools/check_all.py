"""Read every given file with swreader; compare bounds with the stored box.

usage: check_all.py <dir containing swreader> <file> [<file> ...]
Read-only with respect to the CAD files. One line per file.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])

import numpy as np  # noqa: E402
from swreader import SolidWorksError, read_file, world_bounds  # noqa: E402


def count(node):
    total = 1 if node.part or node.missing else 0
    return total + sum(count(c) for c in node.children)


for arg in sys.argv[2:]:
    path = Path(arg)
    t0 = time.time()
    label = f"{path.parent.name}/{path.name} {path.stat().st_size / 1e6:.1f}MB"
    try:
        m = read_file(path)
    except SolidWorksError as exc:
        print(f"NONE {label} | {exc} {time.time() - t0:.1f}s", flush=True)
        continue
    except Exception as exc:
        print(f"FAIL {label} | {type(exc).__name__}: {exc} {time.time() - t0:.1f}s", flush=True)
        continue
    tris = sum(len(p.triangles) for p in m.parts.values())
    colors = sum(1 for p in m.parts.values() if any(p.appearances))
    box = world_bounds(m)
    drift = ""
    if m.bounding_box is not None and box is not None:
        stored = m.bounding_box
        drift = f" boxdiff={max(np.abs(box[0] - stored[0]).max(), np.abs(box[1] - stored[1]).max()) * 1000:.1f}mm"
    size = (box[1] - box[0]) * 1000 if box else np.zeros(3)
    print(f"OK   {label} | leaves={count(m.root)} missing={len(m.missing)} suppressed={m.suppressed} undrawn={m.undrawn} drift={m.placement_drift * 1000:.2f}mm rot={m.rotation_drift:.5f} "
          f"parts={len(m.parts)} files={len(m.from_part_files)} tris={tris:,} coloured={colors} "
          f"size={size[0]:.0f}x{size[1]:.0f}x{size[2]:.0f}mm{drift} {time.time() - t0:.1f}s", flush=True)
