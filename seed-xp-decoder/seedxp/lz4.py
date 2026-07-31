"""Pure-Python LZ4 block decompressor.

Unity asset bundles compress their block-info table and data blocks with the
raw LZ4 *block* format (not the framed `.lz4` format), and no LZ4 codec ships
with CPython.  This module implements just the decompression side of the block
format so the rest of the toolkit has no third-party dependencies.
"""

from __future__ import annotations


class LZ4Error(ValueError):
    """Raised when an LZ4 block is malformed or truncated."""


def _read_varlen(src: bytes, pos: int, initial: int) -> tuple[int, int]:
    """Continue a length field that saturated its 4-bit nibble."""
    length = initial
    if initial == 0x0F:
        while True:
            if pos >= len(src):
                raise LZ4Error("truncated length field")
            byte = src[pos]
            pos += 1
            length += byte
            if byte != 0xFF:
                break
    return length, pos


def decompress_block(src: bytes, uncompressed_size: int) -> bytes:
    """Decompress a raw LZ4 block of known output size."""
    dst = bytearray()
    pos = 0
    end = len(src)

    while pos < end:
        token = src[pos]
        pos += 1

        literal_len, pos = _read_varlen(src, pos, token >> 4)
        if pos + literal_len > end:
            raise LZ4Error("literal run runs past end of block")
        dst += src[pos : pos + literal_len]
        pos += literal_len

        # A block ends on a literal run; there is no match sequence after it.
        if pos == end:
            break
        if pos + 2 > end:
            raise LZ4Error("truncated match offset")

        offset = src[pos] | (src[pos + 1] << 8)
        pos += 2
        if offset == 0:
            raise LZ4Error("match offset of zero")
        if offset > len(dst):
            raise LZ4Error("match offset points before start of output")

        match_len, pos = _read_varlen(src, pos, token & 0x0F)
        match_len += 4  # minimum match length

        # Matches may overlap the region they copy from, so copy byte by byte.
        start = len(dst) - offset
        for i in range(match_len):
            dst.append(dst[start + i])

    if len(dst) != uncompressed_size:
        raise LZ4Error(
            f"decompressed {len(dst)} bytes, header declared {uncompressed_size}"
        )
    return bytes(dst)
