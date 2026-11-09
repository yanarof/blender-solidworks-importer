"""List every visual property in one part's display-list section, with context.

usage: probe_part_colors.py <dir containing swreader> <assembly> <name fragment> [...]
Read-only.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])

from swreader import DISPLAY_LISTS  # noqa: E402
from swreader.container import find_block, read_blocks  # noqa: E402
from swreader.displaylist import _strings, read_sections, read_tables  # noqa: E402

path = Path(sys.argv[2])
data = find_block(read_blocks(path.read_bytes()), DISPLAY_LISTS).inflate()
sections, _ = read_sections(data, read_tables(data))

for fragment in sys.argv[3:]:
    print(f"=== {fragment}")
    index = next((i for i, s in enumerate(sections) if fragment in s.instance and s.tables), None)
    if index is None:
        print("no section with tables")
        continue
    section = sections[index]
    print(section.instance[-90:], "instance appearance", section.appearance, "tables", len(section.tables))
    stop_all = sections[index + 1].name_end if index + 1 < len(sections) else len(data)
    ranges = []
    for i, t in enumerate(section.tables):
        end = section.tables[i + 1].start if i + 1 < len(section.tables) else stop_all
        ranges.append((i, t.end, end))
    for i, start, end in ranges:
        strings = list(_strings(data, start, end))
        names = [s[2][:36] for s in strings if s[2]]
        tags = []
        pos = start
        # Every u16 tag with high byte 0x80 followed by a colour, zero and colour.
        while pos + 14 < end:
            if data[pos + 1] == 0x80:
                tag, color, zero, second = struct.unpack_from("<HIII", data, pos)
                if zero == 0 and not color >> 24 and not second >> 24 and data[pos + 14:pos + 17] == b"\xff\xfe\xff":
                    tags.append((pos - start, hex(tag), (color & 255, color >> 8 & 255, color >> 16 & 255),
                                 hex(second)))
            pos += 1
        if tags or names:
            print(f" t{i} gap={end - start} strings={names[:8]} props={tags}")
