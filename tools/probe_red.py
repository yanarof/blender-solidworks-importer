"""Why do some leaves come out reddish? Lists them with their overrides.

usage: probe_red.py <dir containing swreader> <assembly>
Read-only.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, sys.argv[1])

from swreader import DISPLAY_LISTS, INSTANCE_TREE, read_assembly  # noqa: E402
from swreader.container import find_block, read_blocks  # noqa: E402

path = Path(sys.argv[2])
model = read_assembly(path)
blocks = read_blocks(path.read_bytes())
tree = find_block(blocks, INSTANCE_TREE).inflate().decode("utf-8", "replace")
properties = re.findall(r'<swProperty [^>]*swReference="([^"]*)" swColor="([^"]*)"', tree)
print(f"{len(properties)} swProperty entries; colour histogram:",
      Counter(c for _r, c in properties).most_common(8))


def reddish(a):
    return a and a[0] > a[1] + 50 and a[0] > a[2] + 50


rows = Counter()
trails = {}


def visit(node, inherited, trail):
    effective = inherited or node.appearance
    if node.part is not None:
        faces = model.parts[node.part].appearances
        shown = effective or max(Counter(f for f in faces if f).items(), key=lambda kv: kv[1], default=(None,))[0]
        if reddish(shown):
            key = (model.part_names[node.part], shown, effective is not None)
            rows[key] += 1
            trails.setdefault(key, "/".join(trail + [node.name]))
    for child in node.children:
        visit(child, effective, trail + [node.name])


visit(model.root, None, [])
print(f"{sum(rows.values())} reddish leaves in {len(rows)} part/colour combinations")
for (part, colour, overridden), n in rows.most_common(15):
    print(f"  x{n:<4} {part} {colour} overridden={overridden}  {trails[(part, colour, overridden)][-90:]}")
print("--- reddish parts mentioned in swProperty:")
names = {part for (part, _c, _o) in rows}
hits = [(r, c) for r, c in properties if any(n in r for n in names)]
print(len(hits), hits[:6])
