# SPDX-License-Identifier: LGPL-2.1-or-later
"""Datum reference frames: degrees of freedom arrested (Drake 5.9.7), no FreeCAD needed."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import drf  # noqa: E402

BOTTOM = ("plane", (0, 0, 0), (0, 0, -1))
LEFT = ("plane", (0, 0, 0), (-1, 0, 0))
FRONT = ("plane", (0, 0, 0), (0, -1, 0))
BORE = ("axis", (25, 25, 0), (0, 0, 1))
PIN2 = ("axis", (75, 25, 0), (0, 0, 1))


class ThreeTwoOne(unittest.TestCase):
    def test_three_planes_arrest_3_2_1(self):
        per, free, total = drf.analyse([BOTTOM, LEFT, FRONT])
        self.assertEqual((per, total, free), ([3, 2, 1], 6, []))

    def test_two_planes_leave_the_slide_along_their_line(self):
        per, free, total = drf.analyse([BOTTOM, LEFT])
        self.assertEqual((per, total), ([3, 2], 5))
        self.assertEqual(free, ["translation along Y"])

    def test_primary_plane_alone(self):
        per, free, total = drf.analyse([BOTTOM])
        self.assertEqual((per, total), ([3], 3))
        self.assertIn("rotation about Z", free)
        self.assertEqual(sorted(f for f in free if f.startswith("translation")),
                         ["translation along X", "translation along Y"])

    def test_plane_then_bore_leaves_rotation_about_the_bore(self):
        # a face and a hole perpendicular to it: the part can still turn about the hole's axis
        per, free, total = drf.analyse([BOTTOM, BORE])
        self.assertEqual((per, total), ([3, 2], 5))
        self.assertEqual(len(free), 1)
        self.assertTrue(free[0].startswith("rotation about Z through (25, 25"), free)

    def test_plane_bore_and_second_hole(self):
        per, _, total = drf.analyse([BOTTOM, BORE, PIN2])
        self.assertEqual((per, total), ([3, 2, 1], 6))

    def test_axis_primary_arrests_four(self):
        per, free, total = drf.analyse([BORE])
        self.assertEqual((per, total), ([4], 4))
        self.assertIn("translation along Z", free)

    def test_redundant_datum_arrests_nothing(self):
        top = ("plane", (0, 0, 10), (0, 0, 1))
        per, _, _ = drf.analyse([BOTTOM, top])
        self.assertEqual(per, [3, 0])

    def test_report(self):
        text = drf.report(["A", "B"], [BOTTOM, LEFT])
        self.assertEqual(text, "A | B arrests 5 of 6 degrees of freedom (A 3, B 2); free: translation along Y")


if __name__ == "__main__":
    unittest.main()
