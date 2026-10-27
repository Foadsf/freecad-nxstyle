# SPDX-License-Identifier: LGPL-2.1-or-later
"""ISO 10303: Part 21 files, EXPRESS checking, and parametric models in STEP (no FreeCAD needed)."""

import copy
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import express, iso10303, p21, parametric  # noqa: E402


def rect_face(x0, y0, x1, y1, z=0.0):
    pts = [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
    edges = []
    for a, b in zip(pts, pts[1:] + pts[:1]):
        d = [b[i] - a[i] for i in range(3)]
        edges.append({"curve": {"type": "line", "origin": list(a), "dir": d}, "p1": list(a), "p2": list(b)})
    return {"surface": {"type": "plane", "origin": [0, 0, z], "axis": [0, 0, 1], "x": [1, 0, 0]},
            "loops": [edges]}


def circle_face(cx, cy, r, z):
    p = [cx + r, cy, z]
    edge = {"curve": {"type": "circle", "center": [cx, cy, z], "axis": [0, 0, 1], "x": [1, 0, 0], "r": r},
            "p1": p, "p2": p}
    return {"surface": {"type": "plane", "origin": [0, 0, z], "axis": [0, 0, 1], "x": [1, 0, 0]},
            "loops": [[edge]]}


XY = {"origin": [0, 0, 0], "axis": [0, 0, 1], "x": [1, 0, 0]}
PLATE = {
    "name": "Plate",
    "parameters": [{"name": "L", "value": 80.0, "unit": "mm", "description": "plate length"},
                   {"name": "T", "value": 10.0, "unit": "mm", "description": ""},
                   {"name": "A", "value": 30.0, "unit": "deg", "description": "unused angle"}],
    "sketches": [
        {"name": "Base", "placement": XY, "faces": [rect_face(0, 0, 80, 50)],
         "geometry": [{"type": "line", "p1": [0, 0], "p2": [80, 0]},
                      {"type": "line", "p1": [80, 0], "p2": [80, 50]},
                      {"type": "line", "p1": [80, 50], "p2": [0, 50]},
                      {"type": "line", "p1": [0, 50], "p2": [0, 0]},
                      {"type": "line", "p1": [40, -5], "p2": [40, 55], "construction": True}],
         "constraints": [
             {"type": "Coincident", "first": 0, "first_pos": 2, "second": 1, "second_pos": 1},
             {"type": "Coincident", "first": 1, "first_pos": 2, "second": 2, "second_pos": 1},
             {"type": "Coincident", "first": 2, "first_pos": 2, "second": 3, "second_pos": 1},
             {"type": "Coincident", "first": 3, "first_pos": 2, "second": 0, "second_pos": 1},
             {"type": "Horizontal", "first": 0}, {"type": "Horizontal", "first": 2},
             {"type": "Vertical", "first": 1}, {"type": "Vertical", "first": 3},
             {"type": "Coincident", "first": 0, "first_pos": 1, "second": -1, "second_pos": 1},
             {"type": "DistanceX", "first": 0, "value": 80.0, "name": "length", "expression": ["var", "L"]},
             {"type": "DistanceY", "first": 1, "first_pos": 1, "second": 1, "second_pos": 2, "value": 50.0},
             {"type": "Symmetric", "first": 0, "first_pos": 1, "second": 0, "second_pos": 2, "third": 4},
             {"type": "Angle", "first": 1, "second": 0, "value": math.radians(90)},
         ]},
        {"name": "Hole", "placement": {"origin": [0, 0, 10], "axis": [0, 0, 1], "x": [1, 0, 0]},
         "faces": [circle_face(20, 25, 6, 10)],
         "geometry": [{"type": "circle", "c": [20, 25], "r": 6}],
         "constraints": [{"type": "Diameter", "first": 0, "value": 12.0},
                         {"type": "DistanceX", "first": 0, "first_pos": 3, "value": 20.0},
                         {"type": "DistanceY", "first": 0, "first_pos": 3, "value": 25.0}]},
    ],
    "features": [
        {"type": "extrude", "name": "Pad", "sketch": "Base", "direction": [0, 0, 1], "first": 10.0, "second": 0.0,
         "intent": ["blind", "blind"], "expressions": {"first": ["var", "T"]}},
        {"type": "extrude", "name": "Pocket", "sketch": "Hole", "op": "difference", "direction": [0, 0, -1],
         "first": 10.0, "second": 0.0, "intent": ["through_all", "blind"]},
        {"type": "pattern", "name": "LinearPattern", "source": "Pocket", "kind": "linear",
         "transforms": [{"matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "translation": [20.0 * k, 0, 0]}
                        for k in (1, 2)]},
        {"type": "fillet", "name": "Fillet", "radius": 2.0, "expressions": {"radius": ["/", ["var", "T"], ["num", 5]]},
         "edges": [{"curve": {"type": "line", "origin": [80, 0, 0], "dir": [0, 0, 1]}, "p1": [80, 0, 0],
                    "p2": [80, 0, 10]}]},
    ],
}


class Part21(unittest.TestCase):
    def test_strings(self):
        for s in ["CAT", "Don't", "", "a\\b", "Ärger", "hôtel", "Нет", "𝄞 clef", "see § 4.1"]:
            enc = p21.encode_string(s)
            self.assertTrue(all(32 <= ord(c) <= 126 for c in enc), enc)
            self.assertEqual(p21.decode_string(enc[1:-1]), s)
        # the examples of ISO 10303-21:2002 6.3.3
        self.assertEqual(p21.decode_string("\\S\\Drger"), "Ärger")
        self.assertEqual(p21.decode_string("h\\S\\ttel"), "hôtel")
        self.assertEqual(p21.decode_string("\\PE\\\\S\\=\\S\\U\\S\\b"), "Нет")
        self.assertEqual(p21.decode_string("see \\X\\A7 4.1"), "see § 4.1")
        self.assertEqual(p21.decode_string("line one\\X\\0Aline two"), "line one\nline two")
        self.assertEqual(p21.decode_string("\\X2\\00C4\\X0\\rger\\N\\"), "Ärger")

    def test_tokens(self):
        f = p21.loads("ISO-10303-21;HEADER;FILE_DESCRIPTION((''),'2;1');FILE_NAME('','2026-01-01T00:00:00',(''),(''),"
                      "'','','');FILE_SCHEMA(('S'));ENDSEC;DATA;\n#1=A(+0.0E0,0.E25,-32.178E+02,012,.T.,\"23B\",$,*,"
                      "(1,(2.,3.)),B(4.),'it''s',#0\n2);/* comment */#2=(X(1)Y());ENDSEC;END-ISO-10303-21;")
        v = f[1].params
        self.assertEqual(v[:4], [0.0, 0.0, -3217.8, 12])
        self.assertEqual((v[4], v[5]), ("T", "111011"))
        self.assertIs(v[6], p21.UNSET)
        self.assertIs(v[7], p21.DERIVED)
        self.assertEqual(v[8], [1, [2.0, 3.0]])
        self.assertEqual(v[9], p21.Typed("B", 4.0))
        self.assertEqual(v[10], "it's")
        self.assertEqual(v[11], 2)                  # a line break inside a token is ignored (annex A)
        self.assertTrue(f[2].complex and f[2].names == ["X", "Y"])
        self.assertEqual(p21.loads(p21.dumps(f))[1].params, v)

    def test_reals_and_errors(self):
        for x, s in [(1.0, "1."), (0.25, "0.25"), (1e-5, "1.E-05"), (-2.5e20, "-2.5E+20"), (1e20, "1.E+20")]:
            self.assertEqual(p21.format_real(x), s)
        bad = "ISO-10303-21;HEADER;ENDSEC;DATA;#1=A(1);#1=B(2);ENDSEC;END-ISO-10303-21;"
        with self.assertRaises(p21.P21Error):
            p21.loads(bad)
        with self.assertRaises(p21.P21Error):
            p21.loads("ISO-10303-21;HEADER;ENDSEC;DATA;#1=A(1E5);ENDSEC;END-ISO-10303-21;")

    def test_sections(self):
        f = p21.loads("ISO-10303-21;HEADER;FILE_DESCRIPTION((''),'3;1');FILE_NAME('','2026-01-01T00:00',(''),(''),"
                      "'','','');FILE_SCHEMA(('A','B'));ENDSEC;DATA('one',('A'));#1=X();ENDSEC;"
                      "DATA('two',('B'));#2=Y(#1);ENDSEC;END-ISO-10303-21;")
        self.assertEqual([s.name for s in f.sections], ["one", "two"])
        self.assertEqual(f.get(2).params, [p21.Ref(1)])
        self.assertIn("DATA('two',('B'));", p21.dumps(f))


class Express(unittest.TestCase):
    SCHEMA = """SCHEMA s; TYPE label = STRING; END_TYPE; TYPE colour = ENUMERATION OF (red, green); END_TYPE;
    TYPE thing = SELECT (base, label); END_TYPE;
    ENTITY base ABSTRACT SUPERTYPE OF (ONEOF (a, b)); name : label; END_ENTITY;
    ENTITY a SUBTYPE OF (base); c : colour; pts : LIST [2:3] OF REAL; END_ENTITY;
    ENTITY b SUBTYPE OF (base); other : OPTIONAL thing; DERIVE SELF\\base.name : label := 'b'; END_ENTITY;
    FUNCTION f(x : REAL) : REAL; RETURN (x); END_FUNCTION; END_SCHEMA;"""

    def test_mapping_and_check(self):
        d = express.Dictionary.from_text(self.SCHEMA)
        self.assertEqual([a["name"] for a in d.attributes("a")], ["name", "c", "pts"])
        self.assertEqual([a["derived"] for a in d.attributes("b")], [True, False])
        f = p21.loads("ISO-10303-21;HEADER;FILE_DESCRIPTION((''),'2;1');FILE_NAME('','2026-01-01T00:00',(''),(''),"
                      "'','','');FILE_SCHEMA(('S'));ENDSEC;DATA;#1=A('x',.RED.,(1.,2.));#2=B(*,#1);"
                      "#3=B(*,LABEL('t'));#4=A('y',.BLUE.,(1.));#5=BASE('z');#6=B('n',$);#7=(A('q',.RED.,(1.,2.))"
                      "B(*,$)BASE('q'));ENDSEC;END-ISO-10303-21;")
        msgs = {(i.id, i.message.split(":")[0]) for i in express.check(f, d) if i.level == "error"}
        ids = {i for i, _ in msgs}
        self.assertNotIn(1, ids)
        self.assertNotIn(2, ids)
        self.assertNotIn(3, ids)
        self.assertIn(4, ids)                      # .BLUE. and a list of 1
        self.assertIn(5, ids)                      # abstract
        self.assertIn(6, ids)                      # name must be *
        self.assertIn(7, ids)                      # ONEOF (a, b)

    def test_bundled_dictionary(self):
        d = iso10303.dictionary()
        # ISO 10303-108 Cor.1 annex F.1.1 writes BOUND_VARIATIONAL_PARAMETER('P1', #520, 'P1', 'C5 RADIUS', *)
        a = d.attributes("bound_variational_parameter")
        self.assertEqual([x["name"] for x in a], ["name", "values_space", "name", "parameter_description",
                                                  "parameter_current_value"])
        self.assertTrue(a[-1]["derived"])
        self.assertNotIn("model_parameter", d.entities)            # renamed by Cor.1
        self.assertIn("variational_parameter", d.entities)
        self.assertEqual(d.entity_name("PSRS"), "procedural_shape_representation_sequence")
        for e in ("solid_with_general_pocket", "create_circle_3_points", "pdgc_with_dimension",
                  "user_selected_shape_elements", "b_spline_surface_with_knots", "mapped_item"):
            self.assertIn(e, d.entities)
        self.assertEqual(len([e for e in d.entities if d.entities[e]["schema"] == "procedural_sketch_schema"]), 43)


class Parametric(unittest.TestCase):
    def written(self, model=PLATE):
        f, notes = parametric.to_step(copy.deepcopy(model))
        return p21.loads(p21.dumps(f)), notes

    def test_valid_against_the_schemas_and_rules(self):
        f, notes = self.written()
        issues = iso10303.check(f)
        errors = [i for i in issues if i.level == "error"]
        self.assertEqual(errors, [])
        warnings = [i for i in issues if i.level == "warning"]
        # untyped current values of unbound parameters (as ISO 10303-108 Cor.1 annex F writes them), and the
        # conflict between 108 6.3.4 WR4 and 8.4.9 for each sketch
        self.assertTrue(all("SELECT maths_value" in w.message or "WR4 not met" in w.message for w in warnings),
                        warnings)
        self.assertEqual(sum("WR4" in w.message for w in warnings), 2)
        inv = iso10303.inventory(f)
        for std in ("ISO 10303-42", "ISO 10303-43", "ISO 10303-55", "ISO 10303-108", "ISO 10303-111",
                    "ISO 13584-20"):
            self.assertIn(std, inv)

    def test_round_trip(self):
        f, _ = self.written()
        models, notes = parametric.from_step(f)
        self.assertEqual(len(models), 1)
        m = models[0]
        self.assertEqual({p["name"]: round(p["value"], 9) for p in m["parameters"]}, {"L": 80.0, "T": 10.0, "A": 30.0})
        base = next(s for s in m["sketches"] if s["name"] == "Base")
        types = sorted(c["type"] for c in base["constraints"])
        self.assertEqual(types, sorted(c["type"] for c in PLATE["sketches"][0]["constraints"]))
        dx = next(c for c in base["constraints"] if c["type"] == "DistanceX")
        self.assertEqual((dx["value"], dx["name"], dx["expression"]), (80.0, "length", ["var", "L"]))
        dy = next(c for c in base["constraints"] if c["type"] == "DistanceY")
        self.assertEqual(dy["value"], 50.0)
        ang = next(c for c in base["constraints"] if c["type"] == "Angle")
        self.assertAlmostEqual(abs(ang["value"]), math.pi / 2)
        self.assertEqual(sum(1 for g in base["geometry"] if g.get("construction")), 1)
        hole = next(s for s in m["sketches"] if s["name"] == "Hole")
        self.assertEqual([c["type"] for c in hole["constraints"]], ["Diameter", "DistanceX", "DistanceY"])
        self.assertEqual(hole["constraints"][0]["value"], 12.0)
        self.assertEqual(hole["placement"]["origin"], [0.0, 0.0, 10.0])
        feats = {ft["name"]: ft for ft in m["features"]}
        self.assertEqual([ft["type"] for ft in m["features"]], ["extrude", "extrude", "pattern", "fillet"])
        self.assertEqual(feats["Pad"]["sketch"], "Base")
        self.assertEqual(feats["Pad"]["expressions"], {"first": ["var", "T"]})
        self.assertEqual((feats["Pocket"]["op"], feats["Pocket"]["intent"][0]), ("difference", "through_all"))
        self.assertEqual(feats["LinearPattern"]["source"], "Pocket")
        self.assertEqual([t["translation"] for t in feats["LinearPattern"]["transforms"]],
                         [[20.0, 0, 0], [40.0, 0, 0]])
        self.assertEqual(feats["Fillet"]["expressions"]["radius"], ["/", ["var", "T"], ["num", 5.0]])
        self.assertEqual(feats["Fillet"]["edges"][0]["p2"], [80.0, 0.0, 10.0])

    def test_rules_catch_broken_data(self):
        f, _ = self.written()
        seq = f.by_name("PROCEDURAL_SOLID_REPRESENTATION_SEQUENCE")[0]
        seq.records = [r for r in seq.records if r.name != "SOLID_MODEL"]
        bp = f.by_name("BOUND_VARIATIONAL_PARAMETER")[0]
        bp.records[0].params[2] = "renamed"
        iar = f.by_name("INSTANCE_ATTRIBUTE_REFERENCE")[0]
        iar.records[0].params[0] = "GEOMETRY_SCHEMA.CIRCLE.WIDTH"
        msgs = " ".join(i.message for i in iso10303.rules(f))
        self.assertIn("procedural_solid_representation_sequence WR1", msgs)
        self.assertIn("variational_parameter WR2", msgs)
        self.assertIn("instance_attribute_reference", msgs)

    def test_expressions(self):
        e = ["+", ["*", ["var", "L"], ["num", 2]], ["call", "sqrt", [["var", "T"]]]]
        self.assertEqual(parametric.expr_text(e), "L * 2 + sqrt(T)")
        self.assertAlmostEqual(parametric.expr_eval(e, {"L": 3, "T": 16}), 10.0)

    def test_primitives_and_booleans(self):
        model = {"name": "CSG", "parameters": [{"name": "R", "value": 5.0, "unit": "mm"}], "sketches": [],
                 "features": [
                     {"type": "box", "name": "Box", "x": 10, "y": 20, "z": 30, "placement": XY},
                     {"type": "cylinder", "name": "Cyl", "radius": 5, "height": 40, "placement": XY,
                      "expressions": {"radius": ["var", "R"]}},
                     {"type": "boolean", "name": "Cut", "op": "difference", "first": "Box", "second": "Cyl"}]}
        f, _ = self.written(model)
        self.assertEqual([i for i in iso10303.check(f) if i.level == "error"], [])
        m = parametric.from_step(f)[0][0]
        self.assertEqual([ft["type"] for ft in m["features"]], ["box", "cylinder", "boolean"])
        self.assertEqual(m["features"][2]["first"], "Box")
        self.assertEqual(m["features"][1]["expressions"], {"radius": ["var", "R"]})


if __name__ == "__main__":
    unittest.main()
