# SPDX-License-Identifier: LGPL-2.1-or-later
"""Measurement capability (msa.py) and the uncertainty columns of the inspection plan; no FreeCAD needed."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import msa, pmi  # noqa: E402

# the ranges of Drake's worked example (ch. 25): ten parts measured twice, position tolerance 0.2 mm
RANGES = [0.02, 0.04, 0.04, 0.06, 0.00, 0.04, 0.04, 0.02, 0.02, 0.04]
TRIALS = [[0.10, 0.10 + r] for r in RANGES]


class Repeatability(unittest.TestCase):
    def test_drakes_example_three_sigma(self):
        r = msa.repeatability(TRIALS, 0.2, spread=3.0)
        self.assertAlmostEqual(r["r_bar"], 0.032)
        self.assertAlmostEqual(r["sigma"], 0.032 / 1.128)
        self.assertAlmostEqual(round(r["sigma"], 4), 0.0284)
        self.assertAlmostEqual(round(r["percent"], 1), 42.6)
        self.assertTrue(r["verdict"].startswith("unacceptable"))

    def test_aiag_six_sigma_doubles_it(self):
        self.assertAlmostEqual(msa.repeatability(TRIALS, 0.2)["percent"],
                               2 * msa.repeatability(TRIALS, 0.2, spread=3.0)["percent"])

    def test_verdict_bands(self):
        self.assertEqual(msa.verdict(9.9), "acceptable")
        self.assertTrue(msa.verdict(10).startswith("marginal"))
        self.assertTrue(msa.verdict(30).startswith("marginal"))
        self.assertTrue(msa.verdict(30.1).startswith("unacceptable"))

    def test_d2_for_three_trials(self):
        r = msa.repeatability([[1.0, 1.003, 1.001]] * 5, 0.1)
        self.assertAlmostEqual(r["sigma"], 0.003 / 1.693)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            msa.repeatability([[1, 2], [1, 2, 3]], 0.1)
        with self.assertRaises(ValueError):
            msa.repeatability([[1]], 0.1)
        with self.assertRaises(ValueError):
            msa.repeatability(TRIALS, 0.0)


class DecisionRule(unittest.TestCase):
    def test_tur(self):
        self.assertAlmostEqual(msa.tur(9.98, 10.02, 0.005), 4.0)
        self.assertEqual(msa.tur_verdict(4.0), "meets 4:1")
        self.assertEqual(msa.tur_verdict(10.0), "meets 10:1")
        self.assertTrue(msa.tur_verdict(3.9).startswith("below"))

    def test_ratio_text_rounds_halves_up_on_both_sides_of_the_float(self):
        self.assertEqual(msa.ratio_text(0.021 / 0.004), "5.3:1")
        self.assertEqual(msa.ratio_text(0.01 / 0.008), "1.3:1")
        self.assertEqual(msa.ratio_text(4.0), "4.0:1")

    def test_acceptance_two_sided_and_one_sided(self):
        self.assertEqual(tuple(round(x, 9) for x in msa.acceptance(9.98, 10.02, 0.005)), (9.985, 10.015))
        lo, hi = msa.acceptance(0.0, 0.05, 0.005, one_sided=True)
        self.assertEqual((lo, round(hi, 6)), (0.0, 0.045))
        self.assertIsNone(msa.acceptance(9.99, 10.01, 0.01))

    def test_decide(self):
        self.assertEqual(msa.decide(10.0, 9.98, 10.02, 0.005), "conforms")
        self.assertEqual(msa.decide(10.018, 9.98, 10.02, 0.005), "undecided")
        self.assertEqual(msa.decide(10.03, 9.98, 10.02, 0.005), "does not conform")


class PlanColumns(unittest.TestCase):
    def test_dimension_and_frame_rows(self):
        anns = [{"id": "D", "kind": "dimension", "dim_type": "diameter", "nominal": 10.0, "plus": 0.02, "minus": 0.02,
                 "feature": "P:Face1", "feature_type": "hole", "uncertainty": 0.005},
                {"id": "F", "kind": "fcf", "characteristic": "flatness", "tolerance": 0.05, "feature": "P:Face2",
                 "feature_type": "plane", "uncertainty": 0.005},
                {"id": "G", "kind": "fcf", "characteristic": "flatness", "tolerance": 0.01, "feature": "P:Face3",
                 "feature_type": "plane", "uncertainty": 0.012}]
        rows = {r["id"]: r for r in pmi.inspection_plan(pmi.number(anns))}
        self.assertEqual(rows["D"]["tur"], 4.0)
        self.assertEqual((round(rows["D"]["accept_lower"], 6), round(rows["D"]["accept_upper"], 6)), (9.985, 10.015))
        self.assertIn("ISO 14253-1", rows["D"]["note"])
        self.assertAlmostEqual(rows["F"]["accept_upper"], 0.045)
        self.assertEqual(rows["F"]["accept_lower"], 0.0)
        self.assertIn("cannot prove conformance", rows["G"]["note"])

    def test_no_uncertainty_no_columns(self):
        a = {"id": "D", "kind": "dimension", "dim_type": "diameter", "nominal": 10.0, "plus": 0.02, "minus": 0.02,
             "feature": "P:Face1", "feature_type": "hole"}
        r = pmi.inspection_plan(pmi.number([a]))[0]
        self.assertNotIn("tur", r)


if __name__ == "__main__":
    unittest.main()
