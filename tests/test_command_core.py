# SPDX-License-Identifier: LGPL-2.1-or-later
"""The command controller's decisions: typed lengths and Extrude's Boolean options (no FreeCAD needed)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))
from nxstyle import command_core as cc  # noqa: E402


class Lengths(unittest.TestCase):
    def test_units(self):
        self.assertAlmostEqual(cc.parse_length("25"), 25.0)
        self.assertAlmostEqual(cc.parse_length("25 mm"), 25.0)
        self.assertAlmostEqual(cc.parse_length("2.5 cm"), 25.0)
        self.assertAlmostEqual(cc.parse_length("1 in"), 25.4)
        self.assertAlmostEqual(cc.parse_length('0.5"'), 12.7)
        self.assertAlmostEqual(cc.parse_length("1 ft"), 304.8)
        self.assertAlmostEqual(cc.parse_length("-3 mm"), -3.0)
        self.assertAlmostEqual(cc.parse_length("−3 mm"), -3.0)      # the minus sign FreeCAD shows
        self.assertAlmostEqual(cc.parse_length("1 MM"), 1.0)
        self.assertAlmostEqual(cc.parse_length("2 um"), 0.002)

    def test_decimal_separator_of_the_field(self):
        self.assertAlmostEqual(cc.parse_length("3,175", decimal=","), 3.175)
        with self.assertRaises(cc.UnitError):
            cc.parse_length("3.175", decimal=",")          # Qt would read 3175 here: refused, not guessed
        with self.assertRaises(cc.UnitError):
            cc.parse_length("3,175", decimal=".")

    def test_not_lengths(self):
        for text in ("", "mm", "abc", "5 kg", "10 deg", "=Expressions.L", "2*3", "1.2.3", "."):
            with self.subTest(text=text), self.assertRaises(cc.UnitError):
                cc.parse_length(text)

    def test_read_back_catches_a_misread_decimal(self):
        msg = cc.read_back_issue("3.175", 3175.0, decimal=",")
        self.assertIn("3175", msg)
        self.assertIn("3,175", msg)
        # the field took '.' as the decimal point after all: nothing to report
        self.assertIsNone(cc.read_back_issue("3.175", 3.175, decimal=","))
        self.assertIsNone(cc.read_back_issue("3,175", 3.175, decimal=","))
        self.assertIsNone(cc.read_back_issue("25.4 mm", 25.4))
        self.assertIsNone(cc.read_back_issue("1 in", 25.4))
        self.assertIn("read 30", cc.read_back_issue("25", 30.0))
        self.assertIsNone(cc.read_back_issue("=L", 12.0))            # an expression: not compared


class ExtrudeBoolean(unittest.TestCase):
    def test_inferred(self):
        self.assertEqual(cc.infer_boolean(None, True, True), "unite")
        self.assertEqual(cc.infer_boolean(None, True, False), "new_body")
        self.assertEqual(cc.infer_boolean(None, False, False), "new_body")
        self.assertEqual(cc.infer_boolean("subtract", True, True), "subtract")

    def test_plans(self):
        self.assertEqual(cc.plan_extrude("new_body", True, False), {"feature": "PartDesign::Pad", "body": "sketch"})
        self.assertEqual(cc.plan_extrude("new_body", True, True), {"feature": "PartDesign::Pad", "body": "new"})
        self.assertEqual(cc.plan_extrude("new_body", False, False), {"feature": "PartDesign::Pad", "body": "new"})
        self.assertEqual(cc.plan_extrude("unite", True, True), {"feature": "PartDesign::Pad", "body": "sketch"})
        self.assertEqual(cc.plan_extrude("subtract", True, True),
                         {"feature": "PartDesign::Pocket", "body": "sketch"})

    def test_refusals_say_why(self):
        with self.assertRaisesRegex(cc.CommandError, "Intersect"):
            cc.plan_extrude("intersect", True, True)
        with self.assertRaisesRegex(cc.CommandError, "Body001.*choose None"):
            cc.plan_extrude("unite", True, False, "Body001")
        with self.assertRaisesRegex(cc.CommandError, "not in a Body"):
            cc.plan_extrude("subtract", False, False)
        with self.assertRaises(cc.CommandError):
            cc.plan_extrude("difference", True, True)

    def test_every_boolean_is_planned_or_refused(self):
        """No Boolean falls through to an approximation: each one builds, or names its reason."""
        for key, _ in cc.BOOLEANS:
            with self.subTest(key=key):
                if key in cc.UNSUPPORTED:
                    with self.assertRaises(cc.CommandError):
                        cc.plan_extrude(key, True, True)
                else:
                    self.assertIn(cc.plan_extrude(key, True, True)["feature"], ("PartDesign::Pad", "PartDesign::Pocket"))

    def test_mode_of_existing_features(self):
        self.assertEqual(cc.mode_of("PartDesign::Pocket", True), "subtract")
        self.assertEqual(cc.mode_of("PartDesign::Pad", True), "unite")
        self.assertEqual(cc.mode_of("PartDesign::Pad", False), "new_body")

    def test_result_warnings(self):
        self.assertIsNone(cc.result_warning("unite", 100.0, 150.0))
        self.assertIn("adds nothing", cc.result_warning("unite", 100.0, 100.0))
        self.assertIsNone(cc.result_warning("subtract", 100.0, 80.0))
        self.assertIn("removes nothing", cc.result_warning("subtract", 100.0, 100.0))
        self.assertIsNone(cc.result_warning("new_body", 0.0, 0.0))

    def test_unsupported_options_are_listed(self):
        names = cc.unsupported_summary()
        for option in ("Intersect", "Offset", "Until Extended"):
            self.assertIn(option, names)
        self.assertTrue(all(status in ("supported", "not supported", "sketch's Body only")
                            for _, status, _ in cc.EXTRUDE_OPTIONS))
        tip = cc.options_tooltip()
        self.assertTrue(all(name in tip for name, _, _ in cc.EXTRUDE_OPTIONS))
        for word in ("Intersect", "Offset", "Until Extended", "Sheet"):      # the panel's one-line note
            self.assertIn(word, cc.SHORT_NOTE)


class RevolveOptions(unittest.TestCase):
    def test_plans(self):
        self.assertEqual(cc.plan_revolve("new_body", True, False),
                         {"feature": "PartDesign::Revolution", "body": "sketch"})
        self.assertEqual(cc.plan_revolve("new_body", True, True), {"feature": "PartDesign::Revolution", "body": "new"})
        self.assertEqual(cc.plan_revolve("unite", True, True), {"feature": "PartDesign::Revolution", "body": "sketch"})
        self.assertEqual(cc.plan_revolve("subtract", True, True), {"feature": "PartDesign::Groove", "body": "sketch"})
        with self.assertRaisesRegex(cc.CommandError, "Intersect"):
            cc.plan_revolve("intersect", True, True)
        with self.assertRaisesRegex(cc.CommandError, "choose None"):
            cc.plan_revolve("subtract", True, False)
        self.assertEqual(cc.mode_of("PartDesign::Groove", True), "subtract")
        self.assertEqual(cc.mode_of("PartDesign::Revolution", False), "new_body")

    def test_axis_through_the_origin_is_the_bodys_axis(self):
        self.assertEqual(cc.revolve_axis("XC"), {"kind": "origin", "axis": "X", "reversed": False})
        self.assertEqual(cc.revolve_axis("-ZC", (0, 0, 0)), {"kind": "origin", "axis": "Z", "reversed": True})
        self.assertEqual(cc.revolve_axis("sketch_h")["sub"], "H_Axis")
        self.assertEqual(cc.revolve_axis("line:Edge7"), {"kind": "sketch", "sub": "Edge7", "reversed": False})

    def test_axis_elsewhere_is_a_datum_line(self):
        ref = cc.revolve_axis("-YC", (10.0, 0.0, 5.0))
        self.assertEqual(ref["kind"], "datum")
        self.assertEqual(ref["point"], (10.0, 0.0, 5.0))
        self.assertEqual(ref["direction"], (-0.0, -1.0, -0.0))
        self.assertFalse(ref["reversed"])                  # the direction carries the reversal
        with self.assertRaises(cc.CommandError):
            cc.revolve_axis("WC")

    def test_vector_of_an_existing_axis(self):
        self.assertEqual(cc.vector_of("origin", "X_Axis", False), "XC")
        self.assertEqual(cc.vector_of("origin", "Y_Axis", True), "-YC")
        self.assertEqual(cc.vector_of("sketch", "V_Axis", False), "sketch_v")
        self.assertEqual(cc.vector_of("sketch", "Edge3", False), "line:Edge3")
        self.assertIsNone(cc.vector_of("other", "", False))
        # each vector reads back as itself
        for key, _l, _a, _r in cc.VECTORS:
            ref = cc.revolve_axis(key)
            self.assertEqual(cc.vector_of("origin", ref["axis"] + "_Axis", ref["reversed"]), key)

    def test_limits(self):
        # the book: Start 0, End 180
        self.assertEqual(cc.revolve_limits(0, 180), {"Type": "Angle", "Angle": 180, "Angle2": 0.0, "flip": False})
        self.assertEqual(cc.revolve_limits(-90, 0), {"Type": "Angle", "Angle": 90, "Angle2": 0.0, "flip": True})
        self.assertEqual(cc.revolve_limits(0, -90), {"Type": "Angle", "Angle": 90, "Angle2": 0.0, "flip": True})
        self.assertEqual(cc.revolve_limits(-30, 120), {"Type": "TwoAngles", "Angle": 120, "Angle2": 30, "flip": False})
        self.assertEqual(cc.revolve_limits(0, 360)["Angle"], 360)

    def test_limits_refused_say_why(self):
        with self.assertRaisesRegex(cc.CommandError, "equal"):
            cc.revolve_limits(45, 45)
        with self.assertRaisesRegex(cc.CommandError, "at most 360"):
            cc.revolve_limits(-200, 200)
        with self.assertRaisesRegex(cc.CommandError, "same side"):
            cc.revolve_limits(30, 120)
        with self.assertRaisesRegex(cc.CommandError, "same side"):
            cc.revolve_limits(-120, -30)

    def test_limits_read_back(self):
        """What the box shows for a Revolution is what gives that Revolution again."""
        for start, end in ((0, 180), (0, -90), (-30, 120), (0, 360)):
            lim = cc.revolve_limits(start, end)
            shown = cc.limits_of(lim["Type"], lim["Angle"], lim["Angle2"], lim["flip"])
            again = cc.revolve_limits(*shown)
            self.assertEqual((again["Type"], again["Angle"], again["Angle2"], again["flip"]),
                             (lim["Type"], lim["Angle"], lim["Angle2"], lim["flip"]))
        self.assertEqual(cc.limits_of("Angle", 90, 0, midplane=True), (-45, 45))
        self.assertIsNone(cc.limits_of("UpToFace", 0, 0))

    def test_options_are_listed(self):
        tip = cc.options_tooltip(cc.REVOLVE_OPTIONS, "")
        self.assertTrue(all(name in tip for name, _, _ in cc.REVOLVE_OPTIONS))
        self.assertTrue(all(status in ("supported", "not supported") for _, status, _ in cc.REVOLVE_OPTIONS))
        for word in ("Intersect", "Offset", "Sheet"):
            self.assertIn(word, cc.REVOLVE_NOTE)


# The impeller casing sketch (book 3.5.2 / 4.4) reduced to its topology: vertex keys at the curve ends. The casing
# wall is the inner chain (i1..i4), the copy above it (u1..u4) and the two ends; the edge (lip) shares the inner
# chain; the flange shares the lip's right end and overlaps the inner and the lower Line 2 (their own ends differ).
CASING = {
    "i1": ("L", "A"), "i2": ("A", "B"), "i3": ("B", "C"), "i4": ("C", "R"),
    "u1": ("Lu", "Au"), "u2": ("Au", "Bu"), "u3": ("Bu", "Cu"), "u4": ("Cu", "Ru"),
    "d1": ("Ld", "Ad"), "d2": ("Ad", "Bd"), "d3": ("Bd", "Cd"), "d4": ("Cd", "Rd"),
    "wl": ("L", "Lu"), "wr": ("R", "Ru"), "el": ("L", "Ld"), "er": ("R", "Rd"),
    "fv": ("F", "Fd"), "ft": ("F", "R"), "fb": ("Fd", "Rd"),
}
WALL = ["i1", "i2", "i3", "i4", "u1", "u2", "u3", "u4", "wl", "wr"]
LIP = ["i1", "i2", "i3", "i4", "d1", "d2", "d3", "d4", "el", "er"]
FLANGE = ["fv", "ft", "fb", "er"]


class Sections(unittest.TestCase):
    def test_picks_make_one_sketchs_section(self):
        self.assertEqual(cc.section_from_picks([("Sketch", "Edge3"), ("Sketch", "Edge10"), ("Sketch", "Edge3")]),
                         ("Sketch", ["Edge3", "Edge10"], []))
        # a whole sketch among the picks: the whole sketch, as before
        self.assertEqual(cc.section_from_picks([("Sketch", "Edge3"), ("Sketch", "")]), ("Sketch", None, []))
        # a second sketch is refused: FreeCAD's Profile is one object
        self.assertEqual(cc.section_from_picks([("Sketch", "Edge1"), ("Sketch001", "Edge2")]),
                         ("Sketch", ["Edge1"], [("Sketch001", "Edge2")]))
        self.assertEqual(cc.section_from_picks([("Sketch", "Vertex2")]), ("Sketch", None, [("Sketch", "Vertex2")]))
        self.assertEqual(cc.section_from_picks([]), (None, None, []))

    def test_adding_and_removing(self):
        self.assertEqual(cc.add_to_section([], ["Edge2"]), ["Edge2"])
        self.assertEqual(cc.add_to_section(["Edge9", "Edge2"], ["Edge10", "Edge2"]), ["Edge2", "Edge9", "Edge10"])
        # curves picked into a whole-sketch section start a section of just those curves
        self.assertEqual(cc.add_to_section(None, ["Edge4"]), ["Edge4"])
        self.assertEqual(cc.remove_from_section(["Edge1", "Edge4"], ["Edge4"]), ["Edge1"])
        self.assertIsNone(cc.remove_from_section(None, ["Edge4"]))

    def test_the_casing_loops_are_closed(self):
        for loop in (WALL, LIP, FLANGE):
            self.assertEqual(cc.section_gaps(CASING, loop), ([], []), loop)
            self.assertEqual(cc.section_problem(CASING, loop), "")

    def test_what_is_not_a_profile_says_why(self):
        self.assertIn("open at 2 points", cc.section_problem(CASING, WALL[:-1]))
        # the whole casing: three curves meet at the wall's and the edge's ends
        self.assertIn("branches", cc.section_problem(CASING, sorted(CASING)))
        self.assertIn("empty", cc.section_problem(CASING, []))
        self.assertIn("Edge99 not found", cc.section_problem(CASING, ["i1", "Edge99"]))
        self.assertEqual(cc.section_problem(CASING, None), "")          # a whole sketch: FreeCAD decides
        self.assertEqual(cc.section_gaps({"c": ("P", "P")}, ["c"]), ([], []))   # a circle closes itself

    def test_geometry_to_profile_edges(self):
        """Outside sketch edit a curve's EdgeN follows the sketch shape, not the geometry index (measured on the
        casing sketch: geometry 0 is Edge2, geometry 12 is Edge1), and a line may run the other way."""
        geometry = {0: ((0, 0, 0), (10, 0, 0), (5, 0, 0)),
                    1: ((10, 0, 0), (10, 5, 0), (10, 2.5, 0)),
                    2: ((10, 0, 0), (15, 0, 0), (12.5, 0, 0)),      # overlaps nothing, shares an end
                    3: ((5, 0, 0), (10, 0, 0), (7.5, 0, 0))}        # overlaps the right half of geometry 0
        edges = {"Edge1": ((10, 5, 0), (10, 0, 0), (10, 2.5, 0)),   # reversed
                 "Edge2": ((0, 0, 0), (10, 0, 0), (5, 0, 0)),
                 "Edge3": ((5, 0, 0), (10, 0, 0), (7.5, 0, 0)),
                 "Edge4": ((10, 0, 0), (15, 0, 0), (12.5, 0, 0))}
        self.assertEqual(cc.match_edges(geometry, edges), {0: "Edge2", 1: "Edge1", 2: "Edge4", 3: "Edge3"})
        self.assertEqual(cc.match_edges({5: ((1, 1, 1), (2, 2, 2), (1.5, 1.5, 1.5))}, edges), {})

    def test_edges_sort_by_number(self):
        self.assertEqual(cc.sort_edges(["Edge10", "Edge9", "Edge1", "Edge9"]), ["Edge1", "Edge9", "Edge10"])


class UndoSteps(unittest.TestCase):
    def test_list_with_room(self):
        self.assertEqual(cc.undo_steps_added([], ["Extrude"]), 1)
        self.assertEqual(cc.undo_steps_added(["Sketch", "Body"], ["Extrude", "Sketch", "Body"]), 1)
        self.assertEqual(cc.undo_steps_added(["Body"], ["Extrude", "Sketch", "Body"]), 2)
        self.assertEqual(cc.undo_steps_added(["Sketch", "Body"], ["Sketch", "Body"]), 0)

    def test_full_list_drops_its_oldest_step(self):
        # measured in tutorial AF: the count stayed the same, so a count difference said 0 steps
        before = [f"Edit {i}" for i in range(20)]
        self.assertEqual(cc.undo_steps_added(before, ["Extrude"] + before[:-1]), 1)
        self.assertEqual(cc.undo_steps_added(before, ["Extrude", "Sketch"] + before[:-2]), 2)
        self.assertEqual(cc.undo_steps_added(before, before), 0)

    def test_list_fills_up_during_the_command(self):
        before = [f"Edit {i}" for i in range(19)]
        self.assertEqual(cc.undo_steps_added(before, ["Extrude", "Sketch"] + before[:-1]), 2)

    def test_lists_that_do_not_line_up(self):
        self.assertIsNone(cc.undo_steps_added(["Extrude", "Body"], ["Body"]))          # an undo
        self.assertIsNone(cc.undo_steps_added(["A", "B", "C"], ["X", "Y", "Z"]))      # replaced, not added


if __name__ == "__main__":
    unittest.main()
