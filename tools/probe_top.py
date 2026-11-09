"""Bounds of each top-level component against the stored box, plus outlier chains.

usage: probe_top.py <dir containing swreader> <assembly>
Read-only.
"""

import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])

import numpy as np  # noqa: E402
from swreader import DISPLAY_LISTS, read_assembly  # noqa: E402
from swreader.container import find_block, read_blocks  # noqa: E402
from swreader.displaylist import BOUNDS, PLACE, ROTATION, read_sections, read_tables  # noqa: E402

path = Path(sys.argv[2])
model = read_assembly(path)
lo, hi = model.bounding_box
print("stored box", np.round(lo, 3), np.round(hi, 3))


def bounds(node, parent):
    matrix = parent @ node.matrix
    lows, highs = [], []
    if node.part is not None:
        v = model.parts[node.part].positions.astype(np.float64)
        p = v @ matrix[:3, :3].T + matrix[:3, 3]
        lows.append(p.min(axis=0))
        highs.append(p.max(axis=0))
    for c in node.children:
        b = bounds(c, matrix)
        if b:
            lows.append(b[0])
            highs.append(b[1])
    return (np.min(lows, axis=0), np.max(highs, axis=0)) if lows else None


blocks = read_blocks(path.read_bytes())
data = find_block(blocks, DISPLAY_LISTS).inflate()
sections, _ = read_sections(data, read_tables(data))
by_name = {s.instance: s for s in sections}
print("sections hidden by the header list:", sum(s.hidden for s in sections), "of", len(sections))
print("--- top level: hidden, header list, outside stored box by, bounds")
rows = []
for child in model.root.children:
    b = bounds(child, np.identity(4))
    if b is None:
        continue
    over = max((lo - b[0]).max(), (b[1] - hi).max())
    listed = by_name.get(f"{child.name}@{path.stem}")
    rows.append((over, child.name, child.hidden, b, bool(listed and listed.hidden)))
rows.sort(key=lambda r: (-r[2], -r[0]))
for over, name, hidden, b, listed in rows[:12]:
    print(f"  {'HID' if hidden else '   '} list={listed!s:5} over={over * 1000:8.1f}mm {name:28} {np.round(b[0], 2)} {np.round(b[1], 2)}")

print("--- leaves outside the stored box, with their display-list bounds")
shown = [0]


def leaves(node, parent, scope, parent_stem, hidden):
    matrix = parent @ node.matrix
    hidden = hidden or node.hidden
    for child in node.children:
        stem = child.name.rsplit("-", 1)[0]
        step = f"{child.name}@{parent_stem}"
        instance = f"{scope}/{step}" if scope else step
        if child.part is not None and not hidden and not child.hidden:
            b = bounds(type(child)(child.name, child.matrix, part=child.part), matrix)
            if b and max((lo - b[0]).max(), (b[1] - hi).max()) > 0.01 and shown[0] < 8:
                shown[0] += 1
                s = by_name.get(instance)
                extra = ""
                if s is not None:
                    at = s.name_end + 1 + (ROTATION.size if data[s.name_end] == 1 else 0) + PLACE.size + 1
                    extra = f"bounds={np.round(BOUNDS.unpack_from(data, at), 3).tolist()} flag={data[s.name_end]}"
                print(f"  {instance[-80:]} {extra}")
        leaves(child, matrix, instance, stem, hidden)


leaves(model.root, np.identity(4), "", path.stem, False)
