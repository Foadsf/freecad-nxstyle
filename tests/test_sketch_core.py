# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX sketch constraints in FreeCAD terms: element names, Collinear's roles, the gallery (no FreeCAD needed)."""

import json
import math
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
        items = {i["label"]: i["cmd"] for g in tab["groups"] for i in g["items"] if "label" in i}
        self.assertEqual(items["Point on Curve"], "Sketcher_ConstrainPointOnObject")
        self.assertEqual(items["Collinear"], "NXStyle_SketchCollinear")
        self.assertEqual(items["Geometric Constraints"], "NXStyle_GeometricConstraints")

    def test_linear_dimension_offers_nx_methods(self):
        """NX's Linear Dimension measures Horizontal, Vertical or Point-to-Point: FreeCAD's DistanceX, DistanceY
        and Distance, in the Constraints group."""
        with open(RIBBON, encoding="utf-8") as fh:
            tab = json.load(fh)["tabs"][0]
        group = next(g for g in tab["groups"] if g["name"] == "Constraints")
        drop = next(i for i in group["items"] if i.get("dropdown") == "Linear Dimension")
        self.assertEqual([(s["label"], s["cmd"]) for s in drop["items"]],
                         [("Horizontal", "Sketcher_ConstrainDistanceX"), ("Vertical", "Sketcher_ConstrainDistanceY"),
                          ("Point-to-Point", "Sketcher_ConstrainDistance")])


class OnViewFields(unittest.TestCase):
    def test_fields_matched_to_the_cursor_whatever_their_order(self):
        # FreeCAD 1.1.4 listed Y before X in the self-test: (15.81, 49.83) shown for a cursor at (49.8, 15.8)
        self.assertEqual(core.xy_fields([15.81, 49.83], (49.8, 15.8)), (1, 0))
        self.assertEqual(core.xy_fields([49.83, 15.81], (49.8, 15.8)), (0, 1))

    def test_negative_coordinates_and_extra_fields(self):
        self.assertEqual(core.xy_fields([7.0, -120.0, -40.0], (-40.1, -119.9)), (2, 1))

    def test_too_few_fields(self):
        self.assertIsNone(core.xy_fields([3.0], (3.0, 0.0)))


class ConstraintVisibility(unittest.TestCase):
    def test_constraint_names(self):
        self.assertEqual(core.constraint_id("Constraint1"), 0)
        self.assertEqual(core.constraint_id("Constraint12"), 11)
        for sub in ("Constraint0", "Constraint", "Edge1", "Vertex2", "RootPoint", "", None, "MyConstraint1"):
            self.assertIsNone(core.constraint_id(sub), sub)

    def test_hide_moves_the_picked_shown_ones(self):
        hidden = [False, True, False, False]
        self.assertEqual(core.visibility_change("hide", [2, 0, 2, 1], hidden), ([0, 2], True))

    def test_show_moves_the_picked_hidden_ones(self):
        hidden = [False, True, False, True]
        self.assertEqual(core.visibility_change("show", [3, 0, 1], hidden), ([1, 3], False))

    def test_show_all_needs_no_pick(self):
        self.assertEqual(core.visibility_change("show_all", [], [True, False, True]), ([0, 2], False))

    def test_nothing_to_do_and_stale_picks(self):
        self.assertEqual(core.visibility_change("hide", [0, 7, -1], [True]), ([], True))
        self.assertEqual(core.visibility_change("show", [], [True]), ([], False))
        with self.assertRaises(ValueError):
            core.visibility_change("toggle", [0], [False])


def constraints(rows):
    """'Type First/FirstPos Second/SecondPos' rows, as tutorial AK records them -> constraint tuples."""
    out = []
    for row in rows:
        kind, a, b = row.split()
        (f, fp), (s, sp) = (map(int, x.split("/")) for x in (a, b))
        out.append((kind, f, fp, s, sp, core.GEO_UNDEF))
    return out


# tutorial AK, run C:\dev\nxruns\ak4 (FreeCAD 1.1.4): the constraints on the Ø3.50 circle (curve 3) before and
# after Quick Trim between the slot's sides (curves 8, 9). The top side (5) lost its Tangent, the bottom (7) not
AK4_BEFORE = ["Coincident 3/3 0/3", "Diameter 3/0 -2000/0", "PointOnObject 5/1 3/0", "Tangent 5/0 3/0",
              "PointOnObject 7/2 3/0", "Tangent 7/0 3/0", "PointOnObject 8/1 3/0", "PointOnObject 9/1 3/0"]
AK4_AFTER = ["Coincident 3/3 0/3", "Diameter 3/0 -2000/0", "PointOnObject 5/1 3/0", "PointOnObject 7/2 3/0",
             "Tangent 7/0 3/0", "Coincident 8/1 3/1", "Coincident 9/1 3/2"]


class TrimLosses(unittest.TestCase):
    def test_the_tangency_ak4_lost(self):
        lost = core.trim_losses(constraints(AK4_BEFORE), constraints(AK4_AFTER), 3, [3], {})
        self.assertEqual(lost, [("Tangent", 5, 0)])
        self.assertEqual(core.moved_constraint(*lost[0], 3), ("Tangent", 5, 3))

    def test_nothing_lost_when_the_trim_kept_both(self):
        # run ak8: the same trim kept both sides' Tangent
        after = constraints(AK4_AFTER) + constraints(["Tangent 5/0 3/0"])
        self.assertEqual(core.trim_losses(constraints(AK4_BEFORE), after, 3, [3], {}), [])

    def test_an_end_held_tangent_comes_back_on_its_point(self):
        before = constraints(["Tangent 1/1 0/0", "Tangent 3/2 0/0"])
        after = constraints(["Tangent 3/2 0/0"])
        lost = core.trim_losses(before, after, 0, [0], {})
        self.assertEqual(lost, [("Tangent", 1, 1)])
        self.assertEqual(core.moved_constraint(*lost[0], 0), ("Tangent", 1, 1, 0))

    def test_renumbered_curves_and_two_pieces(self):
        # a line cut into two: the other curves after it shift down by one deleted curve, the new piece is last
        before = constraints(["Perpendicular 6/0 2/0", "Tangent 2/0 7/0"])
        after = constraints(["Perpendicular 5/0 8/0"])
        lost = core.trim_losses(before, after, 2, [2, 8], {6: 5, 7: 6})
        self.assertEqual(lost, [("Tangent", 6, 0)])

    def test_a_cutting_curve_held_at_the_cut_is_kept_in_another_form(self):
        # FreeCAD turns an edge tangency with the cutting curve into one at the new end: not a loss
        before = constraints(["Tangent 4/0 1/0"])
        after = constraints(["Tangent 4/2 1/0"])
        self.assertEqual(core.trim_losses(before, after, 1, [1], {}), [])

    def test_left_alone(self):
        before = [("Tangent", 1, 0, 0, 0, 5),                     # tangent via a point: FreeCAD's own rule
                  ("Tangent", 1, 2, 0, 1, core.GEO_UNDEF),        # at an end of the trimmed curve: moves with it
                  ("Tangent", 1, 0, 2, 0, core.GEO_UNDEF),        # not on the trimmed curve
                  ("PointOnObject", 1, 1, 0, 0, core.GEO_UNDEF),  # not a tangency
                  ("Tangent", 4, 0, 0, 0, core.GEO_UNDEF)]        # its other curve was deleted
        self.assertEqual(core.trim_losses(before, [], 0, [0], {4: None}), [])

    def test_one_kept_constraint_answers_for_one_lost(self):
        before = constraints(["Tangent 1/0 0/0", "Tangent 1/0 0/0"])
        after = constraints(["Tangent 1/0 0/0"])
        self.assertEqual(core.trim_losses(before, after, 0, [0], {}), [("Tangent", 1, 0)])


class ExactDatum(unittest.TestCase):
    """FreeCAD writes typed on-view values through '%f'; the typed number comes back."""

    def test_angles_typed_in_degrees_come_back_in_radians(self):
        self.assertEqual(core.exact_datum(1.570796, [(63.5, False), (90.0, True)]), math.pi / 2)
        self.assertEqual(core.exact_datum(3.141593, [(180.0, True)]), math.pi)
        self.assertEqual(core.exact_datum(-1.308997, [(75.0, True)]), -math.radians(75))   # the sign FreeCAD wrote

    def test_lengths_with_more_than_six_decimals(self):
        typed = math.hypot(38.1, 63.5)
        self.assertEqual(core.exact_datum(core.printf_f(typed), [(typed, False)]), typed)
        self.assertEqual(core.exact_datum(-13.147908, [(-13.1479076, False)]), -13.1479076)

    def test_left_alone(self):
        self.assertIsNone(core.exact_datum(63.5, [(63.5, False)]))             # '%f' kept it exactly
        self.assertIsNone(core.exact_datum(1.570796, []))                      # nothing typed
        self.assertIsNone(core.exact_datum(1.5708, [(90.0, True)]))            # not the '%f' image of a typed value
        self.assertIsNone(core.exact_datum(1.570796, [(1.570796, False)]))     # typed as it stands

    def test_the_nearest_of_two_typed_values(self):
        self.assertEqual(core.exact_datum(2.0, [(2.0000004, False), (1.9999998, False)]), 1.9999998)


class MissingJoins(unittest.TestCase):
    """The smoke's two arcs and line: arc 0 from (0, 63.5) to (-63.5, 0), arc 1 on to (-38.1, 0), line 2 back."""

    POINTS = {(0, 1): (0.0, 63.5), (0, 2): (-63.5, 2.1e-5), (0, 3): (0.0, 0.0),
              (1, 1): (-63.5, 4.4e-6), (1, 2): (-38.1, 0.0), (1, 3): (-50.8, 0.0),
              (2, 1): (-38.1, 0.0), (2, 2): (0.0, 63.5)}

    def test_each_new_point_on_an_older_one(self):
        self.assertEqual(core.missing_joins(self.POINTS, {2}, [((1, 1), (0, 2))], 1e-4),
                         [((2, 1), (1, 2)), ((2, 2), (0, 1))])

    def test_points_already_joined_are_left_alone(self):
        links = [((1, 1), (0, 2)), ((2, 1), (1, 2)), ((2, 2), (0, 1))]
        self.assertEqual(core.missing_joins(self.POINTS, {2}, links, 1e-4), [])

    def test_joined_through_another_point(self):
        pts = {(0, 2): (5.0, 0.0), (1, 1): (5.0, 0.0), (2, 1): (5.0, 0.0)}
        self.assertEqual(core.missing_joins(pts, {2}, [((2, 1), (1, 1)), ((1, 1), (0, 2))], 1e-4), [])

    def test_tolerance(self):
        arcs = {k: v for k, v in self.POINTS.items() if k[0] != 2}             # before the line is drawn
        self.assertEqual(core.missing_joins(arcs, {1}, [], 1e-4), [((1, 1), (0, 2))])
        self.assertEqual(core.missing_joins(arcs, {1}, [], 1e-6), [])          # 2.1e-5 apart: '%f' angles

    def test_an_older_curve_first_and_one_join_per_place(self):
        pts = {(0, 2): (5.0, 0.0), (1, 1): (5.0, 0.0), (2, 1): (5.0, 0.0)}
        # curves 1 and 2 are new: both go on the old curve's point, not on each other as well
        self.assertEqual(core.missing_joins(pts, {1, 2}, [], 1e-4), [((1, 1), (0, 2)), ((2, 1), (0, 2))])

    def test_a_curve_is_not_joined_to_itself(self):
        self.assertEqual(core.missing_joins({(0, 1): (0.0, 0.0), (0, 2): (0.0, 0.0)}, {0}, [], 1e-4), [])


if __name__ == "__main__":
    unittest.main()
