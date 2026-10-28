# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tutorials from chapter 5 (drafting) of Leu, Tao, Ghazanfari and Kolan, NX 12 for Engineering Design (Missouri
University of Science and Technology). The book works in inches; the parts are metric, their sizes the book's typed in
millimetres, so a drawing's dimension reads 25.4 times the book's number.

  AZ  5.2-5.4 Arbor Press Rack drawing: tutorial AT's rack on a B sheet (11 x 17) at 1:25; Base View Front,
      Projected Views above and to the right, Display Borders (off already), dimensions on the three views, a Section View
      through the hole in the end.
  BA  5.5 PMI on the impeller (tutorial AU's part): Linear and Radial PMI dimensions, a Centerline, a Note; a
      drawing whose views inherit the PMI (Aligned to Drawing).
  BB  5.6 Hex bolt drawing: tutorial AQ's screw on an E sheet (34 x 44) at 8:1; Front, Top and Right views with
      hidden lines dashed, vertical dimensions, a thread note with a leader, a radial dimension, an Isometric view.

5.7 (draft the chapter 4 parts) is an open exercise; it is not replayed.

Every check reads the drawing back from TechDraw (view directions, scales, the projected edges, dimension values,
the section) and compares it with the model's own geometry or the book's sizes built by the Part API.
"""

import math
import os

import FreeCAD as App
import FreeCADGui as Gui
from . import drafting_ui
from .qt import QtWidgets

IN = 25.4
SAME, DIFFERS, MISSING, FAIL = "same", "differs", "missing", "FAILED"
FRONT = ((0, -1, 0), (1, 0, 0))
ISO = ((1 / math.sqrt(3), -1 / math.sqrt(3), 1 / math.sqrt(3)), (1 / math.sqrt(2), 1 / math.sqrt(2), 0))
EDGE_TOL = 1e-2          # mm (unscaled view coordinates): a point counts as on a view edge within this


def _out():
    return os.environ.get("NXSTYLE_TUTORIAL_OUT", "")


class DraftingSteps:
    """Helpers shared by the chapter 5 tutorials: opening a saved part, sheets, views and dimensions through the
    Drafting ribbon, and reading the drawing back."""

    def dz_open(self, name, label, oracle=None):
        """File > Open of a part an earlier tutorial saved; (document, geometry check result, detail)."""
        self.clean_slate()                 # no dialog or edit mode left from the tutorial before
        path = os.path.join(_out(), name)
        for n, d in list(App.listDocuments().items()):
            if os.path.normcase(d.FileName or "") == os.path.normcase(path):
                App.closeDocument(n)
        QtWidgets.QApplication.processEvents()
        doc = App.openDocument(path) if os.path.exists(path) else None
        if doc is None:
            self.step(label, "File > Open (by script)", FAIL, f"no {path}: the tutorial that makes it saves it")
            raise RuntimeError(f"no {name}; the drawing cannot be made")
        App.setActiveDocument(doc.Name)
        ok, detail = (True, "")
        if oracle is not None:
            ok, detail = oracle(doc)
        self.step(label, "File > Open (by script)", SAME if ok else FAIL, detail)
        return doc

    def dz_template(self, name):
        import glob
        root = os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates")
        hits = glob.glob(os.path.join(root, "**", name), recursive=True)
        return hits[0] if hits else None

    def dz_sheet(self, template, scale, label, size_in):
        """New Sheet; the sheet's template, scale and third angle projection (NX asks in one Sheet dialog)."""
        wb = Gui.activeWorkbench().name()
        self.step("File > Drafting", "Ctrl+Shift+D", SAME if wb == "TechDrawWorkbench" else FAIL, wb)
        b, where = self.click_ribbon("New Sheet")
        QtWidgets.QApplication.processEvents()
        page = self.newest("TechDraw::DrawPage")
        path = self.dz_template(template)
        if page is not None and path:
            page.Template.Template = path
            page.ProjectionType = "Third angle"
            page.Scale = scale
        App.ActiveDocument.recompute()
        w, h = (float(page.Template.Width), float(page.Template.Height)) if page is not None else (0, 0)
        want = (size_in[0] * IN, size_in[1] * IN)
        ok = page is not None and abs(w - want[0]) < 0.5 and abs(h - want[1]) < 0.5 and abs(page.Scale - scale) < 1e-12
        self.step(label, f"ribbon '{where} > New Sheet'; the sheet's Template, Scale and Projection",
                  DIFFERS if ok else FAIL,
                  f"{os.path.basename(path or '?')}: {w:.1f} x {h:.1f} mm (the book's {size_in[0]:g} x {size_in[1]:g} "
                  f"in), scale {page.Scale if page else '?'}, {getattr(page, 'ProjectionType', '?')}. NX asks for size, "
                  "scale and projection in one Sheet dialog; FreeCAD's New Sheet uses the default template and these "
                  "are the sheet's properties")
        return page

    def dz_edges(self, view, what, timeout_ms=60000):
        """Wait for TechDraw's hidden-line worker to give the view's edges."""
        return self.wait_for(f"{what}: hidden-line worker", lambda: len(view.getVisibleEdges()) > 0, timeout_ms)

    def dz_base(self, page, sources, direction, xdirection, x, y, scale_type="Page"):
        """The sources selected + Base View, MB2 on the sheet; the view's direction (NX: Model View to Use)."""
        before = {v.Name for v in page.Views}
        Gui.Selection.clearSelection()
        for s in sources:
            Gui.Selection.addSelection(App.ActiveDocument.Name, s.Name)
        b, where = self.click_ribbon("Base View")
        QtWidgets.QApplication.processEvents()
        self.wait_for("base view", lambda: any(v.Name not in before for v in page.Views), 4000)
        new = [v for v in page.Views if v.Name not in before and v.isDerivedFrom("TechDraw::DrawViewPart")]
        v = new[-1] if new else None
        if v is not None:
            v.Direction, v.XDirection = App.Vector(*direction), App.Vector(*xdirection)
            self.dz_place(v, x, y, scale_type)
        self.wait_for("base view dialog", lambda: bool(Gui.Control.activeDialog()), 1500)
        if Gui.Control.activeDialog():
            self.mb2_click_on_sheet()
            QtWidgets.QApplication.processEvents()
        if not self.wait_for("base view dialog closed by MB2", lambda: not Gui.Control.activeDialog(), 3000):
            from .navigation import accept_task_dialog
            self.retries.append("Base View: MB2 on the sheet did not close the dialog; OK pressed")
            self.progress(f"dz_base: dialog still open after MB2: {self.task_widgets()}")
            accept_task_dialog()
            self.wait_for("base view dialog closed by OK", lambda: not Gui.Control.activeDialog(), 3000)
        App.ActiveDocument.recompute()
        return v, where

    def dz_projected(self, parent, sides):
        """The parent view selected + Projected View; one side button per view, MB2 on the sheet (NX: a click on
        each side of the parent, then Close)."""
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, parent.Name)
        QtWidgets.QApplication.processEvents()
        cmd = drafting_ui.COMMANDS["NXStyle_ProjectedView"]
        self.progress(f"dz_projected: parent {parent.Name} {parent.TypeId}; selection "
                      f"{[(o.Name, o.TypeId) for o in Gui.Selection.getSelection()]}; dialog "
                      f"{bool(Gui.Control.activeDialog())}; parent_view {getattr(drafting_ui.parent_view(), 'Name', None)}"
                      f"; IsActive {cmd.IsActive()}; document {App.ActiveDocument.Name}")
        b, where = self.click_ribbon("Projected View")
        QtWidgets.QApplication.processEvents()
        p = drafting_ui.current()
        made = {}
        if p is not None:
            for s in sides:
                btn = p.form.findChild(QtWidgets.QPushButton, f"projected{s}")
                if btn is not None:
                    btn.click()
                    QtWidgets.QApplication.processEvents()
                    made[s] = p.made[-1] if p.made else None
        self.mb2_click_on_sheet()
        QtWidgets.QApplication.processEvents()
        closed = drafting_ui.current() is None
        if not closed:
            drafting_ui.current().accept()
        App.ActiveDocument.recompute()
        return made, where, closed

    def dz_hidden_ready(self, view, what, tries=6):
        """Wait for a view's hidden lines. TechDraw's worker sometimes delivers none until the view is recomputed again
        (measured: none for 60 s after Hard Hidden was set, 60 hidden edges after a later recompute), so it is touched
        between waits, as tutorial Y does."""
        for k in range(tries):
            if self.wait_for(f"{what}: hidden lines (try {k + 1})", lambda: len(view.getHiddenEdges()) > 0, 10000):
                return True
            view.touch()
            view.recompute()
        return len(view.getHiddenEdges()) > 0

    @staticmethod
    def dz_lines(view, hidden=False):
        """The view's visible (or, with hidden, its dashed hidden) edges, unscaled and centred: getEdgeByIndex.
        getVisibleEdges gives them at the view's scale (measured: 120 x 50 for a 60 x 25 top view at 2:1)."""
        from . import pmi_ui
        return [e for _, e in pmi_ui._view_edges(view, hidden)]

    @classmethod
    def dz_span(cls, view):
        """(width, height) of a view's visible edges, unscaled (mm)."""
        bb = None
        for e in cls.dz_lines(view):
            bb = e.BoundBox if bb is None else bb.united(e.BoundBox)
        return (round(bb.XLength, 4), round(bb.YLength, 4)) if bb is not None else None

    @staticmethod
    def dz_oracle_span(shape, view):
        """What the Part API says an orthographic view of shape spans: its exact box seen along the view."""
        from . import drafting_core
        bb = shape.optimalBoundingBox(False, False)
        corners = [(x, y, z) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax) for z in (bb.ZMin, bb.ZMax)]
        w, h, _, _ = drafting_core.extent(corners, tuple(view.Direction), tuple(view.XDirection))
        return round(w, 4), round(h, 4)

    @classmethod
    def dz_on_edge(cls, view, q):
        """Distance (unscaled mm) from a view point to the nearest visible edge."""
        import Part
        v = Part.Vertex(App.Vector(q.x, q.y, 0))
        best = None
        for e in cls.dz_lines(view):
            try:
                d = e.distToShape(v)[0]
            except Exception:
                continue
            best = d if best is None or d < best else best
        return best

    def dz_vertex(self, view, p):
        """(vertex name, how) for a model point in a view: the view's own vertex there, else a cosmetic vertex, but
        only on a visible edge (so a point the model has no edge at is never dimensioned)."""
        from . import pmi_ui
        q = pmi_ui.view_xy(view, App.Vector(*p))
        for k in range(2000):
            try:
                pt = view.getVertexByIndex(k).Point
            except Exception:
                break
            if abs(pt.x - q.x) < EDGE_TOL and abs(pt.y - q.y) < EDGE_TOL:
                return f"Vertex{k}", "vertex"
        d = self.dz_on_edge(view, q)
        if d is None or d > EDGE_TOL:
            self.progress(f"dz_vertex: no edge at {tuple(round(c, 3) for c in p)} in {view.Label} (nearest {d})")
            return None, f"no edge within {EDGE_TOL} mm (nearest {d})"
        view.makeCosmeticVertex(App.Vector(q.x, q.y, 0))
        App.ActiveDocument.recompute()
        names = self.vertices_at(view, [q])
        return (names[0] if names else None), "cosmetic vertex on an edge"

    def dz_dimension(self, page, view, kind, p1, p2, offset):
        """Two model points' vertices selected + the ribbon's dimension; (dimension, how)."""
        _, how_a = self.dz_vertex(view, p1)
        _, how_b = self.dz_vertex(view, p2)
        # a cosmetic vertex renumbers the view's vertices: look both names up again once both exist (measured: the
        # first name went stale when the second point needed a cosmetic vertex, and no dimension was made)
        a, _ = self.dz_vertex(view, p1)
        b, _ = self.dz_vertex(view, p2)
        if not a or not b:
            return None, f"{how_a}; {how_b}"
        before = {d.Name for d in page.Views if d.isDerivedFrom("TechDraw::DrawViewDimension")}
        self.select_view_subs(view, [a, b])
        btn, where = self.click_ribbon(kind)
        QtWidgets.QApplication.processEvents()
        if Gui.Control.activeDialog():
            self.mb2_click_on_sheet()
        App.ActiveDocument.recompute()
        new = [d for d in page.Views if d.isDerivedFrom("TechDraw::DrawViewDimension") and d.Name not in before]
        d = new[-1] if new else None
        if d is not None:
            d.X, d.Y = offset
        return d, f"{a} ({how_a}), {b} ({how_b}) + ribbon '{where} > {kind}'"

    @staticmethod
    def dz_place(view, x, y, scale_type=None, scale=None):
        """Place a view on the sheet and set its scale; a projection group's view (what Base View makes in FreeCAD
        1.1) is placed and scaled through its group."""
        g = drafting_ui.group_of(view)
        target = g if g is not None and g.Anchor is view else view
        if scale_type is not None:
            target.ScaleType = scale_type
        if scale is not None:
            target.ScaleType, target.Scale = "Custom", scale
        if target is view and g is not None:
            gx, gy = drafting_ui.sheet_xy(g) if hasattr(g, "X") else (0.0, 0.0)
            view.X, view.Y = x - gx, y - gy
        else:
            target.X, target.Y = x, y
        App.ActiveDocument.recompute()

    @staticmethod
    def dz_close(a, b, tol=1e-3):
        return a is not None and b is not None and all(abs(p - q) < tol for p, q in zip(a, b))

    def dz_borders_off(self, page, label):
        """NX shows a border round each view until Display Borders is unchecked. The FreeCAD sheet's Show Frames is off
        by default; its own Turn View Frames On/Off stays greyed in 1.1.4, and no instrument here showed a change on
        screen when Show Frames was set (a grab of the sheet did not change even when a view was selected), so the
        replay reports the property and does not claim what the sheet looks like."""
        on = bool(page.ViewObject.ShowFrames)
        self.step(label, "nothing to press: the sheet's Show Frames is off", DIFFERS if not on else FAIL,
                  f"Show Frames {on}. NX shows the borders until this is unchecked; FreeCAD's sheet starts with Show "
                  "Frames off. Its Turn View Frames On/Off stays greyed in FreeCAD 1.1.4, so NX-Style has no Display "
                  "Borders button; how the sheet looks was not measured")
    def dz_fit_sheet(self):
        try:
            Gui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
        QtWidgets.QApplication.processEvents()


# ================================================================== AZ: the rack's drawing (5.2-5.4)
# The book (pp. 104-114): Arborpress_rack opened; File > Drafting; Standard Size B (11 x 17), Custom Scale 1:25; Base
# View Front; Projected Views; Drafting Preferences > View > Display Borders off; dimensions: the book's text puts the
# first one (240) on the front view's top corners, its figures dimension the 240 and the 34.8 in the top view, the
# tooth space's 6.000, 3.396 and 5.034 in the front view, the 20 and 25 in the right view (followed here); a Section
# View through the middle of the front view with the arrows up, dragged below it (section A-A, through the hole).
AZ_SCALE = 1 / 25


class MstRackDrawingTutorials(DraftingSteps):
    """Mixin for tutorial.Replay: tutorial AZ (it draws tutorial AT's rack)."""

    def AZ_STEPS(self):
        return [self.p_modeling, self.az_open, self.az_drafting, self.az_sheet, self.az_base, self.az_projected,
                self.az_borders, self.az_dimensions, self.az_section, self.az_section_dialog, self.az_section_check,
                self.az_save, self.az_show]

    def az_open(self):
        from . import geomcheck
        from .tutorial_mst4 import at_stages
        self.tutorial = "AZ: Arbor Press Rack drawing (NX 12 for Engineering Design, 5.2-5.4; book in inches, typed " \
                        "in mm)"
        self._az = at_stages()

        def oracle(doc):
            body = next((o for o in doc.Objects if o.isDerivedFrom("PartDesign::Body")), None)
            ok, detail = geomcheck.compare(body.Shape if body is not None else None, self._az["final"])
            return ok, f"tutorial AT's rack: {detail}"
        self._az_doc = self.dz_open("Arborpress_rack.FCStd", "Open Arborpress_rack (tutorial AT's part)", oracle)
        self._az_body = next(o for o in self._az_doc.Objects if o.isDerivedFrom("PartDesign::Body"))
        self.wait = 800

    def az_drafting(self):
        self.key("Ctrl+Shift+D")
        self.wait = 2500

    def az_sheet(self):
        self._az_page = self.dz_sheet("ANSIB_Landscape.svg", AZ_SCALE,
                                      "Sheet: Standard Size B 11 x 17, Custom Scale 1:25, OK", (17, 11))
        self.wait = 1200

    def az_base(self):
        v, where = self.dz_base(self._az_page, [self._az_body], *FRONT, 175.0, 140.0)
        ok = v is not None and self.dz_edges(v, "az front")
        span = self.dz_span(v) if ok else None
        want = self.dz_oracle_span(self._az_body.Shape, v) if v is not None else None
        good = ok and self.dz_close(span, want) and abs(drafting_ui.scale_of(v) - AZ_SCALE) < 1e-12
        self._az_front = v
        self.step("Base View: Model View to Use Front, Scale 1:25, a click to place it",
                  f"body selected + ribbon '{where} > Base View', MB2 on the sheet; the view's Direction Front",
                  DIFFERS if good else FAIL,
                  f"edges span {span} mm, the Part API {want} (240 x 20 in); scale {v.Scale if v else '?'} from the "
                  "sheet. NX lists the model views in the Base View dialog; TechDraw's view takes its direction as a "
                  "property")
        self.wait = 600

    def az_projected(self):
        made, where, closed = self.dz_projected(self._az_front, ("Above", "Right"))
        top, right = made.get("Above"), made.get("Right")
        rows = {}
        good = closed and top is not None and right is not None
        for name, v, d in (("top", top, (0, 0, 1)), ("right", right, (1, 0, 0))):
            if v is None:
                continue
            self.dz_edges(v, f"az {name}")
            span, want = self.dz_span(v), self.dz_oracle_span(self._az_body.Shape, v)
            rows[name] = {"direction": tuple(round(c, 6) for c in v.Direction), "span": span, "Part API": want,
                          "scale": drafting_ui.scale_of(v), "at": tuple(round(c, 2) for c in drafting_ui.sheet_xy(v))}
            good = good and self.dz_close(span, want) and tuple(v.Direction) == d and \
                abs(drafting_ui.scale_of(v) - drafting_ui.scale_of(self._az_front)) < 1e-12
        holes = [e for e in (self.dz_lines(right) if right is not None else []) if hasattr(e.Curve, "Radius")
                 and abs(e.Curve.Radius - self._az_hole_r()) < 1e-3]
        fx, fy = drafting_ui.sheet_xy(self._az_front)
        aligned = good and abs(drafting_ui.sheet_xy(top)[0] - fx) < 1e-6 and abs(drafting_ui.sheet_xy(right)[1] - fy) < 1e-6
        self._az_top, self._az_right = top, right
        self.step("Projected View: move the cursor above and to the right of the front view and click; Close",
                  f"front view selected + ribbon '{where} > Projected View', Above and Right, MB2",
                  SAME if aligned and holes else FAIL,
                  f"{rows}; the right view shows the hole as a circle (Ø{2 * self._az_hole_r():g} mm): {bool(holes)}; "
                  "each lined up with the front view at its scale")
        self.wait = 600

    def _az_hole_r(self):
        from .tutorial_mst4 import AT_HOLE
        return AT_HOLE[1] / 2 * IN

    def az_borders(self):
        self.dz_borders_off(self._az_page, "Drafting Preferences > View: Display Borders off, OK")
        self.wait = 300
    def az_dimensions(self):
        """The book's figure (p. 112): 240 and 34.8 on the top view, the tooth space's 6.000, 3.396 and 5.034 on the
        front view, 20 and 25 on the right view. Each value is compared with the Part API's tooth space and bar."""
        from .tutorial_mst4 import AT_BAR, at_slot
        slot = at_slot()
        sb = slot.optimalBoundingBox(False, False)
        floor = next(f for f in slot.Faces if f.Surface.__class__.__name__ == "Plane"
                     and abs(f.normalAt(0, 0).z + 1) < 1e-9)
        fb = floor.BoundBox
        L, W, H = (c * IN for c in AT_BAR)
        x0, x1, z1 = sb.XMin, sb.XMax, sb.ZMax
        f0, f1, z0 = fb.XMin, fb.XMax, fb.ZMin
        page = self._az_page
        plan = [  # view, ribbon, point 1, point 2, offset from the view's centre on the sheet, the book's value (in)
            ("top", "Horizontal", (0, W, H), (L, W, H), (0, 26), 240.0, L),
            ("top", "Horizontal", (0, W, H), (x0, W, H), (-100, 18), 34.8, x0),
            ("front", "Horizontal", (x0, 0, z1), (x1, 0, z1), (-110, 20), 6.0, x1 - x0),
            ("front", "Horizontal", (f0, 0, z0), (f1, 0, z0), (-110, -20), 3.396, f1 - f0),
            ("front", "Vertical", (x1, 0, z1), (f1, 0, z0), (-95, 0), 5.034, z1 - z0),
            ("right", "Vertical", (L, 0, 0), (L, 0, H), (-22, 0), 20.0, H),
            ("right", "Horizontal", (L, 0, H), (L, W, H), (0, 22), 25.0, W),
        ]
        views = {"top": self._az_top, "front": self._az_front, "right": self._az_right}
        got, bad = [], []
        for name, kind, p1, p2, off, book, want in plan:
            d, how = self.dz_dimension(page, views[name], kind, p1, p2, off)
            val = float(d.getRawValue()) if d is not None else None
            row = (name, kind, book, round(val, 4) if val is not None else None, round(want, 4))
            got.append(row)
            if val is None or abs(val - want) > 1e-3 or abs(val - book * IN) > 0.01:
                bad.append((row, how))
        self._az_dims = got
        self.step("Dimensions: 240 and 34.8 on the top view; 6.000, 3.396 and 5.034 on the front view; 20 and 25 on "
                  "the right view; each dragged clear of its view",
                  "two vertices picked + ribbon 'Horizontal' or 'Vertical' (the inferred direction of NX's Rapid)",
                  DIFFERS if not bad else FAIL,
                  f"(view, ribbon, book in, drawing mm, model mm): {got}" + (f"; wrong: {bad}" if bad else "") +
                  ". All are the book's numbers x 25.4. NX infers horizontal or vertical from the pointer; here "
                  "the button says which. Where the view has no vertex at a point (a slot's foot), a cosmetic vertex "
                  "is put on the edge there first, as in tutorials H and N. The book's text puts the 240 on the front "
                  "view, its figures on the top view: the figures are followed")
        self.wait = 600

    def az_section(self):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self._az_front.Name)
        b, self._az_sec_where = self.click_ribbon("Section View")
        self._az_sec_before = {v.Name for v in self._az_page.Views}
        self.wait = 1500

    def az_section_dialog(self):
        self.wait_dialog("az_section_dialog")
        dock = self.tasks_dock()
        pressed = None
        for btn in dock.findChildren(QtWidgets.QAbstractButton):
            if btn.objectName().lower() == "pbup" and btn.isVisible():
                btn.click()
                pressed = btn.objectName()
                break
        self.info["AZ section dialog widgets"] = self.task_widgets()
        QtWidgets.QApplication.processEvents()
        self.mb2_click_on_sheet()
        self._az_sec_pressed = pressed
        self.wait = 2000

    def az_section_check(self):
        if Gui.Control.activeDialog():
            from .navigation import accept_task_dialog
            self.retries.append("AZ: MB2 on the sheet did not close the Section View dialog; OK pressed")
            accept_task_dialog()
        App.ActiveDocument.recompute()
        secs = [v for v in self._az_page.Views if v.TypeId == "TechDraw::DrawViewSection"
                and v.Name not in self._az_sec_before]
        sec = secs[-1] if secs else None
        if sec is not None:
            self.dz_edges(sec, "az section")
        # the cut must pass through the hole's axis (z = 10 in): the hole's walls are then a diameter apart
        r = self._az_hole_r()
        walls = []
        if sec is not None:
            for e in self.dz_lines(sec):
                if hasattr(e.Curve, "Radius") or len(e.Vertexes) < 2:
                    continue
                a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
                if abs(a.y - b.y) < 1e-6 and abs(abs(a.x - b.x) - 20 * IN) < 1e-3:       # 20 in deep, along XC
                    walls.append(round(a.y, 4))
        gap = round(max(walls) - min(walls), 4) if len(walls) >= 2 else None
        n = tuple(round(c, 6) for c in sec.SectionNormal) if sec is not None else None
        o = tuple(round(c, 4) for c in sec.SectionOrigin) if sec is not None else None
        span = self.dz_span(sec) if sec is not None else None
        good = sec is not None and n is not None and abs(abs(n[2]) - 1) < 1e-9 and abs(o[2] - 10 * IN) < 1e-3 \
            and gap is not None and abs(gap - 2 * r) < 1e-3 and self.dz_close(span, (240 * IN, 25 * IN))
        if sec is not None:
            # NX: the section is dragged below the base view and placed with MB1; FreeCAD drops it on its base view
            fx, fy = drafting_ui.sheet_xy(self._az_front)
            sec.X, sec.Y = fx, fy - 48.0
            App.ActiveDocument.recompute()
        self.step("Section View: a click under the front view's middle (arrows up), drag the section below it, MB1",
                  f"front view selected + ribbon '{self._az_sec_where} > Section View', direction "
                  f"'{self._az_sec_pressed}', MB2 = OK; the section moved below the front view",
                  DIFFERS if good else FAIL,
                  f"cut plane normal {n} through {o} (the hole's axis is at z = {10 * IN:g}); the hole's walls in the "
                  f"section are {gap} apart (Ø{2 * r:g}: the cut is through its axis); section spans {span}. TechDraw "
                  "cuts through the middle of the view as the book's click does, and puts the new view on top of its "
                  "base view: it is moved afterwards")
        self._az_sec = sec
        self.wait = 400

    def az_save(self):
        self.dz_fit_sheet()
        self.shot("AZ_drawing.png")
        outcome, how, detail, path = self.save_ctrl_s("Arborpress_rack.FCStd")
        self.step("Save and close the model (the drawing is saved in the part)", how, outcome, detail)
        self.wait = 300

    def az_show(self):
        self.info["AZ dimensions"] = self._az_dims
        self.wait = 300


# ================================================================== BA: PMI on the impeller (5.5)
# The book (pp. 114-117): Impeller_impeller opened; File > PMI; Rapid on the impeller's two end faces (or Linear);
# Radial on the holes and curved surfaces (its figure: Ø15, Ø8, Ø4, Ø0.275, and 16.25 and 16 along the axis); a
# Centerline on the inner surface (the bore); a Note ("Five impeller blades"); then Drafting, a sheet whose views
# inherit the PMI (View Creation Wizard: Inherit PMI, Aligned to Drawing (Entire Part)). The book does not say which
# model view each PMI is made in: here the sizes along the axis, the centerline and the note lie in Front, the
# diameters in Right (the view down the axis), so each drawing view gets the PMI it shows.
BA_SCALE = 1 / 10


class MstImpellerPMITutorials(DraftingSteps):
    """Mixin for tutorial.Replay: tutorial BA (PMI on tutorial AU's impeller)."""

    def BA_STEPS(self):
        return [self.p_modeling, self.ba_open, self.ba_pmi_tab, self.ba_rapid, self.ba_linear, self.ba_right,
                self.ba_radials, self.ba_front, self.ba_centerline, self.ba_note, self.ba_trimetric, self.ba_shot,
                self.ba_drafting, self.ba_sheet, self.ba_views, self.ba_inherit, self.ba_done]

    # ------------------------------------------------------------- the impeller's faces, from its geometry
    def ba_face(self, test):
        return self.p_face(self._ba_body, test)

    def ba_edge(self, test):
        for i, e in enumerate(self._ba_body.Shape.Edges, start=1):
            try:
                if test(e):
                    return f"Edge{i}"
            except Exception:
                continue
        return None

    @staticmethod
    def ba_plane_x(x):
        def test(f):
            return f.Surface.__class__.__name__ == "Plane" and abs(abs(f.normalAt(0, 0).x) - 1) < 1e-9 and \
                abs(f.CenterOfMass.x - x) < 1e-6
        return test

    @staticmethod
    def ba_circle(x, r):
        def test(e):
            return hasattr(e.Curve, "Radius") and e.Curve.__class__.__name__ == "Circle" and \
                abs(e.Curve.Radius - r) < 1e-6 and abs(e.Curve.Center.x - x) < 1e-6
        return test

    def ba_pmi(self, label, subs, ribbon, fill, check, how, outcome=DIFFERS):
        """Select, PMI tab button, fill, MB2 = OK; check the new PMI against the model."""
        from . import pmi_ui
        doc = App.ActiveDocument
        before = {o.Name for o in pmi_ui.all_pmi(doc)}
        Gui.Selection.clearSelection()
        for s in subs:
            Gui.Selection.addSelection(doc.Name, self._ba_body.Name, s or "")
        QtWidgets.QApplication.processEvents()
        b, where = self.click_ribbon(ribbon, tab="PMI")
        QtWidgets.QApplication.processEvents()
        filled = fill() if fill is not None else True
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        doc.recompute()
        new = [o for o in pmi_ui.all_pmi(doc) if o.Name not in before]
        o = new[-1] if new else None
        ok, detail = check(o) if o is not None else (False, "no PMI made")
        good = bool(filled) and ok and not Gui.Control.activeDialog()
        self.step(label, f"{', '.join(s for s in subs if s)} selected + ribbon '{where} > {ribbon}'; {how}; MB2 = OK",
                  outcome if good else FAIL, detail)
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        return o

    # ------------------------------------------------------------- steps
    def ba_open(self):
        from . import geomcheck
        self.tutorial = "BA: PMI on the impeller (NX 12 for Engineering Design, 5.5; book in inches, typed in mm)"

        def oracle(doc):
            sk = next((o for o in doc.Objects if o.TypeId == "Sketcher::SketchObject"), None)
            body = next((o for o in doc.Objects if o.isDerivedFrom("PartDesign::Body")), None)
            if sk is None or body is None:
                return False, "no blade sketch or body: tutorial AU saves the impeller"
            self._ba_ref = self.au_stages(sk)["final"]
            ok, d = geomcheck.compare(body.Shape, self._ba_ref)
            return ok, f"tutorial AU's impeller: {d}"
        self._ba_doc = self.dz_open("Impeller_impeller.FCStd", "Open Impeller_impeller (tutorial AU's part)", oracle)
        self._ba_body = next(o for o in self._ba_doc.Objects if o.isDerivedFrom("PartDesign::Body"))
        self.key("Ctrl+F")
        self.wait = 1200

    def ba_pmi_tab(self):
        r = self.shell.ribbon
        r.select("PMI")
        QtWidgets.QApplication.processEvents()
        here = r.tabs.tabText(r.tabs.currentIndex())
        self.step("File > PMI (check mark on): the PMI tab", "the Modeling ribbon's PMI tab",
                  DIFFERS if here == "PMI" else FAIL,
                  f"tab '{here}'. NX 12 turns the PMI application on from File; NX-Style's PMI tab is always there")
        self.wait = 300

    def ba_ends(self):
        from .tutorial_mst4 import AU_CONE
        (p, d1, d2, h) = AU_CONE
        return p[0] * IN, (p[0] - h) * IN

    def ba_rapid(self):
        big, small = self.ba_ends()
        a, b = self.ba_face(self.ba_plane_x(big)), self.ba_face(self.ba_plane_x(small))
        # the oracle: the end faces' planes, from the Part API's impeller
        fa = next(f for f in self._ba_ref.Faces if self.ba_plane_x(big)(f))
        fb = next(f for f in self._ba_ref.Faces if self.ba_plane_x(small)(f))
        want = abs(fa.CenterOfMass.x - fb.CenterOfMass.x)

        def check(o):
            return (o.DimensionType == "Distance" and abs(o.Nominal - want) < 1e-6,
                    f"{o.Callout}: {o.Nominal / IN:.4f} in, the end faces {want / IN:.4f} in apart (the book's 16.25)")
        self._ba_len = self.ba_pmi("Rapid: the impeller's two end surfaces, the linear dimension 16.25", [a, b],
                                   "Rapid Dimension", None, check, "nothing typed", outcome=SAME)
        self.wait = 300

    def ba_linear(self):
        from .tutorial_mst4 import AU_BORE
        big, _ = self.ba_ends()
        (p, d, h) = AU_BORE
        bottom = (p[0] - h) * IN
        a = self.ba_face(self.ba_plane_x(big))
        # the bore's floor: the plane at its far end (an annulus round the pin hole)
        b = self.ba_face(self.ba_plane_x(bottom))
        want = h * IN

        def check(o):
            return (o.DimensionType == "Distance" and abs(o.Nominal - want) < 1e-6,
                    f"{o.Callout}: {o.Nominal / IN:.4f} in from the large end to the bore's floor (the book's 16)")
        self._ba_depth = self.ba_pmi("Linear: the bore's depth 16", [a, b], "Linear", None, check, "nothing typed",
                                     outcome=SAME)
        self.wait = 300

    def ba_right(self):
        ok = self.y_activate("Right")
        self.step("The diameters are read down the axis: Right as the work view", "double-click 'Right' under Model "
                  "Views in the Part Navigator", DIFFERS if ok else FAIL,
                  "the book does not say; a PMI goes into the work view, and a drawing view looking down the axis "
                  "inherits those (Aligned to Drawing)")
        self.wait = 400

    def ba_radials(self):
        from .tutorial_mst4 import AU_BORE, AU_CONE, AU_PIN
        big, small = self.ba_ends()
        (_, d1, d2, _) = AU_CONE
        plan = [("Ø15, the large end", self.ba_edge(self.ba_circle(big, d1 / 2 * IN)), 2 * d1 / 2 * IN, 15),
                ("Ø8, the small end", self.ba_edge(self.ba_circle(small, d2 / 2 * IN)), d2 * IN, 8),
                ("Ø4, the bore", self.ba_face(self.p_cylinder(AU_BORE[1] / 2 * IN)), AU_BORE[1] * IN, 4),
                ("Ø0.275, the pin hole", self.ba_face(self.p_cylinder(AU_PIN[1] / 2 * IN)), AU_PIN[1] * IN, 0.275)]
        made, rows = [], []
        for what, sub, want, book in plan:
            def check(o, want=want):
                return (o.DimensionType == "Diameter" and abs(o.Nominal - want) < 1e-6, o.Callout)
            o = self.ba_pmi(f"Radial: {what}", [sub], "Radial", None, check, "Method Diameter")
            made.append(o)
            rows.append((what, sub, round(o.Nominal / IN, 4) if o else None, book))
        self._ba_dias = made
        self.info["BA radials"] = rows
        self.wait = 300

    def ba_front(self):
        ok = self.y_activate("Front")
        self.step("The centerline and the note in Front", "double-click 'Front' under Model Views",
                  DIFFERS if ok else FAIL, "the view the sizes along the axis are in")
        self.wait = 400

    def ba_centerline(self):
        from .tutorial_mst4 import AU_BORE
        from . import pmi_ui
        (p, d, h) = AU_BORE
        r = d / 2 * IN
        bore = self.ba_face(self.p_cylinder(r))
        lo, hi = (p[0] - h) * IN, p[0] * IN
        over = (hi - lo) * pmi_ui.CENTERLINE_OVERRUN

        def check(o):
            a, b = App.Vector(o.Anchor), App.Vector(o.Anchor2)
            ok = o.Valid and abs(a.y) < 1e-6 and abs(a.z) < 1e-6 and abs(b.y) < 1e-6 and abs(b.z) < 1e-6 and \
                abs(min(a.x, b.x) - (lo - over)) < 1e-6 and abs(max(a.x, b.x) - (hi + over)) < 1e-6
            return ok, (f"from x = {min(a.x, b.x) / IN:.4f} to {max(a.x, b.x) / IN:.4f} in on the XC axis: the bore "
                        f"({lo / IN:g} to {hi / IN:g} in) and {pmi_ui.CENTERLINE_OVERRUN:.0%} past each end")
        self._ba_axis = self.ba_pmi("Supplemental Geometry > Centerline: the inner surface of the impeller", [bore],
                                    "Centerline", None, check, "the bore's face", outcome=SAME)
        self.wait = 300

    def ba_note(self):
        import Part
        from .tutorial import qtest
        # a blade: the face of the body furthest from the axis
        faces = list(enumerate(self._ba_body.Shape.Faces, start=1))
        i, blade = max(faces, key=lambda t: math.hypot(t[1].CenterOfMass.y, t[1].CenterOfMass.z))
        text = "Five impeller blades"

        def fill():
            ed = self.p_widget(QtWidgets.QPlainTextEdit, "noteText")
            if ed is None:
                return False
            ed.setFocus()
            qtest().keyClicks(ed, text)
            return True

        def check(o):
            d = blade.distToShape(Part.Vertex(App.Vector(o.Anchor)))[0]
            return (list(o.Text) == [text] and d < 1e-6 and o.LabelOffset.Length > 0,
                    f"'{o.Callout}', its leader on Face{i} (a blade; {d:.1e} mm from it)")
        self._ba_note = self.ba_pmi("Note: 'Five impeller blades', its leader on a blade", [f"Face{i}"], "Note", fill,
                                    check, "the text typed", outcome=SAME)
        self.wait = 300

    def ba_trimetric(self):
        from . import pmi_ui
        pmi_ui.show_all(App.ActiveDocument)
        self.fit()

    def ba_shot(self):
        self.shot("BA_pmi.png")
        outcome, how, detail, path = self.save_ctrl_s("Impeller_impeller.FCStd")
        self.step("The trimetric view with the PMI; save the file", f"Show All PMI, Trimetric; {how}", outcome, detail)
        self.wait = 300

    def ba_drafting(self):
        self.key("Ctrl+Shift+D")
        self.wait = 2500

    def ba_sheet(self):
        self._ba_page = self.dz_sheet("ANSIB_Landscape.svg", BA_SCALE, "Drawing sheet: as in 5.2 (B 11 x 17), here "
                                      "at 1:10", (17, 11))
        self.wait = 1200

    def ba_views(self):
        from . import pmi_ui
        front, where = self.dz_base(self._ba_page, [self._ba_body], *FRONT, 120.0, 150.0)
        if front is not None:
            front.HardHidden = True                 # the bore's floor is inside: its 16 is read off dashed lines
            App.ActiveDocument.recompute()
        ok = front is not None and self.dz_edges(front, "ba front", 120000)
        if ok:            # the bore's floor is a hidden line: Inherit PMI needs it computed
            self.dz_hidden_ready(front, "ba front")
        made, where2, closed = self.dz_projected(front, ("Right",)) if ok else ({}, "", False)
        right = made.get("Right")
        if right is not None:
            right.HardHidden = True                 # the book's view down the axis shows its hidden circles dashed
            App.ActiveDocument.recompute()
            self.dz_edges(right, "ba right", 120000)
            self.dz_hidden_ready(right, "ba right")
        iso, _ = self.dz_base(self._ba_page, [self._ba_body], *ISO, 330.0, 200.0)     # clear of the title block
        if iso is not None:
            self.dz_edges(iso, "ba iso", 120000)
        modes = []
        for v in (front, right):
            if v is not None:
                pmi_ui.inherit_mode(v)
                v.NX_InheritPMI = "Aligned to Drawing (Entire Part)"
                modes.append(v.NX_InheritPMI)
        self._ba_front, self._ba_right, self._ba_iso = front, right, iso
        good = ok and closed and right is not None and tuple(right.Direction) == (1, 0, 0) and iso is not None
        self.step("Drawing views (View Creation Wizard): Front, Right and Isometric; Inherit PMI, Aligned to Drawing "
                  "(Entire Part), Inherit PMI onto Drawing", f"body selected + ribbon '{where} > Base View' (Front, "
                  f"then Isometric), '{where2} > Projected View' Right; the views' NX_InheritPMI",
                  DIFFERS if good else FAIL,
                  f"Right looks down the axis {tuple(right.Direction) if right else None}, with hidden lines; inherit "
                  f"modes {modes}. NX's wizard asks for the PMI option; here it is each view's NX_InheritPMI property "
                  "(NX: Settings > Common > PMI)")
        self.wait = 800

    def ba_inherit(self):
        from . import pmi_ui
        page = self._ba_page
        got = {}
        for v in (self._ba_front, self._ba_right):
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(App.ActiveDocument.Name, v.Name)
            QtWidgets.QApplication.processEvents()
            before = {x.Name for x in page.Views}
            b, where = self.click_ribbon("Inherit PMI")
            QtWidgets.QApplication.processEvents()
            App.ActiveDocument.recompute()
            new = [x for x in page.Views if x.Name not in before]
            got[v.Label] = {"made": new, "skipped": list(pmi_ui.last_inherit.get(v.Name, [])),
                            "how": pmi_ui.last_inherit_how.get(v.Name)}
        front, right = got.get(self._ba_front.Label, {}), got.get(self._ba_right.Label, {})

        def values(made):
            out = []
            for d in made:
                if d.isDerivedFrom("TechDraw::DrawViewDimension"):
                    try:
                        out.append(round(float(d.getRawValue()) / IN, 4))
                    except Exception:
                        out.append(None)
            return sorted(x for x in out if x is not None)
        for hidden in (False, True):            # for the record: the front view's lines across the axis
            xs = sorted({round((e.Vertexes[0].Point.x), 3) for _, e in pmi_ui._view_edges(self._ba_front, hidden)
                         if not hasattr(e.Curve, "Radius") and len(e.Vertexes) >= 2
                         and abs(e.Vertexes[0].Point.x - e.Vertexes[-1].Point.x) < 1e-6})
            self.progress(f"ba_inherit: front {'hidden' if hidden else 'visible'} vertical lines at x {xs}; "
                          f"HardHidden {self._ba_front.HardHidden}, {len(self._ba_front.getHiddenEdges())} hidden edges")
        fv, rv = values(front.get("made", [])), values(right.get("made", []))
        want_f = sorted(round(o.Nominal / IN, 4) for o in (self._ba_len, self._ba_depth) if o is not None)
        want_r = sorted(round(o.Nominal / IN, 4) for o in self._ba_dias if o is not None)
        note = [list(x.Text) for x in front.get("made", []) if getattr(x, "NX_Pmi", "") == getattr(self._ba_note, "Name", "")]
        line = next((x for x in front.get("made", []) if getattr(x, "NX_Pmi", "") == getattr(self._ba_axis, "Name", "")), None)
        # the centerline lies on the axis as the front view shows it: the line through the view's centre height
        axis_y = None
        if line is not None:
            cx, cy = pmi_ui.view_centre(self._ba_front)
            axis_y = round(drafting_ui.sheet_xy(self._ba_front)[1] + (0.0 - cy) * drafting_ui.scale_of(self._ba_front), 4)
        good = fv == want_f and rv == want_r and note == [["Five impeller blades"]] and line is not None and \
            abs(float(line.Y) - axis_y) < 1e-3 and abs(float(line.Rotation)) < 1e-6
        self.step("Inherit PMI onto Drawing: the PMI and the note on the views", "each view selected + ribbon "
                  "'Inherit PMI'", DIFFERS if good else FAIL,
                  f"front view: lengths {fv} in (the PMI {want_f}), the note {note}, the centerline at y = "
                  f"{float(line.Y) if line else None} (the axis: {axis_y}); right view: diameters {rv} in (the PMI "
                  f"{want_r}). Skipped: front {front.get('skipped')}, right {right.get('skipped')}. NX inherits in "
                  "the wizard; here the Inherit PMI button does it per view")
        self.wait = 600

    def ba_done(self):
        self.dz_fit_sheet()
        self.shot("BA_drawing.png")
        App.ActiveDocument.save()
        self.key("Ctrl+M")
        self.wait = 1500


# ================================================================== BB: the hex bolt's drawing (5.6)
# The book (pp. 117-121): Impeller_hexa-bolt opened; Drafting; sheet E 34 x 44 at 8:1; Base View Front; Projected
# Views Right and Top; Display Borders off; the views' hidden lines dashed (Settings > Hidden Lines); vertical linear
# dimensions 1.703, 0.065 and 0.188 on the front view and 0.016 on the right; a Note with a leader to the threaded
# shaft (the thread's callout), its lettering and stub enlarged; a Radial dimension on the circle of the top view;
# a Base View Isometric.
BB_SCALE = 8.0


class MstBoltDrawingTutorials(DraftingSteps):
    """Mixin for tutorial.Replay: tutorial BB (it draws tutorial AQ's screw)."""

    def BB_STEPS(self):
        return [self.p_modeling, self.bb_open, self.bb_drafting, self.bb_sheet, self.bb_base, self.bb_projected,
                self.bb_borders, self.bb_hidden, self.bb_dimensions, self.bb_note, self.bb_radial, self.bb_iso,
                self.bb_save]

    def bb_bodies(self):
        return [o for o in self._bb_doc.Objects if o.isDerivedFrom("PartDesign::Body") and o.ViewObject.Visibility
                and not o.Shape.isNull()]

    def bb_open(self):
        from . import geomcheck
        from .tutorial_mst4 import aq_reference
        self.tutorial = "BB: Hex bolt drawing (NX 12 for Engineering Design, 5.6; book in inches, typed in mm)"

        def oracle(doc):
            bodies = [o for o in doc.Objects if o.isDerivedFrom("PartDesign::Body") and o.ViewObject.Visibility
                      and not o.Shape.isNull()]
            shapes = [b.Shape for b in bodies]
            whole = shapes[0].fuse(shapes[1:]).removeSplitter() if shapes else None
            ref = aq_reference()
            # the thread takes material from the shank: compare the box and that the head and step are the book's
            bb, rb = whole.optimalBoundingBox(False, False), ref.optimalBoundingBox(False, False)
            ok = abs(bb.ZLength - rb.ZLength) < 1e-6 and abs(bb.XLength - rb.XLength) < 1e-6 and len(bodies) >= 2
            head = next((b for b in bodies if abs(b.Shape.optimalBoundingBox(False, False).ZMax - rb.ZMax) < 1e-6
                         and b.Shape.optimalBoundingBox(False, False).ZMin > 1e-6), None)
            same_head, d = geomcheck.compare(head.Shape if head else None, self.bb_head_ref())
            return ok and same_head, (f"tutorial AQ's screw ({len(bodies)} bodies): {bb.ZLength / IN:.4f} in long, "
                                      f"{bb.XLength / IN:.4f} across the head (the book's 1.7032 and 0.492); head {d}")
        self._bb_doc = self.dz_open("Impeller_hexa-bolt.FCStd", "Open Impeller_hexa-bolt (tutorial AQ's part)", oracle)
        self.wait = 800

    @staticmethod
    def bb_head_ref():
        import Part
        from .tutorial_mst4 import AQ_HEX, AQ_HEX_H, AQ_SPHERE, AQ_Z_HEAD, hexagon_prism
        return hexagon_prism(AQ_HEX, AQ_Z_HEAD, AQ_HEX_H).common(
            Part.makeSphere(AQ_SPHERE / 2, App.Vector(0, 0, AQ_Z_HEAD)))

    @staticmethod
    def bb_top_r(head):
        """Radius of the head's top face: the flat circle where the sphere meets it (the arcs where the sphere cuts the
        hexagon's sides also reach the top, but slope down)."""
        hb = head.optimalBoundingBox(False, False)
        return max(e.Curve.Radius for e in head.Edges if hasattr(e.Curve, "Radius")
                   and e.BoundBox.ZLength < 1e-6 and abs(e.BoundBox.ZMax - hb.ZMax) < 1e-6)

    def bb_drafting(self):
        self.key("Ctrl+Shift+D")
        self.wait = 2500

    def bb_sheet(self):
        self._bb_page = self.dz_sheet("ANSIE_Landscape.svg", BB_SCALE, "Sheet: E-34 X 44, Scale 8.0 : 1.0, OK",
                                      (44, 34))
        self.wait = 1200

    def bb_base(self):
        v, where = self.dz_base(self._bb_page, self.bb_bodies(), *FRONT, 330.0, 330.0)
        ok = v is not None and self.dz_edges(v, "bb front", 180000)
        span = self.dz_span(v) if ok else None
        self._bb_front = v
        self.step("Base View: Front, a click to place it", f"the screw's bodies selected + ribbon '{where} > Base "
                  "View', MB2 on the sheet; the view's Direction Front", DIFFERS if ok else FAIL,
                  f"edges span {span} mm unscaled (the screw: {1.7032 * IN:.3f} tall); scale {v.Scale if v else '?'}. "
                  "As in tutorial AZ, the direction is the view's property")
        self.wait = 600

    def bb_projected(self):
        made, where, closed = self.dz_projected(self._bb_front, ("Right", "Above"))
        right, top = made.get("Right"), made.get("Above")
        ok = closed and right is not None and top is not None
        for name, v in (("right", right), ("top", top)):
            ok = ok and self.dz_edges(v, f"bb {name}", 180000)
        dirs = {n: tuple(round(c, 6) for c in v.Direction) for n, v in (("right", right), ("top", top)) if v}
        good = ok and dirs == {"right": (1, 0, 0), "top": (0, 0, 1)}
        self._bb_right, self._bb_top = right, top
        self.step("Add the orthographic views Right and Top", f"front view selected + ribbon '{where} > Projected "
                  "View', Right and Above, MB2", SAME if good else FAIL, f"directions {dirs}")
        self.wait = 600

    def bb_borders(self):
        self.dz_borders_off(self._bb_page, "Preferences > Drafting > View: Display Borders off")
        self.wait = 300
    def bb_hidden(self):
        from .tutorial_mst4 import AQ_SHANK
        views = [self._bb_front, self._bb_right, self._bb_top]
        Gui.Selection.clearSelection()
        for v in views:
            Gui.Selection.addSelection(App.ActiveDocument.Name, v.Name)
            v.HardHidden = True
        App.ActiveDocument.recompute()
        self.dz_hidden_ready(self._bb_top, "bb top", tries=12)
        r = AQ_SHANK[0] / 2
        hidden = [round(e.Curve.Radius, 4) for e in self.dz_lines(self._bb_top, hidden=True) if hasattr(e.Curve, "Radius")]
        ok = any(abs(x - r) < 1e-3 for x in hidden)
        for v in views:
            if "HiddenStyle" in v.ViewObject.PropertiesList:
                self.info.setdefault("BB hidden line style", []).append(str(v.ViewObject.HiddenStyle))
        self.step("Select the views, RMB > Settings > Hidden Lines: Process Hidden Lines, Dashed Lines, OK",
                  "the three views selected; their Hard Hidden property on", DIFFERS if ok else FAIL,
                  f"the top view shows the shank under the head as a dashed circle (radius {r:g} mm among its hidden "
                  f"circles {sorted(set(hidden))[:8]}). NX's view Settings dialog; TechDraw's Hard Hidden draws them "
                  "dashed")
        self.wait = 600

    def bb_dimensions(self):
        """Vertical dimensions as in the book's figure (p. 119): 1.703 (the whole screw), 0.188 (the head) and 0.065
        (the head's top to where the sphere meets the hexagon's corners) on the front view; 0.016 (the step) on the
        right view. Each is compared with the model's own geometry."""
        from .tutorial_mst4 import AQ_HEX, AQ_STEP, AQ_SHANK
        head = self.bb_head_ref()
        hb = head.optimalBoundingBox(False, False)
        top_r = self.bb_top_r(head)
        corner_z = max(v.Point.z for v in head.Vertexes if abs(math.hypot(v.Point.x, v.Point.y) - AQ_HEX) < 1e-6)
        z_top, z_head = hb.ZMax, hb.ZMin
        r_step = AQ_STEP[0] / 2
        z0, z1 = AQ_SHANK[1], AQ_SHANK[1] + AQ_STEP[1]
        page = self._bb_page
        plan = [  # view, ribbon, point 1, point 2, offset, the book's value (in), the model's (mm)
            ("front", "Vertical", (top_r, 0, z_top), (0, 0, 0), (-50, 0), 1.703, z_top),
            ("front", "Vertical", (top_r, 0, z_top), (AQ_HEX, 0, corner_z), (55, 175), 0.065, z_top - corner_z),
            ("front", "Vertical", (top_r, 0, z_top), (AQ_HEX, 0, z_head), (75, 175), 0.188, z_top - z_head),
            ("right", "Vertical", (0, r_step, z0), (0, r_step, z1), (-40, 150), 0.016, z1 - z0),
        ]
        views = {"front": self._bb_front, "right": self._bb_right}
        got, bad = [], []
        for name, kind, p1, p2, off, book, want in plan:
            d, how = self.dz_dimension(page, views[name], kind, p1, p2, off)
            val = float(d.getRawValue()) if d is not None else None
            if d is not None:
                d.FormatSpec = "%.3f"
            row = (name, book, round(val / IN, 4) if val is not None else None, round(want / IN, 4))
            got.append(row)
            if val is None or abs(val - want) > 1e-3 or abs(val / IN - book) > 0.0015:
                bad.append((row, how))
        self.step("Insert > Dimensions > Linear: vertical dimensions 1.703, 0.188 and 0.065 on the front view, "
                  "0.016 on the right view", "two vertices picked + ribbon 'Vertical'", DIFFERS if not bad else FAIL,
                  f"(view, book in, drawing in, model in): {got}" + (f"; wrong: {bad}" if bad else "") +
                  ". The 0.065 runs to where the head's sphere meets the hexagon's corners. Points with no vertex of "
                  "their own (the screw's end, cut by the thread) get a cosmetic vertex on the edge there")
        self.wait = 600

    def bb_note(self):
        from .tutorial_mst4 import AQ_SHANK
        v = self._bb_front
        s = drafting_ui.scale_of(v)
        vx, vy = drafting_ui.sheet_xy(v)
        # the thread's flank nearest the middle of the shank's left side: the book's figure has the note left of the
        # front view, clear of the right view
        from . import pmi_ui
        target = pmi_ui.view_xy(v, App.Vector(-AQ_SHANK[0] / 2, 0, AQ_SHANK[1] / 2))
        best = None
        for i, e in self.view_edges(v):
            m = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
            dd = math.hypot(m.x - target.x, m.y - target.y)
            if best is None or dd < best[0]:
                best = (dd, i)
        self.select_view_subs(v, [f"Edge{best[1]}"] if best else [])
        b, where = self.click_ribbon("Note")
        QtWidgets.QApplication.processEvents()
        typed = self.bb_type_note()
        self.mb2_click_on_sheet()
        QtWidgets.QApplication.processEvents()
        rec = drafting_ui.NOTES[-1] if drafting_ui.NOTES else {}
        note = App.ActiveDocument.getObject(rec.get("note", "")) if rec else None
        tip = rec.get("tip")
        # independent: back from the sheet into the model, the arrow's tip must be on the threaded shank
        on = None
        if tip is not None:
            cx, cy = pmi_ui.view_centre(v)
            x_model = (tip[0] - vx) / s + cx
            z_model = (tip[1] - vy) / s + cy
            on = (round(x_model, 4), round(z_model, 4))
        good = typed and note is not None and list(note.Text) == self.BB_NOTE and on is not None and \
            AQ_SHANK[0] / 2 * 0.7 < abs(on[0]) < AQ_SHANK[0] / 2 * 1.001 and 0 < on[1] < AQ_SHANK[1] and \
            abs(float(note.TextSize) - 7.0) < 1e-9
        self.step("Note: 'Right Hand Ø0.20 x 1.5', 'Pitch 0.05, Angle 60°' (Ø and ° from the Symbols tab), a leader "
                  "from the threaded shaft; Settings: Lettering Height and the leader's length increased",
                  f"a thread edge of the front view selected + ribbon '{where} > Note', the text typed with the Ø and "
                  "° buttons, Lettering height 7 and Stub length 12.7 mm, MB2", DIFFERS if good else FAIL,
                  f"note {list(note.Text) if note else None}, height {note.TextSize if note else '?'}; the arrow ends "
                  f"at model (x, z) {on} mm: on the shank's thread (radius {AQ_SHANK[0] / 2:g}). NX drags the leader "
                  "from the shaft and sets height and length in Settings afterwards; here they are fields of the "
                  "dialog")
        self.wait = 600

    BB_NOTE = ["Right Hand Ø0.20 x 1.5", "Pitch 0.05, Angle 60°"]

    def bb_type_note(self):
        from .smoke import decode
        from .tutorial import qtest
        dock = self.tasks_dock()
        ed = dock.findChild(QtWidgets.QPlainTextEdit, "noteText")
        dia = dock.findChild(QtWidgets.QPushButton, "symbol_diameter")
        deg = dock.findChild(QtWidgets.QPushButton, "symbol_degree")
        if ed is None or dia is None or deg is None:
            return False
        ed.setFocus()
        qtest().keyClicks(ed, "Right Hand ")
        dia.click()
        qtest().keyClicks(ed, "0.20 x 1.5")
        qtest().keyClick(ed, *decode("Return"))
        qtest().keyClicks(ed, "Pitch 0.05, Angle 60")
        deg.click()
        for name, value in (("letteringHeight", 7.0), ("stubLength", 12.7)):
            w = dock.findChild(QtWidgets.QDoubleSpinBox, name)
            if w is None:
                return False
            self.type_into(w, value)
        return True

    def bb_radial(self):
        v = self._bb_top
        head = self.bb_head_ref()
        top_r = self.bb_top_r(head)
        circles = [(i, e) for i, e in self.view_edges(v) if hasattr(e.Curve, "Radius")
                   and abs(e.Curve.Radius - top_r) < 1e-3]
        page = self._bb_page
        before = {d.Name for d in page.Views if d.isDerivedFrom("TechDraw::DrawViewDimension")}
        self.select_view_subs(v, [f"Edge{circles[0][0]}"] if circles else [])
        b, where = self.click_ribbon("Radial")
        QtWidgets.QApplication.processEvents()
        if Gui.Control.activeDialog():
            self.mb2_click_on_sheet()
        App.ActiveDocument.recompute()
        new = [d for d in page.Views if d.isDerivedFrom("TechDraw::DrawViewDimension") and d.Name not in before]
        d = new[-1] if new else None
        if d is not None:
            d.X, d.Y = 30.0, -25.0
            d.FormatSpec = "%.3f"
        val = float(d.getRawValue()) if d is not None else None
        good = val is not None and abs(val - top_r) < 1e-3
        self.step("Radial: click the circle of the bolt in the top view", f"the head's top circle selected + ribbon "
                  f"'{where} > Radial'", DIFFERS if good else FAIL,
                  f"R{val / IN if val else 0:.3f} in ({val} mm), the circle where the head's sphere meets its top face "
                  f"(radius {top_r / IN:.4f} in from the model). The book's figure labels this circle Ø0.200, the "
                  "size of its radius; TechDraw's Radial gives R")
        self.wait = 600

    def bb_iso(self):
        v, where = self.dz_base(self._bb_page, self.bb_bodies(), *ISO, 820.0, 400.0)
        if v is not None:
            self.dz_place(v, 820.0, 400.0, scale=BB_SCALE / 2)
        ok = v is not None and self.dz_edges(v, "bb iso", 180000)
        d = tuple(round(c, 6) for c in v.Direction) if v else None
        self.step("Base View: Isometric, placed beside the others", f"the screw's bodies selected + ribbon '{where} > "
                  "Base View', MB2; Direction isometric", SAME if ok and d == tuple(round(c, 6) for c in ISO[0])
                  else FAIL, f"direction {d}, {len(v.getVisibleEdges()) if ok else 0} edges, scale {drafting_ui.scale_of(v) if v else '?'}"
                  " (half the sheet's, to fit beside the views)")
        self.wait = 600

    def bb_save(self):
        self.dz_fit_sheet()
        self.shot("BB_drawing.png")
        outcome, how, detail, path = self.save_ctrl_s("Impeller_hexa-bolt.FCStd")
        self.step("Save", how, outcome, detail)
        self.wait = 300
