# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX sketch constraints in FreeCAD terms: element names, Collinear's roles, the gallery (no FreeCAD needed)."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))
from nxstyle import sketch_core as core  # noqa: E402

RIBBON = os.path.join(os.path.dirname(__file__), "..", "NXStyle", "nxstyle", "resources", "ribbons", "sketch.json")


class GeoIds(unittest.TestCase):
    def test_names(self):
        self.assertEqual(core.geo_id("Edge1"), 0)
        self.assertEqual(core.geo_id("Edge14"), 13)
        self.assertEqual(core.geo_id("H_Axis"), -1)
        self.assertEqual(core.geo_id("V_Axis"), -2)
        self.assertEqual(core.geo_id("ExternalEdge1"), -3)
        self.assertEqual(core.geo_id("ExternalEdge4"), -6)

    def test_points_are_not_curves(self):
        for sub in ("Vertex3", "RootPoint", "Constraint2", "", None, "Edge", "MyEdge2"):
            self.assertIsNone(core.geo_id(sub), sub)


class CollinearRoles(unittest.TestCase):
    def test_first_pick_moves(self):
        self.assertEqual(core.collinear_roles([(4, True), (0, True)]), (4, 0))
        self.assertEqual(core.collinear_roles([(0, True), (4, True)]), (0, 4))

    def test_a_fixed_line_is_the_target_whatever_the_order(self):
        self.assertEqual(core.collinear_roles([(core.H_AXIS, True), (3, True)]), (3, core.H_AXIS))
        self.assertEqual(core.collinear_roles([(3, True), (-3, True)]), (3, -3))

    def test_refusals_say_why(self):
        cases = {"two lines; 1 picked": [(1, True)],
                 "two lines; 3 picked": [(1, True), (2, True), (3, True)],
                 "not a line": [(1, True), (2, False)],
                 "different": [(2, True), (2, True)],
                 "cannot move": [(core.H_AXIS, True), (-3, True)]}
        for why, picks in cases.items():
            with self.assertRaises(core.NotCollinear) as cm:
                core.collinear_roles(picks)
            self.assertIn(why, str(cm.exception))


class Gallery(unittest.TestCase):
    def test_nx_names_in_nx_order(self):
        names = [g[0] for g in core.GALLERY]
        self.assertEqual(names[:3], ["Coincident", "Point on Curve", "Tangent"])
        for must in ("Collinear", "Midpoint", "Concentric", "Equal Length", "Horizontal Alignment"):
            self.assertIn(must, names)
        self.assertEqual(len(names), len(set(names)))

    def test_every_entry_names_a_command_and_a_pick(self):
        for label, cmds, pick in core.GALLERY:
            self.assertTrue(cmds and all(c.startswith(("Sketcher_", "NXStyle_")) for c in cmds), label)
            self.assertTrue(pick, label)

    def test_the_sketch_tab_has_the_new_buttons(self):
        with open(RIBBON, encoding="utf-8") as fh:
            tab = json.load(fh)["tabs"][0]
        items = {i["label"]: i["cmd"] for g in tab["groups"] for i in g["items"]}
        self.assertEqual(items["Point on Curve"], "Sketcher_ConstrainPointOnObject")
        self.assertEqual(items["Collinear"], "NXStyle_SketchCollinear")
        self.assertEqual(items["Geometric Constraints"], "NXStyle_GeometricConstraints")


if __name__ == "__main__":
    unittest.main()
