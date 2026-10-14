# SPDX-License-Identifier: LGPL-2.1-or-later
"""Assembly clearance classification (no FreeCAD needed)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))
from nxstyle import clearance_core as cc  # noqa: E402


class Classify(unittest.TestCase):
    def test_four_kinds_and_clear(self):
        self.assertEqual(cc.classify(0.0, 50.0, 1000, 800), "hard")
        self.assertEqual(cc.classify(0.0, 800.0, 1000, 800), "containment")
        self.assertEqual(cc.classify(0.0, 0.0, 1000, 800), "touching")
        self.assertEqual(cc.classify(0.4, 0.0, 1000, 800, zone=0.5), "soft")
        self.assertIsNone(cc.classify(0.6, 0.0, 1000, 800, zone=0.5))
        self.assertIsNone(cc.classify(0.4, 0.0, 1000, 800))          # no zone: only contact counts

    def test_sliver_is_not_hard(self):
        self.assertEqual(cc.classify(0.0, 1e-5, 1000, 800), "touching")


class Rules(unittest.TestCase):
    def test_parse(self):
        r = cc.parse_rules(["Bolt | Plate = exclude", "Shaft|Bushing=0.5", "nonsense", "A|B=x"])
        self.assertEqual(r[cc.pair_key("Plate", "Bolt")], "exclude")
        self.assertEqual(r[cc.pair_key("Bushing", "Shaft")], 0.5)
        self.assertEqual(len(r), 2)

    def test_status(self):
        s = cc.status({"A|B": "hard", "A|C": "soft", "B|C": "touching"}, {"A|B": "hard", "A|C": "hard", "C|D": "soft"})
        self.assertEqual(s, {"A|B": "Unchanged", "A|C": "Changed (was soft)", "C|D": "New", "B|C": "Gone"})


if __name__ == "__main__":
    unittest.main()
