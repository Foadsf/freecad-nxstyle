# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pin location (Drake ch. 24) and pointing error (Fischer ch. 15), no FreeCAD needed."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import alignment as al  # noqa: E402

G6 = al.limits(6.0, "G6")          # 6.004 .. 6.012
H6PIN = al.limits(6.0, "h6")       # 5.992 .. 6.000


class Basics(unittest.TestCase):
    def test_limits(self):
        self.assertEqual(tuple(round(x, 4) for x in G6), (6.004, 6.012))
        self.assertEqual(tuple(round(x, 4) for x in H6PIN), (5.992, 6.0))
        self.assertEqual(al.limits(80, plus=0.005, minus=0.005), (79.995, 80.005))

    def test_fischer_lever(self):
        # Fischer ch. 15: 1° over 1000 m moves the far end 17.455 m
        self.assertAlmostEqual(al.pointing(math.radians(1), 1000.0), 17.455, places=3)

    def test_spacing_gap(self):
        worst, best = al.spacing_gap((79.995, 80.005), (79.995, 80.005))
        self.assertAlmostEqual(worst, 0.01)
        self.assertEqual(best, 0.0)
        worst, best = al.spacing_gap((80.0, 80.01), (80.02, 80.03))
        self.assertAlmostEqual(worst, 0.03)
        self.assertAlmostEqual(best, 0.01)

    def test_thermal(self):
        # 200 mm, 10 K, aluminium (23.1e-6) on steel (11.7e-6)
        self.assertAlmostEqual(al.thermal_growth(200, 10, 23.1e-6, 11.7e-6), 0.0228)


class TwoHoles(unittest.TestCase):
    def test_tight_holes_do_not_assemble_with_spacing_tolerance(self):
        d = (79.995, 80.005)
        r = al.analyse(al.TWO_HOLES, G6, H6PIN, G6, H6PIN, d, d)
        self.assertAlmostEqual(r["clearance"], 0.004 - 0.010)
        self.assertFalse(r["assembles"])
        self.assertIn("does not assemble", r["findings"][0])

    def test_exact_and_simplified_rotation_agree(self):
        hole, pin = (6.03, 6.05), (5.992, 6.0)
        d = (99.99, 100.01)
        r = al.analyse(al.TWO_HOLES, hole, pin, hole, pin, d, d)
        self.assertTrue(r["assembles"])
        # 24.4 with equal spacings is 2 asin(e/2d): above e/d (24.5) only by (e/d)^3/24
        e_over_d = r["rotation_simplified"]
        self.assertAlmostEqual(r["rotation"] - e_over_d, e_over_d ** 3 / 24, delta=2e-13)   # acos near 1
        self.assertAlmostEqual(r["translation"], (6.05 - 5.992) / 2)

    def test_law_of_cosines(self):
        self.assertAlmostEqual(al.rotation_two_holes(100, 100, 0.0), 0.0)
        self.assertIsNone(al.rotation_two_holes(100, 101, 0.5))      # 1 mm apart, 0.5 clearance: no fit
        a = al.rotation_two_holes(100, 100, 0.05)
        self.assertAlmostEqual(a, 2 * math.asin(0.025 / 100))

    def test_temperature_enlarges_errors(self):
        hole, pin = (6.03, 6.05), (5.992, 6.0)
        d = (199.99, 200.01)
        cold = al.analyse(al.TWO_HOLES, hole, pin, hole, pin, d, d)
        warm = al.analyse(al.TWO_HOLES, hole, pin, hole, pin, d, d, dT=10, cte_holes=23.1e-6, cte_pins=11.7e-6)
        self.assertAlmostEqual(warm["clearance"], cold["clearance"] - 0.0228)
        self.assertAlmostEqual(warm["translation"], cold["translation"] + 0.0114)
        self.assertAlmostEqual(warm["rotation"], cold["rotation"] + 10 * 11.4e-6)


class HoleAndSlot(unittest.TestCase):
    def test_slot_takes_the_spacing_out_of_the_fit(self):
        d = (79.995, 80.005)
        r = al.analyse(al.HOLE_SLOT, G6, H6PIN, G6, H6PIN, d, d, slot_length=7.0, distance=2000)
        self.assertTrue(r["assembles"])
        self.assertAlmostEqual(r["clearance"], 0.002)                # the tighter of hole and slot width
        self.assertAlmostEqual(r["translation"], 0.010)
        self.assertAlmostEqual(r["rotation"], math.asin(0.020 / 79.995))
        self.assertAlmostEqual(r["pointing"], 2000 * math.tan(r["rotation"]))
        self.assertAlmostEqual(r["pointing"], 0.5, delta=0.001)

    def test_longer_base_and_finer_classes(self):
        d = (199.995, 200.005)
        r = al.analyse(al.HOLE_SLOT, al.limits(6, "G5"), al.limits(6, "h5"), al.limits(6, "G5"),
                       al.limits(6, "h5"), d, d, slot_length=7.0, distance=2000)
        self.assertAlmostEqual(r["translation"], 0.007)
        self.assertAlmostEqual(r["pointing"], 2000 * 0.014 / 199.995, delta=1e-6)

    def test_short_slot_and_heat(self):
        d = (199.995, 200.005)
        r = al.analyse(al.HOLE_SLOT, G6, H6PIN, G6, H6PIN, d, d, slot_length=6.02, dT=10, cte_holes=23.1e-6,
                       cte_pins=11.7e-6)
        self.assertFalse(r["assembles"])
        self.assertTrue(any("too short" in f for f in r["findings"]))
        ok = al.analyse(al.HOLE_SLOT, G6, H6PIN, G6, H6PIN, d, d, slot_length=6.1, dT=10, cte_holes=23.1e-6,
                        cte_pins=11.7e-6)
        self.assertTrue(ok["assembles"])

    def test_report(self):
        d = (79.995, 80.005)
        text = al.report(al.analyse(al.HOLE_SLOT, G6, H6PIN, G6, H6PIN, d, d, slot_length=7, distance=2000))
        self.assertIn("assembles", text)
        self.assertIn("pointing error at 2000 mm", text)


if __name__ == "__main__":
    unittest.main()
