# SPDX-License-Identifier: LGPL-2.1-or-later
"""PMI semantics: checks, characteristic numbering, inspection plan, gauges (no FreeCAD needed)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))
from nxstyle import pmi  # noqa: E402


def plate():
    """A hole pattern located from a datum feature of size, as in Cogorno ch. 13 (inches):
    centre hole D .505-.520 perpendicular .005 (M) to A and at position .020 (M) to A|B|C;
    four holes .255-.265 at position .005 (M) to A|D(M)|B."""
    return [
        {"id": "DatumA", "kind": "datum", "letter": "A", "feature": "Face6", "feature_type": "plane"},
        {"id": "DatumB", "kind": "datum", "letter": "B", "feature": "Face3", "feature_type": "plane"},
        {"id": "DatumC", "kind": "datum", "letter": "C", "feature": "Face1", "feature_type": "plane"},
        {"id": "SizeD", "kind": "dimension", "dim_type": "diameter", "nominal": 0.505, "plus": 0.015, "minus": 0.0,
         "feature": "Face9", "feature_type": "hole"},
        {"id": "DatumD", "kind": "datum", "letter": "D", "feature": "Face9", "feature_type": "hole"},
        {"id": "PerpD", "kind": "fcf", "characteristic": "perpendicularity", "tolerance": 0.005, "diameter": True,
         "modifier": "MMC", "datums": [["A", ""]], "feature": "Face9", "feature_type": "hole"},
        {"id": "PosD", "kind": "fcf", "characteristic": "position", "tolerance": 0.020, "diameter": True,
         "modifier": "MMC", "datums": [["A", ""], ["B", ""], ["C", ""]], "feature": "Face9", "feature_type": "hole"},
        {"id": "Size4X", "kind": "dimension", "dim_type": "diameter", "nominal": 0.255, "plus": 0.010, "minus": 0.0,
         "count": 4, "feature": "Face10", "feature_type": "hole"},
        {"id": "Pos4X", "kind": "fcf", "characteristic": "position", "tolerance": 0.005, "diameter": True,
         "modifier": "MMC", "datums": [["A", ""], ["D", "MMC"], ["B", ""]], "feature": "Face10", "feature_type": "hole"},
        {"id": "Basic4", "kind": "dimension", "dim_type": "distance", "nominal": 4.0, "basic": True,
         "feature": "Face10 | Face9", "feature_type": "other"},
        {"id": "FlatA", "kind": "fcf", "characteristic": "flatness", "tolerance": 0.002, "feature": "Face6",
         "feature_type": "plane"},
    ]


class Text(unittest.TestCase):
    def test_zero_deviation_is_the_digit_0(self):
        a = {"kind": "dimension", "dim_type": "diameter", "nominal": 5.0, "plus": 0.2, "minus": 0.0, "count": 4}
        self.assertEqual(pmi.dimension_text(a), "4X Ø5.000 +0.200/0")         # ISO 129-1, not "-0.000"
        b = {"kind": "dimension", "dim_type": "diameter", "nominal": 6.0, "fit": "h6"}
        self.assertEqual(pmi.dimension_text(b), "Ø6.000 h6 (0/-0.008)")

    def test_zone_above_nominal(self):
        a = {"kind": "dimension", "dim_type": "distance", "nominal": 10.0, "plus": 0.05, "minus": -0.02}
        self.assertEqual(pmi.dimension_text(a), "10.000 +0.050/+0.020")


class Checks(unittest.TestCase):
    def test_the_plate_is_clean(self):
        self.assertEqual(pmi.check(plate(), "ASME"), [])      # Cogorno's plate is an ASME drawing

    def errors(self, mutate, standard="ASME"):
        ann = plate()
        mutate(ann)
        return [m for s, _, m in pmi.check(ann, standard) if s == "error"]

    def test_form_tolerance_with_a_datum(self):
        def m(a):
            a[-1]["datums"] = [["A", ""]]
        self.assertTrue(any("form tolerance" in e for e in self.errors(m)))

    def test_mmc_on_a_plane(self):
        def m(a):
            a[-1]["modifier"] = "MMC"
        self.assertTrue(any("feature of size" in e for e in self.errors(m)))

    def test_datum_letters(self):
        def m(a):
            a[0]["letter"] = "I"
        self.assertTrue(any("I, O and Q" in e for e in self.errors(m)))
        self.assertFalse(any("I, O and Q" in e for e in self.errors(m, "ISO")))

    def test_undefined_datum(self):
        def m(a):
            a[8]["datums"][2] = ["E", ""]
        self.assertTrue(any("datum E is referenced" in e for e in self.errors(m)))

    def test_mmb_on_a_plane_datum(self):
        def m(a):
            a[8]["datums"][2] = ["B", "MMC"]
        self.assertTrue(any("not a feature of size" in e for e in self.errors(m)))

    def test_runout_is_rfs(self):
        def m(a):
            a.append({"id": "R", "kind": "fcf", "characteristic": "circular runout", "tolerance": 0.01,
                      "modifier": "MMC", "datums": [["D", ""]], "feature": "Face10", "feature_type": "hole"})
        self.assertTrue(any("always RFS" in e for e in self.errors(m)))

    def test_orientation_needs_a_datum(self):
        def m(a):
            a[5]["datums"] = []
        self.assertTrue(any("needs a datum" in e for e in self.errors(m)))

    def test_basic_with_tolerance(self):
        def m(a):
            a[9]["plus"] = 0.01
        self.assertTrue(any("(basic) dimension has no tolerance" in e for e in self.errors(m)))

    def test_duplicate_datum(self):
        def m(a):
            a[1]["letter"] = "A"
        self.assertTrue(any("identified twice" in e for e in self.errors(m)))


class Plan(unittest.TestCase):
    def setUp(self):
        self.ann = pmi.number(plate())
        self.plan = pmi.inspection_plan(self.ann)

    def test_numbering_skips_datums_and_basic_dimensions(self):
        self.assertEqual([r["id"] for r in self.plan], ["SizeD", "PerpD", "PosD", "Size4X", "Pos4X", "FlatA"])
        self.assertEqual([r["number"] for r in self.plan], [1, 2, 3, 4, 5, 6])
        self.assertEqual(next(a for a in self.ann if a["id"] == "Basic4")["number"], 0)

    def test_size_limits(self):
        d = self.plan[0]
        self.assertAlmostEqual(d["lower"], 0.505)
        self.assertAlmostEqual(d["upper"], 0.520)

    def test_bonus_up_to_lmc(self):
        pos = next(r for r in self.plan if r["id"] == "Pos4X")
        self.assertAlmostEqual(pos["upper_at_departure"], 0.015)       # .005 + (.265 - .255)
        self.assertEqual(pos["datums"], "A|D(M)|B")
        self.assertIn("functional gauge", pos["method"])

    def test_texts(self):
        self.assertEqual(pmi.text(self.ann[3]), "Ø0.505 +0.015/0")
        self.assertEqual(pmi.text(self.ann[9]), "[4.000]")
        self.assertEqual(pmi.text(self.ann[8]), "position | Ø0.005 (M) | A | D (M) | B")


class Gauges(unittest.TestCase):
    def test_cogorno_gauge_pins(self):
        g = {e["for"]: e for e in pmi.gauges(plate())}
        pins = g["position | Ø0.005 (M) | A | D (M) | B"]
        self.assertAlmostEqual(pins["size"], 0.250)            # .255 - .005
        self.assertEqual(pins["element"], "gauge pin x4")
        d = g["datum D at MMC"]
        self.assertAlmostEqual(d["size"], 0.500)               # .505 - .005 (perpendicularity to A)

    def test_external_feature(self):
        ann = [{"id": "S", "kind": "dimension", "dim_type": "diameter", "nominal": 1.0, "plus": 0.010, "minus": 0.0,
                "feature": "F", "feature_type": "pin"},
               {"id": "P", "kind": "fcf", "characteristic": "position", "tolerance": 0.010, "diameter": True,
                "modifier": "MMC", "datums": [], "feature": "F", "feature_type": "pin"}]
        self.assertAlmostEqual(pmi.gauges(ann)[0]["size"], 1.020)   # 1.010 + .010

    def test_report(self):
        text = pmi.report(plate(), standard="ASME")
        self.assertIn("Functional gauge", text)
        self.assertIn("Checks: no issues", text)


def shaft_part(**bore):
    """A metric part to ISO GPS: a Ø20 H7 bore (datum A), a 40 mm length without tolerance, and
    position of a Ø8 hole."""
    b = {"id": "Bore", "kind": "dimension", "dim_type": "diameter", "nominal": 20.0, "fit": "H7",
         "feature": "Face4", "feature_type": "hole"}
    b.update(bore)
    return [b,
            {"id": "DatumA", "kind": "datum", "letter": "A", "feature": "Face4", "feature_type": "hole"},
            {"id": "Length", "kind": "dimension", "dim_type": "distance", "nominal": 40.0, "feature": "Face1 | Face2",
             "feature_type": "width", "internal": False},
            {"id": "Hole", "kind": "dimension", "dim_type": "diameter", "nominal": 8.0, "plus": 0.1, "minus": 0.0,
             "feature": "Face7", "feature_type": "hole"},
            {"id": "PosHole", "kind": "fcf", "characteristic": "position", "tolerance": 0.05, "diameter": True,
             "modifier": "MMC", "datums": [["A", "MMC"]], "feature": "Face7", "feature_type": "hole"}]


class IsoGps(unittest.TestCase):
    def findings(self, ann, general=None):
        return [(s, i, m) for s, i, m in pmi.check(ann, "ISO", general)]

    def test_fit_without_envelope_is_flagged_under_independency(self):
        f = self.findings(shaft_part(), "ISO 2768-mK")
        self.assertTrue(any(s == "warning" and i == "Bore" and "ISO 8015" in m for s, i, m in f))
        f = self.findings(shaft_part(envelope=True), "ISO 2768-mK")
        self.assertFalse(any(i == "Bore" and "ISO 8015" in m for _, i, m in f))

    def test_general_note_with_e_is_an_envelope_for_all(self):
        f = self.findings(shaft_part(), "ISO 2768-mK-E")
        self.assertFalse(any("ISO 8015" in m for _, _, m in f))

    def test_untoleranced_dimension_needs_the_general_note(self):
        self.assertTrue(any(i == "Length" and "no ISO 2768" in m for _, i, m in self.findings(shaft_part())))
        self.assertFalse(any(i == "Length" and "no tolerance" in m
                             for _, i, m in self.findings(shaft_part(), "ISO 2768-mK")))

    def test_plan_takes_iso_286_and_2768(self):
        ann = pmi.number(shaft_part(envelope=True), general="ISO 2768-mK")
        plan = {r["id"]: r for r in pmi.inspection_plan(ann, general="ISO 2768-mK")}
        self.assertAlmostEqual(plan["Bore"]["lower"], 20.0)
        self.assertAlmostEqual(plan["Bore"]["upper"], 20.021)
        self.assertEqual(plan["Bore"]["tolerance_from"], "ISO 286 H7")
        self.assertIn("envelope", plan["Bore"]["note"])
        self.assertAlmostEqual(plan["Length"]["lower"], 39.7)          # ISO 2768-m: +/-0.3 over 30 to 120
        self.assertEqual(plan["Length"]["tolerance_from"], "ISO 2768-m")
        self.assertEqual([r["number"] for r in plan.values()], [1, 2, 3, 4])

    def test_gauge_uses_the_fit_limits(self):
        g = {e["for"]: e for e in pmi.gauges(shaft_part())}
        self.assertAlmostEqual(g["datum A at MMC"]["size"], 20.0)       # MMC of Ø20 H7
        self.assertAlmostEqual(g["position | Ø0.050 (M) | A (M)"]["size"], 7.95)

    def test_shaft_class_on_a_hole_is_an_error(self):
        f = self.findings(shaft_part(fit="g6"), "ISO 2768-mK")
        self.assertTrue(any(s == "error" and "shaft class" in m for s, _, m in f))

    def test_text(self):
        self.assertEqual(pmi.text(shaft_part(envelope=True)[0]), "Ø20.000 H7 (+0.021/0) Ⓔ")

    def test_asme_flags_dropped_characteristics(self):
        ann = shaft_part()
        ann.append({"id": "Sym", "kind": "fcf", "characteristic": "symmetry", "tolerance": 0.1, "datums": [["A", ""]],
                    "feature": "Face1 | Face2", "feature_type": "width"})
        self.assertTrue(any("2018" in m for _, _, m in pmi.check(ann, "ASME")))
        self.assertFalse(any("2018" in m for _, _, m in pmi.check(ann, "ISO")))


if __name__ == "__main__":
    unittest.main()
