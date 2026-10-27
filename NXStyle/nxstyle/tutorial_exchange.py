# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exchange tutorial: the design intent through STEP (ISO 10303-55, -108, -111).

  AL  a plate driven by spreadsheet parameters (a constrained sketch, Pad, Fillet, a Pocket through all,
      a linear pattern) goes out as STEP with Parameters, the file is checked against ISO 10303, and a new
      part rebuilds it from the file alone: the same solid, the same parameters and expressions, and the
      same response to a design change
  AM  a STEP file received from a supplier: its application protocol named and checked against the AP's own
      schema, its product structure (BOM) read, and a sketch sent as ISO 10303-112 commands rebuilt into a
      FreeCAD sketch and extruded
"""

import os

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtWidgets

SAME, DIFFERS, MISSING, FAIL = "same", "differs", "missing", "FAILED"


def _out():
    return os.environ.get("NXSTYLE_TUTORIAL_OUT", "")


def _same(a, b, tol=1e-6):
    """Symmetric difference volume of two solids, relative to the larger one."""
    diff = a.cut(b).Volume + b.cut(a).Volume
    return diff, diff <= tol * max(a.Volume, b.Volume, 1.0)


class ExchangeTutorials:
    """Mixin for tutorial.Replay (uses the p_ helpers of PrecisionTutorials)."""

    # ================================================================ tutorial AL
    # A plate 80 x 50 x 10 with a Ø12 hole repeated three times 20 apart, its long edge rounded R3. Length,
    # Width, Thick and HoleR are spreadsheet aliases; the sketch's dimensions and the Pad's length are
    # expressions of them.
    AL_PARAMS = (("A1", "Length", "80 mm"), ("A2", "Width", "50 mm"), ("A3", "Thick", "10 mm"),
                 ("A4", "HoleR", "6 mm"))

    def AL_STEPS(self):
        return [self.p_modeling, self.al_new, self.al_part, self.al_export, self.al_check, self.al_new2,
                self.al_import, self.al_change, self.al_show, self.al_render]

    def al_new(self):
        self.tutorial = "AL: Design intent through STEP (ISO 10303-55, -108, -111)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def al_build(self, doc, body):
        """The plate, as a user would build it with Sketch, Extrude, Edge Blend, Extrude (Subtract) and
        Pattern Feature; returns the spreadsheet."""
        import Part
        import Sketcher
        sh = doc.addObject("Spreadsheet::Sheet", "Spreadsheet")
        for cell, alias, value in self.AL_PARAMS:
            sh.set(cell, value)
            sh.setAlias(cell, alias)
        doc.recompute()
        origin = body.Origin.OriginFeatures
        xy = next(f for f in origin if getattr(f, "Role", "") == "XY_Plane")
        x_axis = next(f for f in origin if getattr(f, "Role", "") == "X_Axis")
        sk = body.newObject("Sketcher::SketchObject", "Sketch")
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
        sk.renameConstraint(c, "width")
        sk.setExpression("Constraints.width", "Spreadsheet.Width")
        doc.recompute()
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sk
        pad.setExpression("Length", "Spreadsheet.Thick")
        doc.recompute()
        edge = next(f"Edge{i + 1}" for i, e in enumerate(pad.Shape.Edges)
                    if all(abs(v.Point.x - 80) < 1e-6 and abs(v.Point.y) < 1e-6 for v in e.Vertexes))
        fil = body.newObject("PartDesign::Fillet", "EdgeBlend")
        fil.Base = (pad, [edge])
        fil.Radius = 3
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
        pocket = body.newObject("PartDesign::Pocket", "ExtrudeSubtract")
        pocket.Profile = hole
        pocket.Type = "ThroughAll"
        doc.recompute()
        pat = body.newObject("PartDesign::LinearPattern", "PatternFeature")
        pat.Originals = [pocket]
        pat.Direction = (x_axis, [""])
        pat.Length = 40
        pat.Occurrences = 3
        body.Tip = pat                               # newObject leaves the Tip on the pocket for a pattern
        doc.recompute()
        return sh

    def al_part(self):
        self.wait_for("al_part: document", lambda: App.ActiveDocument is not None)
        doc = App.ActiveDocument
        body = next(iter(doc.findObjects("PartDesign::Body")), None) or doc.addObject("PartDesign::Body", "Body")
        body.Label = "Plate"
        sh = self.al_build(doc, body)
        doc.saveAs(os.path.join(_out(), "ParametricPlate.FCStd"))
        self._al_doc, self._al_body, self._al_sheet = doc, body, sh
        self._al_volume = body.Shape.Volume
        feats = [o.Label for o in body.Group if o.isDerivedFrom("PartDesign::Feature")]
        exprs = sorted(f"{o.Label}: {e}" for o in doc.Objects for _, e in o.ExpressionEngine)
        ok = body.Shape.isValid() and abs(self._al_volume - 36587.766) < 0.01
        self.view().viewIsometric()
        self.fit()
        self.step("A plate driven by parameters: Length, Width, Thick, HoleR in a spreadsheet; the sketch's "
                  "dimensions and the extrusion's length are expressions of them; an edge blend, a hole through "
                  "all and a pattern of it", "modelled by script (tutorials J and K build such expressions with the "
                  "ribbon and the Expressions table)", DIFFERS if ok else FAIL,
                  f"features {feats}; volume {self._al_volume:.3f} mm³; expressions {exprs}")
        self.wait = 600

    def al_export(self):
        from . import iso10303, p21
        path = os.path.join(_out(), "ParametricPlate.step")
        if os.path.exists(path):
            os.remove(path)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self._al_body)
        b, where = self.click_ribbon("STEP with Parameters", tab="PMI")
        QtWidgets.QApplication.processEvents()
        typed = self.p_type("stepFile", path)
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        text = self.p_info_text()
        self._al_path = path
        inv = iso10303.inventory(p21.read(path)) if os.path.isfile(path) else {}
        parts = [k for k in ("ISO 10303-42", "ISO 10303-55", "ISO 10303-108", "ISO 10303-111") if k in inv]
        ok = typed and len(parts) == 4 and "0 error(s)" in text and "Not written" not in text
        counts = ", ".join(f"{k} {sum(inv[k].values())}" for k in parts)
        self.step("PMI > STEP with Parameters: the part, its history, its sketches with their constraints and its "
                  "parameters in one STEP AP242 file", f"Plate selected, ribbon '{where} > STEP with Parameters', file "
                  "name typed, MB2 = OK", DIFFERS if ok else FAIL,
                  f"instances by part: {counts}; nothing left out. NX's STEP export writes the B-rep (and PMI); "
                  "the history, the sketch constraints and the expressions stay in the .prt")
        self.p_shot_info("AL_export.png")
        self.p_close_info()
        self.wait = 300

    def al_check(self):
        b, where = self.click_ribbon("Check STEP", tab="PMI")
        QtWidgets.QApplication.processEvents()
        typed = self.p_type("stepFile", self._al_path)
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        text = self.p_info_text()
        line = next((ln for ln in text.splitlines() if "error(s)" in ln), "")
        ok = typed and line.startswith("0 error(s)")
        self.step("Check STEP: the file against ISO 10303-21 and the EXPRESS schemas of Parts 42, 43, 55, 108, 111 "
                  "and 112", f"ribbon '{where} > Check STEP', file name typed, MB2 = OK", DIFFERS if ok else FAIL,
                  f"{line}; the warnings name the places where ISO 10303-108 contradicts itself. NX has no such "
                  "check")
        self.p_shot_info("AL_check.png")
        self.p_close_info()
        self.wait = 300

    def al_new2(self):
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1500

    def al_import(self):
        self.wait_for("al_import: new part", lambda: App.ActiveDocument is not None
                      and App.ActiveDocument is not self._al_doc)
        doc = App.ActiveDocument
        b, where = self.click_ribbon("Import STEP with Parameters", tab="PMI")
        QtWidgets.QApplication.processEvents()
        typed = self.p_type("stepFile", self._al_path)
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        text = self.p_info_text()
        bodies = doc.findObjects("PartDesign::Body")
        body = bodies[0] if len(bodies) == 1 and bodies[0].Label == "Plate" else None   # into the new part's Body
        sheet = doc.getObject("Parameters")
        ok, diff, feats, exprs = False, None, [], []
        if body is not None and sheet is not None:
            diff, same = _same(self._al_body.Shape, body.Shape)
            feats = [o.TypeId.split("::")[1] for o in body.Group if o.isDerivedFrom("PartDesign::Feature")]
            exprs = sorted(e for o in doc.Objects for _, e in o.ExpressionEngine)
            ok = typed and same and "symmetric difference" in text and len(exprs) == 4
        self._al_doc2, self._al_body2, self._al_sheet2 = doc, body, sheet
        self.step("New part, PMI > Import STEP with Parameters: the part rebuilt from the file, editable",
                  f"Ctrl+N, ribbon '{where} > Import STEP with Parameters', the file typed, MB2 = OK",
                  DIFFERS if ok else FAIL,
                  f"into the new part's Body: features {feats}; a Parameters spreadsheet and the expressions {exprs}; against the source "
                  f"part: {diff if diff is None else f'{diff:.6f}'} mm³ differ, and against the B-rep in the file "
                  "the same (the report's last line). NX's STEP import gives a solid without history")
        self.p_shot_info("AL_import.png")
        self.p_close_info()
        self.wait = 300

    def al_change(self):
        before = self._al_body.Shape.Volume
        for doc, sheet in ((self._al_doc, self._al_sheet), (self._al_doc2, self._al_sheet2)):
            sheet.set(sheet.getCellFromAlias("HoleR"), "4 mm")
            doc.recompute()
        diff, same = _same(self._al_body.Shape, self._al_body2.Shape)
        moved = abs(self._al_body2.Shape.Volume - before) > 1e-3
        valid = all(o.isValid() for d in (self._al_doc, self._al_doc2) for o in d.Objects if hasattr(o, "isValid"))
        self.step("A design change in the received part: HoleR 6 → 4 mm; the three holes follow, as in the source",
                  "HoleR typed into the Parameters spreadsheet by script (the same change in the source part)",
                  DIFFERS if same and moved and valid else FAIL,
                  f"volume {before:.3f} → {self._al_body2.Shape.Volume:.3f} mm³ in both parts; {diff:.6f} mm³ differ")
        self.wait = 300

    def al_show(self):
        App.setActiveDocument(self._al_doc2.Name)
        Gui.ActiveDocument = Gui.getDocument(self._al_doc2.Name)
        self.fit()                                   # the view settles before the next step renders it

    def al_render(self):
        QtWidgets.QApplication.processEvents()
        self.shot("AL_rebuilt_window.png")          # with the rebuilt feature tree in the Part Navigator
        self.check_drawn("The rebuilt plate after the change", "AL_rebuilt.png")
        self._al_doc2.saveAs(os.path.join(_out(), "ParametricPlate_imported.FCStd"))

    # ================================================================ tutorial AM
    # A fixture (a plate 120 x 80 x 10, two brackets, four bolts as links) arrives as STEP AP242; a bracket
    # profile arrives as ISO 10303-112 commands: a 60 x 40 rectangle with R5 rounds at its right corners, a
    # Ø16 bore at (20, 20) and four Ø4 holes on a 13 mm circle round it.
    AM_BOLTS = [(15, 15), (105, 15), (15, 65), (105, 65)]
    AM_AREA = 60 * 40 - 2 * (25 - 25 * 3.141592653589793 / 4) - 64 * 3.141592653589793 - 4 * 4 * 3.141592653589793

    def AM_STEPS(self):
        return [self.p_modeling, self.am_new, self.am_assembly, self.am_check, self.am_sketch_file,
                self.am_check112, self.am_new2, self.am_import, self.am_extrude, self.am_show, self.am_render]

    def am_new(self):
        self.tutorial = "AM: Receiving STEP: the application protocol, the BOM and an ISO 10303-112 sketch"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def am_assembly(self):
        import Import
        import Part
        self.wait_for("am_assembly: document", lambda: App.ActiveDocument is not None)
        doc = App.ActiveDocument
        top = doc.addObject("App::Part", "Fixture")
        plate = doc.addObject("Part::Box", "BasePlate")
        plate.Length, plate.Width, plate.Height = 120, 80, 10
        top.addObject(plate)
        bracket = doc.addObject("Part::Box", "Bracket")
        bracket.Length, bracket.Width, bracket.Height = 10, 40, 30
        bracket.Placement = App.Placement(App.Vector(20, 20, 10), App.Rotation())
        top.addObject(bracket)
        copy = doc.addObject("App::Link", "Bracket001")
        copy.LinkedObject = bracket
        copy.Placement = App.Placement(App.Vector(90, 20, 10), App.Rotation())
        top.addObject(copy)
        bolt = doc.addObject("Part::Cylinder", "Bolt")
        bolt.Radius, bolt.Height = 4, 30
        bolt.Visibility = False
        for i, (x, y) in enumerate(self.AM_BOLTS):
            lk = doc.addObject("App::Link", f"Bolt{i + 1:03d}")
            lk.LinkedObject = bolt
            lk.Placement = App.Placement(App.Vector(x, y, -10), App.Rotation())
            top.addObject(lk)
        doc.recompute()
        path = os.path.join(_out(), "Fixture.step")
        Part.setStaticValue("write.step.schema", "AP242DIS")
        Import.export([top], path)
        self._am_asm = path
        self.view().viewIsometric()
        self.fit()
        ok = os.path.isfile(path)
        self.step("The supplier's fixture as STEP AP242: a plate, two brackets, four bolts (one bracket and the "
                  "bolts as links)", "assembled and exported by script with FreeCAD's own STEP export",
                  DIFFERS if ok else FAIL, f"{os.path.getsize(path) if ok else 0} bytes")
        self.wait = 600

    def am_check(self):
        b, where = self.click_ribbon("Check STEP", tab="PMI")
        QtWidgets.QApplication.processEvents()
        typed = self.p_type("stepFile", self._am_asm)
        ticked = self.p_check("fetchSchema", True)
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        text = self.p_info_text()
        line = next((ln for ln in text.splitlines() if "error(s)" in ln), "")
        bom = text.split("Product structure:")[-1] if "Product structure:" in text else ""
        own = "long form in the schema cache" in text
        ok = typed and ticked and line.startswith("0 error(s)") and "AP242" in text and own \
            and "4 x Bolt" in bom and "2 x Bracket" in bom
        self.step("Check STEP with 'Download the AP's schema': the application protocol named, every entity checked "
                  "against AP242's own long form, the product structure listed",
                  f"ribbon '{where} > Check STEP', file name typed, the box ticked, MB2 = OK", DIFFERS if ok else FAIL,
                  f"{line}; checked against AP242's long form: {own}; parts list: "
                  + "; ".join(ln.strip() for ln in bom.splitlines() if " x " in ln and ln.startswith("  "))
                  + ". NX has no STEP checker; its BOM comes from the assembly navigator")
        self.p_shot_info("AM_check.png")
        self.p_close_info()
        self.wait = 300

    def am_sketch_file(self):
        """The bracket profile as a supplier's CAD system would send it: ISO 10303-112 commands."""
        import math
        from . import p21
        f = p21.File(("PROCEDURAL_SKETCH_SCHEMA",), name="bracket profile", description=("ISO 10303-112 sketch",))
        E = p21.Enum
        P = lambda x, y: f.add("CARTESIAN_POINT", "", [float(x), float(y)])   # noqa: E731

        def tline(p, q):
            d = (q[0] - p[0], q[1] - p[1])
            n = math.hypot(*d)
            ln = f.add("LINE", "", P(*p), f.add("VECTOR", "", f.add("DIRECTION", "", [d[0] / n, d[1] / n]), n))
            return f.add("TRIMMED_CURVE", "", ln, [P(*p)], [P(*q)], True, E("CARTESIAN"))

        def picked(items):
            return f.add_complex([("GEOMETRIC_REPRESENTATION_ITEM", []), ("REPRESENTATION_ITEM", [""]),
                                  ("USER_SELECTED_ELEMENTS", [items]), ("USER_SELECTED_SHAPE_ELEMENTS", [])])

        cmds = [f.add("CREATE_RECTANGLE", "outline", P(0, 0), P(60, 0), P(60, 40))]
        bottom, right = tline((0, 0), (60, 0)), tline((60, 0), (60, 40))
        cmds += [picked([bottom, right]), f.add("CREATE_FILLET", "round 1", bottom, False, right, False, 5.0, True,
                                                  P(59, 1))]
        right2, top = tline((60, 5), (60, 40)), tline((60, 40), (0, 40))
        cmds += [picked([right2, top]), f.add("CREATE_FILLET", "round 2", right2, False, top, False, 5.0, True,
                                                P(59, 39))]
        cmds.append(f.add("CREATE_CIRCLE_CENTRE_POINT", "bore", P(20, 20), 8.0))
        cmds.append(f.add("CREATE_CIRCLE_CENTRE_POINT", "hole", P(33, 20), 2.0))
        hole = f.add("CIRCLE", "", f.add("AXIS2_PLACEMENT_2D", "", P(33, 20), f.add("DIRECTION", "", [1.0, 0.0])), 2.0)
        cmds.append(f.add("CREATE_PATTERN_CIRCULAR", "holes", [hole], f.add("GEOMETRIC_CURVE_SET", "", [hole]), 3,
                          math.pi / 2, P(20, 20), True, P(33, 20)))
        seq = f.add("PROCEDURAL_SHAPE_REPRESENTATION_SEQUENCE", "bracket profile", cmds, [], "ISO 10303-112 commands")
        f.add("PROCEDURAL_SHAPE_REPRESENTATION", "BracketProfile", [seq],
              f.add("GEOMETRIC_REPRESENTATION_CONTEXT", "2D", "sketch", 2))
        path = os.path.join(_out(), "BracketProfile.step")
        p21.write(f, path)
        self._am_sketch = path
        self.step("The supplier's bracket profile as ISO 10303-112 commands: a rectangle, two R5 rounds (fillets "
                  "with trimming), a Ø16 bore, a Ø4 hole and its circular pattern", "the file written by script, "
                  "as another CAD system would send it", DIFFERS, f"{len(cmds)} commands")
        self.wait = 200

    def am_check112(self):
        b, where = self.click_ribbon("Check STEP", tab="PMI")
        QtWidgets.QApplication.processEvents()
        typed = self.p_type("stepFile", self._am_sketch)
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        text = self.p_info_text()
        line = next((ln for ln in text.splitlines() if "error(s)" in ln), "")
        n112 = next((ln for ln in text.splitlines() if ln.startswith("ISO 10303-112:")), "")
        ok = typed and line.startswith("0 error(s)") and n112
        self.step("Check STEP on the sketch file: the Part 112 commands against ISO 10303-112's schema",
                  f"ribbon '{where} > Check STEP', file name typed, MB2 = OK", DIFFERS if ok else FAIL,
                  f"{line}; {n112} instances of ISO 10303-112 entities")
        self.p_close_info()
        self.wait = 300

    def am_new2(self):
        self._am_doc1 = App.ActiveDocument
        self.key("Ctrl+N")
        self.wait = 1500

    def am_import(self):
        self.wait_for("am_import: new part", lambda: App.ActiveDocument is not None
                      and App.ActiveDocument is not self._am_doc1)
        doc = App.ActiveDocument
        b, where = self.click_ribbon("Import STEP with Parameters", tab="PMI")
        QtWidgets.QApplication.processEvents()
        typed = self.p_type("stepFile", self._am_sketch)
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        text = self.p_info_text()
        sk = [o for o in doc.Objects if o.TypeId == "Sketcher::SketchObject"]
        kinds = {}
        for g in (sk[0].Geometry if sk else []):
            kinds[type(g).__name__] = kinds.get(type(g).__name__, 0) + 1
        closed = sk and all(w.isClosed() for w in sk[0].Shape.Wires)
        ok = typed and len(sk) == 1 and sum(kinds.values()) == 11 and closed and "placed on XY" in text
        self._am_doc2, self._am_sketch_obj = doc, sk[0] if sk else None
        self.step("New part, Import STEP with Parameters: the commands evaluated into a FreeCAD sketch",
                  f"Ctrl+N, ribbon '{where} > Import STEP with Parameters', the file typed, MB2 = OK",
                  DIFFERS if ok else FAIL,
                  f"one sketch: {kinds}, every wire closed: {bool(closed)}; Part 112 does not position a sketch, so it "
                  "lies on XY. NX imports a STEP sketch as curves without its history")
        self.p_shot_info("AM_import.png")
        self.p_close_info()
        self.wait = 300

    def am_extrude(self):
        doc, sk = self._am_doc2, self._am_sketch_obj
        body = next(iter(doc.findObjects("PartDesign::Body")))
        pad = body.newObject("PartDesign::Pad", "Extrude")
        pad.Profile = sk
        pad.Length = 8
        doc.recompute()
        expected = self.AM_AREA * 8
        ok = pad.isValid() and abs(pad.Shape.Volume - expected) < 1e-6 * expected
        self.step("Extrude the received profile 8 mm: the bracket", "Pad by script on the imported sketch",
                  DIFFERS if ok else FAIL, f"volume {pad.Shape.Volume:.4f} mm³, expected {expected:.4f} "
                  "(60 × 40 less two R5 corners, the Ø16 bore and four Ø4 holes, times 8): the commands' geometry "
                  "is exact")
        self.wait = 300

    def am_show(self):
        App.setActiveDocument(self._am_doc2.Name)
        Gui.ActiveDocument = Gui.getDocument(self._am_doc2.Name)
        self.fit()

    def am_render(self):
        QtWidgets.QApplication.processEvents()
        self.shot("AM_bracket_window.png")
        self.check_drawn("The bracket from the received profile", "AM_bracket.png")
        self._am_doc2.saveAs(os.path.join(_out(), "Bracket_from_ISO10303-112.FCStd"))
