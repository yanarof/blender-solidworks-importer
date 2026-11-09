"""Compare a stray pattern instance with a well-placed one, tree and display list.

usage: probe_stray.py <dir containing swreader> <assembly> <name stem> <good n> <stray n>
Read-only.
"""

import sys
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, sys.argv[1])

from swreader import DISPLAY_LISTS, INSTANCE_TREE  # noqa: E402
from swreader.container import find_block, read_blocks  # noqa: E402
from swreader.displaylist import _strings, read_sections, read_tables  # noqa: E402

path, stem, good, stray = Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
blocks = read_blocks(path.read_bytes())
xml_text = find_block(blocks, INSTANCE_TREE).inflate().decode("utf-8", "replace")
xml = ElementTree.fromstring(xml_text)

parents = {c: p for p in xml.iter() for c in p}
for number in (good, stray):
    for el in xml.iter():
        if el.tag.endswith("swReference") and el.get("swName") == stem and el.get("swReferenceNumber") == number:
            print(f"--- {stem}-{number}: parent model {parents[el].get('id')} "
                  f"config={parents[el].get('swConfigurationName')!r}")
            print({k: v for k, v in el.attrib.items() if k not in ("swName", "swComponentName")})
            print("   children:", [c.tag.rsplit('}', 1)[-1] for c in el])
            break

for el in xml.iter():
    tag = el.tag.rsplit("}", 1)[-1]
    if tag in ("swDisplayState", "swDisplayStateList"):
        text = " ".join(f"{k}={v[:300]}" for k, v in el.attrib.items())
        if f"{stem}-{stray}" in str(el.attrib) or tag == "swDisplayState":
            print(tag, text[:400])
            break

print("mentions of stray instance in tree:", xml_text.count(f"{stem}-{stray}"))

data = find_block(blocks, DISPLAY_LISTS).inflate()
tables = read_tables(data)
sections, _ = read_sections(data, tables)
for number in (good, stray):
    hits = [s for s in sections if f"/{stem}-{number}@" in s.instance or s.instance.startswith(f"{stem}-{number}@")]
    print(f"--- display list {stem}-{number}: {len(hits)} sections; "
          f"tables={[len(s.tables) for s in hits][:6]} {hits[0].instance if hits else ''}")
    if hits:
        needle = hits[0].instance.encode("utf-16-le")
        at = data.find(needle)
        print("   before:", data[at - 40 : at].hex())
        after = data[at + len(needle) : at + len(needle) + 260]
        print("   after :", after.hex())
