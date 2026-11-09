"""Do stray pattern members differ from in-box ones in tree or header bytes?

usage: probe_pattern.py <dir containing swreader> <assembly> <part stem>
Read-only.
"""

import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, sys.argv[1])

from swreader import DISPLAY_LISTS, INSTANCE_TREE  # noqa: E402
from swreader.container import find_block, read_blocks  # noqa: E402
from swreader.displaylist import read_sections, read_tables  # noqa: E402

path, stem = Path(sys.argv[2]), sys.argv[3]
blocks = read_blocks(path.read_bytes())
xml = ElementTree.fromstring(find_block(blocks, INSTANCE_TREE).inflate().decode("utf-8", "replace"))
parents = {c: p for p in xml.iter() for c in p}

refs = [e for e in xml.iter() if e.tag.endswith("swReference") and e.get("swName") == stem]
model_el = parents[refs[0]]
print("model", {k: v[:300] for k, v in model_el.attrib.items()})
members = [e for e in refs if parents[e] is model_el]
print(f"{len(members)} members; other children of the model:",
      Counter(c.tag.rsplit('}', 1)[-1] for c in model_el))
for e in sorted(members, key=lambda e: int(e.get("swReferenceNumber")))[:40]:
    print(f"  #{e.get('swReferenceNumber'):>3} stamp={e.get('swTransformStamp')} swID={e.get('swID')} "
          f"xyz={' '.join(e.get('swTransform').split()[12:15])}")

data = find_block(blocks, DISPLAY_LISTS).inflate()
sections, _ = read_sections(data, read_tables(data))
scope = [s for s in sections if f"/{stem}-" in s.instance]
first = scope[0].instance.rsplit("/", 1)[0]
group = {s.instance.rsplit("/", 1)[1].split("@")[0]: s for s in scope if s.instance.startswith(first + "/")}
print("group", first[-90:], len(group), "drawn:", sum(s.drawn for s in group.values()))
names = sorted(group, key=lambda n: int(n.rsplit("-", 1)[1]))
base = group[names[0]]
base_bytes = data[base.name_end : base.name_end + 700]
for name in names:
    s = group[name]
    other = data[s.name_end : s.name_end + 700]
    diff = [i for i, (a, b) in enumerate(zip(base_bytes, other)) if a != b]
    print(f"  {name} drawn={s.drawn} diffs={len(diff)} at {diff[:14]} ... {diff[-4:]}")

print("--- bytes 200..470 past the name")
for name in names[:1] + names[13:15] + names[-1:]:
    s = group[name]
    raw = data[s.name_end + 200 : s.name_end + 470]
    print(f"{name}\n  " + " ".join(raw[i : i + 8].hex() for i in range(0, len(raw), 8)))
