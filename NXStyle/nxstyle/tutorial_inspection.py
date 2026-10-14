# SPDX-License-Identifier: LGPL-2.1-or-later
"""Inspection tutorials: from the PMI to the measured part and the released sheet.

  AA  a hole pattern with a composite position frame (ASME Y14.5; Cogorno ch. 12 and 13): the frame
      and its rule checks, the inspection plan's two rows and two gauges, and the pattern evaluated
      from CMM data: the pattern-locating zones fixed to A|B|C, the feature-relating zones best-fit
  AB  measurement capability (Drake ch. 25; ISO 14253-1): the uncertainty of each inspection method,
      the TUR and the guard-banded acceptance limits in the inspection plan, and two gauge studies
  AC  the guide bush's drawing: its title block from the Strata release and its revision block from
      the release history (runs T and V first)
"""

import os

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtWidgets

SAME, DIFFERS, MISSING, FAIL = "same", "differs", "missing", "FAILED"


def _out():
    return os.environ.get("NXSTYLE_TUTORIAL_OUT", "")


class InspectionTutorials:
    """Mixin for tutorial.Replay (uses the p_ helpers of PrecisionTutorials)."""

    def i_combo(self, name, text):
        """Pick an item of a combo box in the open dialog."""
        w = self.p_widget(QtWidgets.QComboBox, name)
        if w is None:
            return False
        i = w.findText(text)
        if i < 0:
            return False
        w.setCurrentIndex(i)
        QtWidgets.QApplication.processEvents()
        return True

    def i_lines(self, name, lines):
        """Type lines into a plain text box of the open dialog, Return after each."""
        from .smoke import decode
        from .tutorial import qtest
        w = self.p_widget(QtWidgets.QPlainTextEdit, name)
        if w is None:
            return False
        w.setFocus()
        w.selectAll()
        for ln in lines:
            qtest().keyClicks(w, ln)
            qtest().keyClick(w, *decode("Return"))
        QtWidgets.QApplication.processEvents()
        return w.toPlainText().split() == " ".join(lines).split()

    def i_pmi(self, label, obj, faces, ribbon, fill, check, how, outcome=DIFFERS, shot=None):
        """Select faces, start a PMI command on the PMI tab, fill its dialog, MB2 = OK, check the new PMI."""
        from . import pmi_ui
        doc = App.ActiveDocument
        before = {o.Name for o in pmi_ui.all_pmi(doc)}
        self.p_select([(obj, f) for f in faces])
        b, where = self.click_ribbon(ribbon, tab="PMI")
        QtWidgets.QApplication.processEvents()
        filled = fill()
        if shot:
            self.shot(shot)
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        doc.recompute()
        new = [o for o in pmi_ui.all_pmi(doc) if o.Name not in before]
        o = new[-1] if new else None
        ok = bool(filled) and o is not None and check(o) and not Gui.Control.activeDialog()
        self.step(label, f"{len(faces)} face(s) selected + ribbon '{where} > {ribbon}'; {how}; MB2 = OK",
                  outcome if ok else FAIL, o.Callout if o is not None else "no PMI made")
        return o

    # ================================================================ tutorial AA
    # A plate 80 x 80 x 10 with four holes Ø5 +0.2/0 at 20 and 60 from datums B and C, located Ø0.2 (M) to
    # A|B|C and held to each other Ø0.04 (M), oriented to A: the layout of Cogorno's graphic analysis example
    # (ch. 13), in millimetres. The measured data are ours.
    AA_HOLES = [(20.0, 20.0), (20.0, 60.0), (60.0, 60.0), (60.0, 20.0)]
    AA_MEASURED = [("19.94", "20.06", "5.12"), ("20.08", "60.08", "5.16"), ("60.12", "59.96", "5.20"),
                   ("60.04", "19.96", "5.08")]

    def AA_STEPS(self):
        return [self.p_modeling, self.aa_new, self.aa_part, self.aa_frame, self.aa_plan, self.aa_rule, self.aa_eval,
                self.aa_slide, self.aa_show]

    def aa_new(self):
        self.tutorial = "AA: Composite position of a hole pattern, evaluated from CMM data"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def aa_part(self):
        import Part
        from . import pmi_ui
        self.wait_for("aa_part: document", lambda: App.ActiveDocument is not None)
        doc = App.ActiveDocument
        shape = Part.makeBox(80, 80, 10)
        for x, y in self.AA_HOLES:
            shape = shape.cut(Part.makeCylinder(2.5, 10, App.Vector(x, y, 0)))
        plate = doc.addObject("Part::Feature", "Plate")
        plate.Shape = shape
        plate.Label = "Cover plate"
        doc.recompute()
        self._aa_plate = plate
        self._aa_holes = [self.p_face(plate, lambda f, x=x, y=y: f.Surface.__class__.__name__ == "Cylinder"
                                      and abs(f.Surface.Center.x - x) < 1e-6 and abs(f.Surface.Center.y - y) < 1e-6)
                          for x, y in self.AA_HOLES]
        A, B, C = (self.p_face(plate, self.p_plane_at(a, 0.0)) for a in ("z", "x", "y"))
        pmi_ui.folder(doc).Standard = "ASME Y14.5"
        made = [pmi_ui.create("Datum Feature", [(plate, A)], doc, Letter="A"),
                pmi_ui.create("Datum Feature", [(plate, B)], doc, Letter="B"),
                pmi_ui.create("Datum Feature", [(plate, C)], doc, Letter="C"),
                pmi_ui.create("Dimension", [(plate, h) for h in self._aa_holes], doc, DimensionType="Diameter",
                              UpperDeviation=0.2, LowerDeviation=0.0, Quantity=4)]
        doc.recompute()
        doc.saveAs(os.path.join(_out(), "CoverPlate.FCStd"))
        self.view().viewIsometric()
        self.fit()
        ok = all(self._aa_holes) and made[-1].Callout == "4X Ø5.000 +0.200/0"
        self.step("The cover plate: four holes 4X Ø5 +0.2/0 on a 40 mm square; datums A (underside), B (left), C "
                  "(front); ASME Y14.5", "modelled by script, the datums and the size made as in tutorial T",
                  DIFFERS if ok else FAIL, "; ".join(o.Callout for o in made))
        self.wait = 500

    def aa_frame(self):
        def fill():
            return all([self.i_combo("characteristic", "Position"), self.p_check("zoneDiameter"),
                        self.p_type("tolerance", "0.2"), self.i_combo("materialCondition", "MMC"),
                        self.p_type("datum1", "A"), self.p_type("datum2", "B"), self.p_type("datum3", "C"),
                        self.i_combo("frameStyle", "Composite Frame"), self.p_type("lowerTolerance", "0.04"),
                        self.i_combo("lowerMaterialCondition", "MMC"), self.p_type("lowerDatums", "A")])
        want = "position | Ø0.200 (M) | A | B | C / Ø0.040 (M) | A"
        self._aa_frame = self.i_pmi(
            "Feature Control Frame, Frame Style Composite: the pattern Ø0.2 (M) to A|B|C, the holes to each other "
            "Ø0.04 (M) oriented to A", self._aa_plate, self._aa_holes, "Feature Control Frame", fill,
            lambda o: o.Callout == want, "Position, Ø ticked, 0.2, MMC, A B C; Frame Style Composite Frame, lower "
            "row 0.04, MMC, datum A", SAME, shot="AA_dialog.png")
        self.wait = 400

    def aa_plan(self):
        b, where = self.click_ribbon("Inspection Plan", tab="PMI")
        QtWidgets.QApplication.processEvents()
        text = self.p_info_text()
        rows = [ln.strip() for ln in text.splitlines() if "pattern-locating" in ln or "feature-relating" in ln]
        gauges = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("gauge pin")]
        ok = (len(rows) == 2 and any("Ø4.800" in g for g in gauges) and any("Ø4.960" in g and "float" in g
                                                                             for g in gauges)
              and "Checks: no issues" in text)
        self.step("Inspection Plan: one row per segment, one functional gauge per row", f"ribbon '{where} > "
                  "Inspection Plan'", DIFFERS if ok else FAIL,
                  "PLTZF Ø0.2 at MMC up to Ø0.4 at LMC, gauge pins Ø4.8 on A|B|C; FRTZF Ø0.04 up to Ø0.24, gauge "
                  "pins Ø4.96 that float on A (Cogorno ch. 13: a composite frame takes two gauges). NX lists the "
                  "frame; the plan and the gauges are NXStyle's")
        self.p_shot_info("AA_plan.png")
        self.p_close_info()
        self.wait = 300

    def aa_rule(self):
        f = self._aa_frame
        f.LowerDatumReferences = ["B"]             # the PMI's property, as edited in the property view
        App.ActiveDocument.recompute()
        self.click_ribbon("Inspection Plan", tab="PMI")
        QtWidgets.QApplication.processEvents()
        text = self.p_info_text()
        caught = "may only repeat the upper row's datums" in text
        self.p_close_info()
        f.LowerDatumReferences = ["A"]
        App.ActiveDocument.recompute()
        self.step("A composite lower row may only repeat the upper row's datums, in order", "the frame's "
                  "LowerDatumReferences set to B in the property view; Inspection Plan; set back to A",
                  DIFFERS if caught and f.Callout.endswith("/ Ø0.040 (M) | A") else FAIL,
                  "the check reports B as an error: the lower row orients to the datums it repeats, starting with "
                  "the primary (Cogorno ch. 12, Drake ch. 5)")
        self.wait = 300

    def aa_eval(self):
        doc = App.ActiveDocument
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, self._aa_frame.Name)
        QtWidgets.QApplication.processEvents()
        before = {o.Name for o in doc.Objects}
        b, where = self.click_ribbon("Position Evaluation", tab="Analysis")
        QtWidgets.QApplication.processEvents()
        table = self.p_widget(QtWidgets.QTableWidget, "measurements")
        typed = table is not None and table.rowCount() == 4 and all(
            self.p_cell(table, r, 2 + c, v) for r, row in enumerate(self.AA_MEASURED) for c, v in enumerate(row))
        self.shot("AA_measured.png")
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        e = next((o for o in doc.Objects if o.Name not in before and hasattr(o, "LowerUsed")), None)
        self._aa_eval = e
        ok = (typed and e is not None and e.Verdict == "ACCEPT" and abs(e.UpperUsed - 63.2) < 0.5
              and abs(e.LowerUsed - 71.5) < 0.2)
        self.step("Analysis > Position Evaluation: the measured holes against both rows", f"the frame selected + "
                  f"ribbon '{where} > Position Evaluation'; the CMM's 12 values typed into the table; MB2 = OK",
                  DIFFERS if ok else FAIL,
                  (f"{e.Verdict}: the pattern-locating zones (with each hole's bonus) {e.UpperUsed:.0f} % used; the "
                   f"feature-relating zones, moved and turned to fit, {e.LowerUsed:.0f} % used. The paper gauge of "
                   "Cogorno ch. 13 done numerically: a minimax fit. NX has no evaluation of measured data (that is a "
                   "CMM program's job)") if e else "no evaluation")
        self.p_shot_info("AA_evaluation.png")
        self.p_close_info()
        self.wait = 300

    def aa_slide(self):
        e = self._aa_eval
        e.ViewObject.doubleClicked()
        QtWidgets.QApplication.processEvents()
        picked = self.i_combo("lowerMotion", "Translate only")
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        ok = picked and e.Verdict == "REJECT" and e.LowerUsed > 100
        self.step("The same holes if the lower row could not turn (as if it repeated A|B)", "the evaluation "
                  "double-clicked, Lower row zones 'Translate only', MB2 = OK", DIFFERS if ok else FAIL,
                  f"{e.Verdict}: {e.LowerUsed:.0f} % of the feature-relating zones. The datums a composite lower row "
                  "repeats decide how its zones may move, and so whether the part passes")
        self.p_shot_info("AA_slide.png")
        self.p_close_info()
        e.LowerMotion = "From datums"
        App.ActiveDocument.recompute()
        self.wait = 300

    def aa_show(self):
        self.view().viewIsometric()
        self.fit()
        QtWidgets.QApplication.processEvents()
        self.check_drawn("The cover plate with its composite frame", "AA_pmi.png")
        App.ActiveDocument.save()

    # ================================================================ tutorial AB
    # A bearing plate 60 x 40 x 12 with a bore Ø20 H7. The inspection methods' uncertainties are ours;
    # Drake's worked gauge study (ch. 25: a position tolerance of 0.2 mm, ten parts measured twice) uses
    # the book's ranges.
    AB_DRAKE = [(0.06, 0.08), (0.08, 0.12), (0.10, 0.14), (0.05, 0.11), (0.12, 0.12), (0.07, 0.11), (0.09, 0.13),
                (0.11, 0.13), (0.06, 0.08), (0.08, 0.12)]
    AB_AIR = [(20.0081, 20.0083), (20.0102, 20.0106), (20.0094, 20.0096), (20.0077, 20.0080), (20.0110, 20.0111),
              (20.0088, 20.0092), (20.0099, 20.0102), (20.0085, 20.0087), (20.0105, 20.0108), (20.0091, 20.0093)]

    def AB_STEPS(self):
        return [self.p_modeling, self.ab_new, self.ab_part, self.ab_bore, self.ab_thickness, self.ab_flatness,
                self.ab_plan, self.ab_drake, self.ab_air, self.ab_show]

    def ab_new(self):
        self.tutorial = "AB: Measurement capability: uncertainty, TUR, guard bands and gauge studies"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def ab_part(self):
        import Part
        from . import pmi_ui
        self.wait_for("ab_part: document", lambda: App.ActiveDocument is not None)
        doc = App.ActiveDocument
        plate = doc.addObject("Part::Feature", "BearingPlate")
        plate.Shape = Part.makeBox(60, 40, 12).cut(Part.makeCylinder(10, 12, App.Vector(30, 20, 0)))
        plate.Label = "Bearing plate"
        doc.recompute()
        self._ab_plate = plate
        self._ab_faces = {"bore": self.p_face(plate, self.p_cylinder(10.0)),
                          "A": self.p_face(plate, self.p_plane_at("z", 0.0)),
                          "top": self.p_face(plate, self.p_plane_at("z", 12.0)),
                          "B": self.p_face(plate, self.p_plane_at("x", 0.0)),
                          "C": self.p_face(plate, self.p_plane_at("y", 0.0))}
        f = self._ab_faces
        g = pmi_ui.folder(doc)
        g.GeneralTolerance = "ISO 2768-mK"
        made = [pmi_ui.create("Datum Feature", [(plate, f[x])], doc, Letter=x) for x in "ABC"]
        self._ab_position = pmi_ui.create("Feature Control Frame", [(plate, f["bore"])], doc, Characteristic="Position",
                                          Tolerance=0.2, ZoneDiameter=True, DatumReferences=["A", "B", "C"])
        doc.recompute()
        doc.saveAs(os.path.join(_out(), "BearingPlate.FCStd"))
        self.view().viewIsometric()
        self.fit()
        self.step("The bearing plate: a bore Ø20 positioned Ø0.2 to A|B|C (RFS, as in Drake's gauge study)",
                  "modelled by script, datums and frame made as in tutorial T", DIFFERS,
                  "; ".join(o.Callout for o in made + [self._ab_position]))
        self.wait = 500

    def ab_bore(self):
        def fill():
            return self.p_type("fit", "H7") and self.p_spin("uncertainty", 0.002)
        self._ab_bore = self.i_pmi("Rapid Dimension: the bore Ø20 H7, checked with a bore gauge, U = 0.002",
                                   self._ab_plate, [self._ab_faces["bore"]], "Rapid Dimension", fill,
                                   lambda o: o.Callout.startswith("Ø20.000 H7") and abs(o.Uncertainty - 0.002) < 1e-12,
                                   "'H7' typed, measurement uncertainty 0.002 typed")
        self.wait = 300

    def ab_thickness(self):
        def fill():
            return all([self.p_spin("upperDeviation", 0.05), self.p_spin("lowerDeviation", 0.05),
                        self.p_spin("uncertainty", 0.01)])
        self.i_pmi("Rapid Dimension: the thickness 12 ±0.05, measured with a micrometer, U = 0.01", self._ab_plate,
                   [self._ab_faces["A"], self._ab_faces["top"]], "Rapid Dimension", fill,
                   lambda o: o.Callout == "12.000 ±0.050" and abs(o.Uncertainty - 0.01) < 1e-12,
                   "±0.05 and the uncertainty typed")
        self.wait = 300

    def ab_flatness(self):
        def fill():
            return all([self.i_combo("characteristic", "Flatness"), self.p_type("tolerance", "0.01"),
                        self.p_spin("uncertainty", 0.004)])
        self.i_pmi("Feature Control Frame: the top face flat to 0.01, on a surface plate with an indicator, U = 0.004",
                   self._ab_plate, [self._ab_faces["top"]], "Feature Control Frame", fill,
                   lambda o: o.Characteristic == "Flatness" and abs(o.Uncertainty - 0.004) < 1e-12,
                   "Flatness, 0.01, the uncertainty typed")
        self.wait = 300

    def ab_plan(self):
        b, where = self.click_ribbon("Inspection Plan", tab="PMI")
        QtWidgets.QApplication.processEvents()
        text = self.p_info_text()
        ok = ("TUR 5.3:1 (meets 4:1); accept 20.002 to 20.019" in text
              and "TUR 5.0:1 (meets 4:1); accept 11.960 to 12.040" in text
              and "TUR 1.3:1 (below 4:1" in text and "accept 0.006 max" in text)
        self.step("Inspection Plan: each method's TUR and the ISO 14253-1 acceptance limits", f"ribbon '{where} > "
                  "Inspection Plan'", DIFFERS if ok else FAIL,
                  "the bore is accepted only from 20.002 to 20.019, the thickness from 11.960 to 12.040: the "
                  "specification less U at each limit, so no part is accepted on a doubtful reading. The flatness "
                  "check uses 80 % of its tolerance (TUR 1.25): accept up to 0.006, or find a better method. NX has "
                  "no measurement capability in its PMI")
        self.p_shot_info("AB_plan.png")
        self.p_close_info()
        self.wait = 300

    def ab_study(self, pmi_obj, gauge, readings, spread):
        doc = App.ActiveDocument
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, pmi_obj.Name)
        QtWidgets.QApplication.processEvents()
        before = {o.Name for o in doc.Objects}
        b, where = self.click_ribbon("Gauge Study", tab="Analysis")
        QtWidgets.QApplication.processEvents()
        typed = all([self.p_type("gauge", gauge), self.i_lines("readings", [f"{a:.4f} {b:.4f}" for a, b in readings]),
                     self.i_combo("spread", spread)])
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        s = next((o for o in doc.Objects if o.Name not in before and hasattr(o, "Percent")), None)
        return typed, where, s

    def ab_drake(self):
        typed, where, s = self.ab_study(self._ab_position, "CMM", self.AB_DRAKE, "3 sigma (Drake ch. 25)")
        ok = typed and s is not None and round(s.Percent, 1) == 42.6 and s.Verdict.startswith("unacceptable")
        self.step("Gauge Study on the position Ø0.2: Drake's worked example (ten parts, two readings each)",
                  f"the frame selected + ribbon '{where} > Gauge Study'; gauge, 20 readings and the spread typed; "
                  "MB2 = OK", DIFFERS if ok else FAIL,
                  (f"average range {s.Sigma * 1.128:.3f}, σ = {s.Sigma:.4f}, 3σ = {3 * s.Sigma:.3f} mm: "
                   f"{s.Percent:.1f} % of the tolerance, {s.Verdict.split(':')[0]} (Drake: 42.6 %, over 30 %). "
                   "With AIAG's 6σ it would be twice that") if s else "no study")
        self.p_shot_info("AB_drake.png")
        self.p_close_info()
        self.wait = 300

    def ab_air(self):
        typed, where, s = self.ab_study(self._ab_bore, "Air gauge", self.AB_AIR, "6 sigma (AIAG MSA)")
        ok = typed and s is not None and s.Percent < 10 and s.Verdict == "acceptable"
        self.step("Gauge Study on the bore Ø20 H7 with an air gauge", f"the bore's PMI selected + ribbon '{where} > "
                  "Gauge Study'; readings typed; 6σ; MB2 = OK", DIFFERS if ok else FAIL,
                  (f"σ = {s.Sigma * 1000:.2f} µm, 6σ uses {s.Percent:.1f} % of the 0.021 tolerance: {s.Verdict}. "
                   "The study is kept in the part, beside the PMI it qualifies") if s else "no study")
        self.p_shot_info("AB_air.png")
        self.p_close_info()
        self.wait = 300

    def ab_show(self):
        self.view().viewIsometric()
        self.fit()
        QtWidgets.QApplication.processEvents()
        self.check_drawn("The bearing plate with its PMI", "AB_pmi.png")
        App.ActiveDocument.save()

    # ================================================================ tutorial AC
    # Tutorial V left the guide bush released twice (A, now obsolete, and B after ECO-001); its drawing is
    # tutorial T's. The sheet's title block is filled from release B, its revision block from both.
    def AC_STEPS(self):
        return [self.ac_open, self.ac_sheet, self.ac_populate, self.ac_show]

    def ac_open(self):
        self.tutorial = "AC: The title block and revision block from the release (runs T and V first)"
        doc = self._v_doc
        App.setActiveDocument(doc.Name)
        Gui.getDocument(doc.Name)
        self._ac_doc = doc
        self.key("Ctrl+Shift+D")
        self.wait = 2500

    def ac_sheet(self):
        page = self._t_page
        try:
            page.ViewObject.show()
        except Exception:
            pass
        QtWidgets.QApplication.processEvents()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self._ac_doc.Name, page.Name)
        tmpl = os.path.basename(page.Template.Template) if page.Template else ""
        self.step("The guide bush's drawing (tutorial T) in Drafting", "Ctrl+Shift+D; the sheet selected in the Part "
                  "Navigator", SAME if page is not None else FAIL,
                  f"template {tmpl}: FreeCAD's default sheet has no title block")
        self.wait = 500

    def ac_populate(self):
        from . import titleblock_ui
        page = self._t_page
        b, where = self.click_ribbon("Populate Title Block")
        QtWidgets.QApplication.processEvents()
        prefilled = {n: (self.p_widget(QtWidgets.QLineEdit, n).text() if self.p_widget(QtWidgets.QLineEdit, n)
                         else None) for n in ("drawing_number", "revision_index", "title", "general_tolerances")}
        ticked = self.p_check("revisionBlock")
        self.shot("AC_dialog.png")
        how = self.p_ok()
        QtWidgets.QApplication.processEvents()
        texts = dict(page.Template.EditableTexts)
        block = next((v for v in page.Views if getattr(v, "NX_Kind", "") == "revision block"), None)
        ok = (ticked and texts.get("drawing_number") == "BUSH-100" and texts.get("revision_index") == "B"
              and texts.get("title") == "Guide bush" and texts.get("general_tolerances") == "ISO 2768-mK"
              and not any(getattr(v, "NX_Pmi", "") == "tolerancing-note" for v in page.Views)
              and texts.get("document_status") == "Released" and block is not None and ">ECO-001" in block.Symbol
              and page.Template.Template.endswith("ISO5457_advanced.svg"))
        self.step("Drafting > Populate Title Block: from release B, the revision block from the releases",
                  f"ribbon '{where} > Populate Title Block'; the fields come filled; 'Revision block' ticked; {how}",
                  DIFFERS if ok else FAIL,
                  f"dialog: {prefilled}; sheet: number {texts.get('drawing_number')}, rev {texts.get('revision_index')}, "
                  f"{texts.get('document_status')}, by {texts.get('creator')}, tolerancing "
                  f"'{texts.get('general_tolerances')}'; revision block rows {titleblock_ui.revision_rows(self._ac_doc)}"
                  ". NX: Populate Title Block from DB_PART_NO and DB_PART_REV (Teamcenter); here from Strata")
        self.wait = 800

    def ac_show(self):
        from .tutorial import qtest
        App.ActiveDocument.recompute()
        qtest().qWait(800)
        QtWidgets.QApplication.processEvents()
        self.shot("AC_sheet.png")
        App.ActiveDocument.save()
        self.key("Ctrl+M")
        self.wait = 1500
