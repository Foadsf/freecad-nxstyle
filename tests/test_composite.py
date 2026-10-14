# SPDX-License-Identifier: LGPL-2.1-or-later
"""Composite position (two-row frames) in pmi.py and gdt.py, and the pattern evaluation of
position_eval.py; no FreeCAD needed."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import gdt, pmi, position_eval as pe  # noqa: E402

HOLES = {"id": "D1", "kind": "dimension", "dim_type": "diameter", "nominal": 6.35, "plus": 0.25, "minus": 0.0,
         "feature": "Plate:Face5 | Plate:Face6 | Plate:Face7 | Plate:Face8", "feature_type": "hole", "count": 4}
DATUMS = [{"id": f"P{x}", "kind": "datum", "letter": x, "feature": f"Plate:Face{i}", "feature_type": "plane"}
          for i, x in enumerate("ABC", 1)]


def frame(**kw):
    a = {"id": "F1", "kind": "fcf", "characteristic": "position", "tolerance": 0.25, "diameter": True,
         "modifier": "MMC", "datums": [["A", ""], ["B", ""], ["C", ""]], "feature": HOLES["feature"],
         "feature_type": "hole", "frame": "composite",
         "lower": {"tolerance": 0.05, "modifier": "MMC", "datums": [["A", ""]]}}
    a.update(kw)
    return a


def errors(anns, std="ASME"):
    return [m for s, _, m in pmi.check(anns, std) if s == "error"]


class Text(unittest.TestCase):
    def test_composite_callout_has_the_symbol_once(self):
        self.assertEqual(pmi.text(frame()), "position | Ø0.250 (M) | A | B | C / Ø0.050 (M) | A")

    def test_stacked_frames_repeat_the_symbol(self):
        low = {"tolerance": 0.05, "modifier": "MMC", "datums": [["A", ""], ["B", ""]]}
        t = pmi.text(frame(frame="single", lower=low))
        self.assertEqual(t, "position | Ø0.250 (M) | A | B | C / position | Ø0.050 (M) | A | B")

    def test_no_lower_tolerance_is_a_single_frame(self):
        a = frame(lower={"tolerance": 0.0, "modifier": "", "datums": []})
        self.assertIsNone(pmi.lower(a))
        self.assertEqual(pmi.text(a), "position | Ø0.250 (M) | A | B | C")

    def test_svg_is_two_rows_and_one_symbol_cell(self):
        rows = [("0.25", True, "MMC", [("A", ""), ("B", ""), ("C", "")]), ("0.05", True, "MMC", [("A", "")])]
        svg, w, h = gdt.stacked_frame("position", rows, composite=True)
        self.assertAlmostEqual(h, 2 * gdt.H)
        self.assertEqual(svg.count(gdt.SYMBOLS["position"]), 3)      # one per row, blanked, and the shared one
        self.assertIn('freecad:editable="tolerance2"', svg)
        self.assertIn('freecad:editable="row2_datum1"', svg)
        single = gdt.feature_control_frame("position", "0.25", True, "MMC", [("A", ""), ("B", ""), ("C", "")])[1]
        self.assertAlmostEqual(w, single)                              # the upper row is the wider


class Checks(unittest.TestCase):
    def test_a_good_composite_frame_has_no_errors(self):
        self.assertEqual(errors(DATUMS + [HOLES, frame()]), [])

    def test_lower_row_must_be_tighter(self):
        a = frame(lower={"tolerance": 0.3, "modifier": "MMC", "datums": [["A", ""]]})
        self.assertTrue(any("must be tighter" in e for e in errors(DATUMS + [HOLES, a])))

    def test_composite_lower_row_repeats_the_upper_datums_in_order(self):
        for ds in ([["B", ""]], [["A", ""], ["C", ""]], [["D", ""]]):
            a = frame(lower={"tolerance": 0.05, "modifier": "MMC", "datums": ds})
            self.assertTrue(any("only repeat" in e for e in errors(DATUMS + [HOLES, a])), ds)

    def test_stacked_lower_row_may_choose_its_datums(self):
        a = frame(frame="single", lower={"tolerance": 0.05, "modifier": "MMC", "datums": [["A", ""], ["C", ""]]})
        self.assertEqual(errors(DATUMS + [HOLES, a]), [])

    def test_only_position_and_profile(self):
        a = frame(characteristic="perpendicularity", datums=[["A", ""]])
        self.assertTrue(any("for position or profile" in e for e in errors(DATUMS + [HOLES, a])))

    def test_lower_datum_must_be_identified(self):
        a = frame(frame="single", lower={"tolerance": 0.05, "modifier": "", "datums": [["E", ""]]})
        self.assertTrue(any("datum E is referenced" in e for e in errors(DATUMS + [HOLES, a])))

    def test_iso_gets_a_note(self):
        notes = [m for s, _, m in pmi.check(DATUMS + [HOLES, frame()], "ISO") if s == "note"]
        self.assertTrue(any("ISO 5458" in m for m in notes))


class Plan(unittest.TestCase):
    def test_two_rows_with_their_bonus_and_methods(self):
        anns = pmi.number(DATUMS + [HOLES, frame()])
        rows = [r for r in pmi.inspection_plan(anns) if r["id"] == "F1"]
        self.assertEqual([r["segment"] for r in rows], ["PLTZF", "FRTZF"])
        self.assertEqual(rows[0]["number"], rows[1]["number"])
        self.assertAlmostEqual(rows[0]["upper_at_departure"], 0.5)       # 0.25 + (6.60 - 6.35)
        self.assertAlmostEqual(rows[1]["upper_at_departure"], 0.3)
        self.assertIn("pins float", rows[1]["method"])
        self.assertIn("orientation to A", rows[1]["note"])
        self.assertIn("pins float", next(g["how"] for g in pmi.gauges(DATUMS + [HOLES, frame()])
                                         if g["for"].startswith("FRTZF")))

    def test_one_gauge_per_row(self):
        g = [x for x in pmi.gauges(DATUMS + [HOLES, frame()]) if x["element"].startswith("gauge pin")]
        self.assertEqual([round(x["size"], 3) for x in g], [6.1, 6.3])     # MMC 6.35 - 0.25, - 0.05


# a four-hole pattern laid out as in Cogorno's graphic analysis example (ch. 13): holes 2 apart on 1, 3
BASIC = [(1.0, 1.0), (1.0, 3.0), (3.0, 3.0), (3.0, 1.0)]
ACTUAL = [(0.997, 1.003), (1.004, 3.004), (3.006, 2.998), (3.002, 0.998)]
SIZES = [0.256, 0.258, 0.260, 0.254]


def pattern():
    return [{"basic": b, "actual": a, "size": s} for b, a, s in zip(BASIC, ACTUAL, SIZES)]


class Evaluation(unittest.TestCase):
    def test_bonus_and_upper_row(self):
        r = pe.evaluate(pattern(), 0.010, "MMC", mmc=0.250, lmc=0.260)
        self.assertTrue(r["upper_pass"])
        self.assertEqual([round(f["bonus"], 4) for f in r["features"]], [0.006, 0.008, 0.010, 0.004])
        self.assertAlmostEqual(r["features"][0]["deviation"], 2 * math.hypot(0.003, 0.003))

    def test_lower_row_passes_when_it_may_turn_and_fails_when_it_may_not(self):
        low = {"tolerance": 0.002, "modifier": "MMC"}
        turn = pe.evaluate(pattern(), 0.010, "MMC", mmc=0.250, lmc=0.260, lower=low,
                           lower_motions=pe.motions_for([["A", ""]]))
        slide = pe.evaluate(pattern(), 0.010, "MMC", mmc=0.250, lmc=0.260, lower=low,
                            lower_motions=pe.motions_for([["A", ""], ["B", ""]]))
        self.assertTrue(turn["lower_pass"] and turn["pass"])
        self.assertFalse(slide["lower_pass"])
        self.assertLess(turn["lower_utilisation"], slide["lower_utilisation"])

    def test_minimax_fit_is_at_least_as_good_as_a_grid(self):
        zones = [0.002 + s - 0.25 for s in SIZES]
        util, _, _ = pe.best_fit(BASIC, ACTUAL, zones, pe.TRANSLATE_ROTATE)
        best = float("inf")
        centre = (2.0, 2.0)
        for i in range(-30, 31):
            for j in range(-30, 31):
                for k in range(-20, 21):
                    tx, ty, rot = i * 1e-4, j * 1e-4, k * 1e-4
                    moved = pe._moved(BASIC, centre, tx, ty, rot)
                    best = min(best, max(pe.deviation(a, m) / z for a, m, z in zip(ACTUAL, moved, zones)))
        self.assertLessEqual(util, best + 1e-6)

    def test_a_perfect_pattern_moved_and_turned_fits_exactly(self):
        c, s = math.cos(0.001), math.sin(0.001)
        actual = [(2 + c * (x - 2) - s * (y - 2) + 0.01, 2 + s * (x - 2) + c * (y - 2) - 0.02) for x, y in BASIC]
        feats = [{"basic": b, "actual": a, "size": 0.25} for b, a in zip(BASIC, actual)]
        r = pe.evaluate(feats, 0.05, "MMC", mmc=0.25, lower={"tolerance": 0.002, "modifier": "MMC"})
        self.assertLess(r["lower_utilisation"], 1e-5)
        self.assertGreater(r["upper_utilisation"], 0.5)          # but it is off its true position

    def test_size_beyond_mmc_rejects(self):
        feats = pattern()
        feats[0]["size"] = 0.249
        r = pe.evaluate(feats, 0.010, "MMC", mmc=0.250, lmc=0.260)
        self.assertFalse(r["features"][0]["size_ok"])
        self.assertFalse(r["pass"])

    def test_lmc_bonus(self):
        self.assertAlmostEqual(pe.bonus(0.255, 0.260, True, "LMC"), 0.005)
        self.assertAlmostEqual(pe.zone(0.01, "LMC", 0.255, 0.260, True), 0.015)

    def test_report_names_both_rows(self):
        r = pe.evaluate(pattern(), 0.010, "MMC", mmc=0.250, lmc=0.260, lower={"tolerance": 0.002, "modifier": "MMC"})
        text = pe.report(r)
        self.assertIn("Pattern-locating row: PASS", text)
        self.assertIn("Feature-relating row: PASS", text)
        self.assertIn("Pattern: ACCEPT", text)


if __name__ == "__main__":
    unittest.main()
