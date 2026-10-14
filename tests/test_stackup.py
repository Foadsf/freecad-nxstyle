# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tolerance stack-up engine (no FreeCAD needed), checked against the books' worked examples."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))
from nxstyle import stackup as su  # noqa: E402
from nxstyle.stackup import Contributor as C  # noqa: E402


def pin():
    """Fischer, Mechanical Tolerance Stackup and Analysis, Example 7.1 / 8.1: the groove width
    of a pin, from A (one side of the groove) to B (the other)."""
    return [C("Groove to head", 30, 0.2, direction=-1), C("Overall length", 45, 0.5, direction=+1),
            C("Tip to groove", 13.2, 0.5, direction=-1)]


class FischerPin(unittest.TestCase):
    def setUp(self):
        self.r = su.analyse(pin(), lsl=0.5)

    def test_nominal_gap(self):
        self.assertAlmostEqual(self.r.nominal, 1.8, places=9)

    def test_worst_case_is_0_6_to_3_0(self):
        lo, hi = self.r.limits["worst case"]
        self.assertAlmostEqual(self.r.t_wc, 1.2, places=9)
        self.assertAlmostEqual(lo, 0.6, places=9)
        self.assertAlmostEqual(hi, 3.0, places=9)

    def test_rss_is_0_74_and_adjusted_1_1(self):
        # the book rounds: RSS +/-0.74, adjusted +/-1.1, so 0.7 to 2.9
        self.assertAlmostEqual(self.r.t_rss, 0.7348, places=4)
        adj = self.r.methods["adjusted RSS (1.5 x RSS)"]
        self.assertAlmostEqual(adj, 1.1023, places=4)
        lo, hi = self.r.limits["adjusted RSS (1.5 x RSS)"]
        self.assertAlmostEqual(round(lo, 1), 0.7)
        self.assertAlmostEqual(round(hi, 1), 2.9)

    def test_percent_contribution(self):
        self.assertAlmostEqual(sum(self.r.wc_share), 1.0)
        self.assertAlmostEqual(self.r.rss_share[0], 0.04 / 0.54)

    def test_requirement_verdicts(self):
        self.assertEqual(self.r.verdicts["worst case"], "OK")
        r = su.analyse(pin(), lsl=0.65)
        self.assertEqual(r.verdicts["worst case"], "FAILS")
        self.assertEqual(r.verdicts["adjusted RSS (1.5 x RSS)"], "OK")

    def test_report_has_the_numbers_and_the_few_contributors_note(self):
        text = su.report(pin(), self.r, "Pin groove")
        self.assertIn("1.8000", text)
        self.assertIn("0.6000", text)
        self.assertIn("3.0000", text)
        self.assertIn("fewer than four contributors", text)


class FischerGroundPlate(unittest.TestCase):
    """Fischer fig. 14.11: ground plate to enclosure, option 1 (13 lines, several of them zero)."""

    def test_results(self):
        tols = [0.5, 0.29, 0.0, 0.2, 0.0, 0.0, 0.665, 0.225, 0.1, 0.0, 0.0, 0.5, 0.15]
        cs = [C(f"line {i + 1}", 0.0, t) for i, t in enumerate(tols)]
        cs[2] = C("Edge of enclosure - datum B", 8.5, 0.0, direction=+1)
        cs[10] = C("Datum B - edge of ground plate", 6.0, 0.0, direction=-1)
        r = su.analyse(cs, lsl=0.0)
        self.assertAlmostEqual(r.mean, 2.5)
        self.assertAlmostEqual(r.t_wc, 2.63)
        self.assertAlmostEqual(r.limits["worst case"][0], -0.13)
        self.assertAlmostEqual(r.t_rss, 1.0721, places=4)
        self.assertAlmostEqual(r.methods["adjusted RSS (1.5 x RSS)"], 1.6082, places=4)
        self.assertEqual(r.verdicts["worst case"], "FAILS")       # the plate can touch the wall
        self.assertEqual(r.verdicts["RSS"], "OK")
        self.assertEqual(r.active, 8)


class Conversions(unittest.TestCase):
    def test_unequal_bilateral_fischer_example_4_2(self):
        c = C("8.50 +.25/-.10", 8.50, 0.25, 0.10)
        self.assertAlmostEqual(c.tolerance, 0.175)
        self.assertAlmostEqual(c.mean, 8.575)
        self.assertAlmostEqual(c.shift, 0.075)

    def test_mean_moves_the_result_not_the_nominal(self):
        r = su.analyse([C("a", 10, 0.3, 0.1), C("b", 4, 0.1, direction=-1)])
        self.assertAlmostEqual(r.nominal, 6.0)
        self.assertAlmostEqual(r.mean, 6.1)

    def test_geometric_and_bonus(self):
        # Fischer: hole 5.7 +/-0.3 with position dia 2 at MMC: +/-1 and a bonus of +/-0.3
        self.assertAlmostEqual(su.geometric("pos", 2.0).tolerance, 1.0)
        self.assertAlmostEqual(su.bonus("bonus", 5.4, 6.0).tolerance, 0.3)

    def test_assembly_shift(self):
        # M8 (MMC 8.0) in a 10 +/-0.6 clearance hole: +/-1.3 for each part that floats
        self.assertAlmostEqual(su.assembly_shift("shift", 10.6, 8.0).tolerance, 1.3)
        with self.assertRaises(ValueError):
            su.assembly_shift("no clearance", 7.9, 8.0)

    def test_flatness_is_a_zone_shift(self):
        c = su.flatness("flat", 1.0)
        self.assertEqual(c.direction, -1)
        self.assertAlmostEqual(c.mean, 0.5)
        self.assertAlmostEqual(c.tolerance, 0.5)


class FastenersAndBoundaries(unittest.TestCase):
    """Cogorno ch. 8 and ch. 3 / 7 (inches)."""

    def test_floating_fastener(self):
        self.assertAlmostEqual(su.floating_fastener(0.250, 0.020), 0.270)
        self.assertAlmostEqual(su.floating_fastener(0.250, hole_mmc=0.270), 0.020)

    def test_fixed_fastener(self):
        self.assertAlmostEqual(su.fixed_fastener(0.250, 0.024, 0.0), 0.274)
        self.assertAlmostEqual(su.fixed_fastener(0.250, t1=0.024, hole_mmc=0.274), 0.0)
        a, b = su.fixed_fastener(0.250, hole_mmc=0.274)
        self.assertAlmostEqual(a, 0.012)

    def test_virtual_and_resultant_condition(self):
        self.assertAlmostEqual(su.virtual_condition(0.520, 0.020, internal=True), 0.500)
        self.assertAlmostEqual(su.resultant_condition(0.520, 0.560, 0.020, internal=True), 0.620)
        self.assertAlmostEqual(su.virtual_condition(1.010, 0.010, internal=False), 1.020)
        self.assertAlmostEqual(su.resultant_condition(1.010, 1.000, 0.010, internal=False), 0.980)

    def test_bonus_at_actual_size(self):
        self.assertAlmostEqual(su.total_position(0.020, 0.270, 0.285), 0.035)


class Statistics(unittest.TestCase):
    def test_drake_mrss_factor(self):
        # Drake, Dimensioning and Tolerancing Handbook ch. 9: t_wc .0955, t_rss .0381, n 11 -> 1.3252
        self.assertAlmostEqual(su.mrss_factor(0.0955, 0.0381, 11), 1.3252, places=4)
        self.assertEqual(su.mrss_factor(0.5, 0.5, 1), 1.0)

    def test_mrss_with_equal_tolerances_is_1_5(self):
        self.assertAlmostEqual(su.mrss_factor(4 * 0.1, 2 * 0.1, 4), 1.5)

    def test_monte_carlo_matches_the_rss_sigma_and_is_repeatable(self):
        cs = [C(f"d{i}", 10, 0.3) for i in range(6)]
        r1 = su.analyse(cs, samples=40000, seed=7)
        r2 = su.analyse(cs, samples=40000, seed=7)
        self.assertEqual(r1.mc, r2.mc)
        self.assertAlmostEqual(r1.mc["mean"], 60.0, delta=0.01)
        self.assertAlmostEqual(r1.mc["sd"], r1.t_rss / 3, delta=0.01)

    def test_predicted_ppm_at_3_sigma(self):
        # a requirement exactly at the RSS limits is +/-3 sigma: 2700 ppm out of spec
        cs = pin()
        r0 = su.analyse(cs)
        lo, hi = r0.limits["RSS"]
        r = su.analyse(cs, lsl=lo, usl=hi)
        self.assertAlmostEqual(r.stat["ppm"], 2699.8, delta=0.5)
        self.assertAlmostEqual(r.stat["cp"], 1.0)

    def test_uniform_distribution_stays_inside_its_limits(self):
        r = su.analyse([C("u", 5, 0.1, distribution="uniform")], samples=2000)
        self.assertGreaterEqual(r.mc["min"], 4.9)
        self.assertLessEqual(r.mc["max"], 5.1)

    def test_empty_stack_refused(self):
        with self.assertRaises(ValueError):
            su.analyse([])

    def test_round_trip(self):
        c = C("x", 1, 0.1, 0.2, -1, "profile", "Plate", "profile 0.3", "uniform")
        self.assertEqual(C.from_dict(c.to_dict()).to_dict(), c.to_dict())


if __name__ == "__main__":
    unittest.main()
