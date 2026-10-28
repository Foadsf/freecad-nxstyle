# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX Move Object's decisions: Distance, Angle, Point to Point, divisions, copies and attached offsets (no FreeCAD
needed)."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))
from nxstyle import move_core as mc  # noqa: E402


def near(a, b, tol=1e-9):
    return all(abs(p - q) <= tol for p, q in zip(a, b))


class Distance(unittest.TestCase):
    def test_book_lift_along_zc(self):
        # NX 12 for Engineering Design 4.7.3: the second block moved 200 (in) along ZC
        m = mc.step("Distance", {"vector": mc.VECTOR["ZC"], "distance": 200 * 25.4})
        self.assertTrue(near(mc.apply(m, (1, 2, 3)), (1, 2, 3 + 5080)))

    def test_each_vector(self):
        for key, d in mc.VECTORS:
            with self.subTest(key=key):
                m = mc.distance(d, 5)
                self.assertTrue(near(mc.apply(m, (0, 0, 0)), tuple(5 * c for c in d)))

    def test_vector_is_normalised(self):
        self.assertTrue(near(mc.distance((0, 0, 3), 7)[0], (0, 0, 7)))

    def test_negative_distance_moves_back(self):
        self.assertTrue(near(mc.apply(mc.distance(mc.VECTOR["XC"], -127), (0, 0, 0)), (-127, 0, 0)))

    def test_no_vector_refused(self):
        with self.assertRaises(mc.CommandError):
            mc.distance((0, 0, 0), 1)

    def test_divisions_divide_the_distance(self):
        m = mc.step("Distance", {"vector": mc.VECTOR["XC"], "distance": 90, "divisions": 3})
        self.assertTrue(near(mc.apply(m, (0, 0, 0)), (30, 0, 0)))


class Angle(unittest.TestCase):
    def test_quarter_turn_about_zc_through_a_point(self):
        m = mc.angle(mc.VECTOR["ZC"], (10, 0, 0), 90)
        self.assertTrue(near(mc.apply(m, (20, 0, 5)), (10, 10, 5)))
        self.assertTrue(near(mc.apply(m, (10, 0, 7)), (10, 0, 7)))    # the axis stays put

    def test_right_hand_about_xc(self):
        self.assertTrue(near(mc.apply(mc.angle(mc.VECTOR["XC"], (0, 0, 0), 90), (0, 1, 0)), (0, 0, 1)))
        self.assertTrue(near(mc.apply(mc.angle(mc.VECTOR["-XC"], (0, 0, 0), 90), (0, 1, 0)), (0, 0, -1)))

    def test_rotation_keeps_distances(self):
        m = mc.angle((1, 2, 3), (4, -5, 6), 37)
        a, b = (1, 1, 1), (-3, 7, 2)
        d0 = math.dist(a, b)
        self.assertAlmostEqual(math.dist(mc.apply(m, a), mc.apply(m, b)), d0, places=9)

    def test_divisions_divide_the_angle(self):
        m = mc.step("Angle", {"axis": mc.VECTOR["ZC"], "point": (0, 0, 0), "angle": 180, "divisions": 2})
        self.assertTrue(near(mc.apply(m, (1, 0, 0)), (0, 1, 0)))


class PointToPoint(unittest.TestCase):
    def test_from_to(self):
        m = mc.step("Point to Point", {"from": (1, 2, 3), "to": (11, -2, 3)})
        self.assertTrue(near(mc.apply(m, (0, 0, 0)), (10, -4, 0)))
        self.assertEqual(m[1], mc.IDENTITY[1])

    def test_divisions(self):
        m = mc.step("Point to Point", {"from": (0, 0, 0), "to": (10, 0, 0), "divisions": 4})
        self.assertTrue(near(mc.apply(m, (0, 0, 0)), (2.5, 0, 0)))

    def test_dynamic_is_not_typed(self):
        with self.assertRaises(mc.CommandError):
            mc.step("Dynamic", {})


class Copies(unittest.TestCase):
    def test_move_original_is_one_motion(self):
        one = mc.distance(mc.VECTOR["XC"], 5)
        self.assertEqual(mc.motions("Move Original", one, 4), [one])

    def test_copy_i_moves_i_times(self):
        one = mc.distance(mc.VECTOR["YC"], 25)
        ms = mc.motions("Copy Original", one, 3)
        self.assertEqual(len(ms), 3)
        for i, m in enumerate(ms, 1):
            self.assertTrue(near(mc.apply(m, (0, 0, 0)), (0, 25 * i, 0)))

    def test_angle_copies_go_round(self):
        one = mc.angle(mc.VECTOR["ZC"], (0, 0, 0), 90)
        last = mc.motions("Copy Original", one, 4)[-1]
        self.assertTrue(near(mc.apply(last, (1, 0, 0)), (1, 0, 0)))    # four quarter turns: back home

    def test_no_copies_refused(self):
        with self.assertRaises(mc.CommandError):
            mc.motions("Copy Original", mc.IDENTITY, 0)

    def test_copy_of_sketch_refused(self):
        self.assertIsNone(mc.copy_issue({"body", "link"}, "Copy Original"))
        self.assertIsNone(mc.copy_issue({"attached"}, "Move Original"))
        self.assertIsNotNone(mc.copy_issue({"body", "attached"}, "Copy Original"))


class Composition(unittest.TestCase):
    def test_compose_matches_applying_in_turn(self):
        a = mc.angle((0, 1, 1), (3, 0, 0), 30)
        b = mc.distance((1, 0, 0), 7)
        p = (2, -1, 4)
        self.assertTrue(near(mc.apply(mc.compose(a, b), p), mc.apply(a, mc.apply(b, p))))

    def test_inverse(self):
        m = mc.compose(mc.angle((1, 1, 0), (0, 2, 0), 50), mc.distance((0, 0, 1), 3))
        self.assertTrue(mc.is_identity(mc.compose(mc.inverse(m), m)))

    def test_moved_placement(self):
        placement = ((10, 0, 0), mc.axis_angle((0, 0, 1), 90))
        new = mc.moved(mc.distance(mc.VECTOR["ZC"], 5), placement)
        self.assertTrue(near(new[0], (10, 0, 5)))
        self.assertTrue(near(new[1], placement[1]))

    def test_attached_offset_moves_the_object_by_the_motion(self):
        support = ((0, 50, 0), mc.axis_angle((1, 0, 0), 90))          # e.g. the XZ plane, lifted
        offset = ((3, 4, 0), mc.axis_angle((0, 0, 1), 20))
        placement = mc.compose(support, offset)
        m = mc.compose(mc.angle((0, 0, 1), (1, 1, 0), 33), mc.distance((1, 2, 3), 9))
        new_offset = mc.moved_offset(m, placement, offset)
        got = mc.compose(support, new_offset)
        want = mc.moved(m, placement)
        for p in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)):
            self.assertTrue(near(mc.apply(got, p), mc.apply(want, p)))


class Issues(unittest.TestCase):
    def test_zero_motion_warns(self):
        for motion, values in (("Distance", {"vector": mc.VECTOR["ZC"], "distance": 0}),
                               ("Angle", {"axis": mc.VECTOR["ZC"], "point": (0, 0, 0), "angle": 360}),
                               ("Point to Point", {"from": (1, 1, 1), "to": (1, 1, 1)})):
            with self.subTest(motion=motion):
                error, warnings = mc.issues(motion, values)
                self.assertIsNone(error)
                self.assertTrue(warnings and "do not move" in warnings[0])

    def test_errors(self):
        self.assertIsNotNone(mc.issues("Distance", {"vector": mc.VECTOR["ZC"], "distance": 5}, "Copy Original",
                                       0)[0])
        self.assertIsNotNone(mc.issues("Distance", {"vector": mc.VECTOR["ZC"], "distance": 5, "divisions": 0})[0])
        self.assertIn("from", mc.issues("Point to Point", {"to": (0, 0, 0)})[0])

    def test_fine(self):
        self.assertEqual(mc.issues("Distance", {"vector": mc.VECTOR["XC"], "distance": 127}), (None, []))


if __name__ == "__main__":
    unittest.main()
