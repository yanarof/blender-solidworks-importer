"""Decode `Contents/DisplayLists`: strip tables, per-part sections and appearances.

A strip table is six descriptors (`element size | kind | 2 | count`, then data):
strip lengths, f32 positions in metres, f32 normals (or none), two lists of
per-strip extras and a `2n-2` check list. The layout is from the cadmpeg format
documentation and sldprt-export (see THIRD_PARTY.md).

An assembly's block is a scene. Each component instance is announced by its full
instance path, directly followed by its world placement and bounds, then its file
path and that part's tables in part-local coordinates. A repeated part announces
itself again with no tables. This scene layout was worked out from real assemblies
and is not in those sources.
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass, field

import numpy as np

DESCRIPTORS = ((4, 8), (12, 100), (12, 100), (4, 8), (4, 8), (1, 8))
TABLE_SIGNATURE = struct.pack("<3I", 4, 8, 2)
MAX_STRIPS = 250_000
MAX_STRIP_VERTS = 1_000_000
MAX_DESC_COUNT = 20_000_000

STRING_MARK = b"\xff\xfe\xff"
INSTANCE_NAME = re.compile(r".+-\d+@.+")
CAD_FILE = re.compile(r"\.(sldprt|sldasm)$", re.IGNORECASE)

# How far past an instance path its file path may sit, and how many strings.
HEADER_REACH = 2000
HEADER_STRINGS = 16

# After an instance path: a flag byte (1 when a rotation follows, 0 for identity),
# then 9 f64 rotation if present, 3 f64 translation, f64 scale, a flag byte and
# 10 f64 of bounds. Bounds of (0,0,0), (-1,-1,-1), (1,1,1), -2 mean SolidWorks
# draws nothing for this instance, as with skipped pattern members.
ROTATION = struct.Struct("<9d")
PLACE = struct.Struct("<4d")
BOUNDS = struct.Struct("<10d")
MAX_HIDING_STATES = 4096
EMPTY_BOUNDS = (-1.0, -1.0, -1.0, 1.0, 1.0, 1.0, -2.0)

# Offsets from a visual property's first framed string.
OPTICS = struct.Struct("<6d")
TRANSPARENCY = 4

Appearance = tuple  # (r, g, b, alpha) with r, g, b in 0-255 and alpha in 0-1


@dataclass
class Table:
    start: int
    end: int
    positions: tuple[int, int]
    normals: tuple[int, int]
    lengths_at: int
    strips: int
    appearance: Appearance | None = None  # set on this face
    body_appearance: Appearance | None = None  # default for the body this table ends


@dataclass
class Section:
    """One component instance announced in the display list."""

    instance: str
    file: str
    config: str
    name_end: int = 0  # offset just past the instance path
    world: np.ndarray | None = None  # 4x4, column vectors, metres
    drawn: bool = True
    hidden: bool = False  # hidden by a display state in a parent assembly
    appearance: Appearance | None = None
    tables: list[Table] = field(default_factory=list)


@dataclass
class DecodedPart:
    positions: np.ndarray  # (V, 3) float32, metres
    normals: np.ndarray | None  # (T, 3, 3) float32, per triangle corner
    triangles: np.ndarray  # (T, 3) int32
    triangle_table: np.ndarray  # (T,) int32, index into `appearances`
    appearances: list[Appearance | None]


def _read_table(data: bytes, at: int) -> Table | None:
    """Parse a table at `at`, or None if any part of the layout does not hold."""
    pos = at
    descriptors = []
    for size, kind in DESCRIPTORS:
        if pos + 16 > len(data):
            return None
        d_size, d_kind, flags, count = struct.unpack_from("<4I", data, pos)
        if d_size != size or d_kind != kind or flags != 2:
            return None
        if count > MAX_DESC_COUNT or pos + 16 + count * size > len(data):
            return None
        descriptors.append((pos + 16, count))
        pos += 16 + size * count

    lengths_at, strips = descriptors[0]
    if not strips or strips > MAX_STRIPS or descriptors[4][1] != strips:
        return None

    lengths = np.frombuffer(data, "<u4", strips, lengths_at)
    if lengths.min() < 3 or lengths.max() > MAX_STRIP_VERTS:
        return None
    total = int(lengths.sum())
    if descriptors[1][1] != total or descriptors[2][1] not in (0, total):
        return None
    if not np.array_equal(np.frombuffer(data, "<u4", strips, descriptors[4][0]), 2 * lengths - 2):
        return None

    return Table(at, pos, descriptors[1], descriptors[2], lengths_at, strips)


def read_tables(data: bytes) -> list[Table]:
    """Every strip table in a decompressed block."""
    tables = []
    pos = 0
    while True:
        at = data.find(TABLE_SIGNATURE, pos)
        if at < 0:
            return tables
        table = _read_table(data, at)
        if table is None:
            pos = at + 1
            continue
        tables.append(table)
        pos = table.end


def _strings(data: bytes, start: int, end: int):
    """Framed UTF-16 strings (`ff fe ff`, count, payload) in a byte range."""
    pos = start
    while True:
        at = data.find(STRING_MARK, pos, end)
        if at < 0 or at + 4 > end:
            return
        pos = at + 3
        count = data[at + 3]
        text_at = at + 4
        if count == 0xFF:
            if text_at + 2 > end:
                continue
            count = struct.unpack_from("<H", data, text_at)[0]
            text_at += 2
        stop = text_at + 2 * count
        if stop > end:
            continue
        try:
            text = data[text_at:stop].decode("utf-16-le")
        except UnicodeDecodeError:
            continue
        if text.isprintable():
            yield at, stop, text
            pos = stop


def _appearance(data: bytes, strings: list, index: int, floor: int, end: int):
    """The visual property whose display name is `strings[index]`, if it is one.

    The payload is a class-reference tag (u16, high byte 0x80), a `00BBGGRR`
    colour, a zero u32 and a second colour, two framed names, then six f64
    optics. Bytes after an f64 -1.0 can frame the same way, hence the tag check.
    """
    at = strings[index][0]
    if at - 14 < floor:
        return None
    tag, color, zero, second = struct.unpack_from("<HIII", data, at - 14)
    if tag >> 8 != 0x80 or zero != 0 or color >> 24 or second >> 24:
        return None
    if index + 1 >= len(strings) or strings[index + 1][0] != strings[index][1]:
        return None
    optics_at = strings[index + 1][1]
    if optics_at + OPTICS.size > end:
        return None
    transparency = OPTICS.unpack_from(data, optics_at)[TRANSPARENCY]
    alpha = 1.0 - min(max(transparency, 0.0), 1.0) if math.isfinite(transparency) else 1.0
    return color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF, round(alpha, 3)


def _section(data: bytes, strings: list, index: int, end: int) -> tuple[Section | None, int]:
    """The section announced by `strings[index]`, and the index of its file path."""
    stop = strings[index][1]
    for j in range(index + 1, min(index + 1 + HEADER_STRINGS, len(strings))):
        if strings[j][0] - stop > HEADER_REACH or INSTANCE_NAME.fullmatch(strings[j][2]):
            break
        if not CAD_FILE.search(strings[j][2]):
            continue
        config = strings[j - 2][2] if j - index >= 3 else ""
        section = Section(strings[index][2], re.split(r"[\\/]", strings[j][2])[-1], config, stop)
        # Past the file path: two u16 zeros, then a count of display states that
        # hide this instance, each followed by its id.
        hidden_at = strings[j][1] + 4
        if hidden_at + 4 <= end:
            section.hidden = 0 < struct.unpack_from("<I", data, hidden_at)[0] < MAX_HIDING_STATES
        has_rotation = data[stop] == 1
        at = stop + 1
        bounds_at = at + (ROTATION.size if has_rotation else 0) + PLACE.size + 1
        if bounds_at + BOUNDS.size <= end:
            world = np.identity(4)
            if has_rotation:
                world[:3, :3] = np.array(ROTATION.unpack_from(data, at)).reshape(3, 3).T
                at += ROTATION.size
            world[:3, 3] = PLACE.unpack_from(data, at)[:3]
            section.world = world
            section.drawn = BOUNDS.unpack_from(data, bounds_at)[3:] != EMPTY_BOUNDS
        return section, j
    return None, index


def read_sections(data: bytes, tables: list[Table]) -> tuple[list[Section], list[Table]]:
    """Split the tables by component instance and attach appearances.

    Returns the sections, and the tables that sit before any section (the whole
    model, in a part file).
    """
    sections: list[Section] = []
    loose: list[Table] = []

    gaps = [(0, tables[0].start if tables else len(data), None)]
    for i, table in enumerate(tables):
        next_start = tables[i + 1].start if i + 1 < len(tables) else len(data)
        gaps.append((table.end, next_start, table))

    for start, end, table in gaps:
        if table is not None:
            (sections[-1].tables if sections else loose).append(table)

        strings = list(_strings(data, start, end))
        current = None  # the section whose header is being read in this gap
        header_end = -1
        for i, (_at, _stop, text) in enumerate(strings):
            if INSTANCE_NAME.fullmatch(text):
                section, file_index = _section(data, strings, i, end)
                if section is not None:
                    sections.append(section)
                    current, header_end = section, file_index
                    continue
            found = _appearance(data, strings, i, start, end)
            if found is None:
                continue
            if current is None:
                if table is not None:
                    if table.appearance is None:
                        table.appearance = found
                    else:
                        table.body_appearance = found
            elif i < header_end and current.appearance is None:
                current.appearance = found

    return sections, loose


def _fill_appearances(tables: list[Table]) -> list[Appearance | None]:
    """Resolve each table's appearance: its own, else its body's default.

    A face-local appearance (a red thread, say) stays on its own face. A body
    default follows the tables it covers. When the last table has only one
    property, that property doubles as the default.
    """
    last = tables[-1]
    default = last.body_appearance or last.appearance
    filled: list[Appearance | None] = []
    for table in reversed(tables):
        default = table.body_appearance or default
        filled.append(table.appearance or default)
    filled.reverse()
    return filled


def decode_tables(data: bytes, tables: list[Table], weld: float = 1e-6) -> DecodedPart:
    """Turn strip tables into one indexed triangle mesh.

    Stored normals decide each triangle's winding, since strips alternate and a
    table does not promise a starting direction. `weld` merges coincident
    vertices across faces (metres); stored normals stay per triangle corner.
    """
    positions, normals, triangles, owners = [], [], [], []
    offset = 0
    any_normals = any(t.normals[1] for t in tables)

    for index, table in enumerate(tables):
        pos = np.frombuffer(data, "<f4", table.positions[1] * 3, table.positions[0]).reshape(-1, 3)
        lengths = np.frombuffer(data, "<u4", table.strips, table.lengths_at).astype(np.int64)

        # Every vertex starts a triangle except the last two of each strip.
        strip_starts = np.concatenate(([0], np.cumsum(lengths)))[:-1]
        local = np.arange(len(pos)) - np.repeat(strip_starts, lengths)
        keep = local < np.repeat(lengths - 2, lengths)
        a = np.flatnonzero(keep)
        odd = local[keep] % 2 == 1
        tris = np.stack((a, a + 1 + odd, a + 2 - odd), axis=1)

        # A zero normal asks Blender for its own at that corner.
        nor = np.zeros_like(pos)
        if table.normals[1]:
            nor = np.frombuffer(data, "<f4", table.normals[1] * 3, table.normals[0]).reshape(-1, 3)
            p0, p1, p2 = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
            face = np.cross(p1 - p0, p2 - p0)
            facing = (face * (nor[tris[:, 0]] + nor[tris[:, 1]] + nor[tris[:, 2]])).sum(axis=1)
            flip = facing < 0
            tris[flip, 1], tris[flip, 2] = tris[flip, 2].copy(), tris[flip, 1].copy()

        normals.append(nor)
        positions.append(pos)
        triangles.append(tris + offset)
        owners.append(np.full(len(tris), index, np.int32))
        offset += len(pos)

    verts = np.concatenate(positions)
    tris = np.concatenate(triangles)
    owner = np.concatenate(owners)
    corner_normals = np.concatenate(normals)[tris] if any_normals else None

    if weld > 0:
        _, first, remap = np.unique(
            np.round(verts.astype(np.float64) / weld).astype(np.int64),
            axis=0, return_index=True, return_inverse=True,
        )
        remap = remap.reshape(-1)
        verts = verts[first]
        tris = remap[tris]

    area = np.cross(verts[tris[:, 1]] - verts[tris[:, 0]], verts[tris[:, 2]] - verts[tris[:, 0]])
    good = (
        (tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2])
        & ((area * area).sum(axis=1) > 0)
    )
    # Welding can leave two triangles on the same corners (a shared coplanar face).
    # Keep one; Blender's mesh validation would otherwise drop it and the normals.
    kept = np.flatnonzero(good)
    _, unique = np.unique(np.sort(tris[kept], axis=1), axis=0, return_index=True)
    good = np.zeros(len(tris), bool)
    good[kept[unique]] = True
    return DecodedPart(
        positions=verts,
        normals=corner_normals[good] if corner_normals is not None else None,
        triangles=tris[good].astype(np.int32),
        triangle_table=owner[good],
        appearances=_fill_appearances(tables),
    )
