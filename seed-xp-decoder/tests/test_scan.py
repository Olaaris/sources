"""Tests for XP-table discovery across the shapes game data ships in."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from seedxp import magic, scan  # noqa: E402
from seedxp.tables import XpTable, merge  # noqa: E402

# The first levels of the classic cumulative curve, used as realistic fixtures.
FARMING = [0, 83, 174, 276, 388, 512, 650, 801, 969, 1154]
MINING = [0, 100, 250, 450, 700, 1000, 1350, 1750, 2200, 2700]


class TestMagic(unittest.TestCase):
    def test_detects_unity_and_sqlite(self):
        self.assertEqual(magic.sniff(b"UnityFS\x00rest"), "unityfs")
        self.assertEqual(magic.sniff(b"SQLite format 3\x00rest"), "sqlite")

    def test_detects_json_regardless_of_leading_whitespace(self):
        self.assertEqual(magic.sniff(b'  \n{"a": 1}'), "json")
        self.assertEqual(magic.sniff(b"[1, 2, 3]"), "json")

    def test_falls_back_to_text_and_binary(self):
        self.assertEqual(magic.sniff(b"just some words\n"), "text")
        self.assertEqual(magic.sniff(b"\x00\x01\x02\xff\xfe"), "binary")

    def test_uses_suffix_when_content_is_inconclusive(self):
        self.assertEqual(magic.sniff(b"a;b;c", "table.csv"), "csv")


class TestJsonShapes(unittest.TestCase):
    def test_named_numeric_series(self):
        document = {"skillXpTable": {"Farming": FARMING, "Mining": MINING}}
        tables = merge(scan.candidates_from_json(document, "skills.json"))

        self.assertEqual([t.skill for t in tables], ["Farming", "Mining"])
        self.assertEqual(tables[0].values, [float(v) for v in FARMING])
        self.assertEqual(tables[0].levels, list(range(1, 11)))

    def test_rows_with_level_and_xp_fields(self):
        document = {
            "experience": [
                {"skill": "Cooking", "level": level, "xpRequired": xp}
                for level, xp in enumerate(FARMING, start=1)
            ]
        }
        tables = scan.candidates_from_json(document, "xp.json")
        cooking = [t for t in tables if t.skill == "Cooking"]

        self.assertEqual(len(cooking), 1)
        self.assertEqual(cooking[0].values, [float(v) for v in FARMING])

    def test_rows_split_by_skill(self):
        rows = []
        for level, xp in enumerate(FARMING, start=1):
            rows.append({"skillName": "Farming", "lvl": level, "totalExp": xp})
        for level, xp in enumerate(MINING, start=1):
            rows.append({"skillName": "Mining", "lvl": level, "totalExp": xp})

        tables = merge(scan.candidates_from_json({"skillLevels": rows}, "x.json"))
        by_skill = {t.skill: t.values for t in tables}

        self.assertEqual(set(by_skill), {"Farming", "Mining"})
        self.assertEqual(by_skill["Mining"], [float(v) for v in MINING])

    def test_ignores_unrelated_numeric_arrays(self):
        document = {"spawnWeights": [1, 2, 3, 4, 5, 6, 7], "colors": [0, 1, 2, 3, 4, 5]}
        self.assertEqual(scan.candidates_from_json(document, "misc.json"), [])

    def test_short_series_are_not_candidates(self):
        document = {"skillXp": {"Tiny": [0, 10, 20]}}
        self.assertEqual(scan.candidates_from_json(document, "s.json"), [])


class TestEmbeddedAndFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_carves_json_out_of_binary_payload(self):
        blob = json.dumps({"skillXp": {"Farming": FARMING}}).encode()
        noise = b"\x00\x17\xff" * 8
        path = self.root / "asset.bin"
        path.write_bytes(noise + blob + noise)

        tables = scan._scan_embedded_json(path.read_bytes(), str(path))
        self.assertEqual([t.skill for t in tables], ["Farming"])

    def test_balanced_slice_handles_braces_inside_strings(self):
        blob = b'{"name": "a } trap", "skillXp": [0, 1, 2, 3, 4, 5]}'
        self.assertEqual(scan._balanced_slice(blob, 0), blob)

    def test_scan_json_file(self):
        path = self.root / "skills.json"
        path.write_text(json.dumps({"xpTable": {"Farming": FARMING}}))
        tables = scan.scan_file(path)
        self.assertEqual([t.skill for t in tables], ["Farming"])

    def test_scan_csv_file(self):
        path = self.root / "xp.csv"
        lines = ["skill,level,xp"] + [
            f"Farming,{level},{xp}" for level, xp in enumerate(FARMING, start=1)
        ]
        path.write_text("\n".join(lines))

        tables = scan.scan_file(path)
        self.assertEqual([t.skill for t in tables], ["Farming"])
        self.assertEqual(tables[0].values, [float(v) for v in FARMING])

    def test_scan_sqlite_database(self):
        path = self.root / "game.db"
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE skill_xp (skill_name TEXT, level INTEGER, experience REAL)"
        )
        connection.executemany(
            "INSERT INTO skill_xp VALUES (?, ?, ?)",
            [("Mining", level, xp) for level, xp in enumerate(MINING, start=1)],
        )
        connection.commit()
        connection.close()

        tables = scan.scan_file(path)
        self.assertEqual([t.skill for t in tables], ["Mining"])
        self.assertEqual(tables[0].values, [float(v) for v in MINING])

    def test_scan_tree_walks_recursively(self):
        nested = self.root / "SEED_Data" / "config"
        nested.mkdir(parents=True)
        (nested / "skills.json").write_text(json.dumps({"skillXp": {"Farming": FARMING}}))
        (nested / "unrelated.json").write_text(json.dumps({"volume": 0.8}))

        tables = merge(scan.scan_tree(self.root))
        self.assertEqual([t.skill for t in tables], ["Farming"])


class TestMerge(unittest.TestCase):
    def test_keeps_the_longest_duplicate(self):
        short = XpTable("Farming", [(i, i * 10) for i in range(1, 6)], source="a")
        long = XpTable("farming", [(i, i * 10) for i in range(1, 21)], source="b")

        merged = merge([short, long])
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0].points), 20)
        self.assertTrue(any("supersedes" in note for note in merged[0].notes))


class TestXpTable(unittest.TestCase):
    def test_deltas_from_cumulative(self):
        table = XpTable("Farming", [(1, 0), (2, 83), (3, 174)], cumulative=True)
        self.assertEqual(table.deltas(), [(1, 83.0), (2, 91.0)])

    def test_totals_from_incremental(self):
        table = XpTable("Farming", [(1, 83), (2, 91), (3, 102)], cumulative=False)
        self.assertEqual(table.totals(), [(1, 0.0), (2, 83.0), (3, 174.0)])

    def test_points_are_sorted_on_construction(self):
        table = XpTable("Farming", [(3, 174), (1, 0), (2, 83)])
        self.assertEqual(table.levels, [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
