# SPDX-License-Identifier: LGPL-2.1-or-later
"""Precision-engineering tutorials: tolerance analysis, technical product documentation (ISO GPS,
3D PMI), assembly clearance and volume claims, release and engineering change.

  S  tolerance stack-up of a grooved pin (Fischer, Mechanical Tolerance Stackup and Analysis,
     Example 7.1 / 8.1): worst case, RSS, adjusted RSS, Monte Carlo, a requirement, the dimensioning
     scheme changed, the stack following a model change
  T  a guide bush documented to ISO GPS in 3D (ISO 16792 PMI, the workflow of Wuensch et al., NX fuer
     Einsteiger, 6.10): ISO 286 fits, the envelope, ISO 2768 general tolerances, datums, geometrical
     tolerances, the inspection plan, the fit as a stack-up, and the drawing inheriting the PMI
  U  a system layout: volume claims, then NX's Assembly Clearance (hard, containment, touching, soft)
  V  the guide bush released and changed: Strata versions, release, release package, engineering
     change, compare, revision B (runs T first)
"""

import math
import os

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtCore, QtWidgets, Qt

SAME, DIFFERS, MISSING, FAIL = "same", "differs", "missing", "FAILED"


def _out():
    return os.environ.get("NXSTYLE_TUTORIAL_OUT", "")


class PrecisionTutorials:
    """Mixin for tutorial.Replay."""

    # ------------------------------------------------------------- helpers
    def p_button(self, name):
        """Click a push button of the open dialog by its object name, as a user's MB1 click does."""
        from .tutorial import qtest
        dock = self.tasks_dock()
        b = dock.findChild(QtWidgets.QPushButton, name) if dock is not None else None
        if b is None:
            return False
        qtest().mouseClick(b, Qt.LeftButton)
        QtWidgets.QApplication.processEvents()
        return True

    def p_ok(self):
        """Accept the open dialog: MB2 in the graphics window as NX does, or its OK button when the
        window shows no 3D view (a drawing sheet)."""
        from .tutorial import qtest
        if self.nav() is not None:
            self.mb2_click()
            return "MB2"
        dock = self.tasks_dock()
        for b in dock.findChildren(QtWidgets.QPushButton) if dock is not None else []:
            if b.text().replace("&", "") == "OK" and b.isVisible():
                qtest().mouseClick(b, Qt.LeftButton)
                return "OK button"
        return None

    def p_widget(self, cls, name):
        dock = self.tasks_dock()
        return dock.findChild(cls, name) if dock is not None else None

    def p_type(self, name, text):
        """Type into a line edit of the open dialog."""
        from .tutorial import qtest
        w = self.p_widget(QtWidgets.QLineEdit, name)
        if w is None:
            return False
        w.setFocus()
        w.selectAll()
        qtest().keyClicks(w, text)
        QtWidgets.QApplication.processEvents()
        return True

    def p_check(self, name, state=True):
        from .tutorial import qtest
        w = self.p_widget(QtWidgets.QCheckBox, name)
        if w is None:
            return False
        if w.isChecked() != state:
            qtest().mouseClick(w, Qt.LeftButton, Qt.NoModifier, QtCore.QPoint(6, w.height() // 2))
            if w.isChecked() != state:          # a click beside a small box on a hidden desktop
                w.click()
        QtWidgets.QApplication.processEvents()
        return w.isChecked() == state

    def p_spin(self, name, value):
        w = self.p_widget(QtWidgets.QAbstractSpinBox, name)
        if w is None:
            return False
        self.type_into(w, value)
        return True

    def p_cell(self, table, row, col, text):
        """Edit a table cell the way a user does: start editing, type, Enter."""
        from .tutorial import qtest
        from .smoke import decode
        it = table.item(row, col)
        if it is None:
            return False
        table.setCurrentItem(it)
        table.editItem(it)
        QtWidgets.QApplication.processEvents()
        eds = [e for e in table.findChildren(QtWidgets.QLineEdit) if e.isVisible()] or \
            table.findChildren(QtWidgets.QLineEdit)
        if not eds:
            return False
        ed = eds[-1]
        ed.selectAll()
        qtest().keyClicks(ed, text)
        qtest().keyClick(ed, *decode("Return"))
        QtWidgets.QApplication.processEvents()
        return True

    def p_select(self, picks):
        """Select faces in pick order, as MB1 clicks with nothing else selected do."""
        doc = App.ActiveDocument
        Gui.Selection.clearSelection()
        for obj, sub in picks:
            Gui.Selection.addSelection(doc.Name, obj.Name, sub)
        QtWidgets.QApplication.processEvents()

    @staticmethod
    def p_face(obj, test):
        for i, f in enumerate(obj.Shape.Faces, start=1):
            try:
                if test(f):
                    return f"Face{i}"
            except Exception:
                continue
        return None

    @staticmethod
    def p_plane_at(axis, value):
        """Test for a planar face square to axis ('x', 'y', 'z') at that coordinate."""
        def test(f):
            if f.Surface.__class__.__name__ != "Plane":
                return False
            n = f.normalAt(*f.Surface.parameter(f.CenterOfMass))
            comp = {"x": n.x, "y": n.y, "z": n.z}[axis]
            c = {"x": f.CenterOfMass.x, "y": f.CenterOfMass.y, "z": f.CenterOfMass.z}[axis]
            return abs(abs(comp) - 1) < 1e-6 and abs(c - value) < 1e-6
        return test

    @staticmethod
    def p_cylinder(radius):
        def test(f):
            return f.Surface.__class__.__name__ == "Cylinder" and abs(f.Surface.Radius - radius) < 1e-6
        return test

    def p_stack_panel(self):
        return self.p_widget(QtWidgets.QWidget, "ToleranceStackup")

    def p_stack(self):
        from . import stackup_ui
        s = stackup_ui.stackups(App.ActiveDocument)
        return s[-1] if s else None

    def p_info_text(self):
        from . import commands
        dlg = commands._info_dialog
        try:
            box = dlg.findChild(QtWidgets.QPlainTextEdit) if dlg is not None else None
            return box.toPlainText() if box is not None else ""
        except RuntimeError:                       # already closed and deleted
            return ""

    def p_close_info(self):
        """Close the Information window as a user does (its close button), and give the keys back to the
        main window."""
        for dlg in Gui.getMainWindow().findChildren(QtWidgets.QDialog, "NXInformation"):
            if dlg.isVisible():
                dlg.close()
        QtWidgets.QApplication.processEvents()

    # ================================================================ tutorial S
    # Fischer, Example 7.1 / 8.1: the width of a pin's groove from A (the groove's side towards the
    # head) to B (its other side): -30 +/-0.2 (groove to head), +45 +/-0.5 (overall length),
    # -13.2 +/-0.5 (tip to groove). The book gives only the axial sizes; the diameters are ours:
    # a head 14 x 5, a shank 10, a groove root 8.6.
    S_PROFILE = [(0, 0), (0, 7), (5, 7), (5, 5), (30, 5), (30, 4.3), (31.8, 4.3), (31.8, 5), (45, 5), (45, 0)]

    def s_volume(self, groove=1.8):
        return math.pi * (7 ** 2 * 5 + 5 ** 2 * 25 + 4.3 ** 2 * groove + 5 ** 2 * (45 - 30 - groove))

    def s_new(self):
        self.tutorial = "S: Tolerance stack-up of a grooved pin (Fischer, Example 7.1 and 8.1)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def s_revolve(self):
        self.step("File > New (Ctrl+N), Model template", "Ctrl+N",
                  SAME if set(App.listDocuments()) - self._docs_before and self.body() else FAIL, "")
        Gui.Selection.clearSelection()
        b, where = self.click_ribbon("Revolve")
        self.step("Revolve, nothing selected", f"ribbon '{where} > Revolve'", SAME if b is not None else MISSING, "")
        self.wait = 1500

    def s_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.step("Sketch on the XY plane", "plane row + MB2", SAME if picked else FAIL, f"{picked}")
        self.wait = 1500

    def s_profile(self):
        import Part
        import Sketcher
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch in edit")
        pts = self.S_PROFILE + [self.S_PROFILE[0]]
        _, tool, n, ended = self.draw_clicks("Z", pts)
        self.step("Profile (Z): the pin's half section, 10 lines, MB2", "Z key + 11 MB1 clicks + MB2",
                  SAME if tool and n >= 9 and ended else FAIL, f"tool {tool}; {n} curves; ended {ended}")
        P = [App.Vector(x, y, 0) for (x, y) in self.S_PROFILE]
        sk.deleteAllGeometry()
        for i in range(10):
            sk.addGeometry(Part.LineSegment(P[i], P[(i + 1) % 10]), False)
        C = Sketcher.Constraint
        cons = [C("Coincident", i, 2, (i + 1) % 10, 1) for i in range(10)]
        cons += [C("Vertical", i) for i in (0, 2, 4, 6, 8)] + [C("Horizontal", i) for i in (1, 3, 5, 7, 9)]
        cons += [C("Coincident", 0, 1, -1, 1), C("DistanceY", -1, 1, 1, 1, 7), C("DistanceX", -1, 1, 2, 1, 5),
                 C("DistanceY", -1, 1, 3, 1, 5), C("DistanceX", -1, 1, 4, 1, 30), C("DistanceY", -1, 1, 5, 1, 4.3),
                 C("DistanceX", 5, 1, 5, 2, 1.8), C("DistanceY", -1, 1, 7, 1, 5), C("DistanceX", -1, 1, 8, 1, 45)]
        for c in cons:
            sk.addConstraint(c)
        sk.renameConstraint(len(sk.Constraints) - 3, "GrooveWidth")
        App.ActiveDocument.recompute()
        dof = sk.solve()
        self._s_sketch = sk
        self.step("Rapid Dimension: 45 overall, groove 30 from the head and 1.8 wide; Ø14 head, Ø10 shank, "
                  "Ø8.6 groove root", "values applied (the groove width named GrooveWidth)",
                  DIFFERS if dof == 0 else FAIL, f"solver {dof} (0 = fully constrained)")
        self.wait = 300

    def s_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def s_revolve_dialog(self):
        self.wait_dialog("s_revolve_dialog")
        axis = self.set_combo("axis", "x axis") or self.set_combo("axis", "horizontal")
        self.mb2_click()
        self.check_volume("Revolve about the X axis, 360°, OK", f"axis '{axis}', MB2 = OK", self.s_volume())
        self._s_body = self.body()
        App.ActiveDocument.saveAs(os.path.join(_out(), "Pin.FCStd"))
        self.wait = 600

    def s_faces(self):
        b = self._s_body
        return {k: self.p_face(b, self.p_plane_at("x", x)) for k, x in
                (("head", 0.0), ("A", 30.0), ("B", 31.8), ("tip", 45.0))}

    def s_stack(self):
        Gui.Selection.clearSelection()
        b, where = self.click_ribbon("Tolerance Stackup")
        self.wait = 800
        self._s_where = where

    def s_rows(self):
        panel = self.p_stack_panel()
        self.step("Analysis > Tolerance Stackup", f"ribbon '{self._s_where} > Tolerance Stackup'",
                  DIFFERS if panel is not None else FAIL, "NXStyle's own command: FreeCAD has no stack-up tool "
                  "(NX's is the separate Tolerance Stackup Validation)")
        f = self.s_faces()
        b = self._s_body
        self._s_faces = f
        for pick, label in (((f["A"], f["head"]), "groove side A to the head end"),
                            ((f["head"], f["tip"]), "head end to tip"),
                            ((f["tip"], f["B"]), "tip to groove side B")):
            self.p_select([(b, pick[0]), (b, pick[1])])
            ok = self.p_button("addMeasured")
            s = self.p_stack()
            m = list(s.Measured) if s is not None else []
            self.step(f"Pick {label}, Add Measured", "two MB1 picks + 'Add Measured'", SAME if ok and m else FAIL,
                      f"measured {m[-1]:+.3f} mm along {tuple(round(v, 3) for v in s.Direction)}" if m else "no row")
        self.wait = 400

    def s_tolerances(self):
        table = self.p_widget(QtWidgets.QTableWidget, "stackTable")
        from .stackup_ui import C_NAME, C_PLUS
        typed = []
        for row, (name, tol) in enumerate((("Groove to head", "0.2"), ("Overall length", "0.5"),
                                           ("Tip to groove", "0.5"))):
            typed.append(self.p_cell(table, row, C_NAME, name) and self.p_cell(table, row, C_PLUS, tol))
        s = self.p_stack()
        ok = (all(typed) and abs(s.Nominal - 1.8) < 1e-9 and abs(s.WorstCaseMin - 0.6) < 1e-9
              and abs(s.WorstCaseMax - 3.0) < 1e-9 and round(s.AdjustedMin, 1) == 0.7 and round(s.AdjustedMax, 1) == 2.9)
        rss = (s.RSSMax - s.RSSMin) / 2
        self.step("Tolerances ±0.2, ±0.5, ±0.5: worst case 0.6 to 3.0, RSS ±0.74, adjusted RSS ±1.1 (0.7 to 2.9)",
                  "typed into the table's cells", SAME if ok else FAIL,
                  f"nominal {s.Nominal:.4f}; worst case {s.WorstCaseMin:.4f} to {s.WorstCaseMax:.4f}; RSS ±{rss:.4f}; "
                  f"adjusted {s.AdjustedMin:.4f} to {s.AdjustedMax:.4f}: Fischer's figures 7.12 and 8.17")
        self.shot("S_stack_dialog.png")
        self.wait = 300

    def s_requirement(self):
        ok = self.p_check("checkMinimum") and self.p_spin("minimum", 1.1)
        QtWidgets.QApplication.processEvents()
        s = self.p_stack()
        fails = "worst case FAILS" in s.Verdict and "adjusted RSS FAILS" in s.Verdict
        self.step("Requirement: the groove takes a DIN 471 ring for a Ø10 shaft, so A-B >= 1.1",
                  "Minimum ticked, 1.1 typed", DIFFERS if ok and fails else FAIL,
                  f"verdict: {s.Verdict}; Monte Carlo {s.MonteCarloPPM:,.0f} ppm out (100000 assemblies). The book "
                  "states no requirement: this one shows what the numbers mean")
        self.mb2_click()
        self.wait = 800

    def s_report(self):
        text = self.p_info_text()
        ok = "worst case" in text and "Monte Carlo" in text and not Gui.Control.activeDialog()
        self.step("OK: the stack-up report", "MB2 = OK; the report in the Information window",
                  SAME if ok else FAIL, "the stack-up stays in the Part Navigator and recomputes with the part")
        self.shot("S_report.png")
        self.p_close_info()
        self.p_top_view()              # the loop is drawn beside the pin: seen from above it reads as a drawing
        self.shot("S_loop.png")
        self.wait = 300

    def s_redesign(self):
        """Fischer's advice: fewer contributors. Dimension the groove's width directly, 1.8 +/-0.1."""
        s = self.p_stack()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, s.Name)
        self.click_ribbon("Tolerance Stackup")
        QtWidgets.QApplication.processEvents()
        table = self.p_widget(QtWidgets.QTableWidget, "stackTable")
        removed = 0
        while table is not None and table.rowCount():
            table.setCurrentCell(0, 0)
            if not self.p_button("removeRow"):
                break
            removed += 1
        f, b = self._s_faces, self._s_body
        self.p_select([(b, f["A"]), (b, f["B"])])
        self.p_button("addMeasured")
        from .stackup_ui import C_NAME, C_PLUS
        self.p_cell(table, 0, C_NAME, "Groove width")
        self.p_cell(table, 0, C_PLUS, "0.1")
        ok = removed == 3 and len(s.Rows) == 1 and abs(s.WorstCaseMin - 1.7) < 1e-9 and "worst case OK" in s.Verdict
        self.step("Change the dimensioning: the groove's width dimensioned directly, 1.8 ±0.1",
                  "three rows removed, A to B added, ±0.1 typed", DIFFERS if ok else FAIL,
                  f"worst case {s.WorstCaseMin:.3f} to {s.WorstCaseMax:.3f}; {s.Verdict}. One contributor instead of "
                  "three (Fischer: dimension what the function needs, with the fewest dimensions in the loop)")
        self.mb2_click()
        self.p_close_info()
        self.wait = 600

    def s_change(self):
        sk = self._s_sketch
        sk.setDatum("GrooveWidth", App.Units.Quantity("2.0 mm"))
        App.ActiveDocument.recompute()
        s = self.p_stack()
        vol_ok = abs(self.solid_volume() - self.s_volume(2.0)) < 1e-3 * self.s_volume(2.0)
        ok = vol_ok and abs(s.Nominal - 2.0) < 1e-9 and abs(s.WorstCaseMin - 1.9) < 1e-9
        self.step("Design change: the groove widened to 2.0 in the model", "the sketch's GrooveWidth = 2.0",
                  SAME if ok else FAIL, f"the stack-up follows: nominal {s.Nominal:.3f}, worst case "
                  f"{s.WorstCaseMin:.3f} to {s.WorstCaseMax:.3f} (it measures the faces, not a copy of the numbers)")
        self.wait = 400

    def p_top_view(self):
        """Top view, fitted, after FreeCAD's view animation has ended (a screenshot taken during it
        catches the old view)."""
        self.view().viewTop()
        self.wait_for("top view", lambda: abs(abs(self.view().getViewDirection().z) - 1) < 1e-6, 4000)
        Gui.SendMsgToActiveView("ViewFit")       # (the replay's fit() turns the view trimetric first)
        from .tutorial import qtest
        qtest().qWait(1500)
        QtWidgets.QApplication.processEvents()

    def s_show(self):
        self.p_top_view()
        self.check_drawn("The pin and its stack-up loop in the graphics window", "S_pin.png")
        App.ActiveDocument.save()

    # ================================================================ tutorial T
    # A guide bush documented to ISO GPS in the model (ISO 16792): the workflow of Wuensch, Pilz and
    # Vajna, NX fuer Einsteiger, 6.10 (PMI tab, Rapid Dimension on a cylindrical face, tolerances, PMI
    # in the Part Navigator), applied to a part of ours. Flange Ø40 x 8, body Ø25 k6 x 30 pressed into
    # the housing (datum A, the envelope), shoulder = datum B, bore Ø16 H7 for a g6 shaft; ISO 2768-mK.
    T_R = {"bore": 8.0, "body": 12.5, "flange": 20.0}
    T_Z = {"under": 0.0, "shoulder": 8.0, "top": 38.0}

    def T_STEPS(self):
        return [self.t_new, self.t_part, self.t_tolerancing, self.t_body_size, self.t_datum_a, self.t_datum_b,
                self.t_bore_size, self.t_coaxiality, self.t_perpendicularity, self.t_length, self.t_flange,
                self.t_plan, self.t_envelope, self.t_fit, self.t_pmi_view, self.t_drafting, self.t_views,
                self.t_inherit, self.t_drawing]

    def t_volume(self):
        return math.pi * ((20 ** 2 - 8 ** 2) * 8 + (12.5 ** 2 - 8 ** 2) * 30)

    def t_new(self):
        self.tutorial = "T: A guide bush documented to ISO GPS with 3D PMI (ISO 16792)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def t_part(self):
        import Part
        self.wait_for("t_part: Body", lambda: self.body() is not None)
        doc = App.ActiveDocument
        body = self.body()
        sk = body.newObject("Sketcher::SketchObject", "Section")
        sk.AttachmentSupport = [(body.Origin.OriginFeatures[4], "")]      # XZ plane
        sk.MapMode = "FlatFace"
        pts = [(8, 0), (20, 0), (20, 8), (12.5, 8), (12.5, 38), (8, 38)]
        V = App.Vector
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            sk.addGeometry(Part.LineSegment(V(a[0], a[1], 0), V(b[0], b[1], 0)), False)
        rev = body.newObject("PartDesign::Revolution", "Revolution")
        rev.Profile = sk
        rev.ReferenceAxis = (sk, ["V_Axis"])
        rev.Angle = 360
        sk.Visibility = False
        doc.recompute()
        ok = abs(self.solid_volume() - self.t_volume()) < 1e-3 * self.t_volume()
        doc.saveAs(os.path.join(_out(), "GuideBush.FCStd"))
        self._t_body = body
        self.step("The guide bush: flange Ø40 x 8, body Ø25 x 30, bore Ø16", "modelled by script (the exercise is "
                  "the documentation)", SAME if ok else FAIL, f"volume {self.solid_volume():.1f} mm^3, expected "
                  f"{self.t_volume():.1f}")
        self.key("Escape")
        self.wait = 400

    def t_face(self, what):
        b = self._t_body
        if what in self.T_R:
            return self.p_face(b, self.p_cylinder(self.T_R[what]))
        return self.p_face(b, self.p_plane_at("z", self.T_Z[what]))

    def t_tolerancing(self):
        b, where = self.click_ribbon("Tolerancing", tab="PMI")
        QtWidgets.QApplication.processEvents()
        combo = self.p_widget(QtWidgets.QComboBox, "generalTolerance")
        typed = False
        if combo is not None and combo.lineEdit() is not None:
            from .tutorial import qtest
            ed = combo.lineEdit()
            ed.setFocus()
            ed.selectAll()
            qtest().keyClicks(ed, "ISO 2768-mK")
            typed = True
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        from . import pmi_ui
        std, general = pmi_ui.settings(App.ActiveDocument)
        self.step("PMI tab > Tolerancing: ISO GPS, general tolerances ISO 2768-mK",
                  f"ribbon '{where} > Tolerancing', 'ISO 2768-mK' typed, MB2 = OK",
                  DIFFERS if typed and std == "ISO" and general == "ISO 2768-mK" else FAIL,
                  f"standard {std}, general {general}: what a drawing's title block says (NX keeps it in the drafting "
                  "standard and a general note); stored with the PMI folder of the part")
        self.wait = 300

    def t_pmi(self, label, picks, ribbon, fill, check, how, detail_fn=None, outcome=DIFFERS):
        """Select, start a PMI command on the PMI tab, fill its dialog, MB2 = OK, check the new PMI."""
        from . import pmi_ui
        doc = App.ActiveDocument
        before = {o.Name for o in pmi_ui.all_pmi(doc)}
        self.p_select([(self._t_body, self.t_face(p)) for p in picks])
        b, where = self.click_ribbon(ribbon, tab="PMI")
        QtWidgets.QApplication.processEvents()
        filled = fill()
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        doc.recompute()
        new = [o for o in pmi_ui.all_pmi(doc) if o.Name not in before]
        o = new[-1] if new else None
        ok = bool(filled) and o is not None and check(o) and not Gui.Control.activeDialog()
        self.step(label, f"{', '.join(picks)} selected + ribbon '{where} > {ribbon}'; {how}; MB2 = OK",
                  outcome if ok else FAIL, (detail_fn(o) if detail_fn and o is not None else
                                            (o.Callout if o is not None else "no PMI made")))
        return o

    def t_body_size(self):
        def fill():
            return self.p_type("fit", "k6") and self.p_check("envelope")
        self._t_body_dim = self.t_pmi(
            "Rapid Dimension on the body's cylinder: Ø25 k6 with the envelope Ⓔ (it is pressed into the housing)",
            ["body"], "Rapid Dimension", fill, lambda o: o.Callout.startswith("Ø25.000 k6 (+0.015/+0.002)"),
            "'k6' typed, Envelope ticked", lambda o: f"{o.Callout}; NX: the cylindrical face is picked in the graphics "
            "window and the PMI placed with a click; here it is placed beside the face")
        self.wait = 300

    def t_datum(self, face, letter, what):
        def fill():
            return self.p_type("datumLetter", letter)
        self.t_pmi(f"Datum Feature Symbol {letter} on {what}", [face], "Datum Feature Symbol", fill,
                   lambda o: o.Letter == letter, f"letter {letter}")

    def t_datum_a(self):
        self.t_datum("body", "A", "the Ø25 body (its axis)")
        self.wait = 300

    def t_datum_b(self):
        self.t_datum("shoulder", "B", "the shoulder that seats on the housing")
        self.wait = 300

    def t_bore_size(self):
        def fill():
            return self.p_type("fit", "H7")
        self._t_bore_dim = self.t_pmi("Rapid Dimension on the bore: Ø16 H7 (no envelope yet)", ["bore"],
                                      "Rapid Dimension", fill,
                                      lambda o: o.Callout.startswith("Ø16.000 H7 (+0.018/+0.000)"), "'H7' typed")
        self.wait = 300

    def t_frame(self, label, face, characteristic, tol, diameter, datums):
        def fill():
            combo = self.p_widget(QtWidgets.QComboBox, "characteristic")
            i = next((k for k in range(combo.count()) if combo.itemText(k).lower() == characteristic), -1)
            combo.setCurrentIndex(i)
            if diameter:
                self.p_check("zoneDiameter")
            self.p_type("tolerance", tol)
            for k, d in enumerate(datums):
                self.p_type(f"datum{k + 1}", d)
            return i >= 0
        return self.t_pmi(label, [face], "Feature Control Frame", fill,
                          lambda o: o.Characteristic.lower() == characteristic and abs(o.Tolerance - float(tol)) < 1e-12,
                          f"{characteristic}, {'Ø' if diameter else ''}{tol}, datum {'|'.join(datums)}")

    def t_coaxiality(self):
        self.t_frame("Coaxiality of the bore Ø0.02 to A (ISO 1101; the symbol ASME calls concentricity)", "bore",
                     "concentricity", "0.02", True, ["A"])
        self.wait = 300

    def t_perpendicularity(self):
        self.t_frame("Perpendicularity of the shoulder 0.02 to A", "shoulder", "perpendicularity", "0.02", False, ["A"])
        self.wait = 300

    def t_length(self):
        self.t_pmi("Rapid Dimension: the body's length 30, no tolerance of its own (ISO 2768-m, over 6 up to 30: ±0.2)",
                   ["shoulder", "top"], "Rapid Dimension", lambda: True, lambda o: abs(o.Nominal - 30) < 1e-9,
                   "nothing typed")
        self.wait = 300

    def t_flange(self):
        def fill():
            return self.p_spin("upperDeviation", 0.05) and self.p_spin("lowerDeviation", 0.05)
        self.t_pmi("Rapid Dimension: the flange 8 ±0.05", ["under", "shoulder"], "Rapid Dimension", fill,
                   lambda o: abs(o.Nominal - 8) < 1e-9 and o.Callout == "8.000 ±0.050", "+0.05 and −0.05 typed")
        self.wait = 300

    def t_plan(self):
        b, where = self.click_ribbon("Inspection Plan", tab="PMI")
        QtWidgets.QApplication.processEvents()
        text = self.p_info_text()
        flagged = "ISO 8015" in text and "H7 is a fit" in text
        self.step("Inspection Plan: the characteristics, numbered, and the checks", f"ribbon '{where} > Inspection Plan'",
                  DIFFERS if flagged else FAIL, "the check finds the bore's H7 without the envelope: under ISO 8015 a "
                  "size controls only local two-point sizes, so the fit is not guaranteed. NX has no such check")
        self.shot("T_plan_warning.png")
        self.p_close_info()
        self.wait = 300

    def t_envelope(self):
        o = self._t_bore_dim
        o.Envelope = True                     # the PMI's property, as edited in the property view
        App.ActiveDocument.recompute()
        self.click_ribbon("Inspection Plan", tab="PMI")
        QtWidgets.QApplication.processEvents()
        shown = "Checks: no" in self.p_info_text()
        from . import pmi, pmi_ui
        doc = App.ActiveDocument
        anns = pmi_ui.annotations(doc)
        std, general = pmi_ui.settings(doc)
        issues = [i for i in pmi.check(anns, std, general) if i[0] in ("error", "warning")]
        plan = {r["id"]: r for r in pmi.inspection_plan(anns, general=general)}
        length = next((r for r in plan.values() if r["tolerance_from"] == "ISO 2768-m"), None)
        notes = [i for i in pmi.check(anns, std, general) if i[0] == "note"]
        ok = (not issues and len(plan) == 6 and length is not None and abs(length["lower"] - 29.8) < 1e-9
              and "Ⓔ" in o.Callout and (shown or notes))
        self.step("The bore gets the envelope Ⓔ; the plan again", "the PMI's Envelope property; Inspection Plan",
                  DIFFERS if ok else FAIL, f"{len(plan)} characteristics, no errors or warnings; the length 30 "
                  f"inspected at {length['lower'] if length else '?'} to {length['upper'] if length else '?'} "
                  "(ISO 2768-m); bore " + o.Callout)
        self.shot("T_plan.png")
        self.p_close_info()
        self.wait = 300

    def t_fit(self):
        """The fit with a Ø16 g6 shaft as a stack-up: hole minus shaft, from the PMI and ISO 286."""
        from . import iso
        Gui.Selection.clearSelection()
        self.click_ribbon("Tolerance Stackup", tab="PMI")
        QtWidgets.QApplication.processEvents()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self._t_bore_dim.Name)
        self.p_button("addFromPMI")
        self.p_button("addTyped")
        table = self.p_widget(QtWidgets.QTableWidget, "stackTable")
        from .stackup_ui import C_NAME, C_NOM, C_DIR, C_FIT, C_KIND
        typed = all([self.p_cell(table, 1, C_NAME, "Shaft Ø16 g6"), self.p_cell(table, 1, C_NOM, "16"),
                     self.p_cell(table, 1, C_DIR, "-"), self.p_cell(table, 1, C_FIT, "g6"),
                     self.p_cell(table, 1, C_KIND, "dimension")])
        s = self.p_stack()
        f = iso.fit(16, "H7", "g6")
        ok = typed and abs(s.WorstCaseMin - f["clearance_min"]) < 1e-9 and abs(s.WorstCaseMax - f["clearance_max"]) < 1e-9
        self.step("The fit Ø16 H7/g6 as a stack-up: bore from the PMI, shaft by its ISO 286 class",
                  "Add from PMI (the bore's dimension) + Add Typed: 16, '-', class g6", DIFFERS if ok else FAIL,
                  f"clearance {s.WorstCaseMin:.3f} to {s.WorstCaseMax:.3f} mm worst case, as ISO 286 gives for 16 H7/g6 "
                  f"({f['clearance_min']:.3f} to {f['clearance_max']:.3f}); a later change of the PMI's class follows")
        self.mb2_click()
        self.p_close_info()
        self.wait = 400

    def t_pmi_view(self):
        self.view().viewIsometric()
        self.fit()
        QtWidgets.QApplication.processEvents()
        self.check_drawn("The bush with its PMI in the graphics window", "T_pmi.png")
        self.shot("T_pmi_window.png")
        App.ActiveDocument.save()

    def t_drafting(self):
        self.key("Ctrl+Shift+D")
        self.wait = 2500

    def t_views(self):
        b, where = self.click_ribbon("New Sheet")
        if b is None:
            from .qt import QAction
            owners = [f"{a.objectName() or a.text()} ({a.shortcutContext()}, enabled {a.isEnabled()})"
                      for a in Gui.getMainWindow().findChildren(QAction)
                      if a.shortcut().toString() == "Ctrl+Shift+D"]
            self.progress(f"t_views: no New Sheet; application {(getattr(self.shell, 'current_app', None) or {}).get('id')}, "
                          f"Ctrl+Shift+D held by {owners}; focus {QtWidgets.QApplication.focusWidget()}; "
                          f"active window {QtWidgets.QApplication.activeWindow()}")
            self.retries.append("T: Ctrl+Shift+D did not reach Drafting; Application tab used")
            from . import shell
            shell.switch_application("drafting")
            QtWidgets.QApplication.processEvents()
            b, where = self.click_ribbon("New Sheet")
        QtWidgets.QApplication.processEvents()
        self._t_page = self.newest("TechDraw::DrawPage")
        made = []
        for direction, xdir, pos in ((App.Vector(0, 0, 1), App.Vector(1, 0, 0), (215.0, 120.0)),
                                     (App.Vector(0, -1, 0), App.Vector(1, 0, 0), (95.0, 120.0))):
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(App.ActiveDocument.Name, self._t_body.Name)
            before = {v.Name for v in self._t_page.Views}
            self.click_ribbon("Base View")
            QtWidgets.QApplication.processEvents()
            v = next((x for x in self._t_page.Views if x.Name not in before and x.isDerivedFrom("TechDraw::DrawViewPart")),
                     None)
            if v is not None:
                v.Direction, v.XDirection = direction, xdir
                v.ScaleType = "Custom"
                v.Scale = 2.0
                v.X, v.Y = pos
                made.append(v)
            if Gui.Control.activeDialog():
                self.mb2_click_on_sheet()
            App.ActiveDocument.recompute()
        self._t_views = made
        self.step("Drafting: New Sheet, a top view and a front view at 2:1", "Ctrl+Shift+D, ribbon 'New Sheet', "
                  "twice 'Base View' with the body selected", DIFFERS if len(made) == 2 else FAIL,
                  "the second Base View stands in for a projected view, as in tutorial H")
        self.wait = 1200

    def t_inherit(self):
        page = self._t_page
        made_all = []
        for v in self._t_views:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(App.ActiveDocument.Name, v.Name)
            QtWidgets.QApplication.processEvents()
            before = {x.Name for x in page.Views}
            b, where = self.click_ribbon("Inherit PMI")
            QtWidgets.QApplication.processEvents()
            App.ActiveDocument.recompute()
            made_all += [x for x in page.Views if x.Name not in before]
        from . import pmi_ui
        self.progress(f"t_inherit: skipped {pmi_ui.last_inherit}")
        for v in self._t_views:                   # what the matching saw, for the record
            es = pmi_ui._view_edges(v)
            radii = sorted({round(e.Curve.Radius, 3) for _, e in es if hasattr(e.Curve, "Radius")})
            lens = sorted({round(e.Length, 3) for _, e in es if not hasattr(e.Curve, "Radius")})
            top = [e for _, e in es if not hasattr(e.Curve, "Radius") and abs(e.Vertexes[0].Point.y - e.Vertexes[-1].Point.y) < 1e-6]
            try:
                q = v.projectPoint(App.Vector(0, 0, 38))
            except Exception as ex:
                q = f"error {ex}"
            self.progress(f"t_inherit: {v.Label} scale {v.Scale} edges {len(es)} radii {radii} line lengths {lens[:12]}"
                          f"; projectPoint(0,0,38) = {q}; horizontal edge ys {sorted({round(e.Vertexes[0].Point.y, 3) for e in top})}")
        dims = [x for x in page.Views if x.isDerivedFrom("TechDraw::DrawViewDimension") and getattr(x, "NX_Pmi", "")]
        syms = [x for x in page.Views if x.isDerivedFrom("TechDraw::DrawViewSymbol") and getattr(x, "NX_Pmi", "")]
        note = next((x for x in page.Views if getattr(x, "NX_Pmi", "") == "tolerancing-note"), None)
        specs = [d.FormatSpec for d in dims]
        values = []
        for d in dims:
            try:
                values.append(round(float(d.getRawValue()), 3))
            except Exception:
                values.append(None)
        want = {25.0, 16.0, 30.0, 8.0}
        ok = set(v for v in values if v is not None) == want and len(syms) == 4 and note is not None
        self.step("Inherit PMI on each view: the dimensions with their ISO classes and the envelope, the frames, the "
                  "datum symbols, and the tolerancing note", "each view selected + ribbon 'Drafting > Inherit PMI'",
                  DIFFERS if ok else FAIL, f"{len(dims)} dimensions {sorted(v for v in values if v is not None)} "
                  f"({'; '.join(specs)}), {len(syms)} symbols, note {list(note.Text) if note else None}. NX inherits PMI "
                  "from a model view into a drawing view; FreeCAD has no PMI, NXStyle adds both")
        self.wait = 800

    def t_drawing(self):
        App.ActiveDocument.recompute()
        QtWidgets.QApplication.processEvents()
        self.shot("T_drawing.png")
        App.ActiveDocument.save()
        self.key("Ctrl+M")
        self.wait = 1500

    # ================================================================ tutorial U
    # A system layout of ours: a frame, a stage module, a sensor module and an optical path. Each
    # module owns a volume claim; the beam path is a keep-out. Then NX's Assembly Clearance over all
    # parts: a dowel inside the frame (containment), modules standing on it (touching), a cable bracket
    # close to the sensor (soft, inside a 3 mm zone), a cover screw modelled without its tapped hole (hard).
    U_PARTS = {      # label: (kind, size, position)
        "Frame": ("box", (400, 300, 20), (0, 0, 0)),
        "Dowel": ("cyl", (3, 15), (20, 20, 2)),
        "Stage": ("box", (150, 150, 60), (40, 40, 20)),
        "Sensor housing": ("cyl", (30, 80), (300, 150, 20)),
        "Cover screw": ("cyl", (2, 12), (300, 150, 95)),
        "Cable bracket": ("box", (40, 10, 60), (200, 145, 40)),
    }

    def U_STEPS(self):
        return [self.u_new, self.u_layout, self.u_claim_structure, self.u_claim_stage, self.u_claim_sensor,
                self.u_claim_path, self.u_check, self.u_fix, self.u_recheck, self.u_clearance, self.u_study,
                self.u_exclude, self.u_close]

    def u_new(self):
        self.tutorial = "U: Volume claims and assembly clearance in a system layout"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def u_layout(self):
        doc = App.ActiveDocument
        self._u = {}
        for label, (kind, size, pos) in self.U_PARTS.items():
            if kind == "box":
                o = doc.addObject("Part::Box", "Part")
                o.Length, o.Width, o.Height = size
            else:
                o = doc.addObject("Part::Cylinder", "Part")
                o.Radius, o.Height = size
            o.Placement.Base = App.Vector(*pos)
            o.Label = label
            self._u[label] = o
        doc.recompute()
        doc.saveAs(os.path.join(_out(), "Layout.FCStd"))
        self.view().viewIsometric()
        self.fit()
        self.step("The layout: frame, stage, sensor housing with its cover screw and cable bracket, a dowel",
                  "modelled by script (the exercise is the space management)", SAME if len(self._u) == 6 else FAIL,
                  "boxes and cylinders stand in for the modules' parts")
        self.wait = 400

    def u_claim(self, label, members, owner, size, corner, kind="Keep-in", margin=0.0):
        from . import claims
        doc = App.ActiveDocument
        before = {o.Name for o in claims.claims(doc)}
        Gui.Selection.clearSelection()
        for m in members:
            Gui.Selection.addSelection(doc.Name, self._u[m].Name)
        b, where = self.click_ribbon("Volume Claim", tab="Assemblies")
        QtWidgets.QApplication.processEvents()
        ok = self.p_type("owner", owner)
        if kind != "Keep-in":
            self.set_combo("claimType", kind)
        for name, v in zip(("length", "width", "height", "positionX", "positionY", "positionZ"), size + corner):
            ok = self.p_spin(name, v) and ok
        if margin:
            ok = self.p_spin("margin", margin) and ok
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        new = [o for o in claims.claims(doc) if o.Name not in before]
        c = new[-1] if new else None
        good = (ok and c is not None and abs(c.Shape.Volume - size[0] * size[1] * size[2]) < 1e-6 * c.Shape.Volume
                and [m.Label for m in c.Members] == list(members))
        self.step(label, f"{', '.join(members) or 'nothing'} selected + ribbon '{where} > Volume Claim'; owner, size, "
                  f"corner{', margin' if margin else ''} typed; MB2 = OK", DIFFERS if good else FAIL,
                  f"{c.Label if c else 'none'}: {kind}, {size[0]} x {size[1]} x {size[2]} at {corner}"
                  + (f", margin {margin}" if margin else "") + "; NX has no volume claims (its Assembly Clearance "
                  "checks parts against parts)")
        return c

    def u_claim_structure(self):
        self._uc = {"Structure": self.u_claim("Claim for the structure: frame and dowel", ["Frame", "Dowel"],
                                              "Structure", (400, 300, 20), (0, 0, 0))}
        self.wait = 300

    def u_claim_stage(self):
        self._uc["Stage"] = self.u_claim("Claim for the stage module", ["Stage"], "Stage", (180, 170, 80), (30, 30, 20))
        self.wait = 300

    def u_claim_sensor(self):
        self._uc["Sensor"] = self.u_claim("Claim for the sensor module: housing, cover screw, cable bracket",
                                          ["Sensor housing", "Cover screw", "Cable bracket"], "Sensor",
                                          (100, 100, 120), (250, 100, 20))
        self.wait = 300

    def u_claim_path(self):
        self._uc["Path"] = self.u_claim("Keep-out for the optical path, with a 2 mm margin", [], "Optics",
                                        (60, 20, 20), (190, 140, 90), kind="Keep-out", margin=2.0)
        self.wait = 300

    def u_findings(self):
        from . import claims
        return claims.last.get("findings", [])

    def u_check(self):
        b, where = self.click_ribbon("Check Volume Claims", tab="Assemblies")
        QtWidgets.QApplication.processEvents()
        f = self.u_findings()
        kinds = sorted((x["kind"], x["other"]) for x in f)
        want = sorted([("outside", "Cable bracket"), ("intrusion", "Cable bracket"), ("intrusion", "Cable bracket"),
                       ("overlap", "Claim Optics")])
        self.step("Check Volume Claims", f"ribbon '{where} > Check Volume Claims'", DIFFERS if kinds == want else FAIL,
                  "; ".join(x["text"] for x in f) + ". The offending volumes are drawn in red")
        self.view().viewIsometric()
        self.fit()
        self.shot("U_claims_violated.png")
        self.p_close_info()
        self.wait = 300

    def u_fix(self):
        doc = App.ActiveDocument
        self._uc["Path"].Placement.Base = App.Vector(190, 140, 110)
        self._u["Cable bracket"].Placement.Base = App.Vector(305, 182, 40)
        doc.recompute()
        self.step("The optics designer raises the beam path to 110 mm; the sensor team moves its cable bracket "
                  "into its own claim", "the keep-out's and the bracket's Placement", DIFFERS,
                  "in NX the bracket would be moved with Move Component; the claim's placement is a property")
        self.wait = 300

    def u_recheck(self):
        b, where = self.click_ribbon("Check Volume Claims", tab="Assemblies")
        QtWidgets.QApplication.processEvents()
        f = self.u_findings()
        ok = not f and all(c.Status == "OK" for c in self._uc.values()) and \
            App.ActiveDocument.getObject("ClaimViolations") is None
        self.step("Check Volume Claims again: every part inside its claim, no intrusion, no space claimed twice",
                  f"ribbon '{where} > Check Volume Claims'", DIFFERS if ok else FAIL,
                  "; ".join(x["text"] for x in f) or "no findings")
        self.shot("U_claims_ok.png")
        self.p_close_info()
        self.wait = 300

    def u_browser(self):
        return self.p_widget(QtWidgets.QTreeWidget, "clearanceTree")

    def u_counts(self, cset):
        return {k: getattr(cset, k.capitalize()) for k in ("hard", "containment", "touching", "soft")}

    def u_clearance(self):
        from . import clearance
        Gui.Selection.clearSelection()
        b, where = self.click_ribbon("Clearance Analysis", tab="Assemblies")
        QtWidgets.QApplication.processEvents()
        ok = self.p_spin("clearanceZone", 3.0) and self.p_button("performAnalysis")
        sets = clearance.sets(App.ActiveDocument)
        cset = sets[-1] if sets else None
        self._u_set = cset
        counts = self.u_counts(cset) if cset else {}
        rows, _ = clearance.results_of(cset) if cset else ([], [])
        pairs = {tuple(sorted((r["a"], r["b"]))): r for r in rows}
        want = {("Dowel", "Frame"): "containment", ("Frame", "Stage"): "touching",
                ("Frame", "Sensor housing"): "touching", ("Cable bracket", "Sensor housing"): "soft",
                ("Cover screw", "Sensor housing"): "hard"}
        got = {k: r["kind"] for k, r in pairs.items()}
        screw = pairs.get(("Cover screw", "Sensor housing"))
        good = ok and got == want and screw is not None and abs(screw["penetration"] - 4.0) < 1e-3
        self.step("Assemblies > Clearance Analysis: a clearance set of every part, zone 3 mm, Perform Analysis",
                  f"ribbon '{where} > Clearance Analysis', 3 typed, 'Perform Analysis'", DIFFERS if good else FAIL,
                  f"{counts}; " + "; ".join(f"{a}/{b} {r['kind']}" + (f" (penetration {r['penetration']:.2f}, "
                                                                       f"{r['volume']:.1f} mm³)" if r['volume'] else
                                                                       f" ({r['distance']:.2f} mm)")
                                            for (a, b), r in sorted(pairs.items())) +
                  ". NX: the same four kinds; FreeCAD had only Part > Check Geometry and booleans")
        self.shot("U_clearance_browser.png")
        self.wait = 300

    def u_item(self, pair):
        tree = self.u_browser()
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            for k in range(top.childCount()):
                it = top.child(k)
                if sorted((it.text(0), it.text(1))) == sorted(pair):
                    return it
        return None

    def u_study(self):
        tree = self.u_browser()
        it = self.u_item(("Dowel", "Frame"))
        tree.setCurrentItem(it)
        self.p_button("studyInterference")
        shown = sorted(o.Label for o in App.ActiveDocument.Objects
                       if getattr(o, "ViewObject", None) is not None and o.ViewObject.Visibility
                       and o.isDerivedFrom("Part::Feature"))
        ok = it is not None and set(shown) <= {"Dowel", "Frame", "Clearance interferences"} and "Dowel" in shown
        self.view().viewIsometric()
        self.fit()
        self.shot("U_study.png")
        self.p_button("restoreVisibility")
        back = App.ActiveDocument.getObject(self._u["Stage"].Name).ViewObject.Visibility
        self.step("Study Interference on the dowel in the frame, then Restore Visibility",
                  "row picked in the browser + 'Study Interference', 'Restore Visibility'",
                  SAME if ok and back else FAIL, f"shown while studying: {shown}; NX: MB3 > Study Interference "
                  "and Restore Component Visibility")
        self.wait = 300

    def u_exclude(self):
        from . import clearance
        tree = self.u_browser()
        tree.setCurrentItem(self.u_item(("Cover screw", "Sensor housing")))
        self.p_button("excludePair")
        rows, gone = clearance.results_of(self._u_set)
        counts = self.u_counts(self._u_set)
        ok = counts["hard"] == 0 and len(gone) == 1 and any("Cover screw" in r for r in self._u_set.PairRules)
        self.step("Exclude Pair: the screw's thread engagement is intended; the analysis runs again",
                  "hard row picked + 'Exclude Pair'", SAME if ok else FAIL,
                  f"{counts}; gone since the last run: {gone}; the rule is kept in the set's PairRules, so the next "
                  "check after a design change skips it too")
        self.wait = 300

    # ================================================================ tutorial V
    # Tutorial T's guide bush, released and changed with Strata (Teamcenter's role here): turn on version
    # control, a version, release BUSH-100 rev A, publish the release package; engineering change ECO-001
    # (bore H7 -> F7 for a shaft that runs warmer), version V2, compare, rev B, rev A obsolete, package B.
    def V_STEPS(self):
        return [self.v_new, self.v_start, self.v_version1, self.v_release1, self.v_package1, self.v_eco,
                self.v_version2, self.v_compare, self.v_release2, self.v_obsolete, self.v_package2, self.v_done]

    def v_modal(self, actions):
        """Answer the dialogs Strata opens (modal), as the user would: {title prefix: fn(dialog)}."""
        def handler(w):
            title = w.windowTitle()
            for key, fn in actions.items():
                if title.startswith(key):
                    fn(w)
                    return True
            return False
        self.modals.handler = handler

    @staticmethod
    def v_press(w, text):
        for b in w.findChildren(QtWidgets.QAbstractButton):
            if b.text().replace("&", "") == text and b.isVisible():
                b.click()
                return True
        return False

    def v_project(self):
        from strata.project import Project
        return Project.locate(App.ActiveDocument.FileName)

    def v_panel(self):
        from . import plm
        return plm.strata_panel()

    def v_new(self):
        self.tutorial = "V: Release and engineering change of the guide bush (Strata), with release packages"
        doc = self._t_body.Document
        App.setActiveDocument(doc.Name)
        Gui.getDocument(doc.Name)
        self._v_root = os.path.join(_out(), "V_project")
        os.makedirs(self._v_root, exist_ok=True)
        doc.saveAs(os.path.join(self._v_root, "GuideBush.FCStd"))
        self._v_doc = doc
        # back to the part's 3D view (tutorial T ended on its drawing sheet)
        try:
            Gui.activateView("Gui::View3DInventor", True)
        except Exception:
            pass
        panel = self.v_panel()
        if panel is not None and panel.isVisible():
            panel.raise_()                        # already among the navigators: its tab, as a user clicks it
            how = "the Versions and history tab of the navigators"
        else:
            b, where = self.click_ribbon("Versions and History", tab="PLM")
            how = f"ribbon '{where} > Versions and History'"
        QtWidgets.QApplication.processEvents()
        self.step("The guide bush of tutorial T, saved in a project folder; Versions and history", how,
                  SAME if panel is not None and panel.isVisible() else FAIL,
                  "Strata's panel among the navigators (Teamcenter's place in NX); the ribbon button shows or hides it")
        self.wait = 800

    def v_start(self):
        root = self._v_root

        def start(w):
            w.folder.setText(root)
            w.user.setText("NX-Style replay")
            w.primary.click()
        self.v_modal({"Turn on version control": start})
        panel = self.v_panel()
        from .tutorial import qtest
        qtest().mouseClick(panel.empty_btn, Qt.LeftButton)
        QtWidgets.QApplication.processEvents()
        self.modals.handler = None
        proj = self.v_project()
        self.step("Turn on version control for the project folder", "'Turn on version control', folder and name, "
                  "'Turn on'", SAME if proj is not None else FAIL,
                  f"project {os.path.basename(proj.root) if proj else None}: every save is now recorded")
        self.wait = 800

    def v_version(self, name, desc):
        def create(w):
            w.name.setText(name)
            w.desc.setPlainText(desc)
            w.primary.click()

        def unsaved(w):
            self.v_press(w, "Save and continue")
        self._v_doc.save()
        self.v_modal({"Create version": create, "Unsaved changes": unsaved})
        b, where = self.click_ribbon("Create Version", tab="PLM")
        QtWidgets.QApplication.processEvents()
        self.modals.handler = None
        vs = [v.name for v in self.v_project().versions()]
        return name in vs, where, vs

    def v_version1(self):
        ok, where, vs = self.v_version("V1", "Guide bush as documented in tutorial T")
        self.step("Create Version V1", f"ribbon '{where} > Create Version', name and description, 'Create version'",
                  SAME if ok else FAIL, f"versions {vs}")
        self.wait = 600

    def v_release(self, version, pn, desc):
        def release(w):
            t = w.table
            t.item(0, 1).setText(pn)
            t.item(0, 3).setText(desc)
            w.primary.click()
        self.v_modal({f"Release {version}": release})
        self.v_panel().release(version)          # the version's right-click menu: Release
        QtWidgets.QApplication.processEvents()
        self.modals.handler = None
        return [(r.part_number, r.revision, r.state) for r in self.v_project().releases()]

    def v_release1(self):
        rels = self.v_release("V1", "BUSH-100", "Guide bush")
        ok = ("BUSH-100", "A", "Released") in rels
        self.step("Release V1 as part number BUSH-100: revision A", "the version's MB3 menu > Release; part number "
                  "typed; 'Release'", DIFFERS if ok else FAIL, f"releases {rels}; the menu item's action is called "
                  "(the replay does not open the context menu)")
        self.wait = 600

    def v_publish(self, label, rev, subfolder="packages", state="Released"):
        from . import package_ui, package
        out = os.path.join(_out(), subfolder)
        b, where = self.click_ribbon("Publish Release Package", tab="PLM")
        QtWidgets.QApplication.processEvents()
        combo = self.p_widget(QtWidgets.QComboBox, "release")
        if combo is not None:
            i = next((k for k in range(combo.count()) if f"rev {rev} " in combo.itemText(k)), -1)
            if i >= 0:
                combo.setCurrentIndex(i)
        choice = combo.currentText() if combo is not None else ""
        self.p_type("outputFolder", out)
        self.p_ok()
        QtWidgets.QApplication.processEvents()
        folder = os.path.join(out, f"BUSH-100_{rev}")
        problems = package.verify(folder) if os.path.isdir(folder) else ["no package"]
        m = package_ui.last.get("manifest", {})
        files = [e["path"] for e in m.get("files", [])]
        meta = m.get("package", {})
        need = [f"model/BUSH-100_{rev}.step", f"model/BUSH-100_{rev}.FCStd", "pmi/inspection_plan.csv", "pmi/pmi.json"]
        ok = (not problems and all(n in files for n in need) and any(f.startswith("drawings/") for f in files)
              and meta.get("revision") == rev and meta.get("state") == state and os.path.isfile(folder + ".zip"))
        self.step(label, f"ribbon '{where} > Publish Release Package', release '{choice}', folder typed, MB2 = OK",
                  DIFFERS if ok else FAIL, f"{len(files)} files ({', '.join(files)}); STEP schema "
                  f"{meta.get('step_schema', '?')}; standard {meta.get('standard', '?')}; checksums verified "
                  f"{'OK' if not problems else problems}. NX: File > Export > Publish Technical Data Package")
        self.p_close_info()
        return folder

    def v_package1(self):
        self._v_pkg_a = self.v_publish("Publish the release package of rev A", "A")
        self.wait = 600

    def v_eco(self):
        from . import pmi_ui, stackup_ui
        doc = self._v_doc
        bore = next(o for o in pmi_ui.all_pmi(doc) if getattr(o, "Fit", "") == "H7")
        bore.Fit = "F7"
        doc.recompute()
        s = stackup_ui.stackups(doc)[-1]
        self.key("Ctrl+S")
        QtWidgets.QApplication.processEvents()
        ok = bore.Callout.startswith("Ø16.000 F7 (+0.034/+0.016)") and abs(s.WorstCaseMin - 0.022) < 1e-9
        self.step("ECO-001: the bore Ø16 H7 becomes F7 (the shaft runs warmer); save", "the PMI's Fit property; Ctrl+S",
                  DIFFERS if ok else FAIL, f"{bore.Callout}; the fit's stack-up follows: clearance "
                  f"{s.WorstCaseMin:.3f} to {s.WorstCaseMax:.3f}; the save is recorded in the history")
        self.wait = 800

    def v_version2(self):
        ok, where, vs = self.v_version("V2", "ECO-001: bore F7 for a shaft that runs warmer")
        self.step("Create Version V2", f"ribbon '{where} > Create Version'", SAME if ok else FAIL, f"versions {vs}")
        self.wait = 600

    def v_compare(self):
        seen = {}

        def compare(w):
            for combo, text in ((w.a, "Version V1"), (w.b, "Version V2")):
                i = combo.findText(text)
                if i >= 0:
                    combo.setCurrentIndex(i)
            QtWidgets.QApplication.processEvents()
            items = []
            for i in range(w.tree.topLevelItemCount()):
                top = w.tree.topLevelItem(i)
                items.append(top.text(0))
                for k in range(top.childCount()):
                    c = top.child(k)
                    items.append(f"{c.text(0)}: {c.text(1)}")
                    for j in range(c.childCount()):
                        items.append(f"  {c.child(j).text(0)}: {c.child(j).text(1)}")
            seen["stats"] = w.stats.text()
            seen["items"] = items
            try:
                Gui.getMainWindow().grab().save(os.path.join(_out(), "V_compare_main.png"))
                w.grab().save(os.path.join(_out(), "V_compare.png"))
            except Exception:
                pass
            w.cancel_btn.click()
        self.v_modal({"Compare": compare})
        b, where = self.click_ribbon("Compare", tab="PLM")
        QtWidgets.QApplication.processEvents()
        self.modals.handler = None
        text = " | ".join(seen.get("items", []))
        ok = "F7" in text or "Fit" in text
        self.step("Compare V1 with V2", f"ribbon '{where} > Compare', From V1, To V2", SAME if ok else FAIL,
                  f"{seen.get('stats', 'no dialog')}: {text[:400]}")
        self.wait = 400

    def v_release2(self):
        rels = self.v_release("V2", "BUSH-100", "ECO-001: bore F7")
        ok = ("BUSH-100", "B", "Released") in rels
        self.step("Release V2: the same part number, the next revision B", "MB3 > Release, 'Release'",
                  DIFFERS if ok else FAIL, f"releases {rels}")
        self.wait = 600

    def v_obsolete(self):
        # The clicks are scheduled, not made inside the handler: Mark obsolete opens a confirmation box
        # (a nested modal loop), and the watcher that answers it must not still be inside this call.
        state = {"dialog": None, "asked": False}

        def releases(w):
            if state["dialog"] is w:
                return
            state["dialog"] = w
            t = w.table
            for r in range(t.rowCount()):
                if t.item(r, 0) is not None and t.item(r, 1) is not None and t.item(r, 1).text() == "A":
                    t.selectRow(r)
                    break
            QtCore.QTimer.singleShot(200, w.obsolete.click)

        def confirm(w):
            if state["asked"]:
                return
            state["asked"] = True
            b = w.button(QtWidgets.QMessageBox.Yes) if isinstance(w, QtWidgets.QMessageBox) else None
            if b is not None:
                QtCore.QTimer.singleShot(100, b.click)
            if state["dialog"] is not None:
                QtCore.QTimer.singleShot(700, state["dialog"].cancel_btn.click)
        self.v_modal({"Releases": releases, "Mark obsolete": confirm})
        b, where = self.click_ribbon("Releases", tab="PLM")
        QtWidgets.QApplication.processEvents()
        self.modals.handler = None
        rels = [(r.part_number, r.revision, r.state) for r in self.v_project().releases()]
        ok = ("BUSH-100", "A", "Obsolete") in rels and ("BUSH-100", "B", "Released") in rels
        self.step("Releases: rev A marked obsolete", f"ribbon '{where} > Releases', row A, 'Mark obsolete', Yes",
                  SAME if ok else FAIL, f"releases {rels}")
        self.wait = 400

    def v_package2(self):
        self._v_pkg_b = self.v_publish("Publish the release package of rev B", "B")
        # rev A again, after the change: its package must come from what was released, not the working copy
        self._v_pkg_a2 = self.v_publish("Publish rev A again (now obsolete), after the change", "A",
                                        subfolder="packages_reissued", state="Obsolete")
        self.wait = 400

    def v_done(self):
        import csv
        rows = {}
        for rev, folder in (("A", self._v_pkg_a2), ("B", self._v_pkg_b)):
            try:
                with open(os.path.join(folder, "pmi", "inspection_plan.csv"), encoding="utf-8") as f:
                    rows[rev] = {r["requirement"]: r for r in csv.DictReader(f)}
            except OSError:
                rows[rev] = {}
        bore_a = next((r for k, r in rows["A"].items() if k.startswith("Ø16.000 H7")), None)
        bore_b = next((r for k, r in rows["B"].items() if k.startswith("Ø16.000 F7")), None)
        ok = (bore_a is not None and bore_b is not None and abs(float(bore_a["upper"]) - 16.018) < 1e-9
              and abs(float(bore_b["lower"]) - 16.016) < 1e-9)
        self.step("Each package documents its own revision: the inspection plans of A and B",
                  "the two packages' pmi/inspection_plan.csv", SAME if ok else FAIL,
                  f"rev A bore {bore_a['lower'] if bore_a else '?'} to {bore_a['upper'] if bore_a else '?'}; rev B "
                  f"{bore_b['lower'] if bore_b else '?'} to {bore_b['upper'] if bore_b else '?'}; rev A, published again "
                  "after the change, still documents H7: a package is made from what was released, not from the "
                  "working copy")
        self.shot("V_releases.png")

    def u_close(self):
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        text = self.p_info_text()
        self.step("OK: the clearance report", "MB2 = OK", SAME if "Assembly clearance" in text else FAIL,
                  "the clearance set stays in the Part Navigator; double-click it to run it again")
        self.p_close_info()
        App.ActiveDocument.save()
