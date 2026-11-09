"""Where do colours and stray instances come from in an assembly's display list?

usage: probe_colors.py <dir containing swreader> <assembly>
Read-only.
"""

import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, sys.argv[1])

from swreader import DISPLAY_LISTS, read_assembly  # noqa: E402
from swreader.container import find_block, read_blocks  # noqa: E402
from swreader.displaylist import (  # noqa: E402
    INSTANCE_NAME, _strings, read_sections, read_tables,
)

path = Path(sys.argv[2])
data = find_block(read_blocks(path.read_bytes()), DISPLAY_LISTS).inflate()
tables = read_tables(data)
sections, loose = read_sections(data, tables)
print(f"{len(tables)} tables, {len(sections)} sections, {len(loose)} loose")
names = {s.instance for s in sections}
print(f"distinct instance headers {len(names)}")


def props(start, end):
    """(offset, tag, colour, second, display, material, optics) for each visual property."""
    strings = list(_strings(data, start, end))
    for i, (at, stop, text) in enumerate(strings):
        if at - 14 < start:
            continue
        tag, color, zero, second = struct.unpack_from("<HIII", data, at - 14)
        if not tag & 0x8000 or zero or color >> 24 or second >> 24:
            continue
        # A second framed string follows directly, then six f64 optics.
        if i + 1 < len(strings) and strings[i + 1][0] == stop:
            material, end2 = strings[i + 1][2], strings[i + 1][1]
        else:
            material, end2 = "", stop + 4
        optics = struct.unpack_from("<6d", data, end2) if end2 + 48 <= end else ()
        yield at, tag, color, second, text, material, [round(o, 3) for o in optics]


# Gaps, each classified by whether an instance header starts in it.
tags = Counter()
placement = Counter()
shown = 0
for i, table in enumerate(tables[:-1]):
    start, end = table.end, tables[i + 1].start
    header_at = next(
        (at for at, _s, t in _strings(data, start, end) if INSTANCE_NAME.fullmatch(t)), None
    )
    for at, tag, color, second, text, material, optics in props(start, end):
        tags[tag] += 1
        where = "before-header" if header_at is None or at < header_at else "after-header"
        placement[(where, "first-in-gap" if at - start < 200 else "later")] += 1
        if shown < 40 and (i % 500 < 3 or header_at is not None and i % 97 == 0):
            shown += 1
            rgb = (color & 255, color >> 8 & 255, color >> 16 & 255)
            print(f"t{i} +{at - start} gap={end - start} {where} tag={tag:#x} rgb={rgb} "
                  f"second={second:#x} {text!r} {material!r} optics={optics}")
print("tags", tags.most_common(6))
print("placement", placement.most_common())

# Stray test: are tree instances without a display-list header the outliers?
model = read_assembly(path)
lo, hi = model.bounding_box
print("--- sample of header names:", sorted(names)[:3])
