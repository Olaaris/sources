"""Tests for curve fitting and for the export renderers."""

from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from seedxp import export  # noqa: E402
from seedxp.curves import best_fit, fit_all, polyfit  # noqa: E402
from seedxp.tables import XpTable  # noqa: E402


def runescape_total(level: int) -> int:
    total = 0
    for n in range(1, level):
        total += math.floor(n + 300 * 2 ** (n / 7))
    return math.floor(total / 4)


class TestPolyfit(unittest.TestCase):
    def test_recovers_exact_quadratic(self):
        xs = list(range(1, 11))
        ys = [3 * x * x + 2 * x + 7 for x in xs]
        coefficients = polyfit(xs, ys, 2)

        self.assertIsNotNone(coefficients)
        for got, want in zip(coefficients, [7, 2, 3]):
            self.assertAlmostEqual(got, want, places=6)

    def test_returns_none_when_underdetermined(self):
        self.assertIsNone(polyfit([1, 2], [1, 2], 3))


class TestFitting(unittest.TestCase):
    def test_identifies_a_quadratic_curve_exactly(self):
        table = XpTable(
            "Farming", [(level, 50 * level * level) for level in range(1, 21)]
        )
        fit = best_fit(table)

        self.assertIsNotNone(fit)
        self.assertTrue(fit.is_exact)
        self.assertIn(fit.model, ("quadratic", "power"))
        self.assertAlmostEqual(fit.r_squared, 1.0, places=9)

    def test_identifies_an_exponential_curve(self):
        table = XpTable("Magic", [(level, 100 * 1.5**level) for level in range(1, 21)])
        fits = {fit.model: fit for fit in fit_all(table)}

        self.assertAlmostEqual(fits["exponential"].r_squared, 1.0, places=6)
        self.assertAlmostEqual(fits["exponential"].params[1], 1.5, places=6)

    def test_identifies_the_runescape_curve_exactly(self):
        table = XpTable(
            "Mining", [(level, runescape_total(level)) for level in range(1, 100)]
        )
        fit = best_fit(table)

        self.assertEqual(fit.model, "runescape-style")
        self.assertTrue(fit.is_exact)
        self.assertEqual(fit.exact_matches, 99)

    def test_a_wrong_family_is_ranked_below_an_exact_one(self):
        table = XpTable(
            "Mining", [(level, runescape_total(level)) for level in range(1, 60)]
        )
        fits = fit_all(table)

        self.assertTrue(fits[0].is_exact)
        self.assertFalse(fits[-1].is_exact)

    def test_too_few_points_yields_no_fit(self):
        self.assertEqual(fit_all(XpTable("Tiny", [(1, 0), (2, 5)])), [])


class TestExport(unittest.TestCase):
    def setUp(self):
        self.table = XpTable(
            "Farming",
            [(1, 0), (2, 83), (3, 174), (4, 276), (5, 388)],
            source="SEED_Data/skills.json",
            pointer="/skillXp/Farming",
        )
        self.decoded = [(self.table, best_fit(self.table))]

    def test_json_round_trips(self):
        payload = json.loads(export.render(self.decoded, "json"))

        self.assertEqual(payload["count"], 1)
        entry = payload["tables"][0]
        self.assertEqual(entry["skill"], "Farming")
        self.assertEqual(entry["max_level"], 5)
        self.assertEqual(entry["points"][1], {"level": 2, "xp": 83})
        self.assertIn("best_fit", entry)

    def test_csv_has_one_row_per_level(self):
        rows = export.render(self.decoded, "csv").strip().splitlines()

        self.assertEqual(rows[0], "skill,level,xp_total,xp_to_next,source")
        self.assertEqual(len(rows), 6)
        self.assertTrue(rows[1].startswith("Farming,1,0,83,"))
        self.assertTrue(rows[5].startswith("Farming,5,388,,"))

    def test_markdown_lists_the_skill_and_its_table(self):
        text = export.render(self.decoded, "markdown")

        self.assertIn("## Farming", text)
        self.assertIn("| Niveau | XP cumule | XP vers suivant |", text)
        self.assertIn("| 2 | 83 | 91 |", text)

    def test_markdown_handles_no_results(self):
        self.assertIn("Aucune table", export.render([], "markdown"))

    def test_unknown_format_is_rejected(self):
        with self.assertRaises(ValueError):
            export.render(self.decoded, "xlsx")


class TestCli(unittest.TestCase):
    def test_decode_writes_requested_format(self):
        import tempfile

        from seedxp.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills.json").write_text(
                json.dumps({"skillXp": {"Farming": [0, 83, 174, 276, 388, 512]}})
            )
            output = root / "out.json"

            code = main(
                ["decode", "--path", str(root), "--format", "json", "-o", str(output)]
            )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text())
            self.assertEqual(payload["tables"][0]["skill"], "Farming")

    def test_decode_reports_when_nothing_is_found(self):
        import tempfile

        from seedxp.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "empty.json").write_text("{}")
            self.assertEqual(main(["decode", "--path", tmp]), 1)


if __name__ == "__main__":
    unittest.main()
