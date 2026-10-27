# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX primitives' decisions: Block types, axis rotations, dimensions and the Boolean plan (no FreeCAD needed)."""

import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))
from nxstyle import primitive_core as pc  # noqa: E402


class Blocks(unittest.TestCase):
    def test_origin_and_edge_lengths(self):
        corner, size = pc.block_box("Origin and Edge Lengths", (1, 2, 3),
                                    {"length": 65, "width": 85, "height": 20})
        self.assertEqual(corner, (1, 2, 3))
        self.assertEqual(size, (65, 85, 20))

    def test_zero_or_negative_lengths_refused(self):
        for dims in ({"length": 0, "width": 1, "height": 1}, {"length": 1, "width": -2, "height": 1},
                     {"length": 1, "width": 1}):
            with self.subTest(dims=dims), self.assertRaises(pc.CommandError):
                pc.block_box("Origin and Edge Lengths", (0, 0, 0), dims)

    def test_two_diagonal_points_in_any_order(self):
        a, b = (130, 22.5, 209.5), (190, 42.5, 275.5)
        self.assertEqual(pc.block_box("Two Diagonal Points", a, point2=b), ((130, 22.5, 209.5), (60, 20, 66)))
        self.assertEqual(pc.block_box("Two Diagonal Points", b, point2=a), ((130, 22.5, 209.5), (60, 20, 66)))
        with self.assertRaises(pc.CommandError):
            pc.block_box("Two Diagonal Points", a, point2=(190, 42.5, 209.5))     # flat in ZC

    def test_height_and_two_points_uses_the_origin_plane(self):
        corner, size = pc.block_box("Height and Two Points", (10, 20, 5), {"height": 7}, point2=(0, 0, 99))
        self.assertEqual(corner, (0, 0, 5))
        self.assertEqual(size, (10, 20, 7))
        with self.assertRaises(pc.CommandError):
            pc.block_box("Height and Two Points", (10, 20, 5), {"height": 7}, point2=(10, 0, 0))
        with self.assertRaises(pc.CommandError):
            pc.block_box("Height and Two Points", (10, 20, 5), {}, point2=(0, 0, 0))

    def test_second_point_required(self):
        with self.assertRaises(pc.CommandError):
            pc.block_box("Two Diagonal Points", (0, 0, 0))


class Vectors(unittest.TestCase):
    def test_rotation_turns_z_onto_each_axis(self):
        for key, d in pc.VECTORS:
            with self.subTest(key=key):
                q = pc.rotation_to(d)
                self.assertAlmostEqual(sum(c * c for c in q), 1.0)
                self.assertTrue(pc.close(pc.rotate(q, (0, 0, 1)), d))

    def test_rotation_for_any_direction(self):
        for d in itertools.product((-1, 0, 2), repeat=3):
            if d == (0, 0, 0):
                continue
            with self.subTest(d=d):
                u = pc._unit(d)
                self.assertTrue(pc.close(pc.rotate(pc.rotation_to(d), (0, 0, 1)), u, 1e-12))

    def test_reverse_and_names(self):
        self.assertEqual(pc.vector("ZC", reverse=True), (0, 0, -1))
        self.assertEqual(pc.vector_key((0, 0, -3)), "-ZC")
        self.assertIsNone(pc.vector_key((1, 1, 0)))
        with self.assertRaises(pc.CommandError):
            pc.rotation_to((0, 0, 0))


class Dimensions(unittest.TestCase):
    def test_parameters(self):
        self.assertEqual(pc.check_dimensions("Cylinder", {"diameter": 6.35, "height": 38.1}),     # 0.25 in, 1.5 in
                         {"Radius": 3.175, "Height": 38.1})
        self.assertEqual(pc.check_dimensions("Cone", {"baseDiameter": 4, "topDiameter": 0, "height": 10}),
                         {"Radius1": 2, "Radius2": 0, "Height": 10})
        self.assertEqual(pc.check_dimensions("Sphere", {"diameter": 0.55}), {"Radius": 0.275})

    def test_refusals(self):
        bad = [("Cylinder", {"diameter": 0, "height": 1}), ("Cylinder", {"diameter": 1, "height": -1}),
               ("Cone", {"baseDiameter": 0, "topDiameter": 0, "height": 1}),
               ("Cone", {"baseDiameter": -1, "topDiameter": 2, "height": 1}),
               ("Cone", {"baseDiameter": 1, "topDiameter": 2, "height": 0}), ("Sphere", {"diameter": 0})]
        for command, dims in bad:
            with self.subTest(command=command, dims=dims), self.assertRaises(pc.CommandError):
                pc.check_dimensions(command, dims)

    def test_round_trip_through_properties(self):
        self.assertEqual(pc.dimensions_of("Cone", {"Radius1": 2, "Radius2": 3, "Height": 10}),
                         {"baseDiameter": 4, "topDiameter": 6, "height": 10})
        self.assertEqual(pc.dimensions_of("Block", {"Length": 1, "Width": 2, "Height": 3}),
                         {"length": 1, "width": 2, "height": 3})

    def test_command_of(self):
        self.assertEqual(pc.command_of("PartDesign::AdditiveBox"), ("Block", "additive"))
        self.assertEqual(pc.command_of("PartDesign::SubtractiveCylinder"), ("Cylinder", "subtractive"))
        self.assertIsNone(pc.command_of("PartDesign::Pad"))
        self.assertIsNone(pc.command_of("PartDesign::AdditiveWedge"))


class Boolean(unittest.TestCase):
    def test_plan(self):
        self.assertEqual(pc.plan("none", False, work_body_empty=True)["body"], "work")
        self.assertEqual(pc.plan("none", True)["body"], "new")
        self.assertEqual(pc.plan("unite", True), {"body": "target", "feature": "Additive", "common": False})
        self.assertEqual(pc.plan("subtract", True)["feature"], "Subtractive")
        self.assertEqual(pc.plan("intersect", True), {"body": "new", "feature": "Additive", "common": True})

    def test_target_required(self):
        for mode in ("unite", "subtract", "intersect"):
            with self.subTest(mode=mode), self.assertRaises(pc.CommandError):
                pc.plan(mode, False)
        with self.assertRaises(pc.CommandError):
            pc.plan("merge", True)

    def test_result_issues(self):
        self.assertEqual(pc.result_issue("unite", 100, 150, 1, 2, "Block")[0], "error")
        self.assertEqual(pc.result_issue("unite", 100, 100, 1, 1)[0], "warning")
        self.assertIsNone(pc.result_issue("unite", 100, 150, 1, 1))
        self.assertEqual(pc.result_issue("subtract", 100, 100, 1, 1)[0], "warning")
        self.assertIsNone(pc.result_issue("subtract", 100, 80, 1, 1))
        self.assertEqual(pc.result_issue("intersect", 100, 0, 1, 0)[0], "error")
        self.assertIsNone(pc.result_issue("intersect", 100, 40, 1, 1))
        self.assertIsNone(pc.result_issue("none", 0, 40, 0, 1))


class Points(unittest.TestCase):
    def test_midpoint_and_nearest(self):
        self.assertEqual(pc.midpoint((0, 0, 0), (2, 4, -6)), (1, 2, -3))
        self.assertEqual(pc.nearest([(0, 0, 0), (10, 0, 0)], (7, 1, 0)), (10, 0, 0))


if __name__ == "__main__":
    unittest.main()
