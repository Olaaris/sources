"""End-to-end test: a Unity bundle in, decoded XP tables out.

Every stage is covered in isolation elsewhere; this exercises them wired
together, on an input whose expected output is known in advance.
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from seedxp import scan  # noqa: E402
from seedxp.cli import main  # noqa: E402
from seedxp.curves import best_fit  # noqa: E402
from seedxp.tables import merge  # noqa: E402
from test_lz4_unityfs import build_bundle  # noqa: E402


def runescape_total(level: int) -> int:
    return math.floor(
        sum(math.floor(n + 300 * 2 ** (n / 7)) for n in range(1, level)) / 4
    )


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

        curve = [runescape_total(level) for level in range(1, 60)]
        text_asset = json.dumps(
            {"skillXpTable": {"Farming": curve, "Mining": curve}}
        ).encode()

        # A Unity TextAsset sits inside a serialized file, surrounded by binary
        # metadata, so wrap the JSON in noise the way a real bundle would.
        node_payload = b"\x00\x0a\xff\x01" * 4 + text_asset + b"\x00" * 8

        data_dir = self.root / "SEED_Data" / "StreamingAssets"
        data_dir.mkdir(parents=True)
        (data_dir / "config.bundle").write_bytes(
            build_bundle([("CAB-config", node_payload)], compress=True)
        )
        self.expected = curve

    def test_decodes_tables_and_recovers_the_formula(self):
        tables = merge(scan.scan_tree(self.root))

        self.assertEqual([t.skill for t in tables], ["Farming", "Mining"])
        farming = tables[0]
        self.assertEqual(farming.values, [float(v) for v in self.expected])
        self.assertTrue(farming.cumulative)

        fit = best_fit(farming)
        self.assertEqual(fit.model, "runescape-style")
        self.assertTrue(fit.is_exact)

    def test_cli_decode_produces_json_for_the_install(self):
        output = self.root / "xp.json"
        code = main(
            ["decode", "--path", str(self.root), "--format", "json", "-o", str(output)]
        )

        self.assertEqual(code, 0)
        payload = json.loads(output.read_text())
        self.assertEqual(payload["count"], 2)

        farming = payload["tables"][0]
        self.assertEqual(farming["skill"], "Farming")
        self.assertEqual(farming["max_level"], 59)
        self.assertEqual(farming["points"][1]["xp"], 83)
        self.assertTrue(farming["best_fit"]["exact"])

    def test_cli_decode_produces_markdown(self):
        output = self.root / "xp.md"
        main(["decode", "--path", str(self.root), "--format", "markdown", "-o", str(output)])

        text = output.read_text()
        self.assertIn("## Farming", text)
        self.assertIn("| 2 | 83 | 91 |", text)


if __name__ == "__main__":
    unittest.main()
