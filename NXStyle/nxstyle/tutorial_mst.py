# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercises from Leu, Tao, Ghazanfari and Kolan, NX 12 for Engineering Design (Missouri S&T), ch. 3.5.

  AF  3.5.1 Arbor Press Base: Sketch on XC-YC -> Profile (Z), lines and a tangent arc -> geometric
      constraints (centre of the arc on both axes, Equal, Collinear, Tangent) -> dimensions, biggest first
      -> fully constrained -> Finish -> select the sketch, Extrude 60 -> save
  AG  3.5.2 Impeller Lower Casing (a sketch, inches typed in mm): Profile of a line, two tangent arcs and a
      line -> a point at the origin, Fixed -> radii and distances -> Move Curve copies 0.5 up and 1.5 down,
      the ends joined -> the flange rectangle at the small end -> 19 curves, the casing wall and its edge
      closed; the next chapter revolves it about the X axis
  AH  3.5.3 Impeller (a sketch, inches typed in mm): two points, an arc by centre about each (R1.5 at the
      origin, R0.5 at (11.75, 6)), two arcs by 3 points joining them, all tangent, the origin point Fixed,
      the four radii (1.5, 0.5, 18, 15)

The sketch is drawn roughly, as the book says, and the constraints and dimensions bring it to size. The
sizes are the book's final dimension figure (p. 43): width 130, height 190.94, the outer verticals 125, the
top 95 with a 65 x 65 notch, a slot 40 wide ending in a semicircle whose centre is the origin, 35 above the
bottom edge. The solid is compared with the same solid made with the Part API (nxstyle/geomcheck.py).
"""

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtWidgets, Qt

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


# ================================================================== AG: Impeller Lower Casing (3.5.2)
IN = 25.4
# the book's dimension figure (p. 45), inches: Line 1 15 below the origin and 7.3 long, Curve 1 R33, Curve 2
# R8, Line 2 8.1 below the origin and 1.0 long, all joints tangent. Nothing places the curve along X (the
# casing is revolved about the X axis in ch. 4.4), so one degree of freedom is left, as in the book.
AG_Y1, AG_L1, AG_R1, AG_R2, AG_Y2, AG_L2 = -15 * IN, 7.3 * IN, 33 * IN, 8 * IN, -8.1 * IN, 1.0 * IN
AG_UP, AG_DOWN, AG_FLANGE = 0.5 * IN, -1.5 * IN, -0.5 * IN       # Move Curve: copy up, copy down, flange width
# drawn roughly (inches): Line 1, Curve 1's end, Curve 2's end, Line 2's end
AG_ROUGH = [(-8, -15.3), (-0.8, -15.3), (17, -9.8), (22, -8.3), (23.2, -8.3)]


def ag_chain(a, dy=0.0):
    """The inner curve (Line 1, Curve 1, Curve 2, Line 2) with Line 1 starting at x = a, moved dy in Y:
    a list of (kind, start, end, centre, radius)."""
    import math
    V = App.Vector
    c1 = V(a + AG_L1, AG_Y1 + AG_R1, 0)
    c2y = AG_Y2 - AG_R2
    dx = math.sqrt((AG_R1 + AG_R2) ** 2 - (c1.y - c2y) ** 2)
    c2 = V(c1.x + dx, c2y, 0)
    j = c1 + (c2 - c1) * (AG_R1 / (AG_R1 + AG_R2))
    s = V(0, dy, 0)
    p0, p1, p2 = V(a, AG_Y1, 0), V(a + AG_L1, AG_Y1, 0), V(c2.x, AG_Y2, 0)
    return [("line", p0 + s, p1 + s, None, 0), ("arc", p1 + s, j + s, c1 + s, AG_R1),
            ("arc", j + s, p2 + s, c2 + s, AG_R2), ("line", p2 + s, p2 + V(AG_L2, 0, 0) + s, None, 0)]


def ag_reference(a):
    """All 19 curves of the finished sketch, as (kind, start, end, centre, radius)."""
    V = App.Vector
    inner, up, down = ag_chain(a), ag_chain(a, AG_UP), ag_chain(a, AG_DOWN)
    l, r = inner[0][1], inner[3][2]
    lines = [(l, l + V(0, AG_UP, 0)), (r, r + V(0, AG_UP, 0)),          # the wall's two ends
             (l, l + V(0, AG_DOWN, 0)), (r, r + V(0, AG_DOWN, 0))]      # the edge's two ends
    f = r + V(AG_FLANGE, 0, 0)
    lines += [(f, f + V(0, AG_DOWN, 0)), (f, r), (f + V(0, AG_DOWN, 0), r + V(0, AG_DOWN, 0))]   # the flange
    return inner + up + down + [("line", p, q, None, 0) for p, q in lines]


class MstCasingTutorials:
    """Mixin for tutorial.Replay: tutorial AG."""

    def AG_STEPS(self):
        return [self.p_modeling, self.ag_new, self.ag_sketch, self.ag_plane, self.ag_profile, self.ag_repair,
                self.ag_point, self.ag_tangent, self.ag_dimensions, self.ag_hide, self.ag_copy_up, self.ag_join_wall,
                self.ag_copy_down, self.ag_join_edge, self.ag_flange, self.ag_flange_join, self.ag_check,
                self.ag_finish, self.ag_save, self.ag_fit, self.ag_show]

    # ------------------------------------------------------------- helpers
    def ag_kind(self, g):
        t = self._ag_sk.Geometry[g].TypeId
        return "arc" if "Arc" in t else "line" if "Line" in t else "point" if "Point" in t else t

    def ag_edge(self, g):
        return f"Edge{g + 1}"

    def ag_vertex(self, g, pos):
        return self.af_vertex(self._ag_sk, g, pos)

    def ag_ends(self, g):
        """(start, end) of a curve along the drawing direction: FreeCAD stores arcs anticlockwise."""
        sk = self._ag_sk
        a, b = sk.getPoint(g, 1), sk.getPoint(g, 2)
        return (b, a) if g in self._ag_reversed else (a, b)

    def ag_end_pos(self, g, which):
        """FreeCAD's PointPos (1 start, 2 end) of the drawn start ('s') or end ('e') of curve g."""
        pos = 1 if which == "s" else 2
        return 3 - pos if g in self._ag_reversed else pos

    def ag_frame(self):
        """Frame the casing, after FreeCAD's camera animation into the sketch has finished: clicks made while
        the camera still moves land off the points (the Profile session found this)."""
        from .tutorial import qtest
        last = None
        for _ in range(40):
            pos = tuple(self.view().getCameraNode().position.getValue())
            if pos == last:
                break
            last = pos
            qtest().qWait(100)
        xs = [p[0] * IN for p in AG_ROUGH]
        ys = [p[1] * IN for p in AG_ROUGH] + [0.0, 5 * IN]
        self.frame_sketch(self._ag_sk, (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, (max(xs) - min(xs)) * 0.7)
        QtWidgets.QApplication.processEvents()

    def ag_shot(self, name):
        """A picture of the whole sketch: frame its bounding box (with the window's aspect), then shoot."""
        sk = self._ag_sk
        bb = sk.Shape.BoundBox
        w = self.nav().widget
        aspect = w.height() / max(w.width(), 1)
        self.frame_sketch(sk, (bb.XMin + bb.XMax) / 2, (bb.YMin + bb.YMax) / 2,
                          max(bb.YLength * 1.25, bb.XLength * 1.15 * aspect))
        QtWidgets.QApplication.processEvents()
        self.shot(name)

    def ag_geo_match(self, ref, tol=1e-3):
        """Reference curves with no sketch curve of the same kind, ends (either way round) and radius."""
        sk = self._ag_sk
        have = []
        for g, geo in enumerate(sk.Geometry):
            k = self.ag_kind(g)
            if k in ("line", "arc"):
                have.append((k, sk.getPoint(g, 1), sk.getPoint(g, 2), getattr(geo, "Radius", 0)))
        missing = []
        for kind, p, q, _c, r in ref:
            if not any(k == kind and abs(rad - r) < tol and (((a - p).Length < tol and (b - q).Length < tol)
                                                              or ((a - q).Length < tol and (b - p).Length < tol))
                       for k, a, b, rad in have):
                missing.append(f"{kind} ({p.x / IN:.3f},{p.y / IN:.3f})->({q.x / IN:.3f},{q.y / IN:.3f}) in")
        return missing

    def ag_attached(self, g, targets):
        """Whether each end of the drawn line g is held by Coincident to a curve end where it should be: the
        target point, or any other end at the same place (a corner where three curves meet snaps to one)."""
        sk = self._ag_sk
        out = []
        for pos, (tg, tp) in zip((1, 2), targets):
            want = sk.getPoint(tg, tp)
            hit = False
            for c in sk.Constraints:
                if c.Type != "Coincident":
                    continue
                ends = {(c.First, c.FirstPos), (c.Second, c.SecondPos)}
                if (g, pos) in ends:
                    (og, op), = ends - {(g, pos)}
                    hit = hit or (og >= 0 and (sk.getPoint(og, op) - want).Length < 1e-6)
            out.append(hit)
        return out

    # ------------------------------------------------------------- New, Sketch, Profile
    def ag_new(self):
        self.tutorial = "AG: Impeller Lower Casing (NX 12 for Engineering Design, 3.5.2; book in inches, typed in mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def ag_sketch(self):
        new = set(App.listDocuments()) - self._docs_before
        self.step("Create a new file in inches (Impeller_lower_casing)", "Ctrl+N, Model template",
                  SAME if new and self.body() else FAIL, f"new document {sorted(new)}")
        self.units_step()
        Gui.Selection.clearSelection()
        b, where = self.click_ribbon("Sketch")
        self._ag_where = where
        self.wait = 1500

    def ag_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.wait_for("ag: sketch in edit", lambda: self.edited_sketch() is not None)
        sk = self.edited_sketch()
        self.step("Sketch in Task Environment on the XC-YC plane", f"ribbon '{self._ag_where} > Sketch', plane row + MB2",
                  SAME if picked and sk is not None else FAIL,
                  f"picked {picked}; FreeCAD edits every sketch in its own environment, as NX's task environment")
        if sk is None:
            raise RuntimeError("no sketch in edit; tutorial AG cannot continue")
        self._ag_sk = sk
        self.wait = 600

    def ag_profile(self):
        from .tutorial import qtest
        sk = self._ag_sk
        self.ag_frame()
        self.key("Z")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        # M cycles the next segment: tangent line, perpendicular line, free line, tangent arc, ... After a line the
        # next starts free (3 presses to a tangent arc); after an arc it starts tangent (3 presses too)
        presses = {2: self.AF_ARC_PRESSES, 3: 3}
        trace = []
        for i, (x, y) in enumerate(AG_ROUGH):
            for _ in range(presses.get(i, 0)):
                self.key("M")
                qtest().qWait(50)
            n0 = len(sk.Constraints)
            self.mb1_click(self.screen_point(sk, x * IN, y * IN))
            trace.append({"click": i, "geo": len(sk.Geometry), "new": [f"{c.Type} {c.First}/{c.FirstPos} {c.Second}/"
                                                                        f"{c.SecondPos}" for c in sk.Constraints[n0:]]})
        self.mb2_click(self.screen_point(sk, -12 * IN, 4 * IN))
        ended = not self.nav().sketch_tool_active()
        App.ActiveDocument.recompute()
        geo = list(range(len(sk.Geometry)))
        kinds = [self.ag_kind(g) for g in geo]
        self._ag_geo = geo
        # which arcs FreeCAD stored against the drawing direction (it keeps arcs anticlockwise)
        self._ag_reversed = set()
        for g in geo:
            if kinds[g] == "arc" and g > 0 and (sk.getPoint(g, 2) - sk.getPoint(g - 1, 2)).Length < \
                    (sk.getPoint(g, 1) - sk.getPoint(g - 1, 2)).Length:
                self._ag_reversed.add(g)
        tangents = sum(1 for c in sk.Constraints if c.Type == "Tangent")
        first_h = any(c.Type == "Horizontal" and c.First == 0 for c in sk.Constraints)
        self.info["AG profile clicks"] = trace
        dof, _, _ = self.sk_state(sk)
        self.step("Profile: Line 1, Curve 1, Curve 2, Line 2", f"Z key, 5 MB1 clicks, M ({self.AF_ARC_PRESSES}x) before "
                  "Curve 1's end and 3x before Curve 2's, MB2",
                  SAME if tool and ended and kinds == ["line", "arc", "arc", "line"] and tangents == 3 and first_h
                  else FAIL, f"curves {kinds}; tangent joints {tangents} of 3; Line 1 Horizontal {first_h}; DoF {dof}")
        self.wait = 300

    def ag_repair(self):
        sk = self._ag_sk
        done = []
        for g in (0, 3):
            if not any(c.Type == "Horizontal" and c.First == g for c in sk.Constraints):
                d, where = self.sk_constrain(sk, "Horizontal", [self.ag_edge(g)])
                done.append(f"Horizontal on Line {1 if g == 0 else 2} ({d})")
        ok = all(any(c.Type == "Horizontal" and c.First == g for c in sk.Constraints) for g in (0, 3))
        dof, _, _ = self.sk_state(sk)
        self.step("(not in the book) Horizontal on Line 1 and Line 2", "line + ribbon 'Horizontal' where missing",
                  DIFFERS if ok else FAIL, f"{'; '.join(done) or 'nothing missing'}; DoF {dof}. NX infers Horizontal "
                  "while drawing; FreeCAD's Profile does not for its first line, nor for a line after an arc")

    def ag_point(self):
        """A point at the origin, then Fixed. FreeCAD's Fixed keeps the point where it is; a point on the origin is
        what Coincident with the origin does."""
        sk = self._ag_sk
        b, where = self.click_ribbon("Point", tab="Sketch")
        QtWidgets.QApplication.processEvents()
        self.mb1_click(self.screen_point(sk, 0, 0))
        self.mb2_click(self.screen_point(sk, -12 * IN, 4 * IN))
        App.ActiveDocument.recompute()
        pts = [g for g in range(len(sk.Geometry)) if self.ag_kind(g) == "point"]
        self._ag_point = pts[-1] if pts else None
        if self._ag_point is None:
            self.step("A point at the origin (Point in the Direct Sketch group), Fixed", f"ribbon '{where} > Point', MB1 "
                      "at the origin", FAIL, f"no point made; curves {len(sk.Geometry)}")
            return
        p = self._ag_point
        on_origin = any(c.Type == "Coincident" and {(c.First, c.FirstPos), (c.Second, c.SecondPos)} == {(p, 1), (-1, 1)}
                        for c in sk.Constraints)
        how = f"ribbon '{where} > Point', MB1 at the origin"
        if not on_origin:
            d, w2 = self.sk_constrain(sk, "Coincident", [self.ag_vertex(p, 1), "RootPoint"])
            how += f"; point + origin + '{w2} > Coincident'"
        q = sk.getPoint(p, 1)
        dof, _, _ = self.sk_state(sk)
        self.step("A point at the origin (0, 0, 0), then Fixed", how, DIFFERS if q.Length < 1e-9 else FAIL,
                  f"point at ({q.x:.4f}, {q.y:.4f}) mm; the click {'snapped to' if on_origin else 'did not snap to'} the "
                  f"origin; DoF {dof}. FreeCAD's Fixed keeps a point where it is, so Coincident with the origin puts "
                  "it at (0, 0, 0), as NX's typed coordinates do")

    def ag_tangent(self):
        sk = self._ag_sk
        made = []
        for a, b in ((0, 1), (1, 2), (2, 3)):
            if not any(c.Type == "Tangent" and {c.First, c.Second} == {a, b} for c in sk.Constraints):
                d, where = self.sk_constrain(sk, "Tangent", [self.ag_edge(a), self.ag_edge(b)])
                made.append(f"{a + 1}-{b + 1} ({d})")
        ok = all(any(c.Type == "Tangent" and {c.First, c.Second} == {a, b} for c in sk.Constraints)
                 for a, b in ((0, 1), (1, 2), (2, 3)))
        self.step("Tangent at every curve-line and curve-curve joint", "ribbon 'Tangent' where missing" if made else
                  "none missing", SAME if ok else FAIL, f"made by Profile; added {made or 'none'}")

    def ag_dimensions(self):
        sk = self._ag_sk
        pt = self.ag_vertex(self._ag_point, 1) if self._ag_point is not None else "RootPoint"
        dims = [("Curve 1 radius 33", "Radius / Diameter", [self.ag_edge(1)], 33 * IN),
                ("Line 1 15 below the origin", "Distance", [pt, self.ag_edge(0)], 15 * IN),
                ("Line 2 8.1 below the origin", "Distance", [pt, self.ag_edge(3)], 8.1 * IN),
                ("Curve 2 radius 8", "Radius / Diameter", [self.ag_edge(2)], 8 * IN),
                ("Line 1 7.3 long", "Distance", [self.ag_edge(0)], 7.3 * IN),
                ("Line 2 1.0 long", "Distance", [self.ag_edge(3)], 1.0 * IN)]
        made, where, direct = [], {}, []
        for name, label, subs, value in dims:
            d, w = self.sk_constrain(sk, label, subs, value)
            where[label] = w
            if d == 0 and label == "Radius / Diameter":
                # the ribbon button stays greyed out in sketch edit (reported separately): FreeCAD's own Radius
                d = self.ag_run_with_value("Sketcher_ConstrainRadius", subs, value)
                direct.append(name)
            made.append(name + ("" if d == 1 else " (not made)"))
        dof, full, msg = self.sk_state(sk)
        a = sk.getPoint(0, 1).x
        missing = self.ag_geo_match(ag_chain(a))
        self.info["AG dimensions"] = {"made": made, "solver": msg, "missing": missing}
        self.step("Dimensions: p1 15, p2 7.3, R 33, R 8, p6 8.1, p4 1.0", "picks + ribbon "
                  f"'{where.get('Distance', '')} > Distance' and 'Radius / Diameter', each value typed in FreeCAD's "
                  "dimension dialog (biggest first)",
                  (DIFFERS if direct else SAME) if all("not made" not in m for m in made) and dof == 1 and not missing
                  else FAIL,
                  f"{', '.join(made)}; DoF {dof} ('{msg}'): only the position along X is left free, as in the book; "
                  + (f"the ribbon's Radius / Diameter was greyed out, so FreeCAD's Radius command was run for "
                     f"{', '.join(direct)}; " if direct else "") +
                  f"the four curves {'match' if not missing else 'differ from'} the book's figure"
                  + (f" ({missing})" if missing else ""))
        self.ag_shot("AG1_dimensioned_curve.png")

    def ag_run_with_value(self, command, subs, value):
        """Run a FreeCAD command on the picks and answer its value dialog; returns the constraints added."""
        from .tutorial import qtest
        sk = self._ag_sk
        n0 = len(sk.Constraints)
        Gui.Selection.clearSelection()
        for s in subs:
            Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, s)
        QtWidgets.QApplication.processEvents()
        self.modals.handler = self.datum_dialog(value)
        Gui.runCommand(command)
        QtWidgets.QApplication.processEvents()
        qtest().qWait(300)
        self.modals.handler = None
        App.ActiveDocument.recompute()
        return len(sk.Constraints) - n0

    def ag_hide(self):
        sk = self._ag_sk
        dims = [i for i, c in enumerate(sk.Constraints) if c.Type in ("Distance", "Radius", "DistanceX", "DistanceY")]
        Gui.Selection.clearSelection()
        for i in dims:
            Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, f"Constraint{i + 1}")
        QtWidgets.QApplication.processEvents()
        Gui.runCommand("Sketcher_SwitchVirtualSpace")
        QtWidgets.QApplication.processEvents()
        hidden = [i for i in dims if sk.getVirtualSpace(i)]
        Gui.Selection.clearSelection()
        self.step("Select all the dimensions, MB3 > Hide", "dimensions selected, FreeCAD's 'Switch virtual space'",
                  DIFFERS if dims and len(hidden) == len(dims) else FAIL,
                  f"{len(hidden)} of {len(dims)} dimensions hidden. FreeCAD hides sketch dimensions by moving them to "
                  "its 'virtual space' (not on the ribbon or the MB3 menu); Ctrl+B does not hide them")

    # ------------------------------------------------------------- Move Curve (copy), joins
    def ag_move_curve(self, geos, dx, dy, what):
        """Move Curve with Copy Original: select the curves, click the ribbon button, then a base point and the
        target (the offset typed into FreeCAD's on-view fields when it shows them). Returns the new curves."""
        from .qt import QtCore
        from .tutorial import qtest
        sk = self._ag_sk
        n0 = len(sk.Geometry)
        Gui.Selection.clearSelection()
        for g in geos:
            Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, self.ag_edge(g))
        QtWidgets.QApplication.processEvents()
        self.ag_frame()
        b, where = self.click_ribbon("Move Curve", tab="Sketch")
        qtest().qWait(300)
        tool = self.nav().sketch_tool_active()
        view = self.nav().widget

        def fields():
            dock = self.tasks_dock()
            out = [f"view {w.objectName()}:{type(w).__name__}" for w in view.findChildren(QtWidgets.QAbstractSpinBox)
                   if w.isVisible()]
            out += [f"label {w.objectName()}='{w.text()}'" for w in dock.findChildren(QtWidgets.QLabel)
                    if w.isVisible() and w.text().strip() and len(w.text()) < 60]
            out += [f"spin {w.objectName()}={w.text()}" for w in dock.findChildren(QtWidgets.QAbstractSpinBox)
                    if w.isVisible()]
            out += [f"check {w.objectName()}='{w.text()}' {w.isChecked()}" for w in dock.findChildren(QtWidgets.QCheckBox)
                    if w.isVisible()]
            return out
        moved_from = [sk.getPoint(g, 1) for g in geos]
        before = fields()
        dock = self.tasks_dock()
        copies = next((w for w in dock.findChildren(QtWidgets.QAbstractSpinBox)
                       if w.objectName() == "parameterOne" and w.isVisible()), None)
        if copies is not None:                       # Copy Original: one copy (0 moves the curves)
            self.type_into(copies, 1)
        base = self.ag_ends(geos[0])[0]
        self.mb1_click(self.screen_point(sk, base.x, base.y))
        qtest().qWait(200)
        mw = Gui.getMainWindow()
        area = QtCore.QRect(view.mapToGlobal(QtCore.QPoint(0, 0)), view.size())
        ovp = [w for w in mw.findChildren(QtWidgets.QAbstractSpinBox) if w.isVisible() and not dock.isAncestorOf(w)
               and area.contains(w.mapToGlobal(w.rect().center()))]
        after = fields() + [f"ovp {w.objectName()}:{type(w).__name__}:{w.parent().objectName()}:{w.text()}"
                            for w in mw.findChildren(QtWidgets.QAbstractSpinBox) if w.isVisible()
                            and not dock.isAncestorOf(w)]
        # FreeCAD's on-view fields give the move as a length and an angle: type both, Enter in each, as a user
        # does, then click (the typed values are locked, so the click only confirms)
        import math
        from .smoke import decode
        length = next((w for w in ovp if w.text().strip().endswith("mm")), None)
        angle = next((w for w in ovp if w.text().strip().endswith("°")), None)
        typed = length is not None and angle is not None
        for w, v in ((length, math.hypot(dx, dy)), (angle, math.degrees(math.atan2(dy, dx)))) if typed else ():
            w.setFocus()
            w.lineEdit().selectAll()
            qtest().keyClicks(w.lineEdit(), self.typed_number(w, v))
            qtest().keyClick(w.lineEdit(), *decode("Return"))
            qtest().qWait(150)
        if len(sk.Geometry) == n0 and self.nav().sketch_tool_active():
            self.mb1_click(self.screen_point(sk, base.x + dx, base.y + dy))
        qtest().qWait(200)
        still = self.nav().sketch_tool_active()
        if still:
            self.mb2_click(self.screen_point(sk, -12 * IN, 4 * IN))
        App.ActiveDocument.recompute()
        new = list(range(n0, len(sk.Geometry)))
        moved = max((sk.getPoint(g, 1) - p).Length for g, p in zip(geos, moved_from))
        self.info[f"AG Move Curve {what}"] = {"tool": tool, "fields before base click": before[:40],
                                              "fields after": after[:40], "typed": typed,
                                              "new curves": len(new), "tool open after target": still,
                                              "originals moved mm": moved}
        return new, where, typed

    def ag_offsets(self, geos, new, dx, dy):
        """Largest error of the copies against the originals moved (dx, dy), comparing ends either way round."""
        sk = self._ag_sk
        d = App.Vector(dx, dy, 0)
        err = 0.0
        for g, n in zip(geos, new):
            a, b = sk.getPoint(g, 1) + d, sk.getPoint(g, 2) + d
            p, q = sk.getPoint(n, 1), sk.getPoint(n, 2)
            err = max(err, min(max((a - p).Length, (b - q).Length), max((a - q).Length, (b - p).Length)))
        return err

    def ag_copy(self, geos, dx, dy, label, what):
        new, where, typed = self.ag_move_curve(geos, dx, dy, what)
        err = self.ag_offsets(geos, new, dx, dy) if len(new) == len(geos) else None
        ok = len(new) == len(geos) and err is not None and err < 1e-3
        self.step(label, f"{len(geos)} curves selected + ribbon '{where} > Move Curve', base point, offset "
                  + ("typed" if typed else "clicked"), SAME if ok else FAIL,
                  f"{len(new)} copies made; largest error {err if err is None else f'{err:.1e}'} mm"
                  + ("" if typed else "; no on-view fields to type the distance into, so the target was clicked"))
        return new

    def ag_line(self, p, q):
        """A straight line (L) from p to q, MB2."""
        sk = self._ag_sk
        n0 = len(sk.Geometry)
        self.ag_frame()
        self.key("L")
        QtWidgets.QApplication.processEvents()
        self.mb1_click(self.screen_point(sk, p.x, p.y))
        self.mb1_click(self.screen_point(sk, q.x, q.y))
        self.mb2_click(self.screen_point(sk, -12 * IN, 4 * IN))
        App.ActiveDocument.recompute()
        return n0 if len(sk.Geometry) > n0 else None

    def ag_join(self, ends, label):
        """Lines between pairs of (geo, which) curve ends; attached by Coincident where the click did not snap."""
        sk = self._ag_sk
        lines, snapped, added = [], 0, 0
        for (ga, wa), (gb, wb) in ends:
            pa, pb = self.ag_ends(ga)[0 if wa == "s" else 1], self.ag_ends(gb)[0 if wb == "s" else 1]
            g = self.ag_line(pa, pb)
            if g is None:
                continue
            lines.append(g)
            targets = [(ga, self.ag_end_pos(ga, wa)), (gb, self.ag_end_pos(gb, wb))]
            att = self.ag_attached(g, targets)
            snapped += sum(att)
            for pos, ok, (tg, tp) in zip((1, 2), att, targets):
                if not ok:
                    d, _ = self.sk_constrain(sk, "Coincident", [self.ag_vertex(g, pos), self.ag_vertex(tg, tp)])
                    added += d
        self.step(label, f"L key, MB1 on each end point, MB2 ({len(lines)} lines)",
                  SAME if len(lines) == len(ends) and snapped == 2 * len(ends) else
                  DIFFERS if len(lines) == len(ends) and snapped + added == 2 * len(ends) else FAIL,
                  f"{len(lines)} lines; {snapped} of {2 * len(ends)} ends snapped to the curves"
                  + (f", {added} attached afterwards with Coincident" if added else ""))
        return lines

    def ag_copy_up(self):
        self._ag_up = self.ag_copy([0, 1, 2, 3], 0, AG_UP, "Move Curve: the 4 curves, Distance 0.5 along YC, Copy "
                                   "Original", "up")

    def ag_join_wall(self):
        up = self._ag_up
        if len(up) != 4:
            self.step("Join the two ends with lines: the casing wall", "-", FAIL, "no copies to join")
            return
        self._ag_reversed |= {n for g, n in zip([0, 1, 2, 3], up) if g in self._ag_reversed}
        self._ag_wall = self.ag_join([((0, "s"), (up[0], "s")), ((3, "e"), (up[3], "e"))],
                                     "Join the end points at the two ends: the casing wall is closed")

    def ag_copy_down(self):
        self._ag_down = self.ag_copy([0, 1, 2, 3], 0, AG_DOWN, "Move Curve: the lower curve, -1.5 along YC, Copy "
                                     "Original", "down")

    def ag_join_edge(self):
        down = self._ag_down
        if len(down) != 4:
            self.step("Straight lines join it with the inside curve", "-", FAIL, "no copies to join")
            return
        self._ag_reversed |= {n for g, n in zip([0, 1, 2, 3], down) if g in self._ag_reversed}
        self._ag_edge_lines = self.ag_join([((0, "s"), (down[0], "s")), ((3, "e"), (down[3], "e"))],
                                           "Straight lines join it with the inside curve: a closed chain")

    def ag_flange(self):
        lines = getattr(self, "_ag_edge_lines", [])
        if len(lines) != 2:
            self.step("Move Curve: the end line, -0.5 along XC, Copy Original", "-", FAIL, "no end line")
            self._ag_flange = []
            return
        self._ag_flange = self.ag_copy([lines[1]], AG_FLANGE, 0, "Move Curve: the outer end line, -0.5 along XC, "
                                       "Copy Original", "flange")

    def ag_flange_join(self):
        if len(self._ag_flange) != 1:
            self.step("Straight lines join the two lines: the flange", "-", FAIL, "no copied line")
            return
        f, r = self._ag_flange[0], self._ag_edge_lines[1]
        self._ag_flange_lines = self.ag_join([((f, "s"), (r, "s")), ((f, "e"), (r, "e"))],
                                             "Straight lines join the two lines: the flange's rectangle")

    def ag_check(self):
        sk = self._ag_sk
        curves = [g for g in range(len(sk.Geometry)) if self.ag_kind(g) in ("line", "arc")]
        a = sk.getPoint(0, 1).x
        missing = self.ag_geo_match(ag_reference(a))
        dof, _, msg = self.sk_state(sk)
        self.step("The sketch: 19 curves (the casing wall, its edge, the flange)", "compared with the book's figure",
                  SAME if len(curves) == 19 and not missing else FAIL,
                  f"{len(curves)} curves; {'all 19 match the book' if not missing else f'missing {missing}'}; DoF {dof} "
                  f"('{msg}'): the copies keep no constraints, like NX's non-associative copies. The next chapter "
                  "revolves the wall and the flange about the X axis and extrudes the edge")
        self.ag_shot("AG2_casing_sketch.png")

    def ag_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1200

    def ag_save(self):
        left = self.edited_sketch() is None
        self.step("Finish Sketch", "Ctrl+Q", SAME if left else FAIL, f"sketch edit ended {left}")
        outcome, how, detail, path = self.save_ctrl_s("Impeller_lower_casing.FCStd")
        self.step("Save and close the file", how, outcome, detail)
        self.wait = 300

    def ag_fit(self):
        self.fit()

    def ag_show(self):
        self.show("AG_impeller_lower_casing")


# ================================================================== AH: Impeller (3.5.3)
# The book (p. 48-49), inches: points at the origin and at (11.75, 6); an arc by centre about each, R1.5 and
# R0.5; arcs by 3 points joining their top ends (R18) and their bottom ends (R15); every joint tangent.
AH_P2, AH_R0, AH_R1, AH_RU, AH_RL = (11.75 * IN, 6 * IN), 1.5 * IN, 0.5 * IN, 18 * IN, 15 * IN


def ah_geometry():
    """The four arcs, solved from the book's data: {name: (centre, radius, end, end)}. The R18 arc passes above
    both end arcs (outside it: centre distances R18 + r), the R15 arc below them (inside it: R15 - r)."""
    import math
    V = App.Vector
    c0, c1 = V(0, 0, 0), V(*AH_P2, 0)

    def centre(d0, d1):
        """The point d0 from c0 and d1 from c1, above the line between them."""
        d = (c1 - c0).Length
        a = (d0 ** 2 - d1 ** 2 + d ** 2) / (2 * d)
        u = (c1 - c0) * (1 / d)
        return c0 + u * a + V(-u.y, u.x, 0) * math.sqrt(d0 ** 2 - a ** 2)
    cu, cl = centre(AH_RU + AH_R0, AH_RU + AH_R1), centre(AH_RL - AH_R0, AH_RL - AH_R1)

    def toward(c, p, r):
        return c + (p - c).normalize() * r
    u0, u1 = toward(c0, cu, AH_R0), toward(c1, cu, AH_R1)            # where the R18 arc touches the ends
    l0, l1 = c0 - (cl - c0).normalize() * AH_R0, c1 - (cl - c1).normalize() * AH_R1   # the R15 arc's
    return {"end R1.5": (c0, AH_R0, u0, l0), "end R0.5": (c1, AH_R1, l1, u1),
            "top R18": (cu, AH_RU, u0, u1), "bottom R15": (cl, AH_RL, l0, l1)}


class MstImpellerTutorials:
    """Mixin for tutorial.Replay: tutorial AH. The sketch helpers of AG work on self._ag_sk."""

    def AH_STEPS(self):
        return [self.p_modeling, self.ah_new, self.ah_sketch, self.ah_plane, self.ah_points, self.ah_fix_point,
                self.ah_end_arcs, self.ah_rim_arcs, self.ah_tangent, self.ah_fixed, self.ah_radii,
                self.ah_finish, self.ah_save, self.ah_fit, self.ah_show]

    def ah_new(self):
        self.tutorial = "AH: Impeller (NX 12 for Engineering Design, 3.5.3; book in inches, typed in mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def ah_sketch(self):
        new = set(App.listDocuments()) - self._docs_before
        self.step("Create a new file in inches (Impeller_impeller)", "Ctrl+N, Model template",
                  SAME if new and self.body() else FAIL, f"new document {sorted(new)}")
        self.units_step()
        Gui.Selection.clearSelection()
        b, self._ah_where = self.click_ribbon("Sketch")
        self.wait = 1500

    def ah_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.wait_for("ah: sketch in edit", lambda: self.edited_sketch() is not None)
        sk = self.edited_sketch()
        self.step("Sketch on the XC-YC plane, OK", f"ribbon '{self._ah_where} > Sketch', plane row + MB2",
                  SAME if picked and sk is not None else FAIL, f"picked {picked}")
        if sk is None:
            raise RuntimeError("no sketch in edit; tutorial AH cannot continue")
        self._ag_sk = sk
        self._ag_reversed = set()
        self.wait = 600

    def ah_frame(self):
        """Frame the impeller once FreeCAD's camera has stopped moving."""
        from .tutorial import qtest
        last = None
        for _ in range(40):
            pos = tuple(self.view().getCameraNode().position.getValue())
            if pos == last:
                break
            last = pos
            qtest().qWait(100)
        self.frame_sketch(self._ag_sk, 5.5 * IN, 3 * IN, 13 * IN)
        QtWidgets.QApplication.processEvents()

    def ah_points(self):
        """Point: one at the origin, one at (11.75, 6), typed into FreeCAD's on-view fields when it shows them."""
        from .qt import QtCore
        from .smoke import decode
        from .tutorial import qtest
        sk = self._ag_sk
        self.ah_frame()
        b, where = self.click_ribbon("Point", tab="Sketch")
        QtWidgets.QApplication.processEvents()
        self.mb1_click(self.screen_point(sk, 0, 0))
        view = self.nav().widget
        p = self.screen_point(sk, *AH_P2)
        self.send(QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton)
        qtest().qWait(200)
        area = QtCore.QRect(view.mapToGlobal(QtCore.QPoint(0, 0)), view.size())
        dock = self.tasks_dock()
        ovp = [w for w in Gui.getMainWindow().findChildren(QtWidgets.QAbstractSpinBox) if w.isVisible()
               and not dock.isAncestorOf(w) and area.contains(w.mapToGlobal(w.rect().center()))]
        n0 = len(sk.Geometry)
        typed = len(ovp) >= 2
        if typed:                              # the x and y fields, in that order
            for w, v in zip(ovp[:2], AH_P2):
                w.setFocus()
                w.lineEdit().selectAll()
                qtest().keyClicks(w.lineEdit(), self.typed_number(w, v))
                qtest().keyClick(w.lineEdit(), *decode("Return"))
                qtest().qWait(150)
        if len(sk.Geometry) == n0:
            self.mb1_click(p)
        self.mb2_click(self.screen_point(sk, -3 * IN, 9 * IN))
        App.ActiveDocument.recompute()
        pts = [g for g in range(len(sk.Geometry)) if self.ag_kind(g) == "point"]
        self._ah_pts = pts
        self.info["AH points"] = {"on-view fields": [f"{type(w).__name__}:{w.text()}" for w in ovp], "typed": typed,
                                  "points": [tuple(round(c / IN, 4) for c in sk.getPoint(g, 1)[:2]) for g in pts]}
        q = sk.getPoint(pts[1], 1) if len(pts) > 1 else None
        exact = q is not None and abs(q.x - AH_P2[0]) < 1e-6 and abs(q.y - AH_P2[1]) < 1e-6
        self._ah_exact = exact
        self.step("Point: one at (0, 0, 0), one at (11.75, 6, 0)", f"ribbon '{where} > Point', MB1 at the origin, "
                  + ("the coordinates typed in the on-view fields" if typed else "MB1 at (11.75, 6)"),
                  SAME if len(pts) == 2 and exact else DIFFERS if len(pts) == 2 else FAIL,
                  f"{len(pts)} points; the second at ({q.x / IN:.4f}, {q.y / IN:.4f}) in" if q is not None else
                  f"{len(pts)} points" + ("" if typed else "; FreeCAD shows no coordinate fields for a point (its "
                                          "on-view parameters are set to dimensions only), so the click is approximate"))

    def ah_fix_point(self):
        """(not in the book) Where the point could not be typed: its coordinates as horizontal and vertical
        distances from the origin, FreeCAD's commands (the Sketch tab has no Horizontal or Vertical Distance)."""
        if self._ah_exact or len(self._ah_pts) < 2:
            return
        sk = self._ag_sk
        v = self.ag_vertex(self._ah_pts[1], 1)
        dx = self.ag_run_with_value("Sketcher_ConstrainDistanceX", ["RootPoint", v], AH_P2[0])
        dy = self.ag_run_with_value("Sketcher_ConstrainDistanceY", ["RootPoint", v], AH_P2[1])
        q = sk.getPoint(self._ah_pts[1], 1)
        ok = dx == 1 and dy == 1 and abs(q.x - AH_P2[0]) < 1e-6 and abs(q.y - AH_P2[1]) < 1e-6
        self.step("(not in the book) Put the second point at (11.75, 6) exactly",
                  "origin + point, FreeCAD's Horizontal Distance 298.45 and Vertical Distance 152.4 (not on the "
                  "Sketch tab)", DIFFERS if ok else FAIL, f"point at ({q.x / IN:.4f}, {q.y / IN:.4f}) in. NX "
                  "creates a point at typed coordinates")

    def ah_arc_centre(self, c, r, a0, a1):
        """Arc (A, by centre and end points): click the centre, the start, sweep anticlockwise, click the end."""
        import math
        from .qt import QtCore
        sk = self._ag_sk
        n0 = len(sk.Geometry)
        self.key("A")
        QtWidgets.QApplication.processEvents()
        at = lambda deg: self.screen_point(sk, c[0] + r * math.cos(math.radians(deg)),  # noqa: E731
                                           c[1] + r * math.sin(math.radians(deg)))
        self.mb1_click(self.screen_point(sk, *c))
        self.mb1_click(at(a0))
        for k in range(1, 12):                 # the pointer moves round, as a hand does
            self.send(QtCore.QEvent.MouseMove, at(a0 + (a1 - a0) * k / 12), Qt.NoButton, Qt.NoButton)
            QtWidgets.QApplication.processEvents()
        self.mb1_click(at(a1))
        self.mb2_click(self.screen_point(sk, -3 * IN, 9 * IN))
        App.ActiveDocument.recompute()
        return n0 if len(sk.Geometry) > n0 else None

    def ah_end_arcs(self):
        geo = ah_geometry()
        a = self.ah_arc_centre((0, 0), AH_R0, 105, 255)      # ends clear of the Y axis, which would catch them
        b = self.ah_arc_centre(AH_P2, AH_R1, -31, 133)
        self._ah_end = [a, b]
        sk = self._ag_sk
        ok = a is not None and b is not None and all(self.ag_kind(g) == "arc" for g in (a, b))
        centres = [sk.Geometry[g].Center for g in (a, b) if g is not None]
        on = ok and (centres[0] - geo["end R1.5"][0]).Length < 1e-6 and (centres[1] - geo["end R0.5"][0]).Length < 1e-6
        self.step("Arc by Center and Endpoints: R1.5 about the origin point, R0.5 about the other point",
                  "A key, MB1 on the centre point, the start, round to the end, MB2 (twice)",
                  SAME if ok and on else FAIL,
                  f"arcs {'made' if ok else 'missing'}; centres on the points {on}; radii "
                  f"{', '.join(f'{sk.Geometry[g].Radius / IN:.3f}' for g in (a, b) if g is not None)} in (sized below)")

    def ah_rim_arcs(self):
        """Arc by 3 Points: the two ends, then a point between them."""
        from .tutorial import qtest
        sk = self._ag_sk
        a, b = self._ah_end
        # FreeCAD stores arcs anticlockwise: the R1.5 arc runs from its top end to its bottom end, the R0.5 arc
        # from its bottom end to its top end
        top = (sk.getPoint(a, 1), sk.getPoint(b, 2))
        bottom = (sk.getPoint(a, 2), sk.getPoint(b, 1))
        made, where = [], None
        drop = next((x for x in self.ah_arc_actions() if "3" in x or "three" in x.lower() or "rim" in x.lower()), None)
        modes = []
        for (p, q), rim in ((top, (6.103 * IN, 2.905 * IN)), (bottom, (7.031 * IN, 0.610 * IN))):
            n0 = len(sk.Geometry)
            if drop:
                where = self.click_dropdown("Arc", drop)
            else:                      # FreeCAD's Arc (A) switches to end points and rim point with M
                self.key("A")
                QtWidgets.QApplication.processEvents()
                self.key("M")
                qtest().qWait(150)
                modes.append([c.currentText() for c in self.tasks_dock().findChildren(QtWidgets.QComboBox)
                              if c.isVisible()][:3])
            qtest().qWait(200)
            self.mb1_click(self.screen_point(sk, p.x, p.y))
            self.mb1_click(self.screen_point(sk, q.x, q.y))
            self.mb1_click(self.screen_point(sk, *rim))
            self.mb2_click(self.screen_point(sk, -3 * IN, 9 * IN))
            App.ActiveDocument.recompute()
            made.append(n0 if len(sk.Geometry) > n0 else None)
        self._ah_rim = made
        coin = sum(1 for c in sk.Constraints if c.Type in ("Coincident", "Tangent") and
                   {c.First, c.Second} & {a, b} and {c.First, c.Second} & set(g for g in made if g is not None))
        self.info["AH arc dropdown"] = {"entries": self.ah_arc_actions(), "tool modes after M": modes}
        how = f"ribbon '{where} > Arc' dropdown > '{drop}'" if drop else "A key, M (end points and rim point)"
        ok = None not in made and coin == 4
        self.step("Arc by 3 Points: the top end points, then a point between; the same for the bottom",
                  f"{how}, MB1 on both end points and between, MB2 (twice)",
                  (SAME if drop else DIFFERS) if ok else FAIL,
                  f"arcs made {[g is not None for g in made]}; {coin} of 4 ends snapped to the end arcs"
                  + ("" if drop else "; the ribbon's Arc button offers no Arc by 3 Points, so FreeCAD's Arc tool "
                                     "is switched to it with M"))

    def ah_arc_actions(self):
        from .ribbon import DropdownButton
        r = self.shell.ribbon
        for i in range(r.stack.count()):
            for b in r.stack.widget(i).findChildren(DropdownButton):
                if b.text() == "Arc":
                    return [a.text() for a in b.menu().actions()]
        return []

    def ah_tangent(self):
        sk = self._ag_sk
        a, b = self._ah_end
        u, lo = self._ah_rim
        made = []
        for x, y in ((a, u), (u, b), (b, lo), (lo, a)):
            if x is None or y is None:
                continue
            if not any(c.Type == "Tangent" and {c.First, c.Second} == {x, y} for c in sk.Constraints):
                d, where = self.sk_constrain(sk, "Tangent", [self.ag_edge(x), self.ag_edge(y)])
                made.append(d)
        n = sum(1 for x, y in ((a, u), (u, b), (b, lo), (lo, a))
                if any(c.Type == "Tangent" and {c.First, c.Second} == {x, y} for c in sk.Constraints))
        dof, _, msg = self.sk_state(sk)
        self.step("Constraints: every arc Tangent to the next at its end points", "two arcs + ribbon 'Tangent', 4 times",
                  SAME if n == 4 else FAIL, f"{n} of 4 joints tangent ({sum(made)} added); DoF {dof}")

    def ah_fixed(self):
        sk = self._ag_sk
        p = self._ah_pts[0] if self._ah_pts else None
        on = p is not None and any(c.Type == "Coincident" and {(c.First, c.FirstPos), (c.Second, c.SecondPos)} ==
                                   {(p, 1), (-1, 1)} for c in sk.Constraints)
        self.step("The point at the origin: Fixed", "no click needed: the point snapped to the origin" if on else "-",
                  DIFFERS if on else FAIL, "FreeCAD's Coincident with the origin already fixes it; Fixed on top would "
                  "be redundant" if on else "the point is not on the origin")

    def ah_radii(self):
        sk = self._ag_sk
        a, b = self._ah_end
        u, lo = self._ah_rim
        if None in (a, b, u, lo):
            self.step("Rapid Dimension: the radii 1.5 and 0.5 at the ends, 18 and 15 between", "-", FAIL,
                      "an arc is missing, so there is nothing to dimension")
            return
        made, direct = [], []
        for name, g, value in (("R18", u, AH_RU), ("R15", lo, AH_RL), ("R1.5", a, AH_R0), ("R0.5", b, AH_R1)):
            d, where = self.sk_constrain(sk, "Radius / Diameter", [self.ag_edge(g)], value)
            if d == 0:
                d = self.ag_run_with_value("Sketcher_ConstrainRadius", [self.ag_edge(g)], value)
                direct.append(name)
            made.append(name + ("" if d == 1 else " (not made)"))
        dof, full, msg = self.sk_state(sk)
        geo = ah_geometry()
        errs = {}
        for name, g in (("end R1.5", a), ("end R0.5", b), ("top R18", u), ("bottom R15", lo)):
            c, r, p, q = geo[name]
            s, e = sk.getPoint(g, 1), sk.getPoint(g, 2)
            errs[name] = max((sk.Geometry[g].Center - c).Length, abs(sk.Geometry[g].Radius - r),
                             min(max((s - p).Length, (e - q).Length), max((s - q).Length, (e - p).Length)))
        worst = max(errs.values())
        self.step("Rapid Dimension: the radii 1.5 and 0.5 at the ends, 18 and 15 between",
                  "arc + ribbon 'Radius / Diameter', the value typed in FreeCAD's dialog, 4 times",
                  (DIFFERS if direct else SAME) if "not made" not in "".join(made) and worst < 1e-6 else FAIL,
                  f"{', '.join(made)}; DoF {dof} ('{msg}'); every arc within {worst:.1e} mm of the solved figure "
                  "(centres, radii, ends)" + (f"; Radius / Diameter was greyed out, so FreeCAD's Radius command was "
                                              f"run for {', '.join(direct)}" if direct else ""))
        self.ag_shot("AH1_impeller_sketch.png")

    def ah_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1200

    def ah_save(self):
        left = self.edited_sketch() is None
        self.step("Finish Sketch", "Ctrl+Q", SAME if left else FAIL, f"sketch edit ended {left}")
        outcome, how, detail, path = self.save_ctrl_s("Impeller_impeller.FCStd")
        self.step("Save and close the file", how, outcome, detail)
        self.wait = 300

    def ah_fit(self):
        self.fit()

    def ah_show(self):
        self.show("AH_impeller")


# ================================================================== AJ: Circular Base (exercise 3.6.1)
# The book's top view (p. 50), mm: a disc R60 with four slots ending in semicircles. The top slot is 30 wide
# and its semicircle's centre 31.905 below the rim; the others 17 wide, 30.605 in from the rim (only the right
# one is dimensioned; the figure draws the left and bottom ones the same). The book gives no thickness: 20 is
# assumed (the assembly picture in 6.6.1 shows it about a third of the 60 mm base).
AJ_R, AJ_T, AJ_OUT = 60.0, 20.0, 75.0
AJ_SLOTS = [("top", (0, 1), 15.0, 60 - 31.905), ("right", (1, 0), 8.5, 60 - 30.605),
            ("bottom", (0, -1), 8.5, 60 - 30.605), ("left", (-1, 0), 8.5, 60 - 30.605)]


def aj_reference(slots=True):
    import math
    import Part
    V = App.Vector
    solid = Part.makeCylinder(AJ_R, AJ_T)
    if not slots:
        return solid
    for _name, (dx, dy), w, c in AJ_SLOTS:
        cut = Part.makeBox(2 * w, AJ_OUT + 5 - c, AJ_T, V(-w, c, 0)).fuse(Part.makeCylinder(w, AJ_T, V(0, c, 0)))
        cut.rotate(V(0, 0, 0), V(0, 0, 1), math.degrees(math.atan2(dy, dx)) - 90)
        solid = solid.cut(cut)
    return solid.removeSplitter()


def aj_profile(d, w, c):
    """The slot's U as drawn: down one side from outside the disc, the semicircle, up the other side, back."""
    dx, dy = d
    nx, ny = -dy, dx
    at = lambda u, v: (dx * u + nx * v, dy * u + ny * v)  # noqa: E731
    return [at(AJ_OUT, w), at(c, w), at(c, -w), at(AJ_OUT, -w), at(AJ_OUT, w)]


class MstCircularBaseTutorials:
    """Mixin for tutorial.Replay: tutorial AJ (the AG sketch helpers work on self._ag_sk)."""

    def AJ_STEPS(self):
        return [self.p_modeling, self.aj_new, self.aj_extrude, self.aj_plane, self.aj_circle, self.aj_finish,
                self.aj_disc_dialog, self.aj_face, self.aj_slots, self.aj_slot_constraints, self.aj_slots_finish,
                self.aj_slots_dialog, self.aj_save, self.aj_fit, self.aj_show]

    def aj_settle(self, cx=0.0, cy=0.0, height=180.0):
        from .tutorial import qtest
        last = None
        for _ in range(40):
            pos = tuple(self.view().getCameraNode().position.getValue())
            if pos == last:
                break
            last = pos
            qtest().qWait(100)
        self.frame_sketch(self._ag_sk, cx, cy, height)
        QtWidgets.QApplication.processEvents()

    def aj_new(self):
        self.tutorial = "AJ: Circular Base (NX 12 for Engineering Design, exercise 3.6.1)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def aj_extrude(self):
        new = set(App.listDocuments()) - self._docs_before
        self.step("A new part (mm)", "Ctrl+N, Model template", SAME if new and self.body() else FAIL,
                  f"new document {sorted(new)}")
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def aj_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.step("Extrude (X), sketch on the XC-YC plane", "X key, plane row + MB2", SAME if picked else FAIL,
                  f"picked {picked}")
        self.wait = 1500

    def aj_circle(self):
        sk = self.ae_sketch_in_edit("disc")
        self._ag_sk = sk
        self.aj_settle()
        e = AJ_R * 0.7071
        _, tool, n, ended = self.draw_clicks("O", [(0, 0), (e, e)])
        circ = next((g for g in range(len(sk.Geometry)) if "Circle" in sk.Geometry[g].TypeId), None)
        if circ is None:
            self.step("The disc: a circle R60 about the origin", "O key, MB1 at the origin and on the rim", FAIL,
                      f"no circle; tool {tool}")
            return
        on = any(c.Type == "Coincident" and {(c.First, c.FirstPos), (c.Second, c.SecondPos)} == {(circ, 3), (-1, 1)}
                 for c in sk.Constraints)
        d, where = self.sk_constrain(sk, "Radius / Diameter", [f"Edge{circ + 1}"], AJ_R)
        direct = d == 0
        if direct:
            d = self.ag_run_with_value("Sketcher_ConstrainRadius", [f"Edge{circ + 1}"], AJ_R)
        g = sk.Geometry[circ]
        dof, _, _ = self.sk_state(sk)
        ok = tool and on and d == 1 and abs(g.Radius - AJ_R) < 1e-9 and g.Center.Length < 1e-9 and dof == 0
        self.step("The disc: a circle R60 about the origin", "O key, MB1 at the origin and on the rim, MB2; circle + "
                  "'Radius / Diameter' = 60", (DIFFERS if direct else SAME) if ok else FAIL,
                  f"centre snapped to the origin {on}; radius {g.Radius:g} mm; DoF {dof}"
                  + ("; Radius / Diameter was greyed out, so FreeCAD's Radius command was run" if direct else ""))

    def aj_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def aj_disc_dialog(self):
        self.ae_wait_box("aj_disc_dialog")
        shown, _, status, ok = self.ae_panel()
        field = self.ae_type(AJ_T)
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        self.wait_for("aj_disc_dialog closed", lambda: not self.ae_ctl().busy())
        same, how = self.ae_compare(self.body(), aj_reference(slots=False))
        one, steps = self.ae_one_step("new_body", "Extrude")
        self.step("Finish Sketch, Extrude 20 (the book gives no thickness), Boolean None", f"Ctrl+Q; '{field}' = "
                  "20 mm, MB2 = OK", SAME if shown == "None" and same and one else FAIL,
                  f"Boolean '{shown}'; {how}; {steps}")
        self.wait = 600

    def aj_face(self):
        self.ae_face_extrude(AJ_T, "slots")

    def aj_slots(self):
        """Profile (Z) for each slot: down one side, M three times for the tangent semicircle, back up the other
        side (a tangent line), across outside the disc to the first point; MB2."""
        from .tutorial import qtest
        sk = self.ae_sketch_in_edit("slots")
        self._ag_sk = sk
        place = sk.getGlobalPlacement()
        self.aj_settle()
        self._aj_geo = {}
        report = []
        for name, d, w, c in AJ_SLOTS:
            pts = [self.g2s_mm(sk, x, y, AJ_T) for x, y in aj_profile(d, w, c)]
            n0 = len(sk.Geometry)
            self.key("Z")
            QtWidgets.QApplication.processEvents()
            for i, (x, y) in enumerate(pts):
                if i == 2:                                    # the semicircle's end: a tangent arc
                    for _ in range(self.AF_ARC_PRESSES):
                        self.key("M")
                        qtest().qWait(50)
                self.mb1_click(self.screen_point(sk, x, y))
            self.mb2_click(self.screen_point(sk, -90, 90))
            if self.nav().sketch_tool_active():
                self.mb2_click(self.screen_point(sk, -90, 90))
            App.ActiveDocument.recompute()
            geo = list(range(n0, len(sk.Geometry)))
            self._aj_geo[name] = geo
            kinds = [self.ag_kind(g) for g in geo]
            report.append(f"{name} {kinds}")
        ok = all([self.ag_kind(g) for g in geo] == ["line", "arc", "line", "line"] for geo in self._aj_geo.values())
        self.info["AJ slots sketch"] = {"placement": str(place), "curves": report}
        self.step("On the top face: a U for each slot with Profile (Z), the semicircle as a tangent arc",
                  "select the top face + X; per slot Z, 5 MB1 clicks (M three times before the semicircle's end), MB2",
                  SAME if ok else FAIL, "; ".join(report) + f"; sketch origin at {tuple(round(v, 3) for v in place.Base)}")

    def aj_slot_constraints(self):
        """Each slot: closed, its sides parallel to the slot's axis, the semicircle's centre on that axis, its
        radius, and the centre's distance from the middle. Lines added by hand where Profile left them out."""
        sk = self._ag_sk
        repairs, made, direct = [], 0, []
        for name, d, w, c in AJ_SLOTS:
            geo = self._aj_geo.get(name, [])
            if len(geo) != 4:
                continue
            l1, arc, l2, l3 = geo
            ux, uy = (lambda p, q: (q[0] - p[0], q[1] - p[1]))(self.g2s_mm(sk, 0, 0, AJ_T),
                                                                  self.g2s_mm(sk, d[0], d[1], AJ_T))
            along_x = abs(ux) > abs(uy)
            side = "Horizontal" if along_x else "Vertical"
            axis = "H_Axis" if along_x else "V_Axis"
            closed = any(cc.Type == "Coincident" and {(cc.First, cc.FirstPos), (cc.Second, cc.SecondPos)} ==
                         {(l3, 2), (l1, 1)} for cc in sk.Constraints)
            if not closed:
                k, _ = self.sk_constrain(sk, "Coincident", [self.ag_vertex(l3, 2), self.ag_vertex(l1, 1)])
                repairs.append(f"{name}: closed by Coincident ({k})")
            for ln in (l1, l2):
                if not any(cc.Type == side and cc.First == ln for cc in sk.Constraints):
                    k, _ = self.sk_constrain(sk, side, [self.ag_edge(ln)])
                    repairs.append(f"{name}: {side} on a side ({k})")
            k1, _ = self.sk_constrain(sk, "Coincident", [self.ag_vertex(arc, 3), axis])
            k2, _ = self.sk_constrain(sk, "Radius / Diameter", [self.ag_edge(arc)], w)
            if k2 == 0:
                k2 = self.ag_run_with_value("Sketcher_ConstrainRadius", [self.ag_edge(arc)], w)
                direct.append(name)
            k3, _ = self.sk_constrain(sk, "Distance", [self.ag_vertex(arc, 3), "RootPoint"], c)
            made += k1 + k2 + k3
        dof, _, msg = self.sk_state(sk)
        errs = []
        for name, d, w, c in AJ_SLOTS:
            geo = self._aj_geo.get(name, [])
            if len(geo) == 4:
                g = sk.Geometry[geo[1]]
                want = App.Vector(*self.g2s_mm(sk, d[0] * c, d[1] * c, AJ_T), 0)
                errs.append(max((g.Center - want).Length, abs(g.Radius - w)))
        worst = max(errs) if errs else None
        self.step("Each semicircle's centre on its axis, its radius, and its distance from the middle",
                  "centre + axis + 'Coincident', arc + 'Radius / Diameter', centre + origin + 'Distance', per slot",
                  (DIFFERS if direct or repairs else SAME) if made == 12 and worst is not None and worst < 1e-6
                  else FAIL,
                  f"{made} of 12 constraints; semicircles within {worst if worst is None else f'{worst:.1e}'} mm; "
                  f"DoF {dof} (the outer ends stay free outside the disc)"
                  + (f"; added by hand: {'; '.join(repairs)}" if repairs else "")
                  + (f"; Radius / Diameter greyed out, FreeCAD's Radius run for {', '.join(direct)}" if direct else ""))
        self.ag_shot("AJ1_slots_sketch.png")

    def aj_slots_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def aj_slots_dialog(self):
        doc = App.ActiveDocument
        self.ae_wait_box("aj_slots_dialog")
        picked = self.set_combo("nxBoolean", "Subtract")
        self.ae_wait_box("aj_slots_dialog: Subtract", lambda: any(o.TypeId == "PartDesign::Pocket" for o in doc.Objects))
        shown, _, status, ok = self.ae_panel()
        field = self.ae_type(AJ_T)
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        self.wait_for("aj_slots_dialog closed", lambda: not self.ae_ctl().busy())
        same, how = self.ae_compare(self.body(), aj_reference())
        one, steps = self.ae_one_step("subtract", "Extrude")
        self.step("Finish Sketch, Extrude the four slots through, Boolean Subtract", f"Ctrl+Q; Boolean '{picked}', "
                  f"'{field}' = 20 mm, MB2 = OK", SAME if shown == "Subtract" and same and one else FAIL,
                  f"Boolean '{shown}'; {how}; {steps}")
        self.wait = 600

    def aj_save(self):
        outcome, how, detail, path = self.save_ctrl_s("Circular_base.FCStd")
        self.step("Save", how, outcome, detail)
        self.wait = 300

    def aj_fit(self):
        self.fit()

    def aj_show(self):
        self.show("AJ_circular_base")
