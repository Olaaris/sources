"""Tests for the LZ4 block decoder and the UnityFS container reader."""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from seedxp import unityfs  # noqa: E402
from seedxp.lz4 import LZ4Error, decompress_block  # noqa: E402


def lz4_literals_only(data: bytes) -> bytes:
    """Encode `data` as a valid LZ4 block using literals only."""
    out = bytearray()
    length = len(data)
    if length < 15:
        out.append(length << 4)
    else:
        out.append(0xF0)
        remaining = length - 15
        while remaining >= 255:
            out.append(255)
            remaining -= 255
        out.append(remaining)
    out += data
    return bytes(out)


class TestLz4(unittest.TestCase):
    def test_short_literal_run(self):
        block = lz4_literals_only(b"hello")
        self.assertEqual(decompress_block(block, 5), b"hello")

    def test_long_literal_run_uses_continuation_bytes(self):
        payload = bytes(range(256)) * 3  # 768 bytes, forces multiple 0xFF bytes
        block = lz4_literals_only(payload)
        self.assertEqual(decompress_block(block, len(payload)), payload)

    def test_overlapping_match(self):
        # 4 literals "abcd", then a match of 8 bytes at offset 4 (overlapping).
        block = bytes([(4 << 4) | 4]) + b"abcd" + struct.pack("<H", 4)
        self.assertEqual(decompress_block(block, 12), b"abcdabcdabcd")

    def test_empty_block(self):
        self.assertEqual(decompress_block(lz4_literals_only(b""), 0), b"")

    def test_size_mismatch_is_rejected(self):
        with self.assertRaises(LZ4Error):
            decompress_block(lz4_literals_only(b"hello"), 99)

    def test_offset_past_start_is_rejected(self):
        block = bytes([(1 << 4) | 0]) + b"a" + struct.pack("<H", 50)
        with self.assertRaises(LZ4Error):
            decompress_block(block, 5)


def build_bundle(
    nodes: list[tuple[str, bytes]], format_version: int = 6, compress: bool = False
) -> bytes:
    """Assemble a synthetic UnityFS bundle for testing."""
    payload = b""
    directory = []
    for name, content in nodes:
        directory.append((name, len(payload), len(content)))
        payload += content

    blocks_info = bytearray(b"\x00" * 16)
    blocks_info += struct.pack(">i", 1)
    block_payload = lz4_literals_only(payload) if compress else payload
    block_flags = 2 if compress else 0
    blocks_info += struct.pack(">IIH", len(payload), len(block_payload), block_flags)
    blocks_info += struct.pack(">i", len(directory))
    for name, offset, size in directory:
        blocks_info += struct.pack(">qqI", offset, size, 4)
        blocks_info += name.encode("utf-8") + b"\x00"

    header = bytearray(b"UnityFS\x00")
    header += struct.pack(">I", format_version)
    header += b"2022.3.21f1\x00"
    header += b"2022.3.21f1\x00"
    header += struct.pack(
        ">qIII", 0, len(blocks_info), len(blocks_info), 0  # blocks info uncompressed
    )

    if format_version >= 7:
        padding = (-len(header)) % 16
        header += b"\x00" * padding

    return bytes(header) + bytes(blocks_info) + block_payload


class TestUnityFS(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _write(self, data: bytes, name: str = "test.bundle") -> Path:
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_reads_header_and_directory(self):
        path = self._write(build_bundle([("skills.json", b'{"a":1}'), ("b.txt", b"xy")]))
        info, payload = unityfs.read_bundle(path)

        self.assertEqual(info.signature, "UnityFS")
        self.assertEqual(info.unity_version, "2022.3.21f1")
        self.assertEqual([node.path for node in info.nodes], ["skills.json", "b.txt"])
        self.assertEqual(payload, b'{"a":1}xy')

    def test_node_offsets_slice_the_payload(self):
        path = self._write(build_bundle([("one", b"AAAA"), ("two", b"BBB")]))
        info, payload = unityfs.read_bundle(path)
        sliced = {n.path: payload[n.offset : n.offset + n.size] for n in info.nodes}
        self.assertEqual(sliced, {"one": b"AAAA", "two": b"BBB"})

    def test_lz4_compressed_blocks(self):
        content = b'{"Farming":[0,83,174,276,388]}'
        path = self._write(build_bundle([("skills.json", content)], compress=True))
        _info, payload = unityfs.read_bundle(path)
        self.assertEqual(payload, content)

    def test_format_version_7_alignment(self):
        path = self._write(build_bundle([("x", b"12345")], format_version=7))
        info, payload = unityfs.read_bundle(path)
        self.assertEqual(info.format_version, 7)
        self.assertEqual(payload, b"12345")

    def test_rejects_non_bundle(self):
        path = self._write(b"NotAUnityBundle\x00rest")
        with self.assertRaises(unityfs.UnityFSError):
            unityfs.read_bundle(path)

    def test_extract_writes_every_node(self):
        path = self._write(build_bundle([("data/skills.json", b"{}"), ("readme", b"hi")]))
        dest = self.root / "out"
        written = unityfs.extract(path, dest)

        self.assertEqual(len(written), 2)
        self.assertEqual((dest / "data" / "skills.json").read_bytes(), b"{}")
        self.assertEqual((dest / "readme").read_bytes(), b"hi")

    def test_extract_refuses_path_traversal(self):
        path = self._write(build_bundle([("../escaped", b"nope"), ("ok", b"yes")]))
        dest = self.root / "out"
        written = unityfs.extract(path, dest)

        self.assertEqual([p.name for p in written], ["ok"])
        self.assertFalse((self.root / "escaped").exists())


if __name__ == "__main__":
    unittest.main()
