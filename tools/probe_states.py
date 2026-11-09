"""How are display states and property overrides stored in the instance tree?

usage: probe_states.py <dir containing swreader> <assembly> <name fragment> [...]
Read-only.
"""

import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, sys.argv[1])

from swreader import DISPLAY_LISTS, INSTANCE_TREE  # noqa: E402
from swreader.container import find_block, read_blocks  # noqa: E402
from swreader.displaylist import _appearance, _strings, read_sections, read_tables  # noqa: E402

path = Path(sys.argv[2])
blocks = read_blocks(path.read_bytes())
xml = ElementTree.fromstring(find_block(blocks, INSTANCE_TREE).inflate().decode("utf-8", "replace"))
parents = {c: p for p in xml.iter() for c in p}


def local(el):
    return el.tag.rsplit("}", 1)[-1]


def describe(el):
    p = parents.get(el)
    trail = []
    while p is not None:
        trail.append(f"{local(p)}[{p.get('swName') or p.get('id') or ''}|{p.get('swConfigurationName') or ''}]")
        p = parents.get(p)
    return " < ".join(trail)


print("--- configurations")
for el in xml.iter():
    if local(el) == "swConfiguration" and local(parents[el]) == "swConfigurationList":
        print({k: v[:80] for k, v in el.attrib.items()})

print("--- display state lists")
lists = [el for el in xml.iter() if local(el) == "swDisplayStateList"]
print(len(lists), "lists; first parents:")
for el in lists[:3]:
    names = el.get("swCompNameList", "").split(",")
    print(f"  {describe(el)[:160]} comps={len(names)} sample={names[:3]}")
    for state in el:
        show = state.get("swShowState", "").split(",")
        print(f"     {local(state)} {state.get('swDisplayStateName')} shows={Counter(show).most_common(3)} attrs={list(state.attrib)}")

print("--- property lists")
props = [el for el in xml.iter() if local(el) == "swPropertyList"]
print(len(props), "lists")
for el in props[:6]:
    print(f"  {describe(el)[:200]} entries={len(el)} attrs={dict(el.attrib)}")

data = find_block(blocks, DISPLAY_LISTS).inflate()
sections, _ = read_sections(data, read_tables(data))
for fragment in sys.argv[3:]:
    print(f"=== {fragment}")
    print(" in display state names:", sum(fragment in el.get("swCompNameList", "") for el in lists))
    for el in xml.iter():
        if local(el) == "swProperty" and fragment in el.get("swReference", ""):
            print("  property", el.get("swReference")[:90], el.get("swColor"), "|", describe(el)[:90])
            break
    hit = next((s for s in sections if fragment in s.instance and s.tables), None)
    if hit is None:
        continue
    print(" section", hit.instance[-80:], "appearance", hit.appearance, "tables", len(hit.tables))
    start = hit.name_end
    end = hit.tables[0].start
    strings = list(_strings(data, start, end))
    print("  header strings:", [s[2][:40] for s in strings][:18])
    t = hit.tables[0]
    following = next((x for x in sections if x.name_end > t.end), None)
    limit = hit.tables[1].start if len(hit.tables) > 1 else (following.name_end if following else t.end + 3000)
    strings = list(_strings(data, t.end, limit))
    print(f"  gap after first table ({limit - t.end} B) strings:", [s[2][:40] for s in strings][:18])
    for i in range(len(strings)):
        found = _appearance(data, strings, i, t.end, limit)
        if found:
            print("   appearance", found, "at +", strings[i][0] - t.end, repr(strings[i][2][:30]), repr(strings[i + 1][2][:30]))
