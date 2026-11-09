"""Explain bounding box drift and missing components for one assembly.

usage: diagnose.py <dir containing swreader> <assembly>
Read-only.
"""

import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, sys.argv[1])

import numpy as np  # noqa: E402
from swreader import INSTANCE_TREE, read_assembly, world_bounds  # noqa: E402
from swreader.container import find_block, read_blocks  # noqa: E402

path = Path(sys.argv[2])
m = read_assembly(path)
print("config", m.configuration, "stored box", m.bounding_box)
print("our box", world_bounds(m))
print("from part files:", m.from_part_files[:10])


def bounds(node, parent):
    matrix = parent @ node.matrix
    lows, highs = [], []
    if node.part is not None:
        v = m.parts[node.part].positions.astype(np.float64)
        p = v @ matrix[:3, :3].T + matrix[:3, 3]
        lows.append(p.min(axis=0))
        highs.append(p.max(axis=0))
    for c in node.children:
        if c.hidden:
            continue
        b = bounds(c, matrix)
        if b:
            lows.append(b[0])
            highs.append(b[1])
    return (np.min(lows, axis=0), np.max(highs, axis=0)) if lows else None


lo, hi = m.bounding_box
rows = []


def leaves(node, parent, trail):
    matrix = parent @ node.matrix
    if node.hidden:
        return
    if node.part is not None:
        b = bounds(Node0(node), matrix)
        if b:
            over = max((lo - b[0]).max(), (b[1] - hi).max())
            rows.append((over, "/".join(trail + [node.name]), (b[1] - b[0]) * 1000, m.part_names[node.part]))
    for c in node.children:
        leaves(c, matrix, trail + [node.name])


class Node0:
    def __init__(self, n):
        self.part, self.children, self.matrix = n.part, [], np.identity(4)


leaves(m.root, np.identity(4), [])
rows.sort(key=lambda r: -r[0])
print(f"--- leaves furthest outside the stored box ({sum(1 for r in rows if r[0] > 0.01)} of {len(rows)} beyond 10 mm)")
for over, name, size, part in rows[:12]:
    print(f"  {over * 1000:8.1f}mm  size {size[0]:.0f}x{size[1]:.0f}x{size[2]:.0f}  {part}  {name[-110:]}")

xml = ElementTree.fromstring(
    find_block(read_blocks(path.read_bytes()), INSTANCE_TREE).inflate().decode("utf-8", "replace")
)
refs = {}
for el in xml.iter():
    if el.tag.endswith("swReference"):
        refs.setdefault(f"{el.get('swName')}-{el.get('swReferenceNumber')}", el)
print("--- missing components by name stem, with their flags")
stems = Counter()
flags = Counter()
for name in m.missing:
    stems[name.rsplit("-", 1)[0]] += 1
    r = refs.get(name)
    if r is not None:
        flags[(r.get("swHidden"), r.get("swIsVirtualComponent"), r.get("swDisplayMode"), r.get("swConfigurationName"))] += 1
print(" ", stems.most_common(15))
print(" ", flags.most_common(10))
