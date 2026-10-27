# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tutorials from chapter 4 (three-dimensional modeling) of Leu, Tao, Ghazanfari and Kolan, NX 12 for Engineering
Design (Missouri University of Science and Technology). The book works in inches; the parts are metric and the book's
sizes are typed in millimetres.

  AN  4.2.1, 4.3, 4.5.1 Arbor Press Plate: Block 65 x 85 x 20 at the origin (NX's Block dialog, Origin and Edge
      Lengths), Fit and Trimetric, a Datum Plane 15 above the top face, a Datum Axis through two corners, six simple
      holes Ø8 drilled 25 deep from points typed on the top face (Hole, Simple, Tip Angle 118°).
"""

import math

import FreeCAD as App
import FreeCADGui as Gui

from .qt import Qt, QtWidgets

IN = 25.4
SAME, DIFFERS, MISSING, FAIL = "same", "differs", "missing", "FAILED"

# ================================================================== AN: Arbor Press Plate (4.2.1, 4.3, 4.5.1)
# The book (pp. 55-57, 60-62, 67-69), inches: a Block 65 (XC) x 85 (YC) x 20 (ZC) with its origin at (0, 0, 0); a
# Datum Plane offset 15 from the top face; a Datum Axis through two points of the block (the figure picks a bottom
# corner and the opposite top corner of the front face: here (65, 0, 0) and (0, 0, 20)); six simple holes Ø8, 25 deep,
# tip angle 118°, at the points of the book's table, sketched on the top face. The plate is 20 thick, so the holes
# go through it.
AN_SIZE = (65 * IN, 85 * IN, 20 * IN)
AN_OFFSET = 15 * IN
AN_AXIS = ((65 * IN, 0, 0), (0, 0, 20 * IN))
AN_HOLES = [(11.25, 10.00), (32.50, 23.50), (53.75, 10.00), (11.25, 75.00), (32.50, 61.50), (53.75, 75.00)]
AN_HOLE_D, AN_HOLE_DEPTH, AN_TIP = 8 * IN, 25 * IN, 118.0


def an_reference(holes=True):
    """The plate as the book dimensions it: the block, less the six through holes."""
    import Part
    plate = Part.makeBox(*AN_SIZE)
    if holes:
        for x, y in AN_HOLES:
            plate = plate.cut(Part.makeCylinder(AN_HOLE_D / 2, AN_SIZE[2] + 2, App.Vector(x * IN, y * IN, -1)))
    return plate


class MstPlateTutorials:
    """Mixin for tutorial.Replay: tutorial AN."""

    def AN_STEPS(self):
        return [self.p_modeling, self.an_new, self.an_block, self.an_block_dialog, self.an_view, self.an_save,
                self.an_datum_plane, self.an_datum_plane_ok, self.an_datum_axis, self.an_datum_axis_ok, self.an_hole,
                self.an_hole_points, self.an_hole_finish, self.an_hole_dialog, self.an_check, self.an_fit,
                self.an_show]

    # ------------------------------------------------------------- helpers
    def an_box(self):
        return self.newest("PartDesign::AdditiveBox")

    def an_vertex(self, obj, p):
        """The vertex of obj at p (mm), as a sub-element name."""
        v = App.Vector(*p)
        for i, vx in enumerate(obj.Shape.Vertexes, start=1):
            if (vx.Point - v).Length < 1e-6:
                return f"Vertex{i}"
        return None

    def an_top(self, obj):
        return self.face_of(obj, lambda f: abs(f.normalAt(0, 0).z - 1) < 1e-9
                            and abs(f.CenterOfMass.z - AN_SIZE[2]) < 1e-6)

    def an_type_point(self, sk, xy):
        """With the Point tool running: type XC and YC into FreeCAD's positional on-view fields (NX's input boxes),
        Enter after each; Enter in the second makes the point. Returns (typed, clicked)."""
        from . import sketch_ui
        from .qt import QtCore
        from .smoke import decode
        from .tutorial import qtest
        view = self.nav().widget
        p = self.screen_point(sk, *xy)
        near = p + QtCore.QPoint(45, -40)        # clear of the other points, so FreeCAD adds no snap of its own
        self.send(QtCore.QEvent.MouseMove, near, Qt.NoButton, Qt.NoButton)
        qtest().qWait(200)
        fields = sketch_ui.xy_fields(sk, view, near)
        n0 = len(sk.Geometry)
        for w, v in zip(fields or (), xy):
            w.setFocus()
            w.lineEdit().selectAll()
            qtest().keyClicks(w.lineEdit(), self.typed_number(w, v))
            qtest().keyClick(w.lineEdit(), *decode("Return"))
            qtest().qWait(150)
        clicked = len(sk.Geometry) == n0
        if clicked:                             # no fields typed (or not taken): place it with a click
            self.mb1_click(p)
        return bool(fields), clicked

    # ------------------------------------------------------------- New, Block
    def an_new(self):
        self.tutorial = ("AN: Arbor Press Plate (NX 12 for Engineering Design, 4.2.1, 4.3 and 4.5.1; book in inches, "
                         "typed in mm)")
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def an_block(self):
        new = set(App.listDocuments()) - self._docs_before
        self.step("Create a new file (Arborpress_plate)", "Ctrl+N, Model template",
                  SAME if new and self.body() else FAIL, f"new document {sorted(new)}")
        self.units_step()
        Gui.Selection.clearSelection()
        b, where = self.click_ribbon("Block")
        self._an_where = where
        self.wait = 800

    def an_block_dialog(self):
        from . import primitive_ui
        from .smoke_primitives import choose, field, ok
        p = primitive_ui.current()
        if p is None:
            self.step("Block: Origin and Edge Lengths, origin (0, 0, 0), 65 x 85 x 20, OK",
                      f"ribbon '{self._an_where} > Block'", FAIL, "the Block dialog did not open")
            raise RuntimeError("no Block dialog; tutorial AN cannot continue")
        kind = choose(p, "nxType", "Origin and Edge Lengths")
        for name, v in (("originXC", 0), ("originYC", 0), ("originZC", 0), ("length", AN_SIZE[0]),
                        ("width", AN_SIZE[1]), ("height", AN_SIZE[2])):
            self.type_into(field(p, name), v)
        boolean = field(p, "nxBoolean", QtWidgets.QComboBox).currentText()
        pressed = ok()
        box = self.an_box()
        bb = box.Shape.BoundBox if box is not None else None
        exact = box is not None and abs(box.Shape.Volume - AN_SIZE[0] * AN_SIZE[1] * AN_SIZE[2]) < 1e-3 \
            and max(abs(bb.XMin), abs(bb.YMin), abs(bb.ZMin)) < 1e-9 and abs(bb.ZMax - AN_SIZE[2]) < 1e-9
        undo = App.ActiveDocument.UndoNames[:1]
        self.step("Block: Origin and Edge Lengths, Point Dialog at (0, 0, 0), Length 65, Width 85, Height 20, OK",
                  f"ribbon '{self._an_where} > Block', Type '{kind}', XC/YC/ZC 0 and the lengths typed "
                  "(1651, 2159, 508 mm), OK",
                  SAME if pressed and exact and undo == ["Block"] else FAIL,
                  f"Boolean {boolean}; block {bb.XLength:.1f} x {bb.YLength:.1f} x {bb.ZLength:.1f} mm from "
                  f"({bb.XMin:g}, {bb.YMin:g}, {bb.ZMin:g}); one undo step {undo}. The Point Dialog's XC, YC, ZC are "
                  "fields in the Block dialog (NX opens it as its own window)" if bb is not None else
                  f"OK pressed {pressed}; no block")
        self.wait = 400

    def an_view(self):
        self.key("Ctrl+F")
        self.key("Home")
        self.wait = 1500

    def an_save(self):
        from . import pmi_views
        v = self.view()
        d = v.getViewDirection()
        want = pmi_views.STANDARD["Trimetric"][0]
        along = d.x * want[0] + d.y * want[1] + d.z * want[2]
        w = self.nav().widget
        dpr = w.devicePixelRatioF() if hasattr(w, "devicePixelRatioF") else 1.0
        corners = [v.getPointOnViewport(App.Vector(x, y, z)) for x in (0, AN_SIZE[0]) for y in (0, AN_SIZE[1])
                   for z in (0, AN_SIZE[2])]
        inside = all(0 <= sx / dpr <= w.width() and 0 <= sy / dpr <= w.height() for sx, sy in corners)
        self.step("Fit (Ctrl+F), Orient View > Trimetric", "Ctrl+F, Home (NX's Trimetric key)",
                  SAME if along > 1 - 1e-6 and inside else FAIL,
                  f"view direction {tuple(round(c, 4) for c in d)} (trimetric {along:.6f}); all eight corners of the "
                  f"block in the window {inside}")
        self.shot("AN1_block.png")
        outcome, how, detail, path = self.save_ctrl_s("Arborpress_plate.FCStd")
        self.step("Save the part", how, outcome, detail)
        self.wait = 300

    # ------------------------------------------------------------- Datum Plane, Datum Axis
    def an_datum_plane(self):
        box = self.an_box()
        top = self.an_top(box)
        self.select_sub(box, top)
        self._an_planes = len([o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Plane"])
        where = self.click_dropdown("Datum", "Datum Plane")
        self.step("Datum Plane (Inferred): the top face of the block", f"top face ({top}) selected + ribbon "
                  f"'{where} > Datum > Datum Plane'", SAME if where and Gui.Control.activeDialog() else FAIL,
                  "the plane is attached to the face; FreeCAD's attachment dialog opens with it")
        self.wait = 1200

    def an_datum_plane_ok(self):
        self.wait_dialog("an_datum_plane_ok")
        plane = self.newest("PartDesign::Plane")
        name = self.set_quantity("attachmentoffsetz", AN_OFFSET)
        self.mb2_click()
        App.ActiveDocument.recompute()
        z = plane.Placement.Base.z if plane is not None else None
        n = plane.Placement.Rotation.multVec(App.Vector(0, 0, 1)) if plane is not None else None
        ok = z is not None and abs(z - (AN_SIZE[2] + AN_OFFSET)) < 1e-6 and abs(n.z - 1) < 1e-9 \
            and not Gui.Control.activeDialog()
        self._an_plane = plane
        self.step("Offset Distance 15, OK", f"'{name}' = 381 mm, MB2 = OK", SAME if ok else FAIL,
                  f"datum plane at z = {z:.2f} mm (top face 508 + 381), normal {tuple(round(c, 6) for c in n)}"
                  if z is not None else "no datum plane")
        self.shot("AN2_datum_plane.png")
        self.wait = 500

    def an_datum_axis(self):
        box = self.an_box()
        subs = [self.an_vertex(box, p) for p in AN_AXIS]
        self.select_subs(box, subs)
        where = self.click_dropdown("Datum", "Datum Axis")
        self.step("Datum Axis: the two points on the block", f"{subs[0]} and {subs[1]} selected + ribbon "
                  f"'{where} > Datum > Datum Axis'", SAME if where and Gui.Control.activeDialog() and all(subs)
                  else FAIL, "FreeCAD infers Through Two Points from the two vertices, as NX's Inferred does")
        self.wait = 1200

    def an_datum_axis_ok(self):
        self.wait_dialog("an_datum_axis_ok")
        line = self.newest("PartDesign::Line")
        mode = getattr(line, "MapMode", None)
        self.mb2_click()
        App.ActiveDocument.recompute()
        ok = False
        detail = "no datum axis"
        if line is not None:
            d = line.Placement.Rotation.multVec(App.Vector(0, 0, 1))
            want = (App.Vector(*AN_AXIS[1]) - App.Vector(*AN_AXIS[0])).normalize()
            through = line.Placement.Base
            on = (through - App.Vector(*AN_AXIS[0])).cross(want).Length
            ok = abs(abs(d.dot(want)) - 1) < 1e-9 and on < 1e-6 and not Gui.Control.activeDialog()
            detail = (f"mode {mode}; direction {tuple(round(c, 4) for c in d)} along the diagonal of the front face "
                      f"(65 x 20); through the first point within {on:.1g} mm")
        self.step("OK: the Datum Axis is the diagonal", "MB2 = OK", SAME if ok else FAIL, detail)
        self.shot("AN3_datum_axis.png")
        self.wait = 500

    # ------------------------------------------------------------- Hole
    def an_hole(self):
        box = self.an_box()
        top = self.an_top(box)
        self.select_sub(box, top)
        b, where = self.click_ribbon("Hole")
        self._an_hole_where = where
        self.wait = 1500

    def an_hole_points(self):
        sk = self.edited_sketch()
        self.step("Hole: General Hole, Position > Sketch on the top face", f"top face selected + ribbon "
                  f"'{self._an_hole_where} > Hole'", SAME if sk is not None else FAIL,
                  "the Hole starts a sketch on the face, and Finish Sketch carries on into the Hole dialog, as NX's "
                  "Sketch Section in the Position group" if sk is not None else f"no sketch; modals {self.modals.seen}")
        if sk is None:
            raise RuntimeError("no hole sketch in edit; tutorial AN cannot continue")
        self._an_sk = sk
        self.frame_sketch(sk, AN_SIZE[0] / 2, AN_SIZE[1] / 2, AN_SIZE[1] * 1.3)
        QtWidgets.QApplication.processEvents()
        b, where = self.click_ribbon("Point", tab="Sketch")
        QtWidgets.QApplication.processEvents()
        typed, clicked = [], []
        for x, y in AN_HOLES:
            t, c = self.an_type_point(sk, (x * IN, y * IN))
            typed.append(t)
            clicked.append(c)
        self.mb2_click(self.screen_point(sk, -20 * IN, 95 * IN))
        App.ActiveDocument.recompute()
        pts = [sk.getPoint(g, 1) for g, geo in enumerate(sk.Geometry) if "Point" in geo.TypeId]
        missing = [(x, y) for x, y in AN_HOLES
                   if not any(abs(p.x - x * IN) < 1e-9 and abs(p.y - y * IN) < 1e-9 for p in pts)]
        on_face = abs(sk.Placement.Base.z - AN_SIZE[2]) < 1e-9
        self.info["AN hole points"] = {"typed": typed, "clicked": clicked,
                                       "points in": [(round(p.x / IN, 4), round(p.y / IN, 4)) for p in pts]}
        self.step("Point Dialog: the six points of the table, each OK", f"ribbon '{where} > Point', XC and YC "
                  "typed in the on-view fields for each point, MB2",
                  SAME if len(pts) == 6 and not missing and all(typed) and on_face else
                  DIFFERS if len(pts) == 6 and not missing and on_face else FAIL,
                  f"{len(pts)} points; {'all at the table coordinates' if not missing else f'missing {missing}'}; "
                  f"sketch on the top face (z = {sk.Placement.Base.z:.1f} mm)")
        self.wait = 300

    def an_hole_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def an_hole_dialog(self):
        self.wait_dialog("an_hole_dialog")
        hole = self.newest("PartDesign::Hole")
        opened = bool(Gui.Control.activeDialog()) and hole is not None
        self.info["AN hole dialog widgets"] = self.task_widgets()
        dia = self.set_quantity("Diameter", AN_HOLE_D)
        depth_type = self.set_combo("DepthType", "Dimension")
        depth = self.set_quantity("Depth", AN_HOLE_DEPTH)
        tip = self.set_quantity("DrillPointAngle", AN_TIP)
        self.mb2_click()
        App.ActiveDocument.recompute()
        state = {p: str(getattr(hole, p, None)) for p in ("Diameter", "DepthType", "Depth", "DrillPoint",
                                                          "DrillPointAngle", "Threaded")} if hole is not None else {}
        self.info["AN hole"] = state
        want = AN_SIZE[0] * AN_SIZE[1] * AN_SIZE[2] - 6 * math.pi * (AN_HOLE_D / 2) ** 2 * AN_SIZE[2]
        values = hole is not None and abs(hole.Diameter.Value - AN_HOLE_D) < 1e-9 and \
            abs(hole.Depth.Value - AN_HOLE_DEPTH) < 1e-9 and abs(hole.DrillPointAngle.Value - AN_TIP) < 1e-9
        self.check_volume("Simple Hole: Diameter 8, Depth 25, Tip Angle 118°, Boolean Subtract, OK",
                          f"dialog open {opened}; '{dia}' = 203.2 mm, '{depth_type}', '{depth}' = 635 mm, "
                          f"'{tip}' = 118°, MB2 = OK", want,
                          f"; the plate is 20 thick, so the holes go through it; values as typed {values}; FreeCAD's "
                          "Hole always subtracts from its body")
        self.wait = 500

    def an_check(self):
        from . import geomcheck
        body = self.body()
        ok, detail = geomcheck.compare(body.Shape if body is not None else None, an_reference())
        self.step("The plate: the block with its six holes", "compared with the book's dimensions",
                  SAME if ok else FAIL, detail)
        outcome, how, detail, path = self.save_ctrl_s("Arborpress_plate.FCStd")
        self.step("Save the part", how, outcome, detail)
        self.wait = 300

    def an_fit(self):
        self.fit()

    def an_show(self):
        self.show("AN_arborpress_plate")
