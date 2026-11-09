"""Header layout variants and appearance overrides in an assembly's display list.

usage: probe_headers.py <dir containing swreader> <assembly>
Read-only.
"""

import math
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, sys.argv[1])

from swreader import DISPLAY_LISTS, INSTANCE_TREE  # noqa: E402
from swreader.container import find_block, read_blocks  # noqa: E402
from swreader.displaylist import read_sections, read_tables  # noqa: E402

path = Path(sys.argv[2])
blocks = read_blocks(path.read_bytes())
data = find_block(blocks, DISPLAY_LISTS).inflate()
sections, _ = read_sections(data, read_tables(data))
tree = find_block(blocks, INSTANCE_TREE).inflate().decode("utf-8", "replace")

sane = Counter()
shown = 0
for s in sections:
    ok = s.world is not None and all(abs(v) < 1e4 and not math.isnan(v) for v in s.world.ravel())
    stop = s.name_end
    sane[(ok, data[stop])] += 1
    if not ok and shown < 6:
        shown += 1
        print(f"BAD {s.instance[-70:]}\n   first bytes {data[stop:stop + 150].hex()}")
print("(sane placement, first byte after name):", sane.most_common(12))

print("--- instance appearances")
counts = Counter(s.appearance for s in sections)
print(counts.most_common(14))
red = [s for s in sections if s.appearance and s.appearance[0] > s.appearance[1] + 50 and s.appearance[0] > s.appearance[2] + 50]
print("reddish instance overrides:", len(red))
for s in red[:8]:
    print("  ", s.appearance, s.instance[-90:], "tables", len(s.tables))

faces = Counter(t.appearance for s in sections for t in s.tables)
print("--- table appearances", faces.most_common(14))
red_faces = [(s, t) for s in sections for t in s.tables
             if t.appearance and t.appearance[0] > t.appearance[1] + 50 and t.appearance[0] > t.appearance[2] + 50]
print("reddish tables:", len(red_faces))
seen = set()
for s, t in red_faces:
    if s.file not in seen and len(seen) < 8:
        seen.add(s.file)
        print("  ", t.appearance, s.file, s.instance[-70:])

import re  # noqa: E402
print("--- swProperty samples:", re.findall(r"<swProperty [^>]*>", tree)[:6])
print("transparent appearances:", Counter(a for a in list(counts) + list(faces) if a and a[3] < 1).most_common(10))
