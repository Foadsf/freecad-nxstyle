# SPDX-License-Identifier: LGPL-2.1-or-later
"""Parametric STEP round trip in a real FreeCAD (run with freecadcmd; not part of the unit tests):

    NXSTYLE_OUT=folder freecadcmd tests/fc_parametric_step.py

Builds a parametric plate (spreadsheet parameters, a constrained sketch, Pad, Pocket through all, linear
pattern, Fillet, Chamfer, Revolution, Thickness), holes of each kind on sketches attached to a face, mirrors
and patterns of several features and a MultiTransform, up-to-face extents, a Draft, Pipes and a Loft, and a
Part CSG tree; exports each as STEP AP242 with its ISO 10303-55/108/111 model, checks the file against
ISO 10303, imports it into a new document, and compares: the rebuilt solid with the original and with the
explicit B-rep in the file, the re-attached sketches, then both documents again after the same parameter
change. Holes, replicas and the sweep are also built from the ISO definitions alone and compared with
FreeCAD's. Prints one line per check, writes them to results.txt, and exits non-zero when one fails.
"""

import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "NXStyle"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402
import Sketcher  # noqa: E402

from nxstyle import iso10303, p21, parametric, parametric_fc  # noqa: E402

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
    diff, _how = parametric_fc.compare_solids(a, b)
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
    before, shape = obj.Shape.Volume, obj.Shape.copy()
    sheet.set(sheet.getCellFromAlias(alias), new_value)
    doc.recompute()
    p2 = doc2.getObject("Parameters")
    p2.set(p2.getCellFromAlias(alias), new_value)
    doc2.recompute()
    ok, diff = same(obj.Shape, made[0].Shape)
    moved = shape.cut(obj.Shape).Volume + obj.Shape.cut(shape).Volume
    check(moved > 1e-6, f"{name}: the change of {alias} changes the solid ({before:.3f} -> {obj.Shape.Volume:.3f}, "
                        f"{moved:.3f} mm³ moved)")
    broken = [o.Label for d in (doc, doc2) for o in d.Objects if hasattr(o, "isValid") and not o.isValid()]
    check(not broken, f"{name}: every feature recomputes after the change {broken or ''}")
    check(ok, f"{name}: after {alias} = {new_value} both agree (volumes {obj.Shape.Volume:.3f} / "
              f"{made[0].Shape.Volume:.3f}, diff {diff:.6f})")


doc, body, sh = plate()
check(body.Shape.isValid() and body.Shape.Volume > 0, "plate builds")
# not Length or Thick: in FreeCAD 1.1.4 its own topological naming loses the filleted edge when the pad grows
# (the original document breaks as well), which is not what this test is about
roundtrip("plate", doc, body, sh, [("HoleR", "4 mm"), ("Width", "60 mm")])
def part112_and_curves():
    """A Part 112 sketch from another system rebuilt as a FreeCAD sketch; ellipse and spline geometry; the
    plate's sketches written as Part 112 commands too and found to match."""
    sys.path.insert(0, HERE)
    import test_iso10303
    path = os.path.join(OUT, "part112.step")
    p21.write(test_iso10303.part112_file(), path)
    doc = App.newDocument("Part112")
    made, text = parametric_fc.import_file(path, doc)
    print(text)
    sk = [o for o in doc.Objects if o.TypeId == "Sketcher::SketchObject"]
    ok = len(sk) == 1 and len(sk[0].Geometry) == 19 and sk[0].Shape.isValid()
    check(ok, f"part112: a Part 112 sketch becomes a FreeCAD sketch ({len(sk[0].Geometry) if sk else 0} curves)")
    model = {"name": "Curves", "parameters": [], "features": [], "sketches": [
        {"name": "Curves", "placement": {"origin": [0, 0, 0], "axis": [0, 0, 1], "x": [1, 0, 0]}, "constraints": [],
         "geometry": [{"type": "ellipse", "c": [0, 0], "major": [20, 0], "r2": 8},
                      {"type": "spline", "points": [[0, 0], [10, 5], [20, -5], [30, 0]], "closed": False}]}]}
    doc2 = App.newDocument("Curves")
    parametric_fc.model_to_document(model, doc2)
    s2 = [o for o in doc2.Objects if o.TypeId == "Sketcher::SketchObject"][0]
    kinds = sorted(type(g).__name__ for g in s2.Geometry)
    check(kinds == ["BSplineCurve", "Ellipse"] and abs(s2.Geometry[0].MajorRadius - 20) < 1e-9,
          f"ellipse and spline geometry built: {kinds}")
    doc3, body, _ = plate()
    path = os.path.join(OUT, "plate112.step")
    report = parametric_fc.export(body, path, sketch_commands=True)
    _, notes = parametric.from_step(p21.read(path))
    check("Base: its ISO 10303-112 commands make 4 of its 4 curves" in notes and "0 error(s)" in report,
          f"plate: sketches also written as Part 112 commands, which reproduce them: {notes}")


def sheet(doc, values):
    sh = doc.addObject("Spreadsheet::Sheet", "Spreadsheet")
    for k, (alias, value) in enumerate(values, 1):
        sh.set(f"A{k}", value)
        sh.setAlias(f"A{k}", alias)
    doc.recompute()
    return sh


def rect(sk, x0, y0, x1, y1):
    pts = [App.Vector(x0, y0, 0), App.Vector(x1, y0, 0), App.Vector(x1, y1, 0), App.Vector(x0, y1, 0)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        sk.addGeometry(Part.LineSegment(a, b), False)
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))


def on(body, sk_name, support, offset=None):
    sk = body.newObject("Sketcher::SketchObject", sk_name)
    sk.AttachmentSupport = support
    sk.MapMode = "FlatFace"
    if offset is not None:
        sk.AttachmentOffset = App.Placement(App.Vector(*offset), App.Rotation())
    return sk


def face_where(obj, test):
    return next(f"Face{i + 1}" for i, f in enumerate(obj.Shape.Faces) if test(f))


def block(doc, body, sh, x=60, y=40, x0=0, y0=0):
    """A pad on XY, its thickness the spreadsheet's Thick."""
    sk = on(body, "Base", (body.Origin.OriginFeatures[3], [""]))
    rect(sk, x0, y0, x0 + x, y0 + y)
    doc.recompute()
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sk
    pad.Length = 20
    pad.setExpression("Length", "Spreadsheet.Thick")
    doc.recompute()
    return pad


def top_of(obj):
    z = obj.Shape.BoundBox.ZMax
    return face_where(obj, lambda f: type(f.Surface).__name__ == "Plane" and abs(f.CenterOfMass.z - z) < 1e-6)


def holes():
    """Holes on a sketch attached to the top face: flat, counterbore, drill point; countersunk through all."""
    doc = App.newDocument("Holes")
    sh = sheet(doc, [("Thick", "20 mm"), ("HX", "12 mm")])
    body = doc.addObject("PartDesign::Body", "Body")
    pad = block(doc, body, sh)
    kinds = []
    for k, (cut, point, depth_type) in enumerate((("None", "Flat", "Dimension"), ("Counterbore", "Flat", "Dimension"),
                                                 ("None", "Angled", "Dimension"), ("Countersink", "Flat", "ThroughAll"))):
        sk = on(body, f"HoleSketch{k}", (pad, [top_of(pad)]))
        y = 8 + 8 * k
        sk.addGeometry(Part.Circle(App.Vector(12, y, 0), App.Vector(0, 0, 1), 2), False)
        sk.addGeometry(Part.Circle(App.Vector(40, y, 0), App.Vector(0, 0, 1), 2), False)
        c = sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 3, 12))
        sk.setExpression(f".Constraints[{c}]", "Spreadsheet.HX")
        sk.addConstraint(Sketcher.Constraint("DistanceY", 0, 3, y))
        sk.addConstraint(Sketcher.Constraint("DistanceX", 1, 3, 40))
        sk.addConstraint(Sketcher.Constraint("DistanceY", 1, 3, y))
        sk.addConstraint(Sketcher.Constraint("Radius", 0, 2))
        sk.addConstraint(Sketcher.Constraint("Radius", 1, 2))
        doc.recompute()
        h = body.newObject("PartDesign::Hole", "Hole")
        h.Profile = sk
        h.Diameter, h.Depth = 4, 9
        h.DrillPoint = point
        h.DrillPointAngle = 118
        if cut != "None":
            h.HoleCutType = cut
            h.HoleCutDiameter = 7
            if cut == "Counterbore":
                h.HoleCutDepth = 3
            else:
                h.HoleCutCountersinkAngle = 90
        h.DepthType = depth_type
        body.Tip = h
        doc.recompute()
        kinds.append(h)
    return doc, body, sh


def patterns():
    """Mirrored and LinearPattern of two features (a boss and a pocket), a MultiTransform of a third."""
    doc = App.newDocument("Patterns")
    sh = sheet(doc, [("Thick", "10 mm"), ("BossR", "3 mm")])
    body = doc.addObject("PartDesign::Body", "Body")
    pad = block(doc, body, sh, 80, 60, -40, -30)
    xy = body.Origin.OriginFeatures[3]
    s1 = on(body, "BossSketch", (xy, [""]), (0, 0, 10))
    s1.addGeometry(Part.Circle(App.Vector(10, 10, 0), App.Vector(0, 0, 1), 3), False)
    c = s1.addConstraint(Sketcher.Constraint("Radius", 0, 3))
    s1.setExpression(f".Constraints[{c}]", "Spreadsheet.BossR")
    s1.addConstraint(Sketcher.Constraint("DistanceX", 0, 3, 10))
    s1.addConstraint(Sketcher.Constraint("DistanceY", 0, 3, 10))
    doc.recompute()
    boss = body.newObject("PartDesign::Pad", "Boss")
    boss.Profile, boss.Length = s1, 4
    doc.recompute()
    s2 = on(body, "PocketSketch", (pad, [top_of(pad)]))
    s2.addGeometry(Part.Circle(App.Vector(25, 12, 0), App.Vector(0, 0, 1), 2), False)
    doc.recompute()
    pocket = body.newObject("PartDesign::Pocket", "Pocket")
    pocket.Profile, pocket.Length = s2, 5
    doc.recompute()
    mir = body.newObject("PartDesign::Mirrored", "Mirrored")
    mir.Originals = [boss, pocket]
    mir.MirrorPlane = (body.Origin.OriginFeatures[4], [""])       # XZ: y -> -y, out of the block
    body.Tip = mir
    doc.recompute()
    mir.MirrorPlane = (s1, ["H_Axis"])                            # the boss sketch's x axis (y = 0)
    doc.recompute()
    lin = body.newObject("PartDesign::LinearPattern", "LinearPattern")
    lin.Originals = [boss, pocket]
    lin.Direction = (body.Origin.OriginFeatures[1], [""])        # along Y
    lin.Length, lin.Occurrences = 14, 3
    body.Tip = lin
    doc.recompute()
    s3 = on(body, "PinSketch", (xy, [""]), (0, 0, 10))
    s3.addGeometry(Part.Circle(App.Vector(20, -20, 0), App.Vector(0, 0, 1), 1.5), False)
    doc.recompute()
    pin = body.newObject("PartDesign::Pad", "Pin")
    pin.Profile, pin.Length = s3, 6
    body.Tip = pin
    doc.recompute()
    mt = body.newObject("PartDesign::MultiTransform", "MultiTransform")
    mt.Originals = [pin]
    lp = doc.addObject("PartDesign::LinearPattern", "MTLinear")
    lp.Direction = (body.Origin.OriginFeatures[0], [""])
    lp.Length, lp.Occurrences = 10, 2
    pp = doc.addObject("PartDesign::PolarPattern", "MTPolar")
    pp.Axis = (body.Origin.OriginFeatures[2], [""])
    pp.Angle, pp.Occurrences = 40, 2
    mt.Transformations = [lp, pp]
    body.Tip = mt
    doc.recompute()
    return doc, body, sh


def up_to():
    """Pad up to a face, Pocket up to the first face, Pad up to a face with an offset, Revolution up to a face."""
    doc = App.newDocument("UpTo")
    sh = sheet(doc, [("Thick", "20 mm")])
    body = doc.addObject("PartDesign::Body", "Body")
    pad = block(doc, body, sh)
    xy = body.Origin.OriginFeatures[3]
    a = on(body, "Riser", (xy, [""]), (0, 0, -15))
    a.addGeometry(Part.Circle(App.Vector(15, 20, 0), App.Vector(0, 0, 1), 4), False)
    doc.recompute()
    p2 = body.newObject("PartDesign::Pad", "PadToFace")
    p2.Profile, p2.Type = a, "UpToFace"
    p2.UpToFace = (pad, [top_of(pad)])
    doc.recompute()
    b = on(body, "Drill", (p2, [top_of(p2)]))
    rect(b, 30, 10, 40, 30)
    doc.recompute()
    pk = body.newObject("PartDesign::Pocket", "PocketToFirst")
    pk.Profile, pk.Type = b, "UpToFirst"
    pk.Reversed = False
    doc.recompute()
    c = on(body, "Post", (xy, [""]), (0, 0, -15))
    c.addGeometry(Part.Circle(App.Vector(50, 30, 0), App.Vector(0, 0, 1), 3), False)
    doc.recompute()
    p3 = body.newObject("PartDesign::Pad", "PadOffset")
    p3.Profile, p3.Type = c, "UpToFace"
    p3.UpToFace = (pk, [top_of(pk)])
    p3.Offset = 5
    body.Tip = p3
    doc.recompute()
    return doc, body, sh


def sweeps():
    """Draft of two side faces (a hybrid step) and a fillet after it, so that the history goes on; a Pipe along
    a line and an arc (Part 42's sweep), a Fixed-mode pipe and a Loft (hybrid steps)."""
    doc = App.newDocument("Sweeps")
    sh = sheet(doc, [("Thick", "20 mm"), ("PipeR", "2 mm")])
    body = doc.addObject("PartDesign::Body", "Body")
    pad = block(doc, body, sh)
    O = body.Origin.OriginFeatures
    sides = [f"Face{i + 1}" for i, f in enumerate(pad.Shape.Faces) if type(f.Surface).__name__ == "Plane" and
             abs(f.normalAt(0, 0).z) < 1e-9 and abs(f.normalAt(0, 0).x) > 0.5]
    dr = body.newObject("PartDesign::Draft", "Draft")
    dr.Base = (pad, sides)
    dr.NeutralPlane = (O[3], [""])
    dr.Angle = 4
    doc.recompute()
    e = next(f"Edge{i + 1}" for i, ed in enumerate(dr.Shape.Edges) if type(ed.Curve).__name__ in ("Line", "LineSegment")
             and all(abs(v.Point.y) < 1e-6 for v in ed.Vertexes) and min(v.Point.x for v in ed.Vertexes) < 1e-6
             and abs(ed.Vertexes[0].Point.z - ed.Vertexes[-1].Point.z) > 1)
    fil = body.newObject("PartDesign::Fillet", "Fillet")
    fil.Base = (dr, [e])
    fil.Radius = 2
    body.Tip = fil
    doc.recompute()
    path = on(body, "Path", (O[4], [""]), (0, 0, -20))       # XZ moved to y = 20: sketch y is global z
    path.addGeometry(Part.LineSegment(App.Vector(30, 20, 0), App.Vector(30, 30, 0)), False)
    path.addGeometry(Part.ArcOfCircle(Part.Circle(App.Vector(40, 30, 0), App.Vector(0, 0, 1), 10), math.pi / 2,
                                      math.pi), False)
    doc.recompute()
    prof = on(body, "PipeProfile", (O[3], [""]), (0, 0, 20))
    prof.addGeometry(Part.Circle(App.Vector(30, 20, 0), App.Vector(0, 0, 1), 2), False)
    c = prof.addConstraint(Sketcher.Constraint("Radius", 0, 2))
    prof.setExpression(f".Constraints[{c}]", "Spreadsheet.PipeR")
    prof.addConstraint(Sketcher.Constraint("DistanceX", 0, 3, 30))
    prof.addConstraint(Sketcher.Constraint("DistanceY", 0, 3, 20))
    doc.recompute()
    pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
    pipe.Profile = prof
    pipe.Spine = (path, ["Edge1", "Edge2"])
    body.Tip = pipe
    doc.recompute()
    path2 = on(body, "Path2", (O[3], [""]), (0, 0, 20))
    path2.addGeometry(Part.LineSegment(App.Vector(10, 30, 0), App.Vector(10, 10, 0)), False)
    doc.recompute()
    prof2 = on(body, "CutProfile", (O[5], [""]), (0, 0, 10))   # YZ plane through x = 10
    prof2.addGeometry(Part.Circle(App.Vector(30, 20, 0), App.Vector(0, 0, 1), 1.5), False)
    doc.recompute()
    cut = body.newObject("PartDesign::SubtractivePipe", "CutPipe")
    cut.Profile = prof2
    cut.Spine = (path2, ["Edge1"])
    cut.Mode = "Fixed"
    body.Tip = cut
    doc.recompute()
    l1 = on(body, "Loft1", (O[3], [""]), (0, 0, 20))
    rect(l1, 40, 5, 52, 17)
    l2 = on(body, "Loft2", (O[3], [""]), (0, 0, 30))
    l2.addGeometry(Part.Circle(App.Vector(46, 11, 0), App.Vector(0, 0, 1), 4), False)
    doc.recompute()
    loft = body.newObject("PartDesign::AdditiveLoft", "Loft")
    loft.Profile, loft.Sections = l1, [l2]
    body.Tip = loft
    doc.recompute()
    return doc, body, sh


def model_of(path):
    return parametric.from_step(p21.read(path))[0][0]


def hole_tool(ft, k):
    """The material a hole removes at position k, built from ISO 10303-111's definitions (4.4.22-27): coaxial
    segments going into the material against the placing's z axis, conical transitions, the bottom."""
    pos, ax = App.Vector(*ft["positions"][k]), App.Vector(*ft["axis"]).normalize()
    down = ax * -1
    depths = list(ft["depths"])
    if ft.get("through"):
        depths[-1] = ft["exit_depths"][k] if "exit_depths" in ft else depths[-1]
        depths[-1] += 1.0                                  # out through the exit face
    shape, z = None, 0.0
    for r, d in zip(ft["radii"], depths):
        seg = Part.makeCylinder(r, d, pos + down * z, down)
        shape = seg if shape is None else shape.fuse(seg)
        z += d
    for c in ft.get("transitions") or []:
        if c["number"] == 1:                               # at the entrance, narrowing into the next segment
            r_next = ft["radii"][0]
            h = (c["radius"] - r_next) / math.tan(c["apex"] / 2)
            shape = shape.fuse(Part.makeCone(c["radius"], r_next, h, pos, down))
    if ft.get("bottom") == "conical":
        r = ft["radii"][-1]
        shape = shape.fuse(Part.makeCone(r, 0, r / math.tan(ft["semi_apex"]), pos + down * z, down))
    return shape


def semantics_holes(doc, body, path):
    """The STEP holes, built from Part 111's definitions, remove what FreeCAD's holes remove."""
    m = model_of(path)
    got = body.Shape
    pad = next(o for o in body.Group if o.TypeId == "PartDesign::Pad")
    want = pad.Shape
    for ft in m["features"]:
        if ft["type"] != "hole":
            continue
        for k in range(len(ft["positions"])):
            want = want.cut(hole_tool(ft, k))
    ok, diff = same(got, want)
    check(ok, f"holes: Part 111 hole definitions reproduce FreeCAD's holes (diff {diff:.6f})")


def semantics_patterns(doc, body, path):
    """The STEP replicas (mirror included) reproduce FreeCAD's Mirrored and LinearPattern."""
    m = model_of(path)
    for name in ("Mirrored", "LinearPattern", "MultiTransform"):
        ft = next(f for f in m["features"] if f["name"] == name)
        obj = doc.getObjectsByLabel(name)[0]
        cur = obj.BaseFeature.Shape
        for s_name in ft["sources"]:
            src = doc.getObjectsByLabel(s_name)[0]
            for tr in ft["transforms"]:
                mm = tr["matrix"]
                mat = App.Matrix(mm[0][0], mm[0][1], mm[0][2], tr["translation"][0], mm[1][0], mm[1][1], mm[1][2],
                                 tr["translation"][1], mm[2][0], mm[2][1], mm[2][2], tr["translation"][2])
                tool = src.AddSubShape.transformGeometry(mat)
                cur = cur.cut(tool) if src.TypeId == "PartDesign::Pocket" else cur.fuse(tool)
        ok, diff = same(obj.Shape, cur)
        check(ok, f"patterns: the {ft['kind']} replicas of {ft['sources']} reproduce {name} (diff {diff:.6f})")


def semantics_pipe(doc, body, path):
    """Part 42's surface-curve sweep (x along the path plane's normal, z along the tangent) is FreeCAD's
    Standard pipe: sweep the profile with that frame and compare."""
    m = model_of(path)
    ft = next(f for f in m["features"] if f["type"] == "pipe")
    pipe = doc.getObjectsByLabel(ft["name"])[0]
    spine = Part.Wire([Part.Edge(Part.LineSegment(App.Vector(*e["p1"]), App.Vector(*e["p2"])))
                       if e["curve"]["type"] == "line" else
                       Part.Edge(Part.Arc(App.Vector(*e["p1"]), App.Vector(*parametric_fc.edge_midpoint(e)),
                                          App.Vector(*e["p2"]))) for e in ft["path_edges"]])
    prof = doc.getObjectsByLabel(ft["sketch"])[0]
    mps = Part.BRepOffsetAPI.MakePipeShell(spine)
    mps.setBiNormalMode(App.Vector(*ft["normal"]))
    mps.add(prof.Shape.Wires[0])
    mps.build()
    mps.makeSolid()
    ok, diff = same(pipe.AddSubShape, mps.shape())
    check(ok, f"sweeps: Part 42's sweep frame along the STEP directrix makes FreeCAD's pipe (diff {diff:.6f})")


def attached(doc2, names):
    sks = {o.Label: o for o in doc2.Objects if o.TypeId == "Sketcher::SketchObject"}
    got = {n: (sks[n].MapMode, parametric_fc._support(sks[n])[0][0].TypeId if parametric_fc._support(sks[n]) else "")
           for n in names if n in sks}
    return got


def roundtrip2(name, doc, obj, sheet_, changes, semantics=None, attach=()):
    """roundtrip() plus the ISO semantics check and the re-attached sketches."""
    path = os.path.join(OUT, f"{name}.step")
    roundtrip(name, doc, obj, sheet_, [])
    if semantics:
        semantics(doc, obj, path)
    doc2 = App.getDocument(name + "_imported")
    made = [o for o in doc2.Objects if o.TypeId == "PartDesign::Body"]
    if attach:
        got = attached(doc2, [n for n, _ in attach])
        want = {n: ("FlatFace", t) for n, t in attach}
        check(got == want, f"{name}: sketches re-attached {got}")
    for alias, new_value in changes:
        change(name, doc, obj, sheet_, doc2, made, alias, new_value)


doc, body, sh = holes()
check(body.Shape.isValid() and len(body.Group) > 8, "holes builds")
roundtrip2("holes", doc, body, sh, [("HX", "15 mm"), ("Thick", "24 mm")], semantics_holes,
           [("Base", "App::Plane")] + [(f"HoleSketch{k}", "PartDesign::Pad") for k in range(4)])
doc, body, sh = patterns()
check(body.Shape.isValid(), "patterns builds")
roundtrip2("patterns", doc, body, sh, [("BossR", "4 mm")], semantics_patterns,
           [("BossSketch", "App::Plane"), ("PocketSketch", "PartDesign::Pad")])
doc, body, sh = up_to()
check(body.Shape.isValid(), "up_to builds")
roundtrip2("upto", doc, body, sh, [("Thick", "25 mm")], None, [("Riser", "App::Plane"), ("Drill", "PartDesign::Pad")])
doc, body, sh = sweeps()
check(body.Shape.isValid() and all(o.isValid() for o in body.Group if hasattr(o, "isValid")), "sweeps builds")
roundtrip2("sweeps", doc, body, sh, [("PipeR", "2.5 mm")], semantics_pipe, [("Path", "App::Plane")])

doc, body, sh = cup()
check(body.Shape.isValid() and body.Shape.Volume > 0, "cup builds")
roundtrip("cup", doc, body, sh, [("Wall", "3 mm")])
doc, fuse, sh = csg()
roundtrip("csg", doc, fuse, sh, [("CylR", "3 mm")])
part112_and_curves()
print(f"{len(failures)} failure(s); files in {OUT}")
if failures:
    sys.exit(1)
