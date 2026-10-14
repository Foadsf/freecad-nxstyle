# SPDX-License-Identifier: LGPL-2.1-or-later
"""PMI model views: frames, camera orientation, label layout (no FreeCAD needed)."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import pmi_views as pv  # noqa: E402

BOX = [(x, y, z) for x in (0, 80) for y in (0, 60) for z in (0, 10)]
SIZE = math.sqrt(80 ** 2 + 60 ** 2 + 10 ** 2)


def close(a, b, tol=1e-9):
    return all(abs(p - q) < tol for p, q in zip(a, b))


class Frames(unittest.TestCase):
    def test_nx_default_views(self):
        self.assertEqual(pv.ORDER, ["Front", "Top", "Right", "Back", "Bottom", "Left", "Isometric", "Trimetric"])

    def test_frames_are_right_handed_and_orthonormal(self):
        for name, (d, u) in pv.STANDARD.items():
            r, up, back = pv.frame(d, u)
            for v in (r, up, back):
                self.assertAlmostEqual(pv._dot(v, v), 1.0, msg=name)
            self.assertAlmostEqual(pv._dot(r, up), 0.0, msg=name)
            self.assertTrue(close(pv._cross(r, up), back), name)

    def test_front_looks_along_y_with_x_to_the_right(self):
        r, u, b = pv.frame(*pv.STANDARD["Front"])
        self.assertTrue(close(r, (1, 0, 0)) and close(u, (0, 0, 1)) and close(b, (0, -1, 0)))

    def test_trimetric_is_freecads(self):
        # measured from FreeCAD 1.1.4's View > Standard views > Trimetric (self-test checks all eight live)
        d, u = pv.STANDARD["Trimetric"]
        self.assertTrue(close(d, (-0.409575, 0.709407, -0.573577), 5e-6))           # printed to 6 places
        self.assertTrue(close(pv.frame(d, u)[1], (-0.286788, 0.496732, 0.819152), 5e-6))

    def test_top_has_x_right_and_y_up(self):
        r, u, _ = pv.frame(*pv.STANDARD["Top"])
        self.assertTrue(close(r, (1, 0, 0)) and close(u, (0, 1, 0)))

    def test_up_along_the_view_is_refused(self):
        with self.assertRaises(ValueError):
            pv.frame((0, 0, -1), (0, 0, 1))


class Camera(unittest.TestCase):
    def test_quaternion_turns_the_camera_onto_the_view(self):
        for name, (d, u) in pv.STANDARD.items():
            q = pv.quaternion(d, u)
            self.assertAlmostEqual(sum(c * c for c in q), 1.0, msg=name)
            _, up, _ = pv.frame(d, u)
            self.assertTrue(close(pv.rotate(q, (0, 0, -1)), pv._unit(d), 1e-9), name)
            self.assertTrue(close(pv.rotate(q, (0, 1, 0)), up, 1e-9), name)

    def test_front_is_a_quarter_turn_about_x(self):
        q = pv.quaternion(*pv.STANDARD["Front"])
        h = math.sqrt(0.5)
        self.assertTrue(close(q, (h, 0, 0, h)) or close(q, (-h, 0, 0, -h)))


class Labels(unittest.TestCase):
    def test_front_column_is_the_existing_one(self):
        # left of the part (x = 0 - 0.35 size), rows down from above it, at the box centre's depth
        p = pv.label_point(BOX, SIZE, *pv.STANDARD["Front"], row=2)
        self.assertTrue(close(p, (-0.35 * SIZE, 30, 10 + 0.1 * SIZE - 0.28 * SIZE)))

    def test_top_view_rows_run_down_the_screen(self):
        p0 = pv.label_point(BOX, SIZE, *pv.STANDARD["Top"], row=0)
        p1 = pv.label_point(BOX, SIZE, *pv.STANDARD["Top"], row=1)
        self.assertAlmostEqual(p0[0], -0.35 * SIZE)
        self.assertAlmostEqual(p0[1] - p1[1], 0.14 * SIZE)      # one row lower on screen = smaller y
        self.assertAlmostEqual(p0[2], p1[2])                    # same depth: they do not stack behind each other

    def test_row_round_trip(self):
        for name in pv.ORDER:
            for row in (0, 3, 7):
                p = pv.label_point(BOX, SIZE, *pv.STANDARD[name], row=row)
                self.assertEqual(pv.label_row(BOX, SIZE, *pv.STANDARD[name], p), row, name)

    def test_shown(self):
        self.assertTrue(pv.shown([], "Top"))                 # displayed in all views
        self.assertTrue(pv.shown(["Top"], None))             # no work view: everything shows
        self.assertTrue(pv.shown(["Top", "Front"], "Front"))
        self.assertFalse(pv.shown(["Top"], "Front"))


if __name__ == "__main__":
    unittest.main()
