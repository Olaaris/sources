"""Tests for rebuilding a full XP table from banded SkillTier values."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from seedxp import progression  # noqa: E402
from seedxp.cli import main  # noqa: E402
from seedxp.curves import best_fit  # noqa: E402


class TestParsing(unittest.TestCase):
    def test_parses_a_tier_specification(self):
        tier = progression.parse_tier("Novice:1-10:100")
        self.assertEqual(
            (tier.name, tier.start_level, tier.end_level, tier.xp_per_level),
            ("Novice", 1, 10, 100),
        )

    def test_tolerates_surrounding_whitespace(self):
        self.assertEqual(progression.parse_tier("  Adepte : 11 - 20 : 250 ").name, "Adepte")

    def test_rejects_a_malformed_specification(self):
        for bad in ("Novice:1-10", "Novice", "Novice:a-b:100", ""):
            with self.assertRaises(progression.TierError):
                progression.parse_tier(bad)

    def test_rejects_an_inverted_range(self):
        with self.assertRaises(progression.TierError):
            progression.parse_tier("Novice:10-1:100")


class TestBuildTable(unittest.TestCase):
    def setUp(self):
        self.tiers = [
            progression.parse_tier("Novice:1-10:100"),
            progression.parse_tier("Adepte:11-20:250"),
        ]

    def test_accumulates_within_a_tier(self):
        table = progression.build_table(self.tiers, skill="Farming")
        totals = dict(table.totals())

        self.assertEqual(totals[1], 0)
        self.assertEqual(totals[2], 100)
        self.assertEqual(totals[10], 900)

    def test_switches_rate_at_the_tier_boundary(self):
        totals = dict(progression.build_table(self.tiers).totals())

        self.assertEqual(totals[11], 1000)  # last Novice level still costs 100
        self.assertEqual(totals[12], 1250)  # then the Adepte rate applies
        self.assertEqual(totals[20], 3250)

    def test_covers_every_level_of_every_tier(self):
        table = progression.build_table(self.tiers)
        self.assertEqual(table.levels, list(range(1, 21)))

    def test_max_level_truncates_the_table(self):
        table = progression.build_table(self.tiers, max_level=5)
        self.assertEqual(table.max_level, 5)

    def test_records_the_tiers_it_used(self):
        notes = " ".join(progression.build_table(self.tiers).notes)
        self.assertIn("Novice 1-10 @ 100/niv", notes)

    def test_a_single_flat_tier_fits_a_line_exactly(self):
        table = progression.build_table([progression.parse_tier("Flat:1-30:50")])
        fit = best_fit(table)

        self.assertTrue(fit.is_exact)
        self.assertEqual(fit.model, "linear")

    def test_no_tiers_is_an_error(self):
        with self.assertRaises(progression.TierError):
            progression.build_table([])


class TestValidation(unittest.TestCase):
    def test_reports_a_gap(self):
        tiers = [progression.parse_tier("A:1-10:100"), progression.parse_tier("B:15-20:200")]
        problems = progression.validate(tiers)

        self.assertEqual(len(problems), 1)
        self.assertIn("trou", problems[0])

    def test_reports_an_overlap(self):
        tiers = [progression.parse_tier("A:1-10:100"), progression.parse_tier("B:8-20:200")]
        problems = progression.validate(tiers)

        self.assertEqual(len(problems), 1)
        self.assertIn("chevauchent", problems[0])

    def test_contiguous_tiers_are_clean(self):
        tiers = [progression.parse_tier("A:1-10:100"), progression.parse_tier("B:11-20:200")]
        self.assertEqual(progression.validate(tiers), [])

    def test_problems_are_carried_into_the_table_notes(self):
        tiers = [progression.parse_tier("A:1-10:100"), progression.parse_tier("B:15-20:200")]
        notes = " ".join(progression.build_table(tiers).notes)
        self.assertIn("trou", notes)


class TestLoadFromJson(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _write(self, document) -> Path:
        path = self.root / "config.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_reads_the_games_own_field_names(self):
        path = self._write(
            {
                "MaxLevel": 20,
                "SkillTiers": [
                    {"Name": "Novice", "StartLevel": 1, "EndLevel": 10, "XPPerLevel": 100},
                    {"Name": "Adepte", "StartLevel": 11, "EndLevel": 20, "XPPerLevel": 250},
                ],
            }
        )
        tiers = progression.load_tiers(path)

        self.assertEqual([t.name for t in tiers], ["Novice", "Adepte"])
        self.assertEqual(tiers[1].xp_per_level, 250)

    def test_accepts_a_bare_list(self):
        path = self._write([{"name": "A", "start": 1, "end": 5, "xp": 10}])
        self.assertEqual(progression.load_tiers(path)[0].end_level, 5)

    def test_missing_field_is_reported(self):
        path = self._write([{"Name": "A", "StartLevel": 1, "EndLevel": 5}])
        with self.assertRaises(progression.TierError):
            progression.load_tiers(path)


class TestCli(unittest.TestCase):
    def test_tiers_command_writes_a_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "farming.json"
            code = main(
                ["tiers", "-t", "Novice:1-10:100", "-t", "Adepte:11-20:250",
                 "-s", "Farming", "-f", "json", "-o", str(output)]
            )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text())
            entry = payload["tables"][0]
            self.assertEqual(entry["skill"], "Farming")
            self.assertEqual(entry["max_level"], 20)
            self.assertEqual(entry["points"][11], {"level": 12, "xp": 1250})

    def test_malformed_tier_exits_non_zero(self):
        self.assertEqual(main(["tiers", "-t", "nonsense"]), 1)


if __name__ == "__main__":
    unittest.main()
