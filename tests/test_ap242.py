# SPDX-License-Identifier: LGPL-2.1-or-later
"""STEP AP242 semantic PMI: the mapping and the file checks (no FreeCAD or OCCT needed)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import ap242  # noqa: E402

PLATE = [
    {"id": "A", "kind": "datum", "letter": "A", "feature_type": "plane"},
    {"id": "B", "kind": "datum", "letter": "B", "feature_type": "plane"},
    {"id": "D1", "kind": "dimension", "dim_type": "diameter", "feature_type": "hole", "nominal": 16.0,
     "plus": 0.0, "minus": 0.0, "fit": "H7", "envelope": True},
    {"id": "D2", "kind": "dimension", "dim_type": "diameter", "feature_type": "pin", "nominal": 10.0,
     "plus": 0.0, "minus": 0.0, "fit": "g6"},
    {"id": "D3", "kind": "dimension", "dim_type": "distance", "feature_type": "width", "nominal": 80.0,
     "plus": 0.1, "minus": 0.1},
    {"id": "D4", "kind": "dimension", "dim_type": "distance", "feature_type": "other", "nominal": 25.0,
     "plus": 0.0, "minus": 0.0, "count": 4},
    {"id": "D5", "kind": "dimension", "dim_type": "distance", "feature_type": "other", "nominal": 40.0,
     "basic": True},
    {"id": "P", "kind": "fcf", "characteristic": "position", "feature_type": "hole", "tolerance": 0.05,
     "diameter": True, "modifier": "MMC", "datums": [["A", ""], ["B", "MMC"]]},
    {"id": "C", "kind": "fcf", "characteristic": "concentricity", "feature_type": "pin", "tolerance": 0.02,
     "diameter": True, "modifier": "", "datums": [["A", ""]]},
]

# what OCCT 7.8 writes for the plate (abridged): grades two too high, as it does
STEP = """ISO-10303-21;
HEADER;
FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF. {1 0 10303 442 1 1 4 }'));
ENDSEC;
DATA;
#212 = DATUM('','',#4,.F.,'A');
#216 = DATUM('','',#4,.F.,'B');
#223 = DIMENSIONAL_SIZE(#218,'diameter');
#228 = LIMITS_AND_FITS('H','hole','9','');
#227 = PLUS_MINUS_TOLERANCE(#226,#223);
#229 = PLUS_MINUS_TOLERANCE(#228,#223);
#307 = DIMENSIONAL_SIZE(#302,'diameter');
#312 = LIMITS_AND_FITS('G','shaft','8','');
#313 = PLUS_MINUS_TOLERANCE(#312,#307);
#324 = DIMENSIONAL_SIZE(#316,'thickness');
#327 = PLUS_MINUS_TOLERANCE(#326,#324);
#330 = DIMENSIONAL_LOCATION('distance','',#1,#2);
#331 = DATUM_SYSTEM('','',#26,.F.,(#329,#330));
#233 = LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(5.E-02),#205);
#236 = ( GEOMETRIC_TOLERANCE('','',#233,#234)
GEOMETRIC_TOLERANCE_WITH_DATUM_REFERENCE((#331))
GEOMETRIC_TOLERANCE_WITH_MODIFIERS((.MAXIMUM_MATERIAL_REQUIREMENT.))
POSITION_TOLERANCE() );
#242 = LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-02),#205);
#245 = FLATNESS_TOLERANCE('','',#242,#243);
ENDSEC;
END-ISO-10303-21;
"""


class Plan(unittest.TestCase):
    def setUp(self):
        self.p = {r["id"]: r for r in ap242.plan(PLATE, "ISO")}

    def test_sizes_and_locations(self):
        self.assertEqual(self.p["D1"]["type"], "Size_Diameter")
        self.assertTrue(self.p["D1"]["size"])
        self.assertEqual(self.p["D3"]["type"], "Size_Thickness")          # a width is a feature of size
        self.assertEqual(self.p["D4"]["type"], "Location_LinearDistance")
        self.assertFalse(self.p["D4"]["size"])

    def test_fit_gives_signed_deviations_and_class(self):
        d = self.p["D2"]                                                 # 10 g6: -0.005 / -0.014
        self.assertAlmostEqual(d["upper"], -0.005)
        self.assertAlmostEqual(d["lower"], -0.014)
        self.assertEqual(d["fit"], ("g", 6, "shaft"))
        self.assertEqual(self.p["D1"]["fit"], ("H", 7, "hole"))
        self.assertAlmostEqual(self.p["D1"]["upper"], 0.018)

    def test_individual_tolerance(self):
        self.assertAlmostEqual(self.p["D3"]["upper"], 0.1)
        self.assertAlmostEqual(self.p["D3"]["lower"], -0.1)
        self.assertIsNone(self.p["D3"]["fit"])

    def test_what_occt_cannot_carry_is_reported(self):
        self.assertIn("ISO 14405 envelope (E)", self.p["D1"]["not_written"])
        self.assertIn("4X", self.p["D4"]["not_written"])
        self.assertIn("basic (theoretically exact)", self.p["D5"]["not_written"])
        self.assertIsNone(self.p["D5"]["upper"])

    def test_general_tolerance_is_not_written_as_individual(self):
        d = {r["id"]: r for r in ap242.plan(PLATE, "ISO", "ISO 2768-mK")}["D4"]
        self.assertIsNone(d["upper"])
        self.assertTrue(any("ISO 2768-m" in w for w in d["not_written"]))

    def test_frames(self):
        f = self.p["P"]
        self.assertEqual((f["type"], f["value"], f["diameter"], f["material"]), ("Position", 0.05, True, "M"))
        self.assertEqual(f["datums"], [("A", 1, ""), ("B", 2, "M")])

    def test_coaxiality_under_iso_concentricity_under_asme(self):
        self.assertEqual(self.p["C"]["type"], "Coaxiality")
        asme = {r["id"]: r for r in ap242.plan(PLATE, "ASME")}
        self.assertEqual(asme["C"]["type"], "Concentricity")

    def test_every_characteristic_has_an_occt_type_and_entity(self):
        from nxstyle import gdt
        for c in gdt.CHARACTERISTICS:
            self.assertIn(ap242.GEOM_TYPES[c], ap242.ENTITY)


class File(unittest.TestCase):
    def test_limits_and_fits_get_the_annotations_grades(self):
        text, n = ap242.fix_limits_and_fits(STEP, [("H", 7, "hole"), ("g", 6, "shaft")])
        self.assertEqual(n, 2)
        self.assertIn("LIMITS_AND_FITS('H','hole','7','')", text)
        self.assertIn("LIMITS_AND_FITS('g','shaft','6','')", text)

    def test_count_mismatch_leaves_file_alone(self):
        text, n = ap242.fix_limits_and_fits(STEP, [("H", 7, "hole")])
        self.assertEqual((text, n), (STEP, 0))

    def test_correct_file_needs_no_change(self):
        text, _ = ap242.fix_limits_and_fits(STEP, [("H", 7, "hole"), ("g", 6, "shaft")])
        again, n = ap242.fix_limits_and_fits(text, [("H", 7, "hole"), ("g", 6, "shaft")])
        self.assertEqual((again, n), (text, 0))

    def test_summary(self):
        s = ap242.summary(STEP)
        self.assertEqual(s["schema"], "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF")
        self.assertEqual(s["datums"], ["A", "B"])
        self.assertEqual(s["datum_systems"], 1)
        self.assertEqual(s["dimensions"], {"diameter": 2, "thickness": 1})
        self.assertEqual(s["locations"], 1)
        self.assertEqual(s["plus_minus"], 3)
        self.assertEqual(s["fits"], ["G8", "H9"])
        self.assertEqual(s["tolerances"], {"POSITION_TOLERANCE": 1, "FLATNESS_TOLERANCE": 1})
        self.assertEqual(s["material_requirements"], 1)
        self.assertEqual(s["values"], [0.01, 0.05])
        self.assertIn("geometric tolerances: 1 flatness, 1 position", ap242.summary_text(s))


class Reading(unittest.TestCase):
    def test_dimension_with_class(self):
        kind, v = ap242.pmi_values({"kind": "dimension", "type": "Size_Diameter", "fit": ("G", 6, "shaft"),
                                    "upper": -0.002, "lower": -0.011})
        self.assertEqual((kind, v), ("Dimension", {"DimensionType": "Diameter", "Fit": "g6"}))

    def test_dimension_with_deviations_signed(self):
        # lower bound below nominal: a positive "minus"; above nominal: a negative one
        _, v = ap242.pmi_values({"kind": "dimension", "type": "Location_LinearDistance", "upper": 0.2, "lower": -0.1})
        self.assertEqual(v, {"DimensionType": "Distance", "UpperDeviation": 0.2, "LowerDeviation": 0.1})
        _, v = ap242.pmi_values({"kind": "dimension", "type": "Size_Thickness", "upper": 0.05, "lower": 0.02})
        self.assertEqual(v["LowerDeviation"], -0.02)

    def test_frame(self):
        kind, v = ap242.pmi_values({"kind": "fcf", "type": "Position", "value": 0.05, "diameter": True,
                                    "material": "M", "datums": [("B", 2, "M"), ("A", 1, "")]})
        self.assertEqual(kind, "Feature Control Frame")
        self.assertEqual(v, {"Characteristic": "Position", "Tolerance": 0.05, "ZoneDiameter": True,
                             "MaterialCondition": "MMC", "DatumReferences": ["A", "B(M)"]})
        _, v = ap242.pmi_values({"kind": "fcf", "type": "Coaxiality", "value": 0.02, "datums": []})
        self.assertEqual(v["Characteristic"], "Concentricity")

    def test_what_pmi_cannot_hold(self):
        self.assertIsNone(ap242.pmi_values({"kind": "dimension", "type": "Size_SphericalDiameter"})[0])

    def test_signed_tolerances_from_the_file(self):
        text = """DATA;
#1 = ( LENGTH_MEASURE_WITH_UNIT() MEASURE_REPRESENTATION_ITEM() MEASURE_WITH_UNIT(POSITIVE_LENGTH_MEASURE(16.),#9) REPRESENTATION_ITEM('') );
#2 = SHAPE_DIMENSION_REPRESENTATION('',(#1),#8);
#3 = DIMENSIONAL_SIZE(#7,'diameter');
#4 = DIMENSIONAL_CHARACTERISTIC_REPRESENTATION(#3,#2);
#5 = MEASURE_WITH_UNIT(5.E-02,#9);
#6 = MEASURE_WITH_UNIT(2.E-02,#9);
#10 = TOLERANCE_VALUE(#6,#5);
#11 = PLUS_MINUS_TOLERANCE(#10,#3);
ENDSEC;
"""
        self.assertEqual(ap242.signed_tolerances(text), [(16.0, 0.02, 0.05)])


if __name__ == "__main__":
    unittest.main()
