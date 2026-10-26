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


if __name__ == "__main__":
    unittest.main()
