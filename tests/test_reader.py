"""Unit tests for swreader on small synthetic display lists.

Run with Blender's Python, which has numpy:
    "<blender>/5.2/python/bin/python.exe" tests/test_reader.py
"""

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "solidworks_import"))

import numpy as np  # noqa: E402
from swreader.displaylist import (  # noqa: E402
    EMPTY_BOUNDS, decode_tables, read_sections, read_tables,
)


def framed(text: str) -> bytes:
    return b"\xff\xfe\xff" + bytes([len(text)]) + text.encode("utf-16-le")


def table(positions, normals, lengths) -> bytes:
    """A six-descriptor strip table."""
    out = struct.pack("<4I", 4, 8, 2, len(lengths)) + struct.pack(f"<{len(lengths)}I", *lengths)
    flat = [v for p in positions for v in p]
    out += struct.pack("<4I", 12, 100, 2, len(positions)) + struct.pack(f"<{len(flat)}f", *flat)
    flat = [v for p in normals for v in p]
    out += struct.pack("<4I", 12, 100, 2, len(normals)) + struct.pack(f"<{len(flat)}f", *flat)
    out += struct.pack("<4I", 4, 8, 2, 0)
    checks = [2 * n - 2 for n in lengths]
    out += struct.pack("<4I", 4, 8, 2, len(lengths)) + struct.pack(f"<{len(lengths)}I", *checks)
    out += struct.pack("<4I", 1, 8, 2, 0)
    return out


QUAD = table(
    [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)],
    [(0, 0, 1)] * 4,
    [4],
)


def header(name, file="C:\\cad\\part.SLDPRT", rotation=True, bounds=None, hiding=0, translate=(1, 2, 3)):
    out = framed(name)
    if rotation:
        out += b"\x01" + struct.pack("<9d", 1, 0, 0, 0, 1, 0, 0, 0, 1)
    else:
        out += b"\x00"
    out += struct.pack("<4d", *translate, 1.0) + b"\x00"
    out += struct.pack("<10d", *(bounds or (0.1,) * 10))
    out += b"\x00\x00" + framed("Default") + b"\x00" * 8 + framed("part") + framed(file)
    out += b"\x00\x00\x00\x00" + struct.pack("<I", hiding) + b"\x00" * 16
    return out


def visual(rgb, transparency=0.0) -> bytes:
    color = rgb[0] | rgb[1] << 8 | rgb[2] << 16
    out = struct.pack("<HIII", 0x8032, color, 0, 0xC0C0C0)
    out += framed("") + framed("")
    return out + struct.pack("<6d", 1, 1, 1, 0.3, transparency, 0) + b"\x00" * 8


class Decoding(unittest.TestCase):
    def test_strip_becomes_two_triangles_facing_the_normals(self):
        tables = read_tables(QUAD)
        self.assertEqual(len(tables), 1)
        part = decode_tables(QUAD, tables)
        self.assertEqual(len(part.triangles), 2)
        v = part.positions
        for a, b, c in part.triangles:
            self.assertGreater(np.cross(v[b] - v[a], v[c] - v[a])[2], 0)

    def test_flipped_normals_flip_the_winding(self):
        data = table([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, -1)] * 3, [3])
        part = decode_tables(data, read_tables(data))
        v = part.positions
        a, b, c = part.triangles[0]
        self.assertLess(np.cross(v[b] - v[a], v[c] - v[a])[2], 0)

    def test_weld_merges_shared_corners_across_tables(self):
        second = table([(1, 0, 0), (1, 1, 0), (2, 0, 0)], [(0, 0, 1)] * 3, [3])
        data = QUAD + b"\x00" * 8 + second
        part = decode_tables(data, read_tables(data))
        self.assertEqual(len(part.positions), 5)
        self.assertEqual(part.normals.shape, (3, 3, 3))

    def test_degenerate_triangles_are_dropped(self):
        data = table([(0, 0, 0), (0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, 1)] * 4, [4])
        self.assertEqual(len(decode_tables(data, read_tables(data)).triangles), 1)

    def test_duplicate_triangles_after_welding_keep_one(self):
        tri = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        data = table(tri, [(0, 0, 1)] * 3, [3]) + b"\x00" * 8 + table(tri, [(0, 0, 1)] * 3, [3])
        part = decode_tables(data, read_tables(data))
        self.assertEqual(len(part.triangles), 1)
        self.assertEqual(part.normals.shape, (1, 3, 3))

    def test_mixed_tables_keep_normals_and_winding(self):
        flipped = table([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, -1)] * 3, [3])
        bare = table([(5, 0, 0), (6, 0, 0), (5, 1, 0)], [], [3])
        data = flipped + b"\x00" * 8 + bare
        part = decode_tables(data, read_tables(data))
        self.assertEqual(part.normals.shape, (2, 3, 3))
        by_owner = dict(zip(part.triangle_table.tolist(), part.triangles.tolist()))
        v = part.positions
        a, b, c = by_owner[0]
        self.assertLess(np.cross(v[b] - v[a], v[c] - v[a])[2], 0)
        self.assertEqual(part.normals[part.triangle_table == 1].tolist(), [[[0, 0, 0]] * 3])

    def test_a_signature_without_a_valid_table_is_skipped(self):
        data = struct.pack("<3I", 4, 8, 2) + b"\x00" * 40 + QUAD
        self.assertEqual(len(read_tables(data)), 1)


class Sections(unittest.TestCase):
    def sections(self, data):
        return read_sections(data, read_tables(data))[0]

    def test_tables_belong_to_the_preceding_instance(self):
        data = header("a-1@top") + QUAD + b"\x00" * 8 + header("b-1@top", "C:\\cad\\b.SLDPRT") + QUAD
        a, b = self.sections(data)
        self.assertEqual((a.instance, a.file, len(a.tables)), ("a-1@top", "part.SLDPRT", 1))
        self.assertEqual((b.instance, b.file, len(b.tables)), ("b-1@top", "b.SLDPRT", 1))

    def test_rotation_flag_moves_the_later_fields(self):
        for rotation in (True, False):
            data = header("a-1@top", rotation=rotation) + QUAD
            section = self.sections(data)[0]
            self.assertEqual(section.world[:3, 3].tolist(), [1, 2, 3])
            self.assertEqual(section.world[:3, :3].tolist(), np.identity(3).tolist())
            self.assertTrue(section.drawn)

    def test_empty_bounds_mean_not_drawn(self):
        data = header("a-1@top", rotation=False, bounds=(0, 0, 0) + EMPTY_BOUNDS) + QUAD
        self.assertFalse(self.sections(data)[0].drawn)

    def test_hiding_list_marks_the_instance_hidden(self):
        self.assertFalse(self.sections(header("a-1@top") + QUAD)[0].hidden)
        self.assertTrue(self.sections(header("a-1@top", hiding=1) + QUAD)[0].hidden)


class Appearances(unittest.TestCase):
    def test_a_face_colour_stays_on_its_face_and_the_body_default_covers_the_rest(self):
        red, grey = (255, 0, 0), (192, 192, 192)
        data = (
            QUAD + b"\x00" * 8  # no appearance of its own
            + QUAD + visual(red) + b"\x00" * 8  # a thread face
            + QUAD + visual(grey)  # the last table's property is the body default
        )
        tables = read_tables(data)
        read_sections(data, tables)
        part = decode_tables(data, tables)
        self.assertEqual([a[:3] for a in part.appearances], [grey, red, grey])

    def test_transparency_becomes_alpha(self):
        data = QUAD + visual((10, 20, 30), 0.75)
        tables = read_tables(data)
        read_sections(data, tables)
        self.assertEqual(tables[0].appearance, (10, 20, 30, 0.25))


if __name__ == "__main__":
    unittest.main()
