# SPDX-License-Identifier: LGPL-2.1-or-later
"""Decimals a typed value needs in a FreeCAD quantity field (no FreeCAD needed)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))
from nxstyle.quantity_core import decimals_needed  # noqa: E402


class DecimalsNeeded(unittest.TestCase):
    def test_typed_values(self):
        self.assertEqual(decimals_needed(28.095), 3)       # the double is 28.094999...: still 3
        self.assertEqual(decimals_needed(60 - 31.905), 3)  # computed, not typed: 28.095000000000002
        self.assertEqual(decimals_needed(29.395), 3)
        self.assertEqual(decimals_needed(190.94), 2)
        self.assertEqual(decimals_needed(20.0), 0)
        self.assertEqual(decimals_needed(0.0), 0)
        self.assertEqual(decimals_needed(-3.175), 3)

    def test_inch_values_in_mm(self):
        self.assertEqual(decimals_needed(25.4 / 64), 6)    # 1/64 in = 0.396875 mm
        self.assertEqual(decimals_needed(1.125 * 25.4), 3)  # 28.574999999999996 mm reads 28.575

    def test_small_and_capped(self):
        self.assertEqual(decimals_needed(0.0005), 4)
        self.assertEqual(decimals_needed(1e-7), 7)
        self.assertEqual(decimals_needed(1 / 3), 15)


if __name__ == "__main__":
    unittest.main()
