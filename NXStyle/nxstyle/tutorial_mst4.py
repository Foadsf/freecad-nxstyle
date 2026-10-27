# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tutorials from chapter 4 (three-dimensional modeling) of Leu, Tao, Ghazanfari and Kolan, NX 12 for Engineering
Design (Missouri University of Science and Technology). The book works in inches; the parts are metric and the book's
sizes are typed in millimetres.

  AN  4.2.1, 4.3, 4.5.1 Arbor Press Plate: Block 65 x 85 x 20 at the origin (NX's Block dialog, Origin and Edge
      Lengths), Fit and Trimetric, a Datum Plane 15 above the top face, a Datum Axis through two corners, six simple
      holes Ø8 drilled 25 deep from points typed on the top face (Hole, Simple, Tip Angle 118°).
  AO  4.4 Impeller Lower Casing, the solids: tutorial AG's sketch reopened; Revolve of the 10 wall curves picked
      with the Curve Rule on Single Curve, about XC through (0, 0, 0), 0 to 180°; Extrude of the 10 edge curves 0.5
      along -ZC as its own body; the edge mirrored to the other side; Revolve of the 4 flange curves, united.
  AP  4.2.2 Impeller Shaft: Cylinder Ø4 x 18 on ZC at the origin, Isometric, a Cone 4 -> 6 x 10 at the centre of
      the cylinder's top edge (Point type Arc/Ellipse/Sphere Center, a click on the edge), Unite, and a Cylinder
      Ø6 x 20 at the centre of the cone's top edge, Unite.
"""

import math

import FreeCAD as App
import FreeCADGui as Gui

from .qt import Qt, QtCore, QtWidgets

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


# ================================================================== AO: Impeller Lower Casing, the solids (4.4)
# The book (pp. 62-67) reopens the casing sketch of 3.5.2 (tutorial AG) and, with the Curve Rule on Single Curve,
# revolves the wall's 10 curves about XC through (0, 0, 0) from 0 to 180°, extrudes the edge's 10 curves 0.5 in along
# -ZC, mirrors the edge (Edit > Transform > Mirror Through a Plane, Copy) to the other side and revolves the flange's
# 4 curves like the wall. Indices are those of tutorial_mst.ag_reference: the inner chain 0-3, the wall's upper
# chain 4-7, the edge's lower chain 8-11, the wall's ends 12, 13, the edge's ends 14, 15, the flange 16-18 (and 15).
AO_WALL = list(range(0, 8)) + [12, 13]
AO_LIP = list(range(0, 4)) + list(range(8, 12)) + [14, 15]
AO_FLANGE = [15, 16, 17, 18]
AO_ALONG = {3: 0.25, 11: 0.25}          # Line 2 of the inner and lower chains: picked clear of the flange on them
AO_LIP_DEPTH = 0.5 * IN


class MstLowerCasingTutorials:
    """Mixin for tutorial.Replay: tutorial AO (it continues tutorial AG's part)."""

    def AO_STEPS(self):
        return [self.p_modeling, self.ao_open, self.ao_revolve, self.ao_revolve_section, self.ao_revolve_ok,
                self.ao_wall_view, self.ao_extrude, self.ao_extrude_section, self.ao_extrude_ok, self.ao_lip_view,
                self.ao_mirror, self.ao_mirror_ok, self.ao_flange, self.ao_flange_section, self.ao_flange_ok,
                self.ao_check, self.ao_fit, self.ao_show]

    # ------------------------------------------------------------- helpers
    def ao_ctl(self):
        from . import controller
        return controller.CONTROLLER

    def ao_map(self, sk):
        """{ag_reference index: geometry index of the sketch}: each reference curve matched by kind, ends and
        radius (the replayed sketch keeps its curves in the order they were drawn and copied)."""
        from .tutorial_mst import ag_reference
        out = {}
        a = min((sk.getPoint(g, 1).x for g, geo in enumerate(sk.Geometry) if "Line" in geo.TypeId
                 and abs(sk.getPoint(g, 1).y - sk.getPoint(g, 2).y) < 1e-6), default=0.0)
        for i, (kind, p, q, _c, r) in enumerate(ag_reference(a)):
            for g, geo in enumerate(sk.Geometry):
                k = "arc" if "Arc" in geo.TypeId else "line" if "Line" in geo.TypeId else None
                a1, b1 = sk.getPoint(g, 1), sk.getPoint(g, 2)
                if k == kind and abs(getattr(geo, "Radius", 0) - r) < 1e-3 and \
                        (((a1 - p).Length < 1e-3 and (b1 - q).Length < 1e-3) or
                         ((a1 - q).Length < 1e-3 and (b1 - p).Length < 1e-3)):
                    out[i] = g
                    break
        return out

    @staticmethod
    def ao_edge_names(sk):
        """{geometry index: 'EdgeN'} of the sketch's curves outside edit (its shape keeps another order; the
        sketch's point has no edge)."""
        from . import command_core as core

        def rec(e, place=None):
            a, b = e.FirstParameter, e.LastParameter
            pts = [e.valueAt(t) for t in (a, b, (a + b) / 2)]
            return tuple(tuple(place.multVec(p) if place else p) for p in pts)
        # the shape's edges carry the sketch's placement, its geometry does not
        geo = {i: rec(g.toShape(), sk.Placement) for i, g in enumerate(sk.Geometry)
               if "Point" not in g.TypeId and not sk.getConstruction(i)}
        return core.match_edges(geo, {f"Edge{i}": rec(e) for i, e in enumerate(sk.Shape.Edges, 1)})

    def ao_rule(self, label):
        """The Curve Rule list on the Top Border Bar, chosen as a user does."""
        from . import selection_filter as sf
        w = getattr(self.shell, "curve_rule", None)
        if w is None:
            return None
        i = w.findText(label)
        w.setCurrentIndex(i)
        QtWidgets.QApplication.processEvents()
        return w.currentText() if sf.manager().curve_rule == w.itemData(i) else None

    def ao_frame(self):
        sk = self._ao_sk
        bb = sk.Shape.BoundBox
        w = self.nav().widget
        aspect = w.height() / max(w.width(), 1)
        self.frame_sketch(sk, (bb.XMin + bb.XMax) / 2, (bb.YMin + bb.YMax) / 2,
                          max(bb.YLength * 1.3, bb.XLength * 1.1 * aspect))
        QtWidgets.QApplication.processEvents()

    def ao_pick(self, ref):
        sk, g = self._ao_sk, self._ao_map[ref]
        return self.curve_pick(sk, g, self._ao_names[g], AO_ALONG.get(ref, 0.5))

    def curve_pick(self, sk, g, name, along=0.5):
        """Pick curve g (shape edge name) of the sketch sk as a user does: MB1 where it is the only thing under the
        pointer, else its row in QuickPick (a solid's face or edge, or a curve on top of it, lies there); the point
        is along the curve by that fraction. Returns the route."""
        from . import selection_filter as sf
        from .smoke_section import Run
        from .tutorial import qtest
        e = sk.Geometry[g].toShape()
        t = e.FirstParameter + along * (e.LastParameter - e.FirstParameter)
        view = self.view()
        coin = view.getPointOnViewport(sk.getGlobalPlacement().multVec(e.valueAt(t)))
        rows = sf.rows_at(view, coin)
        want = next((r for r in rows if r["pick"].leaf is sk and r["pick"].element == name), None)
        w = self.nav().widget
        dpr = w.devicePixelRatioF() if hasattr(w, "devicePixelRatioF") else 1.0
        p = QtCore.QPoint(int(coin[0] / dpr), int(w.height() - coin[1] / dpr))
        self.send(QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton)
        QtWidgets.QApplication.processEvents()
        qtest().qWait(40)
        alone = want is not None and Run.preselected() == (sk, name) and all(r["pick"].leaf is sk for r in rows)
        if alone:
            self.mb1_click(p)
            route = "click"
            if not self.wait_for(f"the click took {name}", lambda: self.ao_taken(sk, name), timeout_ms=1500):
                route = "QuickPick (the click was not taken)"
                sf.select_row(want, clear=False)
        elif want is not None:
            route = "QuickPick"
            sf.select_row(want, clear=False)
        else:
            route = f"missing ({[r['label'] for r in rows[:3]]})"
        qtest().qWait(QtWidgets.QApplication.doubleClickInterval() + 80)   # not a double click: a whole object
        return route

    def ao_taken(self, sk, name):
        """Curve name of sketch sk is in the section, the whole sketch is (Inferred Curves), or, while FreeCAD's
        plane list still shows, the curve is selected."""
        s = self.ao_ctl().session
        if s is not None and s.stage == "parameterize" and getattr(s, "sketch", None) is sk and \
                (not s.edges or name in s.edges):
            return True
        return any(x.Object is sk and any(sub.split(".")[-1] == name for sub in x.SubElementNames)
                   for x in Gui.Selection.getSelectionEx("", 0))

    def ao_picks(self, refs):
        routes = [self.ao_pick(r) for r in refs]
        counts = {k: routes.count(k) for k in sorted(set(routes))}
        return routes, ", ".join(f"{n} by {k}" for k, n in counts.items())

    def ao_opened(self, n, ms=6000):
        """The NX box is up with n curves in the section."""
        from . import controller

        def up():
            s = self.ao_ctl().session
            return s is not None and s.stage == "parameterize" and controller._alive(s.box) and \
                s.edges is not None and len(s.edges) == n
        return self.wait_for(f"the section holds {n} curves", up, timeout_ms=ms)

    def ao_axis(self):
        """Specify Vector XC, Specify Point (0, 0, 0), Start 0, End 180: chosen and typed in the box."""
        vector = self.set_combo("nxSpecifyVector", "XC")
        for c in "XYZ":
            self.set_quantity(f"nxPoint{c}", 0)
        self.set_quantity("nxLimitStart", 0)
        self.set_quantity("nxLimitEnd", 180)
        QtWidgets.QApplication.processEvents()
        s = self.ao_ctl().session
        return vector, (dict(s.axis), tuple(s.limits) if s.limits else None) if s is not None else None

    def ao_ok(self):
        """The box's OK, clicked; returns whether it was available."""
        from .tutorial import qtest
        ctl = self.ao_ctl()
        b = ctl._ok_button()
        enabled = b is not None and b.isEnabled()
        if enabled:
            qtest().mouseClick(b, Qt.LeftButton)
        self.wait_for("the command ended", lambda: not ctl.busy() and not Gui.Control.activeDialog(),
                      timeout_ms=8000)
        return enabled

    def ao_subs(self, refs):
        return sorted((self._ao_names[self._ao_map[r]] for r in refs), key=lambda e: int(e[4:]))

    def ao_expected(self, refs, how):
        from .smoke_section import expected
        return expected(self._ao_sk, [self._ao_map[r] for r in refs], how).Volume

    def ao_bodies(self):
        return [o for o in App.ActiveDocument.Objects if o.isDerivedFrom("PartDesign::Body")]

    def ao_trimetric(self, name):
        self.key("Home")
        self.key("Ctrl+F")
        self._ao_shot = name
        self.wait = 1500

    def ao_top(self):
        if getattr(self, "_ao_shot", None):
            self.shot(self._ao_shot)
            self._ao_shot = None
        self.key("Ctrl+Alt+T")
        self.key("Ctrl+F")

    # ------------------------------------------------------------- open
    def ao_open(self):
        import os
        from .tutorial import OUT
        self.tutorial = ("AO: Impeller Lower Casing, Extrude and Revolve (NX 12 for Engineering Design, 4.4; book in "
                         "inches, typed in mm)")
        path = os.path.join(OUT, "Impeller_lower_casing.FCStd")
        for name, d in list(App.listDocuments().items()):
            if os.path.normcase(d.FileName or "") == os.path.normcase(path):
                App.closeDocument(name)
        QtWidgets.QApplication.processEvents()
        doc = App.openDocument(path) if os.path.exists(path) else None
        sk = next((o for o in doc.Objects if o.TypeId == "Sketcher::SketchObject"), None) if doc else None
        self._ao_sk = sk
        self._ao_map = self.ao_map(sk) if sk is not None else {}
        self._ao_names = self.ao_edge_names(sk) if sk is not None else {}
        ok = sk is not None and len(self._ao_map) == 19 and all(g in self._ao_names for g in self._ao_map.values())
        self.step("Open Impeller_lower_casing (tutorial AG's part)", "File > Open (by script)", SAME if ok else FAIL,
                  f"the sketch with {len(self._ao_map)} of the 19 curves of the book's figure; shown "
                  f"{sk.ViewObject.Visibility}" if sk is not None else f"no part at {path}: tutorial AG saves it")
        if not ok:
            raise RuntimeError("no casing sketch; tutorial AO cannot continue")
        self._ao_rev_before = len([o for o in doc.Objects if o.TypeId == "PartDesign::Revolution"])
        self.key("Ctrl+Alt+T")
        self.key("Ctrl+F")
        self.wait = 1500

    # ------------------------------------------------------------- Revolve the wall
    def ao_revolve(self):
        Gui.Selection.clearSelection()
        self._ao_undo = list(App.ActiveDocument.UndoNames)
        b, self._ao_where = self.click_ribbon("Revolve")
        self.wait = 1200

    def ao_revolve_section(self):
        asked = bool(Gui.Control.activeDialog())
        rule = self.ao_rule("Single Curve")
        self.ao_frame()
        routes, how = self.ao_picks(AO_WALL)
        up = self.ao_opened(len(AO_WALL))
        s = self.ao_ctl().session
        edges = sorted(s.edges or [], key=lambda e: int(e[4:])) if s is not None else []
        self.info["AO wall picks"] = routes
        self.step("Revolve, Selection Filter Single Curve, the 10 curves of the wall", f"ribbon '{self._ao_where} > "
                  f"Revolve' (FreeCAD asks for a plane: {asked}), Curve Rule '{rule}', MB1 on each curve: {how}",
                  SAME if up and rule and edges == self.ao_subs(AO_WALL) else FAIL,
                  f"the section holds {len(edges)} curves, the wall's {edges == self.ao_subs(AO_WALL)}; the first "
                  "pick closes FreeCAD's plane list and opens the dialog with it")
        vector, state = self.ao_axis()
        self._ao_state = state
        self.step("Axis: Specify Vector XC, Specify Point (0, 0, 0); Start 0, End 180",
                  f"'{vector}' chosen, X, Y, Z and the angles typed in the box",
                  SAME if state and state[0]["vector"] == "XC" and tuple(state[0]["point"]) == (0, 0, 0)
                  and state[1] == (0.0, 180.0) else FAIL, f"axis {state[0] if state else None}, limits "
                  f"{state[1] if state else None}")
        self.wait = 300

    def ao_revolve_ok(self):
        doc = App.ActiveDocument
        ok = self.ao_ok()
        revs = [o for o in doc.Objects if o.TypeId == "PartDesign::Revolution"]
        rev = revs[-1] if revs else None
        prof = sorted(rev.Profile[1], key=lambda e: int(e[4:])) if rev is not None else None
        box = rev.Shape.optimalBoundingBox(False, False) if rev is not None else None
        last = self.ao_ctl().history[-1] if self.ao_ctl().history else {}
        self.check_volume("OK: the revolved wall", f"OK {'clicked' if ok else 'unavailable'}",
                          self.ao_expected(AO_WALL, "revolve"),
                          f"; Profile the 10 curves {prof == self.ao_subs(AO_WALL)}; below the sketch plane "
                          f"{box is not None and box.ZMax < 1e-6}; one undo step {last.get('undo_steps') == 1} "
                          f"({doc.UndoNames[:1]})")
        self.ao_trimetric("AO1_wall.png")

    def ao_wall_view(self):
        self.ao_top()
        self.wait = 1500

    # ------------------------------------------------------------- Extrude the edge
    def ao_extrude(self):
        Gui.Selection.clearSelection()
        self._ao_bodies0 = len(self.ao_bodies())
        b, self._ao_where = self.click_ribbon("Extrude")
        self.wait = 1200

    def ao_extrude_section(self):
        from .tutorial import qtest
        asked = bool(Gui.Control.activeDialog())
        rule = self.ao_rule("Single Curve")
        self.ao_frame()
        routes, how = self.ao_picks(AO_LIP)
        up = self.ao_opened(len(AO_LIP))
        s = self.ao_ctl().session
        edges = sorted(s.edges or [], key=lambda e: int(e[4:])) if s is not None else []
        self.info["AO edge picks"] = routes
        self.step("Extrude, Single Curve, the outer curves of the casing (its edge)", f"ribbon '{self._ao_where} > "
                  f"Extrude' (plane asked: {asked}), Curve Rule '{rule}', MB1 on each curve: {how}",
                  SAME if up and edges == self.ao_subs(AO_LIP) else FAIL,
                  f"the section holds {len(edges)} curves, the edge's {edges == self.ao_subs(AO_LIP)}; where a "
                  "curve lies on the wall's face, QuickPick lists it (the book's note: press and hold MB1)")
        boolean = self.set_combo("nxBoolean", "None")
        length = self.set_quantity("lengthEdit", AO_LIP_DEPTH)
        rev = self._field(QtWidgets.QCheckBox, "checkBoxReversed")
        if rev is not None and not rev.isChecked():
            # on its box: the check box fills the panel's row, and a click right of its label does not toggle it
            opt = QtWidgets.QStyleOptionButton()
            rev.initStyleOption(opt)
            at = rev.style().subElementRect(QtWidgets.QStyle.SE_CheckBoxIndicator, opt, rev).center()
            qtest().mouseClick(rev, Qt.LeftButton, Qt.NoModifier, at)
            QtWidgets.QApplication.processEvents()
        self._ao_lip_how = (f"Boolean '{boolean}' in the box; '{length}' = 12.7 mm and Reversed clicked "
                            f"({rev.isChecked() if rev is not None else 'not found'}) in FreeCAD's panel")
        self.wait = 300

    def ao_extrude_ok(self):
        doc = App.ActiveDocument
        ok = self.ao_ok()
        pads = [o for o in doc.Objects if o.TypeId == "PartDesign::Pad"]
        pad = pads[-1] if pads else None
        bodies = self.ao_bodies()
        want = self.ao_expected(AO_LIP, "extrude")
        got = pad.Shape.Volume if pad is not None else 0.0
        box = pad.Shape.optimalBoundingBox(False, False) if pad is not None else None
        down = box is not None and abs(box.ZMin + AO_LIP_DEPTH) < 1e-6 and box.ZMax < 1e-6
        self._ao_pad = pad
        self.step("Extrude it 0.5 in along -ZC, OK", f"{self._ao_lip_how}; OK {'clicked' if ok else 'unavailable'}",
                  SAME if ok and pad is not None and abs(got - want) < 1e-6 * want and down
                  and len(bodies) == self._ao_bodies0 + 1 else FAIL,
                  f"volume {got:.1f} mm^3, expected {want:.1f}; z {box.ZMin:.2f} to {box.ZMax:.2f} mm; its own body "
                  f"({len(bodies)} bodies): with Unite it would touch the wall only along a line, two solids in one "
                  "body, so the edge is a body of its own, as the book's Solid Body filter in the next step shows"
                  if box is not None else f"OK {ok}; no Extrude")
        self.ao_trimetric("AO2_edge.png")

    def ao_lip_view(self):
        self.ao_top()
        self.wait = 1500

    # ------------------------------------------------------------- Mirror the edge
    def ao_mirror(self):
        pad = self._ao_pad
        body = next((b for b in self.ao_bodies() if pad in b.Group), None)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, body.Name, f"{pad.Name}.")
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
        self._ao_lip_body = body
        self._ao_lip_volume = pad.Shape.Volume
        b, self._ao_where = self.click_ribbon("Mirror Feature")
        self.wait = 1500

    def ao_mirror_ok(self):
        self.wait_dialog("ao_mirror_ok")
        self.info["AO mirror widgets"] = self.task_widgets()
        plane = None
        for c in self.tasks_dock().findChildren(QtWidgets.QComboBox):
            i = next((k for k in range(c.count()) if "xz" in c.itemText(k).lower().replace("_", "").replace("-", "")),
                     None)
            if i is not None:
                c.setCurrentIndex(i)
                c.activated.emit(i)
                QtWidgets.QApplication.processEvents()
                plane = c.itemText(i)
                break
        self.mb2_click()
        App.ActiveDocument.recompute()
        m = self.newest("PartDesign::Mirrored")
        body = self._ao_lip_body
        shape = body.Shape
        bb = shape.optimalBoundingBox(False, False) if not shape.isNull() else None
        ok = m is not None and len(shape.Solids) == 2 and abs(shape.Volume - 2 * self._ao_lip_volume) < 1e-6 * \
            shape.Volume and bb is not None and abs(bb.YMin + bb.YMax) < 1e-6 and not Gui.Control.activeDialog()
        self.step("Mirror the edge through the centre plane, Copy", "the edge's body made the work body and its "
                  "Extrude selected (Part Navigator) + "
                  f"ribbon '{self._ao_where} > Mirror Feature', plane '{plane}', MB2 = OK",
                  DIFFERS if ok else FAIL,
                  f"the edge's body holds {len(shape.Solids)} solids, {shape.Volume:.1f} mm^3 (twice "
                  f"{self._ao_lip_volume:.1f}), symmetric about XZ (y {bb.YMin:.1f} to {bb.YMax:.1f} mm). NX's Edit > "
                  "Transform copies the solid unparametrised; Mirror Feature keeps the copy following the edge"
                  if bb is not None else f"no mirrored edge; dialog widgets {self.info['AO mirror widgets'][:12]}")
        self.ao_trimetric("AO3_mirror.png")

    # ------------------------------------------------------------- Revolve the flange
    def ao_flange(self):
        self.ao_top()
        wall = self.ao_bodies()[0]
        Gui.Selection.clearSelection()
        self._ao_wall_volume = wall.Shape.Volume
        b, self._ao_where = self.click_ribbon("Revolve")
        self.wait = 1500

    def ao_flange_section(self):
        asked = bool(Gui.Control.activeDialog())
        rule = self.ao_rule("Single Curve")
        self.ao_frame()
        routes, how = self.ao_picks(AO_FLANGE)
        up = self.ao_opened(len(AO_FLANGE))
        s = self.ao_ctl().session
        edges = sorted(s.edges or [], key=lambda e: int(e[4:])) if s is not None else []
        self.info["AO flange picks"] = routes
        self.step("Revolve, Single Curve, the 4 curves of the flange", f"ribbon '{self._ao_where} > Revolve' (plane "
                  f"asked: {asked}), Curve Rule '{rule}', MB1 on each curve: {how}",
                  SAME if up and edges == self.ao_subs(AO_FLANGE) else FAIL,
                  f"the section holds {len(edges)} curves, the flange's {edges == self.ao_subs(AO_FLANGE)}; two of "
                  "them lie on the wall's and the edge's lines, and QuickPick tells them apart")
        vector, state = self.ao_axis()
        mode = s.mode if s is not None else None
        if mode != "unite":
            self.set_combo("nxBoolean", "Unite")
        s = self.ao_ctl().session
        self.step("XC through the origin, Start 0, End 180, as for the casing",
                  f"'{vector}', X, Y, Z and the angles typed; Boolean {'Unite by itself' if mode == 'unite' else 'set to Unite'}",
                  SAME if state and state[0]["vector"] == "XC" and state[1] == (0.0, 180.0)
                  and s is not None and s.mode == "unite" else FAIL,
                  f"axis {state[0] if state else None}, limits {state[1] if state else None}, Boolean "
                  f"{s.mode if s else None}")
        self.wait = 300

    def ao_flange_ok(self):
        ok = self.ao_ok()
        wall = self.ao_bodies()[0]
        want = self._ao_wall_volume + self.ao_expected(AO_FLANGE, "revolve")
        self.check_volume("OK: the flange, united with the wall", f"OK {'clicked' if ok else 'unavailable'}", want,
                          "; the flange's volume added to the wall's")
        self._ao_wall = wall
        self.ao_trimetric("AO4_casing.png")

    # ------------------------------------------------------------- check, save
    def ao_reference(self):
        """The casing as the book's curves make it, through the Part API: the wall and the flange revolved,
        the edge extruded and mirrored."""
        import Part
        sk = self._ao_sk

        def face(refs):
            edges = Part.__sortEdges__([sk.Geometry[self._ao_map[r]].toShape() for r in refs])
            return Part.Face(Part.Wire(edges))
        o, x = App.Vector(0, 0, 0), App.Vector(1, 0, 0)
        wall = face(AO_WALL).revolve(o, x, 180).fuse(face(AO_FLANGE).revolve(o, x, 180)).removeSplitter()
        lip = face(AO_LIP).extrude(App.Vector(0, 0, -AO_LIP_DEPTH))
        return wall, Part.makeCompound([lip, lip.mirror(o, App.Vector(0, 1, 0))])

    def ao_check(self):
        from . import geomcheck
        if getattr(self, "_ao_shot", None):
            self.shot(self._ao_shot)
            self._ao_shot = None
        wall_ref, lip_ref = self.ao_reference()
        bodies = self.ao_bodies()
        ok_w, how_w = geomcheck.compare(bodies[0].Shape if bodies else None, wall_ref)
        ok_l, how_l = geomcheck.compare(self._ao_lip_body.Shape, lip_ref)
        self.step("The lower casing: the wall with its flange, the edge on both sides",
                  "compared with the book's curves revolved and extruded by the Part API",
                  SAME if ok_w and ok_l else FAIL, f"wall and flange: {how_w}; edges: {how_l}")
        self.ao_rule("Inferred Curves")
        outcome, how, detail, path = self.save_ctrl_s("Impeller_lower_casing.FCStd")
        self.step("Save the model", how, outcome, detail)
        self.wait = 300

    def ao_fit(self):
        self.fit()

    def ao_show(self):
        self.show("AO_impeller_lower_casing")


# ================================================================== AP: Impeller Shaft (4.2.2)
# The book (pp. 57-60), inches: a Cylinder (Axis, Diameter, and Height) on ZC from (0, 0, 0), Ø4 x 18; a Cone
# (Diameters and Height) on ZC from the centre of the cylinder's top edge (0, 0, 18), base Ø4, top Ø6, height 10,
# united; a Cylinder on ZC from the centre of the cone's top edge (0, 0, 28), Ø6 x 20, united.
AP_CYL1 = (4 * IN, 18 * IN)
AP_CONE = (4 * IN, 6 * IN, 10 * IN)
AP_CYL2 = (6 * IN, 20 * IN)
AP_Z_CONE = AP_CYL1[1]
AP_Z_CYL2 = AP_CYL1[1] + AP_CONE[2]


def ap_reference():
    """The shaft as the book dimensions it: cylinder, frustum and cylinder on one axis."""
    import Part
    z = App.Vector(0, 0, 1)
    lower = Part.makeCylinder(AP_CYL1[0] / 2, AP_CYL1[1])
    cone = Part.makeCone(AP_CONE[0] / 2, AP_CONE[1] / 2, AP_CONE[2], App.Vector(0, 0, AP_Z_CONE), z)
    upper = Part.makeCylinder(AP_CYL2[0] / 2, AP_CYL2[1], App.Vector(0, 0, AP_Z_CYL2), z)
    return lower.fuse([cone, upper]).removeSplitter()


def ap_volume():
    r1, r2, h = AP_CONE[0] / 2, AP_CONE[1] / 2, AP_CONE[2]
    return (math.pi * (AP_CYL1[0] / 2) ** 2 * AP_CYL1[1] + math.pi * h / 3 * (r1 * r1 + r1 * r2 + r2 * r2)
            + math.pi * (AP_CYL2[0] / 2) ** 2 * AP_CYL2[1])


class MstShaftTutorials:
    """Mixin for tutorial.Replay: tutorial AP."""

    def AP_STEPS(self):
        return [self.p_modeling, self.ap_new, self.ap_save, self.ap_cylinder, self.ap_view, self.ap_cone,
                self.ap_cone_dialog, self.ap_cone_view, self.ap_cylinder2, self.ap_check, self.ap_fit, self.ap_show]

    # ------------------------------------------------------------- helpers
    def ap_screen(self, p):
        """A model point (mm) -> widget pixel position."""
        from .qt import QtCore
        sx, sy = self.view().getPointOnViewport(App.Vector(*p))
        w = self.nav().widget
        dpr = w.devicePixelRatioF() if hasattr(w, "devicePixelRatioF") else 1.0
        return QtCore.QPoint(int(round(sx / dpr)), int(round(w.height() - sy / dpr)))

    def ap_rim(self, z, r, side=False):
        """The point of the circle (centre on ZC at height z, radius r) nearest the viewer: on the edge's outline.
        side: its left or right end on the screen instead, where nothing seen edge-on stands in front of it (a
        prism's vertical edge nearest the viewer runs through the nearest point)."""
        d = self.view().getViewDirection()
        u = App.Vector(-d.x, -d.y, 0)
        u = u.normalize() if u.Length > 1e-9 else App.Vector(1, 0, 0)
        if side:
            u = App.Vector(-u.y, u.x, 0)
        return (r * u.x, r * u.y, z)

    def ap_pick_center(self, p, z, r, side=False):
        """Specify Point with Arc/Ellipse/Sphere Center: MB1 on the circular edge (centre (0, 0, z), radius r).
        Returns (point type, the point in XC/YC/ZC, the step's status, the pick in the window)."""
        from .smoke_primitives import choose
        from .tutorial import qtest
        p.activate("origin")
        kind = choose(p, "originPointType", "Arc/Ellipse/Sphere Center")
        rim = self.ap_rim(z, r, side)
        at = self.ap_screen(rim)
        self.mb1_click(at)
        qtest().qWait(400)
        return kind, p.steps["origin"].point(), p.steps["origin"].status.text(), (at.x(), at.y())

    def ap_dialog(self, command, kind, dims, boolean, label, how_extra, want, center=None, typed=(0, 0, 0),
                  target=None, check=None, axis="ZC", point_type="Inferred Point"):
        """Fill the Block, Cylinder, Cone or Sphere dialog the way the book does, press OK, and check the result.
        center (z, r): Arc/Ellipse/Sphere Center and a click on that circle about ZC; else the point typed. target:
        the body the Boolean works on, chosen in Select Body. check: () -> (ok, detail) instead of the volume of
        the part's first body (want)."""
        from . import primitive_ui
        from .smoke_primitives import choose, field, ok
        p = primitive_ui.current()
        if p is None:
            self.step(label, f"ribbon '{command}'", FAIL, f"the {command} dialog did not open")
            raise RuntimeError(f"no {command} dialog; the tutorial cannot continue")
        typ = choose(p, "nxType", kind)
        vector = choose(p, "nxVector", axis) if command in ("Cylinder", "Cone") else None
        if callable(center):                 # picks of the caller's own: (description, the point it should give)
            pick, where = center(p)
            got = p.steps["origin"].point()
        elif center is None:
            pick = None
            choose(p, "originPointType", point_type)
            for name, v in zip(("originXC", "originYC", "originZC"), typed):
                self.type_into(field(p, name), v)
            got = p.steps["origin"].point()
        else:
            ptype, got, status, at = self.ap_pick_center(p, *center)
            pick = f"'{ptype}', MB1 at pixel {at}: {status}"
        for name, v in dims:
            self.type_into(field(p, name), v)
        mode = choose(p, "nxBoolean", boolean)
        if target is not None:
            p.activate("body")
            combo = p.steps["body"].combo
            i = combo.findData(target.Name)
            combo.setCurrentIndex(i)
            combo.activated.emit(i)
            from .tutorial import qtest
            qtest().qWait(500)                   # the dialog rebuilds its preview for the new target
        chosen = p.steps["body"].chosen()
        pressed = ok()
        if not callable(center):
            where = tuple(typed) if center is None else (0, 0, center[0])
        at_point = got is not None and all(abs(a - b) < 1e-6 for a, b in zip(got, where))
        undo = App.ActiveDocument.UndoNames[:1]
        how = (f"ribbon '{self._ap_where}', Type '{typ}'" + (f", Specify Vector '{vector}'" if vector else "")
               + ", " + (pick if pick else f"XC/YC/ZC {'/'.join(f'{v:g}' for v in typed)} typed")
               + f", {how_extra}, Boolean '{mode}'" + (f", Select Body '{target.Label}' from the list"
                                                       if target is not None else "") + ", OK")
        if not (pressed and at_point and undo == [command] and (target is None or chosen == target.Name)):
            self.step(label, how, FAIL, f"OK pressed {pressed}; point {got}, wanted {where}; target {chosen}; "
                      f"undo {App.ActiveDocument.UndoNames[:2]}")
            return False
        extra = f"; origin {tuple(round(c, 6) for c in got)}; one undo step {undo}" + \
            (f"; with {chosen}" if boolean != "None" else "")
        if check is not None:
            App.ActiveDocument.recompute()
            good, detail = check()
            self.step(label, how, SAME if good else FAIL, detail + extra)
            return good
        return self.check_volume(label, how, want, extra)

    # ------------------------------------------------------------- New, Save, the first cylinder
    def ap_new(self):
        self.tutorial = "AP: Impeller Shaft (NX 12 for Engineering Design, 4.2.2; book in inches, typed in mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def ap_save(self):
        new = set(App.listDocuments()) - self._docs_before
        self.step("Create a new file (Impeller_shaft)", "Ctrl+N, Model template",
                  SAME if new and self.body() else FAIL, f"new document {sorted(new)}")
        self.units_step()
        outcome, how, detail, path = self.save_ctrl_s("Impeller_shaft.FCStd")
        self.step("Save it as Impeller_shaft", how, outcome, detail)
        Gui.Selection.clearSelection()
        b, self._ap_where = self.click_ribbon("Cylinder")
        self.wait = 800

    def ap_cylinder(self):
        self.ap_dialog("Cylinder", "Axis, Diameter, and Height", (("diameter", AP_CYL1[0]), ("height", AP_CYL1[1])),
                       "None", "Cylinder: Axis, Diameter, and Height; ZC Axis; Point Dialog (0, 0, 0); Diameter 4, "
                       "Height 18; OK", "Diameter 101.6 and Height 457.2 typed",
                       math.pi * (AP_CYL1[0] / 2) ** 2 * AP_CYL1[1])
        self.wait = 400

    def ap_view(self):
        self.key("Ctrl+F")
        self.key("End")
        self.wait = 1500

    # ------------------------------------------------------------- the cone, the second cylinder
    def ap_cone(self):
        from . import pmi_views
        d = self.view().getViewDirection()
        want = pmi_views.STANDARD["Isometric"][0]
        along = d.x * want[0] + d.y * want[1] + d.z * want[2]
        self.step("MB3 > Orient View > Isometric", "Ctrl+F (Fit, to see the cylinder whole), End (NX's Isometric key)",
                  SAME if along > 1 - 1e-6 else FAIL,
                  f"view direction {tuple(round(c, 4) for c in d)} (isometric {along:.6f})")
        self.shot("AP1_cylinder.png")
        Gui.Selection.clearSelection()
        b, self._ap_where = self.click_ribbon("Cone")
        self.wait = 800

    def ap_cone_dialog(self):
        r1, r2, h = AP_CONE[0] / 2, AP_CONE[1] / 2, AP_CONE[2]
        want = math.pi * (AP_CYL1[0] / 2) ** 2 * AP_CYL1[1] + math.pi * h / 3 * (r1 * r1 + r1 * r2 + r2 * r2)
        self.ap_dialog("Cone", "Diameters and Height",
                       (("baseDiameter", AP_CONE[0]), ("topDiameter", AP_CONE[1]), ("height", AP_CONE[2])), "Unite",
                       "Cone: Diameters and Height; ZC Axis; Point Constructor, Arc/Ellipse/Sphere Center on the "
                       "cylinder's top edge; Base Diameter 4, Top Diameter 6, Height 10; Unite with the cylinder; OK",
                       "Base 101.6, Top 152.4, Height 254 typed", want, center=(AP_Z_CONE, AP_CYL1[0] / 2))
        self.key("Ctrl+F")
        self.wait = 1500

    def ap_cone_view(self):
        self.shot("AP2_cone.png")
        Gui.Selection.clearSelection()
        b, self._ap_where = self.click_ribbon("Cylinder")
        self.wait = 1000

    def ap_cylinder2(self):
        self.ap_dialog("Cylinder", "Axis, Diameter, and Height", (("diameter", AP_CYL2[0]), ("height", AP_CYL2[1])),
                       "Unite", "Cylinder: ZC Axis; Arc/Ellipse/Sphere Center on the cone's top edge; Diameter 6, "
                       "Height 20; Unite; OK", "Diameter 152.4 and Height 508 typed", ap_volume(),
                       center=(AP_Z_CYL2, AP_CONE[1] / 2))
        self.wait = 400

    def ap_check(self):
        from . import geomcheck
        body = self.body()
        ok, detail = geomcheck.compare(body.Shape if body is not None else None, ap_reference())
        self.step("The shaft: cylinder, cone and cylinder in one solid", "compared with the book's dimensions",
                  SAME if ok else FAIL, detail)
        outcome, how, detail, path = self.save_ctrl_s("Impeller_shaft.FCStd")
        self.step("Save the model", how, outcome, detail)
        self.wait = 300

    def ap_fit(self):
        self.fit()

    def ap_show(self):
        self.show("AP_impeller_shaft")


# ================================================================== AQ, AR: Hexagonal Screw and Nut (4.7.1, 4.7.2)
# The book (pp. 77-82), inches. The screw: a Cylinder Ø0.25 x 1.5 on ZC at the origin; a Cylinder Ø0.387 x 0.0156 at
# the centre of its top face, united; a hexagon of side 0.246 (Rotation 0) centred on that cylinder's top, extruded
# 0.1876; a Cylinder Ø0.387 x 0.1875 on the step cylinder; a Sphere Ø0.55 centred on the bottom of that cylinder,
# intersected with the hexagonal head; a Detailed Thread on the shank. The nut: a hexagon of side 0.28685 at the
# origin, extruded 0.125; a Sphere Ø0.57 at (0, 0, 0.125), Intersect; the half mirrored through its flat side and
# united; a Cylinder Ø0.25 x 1 at the origin subtracted; the two inner edges chamfered 0.0436.
# A regular hexagon's side is its circumradius; Rotation 0 puts a corner on XC.
AQ_SHANK = (0.25 * IN, 1.5 * IN)
AQ_STEP = (0.387 * IN, 0.0156 * IN)
AQ_HEX, AQ_HEX_H = 0.246 * IN, 0.1876 * IN
AQ_INNER = (0.387 * IN, 0.1875 * IN)
AQ_SPHERE = 0.55 * IN
AQ_Z_STEP = AQ_SHANK[1]
AQ_Z_HEAD = AQ_SHANK[1] + AQ_STEP[1]
AR_HEX, AR_HEX_H = 0.28685 * IN, 0.125 * IN
AR_SPHERE = 0.57 * IN
AR_HOLE = (0.25 * IN, 1.0 * IN)
AR_CHAMFER = 0.0436 * IN


def hole_edge(e, r):
    """e is a circle of radius r (an edge without a curve FreeCAD can name is not)."""
    try:
        return type(e.Curve).__name__ == "Circle" and abs(e.Curve.Radius - r) < 1e-6
    except Exception:
        return False


def hexagon_prism(r, z0, h):
    import Part
    pts = [App.Vector(r * math.cos(math.radians(60 * k)), r * math.sin(math.radians(60 * k)), z0) for k in range(7)]
    return Part.Face(Part.makePolygon(pts)).extrude(App.Vector(0, 0, h))


def aq_reference():
    """The screw as the book dimensions it, without the thread: shank, step, head (hexagon less what lies outside
    the sphere) and the cylinder inside the head."""
    import Part
    z = App.Vector(0, 0, 1)
    shank = Part.makeCylinder(AQ_SHANK[0] / 2, AQ_SHANK[1])
    step = Part.makeCylinder(AQ_STEP[0] / 2, AQ_STEP[1], App.Vector(0, 0, AQ_Z_STEP), z)
    head = hexagon_prism(AQ_HEX, AQ_Z_HEAD, AQ_HEX_H).common(Part.makeSphere(AQ_SPHERE / 2, App.Vector(0, 0, AQ_Z_HEAD)))
    inner = Part.makeCylinder(AQ_INNER[0] / 2, AQ_INNER[1], App.Vector(0, 0, AQ_Z_HEAD), z)
    return shank.fuse([step, head, inner]).removeSplitter()


def ar_half():
    import Part
    return hexagon_prism(AR_HEX, 0, AR_HEX_H).common(Part.makeSphere(AR_SPHERE / 2, App.Vector(0, 0, AR_HEX_H)))


def ar_reference(chamfer=True):
    """The nut: the half, mirrored through its flat side and united, less the Ø0.25 hole, its two edges chamfered."""
    import Part
    half = ar_half()
    nut = half.fuse(half.mirror(App.Vector(0, 0, AR_HEX_H), App.Vector(0, 0, 1))).removeSplitter()
    nut = nut.cut(Part.makeCylinder(AR_HOLE[0] / 2, AR_HOLE[1])).removeSplitter()
    if chamfer:
        edges = [e for e in nut.Edges if hole_edge(e, AR_HOLE[0] / 2)]
        nut = nut.makeChamfer(AR_CHAMFER, edges)
    return nut


class MstFastenerTutorials:
    """Mixin for tutorial.Replay: tutorials AQ (hexagonal screw) and AR (hexagonal nut)."""

    def AQ_STEPS(self):
        return [self.p_modeling, self.aq_new, self.aq_save, self.aq_shank, self.aq_view, self.aq_step,
                self.aq_sketch, self.aq_polygon, self.aq_finish, self.aq_extrude, self.aq_extrude_section,
                self.aq_wireframe, self.aq_inner, self.aq_sphere, self.aq_sphere_dialog, self.aq_check,
                self.aq_thread, self.aq_thread_dialog, self.aq_save_end, self.aq_fit, self.aq_show]

    def AR_STEPS(self):
        return [self.p_modeling, self.ar_new, self.ar_save, self.ar_plane, self.ar_polygon, self.ar_finish,
                self.ar_extrude, self.ar_extrude_section, self.ar_sphere, self.ar_sphere_dialog, self.ar_mirror,
                self.ar_mirror_dialog, self.ar_hole, self.ar_hole_dialog, self.ar_chamfer, self.ar_chamfer_dialog,
                self.ar_check, self.ar_fit, self.ar_show]

    # ------------------------------------------------------------- helpers
    def fs_zoom(self, p, height):
        """Centre the view on the model point p (mm), height mm tall (once FreeCAD's view animation has ended)."""
        from pivy import coin
        from .tutorial import settle_view
        settle_view(self.view())
        cam = self.view().getCameraNode()
        d = cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
        cam.position.setValue(coin.SbVec3f(*p) - d * cam.focalDistance.getValue())
        if hasattr(cam, "height"):
            cam.height.setValue(height)
        QtWidgets.QApplication.processEvents()

    def fs_polygon(self, sk, r):
        """Polygon (P) in the sketch: the centre typed (0, 0) in the fields beside the pointer, then the corner
        typed (r along XC: the side length of a hexagon, Rotation 0); MB2 ends the tool. Returns (how, missing
        corners)."""
        from . import sketch_ui
        from .smoke import decode
        from .tutorial import qtest
        view = self.nav().widget
        self.frame_sketch(sk, 0, 0, r * 5)
        n0 = len(sk.Geometry)
        asked = {}

        def sides(w):
            """FreeCAD's Regular Polygon asks for the number of sides first: 6, OK."""
            box = next(iter(w.findChildren(QtWidgets.QSpinBox)), None)
            ok = next((b for b in w.findChildren(QtWidgets.QAbstractButton) if b.text().replace("&", "") == "OK"),
                      None)
            if box is None or ok is None:
                return False
            box.setFocus()
            box.selectAll()
            qtest().keyClicks(box, "6")
            asked.update(title=w.windowTitle(), sides=box.value())
            ok.click()
            return True
        self.modals.handler = sides
        self.key("P")
        QtWidgets.QApplication.processEvents()
        qtest().qWait(300)
        self.modals.handler = None
        tool = self.nav().sketch_tool_active()
        near = self.screen_point(sk, -r * 0.6, r * 0.7)
        self.send(QtCore.QEvent.MouseMove, near, Qt.NoButton, Qt.NoButton)
        qtest().qWait(200)
        typed = []
        fields = sketch_ui.xy_fields(sk, view, near)
        for w, v in zip(fields or (), (0.0, 0.0)):
            w.setFocus()
            w.lineEdit().selectAll()
            qtest().keyClicks(w.lineEdit(), self.typed_number(w, v))
            qtest().keyClick(w.lineEdit(), *decode("Return"))
            qtest().qWait(150)
        typed.append("centre typed" if fields else "centre clicked")
        if not fields:
            self.mb1_click(self.screen_point(sk, 0, 0))
        corner = self.screen_point(sk, r, 0)
        self.send(QtCore.QEvent.MouseMove, corner, Qt.NoButton, Qt.NoButton)
        qtest().qWait(200)
        second = sketch_ui.on_view_fields(view)
        self.info.setdefault("polygon corner fields", []).append(
            [(w.objectName(), sketch_ui.field_value(w)) for w in second])
        if len(second) >= 2:
            # the length field shows the pointer's distance from the centre (r here), the other is the angle
            length = min(second[:2], key=lambda w: abs(sketch_ui.field_value(w) - r))
            angle = next(w for w in second[:2] if w is not length)
            for w, v in ((length, r), (angle, 0.0)):
                w.setFocus()
                w.lineEdit().selectAll()
                qtest().keyClicks(w.lineEdit(), self.typed_number(w, v))
                qtest().keyClick(w.lineEdit(), *decode("Return"))
                qtest().qWait(150)
            typed.append("corner typed")
        if len(sk.Geometry) == n0:
            self.mb1_click(corner)
            typed.append("corner clicked")
        self.mb2_click(self.screen_point(sk, -r * 2, r * 2))
        App.ActiveDocument.recompute()
        lines = [g for g in range(n0, len(sk.Geometry)) if "Line" in sk.Geometry[g].TypeId
                 and not sk.getConstruction(g)]
        corners = [sk.getPoint(g, 1) for g in lines]
        want = [App.Vector(r * math.cos(math.radians(60 * k)), r * math.sin(math.radians(60 * k)), 0)
                for k in range(6)]
        missing = [k for k, w in enumerate(want) if not any((c - w).Length < 1e-6 for c in corners)]
        sides_how = f"'{asked['title']}' {asked['sides']} sides, OK" if asked else "no sides asked"
        return f"P key ({sides_how}; tool {tool}), {', '.join(typed)}, MB2", len(lines), missing

    def fs_type(self, w, v):
        from .smoke import decode
        from .tutorial import qtest
        w.setFocus()
        w.lineEdit().selectAll()
        qtest().keyClicks(w.lineEdit(), self.typed_number(w, v))
        qtest().keyClick(w.lineEdit(), *decode("Return"))
        qtest().qWait(150)

    def fs_rectangle(self, sk, c1, c2):
        """Rectangle (R) in the sketch from corner c1 to the opposite corner c2 (sketch mm): c1 typed in the fields
        beside the pointer, then c2 as the fields offer it (its X and Y, or the length and the width); MB2 ends the
        tool. Returns (how, the corners found missing)."""
        from . import sketch_ui
        from .tutorial import qtest
        view = self.nav().widget
        (x1, y1), (x2, y2) = c1, c2
        span = max(abs(x2 - x1), abs(y2 - y1))
        self.frame_sketch(sk, (x1 + x2) / 2, (y1 + y2) / 2, span * 1.6)
        n0 = len(sk.Geometry)
        self.key("R")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        near = self.screen_point(sk, x1 - span * 0.05, y1 - span * 0.05)
        self.send(QtCore.QEvent.MouseMove, near, Qt.NoButton, Qt.NoButton)
        qtest().qWait(200)
        fields = sketch_ui.xy_fields(sk, view, near)
        for w, v in zip(fields or (), c1):
            self.fs_type(w, v)
        how = ["first corner typed" if fields else "first corner clicked"]
        if not fields:
            self.mb1_click(self.screen_point(sk, x1, y1))
        corner = self.screen_point(sk, x2, y2)
        self.send(QtCore.QEvent.MouseMove, corner, Qt.NoButton, Qt.NoButton)
        qtest().qWait(200)
        second = sketch_ui.on_view_fields(view)[:2]
        shown = [sketch_ui.field_value(w) for w in second]
        self.info.setdefault("rectangle corner fields", []).append(shown)
        if len(second) == 2:
            # the fields show the pointer's place as X, Y or as length, width, in an order of their own: each value
            # goes to the field showing the nearest number
            best = None
            for name, pair in (("X, Y", (x2, y2)), ("length, width", (x2 - x1, y2 - y1))):
                for order in ((0, 1), (1, 0)):
                    err = sum(abs(abs(shown[order[k]]) - abs(pair[k])) for k in range(2))
                    if best is None or err < best[0]:
                        best = (err, name, order, pair)
            _err, name, order, pair = best
            for k in range(2):
                self.fs_type(second[order[k]], pair[k])
            how.append(f"opposite corner typed as {name}")
        if len(sk.Geometry) == n0:
            self.mb1_click(corner)
            how.append("opposite corner clicked")
        self.mb2_click(self.screen_point(sk, x1 - span * 0.3, y2 + span * 0.3))
        App.ActiveDocument.recompute()
        lines = [g for g in range(n0, len(sk.Geometry)) if "Line" in sk.Geometry[g].TypeId
                 and not sk.getConstruction(g)]
        corners = [sk.getPoint(g, 1) for g in lines]
        want = [App.Vector(x, y, 0) for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))]
        missing = [k for k, w in enumerate(want) if not any((c - w).Length < 1e-6 for c in corners)]
        return f"R key (tool {tool}), {', '.join(how)}, MB2", len(lines), missing

    def fs_extrude(self, sk, length, boolean, taper=None):
        """Extrude started from the ribbon, the sketch picked in the graphics window by one of its lines (Curve
        Rule Inferred Curves: one pick is the whole sketch), Boolean, length (and taper) set, OK. Returns (how,
        OK available)."""
        from . import controller
        names = self.ao_edge_names(sk)
        line = next(g for g, geo in enumerate(sk.Geometry) if "Line" in geo.TypeId and not sk.getConstruction(g))
        route = self.curve_pick(sk, line, names[line])

        def up():
            s = self.ao_ctl().session
            return s is not None and s.stage == "parameterize" and controller._alive(s.box)
        opened = self.wait_for("the Extrude dialog", up, timeout_ms=6000)
        picked = self.set_combo("nxBoolean", boolean)
        field = self.set_quantity("lengthEdit", length)
        tapered = ""
        if taper is not None:
            self.info.setdefault("extrude panel widgets", []).append(self.task_widgets())
            name = self.set_quantity("taperEdit", taper) or self.set_quantity("taper", taper)
            tapered = f", '{name}' = {taper:g}°"
        ok = self.ao_ok()
        return (f"a side picked ({route}; Curve Rule Inferred Curves), dialog opened {opened}; Boolean "
                f"'{picked}', '{field}' = {length:g} mm{tapered}; OK"), ok

    def fs_new_feature(self, type_id, before):
        new = [o for o in App.ActiveDocument.Objects if o.TypeId == type_id and o.Name not in before]
        return new[-1] if new else None

    def fs_names(self, type_id):
        return {o.Name for o in App.ActiveDocument.Objects if o.TypeId == type_id}

    def fs_body_of(self, feature):
        return next((b for b in self.ao_bodies() if feature in b.Group), None)

    # ================================================================ AR: the nut
    def ar_new(self):
        self.tutorial = "AR: Hexagonal Nut (NX 12 for Engineering Design, 4.7.2; book in inches, typed in mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def ar_save(self):
        new = set(App.listDocuments()) - self._docs_before
        self.step("Create a new file (Impeller_hexa-nut)", "Ctrl+N, Model template",
                  SAME if new and self.body() else FAIL, f"new document {sorted(new)}")
        self.units_step()
        outcome, how, detail, path = self.save_ctrl_s("Impeller_hexa-nut.FCStd")
        self.step("Save it as Impeller_hexa-nut", how, outcome, detail)
        Gui.Selection.clearSelection()
        b, self._fs_where = self.click_ribbon("Sketch")
        self.wait = 1500

    def ar_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.wait_for("ar: sketch in edit", lambda: self.edited_sketch() is not None)
        self._ar_sk = self.edited_sketch()
        if self._ar_sk is None:
            self.step("Polygon: a sketch on the XC-YC plane", f"ribbon '{self._fs_where} > Sketch'", FAIL,
                      f"no sketch in edit (plane row {picked})")
            raise RuntimeError("no sketch; tutorial AR cannot continue")
        self._ar_plane = picked
        self.wait = 800

    def ar_polygon(self):
        how, n, missing = self.fs_polygon(self._ar_sk, AR_HEX)
        self.step("Polygon: 6 sides, Side Length 0.28685, at the origin",
                  f"ribbon '{self._fs_where} > Sketch' on '{self._ar_plane}', {how}",
                  DIFFERS if n == 6 and not missing else FAIL,
                  f"{n} sides; corners at the book's hexagon (side 7.28599 mm, a corner on XC): "
                  f"{'all six' if not missing else f'missing {missing}'}. NX 12's Insert > Curve > Polygon is a "
                  "curve outside sketches; NX-Style draws the polygon in a sketch (NX 2212: Sketch > Polygon), whose "
                  "corner is typed as the circumradius, which a hexagon's side length equals")
        self.wait = 300

    def ar_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1200

    def ar_extrude(self):
        Gui.Selection.clearSelection()
        self.key("Ctrl+F")
        self.key("Home")
        b, self._fs_where = self.click_ribbon("Extrude")
        self.wait = 1500

    def ar_extrude_section(self):
        how, ok = self.fs_extrude(self._ar_sk, AR_HEX_H, "None")
        want = hexagon_prism(AR_HEX, 0, AR_HEX_H).Volume
        self.check_volume("Extrude the hexagon, End Distance 0.125", f"ribbon '{self._fs_where} > Extrude', {how} "
                          f"{'clicked' if ok else 'unavailable'}", want, "; the part's first solid")
        self.wait = 400

    def ar_sphere(self):
        Gui.Selection.clearSelection()
        b, self._ap_where = self.click_ribbon("Sphere")
        self.wait = 800

    def ar_sphere_dialog(self):
        self.ap_dialog("Sphere", "Center Point and Diameter", (("diameter", AR_SPHERE),), "Intersect",
                       "Sphere: Center Point (0, 0, 0.125) in the Point Dialog, Diameter 0.57, Boolean Intersect, OK",
                       "Diameter 14.478 typed", ar_half().Volume, typed=(0, 0, AR_HEX_H))
        self.key("Ctrl+F")
        self.wait = 1200

    def ar_mirror(self):
        tip = self.body().Tip
        # the flat side, named on the Intersect: once the dialog is open the Mirror's preview is the tip
        self._ar_flat = self.face_of(tip, lambda f: abs(f.normalAt(0, 0).z - 1) < 1e-9
                                     and abs(f.CenterOfMass.z - AR_HEX_H) < 1e-6)
        self.select_sub(tip, "")
        self._ar_half = self.body().Shape.Volume
        b, self._fs_where = self.click_ribbon("Mirror Feature")
        self.wait = 1500

    def ar_mirror_dialog(self):
        from .tutorial import qtest
        self.wait_dialog("ar_mirror_dialog")
        self.info["AR mirror widgets"] = self.task_widgets()
        radio = self._field(QtWidgets.QRadioButton, "radioTransformBody")
        if radio is not None and not radio.isChecked():
            qtest().mouseClick(radio, Qt.LeftButton, Qt.NoModifier, QtCore.QPoint(8, radio.height() // 2))
            qtest().qWait(600)                   # FreeCAD rebuilds the panel for the body mode
        radio = self._field(QtWidgets.QRadioButton, "radioTransformBody")
        body_mode = radio.isChecked() if radio is not None else None   # the panel rebuilds itself again later
        ref = self.set_combo("comboPlane", "Select reference")
        qtest().qWait(300)
        body = self.body()
        flat = self._ar_flat
        at =self.ap_screen((AR_HEX * 0.3, -AR_HEX * 0.3, AR_HEX_H))
        self.send(QtCore.QEvent.MouseMove, at, Qt.NoButton, Qt.NoButton)
        qtest().qWait(150)
        pre = Gui.Selection.getPreselection()
        route = "click"
        if pre is not None and pre.ObjectName and any(s.endswith(flat or "?") for s in pre.SubElementNames):
            self.mb1_click(at)
        else:
            # while a reference is picked FreeCAD shows the origin planes, and one lies in front of the face here:
            # QuickPick lists what is under the pointer, and the face is chosen from it
            from . import selection_filter as sf
            w = self.nav().widget
            dpr = w.devicePixelRatioF() if hasattr(w, "devicePixelRatioF") else 1.0
            rows = sf.rows_at(self.view(), (at.x() * dpr, (w.height() - at.y()) * dpr))
            row = next((r for r in rows if r["pick"].element == flat), None)
            route = f"QuickPick ({[r['label'] for r in rows[:4]]})"
            if row is not None:
                sf.select_row(row, clear=True)
        qtest().qWait(600)
        plane = self._field(QtWidgets.QComboBox, "comboPlane")
        self.info["AR mirror plane pick"] = {
            "preselected": f"{pre.ObjectName}.{pre.SubElementNames}" if pre is not None and pre.ObjectName else None,
            "selection": [(s.ObjectName, list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx("", 0)],
            "items": [plane.itemText(i) for i in range(plane.count())] if plane is not None else None,
            "mirrored": [(m.Name, str(m.MirrorPlane)) for m in App.ActiveDocument.Objects
                         if m.TypeId == "PartDesign::Mirrored"]}
        shown = plane.currentText() if plane is not None else None
        self.mb2_click()
        App.ActiveDocument.recompute()
        shape = body.Shape
        bb = shape.optimalBoundingBox(False, False) if not shape.isNull() else None
        ok = len(shape.Solids) == 1 and abs(shape.Volume - 2 * self._ar_half) < 1e-6 * shape.Volume and bb is not None \
            and abs(bb.ZMin) < 1e-6 and abs(bb.ZMax - 2 * AR_HEX_H) < 1e-6 and not Gui.Control.activeDialog()
        self.step("Edit > Transform: the model, Mirror Through a Plane, its flat side, Copy",
                  f"the Intersect selected + ribbon '{self._fs_where} > Mirror Feature', Transform body "
                  f"{body_mode}, plane '{ref}' and the flat top face by {route} "
                  f"({flat}), MB2 = OK", DIFFERS if ok else FAIL,
                  f"plane shown '{shown}'; {len(shape.Solids)} solid, {shape.Volume:.1f} mm^3 (twice "
                  f"{self._ar_half:.1f}), z {bb.ZMin:.3f} to {bb.ZMax:.3f} mm. NX's Transform copies the body "
                  "unparametrised; Mirror Feature keeps the copy following the half" if bb is not None else
                  f"no shape; plane '{shown}'")
        self.step("Combine > Unite: the two halves", "nothing to do", DIFFERS if ok else FAIL,
                  "Mirror Feature with Transform body unites the copy with the body itself: the nut is one solid")
        self.key("Ctrl+F")
        self.wait = 1000

    def ar_hole(self):
        Gui.Selection.clearSelection()
        b, self._ap_where = self.click_ribbon("Cylinder")
        self.wait = 800

    def ar_hole_dialog(self):
        import Part
        half = ar_half()
        nut = half.fuse(half.mirror(App.Vector(0, 0, AR_HEX_H), App.Vector(0, 0, 1)))
        want = nut.cut(Part.makeCylinder(AR_HOLE[0] / 2, AR_HOLE[1])).Volume
        self.ap_dialog("Cylinder", "Axis, Diameter, and Height", (("diameter", AR_HOLE[0]), ("height", AR_HOLE[1])),
                       "Subtract", "Cylinder: ZC, at the origin, Diameter 0.25, Height 1, Subtract from the nut, OK",
                       "Diameter 6.35 and Height 25.4 typed", want)
        self.wait = 400

    def ar_chamfer(self):
        tip = self.body().Tip
        edges = [f"Edge{i}" for i, e in enumerate(tip.Shape.Edges, 1) if hole_edge(e, AR_HOLE[0] / 2)]
        self._ar_edges = edges
        self.select_subs(tip, edges)
        b, self._fs_where = self.click_ribbon("Chamfer")
        self.wait = 1500

    def ar_chamfer_dialog(self):
        self.wait_dialog("ar_chamfer_dialog")
        self.info["AR chamfer widgets"] = self.task_widgets()
        size = self.set_quantity("chamferSize", AR_CHAMFER) or self.set_quantity("Size", AR_CHAMFER)
        self.mb2_click()
        App.ActiveDocument.recompute()
        self.check_volume("Chamfer: the two inner edges, Distance 0.0436, OK",
                          f"{self._ar_edges} selected + ribbon '{self._fs_where} > Chamfer', '{size}' = 1.10744 mm, "
                          "MB2 = OK", ar_reference().Volume)
        self.wait = 400

    def ar_check(self):
        from . import geomcheck
        body = self.body()
        ok, detail = geomcheck.compare(body.Shape if body is not None else None, ar_reference())
        self.step("The nut", "compared with the book's dimensions", SAME if ok else FAIL, detail)
        outcome, how, detail, path = self.save_ctrl_s("Impeller_hexa-nut.FCStd")
        self.step("Save the model", how, outcome, detail)
        self.wait = 300

    def ar_fit(self):
        self.fit()

    def ar_show(self):
        self.show("AR_hexagonal_nut")

    # ================================================================ AQ: the screw
    def aq_new(self):
        self.tutorial = "AQ: Hexagonal Screw (NX 12 for Engineering Design, 4.7.1; book in inches, typed in mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def aq_save(self):
        new = set(App.listDocuments()) - self._docs_before
        self.step("Create a new file (Impeller_hexa-bolt)", "Ctrl+N, Model template",
                  SAME if new and self.body() else FAIL, f"new document {sorted(new)}")
        self.units_step()
        outcome, how, detail, path = self.save_ctrl_s("Impeller_hexa-bolt.FCStd")
        self.step("Save it as Impeller_hexa-bolt", how, outcome, detail)
        Gui.Selection.clearSelection()
        b, self._ap_where = self.click_ribbon("Cylinder")
        self.wait = 800

    def aq_shank(self):
        self.ap_dialog("Cylinder", "Axis, Diameter, and Height", (("diameter", AQ_SHANK[0]), ("height", AQ_SHANK[1])),
                       "None", "Cylinder: ZC, centre at the origin, Diameter 0.25, Height 1.5, OK",
                       "Diameter 6.35 and Height 38.1 typed", math.pi * (AQ_SHANK[0] / 2) ** 2 * AQ_SHANK[1])
        self.wait = 400

    def aq_view(self):
        self.key("Ctrl+F")
        self.key("Home")
        self.wait = 1500

    def aq_step(self):
        from .tutorial import qtest
        self.fs_zoom((0, 0, AQ_Z_STEP), 30)
        Gui.Selection.clearSelection()
        b, self._ap_where = self.click_ribbon("Cylinder")
        qtest().qWait(800)
        shank = math.pi * (AQ_SHANK[0] / 2) ** 2 * AQ_SHANK[1]
        self.ap_dialog("Cylinder", "Axis, Diameter, and Height", (("diameter", AQ_STEP[0]), ("height", AQ_STEP[1])),
                       "Unite", "Cylinder Ø0.387 x 0.0156: Arc/Ellipse/Sphere Center on the shank's top face, Unite",
                       "Diameter 9.8298 and Height 0.39624 typed",
                       shank + math.pi * (AQ_STEP[0] / 2) ** 2 * AQ_STEP[1], center=(AQ_Z_STEP, AQ_SHANK[0] / 4))
        self.shot("AQ1_cylinders.png")
        self.wait = 400

    def aq_sketch(self):
        tip = self.body().Tip
        top = self.face_of(tip, lambda f: abs(f.normalAt(0, 0).z - 1) < 1e-9 and abs(f.CenterOfMass.z - AQ_Z_HEAD)
                           < 1e-6)
        self.select_sub(tip, top)
        self._aq_top = top
        b, self._fs_where = self.click_ribbon("Sketch")
        self.wait = 1500

    def aq_polygon(self):
        self.wait_for("aq: sketch in edit", lambda: self.edited_sketch() is not None)
        sk = self.edited_sketch()
        if sk is None:
            self.step("Polygon: centre at the top circle's centre, 6 sides, Side Length 0.246",
                      f"{self._aq_top} selected + ribbon '{self._fs_where} > Sketch'", FAIL, "no sketch in edit")
            raise RuntimeError("no sketch; tutorial AQ cannot continue")
        self._aq_sk = sk
        on_face = abs(sk.getGlobalPlacement().Base.z - AQ_Z_HEAD) < 1e-6
        how, n, missing = self.fs_polygon(sk, AQ_HEX)
        self.step("Polygon: centre at the top circle's centre, 6 sides, Side Length 0.246, Rotation 0",
                  f"the step's top face ({self._aq_top}) selected + ribbon '{self._fs_where} > Sketch', {how}",
                  DIFFERS if n == 6 and not missing and on_face else FAIL,
                  f"{n} sides; corners {'all at the book hexagon (side 6.2484 mm, a corner on XC)' if not missing else f'missing {missing}'}; "
                  f"the sketch on the top face {on_face}, its origin the circle's centre. NX 12's Polygon is a curve "
                  "outside sketches; here it is drawn in a sketch on the face (NX 2212: Sketch > Polygon)")
        self.wait = 300

    def aq_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1200

    def aq_extrude(self):
        Gui.Selection.clearSelection()
        self._aq_bodies0 = len(self.ao_bodies())
        self._aq_pads = self.fs_names("PartDesign::Pad")
        self.fs_zoom((0, 0, AQ_Z_HEAD), 30)
        b, self._fs_where = self.click_ribbon("Extrude")
        self.wait = 1500

    def aq_extrude_section(self):
        how, ok = self.fs_extrude(self._aq_sk, AQ_HEX_H, "None")
        pad = self.fs_new_feature("PartDesign::Pad", self._aq_pads)
        want = hexagon_prism(AQ_HEX, AQ_Z_HEAD, AQ_HEX_H)
        got = pad.Shape if pad is not None else None
        bb = got.optimalBoundingBox(False, False) if got is not None else None
        good = ok and got is not None and abs(got.Volume - want.Volume) < 1e-6 * want.Volume and \
            abs(bb.ZMin - AQ_Z_HEAD) < 1e-6 and abs(bb.ZMax - AQ_Z_HEAD - AQ_HEX_H) < 1e-6 and \
            len(self.ao_bodies()) == self._aq_bodies0 + 1
        self._aq_head = self.fs_body_of(pad) if pad is not None else None
        self.step("Extrude the hexagon, End Distance 0.1876", f"ribbon '{self._fs_where} > Extrude', {how}",
                  SAME if good else FAIL,
                  f"volume {got.Volume:.2f} mm^3, expected {want.Volume:.2f}; z {bb.ZMin:.3f} to {bb.ZMax:.3f} mm; "
                  f"the hexagonal head is a body of its own ({len(self.ao_bodies())} bodies), as the book's later "
                  "Intersect with the head alone needs" if got is not None else f"OK {ok}; no Extrude")
        self.wait = 400

    def aq_wireframe(self):
        self.shot("AQ2_head.png")
        b, where = self.click_ribbon("Static Wireframe", tab="View")
        self._aq_wire = where
        self.fs_zoom((0, 0, AQ_Z_HEAD), 14)
        Gui.Selection.clearSelection()
        self._aq_cyls = self.fs_names("PartDesign::AdditiveCylinder")   # before the dialog adds its preview
        b, self._ap_where = self.click_ribbon("Cylinder")
        self.wait = 800

    def aq_inner(self):
        want = math.pi * (AQ_INNER[0] / 2) ** 2 * AQ_INNER[1]

        def check():
            c = self.fs_new_feature("PartDesign::AdditiveCylinder", self._aq_cyls)
            b = self.fs_body_of(c) if c is not None else None
            v = b.Shape.Volume if b is not None else 0.0
            self._aq_inner = b
            return (b is not None and abs(v - want) < 1e-6 * want and b not in (self.ao_bodies()[0], self._aq_head),
                    f"a body of its own, volume {v:.2f} mm^3, expected {want:.2f}; seen in Static Wireframe "
                    f"(View › '{self._aq_wire}'), the hexagon around it")
        self.ap_dialog("Cylinder", "Axis, Diameter, and Height", (("diameter", AQ_INNER[0]), ("height", AQ_INNER[1])),
                       "None", "Cylinder Ø0.387 x 0.1875 on top of the Ø0.387 cylinder",
                       "Diameter 9.8298 and Height 4.7625 typed", want, center=(AQ_Z_HEAD, AQ_STEP[0] / 2, True),
                       check=check)
        self.wait = 400

    def aq_sphere(self):
        Gui.Selection.clearSelection()
        self._aq_others = {b.Name: b.Shape.Volume for b in self.ao_bodies() if b is not self._aq_head}
        b, self._ap_where = self.click_ribbon("Sphere")
        self.wait = 800

    def aq_sphere_dialog(self):
        import Part
        head = hexagon_prism(AQ_HEX, AQ_Z_HEAD, AQ_HEX_H).common(
            Part.makeSphere(AQ_SPHERE / 2, App.Vector(0, 0, AQ_Z_HEAD)))
        others = self._aq_others             # measured before the dialog made its preview

        def check():
            v = self._aq_head.Shape.Volume
            changed = [b.Name for b in self.ao_bodies() if b.Name in others
                       and abs(b.Shape.Volume - others[b.Name]) > 1e-6]
            return (abs(v - head.Volume) < 1e-6 * head.Volume and not changed and len(self._aq_head.Shape.Solids) == 1,
                    f"the head {v:.2f} mm^3, expected {head.Volume:.2f} (hexagon within the sphere); the other "
                    f"bodies {'unchanged' if not changed else f'changed: {changed}'}")
        self.ap_dialog("Sphere", "Center Point and Diameter", (("diameter", AQ_SPHERE),), "Intersect",
                       "Sphere: centre at the bottom of the last cylinder, Diameter 0.55, Intersect, Target the "
                       "hexagonal head, OK", "Diameter 13.97 typed", head.Volume,
                       center=(AQ_Z_HEAD, AQ_INNER[0] / 2, True), target=self._aq_head, check=check)
        self.click_ribbon("Shaded with Edges", tab="View")
        self.key("Ctrl+F")
        self.wait = 1200

    def aq_check(self):
        from . import geomcheck
        shapes = [b.Shape for b in self.ao_bodies() if b.ViewObject.Visibility and not b.Shape.isNull()]
        got = shapes[0].fuse(shapes[1:]).removeSplitter() if shapes else None
        ok, detail = geomcheck.compare(got, aq_reference())
        self.step("The screw before its thread: shank, head and the cylinder in it",
                  f"the {len(shapes)} bodies together, compared with the book's dimensions", SAME if ok else FAIL,
                  detail)
        self.shot("AQ3_screw.png")
        self.wait = 300

    def aq_thread(self):
        shank = self.ao_bodies()[0]
        self._aq_shank_volume = shank.Shape.Volume
        Gui.Selection.clearSelection()
        b, self._fs_where = self.click_ribbon("Thread")
        self.wait = 1000

    def aq_thread_dialog(self):
        from . import thread_core, thread_ui
        from .primitive_ui import mm as primitive_ui_mm
        from .smoke_primitives import choose, field, ok
        from .tutorial import qtest
        p = thread_ui.current()
        label = "Thread: Detailed, Right Hand, the bolt's shank, the values it shows kept, OK"
        if p is None:
            self.step(label, f"ribbon '{self._fs_where} > Thread'", FAIL, "the Thread dialog did not open")
            return
        kind = choose(p, "threadType", "Detailed")
        hand = choose(p, "rotation", "Right Hand")
        # MB1 on the shank's side where it faces the camera, near its lower end: the thread starts at the end
        # nearest the pick
        d = self.view().getViewDirection()
        u = App.Vector(-d.x, -d.y, 0).normalize()
        at = self.ap_screen(tuple(u * (AQ_SHANK[0] / 2 * 0.999) + App.Vector(0, 0, 5)))
        self.mb1_click(at)
        qtest().qWait(600)
        vals = {n: primitive_ui_mm(field(p, n)) for n in ("majorDiameter", "minorDiameter", "pitch", "angle", "length")}
        table = field(p, "threadTable", QtWidgets.QComboBox)
        callout = table.currentText() if table is not None else None
        pressed = ok()
        self.wait_for("the thread built", lambda: not Gui.Control.activeDialog(), timeout_ms=15000)
        App.ActiveDocument.recompute()
        last = dict(thread_ui.HISTORY[-1]) if thread_ui.HISTORY else {}
        shank = self.ao_bodies()[0]
        removed = None
        try:
            removed = thread_core.removed_volume(
                thread_core.profile(vals["majorDiameter"], vals["minorDiameter"], vals["pitch"], vals["angle"],
                                    surface=AQ_SHANK[0] / 2),
                vals["length"], vals["pitch"], AQ_SHANK[0] / 2)
        except Exception as e:
            self.info["AQ thread oracle"] = str(e)
        got = self._aq_shank_volume - shank.Shape.Volume
        good = pressed and removed is not None and abs(got - removed) < 1e-3 * removed and \
            len(shank.Shape.Solids) == 1 and callout == "1/4-20 UNC" and last.get("outcome") == "committed"
        self.step(label, f"ribbon '{self._fs_where} > Thread', Type '{kind}', Rotation '{hand}', MB1 on the shank, "
                  "OK", SAME if good else FAIL,
                  f"the dialog filled in {callout}: major {vals['majorDiameter']:g}, minor {vals['minorDiameter']:g}, "
                  f"pitch {vals['pitch']:g}, angle {vals['angle']:g}°, length {vals['length']:g} mm; the thread took "
                  f"{got:.3f} mm^3 from the shank, a helical sweep of that profile takes {removed:.3f}; "
                  f"{len(shank.Shape.Solids)} solid; undo {last.get('undo')}" if removed is not None else
                  f"OK pressed {pressed}; values {vals}; callout {callout}; {last}")
        self.wait = 400

    def aq_save_end(self):
        outcome, how, detail, path = self.save_ctrl_s("Impeller_hexa-bolt.FCStd")
        self.step("Save the model", how, outcome, detail)
        self.wait = 300

    def aq_fit(self):
        self.fit()

    def aq_show(self):
        self.show("AQ_hexagonal_screw")


# ================================================================== AS, AT: Arbor Press L-Bar and Rack (4.7.3, 4.7.4)
# The book (pp. 83-92), inches. The L-bar: a Block 65 x 65 x 285 at the origin; a Block 182 x 65 x 85 at the origin,
# moved 200 along ZC (Move Object, Distance); from it a hole Ø35 along YC at (130, -5, 242), 100 long, and a bore Ø66
# at (130, 22.5, 242), 20 long, subtracted; a Block 25 x 20 x 150 at (157, 22.5, 180) subtracted from it with Combine
# > Subtract; the two blocks united; Edge Blend R60 on the outer corner and R30 on the inner corner (the figures, p. 86);
# four Cylinders Ø8 x 20 along XC subtracted; a Block 60 x 20 x 66 at (130, 22.5, 209.5) subtracted.
# The rack: a Rectangle (0, 0) to (240, 25) extruded 0 to 20; a rectangular Pocket on the top face, Length 35 across the
# bar, Width 6, Depth 5.034, Taper 14.5° (the figure, p. 89), its centre lines 37.8 from the end and 10 from the side;
# Pattern Feature along XC, 19 at a pitch of 9.4; a Cylinder Ø10 x 20 along -XC from the centre of the far end face
# (Between Two Points, two opposite corners), subtracted.
AS_B1 = (65, 65, 285)
AS_B2 = (182, 65, 85)
AS_LIFT = 200
AS_HOLE = ((130, -5, 242), 35, 100)
AS_BORE = ((130, 22.5, 242), 66, 20)
AS_SLOT = ((157, 22.5, 180), (25, 20, 150))
AS_R_OUTER, AS_R_INNER = 60, 30
AS_PINS = [(162, 11.25, 210), (162, 11.25, 275), (162, 53.75, 210), (162, 53.75, 275)]
AS_PIN = (8, 20)
AS_CUT = ((130, 22.5, 209.5), (60, 20, 66))
AT_BAR = (240, 25, 20)
AT_POCKET = (37.8, 10, 35, 6, 5.034, 14.5)          # centre x, centre y, length (Y), width (X), depth, taper
AT_COUNT, AT_PITCH = 19, 9.4
AT_HOLE = ((240, 12.5, 10), 10, 20)


def _v(p):
    return App.Vector(*[c * IN for c in p])


def as_edge(shape, x, z):
    """The straight edge of shape along YC at (x, z), inches."""
    for e in shape.Edges:
        b = e.BoundBox
        if b.XLength < 1e-6 and b.ZLength < 1e-6 and b.YLength > 1e-6 and abs(b.XMin - x * IN) < 1e-6 \
                and abs(b.ZMin - z * IN) < 1e-6:
            return e
    return None


def as_stages():
    """The L-bar as the book builds it, stage by stage (Part API, mm)."""
    import Part
    y = App.Vector(0, 1, 0)
    s = {"b1": Part.makeBox(*[c * IN for c in AS_B1]), "b2 at the origin": Part.makeBox(*[c * IN for c in AS_B2]),
         "slot block": Part.makeBox(*[c * IN for c in AS_SLOT[1]], _v(AS_SLOT[0]))}
    b2 = Part.makeBox(*[c * IN for c in AS_B2], App.Vector(0, 0, AS_LIFT * IN))
    s["b2"] = b2
    b2 = b2.cut(Part.makeCylinder(AS_HOLE[1] / 2 * IN, AS_HOLE[2] * IN, _v(AS_HOLE[0]), y))
    s["hole"] = b2
    b2 = b2.cut(Part.makeCylinder(AS_BORE[1] / 2 * IN, AS_BORE[2] * IN, _v(AS_BORE[0]), y))
    s["bore"] = b2
    b2 = b2.cut(Part.makeBox(*[c * IN for c in AS_SLOT[1]], _v(AS_SLOT[0])))
    s["slot"] = b2
    u = s["b1"].fuse(b2).removeSplitter()
    s["unite"] = u
    u = u.makeFillet(AS_R_OUTER * IN, [as_edge(u, 0, AS_B1[2])])
    s["outer"] = u
    u = u.makeFillet(AS_R_INNER * IN, [as_edge(u, AS_B1[0], AS_LIFT)])
    s["inner"] = u
    for k, p in enumerate(AS_PINS):
        u = u.cut(Part.makeCylinder(AS_PIN[0] / 2 * IN, AS_PIN[1] * IN, _v(p), App.Vector(1, 0, 0)))
        s[f"pin{k + 1}"] = u
    s["final"] = u.cut(Part.makeBox(*[c * IN for c in AS_CUT[1]], _v(AS_CUT[0]))).removeSplitter()
    return s


def at_slot(dx=0.0):
    """One tooth space: the pocket's rectangle on the top face, tapered inward down to its floor."""
    import Part
    cx, cy, length, width, depth, taper = AT_POCKET
    t = depth * math.tan(math.radians(taper))
    z1, z0 = AT_BAR[2], AT_BAR[2] - depth

    def rect(inset, z):
        x0, x1 = cx + dx - width / 2 + inset, cx + dx + width / 2 - inset
        y0, y1 = cy - length / 2 + inset, cy + length / 2 - inset
        return Part.makePolygon([_v((x0, y0, z)), _v((x1, y0, z)), _v((x1, y1, z)), _v((x0, y1, z)),
                                 _v((x0, y0, z))])
    return Part.makeLoft([rect(0, z1), rect(t, z0)], True, True)


def at_stages():
    import Part
    s = {"bar": Part.makeBox(*[c * IN for c in AT_BAR])}
    s["pocket"] = s["bar"].cut(at_slot())
    rack = s["bar"]
    for k in range(AT_COUNT):
        rack = rack.cut(at_slot(k * AT_PITCH))
    s["pattern"] = rack
    s["final"] = rack.cut(Part.makeCylinder(AT_HOLE[1] / 2 * IN, AT_HOLE[2] * IN, _v(AT_HOLE[0]),
                                            App.Vector(-1, 0, 0)))
    return s


class MstArborPressTutorials:
    """Mixin for tutorial.Replay: tutorials AS (L-bar) and AT (rack)."""

    def AS_STEPS(self):
        return [self.p_modeling, self.as_new, self.as_save, self.as_block1, self.as_block2, self.as_move,
                self.as_move_dialog, self.as_hole, self.as_bore, self.as_slot, self.as_subtract,
                self.as_subtract_dialog, self.as_unite, self.as_unite_dialog, self.as_outer, self.as_outer_dialog,
                self.as_inner, self.as_inner_dialog, self.as_pins, self.as_cut, self.as_check, self.as_fit,
                self.as_show]

    def AT_STEPS(self):
        return [self.p_modeling, self.at_new, self.at_save, self.at_plane, self.at_rectangle, self.at_finish,
                self.at_extrude, self.at_extrude_section, self.at_pocket_sketch, self.at_pocket_rectangle,
                self.at_pocket_finish, self.at_pocket, self.at_pocket_section, self.at_pattern,
                self.at_pattern_dialog, self.at_hole, self.at_check, self.at_fit, self.at_show]

    # ------------------------------------------------------------- helpers
    def as_body(self, k):
        bodies = self.ao_bodies()
        return bodies[k] if len(bodies) > k else None

    def as_vol(self, body, stage, label, how):
        """A step whose check is a body's shape against a stage of the book's L-bar."""
        from . import geomcheck
        ok, detail = geomcheck.compare(body.Shape if body is not None else None, self._as[stage])
        self.step(label, how, SAME if ok else FAIL, detail)
        return ok

    def as_primitive(self, command, kind, dims, boolean, label, typed, body, stage, axis="ZC", target=None):
        """Ribbon command, its dialog filled with typed values, OK; the body compared with the stage."""
        from . import geomcheck
        from .tutorial import qtest
        Gui.Selection.clearSelection()
        b, self._ap_where = self.click_ribbon(command)
        qtest().qWait(900)

        def check():
            got = self.as_body(body) if isinstance(body, int) else body()
            ok, detail = geomcheck.compare(got.Shape if got is not None else None, self._as[stage])
            return ok, f"{got.Label if got is not None else 'no body'}: {detail}"
        names = ", ".join(f"{n} {v:g}" for n, v in dims)
        self.ap_dialog(command, kind, [(n, v * IN) for n, v in dims], boolean, label,
                       f"{names} (in) typed in mm", 0, typed=tuple(c * IN for c in typed), axis=axis, target=target,
                       check=check)

    # ================================================================ AS: the L-bar
    def as_new(self):
        self.tutorial = "AS: Arbor Press L-Bar (NX 12 for Engineering Design, 4.7.3; book in inches, typed in mm)"
        self._as = as_stages()
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def as_save(self):
        new = set(App.listDocuments()) - self._docs_before
        self.step("Create a new file (Arborpress_L-bar)", "Ctrl+N, Model template",
                  SAME if new and self.body() else FAIL, f"new document {sorted(new)}")
        self.units_step()
        outcome, how, detail, path = self.save_ctrl_s("Arborpress_L-bar.FCStd")
        self.step("Save it as Arborpress_L-bar", how, outcome, detail)
        self.wait = 300

    def as_block1(self):
        self.as_primitive("Block", "Origin and Edge Lengths", (("length", 65), ("width", 65), ("height", 285)),
                          "None", "Block 65 x 65 x 285 at the origin", (0, 0, 0), 0, "b1")
        self.key("Ctrl+F")
        self.key("Home")
        self.wait = 1200

    def as_block2(self):
        self.as_primitive("Block", "Origin and Edge Lengths", (("length", 182), ("width", 65), ("height", 85)),
                          "None", "A second Block 182 x 65 x 85, also at the origin", (0, 0, 0), 1,
                          "b2 at the origin")
        self.wait = 400

    def as_move(self):
        body = self.as_body(1)
        block = next(o for o in body.Group if o.TypeId == "PartDesign::AdditiveBox")
        Gui.Selection.clearSelection()
        # the Block itself, as a click on it in the Part Navigator selects it (through its Body, as a sub-object,
        # the Placement dialog moved nothing: measured)
        Gui.Selection.addSelection(App.ActiveDocument.Name, block.Name)
        self._as_moved = body
        # NX-Style's Move Object (Ctrl+T) is FreeCAD's dragger, without a typed Distance yet: FreeCAD's Placement
        # dialog (Menu > Edit > Placement) moves the block by a typed distance. The block, not its Body: a Boolean
        # with a moved Body as its target ignores the Body's placement (measured, FreeCAD 1.1.4)
        Gui.runCommand("Std_Placement")
        self.wait = 1500

    def as_move_dialog(self):
        from . import geomcheck
        self.wait_dialog("as_move_dialog")
        self.info["AS move widgets"] = self.task_widgets()
        sel = [(s.ObjectName, list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx("", 0)]
        z = self.set_quantity("zPos", AS_LIFT * IN)
        self.mb2_click()
        App.ActiveDocument.recompute()
        body = self._as_moved
        block = next(o for o in body.Group if o.TypeId == "PartDesign::AdditiveBox")
        self.info["AS move result"] = {"selection": sel, "body placement": str(body.Placement),
                                       "block placement": str(block.Placement),
                                       "block map mode": getattr(block, "MapMode", None),
                                       "block support": str(getattr(block, "AttachmentSupport", None)),
                                       "offset": str(getattr(block, "AttachmentOffset", None))}
        ok, detail = geomcheck.compare(body.Shape if body is not None else None, self._as["b2"])
        self.step("Edit > Move Object: the second block, Distance 200 along ZC, Move Original, OK",
                  f"the Block selected (Part Navigator), Menu > Edit > Placement, '{z}' = 5080 mm, MB2 = OK",
                  DIFFERS if ok else FAIL, f"{detail}. NX-Style's Move Object (Ctrl+T) has no Distance motion yet "
                  "(it is being added); FreeCAD's Placement dialog moves the block by the typed distance. The block "
                  "moves inside its body: FreeCAD's Unite / Subtract ignores a moved target body's placement")
        self.wait = 400

    def as_hole(self):
        self.as_primitive("Cylinder", "Axis, Diameter, and Height", (("diameter", 35), ("height", 100)),
                          "Subtract", "Cylinder along YC at (130, -5, 242), Ø35 x 100, Subtract from the top block",
                          AS_HOLE[0], 1, "hole", axis="YC", target=self.as_body(1))
        self.wait = 400

    def as_bore(self):
        self.as_primitive("Cylinder", "Axis, Diameter, and Height", (("diameter", 66), ("height", 20)),
                          "Subtract", "Cylinder along YC at (130, 22.5, 242), Ø66 x 20, Subtract from the same block",
                          AS_BORE[0], 1, "bore", axis="YC", target=self.as_body(1))
        self.wait = 400

    def as_slot(self):
        self._as_blocks = len(self.ao_bodies())
        self.as_primitive("Block", "Origin and Edge Lengths", (("length", 25), ("width", 20), ("height", 150)),
                          "None", "Block 25 x 20 x 150 at (157, 22.5, 180)", AS_SLOT[0],
                          lambda: self.ao_bodies()[-1] if len(self.ao_bodies()) > self._as_blocks else None,
                          "slot block")
        self.wait = 400

    def as_boolean(self, target, tool, kind):
        doc = App.ActiveDocument
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", target)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, tool.Name)
        b, where = self.click_ribbon("Unite / Subtract")
        self._as_where = where
        self.wait = 1500

    def as_boolean_dialog(self, kind, label, target, stage):
        self.wait_dialog("as_boolean_dialog")
        self.info[f"AS boolean widgets {kind}"] = self.task_widgets()
        picked = self.set_combo("comboType", kind) or self.set_combo("type", kind)
        self.mb2_click()
        App.ActiveDocument.recompute()
        self.as_vol(target, stage, label, f"the target made the work body, the tool selected (Part Navigator) + "
                    f"ribbon '{self._as_where} > Unite / Subtract', type '{picked}', MB2 = OK")

    def as_subtract(self):
        self.as_boolean(self.as_body(1), self.as_body(2), "Cut")

    def as_subtract_dialog(self):
        self.as_boolean_dialog("Cut", "Combine > Subtract: Target the block with the two holes, Tool the new block",
                               self.as_body(1), "slot")
        self.wait = 400

    def as_unite(self):
        self.as_boolean(self.as_body(0), self.as_body(1), "Fuse")

    def as_unite_dialog(self):
        self.as_boolean_dialog("Fuse", "Combine > Unite: the two blocks", self.as_body(0), "unite")
        self.key("Ctrl+F")
        self.wait = 800

    def as_blend(self, x, z):
        tip = self.as_body(0).Tip
        edge = as_edge(tip.Shape, x, z)
        sub = next((f"Edge{i}" for i, e in enumerate(tip.Shape.Edges, 1) if edge is not None and e.isSame(edge)),
                   None)
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.as_body(0))
        self.select_subs(tip, [sub] if sub else [])
        b, self._as_where = self.click_ribbon("Edge Blend")
        self._as_edge = sub
        self.wait = 1500

    def as_blend_dialog(self, radius, label, stage):
        self.wait_dialog("as_blend_dialog")
        w = self._field(QtWidgets.QAbstractSpinBox, "radius")
        if w is not None:
            self.info.setdefault("AS blend radius field", []).append(
                {"name": w.objectName(), "maximum": w.property("maximum"), "minimum": w.property("minimum"),
                 "text": w.text(), "unit": str(w.property("unit"))})
        field = self.set_quantity("radius", radius * IN)
        self.mb2_click()
        App.ActiveDocument.recompute()
        self.as_vol(self.as_body(0), stage, label, f"{self._as_edge} selected + ribbon '{self._as_where} > Edge "
                    f"Blend', '{field}' = {radius * IN:g} mm, MB2 = OK")
        self.wait = 400

    def as_outer(self):
        self.as_blend(0, AS_B1[2])

    def as_outer_dialog(self):
        self.as_blend_dialog(AS_R_OUTER, "Edge Blend, Radius 60: the outer corner where the blocks meet", "outer")

    def as_inner(self):
        self.as_blend(AS_B1[0], AS_LIFT)

    def as_inner_dialog(self):
        self.as_blend_dialog(AS_R_INNER, "Edge Blend, Radius 30: the inner corner", "inner")

    def as_pins(self):
        for k, p in enumerate(AS_PINS):
            self.as_primitive("Cylinder", "Axis, Diameter, and Height", (("diameter", 8), ("height", 20)),
                              "Subtract", f"Cylinder #{k + 1} along XC at ({p[0]:g}, {p[1]:g}, {p[2]:g}), Ø8 x 20, "
                              "Subtract", p, 0, f"pin{k + 1}", axis="XC")
        self.wait = 400

    def as_cut(self):
        self.as_primitive("Block", "Origin and Edge Lengths", (("length", 60), ("width", 20), ("height", 66)),
                          "Subtract", "Block 60 x 20 x 66 at (130, 22.5, 209.5), Subtract from the top block",
                          AS_CUT[0], 0, "final")
        self.key("Ctrl+F")
        self.wait = 1000

    def as_check(self):
        self.as_vol(self.as_body(0), "final", "The L-bar", "compared with the book's dimensions built by the Part "
                    "API")
        outcome, how, detail, path = self.save_ctrl_s("Arborpress_L-bar.FCStd")
        self.step("Save and close the file", how, outcome, detail)
        self.wait = 300

    def as_fit(self):
        self.fit()

    def as_show(self):
        self.show("AS_arborpress_lbar")

    # ================================================================ AT: the rack
    def at_new(self):
        self.tutorial = "AT: Arbor Press Rack (NX 12 for Engineering Design, 4.7.4; book in inches, typed in mm)"
        self._at = at_stages()
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def at_save(self):
        new = set(App.listDocuments()) - self._docs_before
        self.step("Create a new file (Arborpress_rack)", "Ctrl+N, Model template",
                  SAME if new and self.body() else FAIL, f"new document {sorted(new)}")
        self.units_step()
        outcome, how, detail, path = self.save_ctrl_s("Arborpress_rack.FCStd")
        self.step("Save it as Arborpress_rack", how, outcome, detail)
        self.key("End")
        Gui.Selection.clearSelection()
        b, self._fs_where = self.click_ribbon("Sketch")
        self.wait = 1500

    def at_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.wait_for("at: sketch in edit", lambda: self.edited_sketch() is not None)
        self._at_sk = self.edited_sketch()
        if self._at_sk is None:
            self.step("Rectangle: a sketch on the XC-YC plane", f"ribbon '{self._fs_where} > Sketch'", FAIL,
                      f"no sketch in edit (plane row {picked})")
            raise RuntimeError("no sketch; tutorial AT cannot continue")
        self._at_plane = picked
        self.wait = 800

    def at_rectangle(self):
        how, n, missing = self.fs_rectangle(self._at_sk, (0, 0), (AT_BAR[0] * IN, AT_BAR[1] * IN))
        self.step("Rectangle: corner 1 (0, 0, 0), corner 2 (240, 25, 0)",
                  f"ribbon '{self._fs_where} > Sketch' on '{self._at_plane}', {how}",
                  DIFFERS if n == 4 and not missing else FAIL,
                  f"{n} lines; corners {'all at the book' if not missing else f'missing {missing}'}. NX 12's "
                  "Insert > Curve > Rectangle is a curve outside sketches; NX-Style draws it in a sketch (NX 2212: "
                  "Sketch > Rectangle)")
        self.wait = 300

    def at_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1200

    def at_extrude(self):
        Gui.Selection.clearSelection()
        self.key("Ctrl+F")
        b, self._fs_where = self.click_ribbon("Extrude")
        self.wait = 1500

    def at_extrude_section(self):
        from . import geomcheck
        how, ok = self.fs_extrude(self._at_sk, AT_BAR[2] * IN, "None")
        good, detail = geomcheck.compare(self.body().Shape, self._at["bar"])
        self.step("Extrude the rectangle along ZC, Start 0, End 20", f"ribbon '{self._fs_where} > Extrude', {how} "
                  f"{'clicked' if ok else 'unavailable'}", SAME if good else FAIL, detail)
        self.wait = 400

    def at_pocket_sketch(self):
        tip = self.body().Tip
        top = self.face_of(tip, lambda f: abs(f.normalAt(0, 0).z - 1) < 1e-9
                           and abs(f.CenterOfMass.z - AT_BAR[2] * IN) < 1e-6)
        self.select_sub(tip, top)
        self._at_top = top
        b, self._fs_where = self.click_ribbon("Sketch")
        self.wait = 1500

    def at_pocket_rectangle(self):
        self.wait_for("at: pocket sketch in edit", lambda: self.edited_sketch() is not None)
        sk = self.edited_sketch()
        if sk is None:
            self.step("Pocket: Rectangular, on the top face", f"{self._at_top} + Sketch", FAIL, "no sketch in edit")
            raise RuntimeError("no sketch; tutorial AT cannot continue")
        self._at_psk = sk
        cx, cy, length, width = AT_POCKET[:4]
        c1 = ((cx - width / 2) * IN, (cy - length / 2) * IN)
        c2 = ((cx + width / 2) * IN, (cy + length / 2) * IN)
        on_face = abs(sk.getGlobalPlacement().Base.z - AT_BAR[2] * IN) < 1e-6
        how, n, missing = self.fs_rectangle(sk, c1, c2)
        self.step("Pocket: Rectangular, on the top face; Length 35, Width 6; Perpendicular 37.8 from the end and 10 "
                  "from the side", f"the top face ({self._at_top}) selected + ribbon '{self._fs_where} > Sketch', "
                  f"{how}", DIFFERS if n == 4 and not missing and on_face else FAIL,
                  f"{n} lines, corners {'as the book places the pocket' if not missing else f'missing {missing}'}; "
                  f"on the top face {on_face}. NX 12's Pocket is a legacy feature (positioned with Perpendicular); "
                  "NX 2212 cuts it with Extrude (Subtract) from a sketched rectangle, whose corners are typed from "
                  "the pocket's size and position")
        self.wait = 300

    def at_pocket_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1200

    def at_pocket(self):
        Gui.Selection.clearSelection()
        self._at_pockets = self.fs_names("PartDesign::Pocket")
        b, self._fs_where = self.click_ribbon("Extrude (Subtract)")
        self.wait = 1500

    def at_pocket_section(self):
        from . import geomcheck
        depth, taper = AT_POCKET[4], AT_POCKET[5]
        how, ok = self.fs_extrude(self._at_psk, depth * IN, "Subtract", taper=-taper)
        good, detail = geomcheck.compare(self.body().Shape, self._at["pocket"])
        self.step("Depth 5.034, Taper Angle 14.5, OK", f"ribbon '{self._fs_where} > Extrude (Subtract)', {how}",
                  SAME if good else FAIL, f"{detail}; FreeCAD's taper is negative for walls that close in with depth, "
                  "as NX's pocket's do")
        self._at_pocket = self.fs_new_feature("PartDesign::Pocket", self._at_pockets)
        self.wait = 400

    def at_pattern(self):
        self.select_sub(self._at_pocket, "")
        b, self._fs_where = self.click_ribbon("Pattern Feature")
        self.wait = 1500

    def at_pattern_dialog(self):
        from . import geomcheck
        self.wait_dialog("at_pattern_dialog")
        self.wait_for("at: direction panels", lambda: bool(self.pattern_dirs())
                      and self.newest("PartDesign::LinearPattern") is not None, 10000)
        panels = self.pattern_dirs()
        d1 = self.set_direction(panels[0], "x axis", AT_COUNT, AT_PITCH) if panels else {}
        self.mb2_click()
        App.ActiveDocument.recompute()
        good, detail = geomcheck.compare(self.body().Shape, self._at["pattern"])
        self.step("Pattern Feature: the pocket, Linear, XC, Count 19, Pitch Distance 9.4, OK",
                  f"the Extrude (Subtract) selected + ribbon '{self._fs_where} > Pattern Feature', {d1}, MB2 = OK",
                  SAME if good else FAIL, detail)
        self.wait = 600

    def at_hole(self):
        from . import geomcheck
        from .smoke_primitives import choose
        from .tutorial import qtest
        self.key("Home")
        self.fs_zoom(tuple(c * IN for c in AT_HOLE[0]), AT_BAR[1] * IN * 3)

        def between(p):
            p.activate("origin")
            choose(p, "originPointType", "Between Two Points")
            # on an edge near each corner: Between Two Points takes an edge's end nearest the pick
            picks = []
            for near in ((AT_BAR[0], 0, AT_BAR[2] * 0.12), (AT_BAR[0], AT_BAR[1] * 0.88, AT_BAR[2])):
                at = self.ap_screen(tuple(c * IN for c in near))
                self.mb1_click(at)
                qtest().qWait(500)
                picks.append((at.x(), at.y()))
            return (f"'Between Two Points', MB1 near the end face's corners (240, 0, 0) and (240, 25, 20) at "
                    f"pixels {picks}: {p.steps['origin'].status.text()}", tuple(c * IN for c in AT_HOLE[0]))
        Gui.Selection.clearSelection()
        b, self._ap_where = self.click_ribbon("Cylinder")
        qtest().qWait(900)

        def check():
            ok, detail = geomcheck.compare(self.body().Shape, self._at["final"])
            return ok, detail
        self.ap_dialog("Cylinder", "Axis, Diameter, and Height", (("diameter", AT_HOLE[1] * IN),
                                                                  ("height", AT_HOLE[2] * IN)), "Subtract",
                       "Cylinder along -XC at the end face's centre (Between Two Points), Ø10 x 20, Subtract",
                       "Diameter 254 and Height 508 typed", 0, center=between, axis="-XC", check=check)
        self.key("Ctrl+F")
        self.wait = 1000

    def at_check(self):
        from . import geomcheck
        ok, detail = geomcheck.compare(self.body().Shape, self._at["final"])
        self.step("The rack", "compared with the book's dimensions built by the Part API", SAME if ok else FAIL,
                  detail)
        outcome, how, detail, path = self.save_ctrl_s("Arborpress_rack.FCStd")
        self.step("Save and close the model", how, outcome, detail)
        self.wait = 300

    def at_fit(self):
        self.fit()

    def at_show(self):
        self.show("AT_arborpress_rack")
