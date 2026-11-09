"""Named blocks of a modern SolidWorks file (.SLDPRT / .SLDASM).

Adapted from sldprt-export (MIT, see THIRD_PARTY.md). The layout comes from
the cadmpeg format documentation (CC BY 4.0):

    signature[6]  14 00 06 00 08 00
    +6   type_id      u32 LE
    +10  crc32        u32 LE   of the decompressed payload
    +14  comp_sz      u32 LE
    +18  uncomp_sz    u32 LE
    +22  pre_sz       u32 LE   preamble holding the nibble-swapped name
    +26  preamble, then the compressed payload
"""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass, field

SIGNATURE = bytes([20, 0, 6, 0, 8, 0])
HEADER = 26
MAX_NAME = 1024
_PRINTABLE = re.compile(rb"[\x20-\x7e]+")


@dataclass
class Block:
    name: str
    data_offset: int
    compressed: int
    expanded: int
    _source: bytes = field(repr=False, default=b"")

    def inflate(self) -> bytes:
        """Expand the block, or return it as-is when it is stored."""
        raw = self._source[self.data_offset : self.data_offset + self.compressed]
        for wbits in (-15, 15):
            try:
                out = zlib.decompressobj(wbits).decompress(raw)
            except zlib.error:
                continue
            if out:
                return out
        return raw


def _unswap(raw: bytes) -> bytes:
    """Undo the nibble swap applied to block names."""
    return bytes(((b << 4) | (b >> 4)) & 0xFF for b in raw)


def read_blocks(data: bytes) -> list[Block]:
    """Every named block in the container, in file order."""
    out: list[Block] = []
    pos = 8

    while True:
        at = data.find(SIGNATURE, pos)
        if at < 0 or at + HEADER > len(data):
            break
        pos = at + 1

        checksum, compressed, expanded, name_len = struct.unpack_from("<4I", data, at + 10)

        # A cache-cell section-index grid reuses the marker and encodes one
        # value L across the size fields as 2L, L//2 and L. Not a data block.
        if checksum == expanded * 2 and compressed == expanded // 2:
            continue
        if not compressed or not 1 <= name_len <= MAX_NAME:
            continue
        if at + HEADER + name_len + compressed > len(data):
            continue

        name = _unswap(data[at + HEADER : at + HEADER + name_len])
        if not _PRINTABLE.fullmatch(name):
            continue

        out.append(
            Block(
                name=name.decode("ascii"),
                data_offset=at + HEADER + name_len,
                compressed=compressed,
                expanded=expanded,
                _source=data,
            )
        )

    return out


def find_block(blocks: list[Block], name: str) -> Block | None:
    for block in blocks:
        if block.name == name:
            return block
    return None
