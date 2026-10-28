# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX's Projected View: the direction of each projected view, first and third angle, and its place."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import drafting_core as dc  # noqa: E402

FRONT = ((0, -1, 0), (1, 0, 0))        # TechDraw's Front: the viewer on -Y, paper x = +X, paper y = +Z


def close(a, b):
    return all(abs(p - q) < 1e-12 for p, q in zip(a, b))


class ThirdAngle(unittest.TestCase):
    def test_the_view_above_the_front_is_the_top(self):
        d, x = dc.projected(*FRONT, "Above")
        self.assertTrue(close(d, (0, 0, 1)) and close(x, (1, 0, 0)), (d, x))
        self.assertTrue(close(dc.paper_axes(d, x)[1], (0, 1, 0)))       # the top view's paper y is +Y

    def test_the_view_right_of_the_front_is_the_right_side(self):
        d, x = dc.projected(*FRONT, "Right")
        self.assertTrue(close(d, (1, 0, 0)) and close(x, (0, 1, 0)), (d, x))
        self.assertTrue(close(dc.paper_axes(d, x)[1], (0, 0, 1)))       # Z stays up

    def test_below_and_left(self):
        self.assertTrue(close(dc.projected(*FRONT, "Below")[0], (0, 0, -1)))
        d, x = dc.projected(*FRONT, "Left")
        self.assertTrue(close(d, (-1, 0, 0)) and close(x, (0, -1, 0)), (d, x))

    def test_projecting_twice_round_a_side_comes_back_reversed(self):
        d, x = dc.projected(*dc.projected(*FRONT, "Right"), "Right")
        self.assertTrue(close(d, (0, 1, 0)) and close(x, (-1, 0, 0)), (d, x))      # the back view


class FirstAngle(unittest.TestCase):
    def test_the_view_right_of_the_front_shows_the_left_side(self):
        d, x = dc.projected(*FRONT, "Right", "First angle")
        self.assertTrue(close(d, (-1, 0, 0)) and close(x, (0, -1, 0)), (d, x))

    def test_the_view_below_the_front_is_the_top(self):
        self.assertTrue(close(dc.projected(*FRONT, "Below", "First angle")[0], (0, 0, 1)))


class Placement(unittest.TestCase):
    BOX = [(x, y, z) for x in (0, 240) for y in (0, 25) for z in (0, 20)]   # the rack, inches

    def test_extent_of_the_rack_in_the_front_top_and_right_views(self):
        self.assertEqual(dc.extent(self.BOX, *FRONT)[:2], (240, 20))
        self.assertEqual(dc.extent(self.BOX, *dc.projected(*FRONT, "Above"))[:2], (240, 25))
        self.assertEqual(dc.extent(self.BOX, *dc.projected(*FRONT, "Right"))[:2], (25, 20))

    def test_a_side_view_lines_up_with_its_parent(self):
        x, y = dc.place((100, 80), (240, 20), (25, 20), "Right", 0.5)
        self.assertEqual((x, y), (100 + (120 + 12.5) * 0.5 + dc.GAP, 80))

    def test_a_view_above_lines_up_with_its_parent(self):
        x, y = dc.place((100, 80), (240, 20), (240, 25), "Above", 0.5)
        self.assertEqual((x, y), (100, 80 + 22.5 * 0.5 + dc.GAP))

    def test_the_leaders_arrow_tip_lands_on_the_terminating_point(self):
        import re
        tip, knee = (100.0, 50.0), (120.0, 70.0)
        body, w, h, centre, end = dc.leader(tip, knee, 6.35)
        self.assertEqual(end, (126.35, 70.0))
        arrow = re.search(r'<path d="M ([\d.]+) ([\d.]+) L', body.split("/>")[1])     # the filled head
        got = dc.arrow_tip(centre, w, h, (float(arrow.group(1)), float(arrow.group(2))))
        self.assertTrue(close(got, tip), got)

    def test_unknown_side_is_refused(self):
        with self.assertRaises(ValueError):
            dc.projected(*FRONT, "Behind")


if __name__ == "__main__":
    unittest.main()
