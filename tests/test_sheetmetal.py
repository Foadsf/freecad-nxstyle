# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sheet metal bend allowance and flat lengths (no FreeCAD needed)."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import sheetmetal as sm  # noqa: E402


class Shih(unittest.TestCase):
    """Shih, Parametric Modeling with Siemens NX, ch. 13 (p. 13-31): the actuator bracket, 16 gauge
    (T = R = 0.0625 in), K = 0.41."""
    T = R = 0.0625

    def test_bend_allowance(self):
        self.assertAlmostEqual(sm.bend_allowance(90, self.R, self.T, 0.41), 0.13843, places=5)

    def test_half_flat_length(self):
        # tab 1.508 between the inside faces (half to the bend: 1.508/2 - R), flange 0.615 outside
        # (0.615 - (R + T) straight), one bend; R = T here
        half = sm.flat_from_tangents([1.508 / 2 - self.T, 0.615 - 2 * self.T], [(90, self.R)], self.T, 0.41)
        self.assertAlmostEqual(half, 1.31992, delta=2e-5)
        self.assertAlmostEqual(half * sm.INCH, 33.526, places=3)

    def test_outside_dimensions_give_the_same(self):
        # outside legs: the tab's half, 1.508/2 + T, to the outer sharp corner; the flange 0.615 tall
        half = sm.flat_from_outside([1.508 / 2 + self.T, 0.615], [(90, self.R)], self.T, 0.41)
        self.assertAlmostEqual(half, 1.31992, delta=2e-5)


class Relations(unittest.TestCase):
    def test_bend_deduction_definition(self):
        a, r, t, k = 90, 2.0, 1.5, 0.4
        self.assertAlmostEqual(sm.bend_deduction(a, r, t, k), 2 * (r + t) - math.pi / 2 * (r + k * t))

    def test_zero_angle_changes_nothing(self):
        self.assertAlmostEqual(sm.bend_allowance(0, 2, 1), 0)
        self.assertAlmostEqual(sm.bend_deduction(0, 2, 1), 0)

    def test_k_half_is_the_mid_surface(self):
        self.assertAlmostEqual(sm.bend_allowance(180, 3, 2, 0.5), math.pi * 4)

    def test_din_ansi(self):
        self.assertAlmostEqual(sm.din(0.41), 0.82)
        self.assertAlmostEqual(sm.ansi(sm.din(0.33)), 0.33)


class Checks(unittest.TestCase):
    def test_default_is_clean(self):
        self.assertEqual(sm.check(1.0, 1.0, sm.K_DEFAULT), [])

    def test_din_value_entered_as_ansi(self):
        self.assertEqual(sm.check(1.0, 1.0, 0.82)[0][0], "error")

    def test_unusual_and_tight(self):
        sev = [s for s, _ in sm.check(2.0, 1.0, 0.2)]
        self.assertEqual(sev, ["warning", "note"])

    def test_report_names_values(self):
        r = sm.report(0.0625, 0.0625, 0.41, unit="in")
        self.assertIn("bend allowance 0.1384 in", r)
        self.assertIn("DIN k 0.82", r)


if __name__ == "__main__":
    unittest.main()
