# SPDX-License-Identifier: LGPL-2.1-or-later
"""Parametric STEP round trip in a real FreeCAD (run with freecadcmd; not part of the unit tests):

    NXSTYLE_OUT=folder freecadcmd tests/fc_parametric_step.py

Builds a parametric plate (spreadsheet parameters, a constrained sketch, Pad, Pocket through all, linear
pattern, Fillet, Chamfer, Revolution, Thickness) and a Part CSG tree, exports each as STEP AP242 with its
ISO 10303-55/108/111 model, checks the file against ISO 10303, imports it into a new document, and compares:
the rebuilt solid with the original and with the explicit B-rep in the file, then both documents again after
the same parameter change. Prints one line per check and exits non-zero when one fails.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "NXStyle"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402
import Sketcher  # noqa: E402

from nxstyle import iso10303, p21, parametric_fc  # noqa: E402

OUT = os.environ.get("NXSTYLE_OUT") or tempfile.mkdtemp()
if os.path.exists(os.path.join(OUT, "results.txt")):
    os.remove(os.path.join(OUT, "results.txt"))
failures = []


def check(ok, what):
    line = ("PASS " if ok else "FAIL ") + what
    print(line, flush=True)
    with open(os.path.join(OUT, "results.txt"), "a", encoding="utf-8") as f:   # freecadcmd may drop stdout
        f.write(line + "\n")
    if not ok:
        failures.append(what)


def same(a, b, tol=1e-3):
    diff = a.cut(b).Volume + b.cut(a).Volume
    return diff <= tol * max(a.Volume, b.Volume, 1.0), diff


def plate():
    doc = App.newDocument("Plate")
    sh = doc.addObject("Spreadsheet::Sheet", "Spreadsheet")
    for cell, alias, value in (("A1", "Length", "80 mm"), ("A2", "Width", "50 mm"), ("A3", "Thick", "10 mm"),
                              ("A4", "HoleR", "6 mm")):
        sh.set(cell, value)
        sh.setAlias(cell, alias)
    doc.recompute()
    body = doc.addObject("PartDesign::Body", "Body")
    xy = body.Origin.OriginFeatures[3]
    sk = body.newObject("Sketcher::SketchObject", "Base")
    sk.AttachmentSupport = (xy, [""])
    sk.MapMode = "FlatFace"
    pts = [App.Vector(0, 0, 0), App.Vector(80, 0, 0), App.Vector(80, 50, 0), App.Vector(0, 50, 0)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        sk.addGeometry(Part.LineSegment(a, b), False)
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    for i, kind in enumerate(("Horizontal", "Vertical", "Horizontal", "Vertical")):
        sk.addConstraint(Sketcher.Constraint(kind, i))
    sk.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -1, 1))
    c = sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 80))
    sk.renameConstraint(c, "length")
    sk.setExpression("Constraints.length", "Spreadsheet.Length")
    c = sk.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, 50))
    sk.setExpression(f".Constraints[{c}]", "Spreadsheet.Width")
    doc.recompute()
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sk
    pad.Length = 10
    pad.setExpression("Length", "Spreadsheet.Thick")
    doc.recompute()
    edge = next(f"Edge{i + 1}" for i, e in enumerate(pad.Shape.Edges)
                if type(e.Curve).__name__ in ("Line", "LineSegment") and abs(e.Vertexes[0].Point.x - 80) < 1e-6
                and abs(e.Vertexes[0].Point.y) < 1e-6 and abs(e.Vertexes[-1].Point.x - 80) < 1e-6
                and abs(e.Vertexes[-1].Point.y) < 1e-6)
    fil = body.newObject("PartDesign::Fillet", "Fillet")
    fil.Base = (pad, [edge])
    fil.Radius = 3
    doc.recompute()
    edge = next(f"Edge{i + 1}" for i, e in enumerate(fil.Shape.Edges)
                if type(e.Curve).__name__ in ("Line", "LineSegment") and all(abs(v.Point.x) < 1e-6 and
                                                                              abs(v.Point.y) < 1e-6 for v in e.Vertexes))
    cham = body.newObject("PartDesign::Chamfer", "Chamfer")
    cham.Base = (fil, [edge])
    cham.Size = 2
    doc.recompute()
    hole = body.newObject("Sketcher::SketchObject", "HoleSketch")
    hole.AttachmentSupport = (xy, [""])
    hole.MapMode = "FlatFace"
    hole.AttachmentOffset = App.Placement(App.Vector(0, 0, 10), App.Rotation())
    hole.addGeometry(Part.Circle(App.Vector(15, 25, 0), App.Vector(0, 0, 1), 6), False)
    c = hole.addConstraint(Sketcher.Constraint("Radius", 0, 6))
    hole.setExpression(f".Constraints[{c}]", "Spreadsheet.HoleR")
    hole.addConstraint(Sketcher.Constraint("DistanceX", 0, 3, 15))
    hole.addConstraint(Sketcher.Constraint("DistanceY", 0, 3, 25))
    doc.recompute()
    pocket = body.newObject("PartDesign::Pocket", "Pocket")
    pocket.Profile = hole
    pocket.Type = "ThroughAll"
    doc.recompute()
    pat = body.newObject("PartDesign::LinearPattern", "LinearPattern")
    pat.Originals = [pocket]
    pat.Direction = (body.Origin.OriginFeatures[0], [""])
    pat.Length = 40
    pat.Occurrences = 3
    body.Tip = pat                                   # newObject leaves the Tip on the Pocket for a pattern
    doc.recompute()
    boss = body.newObject("Sketcher::SketchObject", "BossSketch")
    boss.AttachmentSupport = (body.Origin.OriginFeatures[4], [""])   # XZ plane
    boss.MapMode = "FlatFace"
    p = [App.Vector(60, 10, 0), App.Vector(66, 10, 0), App.Vector(66, 20, 0), App.Vector(60, 20, 0)]
    for a, b in zip(p, p[1:] + p[:1]):
        boss.addGeometry(Part.LineSegment(a, b), False)
    doc.recompute()
    rev = body.newObject("PartDesign::Revolution", "Revolution")
    rev.Profile = boss
    rev.ReferenceAxis = (boss, ["V_Axis"])
    rev.Angle = 40
    doc.recompute()
    return doc, body, sh


def cup():
    doc = App.newDocument("Cup")
    sh = doc.addObject("Spreadsheet::Sheet", "Spreadsheet")
    sh.set("A1", "20 mm")
    sh.setAlias("A1", "CupR")
    sh.set("A2", "2 mm")
    sh.setAlias("A2", "Wall")
    doc.recompute()
    body = doc.addObject("PartDesign::Body", "Body")
    cyl = body.newObject("PartDesign::AdditiveCylinder", "Cylinder")
    cyl.Radius, cyl.Height = 20, 30
    cyl.setExpression("Radius", "Spreadsheet.CupR")
    doc.recompute()
    top = max(range(len(cyl.Shape.Faces)), key=lambda i: cyl.Shape.Faces[i].CenterOfMass.z)
    th = body.newObject("PartDesign::Thickness", "Thickness")
    th.Base = (cyl, [f"Face{top + 1}"])
    th.Value = 2
    th.setExpression("Value", "Spreadsheet.Wall")
    doc.recompute()
    sk = body.newObject("Sketcher::SketchObject", "SideHole")
    sk.AttachmentSupport = (body.Origin.OriginFeatures[4], [""])   # XZ plane
    sk.MapMode = "FlatFace"
    sk.addGeometry(Part.Circle(App.Vector(0, 15, 0), App.Vector(0, 0, 1), 4), False)
    sk.addConstraint(Sketcher.Constraint("Radius", 0, 4))
    doc.recompute()
    pocket = body.newObject("PartDesign::Pocket", "Pocket")
    pocket.Profile = sk
    pocket.Type = "ThroughAll"
    pocket.SideType = "Symmetric"
    doc.recompute()
    pat = body.newObject("PartDesign::PolarPattern", "PolarPattern")
    pat.Originals = [pocket]
    pat.Axis = (body.Origin.OriginFeatures[2], [""])          # Z axis
    pat.Angle = 360
    pat.Occurrences = 3
    body.Tip = pat
    doc.recompute()
    return doc, body, sh


def csg():
    doc = App.newDocument("CSG")
    sh = doc.addObject("Spreadsheet::Sheet", "Spreadsheet")
    sh.set("A1", "4 mm")
    sh.setAlias("A1", "CylR")
    doc.recompute()
    box = doc.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 30, 20, 10
    cyl = doc.addObject("Part::Cylinder", "Cylinder")
    cyl.Radius, cyl.Height = 4, 30
    cyl.setExpression("Radius", "Spreadsheet.CylR")
    cyl.Placement = App.Placement(App.Vector(15, 10, -5), App.Rotation())
    cone = doc.addObject("Part::Cone", "Cone")
    cone.Radius1, cone.Radius2, cone.Height = 2, 6, 8
    cone.Placement = App.Placement(App.Vector(5, 5, 6), App.Rotation())
    cut = doc.addObject("Part::Cut", "Cut")
    cut.Base, cut.Tool = box, cyl
    fuse = doc.addObject("Part::Fuse", "Fuse")
    fuse.Base, fuse.Tool = cut, cone
    doc.recompute()
    return doc, fuse, sh


def roundtrip(name, doc, obj, sheet, changes):
    path = os.path.join(OUT, f"{name}.step")
    report = parametric_fc.export(obj, path)
    print(report)
    issues = iso10303.check(path)
    check(not [i for i in issues if i.level == "error"], f"{name}: no ISO 10303 errors in the written file")
    inv = iso10303.inventory(p21.read(path))
    check("ISO 10303-55" in inv and "ISO 10303-108" in inv, f"{name}: file holds Parts 55 and 108 data")
    explicit = Part.read(path)
    ok, diff = same(obj.Shape, explicit)
    check(ok, f"{name}: explicit B-rep equals the FreeCAD solid (diff {diff:.6f})")
    doc2 = App.newDocument(name + "_imported")
    made, text = parametric_fc.import_file(path, doc2)
    print(text)
    check(bool(made), f"{name}: rebuilt in a new document")
    if not made:
        return
    ok, diff = same(obj.Shape, made[0].Shape)
    check(ok, f"{name}: rebuilt solid equals the original (volumes {obj.Shape.Volume:.3f} / {made[0].Shape.Volume:.3f},"
              f" diff {diff:.6f})")
    exprs = sorted(e for o in doc2.Objects for _, e in o.ExpressionEngine)
    check(bool(exprs) and all("Parameters." in e for e in exprs), f"{name}: expressions rebuilt: {exprs}")
    for alias, new_value in changes:            # the same design change in both
        change(name, doc, obj, sheet, doc2, made, alias, new_value)


def change(name, doc, obj, sheet, doc2, made, alias, new_value):
    before = obj.Shape.Volume
    sheet.set(sheet.getCellFromAlias(alias), new_value)
    doc.recompute()
    p2 = doc2.getObject("Parameters")
    p2.set(p2.getCellFromAlias(alias), new_value)
    doc2.recompute()
    ok, diff = same(obj.Shape, made[0].Shape)
    check(abs(obj.Shape.Volume - before) > 1e-6, f"{name}: the change of {alias} changes the solid "
                                                 f"({before:.3f} -> {obj.Shape.Volume:.3f})")
    broken = [o.Label for d in (doc, doc2) for o in d.Objects if hasattr(o, "isValid") and not o.isValid()]
    check(not broken, f"{name}: every feature recomputes after the change {broken or ''}")
    check(ok, f"{name}: after {alias} = {new_value} both agree (volumes {obj.Shape.Volume:.3f} / "
              f"{made[0].Shape.Volume:.3f}, diff {diff:.6f})")


doc, body, sh = plate()
check(body.Shape.isValid() and body.Shape.Volume > 0, "plate builds")
# not Length or Thick: in FreeCAD 1.1.4 its own topological naming loses the filleted edge when the pad grows
# (the original document breaks as well), which is not what this test is about
roundtrip("plate", doc, body, sh, [("HoleR", "4 mm"), ("Width", "60 mm")])
doc, body, sh = cup()
check(body.Shape.isValid() and body.Shape.Volume > 0, "cup builds")
roundtrip("cup", doc, body, sh, [("Wall", "3 mm")])
doc, fuse, sh = csg()
roundtrip("csg", doc, fuse, sh, [("CylR", "3 mm")])
print(f"{len(failures)} failure(s); files in {OUT}")
if failures:
    sys.exit(1)
