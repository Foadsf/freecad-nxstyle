# SPDX-License-Identifier: LGPL-2.1-or-later
"""ISO 286 limits and fits, ISO 2768 general tolerances (no FreeCAD needed)."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))
from nxstyle import iso  # noqa: E402


def means():
    """Geometric mean D of each ISO 286 size range above 3 mm (ISO's formulas do not hold at 0-3 mm)."""
    return [(i, math.sqrt(lo * hi)) for i, (lo, hi) in enumerate(zip(iso.LOWER, iso.RANGES)) if lo >= 3]


class Formulas(unittest.TestCase):
    """The rounded table values against the ISO 286-1 formulas they come from: a typo in the table
    shows up as a value far from its formula."""

    def close(self, table, formula, label):
        self.assertLessEqual(abs(abs(table) - formula), max(1.0, 0.08 * formula), f"{label}: {table} vs {formula:.2f}")

    def test_es_of_d_e_f_g(self):
        for letter, k, p in (("d", 16, 0.44), ("e", 11, 0.41), ("f", 5.5, 0.41), ("g", 2.5, 0.34)):
            for i, D in means():
                self.close(iso.ES[letter][i], k * D ** p, f"{letter} range {i}")

    def test_ei_of_k_m_n_p(self):
        for i, D in means():
            self.close(iso.EI["k"][i], 0.6 * D ** (1 / 3), f"k range {i}")
            self.assertEqual(iso.EI["m"][i], iso.IT[7][i] - iso.IT[6][i], f"m range {i}")
            self.close(iso.EI["n"][i], 5 * D ** 0.34, f"n range {i}")
            self.assertTrue(0 <= iso.EI["p"][i] - iso.IT[7][i] <= 5, f"p range {i}")

    def test_s_and_r(self):
        lo = 3
        for (hi, s), (_, r) in zip(iso.EI_SPLIT["s"][1:], iso.EI_SPLIT["r"][1:]):
            D = math.sqrt(lo * hi)
            i = iso.range_index(hi)
            if hi <= 50:
                self.assertTrue(1 <= s - iso.IT[8][i] <= 4, f"s up to {hi}")
            else:
                self.close(s, iso.IT[7][i] + 0.4 * D, f"s up to {hi}")
            p = iso.EI["p"][i]
            self.close(r, math.sqrt(p * s), f"r up to {hi}")
            lo = hi

    def test_it_grades_step_by_1_6(self):
        # from IT6 on each grade is about 1.6 x the one before (IT6 = 10 i, IT7 = 16 i, IT8 = 25 i ...);
        # ISO's rounding makes the smallest range's IT8/IT7 14/10
        for g in range(7, 17):
            for i in range(len(iso.RANGES)):
                ratio = iso.IT[g][i] / iso.IT[g - 1][i]
                self.assertTrue(1.38 <= ratio <= 1.8, f"IT{g}/IT{g - 1} range {i}: {ratio:.2f}")
                # and exactly ten times every fifth grade from IT7 on (IT6 and below are rounded finer)
                if g >= 12:
                    self.assertAlmostEqual(iso.IT[g][i] / iso.IT[g - 5][i], 10.0, delta=1e-9,
                                           msg=f"IT{g}/IT{g - 5} range {i}")


class Limits(unittest.TestCase):
    def dev(self, cls, size):
        u, lo = iso.deviations(cls, size)
        return round(u * 1000), round(lo * 1000)

    def test_published_examples(self):
        self.assertEqual(self.dev("g6", 40), (-9, -25))      # 39.975 .. 39.991
        self.assertEqual(self.dev("e9", 110)[0], -72)
        self.assertEqual(self.dev("K7", 300)[0], 16)
        self.assertEqual(self.dev("H7", 10), (15, 0))
        self.assertEqual(self.dev("g6", 10), (-5, -14))

    def test_holes_mirror_shafts(self):
        self.assertEqual(self.dev("F7", 20), (41, 20))
        self.assertEqual(self.dev("JS6", 20), (6, -6))     # +/- 6.5 rounded
        self.assertEqual(self.dev("N7", 20), (-7, -28))    # -15 + (21 - 13)
        self.assertEqual(self.dev("P7", 20), (-14, -35))   # -22 + 8
        self.assertEqual(self.dev("M7", 2), (-2, -12))     # no delta up to 3 mm
        self.assertEqual(self.dev("N9", 20), (0, -52))

    def test_fits(self):
        f = iso.fit(10, "H7", "g6")
        self.assertEqual(f["kind"], "clearance")
        self.assertAlmostEqual(f["clearance_min"], 0.005)
        self.assertAlmostEqual(f["clearance_max"], 0.029)
        self.assertEqual(iso.fit(50, "H7", "k6")["kind"], "transition")
        p = iso.fit(25, "H7", "p6")
        self.assertEqual(p["kind"], "interference")
        self.assertAlmostEqual(p["clearance_max"], 0.021 - 0.022)

    def test_bad_input(self):
        for bad in ("X7", "H", "h99", ""):
            with self.assertRaises(ValueError):
                iso.deviations(bad, 10)
        with self.assertRaises(ValueError):
            iso.deviations("H7", 600)


class General(unittest.TestCase):
    def test_linear(self):
        self.assertEqual(iso.linear(25, "m"), 0.2)
        self.assertEqual(iso.linear(150, "m"), 0.5)
        self.assertEqual(iso.linear(30, "f"), 0.1)        # 30 is in "over 6 to 30"
        self.assertEqual(iso.linear(2, "c"), 0.2)
        with self.assertRaises(ValueError):
            iso.linear(2, "v")
        with self.assertRaises(ValueError):
            iso.linear(0.3, "m")

    def test_angular_and_geometric(self):
        self.assertAlmostEqual(iso.angular(30, "m"), 0.5)
        self.assertAlmostEqual(iso.angular(500, "v"), 20 / 60)
        self.assertEqual(iso.flatness(120, "K"), 0.4)
        self.assertEqual(iso.perpendicularity(80, "H"), 0.2)
        self.assertEqual(iso.RUNOUT["L"], 0.5)

    def test_note(self):
        self.assertEqual(iso.parse_general("ISO 2768-mK"), ("m", "K", False))
        self.assertEqual(iso.parse_general("ISO 2768-fH-E"), ("f", "H", True))
        self.assertIsNone(iso.parse_general("tolerances per company standard"))


if __name__ == "__main__":
    unittest.main()
