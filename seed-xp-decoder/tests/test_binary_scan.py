"""Tests for scanning opaque binaries: Unity .assets files and .NET assemblies."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from seedxp import scan, strings  # noqa: E402
from seedxp.tables import merge  # noqa: E402

CURVE = [0, 83, 174, 276, 388, 512, 650, 801]


class TestBinaryScanning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.document = json.dumps({"skillXpTable": {"Farming": CURVE}})

    def test_finds_json_in_a_utf8_binary(self):
        # Shaped like a Unity serialized file: JSON surrounded by binary noise.
        path = self.root / "resources.assets"
        path.write_bytes(b"\x00\x1a\xff\x7f" * 6 + self.document.encode() + b"\x00" * 12)

        tables = scan.scan_file(path)
        self.assertEqual([t.skill for t in tables], ["Farming"])
        self.assertEqual(tables[0].values, [float(v) for v in CURVE])

    def test_finds_json_stored_as_utf16(self):
        # Shaped like a .NET assembly: string literals held in UTF-16.
        path = self.root / "StaticData.dll"
        path.write_bytes(b"MZ\x90\x00" + self.document.encode("utf-16-le") + b"\x00" * 8)

        tables = scan.scan_file(path)
        self.assertEqual([t.skill for t in tables], ["Farming"])
        self.assertTrue(
            any("UTF-16" in note for note in tables[0].notes),
            "the UTF-16 provenance should be recorded on the table",
        )

    def test_the_same_table_in_both_encodings_is_merged(self):
        path = self.root / "both.bin"
        path.write_bytes(
            self.document.encode() + b"\x00\x00" + self.document.encode("utf-16-le")
        )

        self.assertEqual(len(merge(scan.scan_file(path))), 1)

    def test_binary_without_tables_yields_nothing(self):
        path = self.root / "UnityPlayer.dll"
        path.write_bytes(bytes(range(256)) * 40)
        self.assertEqual(scan.scan_file(path), [])


class TestStrings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_extracts_ascii_and_utf16_runs(self):
        data = b"\x00\x01" + b"skillXpTable" + b"\x00" + "levelCurve".encode("utf-16-le")
        found = list(strings.iter_strings(data, min_length=6))
        encodings = {f.encoding for f in found}
        texts = {f.text for f in found}

        self.assertIn("ascii", encodings)
        self.assertIn("utf-16", encodings)
        self.assertIn("levelCurve", texts)

    def test_keeps_only_relevant_strings_by_default(self):
        path = self.root / "StaticData.dll"
        path.write_bytes(b"AgentSkillXpCurve\x00SomeUnrelatedIdentifier\x00")

        texts = [f.text for f in strings.search(path)]
        self.assertIn("AgentSkillXpCurve", texts)
        self.assertNotIn("SomeUnrelatedIdentifier", texts)

    def test_explicit_pattern_overrides_the_default_hints(self):
        path = self.root / "blob.bin"
        path.write_bytes(b"ProgressionCurveTable\x00Irrelevant\x00")

        texts = [f.text for f in strings.search(path, pattern="progression")]
        self.assertEqual(texts, ["ProgressionCurveTable"])

    def test_search_tree_reports_only_files_that_hit(self):
        (self.root / "hit.bin").write_bytes(b"skillExperience\x00")
        (self.root / "miss.bin").write_bytes(b"nothing to see here\x00")

        hits = strings.search_tree(self.root)
        self.assertEqual([Path(p).name for p in hits], ["hit.bin"])


if __name__ == "__main__":
    unittest.main()
