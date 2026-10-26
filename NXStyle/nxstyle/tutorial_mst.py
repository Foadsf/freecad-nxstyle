# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercises from Leu, Tao, Ghazanfari and Kolan, NX 12 for Engineering Design (Missouri S&T), ch. 3.5.

  AF  3.5.1 Arbor Press Base: Sketch on XC-YC -> Profile (Z), lines and a tangent arc -> geometric
      constraints (centre of the arc on both axes, Equal, Collinear, Tangent) -> dimensions, biggest first
      -> fully constrained -> Finish -> select the sketch, Extrude 60 -> save

The sketch is drawn roughly, as the book says, and the constraints and dimensions bring it to size. The
sizes are the book's final dimension figure (p. 43): width 130, height 190.94, the outer verticals 125, the
top 95 with a 65 x 65 notch, a slot 40 wide ending in a semicircle whose centre is the origin, 35 above the
bottom edge. The solid is compared with the same solid made with the Part API (nxstyle/geomcheck.py).
"""

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtWidgets

SAME, DIFFERS, MISSING, FAIL = "same", "differs", "missing", "FAILED"

# the profile as drawn, roughly (sketch mm), in the book's order: from the bottom left, anticlockwise
# through the slot and its arc, up the right side, through the notch, down the left side
AF_ROUGH = [(-60, -40), (-18, -40), (-18, -5), (22, -5), (22, -40), (62, -40), (62, 85), (45, 150), (30, 150),
            (30, 95), (-33, 95), (-33, 150), (-48, 150), (-60, 85), (-60, -40)]
AF_ARC = 2                       # the third curve is the arc; the others are lines
AF_HORIZONTAL = (0, 4, 7, 9, 11)  # the lines Profile should infer Horizontal on
AF_VERTICAL = (1, 3, 5, 8, 10, 13)  # ... and Vertical; 6 and 12 are the slanted ones
AF_DEPTH = 60.0


def af_outline():
    """The finished profile: (points of the lines, the arc's start, middle, end)."""
    top, slot = -35 + 190.94, -35 + 190.94 - 65
    return [(-65, -35), (-20, -35), (-20, 0), (20, 0), (20, -35), (65, -35), (65, 90), (47.5, top),
            (32.5, top), (32.5, slot), (-32.5, slot), (-32.5, top), (-47.5, top), (-65, 90)]


class MstTutorials:
    """Mixin for tutorial.Replay."""

    def AF_STEPS(self):
        return [self.p_modeling, self.af_new, self.af_sketch, self.af_plane, self.af_profile, self.af_point_on_curve, self.af_equal_sides, self.af_bottom, self.af_tangent,
                self.af_redundant, self.af_top, self.af_dimensions, self.af_finish, self.af_extrude,
                self.af_extrude_dialog, self.af_save, self.af_fit, self.af_show]

    # ------------------------------------------------------------- helpers
    def af_ref(self):
        import Part
        P = [App.Vector(x, y, 0) for (x, y) in af_outline()]
        edges = []
        for i in range(len(P)):
            a, b = P[i], P[(i + 1) % len(P)]
            if i == AF_ARC:
                edges.append(Part.Arc(a, App.Vector(0, 20, 0), b).toShape())
            else:
                edges.append(Part.LineSegment(a, b).toShape())
        return Part.Face(Part.Wire(edges)).extrude(App.Vector(0, 0, AF_DEPTH))

    @staticmethod
    def af_vertex(sk, geo, pos):
        """FreeCAD's VertexN name of a curve's start (1), end (2) or centre (3)."""
        for i in range(4 * len(sk.Geometry) + 4):
            try:
                g, p = sk.getGeoVertexIndex(i)
            except Exception:
                break
            if g == geo and p == pos:
                return f"Vertex{i + 1}"
        return None

    def af_edge(self, i):
        return f"Edge{self._af_geo[i] + 1}"

    def af_v(self, i, pos):
        return self.af_vertex(self._af_sk, self._af_geo[i], pos)

    def af_types(self, sk):
        return sorted({c.Type for c in sk.Constraints})

    # ------------------------------------------------------------- New, Sketch, Profile
    def af_new(self):
        self.tutorial = "AF: Arbor Press Base (NX 12 for Engineering Design, 3.5.1)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def af_sketch(self):
        new = set(App.listDocuments()) - self._docs_before
        self.step("Create a new file (Arborpress_base)", "Ctrl+N, Model template", SAME if new and self.body() else FAIL,
                  f"new document {sorted(new)}; the name is given when it is saved")
        Gui.Selection.clearSelection()
        b, where = self.click_ribbon("Sketch")
        self._af_where = where
        self.wait = 1500

    def af_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.wait_for("af: sketch in edit", lambda: self.edited_sketch() is not None)
        sk = self.edited_sketch()
        self.step("Sketch, OK (the XC-YC plane)", f"ribbon '{self._af_where} > Sketch', plane row + MB2",
                  SAME if picked and sk is not None else FAIL, f"picked {picked}; sketch {sk.Label if sk else None}")
        if sk is None:
            raise RuntimeError("no sketch in edit; tutorial AF cannot continue")
        self._af_sk = sk
        self.wait = 600

    def af_profile(self):
        """Profile (Z): lines, M for a tangent arc after the slot's left side, lines again; MB2 ends it."""
        from .tutorial import qtest
        sk = self._af_sk
        xs, ys = [p[0] for p in AF_ROUGH], [p[1] for p in AF_ROUGH]
        self.frame_sketch(sk, (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, (max(ys) - min(ys)) * 1.4)
        QtWidgets.QApplication.processEvents()
        framed = self.camera_state()
        self.key("Z")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        presses = 0
        trace = []
        for i, (x, y) in enumerate(AF_ROUGH):
            # before the arc's end point: switch to arc; after it, back to a plain line (the book clicks
            # Line); FreeCAD would go on with a line held tangent to the arc
            for _ in range({AF_ARC + 1: self.AF_ARC_PRESSES, AF_ARC + 2: self.AF_LINE_PRESSES}.get(i, 0)):
                self.key("M")
                presses += 1
                qtest().qWait(50)
            n0 = len(sk.Constraints)
            p = self.screen_point(sk, x, y)
            self.mb1_click(p)
            pre = Gui.Selection.getPreselection()
            g = sk.Geometry[-1] if sk.Geometry else None
            trace.append({"click": i, "at": (x, y), "px": (p.x(), p.y()), "geo": len(sk.Geometry),
                          "preselected": list(pre.SubElementNames) if pre and pre.ObjectName else [],
                          "last curve": [round(v, 2) for v in (g.StartPoint.x, g.StartPoint.y, g.EndPoint.x,
                                                               g.EndPoint.y)] if g is not None else [],
                          "new": [f"{c.Type} {c.First}/{c.FirstPos} {c.Second}/{c.SecondPos}"
                                  for c in sk.Constraints[n0:]], "tool": self.nav().sketch_tool_active()})
        away = self.screen_point(sk, min(xs) - 60, max(ys) + 40)
        self.mb2_click(away)
        ended = not self.sketch_tool_running(away)
        self.info["AF profile clicks"] = trace
        # the clicks are computed from the camera: it must not move while they are made
        self.info["AF camera moved during the clicks"] = self.camera_state() != framed
        App.ActiveDocument.recompute()
        geo = [i for i, g in enumerate(sk.Geometry) if not sk.getConstruction(i)]
        kinds = [sk.Geometry[i].TypeId.split("::Geom")[-1] for i in geo]
        self._af_geo = geo
        want = ["LineSegment"] * 14
        want[AF_ARC] = "ArcOfCircle"
        wires = sk.Shape.Wires
        closed = len(wires) == 1 and wires[0].isClosed()
        self.info["AF profile"] = {"curves": kinds, "M presses": presses, "constraints": self.af_types(sk),
                                   "closed": closed}
        dof, full, msg = self.sk_state(sk)
        missing = [] if kinds != want else \
            [f"{k} {self.af_edge(i)}" for k, lines in (("Horizontal", AF_HORIZONTAL), ("Vertical", AF_VERTICAL))
             for i in lines if not self.af_has(sk, k, i)]
        tangent = [self.af_edge(s) for s in (1, 3) if kinds == want and self.af_tangent_to_arc(sk, s)]
        self.step("Profile (Z): lines, and an arc for the semicircle (Continuous Auto Dimensioning off)",
                  f"Z key, {len(AF_ROUGH)} MB1 clicks (the last on the first point), M {self.AF_ARC_PRESSES}x before "
                  f"the arc's end and {self.AF_LINE_PRESSES}x after it (the book clicks Line), MB2",
                  SAME if tool and ended and kinds == want and closed and not missing else FAIL,
                  f"{len(kinds)} curves {kinds if kinds != want else '(13 lines, 1 arc)'}; closed by the last click "
                  f"{closed}; Horizontal/Vertical inferred on every straight line except the two slanted ones"
                  f"{' but ' + ', '.join(missing) if missing else ''}; arc tangent to {tangent or 'none'}; tool ended "
                  f"by MB2 {ended}; DoF {dof}. FreeCAD has no automatic dimensions to switch off")
        self.wait = 300

    def af_tangent_to_arc(self, sk, side):
        arc, line = self._af_geo[AF_ARC], self._af_geo[side]
        return any(c.Type == "Tangent" and {c.First, c.Second} == {arc, line} for c in sk.Constraints)

    def af_has(self, sk, kind, i):
        return any(c.Type == kind and c.First == self._af_geo[i] and c.Second < -1999 for c in sk.Constraints)

    AF_ARC_PRESSES = 3       # M: line -> perpendicular line -> tangent line -> tangent arc
    AF_LINE_PRESSES = 2      # M after an arc: tangent line -> perpendicular line -> line

    # ------------------------------------------------------------- geometric constraints
    def af_point_on_curve(self):
        sk = self._af_sk
        centre = self.af_v(AF_ARC, 3)
        n0 = len(sk.Constraints)
        d1, where = self.sk_constrain(sk, "Point on Curve", ["V_Axis", centre])
        d2, _ = self.sk_constrain(sk, "Point on Curve", ["H_Axis", centre])
        made = [f"{k.Type} {k.First}/{k.FirstPos} {k.Second}" for k in sk.Constraints[n0:]]
        dof, _, msg = self.sk_state(sk)
        c = sk.Geometry[self._af_geo[AF_ARC]].Center
        ok = d1 == 1 and d2 == 1 and c.Length < 1e-6 and all(k.Type == "PointOnObject" for k in sk.Constraints[n0:])
        self.step("Point on Curve: the arc's centre on the Y axis, then on the X axis",
                  f"axis + centre + ribbon '{where} > Point on Curve', twice", SAME if ok else FAIL,
                  f"centre at ({c.x:.3f}, {c.y:.3f}); made {made}; DoF {dof} ('{msg}')")

    def af_equal_sides(self):
        sk = self._af_sk
        d1, where = self.sk_constrain(sk, "Equal", [self.af_edge(6), self.af_edge(12)])
        d2, _ = self.sk_constrain(sk, "Equal", [self.af_edge(5), self.af_edge(13)])
        L = [sk.Geometry[self._af_geo[i]].length() for i in (6, 12, 5, 13)]
        dof, _, msg = self.sk_state(sk)
        self.step("Equal Length: the two slanted lines, then the two long vertical lines",
                  f"two lines + ribbon '{where} > Equal', twice",
                  SAME if d1 == 1 and d2 == 1 and abs(L[0] - L[1]) < 1e-6 and abs(L[2] - L[3]) < 1e-6 else FAIL,
                  f"slanted {L[0]:.2f} / {L[1]:.2f}, verticals {L[2]:.2f} / {L[3]:.2f} mm; DoF {dof}")

    def af_collinear(self, a, b, what):
        """NX's Collinear, then Equal Length, on two lines. Both are horizontal already, so Collinear adds one
        point-on-curve constraint (a second would be redundant)."""
        from .sketch_ui import collinear_report
        sk = self._af_sk
        d, where = self.sk_constrain(sk, "Collinear", [self.af_edge(b), self.af_edge(a)])
        rc = sk.solve()
        e, _ = self.sk_constrain(sk, "Equal", [self.af_edge(a), self.af_edge(b)])
        ga, gb = sk.Geometry[self._af_geo[a]], sk.Geometry[self._af_geo[b]]
        off, ang = collinear_report(sk, self._af_geo[a], self._af_geo[b])
        la, lb = ga.length(), gb.length()
        dof, _, _ = self.sk_state(sk)
        ok = d == 1 and rc == 0 and e == 1 and off < 1e-6 and ang < 1e-6 and abs(la - lb) < 1e-6
        return ok, where, (f"{what} {off:.4f} mm apart (Collinear added {d} point-on-curve constraint, solver "
                           f"{rc}), lengths {la:.2f} / {lb:.2f} mm; DoF {dof}")

    def af_bottom(self):
        ok, where, detail = self.af_collinear(0, 4, "the bottom lines")
        self.step("Collinear, then Equal Length: the two bottom lines",
                  f"two lines + ribbon '{where} > Collinear'; two lines + 'Equal'", SAME if ok else FAIL, detail)

    def af_tangent(self):
        """The book: add Tangent where the arc meets a vertical line, unless it is there already."""
        sk = self._af_sk
        arc = self._af_geo[AF_ARC]
        made, had = [], []
        for side in (1, 3):
            line = self._af_geo[side]
            if any(c.Type == "Tangent" and {c.First, c.Second} == {arc, line} for c in sk.Constraints):
                had.append(self.af_edge(side))
                continue
            d, where = self.sk_constrain(sk, "Tangent", [self.af_edge(AF_ARC), self.af_edge(side)])
            made.append((self.af_edge(side), d))
        both = all(any(c.Type == "Tangent" and {c.First, c.Second} == {arc, self._af_geo[s]} for c in sk.Constraints)
                   for s in (1, 3))
        g = sk.Geometry[arc]
        dof, _, _ = self.sk_state(sk)
        self.step("Tangent: the arc and each vertical line at its ends (only where it is missing)",
                  "arc + line + ribbon 'Tangent' where missing" if made else "none missing",
                  SAME if both else FAIL,
                  f"already tangent from Profile: {had or 'none'}; added {made or 'none'}; arc radius {g.Radius:.3f} mm "
                  f"about ({g.Center.x:.3f}, {g.Center.y:.3f}); DoF {dof}")

    def af_redundant(self):
        """The book makes the slot's two short verticals Equal. Here they already are: both run from the bottom
        line to the arc's ends, which the tangency and the centre on the X axis put at Y = 0."""
        sk = self._af_sk
        n = len(sk.Constraints)
        d, where = self.sk_constrain(sk, "Equal", [self.af_edge(1), self.af_edge(3)])
        rc = sk.solve()
        _, _, msg = self.sk_state(sk)
        self.key("Ctrl+Z")
        QtWidgets.QApplication.processEvents()
        App.ActiveDocument.recompute()
        back = len(sk.Constraints) == n
        self.step("Equal Length: the slot's two vertical lines", f"two lines + ribbon '{where} > Equal', then Ctrl+Z",
                  DIFFERS if d == 1 and rc != 0 and back else FAIL,
                  f"FreeCAD reports it redundant (solver {rc}; '{msg}'): the tangency and the centre on the X axis "
                  f"already make them equal, so it is undone ({'removed' if back else 'still there'})")

    def af_top(self):
        ok, where, detail = self.af_collinear(7, 11, "the top lines")
        self.step("Collinear, then Equal: the two short lines at the top",
                  f"two lines + ribbon '{where} > Collinear'; two lines + 'Equal'", SAME if ok else FAIL,
                  f"{detail}; the notch's two sides are then equal too (the book's last Equal is implied)")

    # ------------------------------------------------------------- dimensions
    def af_dimensions(self):
        sk = self._af_sk
        top_left, top_right = self.af_v(12, 1), self.af_v(6, 2)
        # biggest first, as the book recommends; each value is typed when the dimension is made
        dims = [("height", [top_left, self.af_edge(0)], 190.94), ("width", [self.af_v(13, 1), self.af_edge(5)], 130.0),
                ("side", [self.af_edge(5)], 125.0), ("top", [top_right, top_left], 95.0),
                ("notch width", [self.af_edge(9)], 65.0), ("notch depth", [self.af_v(7, 2), self.af_edge(9)], 65.0),
                ("slot", [self.af_v(1, 1), self.af_edge(3)], 40.0), ("centre", [self.af_v(AF_ARC, 3), self.af_edge(0)], 35.0)]
        made, where = [], ""
        for name, subs, value in dims:
            d, where = self.sk_constrain(sk, "Distance", subs, value)
            made.append(f"{name} {value:g}" + ("" if d == 1 else " (not made)"))
        dof, full, msg = self.sk_state(sk)
        # every corner of the book's figure against the nearest sketch end point (FreeCAD stores arcs anticlockwise)
        pts = [sk.getPoint(g, p) for g in self._af_geo for p in (1, 2)]
        err = max(min((App.Vector(*w, 0) - p).Length for p in pts) for w in af_outline())
        self.info["AF dimensions"] = {"made": made, "solver": msg, "corner error mm": err}
        self.step("Rapid Dimension: eight dimensions, then the values, biggest first; the sketch is fully defined",
                  f"picks + ribbon '{where} > Distance', the value typed in FreeCAD's dimension dialog, 8 times",
                  DIFFERS if all("not made" not in m for m in made) and dof == 0 and full and err < 1e-6 else FAIL,
                  f"{', '.join(made)}; DoF {dof}, fully constrained {full} ('{msg}'); corners within {err:.1e} mm of "
                  "the book's figure. NX places all dimensions first and edits them; FreeCAD asks for each value "
                  "as the dimension is made")
        self.shot("AF1_constrained_sketch.png")

    # ------------------------------------------------------------- Finish, Extrude 60
    def af_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1200

    def af_extrude(self):
        sk = self._af_sk
        left = self.edited_sketch() is None
        self.step("Finish Sketch", "Ctrl+Q", SAME if left else FAIL, f"sketch edit ended {left}")
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self.body().Name, f"{sk.Name}.")
        QtWidgets.QApplication.processEvents()
        from . import controller
        ctl = controller.CONTROLLER
        before = {"selection": [(s.ObjectName, list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx("", 0)],
                  "Extrude active": Gui.Command.get("NXStyle_Extrude").isActive(),
                  "section": getattr(controller.ADAPTERS["Extrude"].preselected_section(), "Name", None)}
        self.key("X")
        QtWidgets.QApplication.processEvents()
        report = ""
        for te in Gui.getMainWindow().findChildren(QtWidgets.QTextEdit):
            if "report" in te.objectName().lower() or "report" in (te.parent().objectName() or "").lower():
                report = te.toPlainText()[-1500:]
        s = ctl.session
        before.update({"busy after X": ctl.busy(), "dialog": bool(Gui.Control.activeDialog()),
                       "history": ctl.history[-1:], "trace": getattr(ctl, "trace", [])[-6:],
                       "session": {k: str(v)[:80] for k, v in vars(s).items()} if s is not None else None,
                       "report view tail": report})
        self.info["AF extrude: X with the sketch selected"] = before
        self.wait = 1500

    def af_extrude_dialog(self):
        self.ae_wait_box("af_extrude_dialog")
        shown, _, status, ok = self.ae_panel()
        box = self.ae_box()
        section = box.findChild(QtWidgets.QLabel, "nxSection").text() if box is not None and \
            box.findChild(QtWidgets.QLabel, "nxSection") is not None else ""
        self.shot("AF2_extrude_dialog.png")
        field = self.ae_type(AF_DEPTH)
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        self.wait_for("af_extrude_dialog closed", lambda: not self.ae_ctl().busy())
        same, how = self.ae_compare(self.body(), self.af_ref())
        one, steps = self.ae_one_step("new_body", "Extrude")
        self.step("Select the sketch, Extrude (X): Z direction, 60 mm, Boolean None", f"sketch selected + X; '{field}' "
                  "= 60 mm, MB2 = OK", SAME if shown == "None" and same and one else FAIL,
                  f"Boolean '{shown}' ({status or 'no message'}){'; section ' + section if section else ''}; {how}; {steps}")
        self.wait = 600

    def af_save(self):
        outcome, how, detail, path = self.save_ctrl_s("Arborpress_base.FCStd")
        self.step("Save and close the file", how, outcome, detail)
        self.wait = 300

    def af_fit(self):
        self.fit()

    def af_show(self):
        self.show("AF_arbor_press_base")
