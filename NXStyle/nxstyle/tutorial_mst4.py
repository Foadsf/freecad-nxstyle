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

        def rec(e):
            a, b = e.FirstParameter, e.LastParameter
            return tuple(tuple(e.valueAt(t)) for t in (a, b, (a + b) / 2))
        geo = {i: rec(g.toShape()) for i, g in enumerate(sk.Geometry) if "Point" not in g.TypeId}
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
        """Pick curve ref of the sketch as a user does: MB1 where it is the only thing under the pointer, else its
        row in QuickPick (a solid's face or edge, or a curve on top of it, lies there). Returns the route."""
        from . import selection_filter as sf
        from .smoke_section import Run
        from .tutorial import qtest
        sk, g = self._ao_sk, self._ao_map[ref]
        e = sk.Geometry[g].toShape()
        t = e.FirstParameter + AO_ALONG.get(ref, 0.5) * (e.LastParameter - e.FirstParameter)
        view = self.view()
        coin = view.getPointOnViewport(sk.getGlobalPlacement().multVec(e.valueAt(t)))
        rows = sf.rows_at(view, coin)
        name = self._ao_names[g]
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
            if not self.wait_for(f"the click took {name}", lambda: self.ao_taken(name), timeout_ms=1500):
                route = "QuickPick (the click was not taken)"
                sf.select_row(want, clear=False)
        elif want is not None:
            route = "QuickPick"
            sf.select_row(want, clear=False)
        else:
            route = f"missing ({[r['label'] for r in rows[:3]]})"
        qtest().qWait(QtWidgets.QApplication.doubleClickInterval() + 80)   # not a double click: a whole object
        return route

    def ao_taken(self, name):
        """Curve name of the sketch is in the section (or, while FreeCAD's plane list still shows, selected)."""
        s = self.ao_ctl().session
        if s is not None and s.edges and name in s.edges:
            return True
        sk = self._ao_sk
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

    def ap_rim(self, z, r):
        """The point of the circle (centre on ZC at height z, radius r) nearest the viewer: on the edge's outline."""
        d = self.view().getViewDirection()
        u = App.Vector(-d.x, -d.y, 0)
        u = u.normalize() if u.Length > 1e-9 else App.Vector(1, 0, 0)
        return (r * u.x, r * u.y, z)

    def ap_pick_center(self, p, z, r):
        """Specify Point with Arc/Ellipse/Sphere Center: MB1 on the circular edge (centre (0, 0, z), radius r).
        Returns (point type, the point in XC/YC/ZC, the step's status, the pick in the window)."""
        from .smoke_primitives import choose
        from .tutorial import qtest
        p.activate("origin")
        kind = choose(p, "originPointType", "Arc/Ellipse/Sphere Center")
        rim = self.ap_rim(z, r)
        at = self.ap_screen(rim)
        self.mb1_click(at)
        qtest().qWait(400)
        return kind, p.steps["origin"].point(), p.steps["origin"].status.text(), (at.x(), at.y())

    def ap_dialog(self, command, kind, dims, boolean, label, how_extra, want, center=None):
        """Fill the Cylinder or Cone dialog the way the book does, press OK, and check the body's volume."""
        from . import primitive_ui
        from .smoke_primitives import choose, field, ok
        p = primitive_ui.current()
        if p is None:
            self.step(label, f"ribbon '{command}'", FAIL, f"the {command} dialog did not open")
            raise RuntimeError(f"no {command} dialog; tutorial AP cannot continue")
        typ = choose(p, "nxType", kind)
        vector = choose(p, "nxVector", "ZC")
        if center is None:
            pick = None
            choose(p, "originPointType", "Inferred Point")
            for name in ("originXC", "originYC", "originZC"):
                self.type_into(field(p, name), 0)
            got = p.steps["origin"].point()
        else:
            ptype, got, status, at = self.ap_pick_center(p, *center)
            pick = f"'{ptype}', MB1 on the edge at pixel {at}: {status}"
        for name, v in dims:
            self.type_into(field(p, name), v)
        mode = choose(p, "nxBoolean", boolean)
        target = p.steps["body"].chosen()
        pressed = ok()
        where = (0, 0, 0) if center is None else (0, 0, center[0])
        at_point = got is not None and all(abs(a - b) < 1e-6 for a, b in zip(got, where))
        undo = App.ActiveDocument.UndoNames[:1]
        how = (f"ribbon '{self._ap_where}', Type '{typ}', Specify Vector '{vector}', "
               + (pick if pick else "XC/YC/ZC 0 typed") + f", {how_extra}, Boolean '{mode}', OK")
        if not (pressed and at_point and undo == [command]):
            self.step(label, how, FAIL, f"OK pressed {pressed}; point {got}, wanted {where}; target {target}; "
                      f"undo {App.ActiveDocument.UndoNames[:2]}")
            return False
        return self.check_volume(label, how, want, f"; origin {tuple(round(c, 6) for c in got)}; one undo step "
                                 f"{undo}" + (f"; united with {target}" if boolean == "Unite" else ""))

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
