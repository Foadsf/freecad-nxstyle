# SPDX-License-Identifier: LGPL-2.1-or-later
"""ISO 10303: Part 21 files, EXPRESS checking, and parametric models in STEP (no FreeCAD needed)."""

import copy
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import express, express_eval, iso10303, p21, parametric, procedural_sketch  # noqa: E402


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

    def test_complex_record_order(self):
        # ISO 10303-21 5.2: upper-case names in the basic alphabet's order, where "_" comes after the letters
        d = express.Dictionary.from_text("""SCHEMA s; ENTITY b_spline SUBTYPE OF (bounded); END_ENTITY;
            ENTITY bounded; END_ENTITY; END_SCHEMA;""")
        head = "ISO-10303-21;HEADER;FILE_DESCRIPTION((''),'2;1');FILE_NAME('','2026-01-01T00:00',(''),(''),'','','');" \
               "FILE_SCHEMA(('S'));ENDSEC;DATA;"
        ok = p21.loads(head + "#1=(BOUNDED()B_SPLINE());ENDSEC;END-ISO-10303-21;")
        bad = p21.loads(head + "#1=(B_SPLINE()BOUNDED());ENDSEC;END-ISO-10303-21;")
        order = "partial records of a complex instance must be in name order (10.2.5.3)"
        self.assertNotIn(order, [i.message for i in express.check(ok, d)])
        self.assertIn(order, [i.message for i in express.check(bad, d)])
        f = p21.File(("S",))
        f.add_complex([("B_SPLINE", []), ("BOUNDED", [])])
        self.assertEqual(f[1].names, ["BOUNDED", "B_SPLINE"])

    def test_resource_parts_in_the_dictionary(self):
        # ISO 10303-41, ISO 10303-50 and ISO 13584-20 come from the parts themselves, not from a stand-in
        d = iso10303.dictionary()
        for name, schema in (("product_definition", "product_definition_schema"),
                             ("maths_real_variable", "mathematical_functions_schema"),
                             ("real_numeric_variable", "iso13584_expressions_schema"),
                             ("si_unit", "measure_schema")):
            self.assertEqual(d.entities[name]["schema"], schema)
        ops = d.attributes("plus_expression")[0]["type"]
        self.assertEqual(ops["of"], {"named": "numeric_expression"})       # ISO 13584-20 narrows the operands
        self.assertIn("maths_real", d.select_items("maths_value")[1])

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
        # every warning is a documented contradiction of the standards: 6.3.4 WR4's prose against 8.4.9 (once
        # per sketch), Cor.2's neutral_sketch_representation WR1 against its clause, and
        # variational_representation WR2 against the dual model (express_eval.KNOWN)
        known = ("WR4 as stated in prose", "contradicts the clause", "cannot be met here")
        self.assertTrue(all(any(k in w.message for k in known) for w in warnings), warnings)
        self.assertEqual(sum("WR4" in w.message for w in warnings), 2)
        # every rule of the schemas was decided: the file has no B-rep from an AP the bundled schemas lack
        self.assertTrue(any(i.message.endswith(", 0 not evaluated") for i in issues if i.level == "info"))
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
        bp.records[0].params[2] = "renamed"                  # maths_variable.name (a simple instance)
        iar = f.by_name("INSTANCE_ATTRIBUTE_REFERENCE")[0]
        iar.records[0].params[0] = "GEOMETRY_SCHEMA.CIRCLE.WIDTH"
        msgs = " ".join(i.message for i in iso10303.check(f) if i.level == "error")
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


def poly_face(pts, normal):
    """A planar face through the points (in order), its plane normal given."""
    edges = []
    for a, b in zip(pts, pts[1:] + pts[:1]):
        edges.append({"curve": {"type": "line", "origin": list(a), "dir": [b[i] - a[i] for i in range(3)]},
                      "p1": list(a), "p2": list(b)})
    x = [pts[1][i] - pts[0][i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in x))
    return {"surface": {"type": "plane", "origin": list(pts[0]), "axis": list(normal), "x": [c / n for c in x]},
            "loops": [edges]}


def box_brep_text(x0, y0, z0, x1, y1, z1):
    """Part 21 text of a box as a MANIFOLD_SOLID_BREP (what OpenCASCADE writes for a hybrid step)."""
    f = p21.File(("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF",))
    w = parametric._Writer(f)
    c = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    quads = [((0, 2, 3, 1), (0, 0, -1)), ((4, 5, 7, 6), (0, 0, 1)), ((0, 1, 5, 4), (0, -1, 0)),
             ((2, 6, 7, 3), (0, 1, 0)), ((0, 4, 6, 2), (-1, 0, 0)), ((1, 3, 7, 5), (1, 0, 0))]
    faces = [w.face(poly_face([c[i] for i in q], nrm)) for q, nrm in quads]
    f.add("MANIFOLD_SOLID_BREP", "box", f.add("CLOSED_SHELL", "", faces))
    return p21.dumps(f)


def line_edge(a, b):
    return {"curve": {"type": "line", "origin": list(a), "dir": [b[i] - a[i] for i in range(3)]}, "p1": list(a),
            "p2": list(b)}


def base_model():
    m = copy.deepcopy(PLATE)
    m["features"] = m["features"][:1]
    m["sketches"] = [copy.deepcopy(PLATE["sketches"][0])]
    return m


def boss_sketch(name, cx, cy, r, z):
    return {"name": name, "placement": {"origin": [0, 0, z], "axis": [0, 0, 1], "x": [1, 0, 0]},
            "faces": [circle_face(cx, cy, r, z)], "geometry": [{"type": "circle", "c": [cx, cy], "r": r}],
            "constraints": [{"type": "Radius", "first": 0, "value": r}]}


class HistoryGaps(unittest.TestCase):
    """Holes, mirrors, patterns of several features, up-to extents, sweeps, hybrid steps and attachments."""

    def written(self, model):
        f, notes = parametric.to_step(copy.deepcopy(model))
        f = p21.loads(p21.dumps(f))
        errors = [i for i in iso10303.check(f) if i.level == "error"]
        self.assertEqual(errors, [])
        models, rnotes = parametric.from_step(f)
        return f, models[0], notes + rnotes

    def test_holes(self):
        m = base_model()
        m["features"] += [
            {"type": "hole", "name": "Hole", "positions": [[10, 10, 10], [30, 10, 10]], "axis": [0, 0, 1],
             "x": [1, 0, 0], "radii": [2.0], "depths": [6.0], "bottom": "flat", "fillet_radius": 0.0},
            {"type": "hole", "name": "Counterbore", "positions": [[10, 25, 10]], "axis": [0, 0, 1], "x": [1, 0, 0],
             "radii": [3.5, 2.0], "depths": [3.0, 5.0], "bottom": "conical", "semi_apex": math.radians(59),
             "tip_radius": 0.0},
            {"type": "hole", "name": "Countersink", "positions": [[10, 40, 10], [30, 40, 10]], "axis": [0, 0, 1],
             "x": [1, 0, 0], "radii": [2.0], "depths": [10.0], "through": True, "exit_depths": [10.0, 10.0],
             "transitions": [{"number": 1, "apex": math.radians(90), "radius": 3.5}],
             "exit_faces": [[rect_face(0, 0, 80, 50, 0)], [rect_face(0, 0, 80, 50, 0)]]}]
        f, got, _ = self.written(m)
        self.assertEqual(len(f.by_name("SOLID_WITH_FLAT_BOTTOM_ROUND_HOLE")), 2)
        self.assertEqual(len(f.by_name("SOLID_WITH_CONICAL_BOTTOM_ROUND_HOLE")), 1)
        through = f.by_name("SOLID_WITH_THROUGH_DEPRESSION")
        self.assertEqual(len(through), 2)
        self.assertTrue(all("SOLID_WITH_STEPPED_ROUND_HOLE_AND_CONICAL_TRANSITIONS" in i.names for i in through))
        feats = {ft["name"]: ft for ft in got["features"]}
        self.assertEqual([ft["type"] for ft in got["features"]], ["extrude", "hole", "hole", "hole"])
        h = feats["Hole"]
        self.assertEqual((h["positions"], h["radii"], h["depths"], h["bottom"]),
                         ([[10.0, 10.0, 10.0], [30.0, 10.0, 10.0]], [2.0], [6.0], "flat"))
        self.assertEqual(h["axis"], [0.0, 0.0, 1.0])            # out of the hole entrance (111, 4.4.22)
        cb = feats["Counterbore"]
        self.assertEqual((cb["radii"], cb["depths"], cb["bottom"]), ([3.5, 2.0], [3.0, 5.0], "conical"))
        self.assertAlmostEqual(cb["semi_apex"], math.radians(59))
        cs = feats["Countersink"]
        self.assertTrue(cs["through"])
        self.assertEqual(cs["transitions"][0]["number"], 1)
        self.assertAlmostEqual(cs["transitions"][0]["apex"], math.pi / 2)
        self.assertEqual(cs["exit_depths"], [10.0, 10.0])
        self.assertEqual(len(cs["exit_faces"]), 2)

    def test_mirror_and_patterns_of_several(self):
        m = base_model()
        m["sketches"] += [boss_sketch("BossSketch", 10, 10, 3, 10), boss_sketch("PocketSketch", 25, 12, 2, 10)]
        mirror = {"matrix": [[1, 0, 0], [0, -1, 0], [0, 0, 1]], "translation": [0, 50, 0]}
        lin = [{"matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "translation": [0, 7.0 * k, 0]} for k in (1, 2)]
        rot = parametric._compose({"matrix": [[0, -1, 0], [1, 0, 0], [0, 0, 1]], "translation": [0, 0, 0]},
                                  parametric.IDENTITY)
        m["features"] += [
            {"type": "extrude", "name": "Boss", "sketch": "BossSketch", "direction": [0, 0, 1], "first": 4.0,
             "second": 0.0, "op": "union"},
            {"type": "extrude", "name": "Pocket", "sketch": "PocketSketch", "direction": [0, 0, -1], "first": 5.0,
             "second": 0.0, "op": "difference"},
            {"type": "pattern", "name": "Mirrored", "sources": ["Boss", "Pocket"], "kind": "mirror",
             "transforms": [mirror]},
            {"type": "pattern", "name": "LinearPattern", "sources": ["Boss", "Pocket"], "kind": "linear",
             "transforms": lin},
            {"type": "pattern", "name": "MultiTransform", "sources": ["Boss"], "kind": "multi",
             "steps": [{"name": "Step1", "kind": "linear", "transforms": lin[:1]},
                       {"name": "Step2", "kind": "polar", "transforms": [rot]}]}]
        f, got, _ = self.written(m)
        feats = {ft["name"]: ft for ft in got["features"]}
        mi = feats["Mirrored"]
        self.assertEqual((mi["kind"], mi["sources"]), ("mirror", ["Boss", "Pocket"]))
        self.assertLess(parametric._det(mi["transforms"][0]["matrix"]), 0)       # left-handed axes
        self.assertEqual(mi["transforms"][0]["translation"], [0.0, 50.0, 0.0])
        self.assertEqual(len(f.by_name("SOLID_REPLICA")), 2 + 4 + 3)
        lp = feats["LinearPattern"]
        self.assertEqual((lp["kind"], lp["sources"], [t["translation"] for t in lp["transforms"]]),
                         ("linear", ["Boss", "Pocket"], [[0.0, 7.0, 0.0], [0.0, 14.0, 0.0]]))
        mt = feats["MultiTransform"]
        self.assertEqual((mt["kind"], [st["kind"] for st in mt["steps"]]), ("multi", ["linear", "polar"]))
        self.assertEqual(len(mt["transforms"]), 3)                           # 2 x 2 placements, less the original
        self.assertEqual(mt["steps"][1]["transforms"][0]["matrix"], [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0],
                                                                    [0.0, 0.0, 1.0]])

    def test_up_to(self):
        m = base_model()
        top = rect_face(0, 0, 80, 50, 10)
        m["sketches"] += [boss_sketch("Riser", 20, 20, 4, -5), boss_sketch("Post", 60, 20, 3, -5),
                          boss_sketch("Drill", 40, 20, 2, 10)]
        m["features"] += [
            {"type": "extrude", "name": "PadToFace", "sketch": "Riser", "direction": [0, 0, 1], "first": 15.0,
             "second": 0.0, "intent": ["unspecified", "blind"], "op": "union", "up_to": {"face": top, "offset": 0.0}},
            {"type": "extrude", "name": "PadOffset", "sketch": "Post", "direction": [0, 0, 1], "first": 20.0,
             "second": 0.0, "intent": ["unspecified", "blind"], "op": "union", "up_to": {"face": top, "offset": 5.0}},
            {"type": "extrude", "name": "PadShort", "sketch": "Post", "direction": [0, 0, 1], "first": 12.0,
             "second": 0.0, "intent": ["unspecified", "blind"], "op": "union", "up_to": {"face": top, "offset": -3.0}},
            {"type": "extrude", "name": "PocketToFirst", "sketch": "Drill", "direction": [0, 0, -1], "first": 10.0,
             "second": 0.0, "intent": ["up_to_next", "blind"], "op": "difference",
             "up_to": {"face": rect_face(0, 0, 80, 50, 0), "offset": 0.0}},
            {"type": "revolve", "name": "RevolveToFace", "sketch": "Drill", "op": "union", "angle": 1.0, "second": 0.0,
             "axis": {"origin": [0, 20, 10], "dir": [1, 0, 0]}, "up_to": {"face": top}}]
        f, got, _ = self.written(m)
        feats = {ft["name"]: ft for ft in got["features"]}
        self.assertEqual(feats["PadToFace"]["intent"][0], "unspecified")
        self.assertEqual(feats["PadToFace"]["up_to"]["offset"], 0.0)
        self.assertEqual(feats["PadToFace"]["up_to"]["face"]["surface"]["origin"], [0.0, 0.0, 10.0])
        self.assertEqual((feats["PadOffset"]["intent"][0], feats["PadOffset"]["up_to"]["offset"]), ("offset", 5.0))
        self.assertEqual(feats["PadShort"]["up_to"]["offset"], -3.0)   # the side, from the depth
        self.assertEqual(feats["PocketToFirst"]["intent"][0], "up_to_next")
        self.assertIn("up_to", feats["RevolveToFace"])
        recs = [r for i in f.by_name("EXTRUDED_FACE_SOLID_WITH_TRIM_CONDITIONS") for r in i.records]
        self.assertTrue(any(isinstance(r.params[4], p21.Ref) and r.params[6] == "OFFSET" and r.params[8] == 5.0
                            for r in recs))

    def test_pipe(self):
        m = base_model()
        prof = boss_sketch("PipeProfile", 30, 20, 2, 10)
        path = {"name": "Path", "placement": {"origin": [0, 20, 0], "axis": [0, -1, 0], "x": [1, 0, 0]},
                "faces": [], "constraints": [],
                "geometry": [{"type": "line", "p1": [30, 10], "p2": [30, 20]}]}
        arc = {"curve": {"type": "circle", "center": [40, 20, 20], "axis": [0, 1, 0], "x": [1, 0, 0], "r": 10.0},
               "p1": [30, 20, 20], "p2": [40, 20, 30]}
        m["sketches"] += [prof, path]
        m["features"].append({"type": "pipe", "name": "Pipe", "sketch": "PipeProfile", "path": "Path",
                              "path_edges": [line_edge([30, 20, 10], [30, 20, 20]), arc], "normal": [0, -1, 0],
                              "plane": path["placement"], "op": "union"})
        f, got, _ = self.written(m)
        sweep = f.by_name("SURFACE_CURVE_SWEPT_FACE_SOLID")
        self.assertEqual(len(sweep), 1)
        total = sweep[0].params[4]
        self.assertAlmostEqual(total, 10 + math.pi / 2 * 1.0)   # the line's length plus the arc's angle (42, 4.4.41)
        ft = got["features"][1]
        self.assertEqual((ft["type"], ft["sketch"], ft["path"], ft["op"]), ("pipe", "PipeProfile", "Path", "union"))
        self.assertEqual(ft["normal"], [0.0, -1.0, 0.0])
        self.assertEqual(ft["path_edges"][1]["p2"], [40.0, 20.0, 30.0])
        # the swept face lies in z = 0 of the sweep's frame, centred on the directrix (42, 6.4.35 IP1)
        local = parametric._Reader(f).face(sweep[0].params[1])
        circle = local["loops"][0][0]
        self.assertTrue(all(abs(e["p1"][2]) < 1e-12 for loop in local["loops"] for e in loop))
        self.assertEqual([round(c, 12) for c in circle["curve"]["center"]], [0.0, 0.0, 0.0])
        self.assertAlmostEqual(circle["curve"]["r"], 2.0)

    def test_hybrid_steps(self):
        m = base_model()
        m["sketches"] += [boss_sketch("Loft1", 40, 20, 5, 10), boss_sketch("Loft2", 40, 20, 3, 20)]
        side = poly_face([(80, 0, 0), (80, 50, 0), (80, 50, 10), (80, 0, 10)], (1, 0, 0))
        m["features"] += [
            {"type": "explicit", "name": "Draft", "kind": "Draft", "op": None, "brep": box_brep_text(0, 0, 0, 79, 50, 10),
             "faces": [side], "neutral": {"plane": XY, "name": "XY_Plane"},
             "params": {"angle": math.radians(4), "reversed": False}},
            {"type": "fillet", "name": "Fillet", "radius": 1.0,
             "edges": [{"curve": {"type": "line", "origin": [0, 0, 0], "dir": [0, 0, 1]}, "p1": [0, 0, 0],
                        "p2": [0, 0, 10]}]},
            {"type": "explicit", "name": "Loft", "kind": "AdditiveLoft", "op": "union",
             "brep": box_brep_text(35, 15, 10, 45, 25, 20), "profile": "Loft1", "sections": ["Loft2"],
             "params": {"ruled": True, "closed": False}},
            {"type": "pattern", "name": "LoftCopy", "sources": ["Loft"], "kind": "linear",
             "transforms": [{"matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "translation": [20, 0, 0]}]}]
        f, got, notes = self.written(m)
        self.assertEqual(len(f.by_name("MANIFOLD_SOLID_BREP")), 2)
        feats = {ft["name"]: ft for ft in got["features"]}
        self.assertEqual([ft["type"] for ft in got["features"]], ["extrude", "explicit", "fillet", "explicit", "pattern"])
        dr = feats["Draft"]
        self.assertEqual((dr["kind"], dr["op"], dr["neutral"]["name"]), ("Draft", None, "XY_Plane"))
        self.assertAlmostEqual(dr["params"]["angle"], math.radians(4))
        self.assertIs(dr["params"]["reversed"], False)
        self.assertEqual(dr["faces"][0]["surface"]["axis"], [1.0, 0.0, 0.0])
        self.assertEqual(feats["Fillet"]["base"], "Draft")
        lo = feats["Loft"]
        self.assertEqual((lo["kind"], lo["op"], lo["profile"], lo["sections"]), ("AdditiveLoft", "union", "Loft1",
                                                                                  ["Loft2"]))
        self.assertEqual(feats["LoftCopy"]["sources"], ["Loft"])
        self.assertTrue(any("hybrid" in n for n in notes))

    def test_attachments(self):
        m = base_model()
        m["sketches"][0]["attachment"] = {"mode": "FlatFace", "plane": XY, "name": "XY_Plane"}
        on_top = boss_sketch("OnTop", 20, 20, 3, 10)
        on_top["attachment"] = {"mode": "FlatFace", "face": rect_face(0, 0, 80, 50, 10),
                                "plane": {"origin": [0, 0, 10], "axis": [0, 0, 1], "x": [1, 0, 0]}}
        above = boss_sketch("Above", 50, 20, 3, 13)
        above["attachment"] = dict(on_top["attachment"], offset=3.0)
        m["sketches"] += [on_top, above]
        f, got, _ = self.written(m)
        att = [i for i in f.by_name("INCIDENCE_GEOMETRIC_CONSTRAINT") if i.params[0].endswith(".attachment")]
        self.assertEqual(len(att), 2)
        sks = {sk["name"]: sk for sk in got["sketches"]}
        self.assertEqual((sks["Base"]["attachment"]["name"], sks["Base"]["attachment"]["offset"]), ("XY_Plane", 0.0))
        self.assertNotIn("face", sks["Base"]["attachment"])
        self.assertEqual(sks["OnTop"]["attachment"]["face"]["surface"]["origin"], [0.0, 0.0, 10.0])
        self.assertEqual(sks["Above"]["attachment"]["offset"], 3.0)
        self.assertEqual(len(f.by_name("SDGC_WITH_DIMENSION")), 1)


def part112_file():
    """A Part 112 sketch: rectangle 40 x 20 with a trimmed R3 fillet in its bottom right corner, a hexagon,
    two arcs, a circle copied 10 to the right, that copy in a circular pattern, and a tangent line."""
    f = p21.File(("PROCEDURAL_SKETCH_SCHEMA",), name="part112")
    P = lambda x, y: f.add("CARTESIAN_POINT", "", [float(x), float(y)])    # noqa: E731
    E = p21.Enum
    ctx = f.add("GEOMETRIC_REPRESENTATION_CONTEXT", "2D", "", 2)
    o, a, b = P(0, 0), P(40, 0), P(40, 20)
    cmds = [f.add("CREATE_RECTANGLE", "rect", o, a, b),
            f.add("CREATE_POLYGON", "hex", 6.0, P(60, 10), P(70, 10), E("INSCRIBED"), 10.0),
            f.add("CREATE_CIRCULAR_ARC_3_POINTS", "a3", P(10, 30), P(20, 40), P(30, 30)),
            f.add("CREATE_CIRCULAR_ARC_START_END_RADIUS", "ser", P(0, 50), P(10, 50), 5.0, E("CCW"))]

    def tline(p, q):
        d = f.add("DIRECTION", "", [1.0 if p[0] != q[0] else 0.0, 1.0 if p[1] != q[1] else 0.0])
        ln = f.add("LINE", "", P(*p), f.add("VECTOR", "", d, 1.0))
        return f.add("TRIMMED_CURVE", "", ln, [P(*p)], [P(*q)], True, E("CARTESIAN"))
    bottom, right = tline((0, 0), (40, 0)), tline((40, 0), (40, 20))
    # the selection as a geometric item (ISO 10303-55 5.4.4 WR1); Part 112's 4.2.2 example writes it simple
    sel = f.add_complex([("GEOMETRIC_REPRESENTATION_ITEM", []), ("REPRESENTATION_ITEM", [""]),
                         ("USER_SELECTED_ELEMENTS", [[bottom, right]]), ("USER_SELECTED_SHAPE_ELEMENTS", [])])
    cmds += [sel,
             f.add("CREATE_FILLET", "f", bottom, False, right, False, 3.0, True, P(39, 1))]
    cmds.append(f.add("CREATE_CIRCLE_CENTRE_POINT", "c", P(100, 0), 4.0))
    circle = f.add("CIRCLE", "", f.add("AXIS2_PLACEMENT_2D", "", P(100, 0), f.add("DIRECTION", "", [1.0, 0.0])), 4.0)
    sel = f.add("GEOMETRIC_CURVE_SET", "", [circle])
    cmds.append(f.add("SKETCH_TRANSFORM_TRANSLATE", "t", sel, True, 10.0, 0.0))
    copy = f.add("CIRCLE", "", f.add("AXIS2_PLACEMENT_2D", "", P(110, 0), f.add("DIRECTION", "", [1.0, 0.0])), 4.0)
    cmds.append(f.add("CREATE_PATTERN_CIRCULAR", "pc", [copy], f.add("GEOMETRIC_CURVE_SET", "", [copy]), 3,
                      math.pi / 2, P(100, 0), True, P(110, 0)))
    near_point = P(100, 4)
    # a near point is a hint, not geometry; a representation in the sketch's context founds it (43 WR1)
    f.add("REPRESENTATION", "near points", [near_point], ctx)
    near = f.add("NEAR_POINT_RELATIONSHIP", "", p21.UNSET, circle, near_point)
    cmds.append(f.add("CREATE_LINE_SEGMENT_POINT_TANGENT", "tan", P(100, 20), circle, near))
    seq = f.add("PROCEDURAL_SHAPE_REPRESENTATION_SEQUENCE", "sketch", cmds, [], "Part 112 test")
    f.add("PROCEDURAL_SHAPE_REPRESENTATION", "Part112 commands", [seq], ctx)
    return p21.loads(p21.dumps(f))


class Part112(unittest.TestCase):
    def test_circle_through_three_points(self):
        c, r = procedural_sketch.circle_3((10, 30), (20, 40), (30, 30))
        self.assertEqual((round(c[0], 9), round(c[1], 9), round(r, 9)), (20.0, 30.0, 10.0))
        with self.assertRaises(ValueError):
            procedural_sketch.circle_3((0, 0), (1, 1), (2, 2))

    def test_file_is_valid(self):
        errors = [i for i in iso10303.check(part112_file()) if i.level == "error"]
        self.assertEqual(errors, [])

    def test_evaluation(self):
        models, notes = parametric.from_step(part112_file())
        sk = models[0]["sketches"][0]
        g = sk["geometry"]
        self.assertEqual(sk["name"], "Part112")
        # rectangle 4, hexagon 6, two arcs, the fillet, the circle, its copy, 3 pattern copies, the tangent line
        self.assertEqual(len(g), 19)
        near = lambda p, q: all(abs(x - y) < 1e-9 for x, y in zip(p, q))   # noqa: E731
        lines = [x for x in g if x["type"] == "line"]
        # the rectangle, its bottom and right sides trimmed by the fillet
        self.assertTrue(any(near(x["p1"], [0, 0]) and near(x["p2"], [37, 0]) for x in lines), lines[:4])
        self.assertTrue(any(near(x["p1"], [40, 3]) and near(x["p2"], [40, 20]) for x in lines))
        fil = [x for x in g if x["type"] == "arc" and abs(x["r"] - 3) < 1e-9][0]
        self.assertTrue(near(fil["c"], [37, 3]))
        self.assertEqual({tuple(fil["p1"]), tuple(fil["p2"])}, {(37.0, 0.0), (40.0, 3.0)})
        hexa = [x for x in lines if all(abs(math.dist(x[k], (60, 10)) - 10) < 1e-9 for k in ("p1", "p2"))]
        self.assertEqual(len(hexa), 6)
        a3 = [x for x in g if x["type"] == "arc" and abs(x["r"] - 10) < 1e-9][0]
        self.assertTrue(near(a3["c"], [20, 30]) and near(a3["p1"], [30, 30]) and near(a3["p2"], [10, 30]))
        ser = [x for x in g if x["type"] == "arc" and abs(x["r"] - 5) < 1e-9][0]
        self.assertTrue(near(ser["c"], [5, 50]))
        circles = sorted(tuple(round(v, 9) for v in x["c"]) for x in g if x["type"] == "circle")
        self.assertEqual(circles, [(90.0, 0.0), (100.0, -10.0), (100.0, 0.0), (100.0, 10.0), (110.0, 0.0)])
        tan = [x for x in lines if near(x["p1"], [100, 20])][0]
        self.assertAlmostEqual(math.dist(tan["p1"], tan["p2"]), math.sqrt(20 ** 2 - 4 ** 2))
        self.assertFalse([n for n in notes if "not evaluated" in n or "matches nothing" in n], notes)

    def test_written_commands_reproduce_the_sketch(self):
        model = copy.deepcopy(PLATE)
        model["sketches"][1]["geometry"].append({"type": "arc", "c": [0, 0], "r": 5, "p1": [5, 0], "p2": [0, 5]})
        f, notes = parametric.to_step(model, sketch_commands=True)
        f = p21.loads(p21.dumps(f))
        self.assertIn("CREATE_LINE_SEGMENT_2_POINTS", {i.name for i in f})
        self.assertEqual([i for i in iso10303.check(f) if i.level == "error"], [])
        _, rnotes = parametric.from_step(f)
        self.assertIn("Base: its ISO 10303-112 commands make 5 of its 5 curves", rnotes)   # with its centreline
        self.assertIn("Hole: its ISO 10303-112 commands make 2 of its 2 curves", rnotes)


class Units(unittest.TestCase):
    def test_inch_and_degree(self):
        f = p21.File(("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF",))
        mm = f.add_complex([("LENGTH_UNIT", []), ("NAMED_UNIT", [p21.DERIVED]), ("SI_UNIT", [p21.Enum("MILLI"),
                                                                                           p21.Enum("METRE")])])
        inch = f.add_complex([("CONVERSION_BASED_UNIT", ["INCH", f.add("LENGTH_MEASURE_WITH_UNIT",
                                                                        p21.Typed("LENGTH_MEASURE", 25.4), mm)]),
                              ("LENGTH_UNIT", []), ("NAMED_UNIT", [p21.DERIVED])])
        rad = f.add_complex([("NAMED_UNIT", [p21.DERIVED]), ("PLANE_ANGLE_UNIT", []), ("SI_UNIT", [p21.UNSET,
                                                                                                p21.Enum("RADIAN")])])
        deg = f.add_complex([("CONVERSION_BASED_UNIT", ["DEGREE", f.add("PLANE_ANGLE_MEASURE_WITH_UNIT",
                                                                         p21.Typed("PLANE_ANGLE_MEASURE",
                                                                                   math.pi / 180), rad)]),
                             ("NAMED_UNIT", [p21.DERIVED]), ("PLANE_ANGLE_UNIT", [])])
        ctx = f.add_complex([("GEOMETRIC_REPRESENTATION_CONTEXT", [3]), ("GLOBAL_UNIT_ASSIGNED_CONTEXT", [[inch, deg]]),
                             ("REPRESENTATION_CONTEXT", ["", ""])])
        rd = parametric._Reader(p21.loads(p21.dumps(f)))
        rd.use_units(ctx)
        self.assertAlmostEqual(rd.L, 25.4)
        self.assertAlmostEqual(rd.A, math.pi / 180)


class ApplicationProtocols(unittest.TestCase):
    HEAD = "ISO-10303-21;HEADER;FILE_DESCRIPTION((''),'2;1');FILE_NAME('','2026-01-01T00:00',(''),(''),'','','');"

    def test_identify(self):
        f = p21.loads(self.HEAD + "FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF. {1 0 10303 442 1 1 4 }'))"
                                  ";ENDSEC;DATA;ENDSEC;END-ISO-10303-21;")
        i = iso10303.identify(f)[0]
        self.assertEqual((i["ap"], i["edition"]), ("AP242", "object identifier version 1"))
        f = p21.loads(self.HEAD + "FILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));ENDSEC;DATA;ENDSEC;END-ISO-10303-21;")
        self.assertEqual(iso10303.identify(f)[0]["ap"], "AP203")

    def test_bom(self):
        rows = ["#1=PRODUCT('ASM','Assembly','',());", "#2=PRODUCT('BOLT','Bolt','',());",
                "#3=PRODUCT('SUB','Sub','',());", "#11=PRODUCT_DEFINITION_FORMATION('','',#1);",
                "#12=PRODUCT_DEFINITION_FORMATION('','',#2);", "#13=PRODUCT_DEFINITION_FORMATION('','',#3);",
                "#21=PRODUCT_DEFINITION('design','',#11,#9);", "#22=PRODUCT_DEFINITION('design','',#12,#9);",
                "#23=PRODUCT_DEFINITION('design','',#13,#9);",
                "#31=NEXT_ASSEMBLY_USAGE_OCCURRENCE('1','','',#21,#23,$);",
                "#32=NEXT_ASSEMBLY_USAGE_OCCURRENCE('2','','',#21,#23,$);",
                "#33=NEXT_ASSEMBLY_USAGE_OCCURRENCE('3','','',#23,#22,$);",
                "#34=NEXT_ASSEMBLY_USAGE_OCCURRENCE('4','','',#23,#22,$);",
                "#35=NEXT_ASSEMBLY_USAGE_OCCURRENCE('5','','',#23,#22,$);", "#9=PRODUCT_DEFINITION_CONTEXT('','','');"]
        f = p21.loads(self.HEAD + "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));ENDSEC;DATA;" + "".join(rows) +
                      "ENDSEC;END-ISO-10303-21;")
        b = iso10303.bom(f)
        self.assertEqual(len(b["roots"]), 1)
        self.assertEqual(b["roots"][0]["children"][0]["quantity"], 2)
        self.assertEqual(b["parts"], [{"id": "BOLT", "name": "Bolt", "quantity": 6}])

    def test_long_form_schema(self):
        # an AP long form is one schema with every entity in it; the parser takes its algorithms and rules
        text = """SCHEMA tiny_ap_mim_lf; TYPE label = STRING; END_TYPE;
        ENTITY product; id : label; name : label; END_ENTITY;
        FUNCTION f(a : GENERIC : g) : GENERIC : g; LOCAL x : INTEGER := 0; END_LOCAL;
          REPEAT i := 1 TO 3; IF i > 1 THEN x := x + i; END_IF; END_REPEAT; RETURN (a); END_FUNCTION;
        RULE r FOR (product); WHERE WR1: SIZEOF(product) >= 0; END_RULE;
        SUBTYPE_CONSTRAINT sc FOR product; END_SUBTYPE_CONSTRAINT; END_SCHEMA;"""
        d = express.Dictionary.from_text(text)
        self.assertEqual([a["name"] for a in d.attributes("product")], ["id", "name"])


TINY = """SCHEMA tiny;
TYPE pos = REAL; WHERE WR1: SELF > 0.0; END_TYPE;
TYPE shape_select = SELECT (circle, square); END_TYPE;
TYPE kind = ENUMERATION OF (round, flat); END_TYPE;
ENTITY item ABSTRACT SUPERTYPE OF (ONEOF (circle, square)); name : STRING; END_ENTITY;
ENTITY circle SUBTYPE OF (item); r : pos;
  DERIVE d : REAL := 2.0 * r;
  INVERSE owners : SET [0:?] OF holder FOR members;
  WHERE WR1: d < 100.0; END_ENTITY;
ENTITY square SUBTYPE OF (item); side : pos; UNIQUE UR1: SELF\\item.name; END_ENTITY;
ENTITY holder; members : SET [1:?] OF shape_select; n : INTEGER; sizes : LIST [1:n] OF pos; k : kind;
  WHERE WR1: SIZEOF(QUERY(m <* members | 'TINY.CIRCLE' IN TYPEOF(m))) >= 1;
        WR2: 'TINY.SHAPE_SELECT' IN TYPEOF(members[1]);
        WR3: count_round(members) = SIZEOF(QUERY(m <* members | 'TINY.CIRCLE' IN TYPEOF(m)));
        WR4: (k = round) OR (k = flat);
        WR5: NOT EXISTS(unknown_function(SELF)) OR TRUE; END_ENTITY;
FUNCTION count_round (s : SET OF shape_select) : INTEGER;
  LOCAL c : INTEGER := 0; seen : SET OF shape_select := []; END_LOCAL;
  REPEAT i := 1 TO HIINDEX(s);
    IF 'TINY.CIRCLE' IN TYPEOF(s[i]) THEN c := c + 1; seen := seen + s[i] + s[i]; END_IF;
  END_REPEAT;
  IF SIZEOF(seen) <> c THEN RETURN (-1); END_IF;
  RETURN (c);
END_FUNCTION;
RULE one_holder FOR (holder); WHERE WR1: SIZEOF(holder) <= 1; END_RULE;
END_SCHEMA;"""


class ExpressRules(unittest.TestCase):
    """express_eval: the interpreter, and each kind of rule with a violation and a control."""
    HEAD = "ISO-10303-21;HEADER;FILE_DESCRIPTION((''),'2;1');FILE_NAME('','2026-01-01T00:00',(''),(''),'','','');" \
           "FILE_SCHEMA(('TINY'));ENDSEC;DATA;"

    def d(self):
        return express.Dictionary.from_text(TINY)

    def ev(self, text, rows=()):
        f = p21.loads(self.HEAD + "".join(rows) + "ENDSEC;END-ISO-10303-21;")
        e = express_eval.Evaluator(f, self.d())
        return e.eval(express_eval.parse_expr(text),
                      express_eval._Scope())

    def test_expressions(self):
        U = express_eval.UNKNOWN
        cases = {"1 + 2 * 3": 7, "7 DIV 2": 3, "7 MOD 3": 1, "2 ** 3": 8, "10 / 4": 2.5, "-ABS(-2.5)": -2.5,
                 "? + 1": None, "? = 1": U, "? AND FALSE": False, "? OR TRUE": True, "NOT UNKNOWN": U,
                 "TRUE XOR FALSE": True, "SIZEOF([1, 2, 2] + [3])": 4, "SIZEOF([1, 2] * [2, 3])": 1,
                 "2 IN [1, 2]": True, "[1, 2] <= [1, 2, 3]": True, "SIZEOF(QUERY(x <* [1, 5, 9] | x > 2))": 2,
                 "{1 <= 2 < 3}": True, "{1 <= 3 < 3}": False, "HIINDEX([4, 5, 6])": 3, "NVL(?, 4)": 4,
                 "EXISTS(?)": False, "ODD(3)": True, "SQRT(16.0)": 4.0, "[7, 8, 9][2]": 8, "[7][5]": None}
        for text, want in cases.items():
            self.assertEqual(self.ev(text), want, text)
        self.assertEqual(self.ev("'AB' + 'C'"), "ABC")
        self.assertEqual(self.ev("'ABC'[2]"), "B")
        self.assertIs(self.ev("'A12' LIKE '@##'"), True)
        self.assertIs(self.ev("VALUE('2.5') = 2.5"), True)
        self.assertEqual(sorted(self.ev("TYPEOF(3)")), ["INTEGER", "NUMBER", "REAL"])

    def file(self, rows):
        return p21.loads(self.HEAD + "".join(rows) + "ENDSEC;END-ISO-10303-21;")

    def test_rules_hold(self):
        rows = ["#1=CIRCLE('c',5.);", "#2=SQUARE('s',2.);", "#3=HOLDER((#1,#2),2,(1.,2.),.ROUND.);"]
        r = express_eval.rules(self.file(rows), self.d())
        self.assertEqual([i for i in r.issues if i.level == "error"], [])
        self.assertEqual(r.violated, 0)
        # the derived attribute, the inverse, the SELECT in TYPEOF, the function (a SET drops the duplicate)
        ev = express_eval.Evaluator(self.file(rows), self.d())
        c, h = ev.inst(1), ev.inst(3)
        self.assertEqual(ev.attribute(c, "d"), 10.0)
        self.assertEqual([x.pid for x in ev.attribute(c, "owners")], [3])
        self.assertIn("TINY.SHAPE_SELECT", ev.typeof(c))
        self.assertEqual(ev.eval(express_eval.parse_expr("COUNT_ROUND(MEMBERS)"), express_eval._Scope(self_=h,
                                                                                                         entity="holder")), 1)
        # the function the schema does not declare: reported, not guessed
        self.assertIn("holder.wr5", r.unevaluated)

    def test_rules_violated(self):
        rows = ["#1=CIRCLE('c',60.);", "#2=CIRCLE('n',-1.);", "#3=SQUARE('s',2.);", "#4=SQUARE('s',3.);",
                "#5=HOLDER((#3),1,(1.,2.),.ROUND.);", "#6=HOLDER((#1),1,(1.),.FLAT.);"]
        msgs = [f"#{i.id} {i.message}" for i in express_eval.rules(self.file(rows), self.d()).issues
                if i.level == "error"]
        text = "\n".join(msgs)
        self.assertIn("#1 circle WR1 is violated", text)                        # derived d = 120
        self.assertIn("#2 circle.r: the value -1. breaks pos WR1", text)        # a defined type's rule
        self.assertIn("#4 square UR1", text)                                    # UNIQUE over the population
        self.assertIn("#5 holder WR1 is violated", text)                        # no circle among the members
        self.assertIn("#5 holder.sizes has 2 element(s); its upper bound n is 1", text)
        self.assertIn("global rule one_holder WR1", text)
        self.assertNotIn("#6 holder", text)

    def test_unknown_entities_leave_rules_undecided(self):
        # an instance of an entity the schemas do not define may use #1: USEDIN-based rules are not decided
        d = express.Dictionary.from_text(TINY.replace("WR1: d < 100.0;", "WR1: SIZEOF(USEDIN(SELF, '')) > 0;"))
        f = self.file(["#1=CIRCLE('c',5.);", "#2=SOMETHING_ELSE(#1);"])
        r = express_eval.rules(f, d)
        self.assertEqual(r.violated, 0)
        self.assertIn("circle.wr1", r.unevaluated)

    def test_complex_constructor_and_group(self):
        ev = express_eval.Evaluator(self.file([]), self.d())
        s = express_eval._Scope()
        v = ev.eval(express_eval.parse_expr("CIRCLE(4.0) || ITEM('x')"), s)
        self.assertEqual(v.names, frozenset({"circle", "item"}))
        s.vars["V"] = v
        self.assertEqual(ev.eval(express_eval.parse_expr("V\\ITEM.NAME"), s), "x")
        self.assertEqual(ev.eval(express_eval.parse_expr("V.D"), s), 8.0)


if __name__ == "__main__":
    unittest.main()
