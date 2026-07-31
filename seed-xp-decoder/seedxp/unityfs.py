"""Reader for UnityFS asset bundles.

SEED ships as a Unity title, so most non-code game data lives inside `.bundle`
/ `.unity3d` containers rather than as loose files.  This module parses the
bundle header and directory so the scanner can reach the `TextAsset` and
`MonoBehaviour` payloads that hold configuration tables.

Only the container layer is implemented here: it yields the raw bytes of each
node inside a bundle.  Serialized-file parsing of typed Unity objects is out of
scope — in practice XP tables ship as embedded JSON/CSV `TextAsset`s, which the
scanner finds directly in the extracted payload.
"""

from __future__ import annotations

import io
import lzma
import struct
from dataclasses import dataclass
from pathlib import Path

from .lz4 import decompress_block

COMPRESSION_NONE = 0
COMPRESSION_LZMA = 1
COMPRESSION_LZ4 = 2
COMPRESSION_LZ4HC = 3

FLAG_COMPRESSION_MASK = 0x3F
FLAG_BLOCKS_INFO_AT_END = 0x80


class UnityFSError(ValueError):
    """Raised when a file is not a readable UnityFS bundle."""


@dataclass(frozen=True)
class BundleNode:
    """One file entry inside a bundle's directory."""

    path: str
    offset: int
    size: int
    flags: int


@dataclass(frozen=True)
class BundleInfo:
    """Header metadata plus the directory of a bundle."""

    signature: str
    format_version: int
    unity_version: str
    unity_revision: str
    nodes: tuple[BundleNode, ...]


def _read_cstring(stream: io.BufferedReader) -> str:
    out = bytearray()
    while True:
        byte = stream.read(1)
        if not byte:
            raise UnityFSError("unterminated string in bundle header")
        if byte == b"\x00":
            break
        out += byte
    return out.decode("utf-8", errors="replace")


def _read(stream: io.BufferedReader, fmt: str):
    size = struct.calcsize(fmt)
    data = stream.read(size)
    if len(data) != size:
        raise UnityFSError("truncated bundle header")
    return struct.unpack(fmt, data)


def _decompress(data: bytes, uncompressed_size: int, flags: int) -> bytes:
    method = flags & FLAG_COMPRESSION_MASK
    if method == COMPRESSION_NONE:
        return data
    if method in (COMPRESSION_LZ4, COMPRESSION_LZ4HC):
        return decompress_block(data, uncompressed_size)
    if method == COMPRESSION_LZMA:
        # Unity stores the 5 LZMA properties bytes but omits the 8-byte size
        # field that the standalone (`FORMAT_ALONE`) container expects.
        if len(data) < 5:
            raise UnityFSError("truncated LZMA payload")
        rebuilt = data[:5] + struct.pack("<Q", uncompressed_size) + data[5:]
        return lzma.decompress(rebuilt, format=lzma.FORMAT_ALONE)
    raise UnityFSError(f"unsupported compression method {method}")


def read_bundle(path: Path) -> tuple[BundleInfo, bytes]:
    """Parse a bundle, returning its directory and its decompressed payload.

    Node offsets index into the returned payload blob.
    """
    with path.open("rb") as stream:
        signature = _read_cstring(stream)
        if signature != "UnityFS":
            raise UnityFSError(f"unsupported bundle signature {signature!r}")

        (format_version,) = _read(stream, ">I")
        unity_version = _read_cstring(stream)
        unity_revision = _read_cstring(stream)
        _total_size, compressed_info_size, uncompressed_info_size, flags = _read(
            stream, ">qIII"
        )

        if format_version >= 7:
            _align(stream, 16)

        if flags & FLAG_BLOCKS_INFO_AT_END:
            resume_at = stream.tell()
            stream.seek(-compressed_info_size, io.SEEK_END)
            raw_info = stream.read(compressed_info_size)
            stream.seek(resume_at)
        else:
            raw_info = stream.read(compressed_info_size)

        if len(raw_info) != compressed_info_size:
            raise UnityFSError("truncated block-info table")

        info = _decompress(raw_info, uncompressed_info_size, flags)
        blocks, nodes = _parse_blocks_info(info)
        payload = _read_payload(stream, blocks)

    return (
        BundleInfo(
            signature=signature,
            format_version=format_version,
            unity_version=unity_version,
            unity_revision=unity_revision,
            nodes=nodes,
        ),
        payload,
    )


def _align(stream: io.BufferedReader, boundary: int) -> None:
    remainder = stream.tell() % boundary
    if remainder:
        stream.seek(boundary - remainder, io.SEEK_CUR)


def _parse_blocks_info(info: bytes) -> tuple[list[tuple[int, int, int]], tuple[BundleNode, ...]]:
    stream = io.BytesIO(info)
    stream.read(16)  # uncompressed data hash, unused

    (block_count,) = struct.unpack(">i", stream.read(4))
    blocks = []
    for _ in range(block_count):
        uncompressed_size, compressed_size, block_flags = struct.unpack(
            ">IIH", stream.read(10)
        )
        blocks.append((uncompressed_size, compressed_size, block_flags))

    (node_count,) = struct.unpack(">i", stream.read(4))
    nodes = []
    for _ in range(node_count):
        offset, size, node_flags = struct.unpack(">qqI", stream.read(20))
        name = bytearray()
        while True:
            byte = stream.read(1)
            if not byte or byte == b"\x00":
                break
            name += byte
        nodes.append(
            BundleNode(
                path=name.decode("utf-8", errors="replace"),
                offset=offset,
                size=size,
                flags=node_flags,
            )
        )

    return blocks, tuple(nodes)


def _read_payload(stream: io.BufferedReader, blocks: list[tuple[int, int, int]]) -> bytes:
    out = bytearray()
    for uncompressed_size, compressed_size, block_flags in blocks:
        chunk = stream.read(compressed_size)
        if len(chunk) != compressed_size:
            raise UnityFSError("truncated data block")
        out += _decompress(chunk, uncompressed_size, block_flags)
    return bytes(out)


def extract(path: Path, dest: Path) -> list[Path]:
    """Extract every node of a bundle into `dest`, returning the written paths."""
    info, payload = read_bundle(path)
    written: list[Path] = []
    for node in info.nodes:
        # Node paths come from the bundle; keep them inside `dest`.
        safe_name = node.path.replace("\\", "/").lstrip("/")
        target = (dest / safe_name).resolve()
        if not str(target).startswith(str(dest.resolve())):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload[node.offset : node.offset + node.size])
        written.append(target)
    return written
