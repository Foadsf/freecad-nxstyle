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
  AJ  3.6.1 Circular Base: a disc R60 extruded, four U slots sketched on its face, cut with Extrude Subtract
  AK  3.6.2 Holder (a sketch, inches typed in mm): circles and their diameters, the bolt circle as a reference
      curve, the outline trimmed with Quick Trim, one arm of the cross and one lug, each copied round the origin
      with Rotate Curve; the 29 curves compared with the book's figure

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
        return [self.p_modeling, self.ag_new, self.ag_sketch, self.ag_plane, self.ag_profile, self.ag_point, self.ag_tangent, self.ag_dimensions, self.ag_hide, self.ag_copy_up, self.ag_join_wall,
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
        """Frame the casing (frame_sketch waits for FreeCAD's camera animation into the sketch to end)."""
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
        # next starts free (3 presses to a tangent arc); after an arc it starts tangent (3 presses too, and 2 to a
        # free line, NX's Line, which gets its Horizontal; the Tangent step adds that joint's tangency)
        presses = {2: self.AF_ARC_PRESSES, 3: 3, 4: self.AF_LINE_PRESSES}
        trace = []
        for i, (x, y) in enumerate(AG_ROUGH):
            for _ in range(presses.get(i, 0)):
                self.key("M")
                qtest().qWait(50)
            n0 = len(sk.Constraints)
            self.mb1_click(self.screen_point(sk, x * IN, y * IN))
            trace.append({"click": i, "geo": len(sk.Geometry), "new": [f"{c.Type} {c.First}/{c.FirstPos} {c.Second}/"
                                                                        f"{c.SecondPos}" for c in sk.Constraints[n0:]]})
        away = self.screen_point(sk, -12 * IN, 4 * IN)
        self.mb2_click(away)
        ended = not self.sketch_tool_running(away)
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
        horizontal = [any(c.Type == "Horizontal" and c.First == g for c in sk.Constraints) for g in (0, 3)]
        self.info["AG profile clicks"] = trace
        dof, _, _ = self.sk_state(sk)
        self.step("Profile: Line 1, Curve 1, Curve 2, Line 2", f"Z key, 5 MB1 clicks, M ({self.AF_ARC_PRESSES}x) before "
                  f"Curve 1's end, 3x before Curve 2's and {self.AF_LINE_PRESSES}x before Line 2's (NX's Line), MB2",
                  SAME if tool and ended and kinds == ["line", "arc", "arc", "line"] and tangents == 2 and all(horizontal)
                  else FAIL, f"curves {kinds}; tangent joints {tangents} (Line 1-Curve 1, Curve 1-Curve 2; Line 2 is "
                  f"drawn as a plain line); Horizontal on Line 1 {horizontal[0]}, on Line 2 {horizontal[1]}; tool ended "
                  f"by MB2 {ended}; DoF {dof}")
        self.wait = 300

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
        made, where = [], {}
        for name, label, subs, value in dims:
            d, w = self.sk_constrain(sk, label, subs, value)
            where[label] = w
            made.append(name + ("" if d == 1 else " (not made)"))
        dof, full, msg = self.sk_state(sk)
        a = sk.getPoint(0, 1).x
        missing = self.ag_geo_match(ag_chain(a))
        self.info["AG dimensions"] = {"made": made, "solver": msg, "missing": missing}
        self.step("Dimensions: p1 15, p2 7.3, R 33, R 8, p6 8.1, p4 1.0", "picks + ribbon "
                  f"'{where.get('Distance', '')} > Distance' and 'Radius / Diameter', each value typed in FreeCAD's "
                  "dimension dialog (biggest first)",
                  SAME if all("not made" not in m for m in made) and dof == 1 and not missing else FAIL,
                  f"{', '.join(made)}; DoF {dof} ('{msg}'): only the position along X is left free, as in the book; "
                  f"the four curves {'match' if not missing else 'differ from'} the book's figure"
                  + (f" ({missing})" if missing else ""))
        self.ag_shot("AG1_dimensioned_curve.png")

    def sketch_menu(self, entry, at):
        """MB3 on empty space of the sketch: FreeCAD's sketch menu opens (modal); pick the entry, as a user does.
        Returns the menu's entries."""
        from .qt import QtCore
        from .ribbon import clean_text
        from .tutorial import qtest
        seen = {"tries": 0}

        def read():
            m = QtWidgets.QApplication.activePopupWidget()
            if isinstance(m, QtWidgets.QMenu):
                seen["items"] = [clean_text(a.text()) for a in m.actions() if a.text()]
                act = next((a for a in m.actions() if clean_text(a.text()) == entry), None)
                m.close()
                if act is not None:
                    act.trigger()
            elif seen["tries"] < 30:
                seen["tries"] += 1
                QtCore.QTimer.singleShot(100, read)
        QtCore.QTimer.singleShot(150, read)
        self.send(QtCore.QEvent.MouseMove, at, Qt.NoButton, Qt.NoButton)
        self.send(QtCore.QEvent.MouseButtonPress, at, Qt.RightButton, Qt.RightButton)
        self.send(QtCore.QEvent.MouseButtonRelease, at, Qt.RightButton, Qt.NoButton)
        for _ in range(40):
            if "items" in seen:
                break
            qtest().qWait(100)
        QtWidgets.QApplication.processEvents()
        return seen.get("items", [])

    def ag_hide(self):
        sk = self._ag_sk
        dims = [i for i, c in enumerate(sk.Constraints) if c.Type in ("Distance", "Radius", "Diameter", "DistanceX",
                                                                       "DistanceY")]
        Gui.Selection.clearSelection()
        for i in dims:
            Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, f"Constraint{i + 1}")
        QtWidgets.QApplication.processEvents()
        # FreeCAD hides the sketch object itself while it is edited (its visibility automation) and shows it
        # again on Finish: Hide must leave that alone
        before = sk.ViewObject.Visibility
        items = self.sketch_menu("Hide", self.screen_point(sk, -12 * IN, 4 * IN))
        hidden = [i for i in dims if sk.getVirtualSpace(i)]
        same = sk.ViewObject.Visibility == before
        self.info["AG MB3 menu on the dimensions"] = items
        self.step("Select all the dimensions, MB3 > Hide", "dimensions selected, MB3 on empty space > Hide",
                  SAME if dims and len(hidden) == len(dims) and same else FAIL,
                  f"{len(hidden)} of {len(dims)} dimensions hidden (FreeCAD's 'virtual space'); the sketch's own "
                  f"visibility untouched {same}; menu {items}")
        self.ag_shot("AG1b_dimensions_hidden.png")

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
        shown = self._ag_sk.ViewObject.Visibility
        self.step("Finish Sketch", "Ctrl+Q", SAME if left and shown else FAIL,
                  f"sketch edit ended {left}; the sketch is shown {shown} (its dimensions stay hidden)")
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
        """Frame the impeller (frame_sketch waits for FreeCAD's camera to stop moving)."""
        self.frame_sketch(self._ag_sk, 5.5 * IN, 3 * IN, 13 * IN)
        QtWidgets.QApplication.processEvents()

    def ah_type_point(self, xy):
        """With the Point tool running: type XC and YC into FreeCAD's positional on-view fields (NX's input boxes),
        Enter after each; Enter in the second makes the point. Returns the fields' texts, or None when FreeCAD
        shows no coordinate fields (then the point is clicked)."""
        from . import sketch_ui
        from .qt import QtCore
        from .smoke import decode
        from .tutorial import qtest
        sk = self._ag_sk
        view = self.nav().widget
        p = self.screen_point(sk, *xy)
        # the pointer rests clear of the origin and the axes: FreeCAD adds the snap under the pointer as well,
        # and a snap to the origin on top of the typed (0, 0) is a redundant second Coincident
        near = p + QtCore.QPoint(45, -40)
        self.send(QtCore.QEvent.MouseMove, near, Qt.NoButton, Qt.NoButton)
        qtest().qWait(200)
        texts = [w.text() for w in sketch_ui.on_view_fields(view)]
        fields = sketch_ui.xy_fields(sk, view, near)     # as a user reads them: FreeCAD orders them freely
        n0 = len(sk.Geometry)
        for w, v in zip(fields or (), xy):
            w.setFocus()
            w.lineEdit().selectAll()
            qtest().keyClicks(w.lineEdit(), self.typed_number(w, v))
            qtest().keyClick(w.lineEdit(), *decode("Return"))
            qtest().qWait(150)
        self._ah_clicked = len(sk.Geometry) == n0
        if self._ah_clicked:                   # no fields typed (or not taken): place it with a click
            self.mb1_click(p if not fields else near)
        return texts if fields else None

    def ah_points(self):
        """Point: one on the origin, one at (11.75, 6), typed into FreeCAD's positional on-view fields (NX-Style's
        profile shows them, as NX's XC and YC boxes)."""
        sk = self._ag_sk
        self.ah_frame()
        b, where = self.click_ribbon("Point", tab="Sketch")
        QtWidgets.QApplication.processEvents()
        # the origin point is clicked (it snaps to the origin): typed 0, 0 gets FreeCAD 1.1.4's Coincident with the
        # origin twice (the solver flags the second redundant), and the arcs drawn on later then take no snaps
        self.mb1_click(self.screen_point(sk, 0, 0))
        fields, clicked = [None], [True]
        fields.append(self.ah_type_point(AH_P2))
        clicked.append(self._ah_clicked)
        self.mb2_click(self.screen_point(sk, -3 * IN, 9 * IN))
        App.ActiveDocument.recompute()
        pts = [g for g in range(len(sk.Geometry)) if self.ag_kind(g) == "point"]
        self._ah_pts = pts
        typed = fields[1] is not None
        held = [sorted(c.Type for c in sk.Constraints if g in (c.First, c.Second)) for g in pts]
        self.info["AH points"] = {"on-view fields": fields, "typed": typed, "clicked after typing": clicked,
                                  "constraints on each point": held,
                                  "points": [tuple(round(c / IN, 4) for c in sk.getPoint(g, 1)[:2]) for g in pts]}
        q = sk.getPoint(pts[1], 1) if len(pts) > 1 else None
        o = sk.getPoint(pts[0], 1) if pts else None
        exact = q is not None and abs(q.x - AH_P2[0]) < 1e-9 and abs(q.y - AH_P2[1]) < 1e-9 and o.Length < 1e-9
        self._ah_exact = exact
        sk.solve()
        redundant = list(sk.RedundantConstraints)
        self.step("Point: one at (0, 0, 0), one at (11.75, 6, 0)", f"ribbon '{where} > Point', MB1 on the origin, "
                  + ("then XC and YC typed in the on-view fields" if typed else "then MB1 at (11.75, 6)"),
                  SAME if len(pts) == 2 and exact and typed and not redundant else
                  DIFFERS if len(pts) == 2 and not redundant else FAIL,
                  (f"{len(pts)} points, at ({o.x / IN:.4f}, {o.y / IN:.4f}) and ({q.x / IN:.4f}, {q.y / IN:.4f}) in; "
                   f"FreeCAD keeps typed coordinates as constraints: {held}; redundant {redundant}") if q is not None else
                  f"{len(pts)} points" + ("" if typed else "; FreeCAD showed no coordinate fields, so the clicks are "
                                          "approximate"))

    def ah_fix_point(self):
        """(not in the book) Only where the coordinates could not be typed: the second point's horizontal and
        vertical distances from the origin, from the Sketch tab's Linear Dimension."""
        if self._ah_exact or len(self._ah_pts) < 2:
            return
        sk = self._ag_sk
        v = self.ag_vertex(self._ah_pts[1], 1)
        dx, where = self.sk_constrain(sk, "Linear Dimension", ["RootPoint", v], AH_P2[0], entry="Horizontal")
        dy, _ = self.sk_constrain(sk, "Linear Dimension", ["RootPoint", v], AH_P2[1], entry="Vertical")
        q = sk.getPoint(self._ah_pts[1], 1)
        ok = dx == 1 and dy == 1 and abs(q.x - AH_P2[0]) < 1e-6 and abs(q.y - AH_P2[1]) < 1e-6
        self.step("(not in the book) Put the second point at (11.75, 6) exactly",
                  f"origin + point, ribbon '{where} > Linear Dimension' > Horizontal 298.45 and > Vertical 152.4",
                  DIFFERS if ok else FAIL, f"point at ({q.x / IN:.4f}, {q.y / IN:.4f}) in. NX creates a point at "
                  "typed coordinates")

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
        entries = self.dropdown_entries("Arc", "Sketch")
        drop = next((x for x in entries if "3" in x or "three" in x.lower() or "rim" in x.lower()), None)
        modes = []
        for (p, q), rim in ((top, (6.103 * IN, 2.905 * IN)), (bottom, (7.031 * IN, 0.610 * IN))):
            n0 = len(sk.Geometry)
            if drop:
                where = self.click_dropdown("Arc", drop, tab="Sketch")
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
        self.info["AH arc dropdown"] = {"entries": entries, "tool modes after M": modes}
        how = f"ribbon '{where} > Arc' dropdown > '{drop}'" if drop else "A key, M (end points and rim point)"
        ok = None not in made and coin == 4
        self.step("Arc by 3 Points: the top end points, then a point between; the same for the bottom",
                  f"{how}, MB1 on both end points and between, MB2 (twice)",
                  (SAME if drop else DIFFERS) if ok else FAIL,
                  f"arcs made {[g is not None for g in made]}; {coin} of 4 ends snapped to the end arcs"
                  + ("" if drop else "; the ribbon's Arc button offers no Arc by 3 Points, so FreeCAD's Arc tool "
                                     "is switched to it with M"))

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
        self.step("The point at the origin: Fixed", "no click needed: the point is Coincident with the origin" if on
                  else "-",
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
        made = []
        for name, g, value in (("R18", u, AH_RU), ("R15", lo, AH_RL), ("R1.5", a, AH_R0), ("R0.5", b, AH_R1)):
            d, where = self.sk_constrain(sk, "Radius / Diameter", [self.ag_edge(g)], value)
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
                  SAME if "not made" not in "".join(made) and worst < 1e-6 else FAIL,
                  f"{', '.join(made)}; DoF {dof} ('{msg}'); every arc within {worst:.1e} mm of the solved figure "
                  "(centres, radii, ends)")
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
        """Frame the sketch (frame_sketch waits for FreeCAD's camera to stop moving)."""
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
        # on a full circle the button's default (auto radius/diameter) makes a diameter: R60 is the radial method,
        # picked from the drop-down as in NX's Radial Dimension (FreeCAD remembers it for the next clicks)
        entry = "Constrain radius"
        d, where = self.sk_constrain(sk, "Radius / Diameter", [f"Edge{circ + 1}"], AJ_R, entry=entry)
        kind = sk.Constraints[-1].Type if d else None
        g = sk.Geometry[circ]
        dof, _, _ = self.sk_state(sk)
        ok = (tool and on and d == 1 and kind == "Radius" and abs(g.Radius - AJ_R) < 1e-9 and g.Center.Length < 1e-9
              and dof == 0)
        self.step("The disc: a circle R60 about the origin", "O key, MB1 at the origin and on the rim, MB2; circle + "
                  f"'Radius / Diameter' drop-down > '{entry}' = 60", SAME if ok else FAIL,
                  f"centre snapped to the origin {on}; {kind} constraint; radius {g.Radius:g} mm; DoF {dof}")

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
        repairs, made = [], 0
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
                  (DIFFERS if repairs else SAME) if made == 12 and worst is not None and worst < 1e-6 else FAIL,
                  f"{made} of 12 constraints; semicircles within {worst if worst is None else f'{worst:.1e}'} mm; "
                  f"DoF {dof} (the outer ends stay free outside the disc)"
                  + (f"; added by hand: {'; '.join(repairs)}" if repairs else ""))
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


# ================================================================== AK: Holder (exercise 3.6.2)
# The book's figure (p. 50), inches: circles Ø0.75, Ø2.00 and Ø2.76 about the origin; the outline a Ø3.50
# circle and a 5.50 x 3.50 rectangle to its right, cut by a 0.50 slot along the X axis; a cross 0.25 wide
# between the Ø0.75 and Ø2.76 circles; three lugs on a Ø4.50 bolt circle 120° apart, each a hole Ø0.38 in an
# R0.38 end, its sides tangent to it and 1.00 apart where they meet the Ø3.50 circle (the sides of the
# lugs at 60° and 300° end on that circle too, inside the rectangle, as at 180°).
AK_D = {"hole": 0.75 * IN, "inner": 2.00 * IN, "ring": 2.76 * IN, "outer": 3.50 * IN}
AK_BOLT, AK_LEN, AK_SLOT, AK_CROSS = 4.50 * IN, 5.50 * IN, 0.50 * IN, 0.25 * IN
AK_LUG_R, AK_LUG_HOLE, AK_LUG_W = 0.38 * IN, 0.38 * IN, 1.00 * IN
AK_LUGS = (180.0, 300.0, 60.0)          # the first is drawn, the others are its Rotate Curve copies


def ak_rot(p, deg):
    import math
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return App.Vector(c * p[0] - s * p[1], s * p[0] + c * p[1], 0)


def ak_lug(deg):
    """One lug, its axis at deg: (side end, tangent point, tangent point, side end, centre); the first side is
    the one at -w across the axis, as Profile draws it."""
    import math
    r, w = AK_D["outer"] / 2, AK_LUG_W / 2
    a = math.sqrt(r * r - w * w)             # where the sides meet the Ø3.50 circle
    cx = AK_BOLT / 2
    t = math.atan2(w, a - cx) - math.acos(AK_LUG_R / math.hypot(a - cx, w))
    tu, tv = cx + AK_LUG_R * math.cos(t), AK_LUG_R * math.sin(t)
    return [ak_rot(p, deg) for p in ((a, -w), (tu, -tv), (tu, tv), (a, w), (cx, 0))]


def ak_reference():
    """The finished sketch: (kind, start, end, centre, radius); circles have no ends."""
    import math
    V = App.Vector
    ref = [("circle", None, None, V(0, 0, 0), AK_D[k] / 2) for k in ("hole", "inner", "ring")]
    r, h, L = AK_D["outer"] / 2, AK_SLOT / 2, AK_LEN
    a = math.sqrt(r * r - h * h)
    ref += [("arc", V(a, h, 0), V(a, -h, 0), V(0, 0, 0), r),
            ("line", V(0, r, 0), V(L, r, 0), None, 0), ("line", V(L, r, 0), V(L, -r, 0), None, 0),
            ("line", V(L, -r, 0), V(0, -r, 0), None, 0),
            ("line", V(a, h, 0), V(L, h, 0), None, 0), ("line", V(a, -h, 0), V(L, -h, 0), None, 0)]
    w = AK_CROSS / 2
    b, c = math.sqrt((AK_D["hole"] / 2) ** 2 - w * w), math.sqrt((AK_D["ring"] / 2) ** 2 - w * w)
    for k in range(4):
        for s in (w, -w):
            ref.append(("line", ak_rot((b, s), 90 * k), ak_rot((c, s), 90 * k), None, 0))
    for deg in AK_LUGS:
        p0, t0, t1, p1, cc = ak_lug(deg)
        ref += [("line", p0, t0, None, 0), ("arc", t0, t1, cc, AK_LUG_R), ("line", t1, p1, None, 0),
                ("circle", None, None, cc, AK_LUG_HOLE / 2)]
    return ref


class MstHolderTutorials:
    """Mixin for tutorial.Replay: tutorial AK (the AG sketch helpers work on self._ag_sk)."""

    def AK_STEPS(self):
        return [self.p_modeling, self.ak_new, self.ak_sketch, self.ak_plane, self.ak_circles, self.ak_bolt_circle,
                self.ak_outline, self.ak_slot, self.ak_trim, self.ak_arm, self.ak_arm_rotate, self.ak_lug_profile,
                self.ak_lug_constraints, self.ak_lug_hole, self.ak_lug_rotate, self.ak_check, self.ak_finish,
                self.ak_save, self.ak_fit, self.ak_show]

    # ------------------------------------------------------------- helpers
    def ak_frame(self, cx=1.4 * IN, cy=0.0, w=8.8 * IN, h=5.6 * IN):
        """Frame a w x h window of the sketch (frame_sketch waits for the camera to stop moving)."""
        v = self.nav().widget
        aspect = v.height() / max(v.width(), 1)
        self.frame_sketch(self._ag_sk, cx, cy, max(h, w * aspect))
        QtWidgets.QApplication.processEvents()

    def ak_shot(self, name):
        """A picture of the whole holder (the sketch's own bounding box is stale while it is edited)."""
        from .tutorial import qtest
        self.ak_frame(1.4 * IN, 0, 9.4 * IN, 6.4 * IN)
        qtest().qWait(400)                  # the 3D view redraws on a timer, after the camera has moved
        self.shot(name)

    def ak_away(self):
        return self.screen_point(self._ag_sk, -2.8 * IN, -2.6 * IN)

    def ak_end_tool(self):
        """MB2 ends the tool; a second MB2 where FreeCAD's continuous mode restarted it."""
        away = self.ak_away()
        self.mb2_click(away)
        if self.sketch_tool_running(away):
            self.mb2_click(away)
        App.ActiveDocument.recompute()

    def ak_on(self, g, pos, target):
        """Whether the end pos of g lies on target (a curve index, -1 the X axis, -2 the Y axis) by a constraint."""
        return any(c.Type == "PointOnObject" and c.First == g and c.FirstPos == pos and c.Second == target
                   for c in self._ag_sk.Constraints)

    def ak_put_on(self, g, pos, target):
        """Point on Curve where the click did not snap the end onto target; returns 1 if one was added."""
        if self.ak_on(g, pos, target):
            return 0
        sub = {-1: "H_Axis", -2: "V_Axis"}.get(target, f"Edge{target + 1}")
        d, _ = self.sk_constrain(self._ag_sk, "Point on Curve", [self.ag_vertex(g, pos), sub])
        return d

    def ak_red(self):
        """FreeCAD's redundant and conflicting constraints (1-based, as its panel lists them), if any."""
        sk = self._ag_sk
        red, con = list(sk.RedundantConstraints), list(sk.ConflictingConstraints)
        return (f"; redundant {red}" if red else "") + (f"; conflicting {con}" if con else "")

    def ak_kind_entry(self, word):
        """The Radius / Diameter drop-down entry for word ('radius' or 'diameter')."""
        entries = self.dropdown_entries("Radius / Diameter", "Sketch")
        other = "radius" if word == "diameter" else "diameter"
        return next((e for e in entries if word in e.lower() and other not in e.lower()), None)

    def ak_missing(self, ref, tol=1e-3):
        """Reference curves with no sketch curve of the same kind, place and radius."""
        sk = self._ag_sk
        have = []
        for g, geo in enumerate(sk.Geometry):
            if sk.getConstruction(g):
                continue
            t = geo.TypeId
            if "ArcOfCircle" in t:
                have.append(("arc", sk.getPoint(g, 1), sk.getPoint(g, 2), geo.Center, geo.Radius))
            elif "Circle" in t:
                have.append(("circle", None, None, geo.Center, geo.Radius))
            elif "Line" in t:
                have.append(("line", sk.getPoint(g, 1), sk.getPoint(g, 2), None, 0))

        def same(h, r):
            if h[0] != r[0] or abs(h[4] - r[4]) > tol:
                return False
            if r[3] is not None and (h[3] - r[3]).Length > tol:
                return False
            if r[1] is None:
                return True
            return ((h[1] - r[1]).Length < tol and (h[2] - r[2]).Length < tol) or \
                ((h[1] - r[2]).Length < tol and (h[2] - r[1]).Length < tol)
        out = []
        for r in ref:
            if not any(same(h, r) for h in have):
                where = r[3] if r[1] is None else r[1]
                out.append(f"{r[0]} at ({where.x / IN:.3f}, {where.y / IN:.3f}) in")
        return out, len(have)

    def ak_ovp(self):
        """FreeCAD's on-view fields in the 3D view (not the task panel)."""
        from .qt import QtCore
        view = self.nav().widget
        area = QtCore.QRect(view.mapToGlobal(QtCore.QPoint(0, 0)), view.size())
        dock = self.tasks_dock()
        return [w for w in Gui.getMainWindow().findChildren(QtWidgets.QAbstractSpinBox) if w.isVisible()
                and not dock.isAncestorOf(w) and area.contains(w.mapToGlobal(w.rect().center()))]

    def ak_rotate(self, geos, copies, angle, what):
        """Rotate Curve with copies (NX: Pattern Curve, circular): select the curves, the ribbon button, Copies
        in the tool panel, the centre on the origin, then the angles typed into FreeCAD's on-view fields
        (the start angle 0, then copies x angle). Returns (new curves, ribbon tab, typed)."""
        import math
        from .smoke import decode
        from .tutorial import qtest
        sk = self._ag_sk
        n0 = len(sk.Geometry)
        self.ak_frame()
        Gui.Selection.clearSelection()
        for g in geos:
            Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, self.ag_edge(g))
        QtWidgets.QApplication.processEvents()
        b, where = self.click_ribbon("Rotate Curve", tab="Sketch")
        qtest().qWait(300)
        tool = self.nav().sketch_tool_active()
        dock = self.tasks_dock()
        panel = [f"{type(w).__name__} {w.objectName()}='{getattr(w, 'text', lambda: '')()}'"
                 for w in dock.findChildren(QtWidgets.QWidget) if w.isVisible()
                 and isinstance(w, (QtWidgets.QLabel, QtWidgets.QAbstractSpinBox, QtWidgets.QCheckBox))
                 and len(str(getattr(w, 'text', lambda: '')())) < 60]
        spin = next((w for w in dock.findChildren(QtWidgets.QAbstractSpinBox)
                     if w.objectName() == "parameterOne" and w.isVisible()), None)
        if spin is not None:
            self.type_into(spin, copies)
        self.mb1_click(self.screen_point(sk, 0, 0))
        qtest().qWait(200)
        # one angle field at a time: the start angle, then the angle the copies are spread over (FreeCAD's angle
        # is the total: 3 copies over 270° are 90° apart). A typed value is locked; the click after it confirms it
        r = 2.0 * IN
        seen, typed = [], 0
        for value in (0.0, angle * copies):
            fields = [w for w in self.ak_ovp() if w.text().strip().endswith("°")]
            seen.append([f"{type(w).__name__}:{w.text()}" for w in self.ak_ovp()])
            if fields:
                w = fields[0]
                w.setFocus()
                w.lineEdit().selectAll()
                qtest().keyClicks(w.lineEdit(), self.typed_number(w, value))
                qtest().keyClick(w.lineEdit(), *decode("Return"))
                qtest().qWait(150)
                typed += 1
            if len(sk.Geometry) == n0 and self.nav().sketch_tool_active():
                self.mb1_click(self.screen_point(sk, r * math.cos(math.radians(value)), r * math.sin(math.radians(value))))
                qtest().qWait(200)
        still = self.nav().sketch_tool_active()
        if still:
            self.ak_end_tool()
        App.ActiveDocument.recompute()
        new = list(range(n0, len(sk.Geometry)))
        self.info[f"AK Rotate Curve {what}"] = {"tool": tool, "panel": panel[:30], "copies field": spin is not None,
                                                "on-view fields": seen, "typed": typed,
                                                "new curves": len(new), "tool open after": still}
        return new, where, typed == 2

    def ak_rotated_error(self, geos, new, angle):
        """Largest distance of the copies from the originals rotated k x angle (ends either way round)."""
        sk = self._ag_sk
        n = len(geos)
        err = 0.0
        for k in range(len(new) // n):
            for g, c in zip(geos, new[k * n:(k + 1) * n]):
                ends = (3, 3) if self.ag_kind(g) not in ("line", "arc") else (1, 2)    # a circle: its centre
                a, b = (ak_rot(sk.getPoint(g, p), angle * (k + 1)) for p in ends)
                p, q = sk.getPoint(c, ends[0]), sk.getPoint(c, ends[1])
                err = max(err, min(max((a - p).Length, (b - q).Length), max((a - q).Length, (b - p).Length)))
        return err

    # ------------------------------------------------------------- New, Sketch
    def ak_new(self):
        self.tutorial = "AK: Holder (NX 12 for Engineering Design, exercise 3.6.2; book in inches, typed in mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def ak_sketch(self):
        new = set(App.listDocuments()) - self._docs_before
        self.step("A new part in inches (Holder)", "Ctrl+N, Model template", SAME if new and self.body() else FAIL,
                  f"new document {sorted(new)}")
        self.units_step()
        Gui.Selection.clearSelection()
        b, self._ak_where = self.click_ribbon("Sketch")
        self.wait = 1500

    def ak_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.wait_for("ak: sketch in edit", lambda: self.edited_sketch() is not None)
        sk = self.edited_sketch()
        self.step("Sketch on the XC-YC plane, OK", f"ribbon '{self._ak_where} > Sketch', plane row + MB2",
                  SAME if picked and sk is not None else FAIL, f"picked {picked}")
        if sk is None:
            raise RuntimeError("no sketch in edit; tutorial AK cannot continue")
        self._ag_sk = sk
        self._ag_reversed = set()
        self.wait = 600

    # ------------------------------------------------------------- circles
    def ak_circles(self):
        """Circle (O), four times about the origin: centre, then a point on the rim (lower right, clear of the
        curves drawn later); then their diameters, biggest first."""
        sk = self._ag_sk
        self.ak_frame()
        self.key("O")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        names = ("hole", "inner", "ring", "outer")
        for name in names:
            r = AK_D[name] / 2
            self.mb1_click(self.screen_point(sk, 0, 0))
            self.mb1_click(self.screen_point(sk, r * 0.7071, -r * 0.7071))
        self.ak_end_tool()
        circles = [g for g in range(len(sk.Geometry)) if "Circle" in sk.Geometry[g].TypeId]
        if len(circles) != 4:
            self._ak_c = {}
            self.step("Circles Ø0.75, Ø2.00, Ø2.76 and Ø3.50 about the origin", "O key, MB1 at the origin and on the "
                      "rim, 4 times, MB2", FAIL, f"{len(circles)} circles; tool {tool}")
            return
        self._ak_c = dict(zip(names, sorted(circles, key=lambda g: sk.Geometry[g].Radius)))
        entry = self.ak_kind_entry("diameter")
        made = []
        for name in reversed(names):
            d, where = self.sk_constrain(sk, "Radius / Diameter", [self.ag_edge(self._ak_c[name])], AK_D[name],
                                         entry=entry)
            made.append(f"Ø{AK_D[name] / IN:.2f}" + ("" if d == 1 and sk.Constraints[-1].Type == "Diameter"
                                                    else " (not made)"))
        dof, _, msg = self.sk_state(sk)
        err = max(max(sk.Geometry[g].Center.Length, abs(2 * sk.Geometry[g].Radius - AK_D[n]))
                  for n, g in self._ak_c.items())
        ok = tool and "not made" not in "".join(made) and err < 1e-6 and dof == 0
        self.step("Circles Ø0.75, Ø2.00, Ø2.76 and Ø3.50 about the origin", "O key, MB1 at the origin and on the "
                  f"rim, 4 times, MB2; each circle + 'Radius / Diameter' drop-down > '{entry}', biggest first",
                  SAME if ok else FAIL, f"{', '.join(made)}; largest error {err:.1e} mm (centres on the origin, "
                  f"diameters); DoF {dof}")

    def ak_bolt_circle(self):
        """The Ø4.50 bolt circle, a reference curve (NX: Convert To/From Reference)."""
        sk = self._ag_sk
        r = AK_BOLT / 2
        self.ak_frame()
        n0 = len(sk.Geometry)
        self.key("O")
        QtWidgets.QApplication.processEvents()
        self.mb1_click(self.screen_point(sk, 0, 0))
        self.mb1_click(self.screen_point(sk, -r * 0.7071, -r * 0.7071))
        self.ak_end_tool()
        g = n0 if len(sk.Geometry) > n0 else None
        self._ak_bolt = g
        if g is None:
            self.step("The Ø4.50 bolt circle, a reference curve", "O key, MB1 at the origin and on the rim, MB2", FAIL,
                      "no circle made")
            return
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, self.ag_edge(g))
        QtWidgets.QApplication.processEvents()
        b, where = self.click_ribbon("Convert To/From Reference", tab="Sketch")
        QtWidgets.QApplication.processEvents()
        App.ActiveDocument.recompute()
        ref = bool(sk.getConstruction(g))
        d, _ = self.sk_constrain(sk, "Radius / Diameter", [self.ag_edge(g)], AK_BOLT,
                                 entry=self.ak_kind_entry("diameter"))
        geo = sk.Geometry[g]
        dof, _, msg = self.sk_state(sk)
        ok = ref and d == 1 and geo.Center.Length < 1e-9 and abs(2 * geo.Radius - AK_BOLT) < 1e-6 and dof == 0
        self.step("The Ø4.50 bolt circle, a reference curve", "O key, MB1 at the origin and on the rim, MB2; circle + "
                  f"ribbon '{where} > Convert To/From Reference'; Diameter 4.50", SAME if ok else FAIL,
                  f"reference {ref}; diameter {2 * geo.Radius / IN:.4f} in; DoF {dof}")

    # ------------------------------------------------------------- the outline, the slot, Quick Trim
    def ak_outline(self):
        """Profile (Z): the rectangle's top, right and bottom sides, from the top of the Ø3.50 circle to its
        bottom; the ends held on the circle and the Y axis (tangent, since the sides are horizontal), and the
        length 5.50."""
        sk = self._ag_sk
        outer = self._ak_c.get("outer")
        r, L = AK_D["outer"] / 2, AK_LEN
        self.ak_frame()
        n0 = len(sk.Geometry)
        self.key("Z")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        for x, y in ((0, r), (L, r), (L, -r), (0, -r)):
            self.mb1_click(self.screen_point(sk, x, y))
        self.ak_end_tool()
        geo = list(range(n0, len(sk.Geometry)))
        kinds = [self.ag_kind(g) for g in geo]
        if kinds != ["line"] * 3 or outer is None:
            self._ak_rect = None
            self.step("Profile: the rectangle's three sides from the top of the Ø3.50 circle", "Z key, 4 MB1 "
                      "clicks, MB2", FAIL, f"curves {kinds}; tool {tool}")
            return
        top, right, bottom = geo
        self._ak_rect = geo
        hv = [any(c.Type == t and c.First == g for c in sk.Constraints)
              for g, t in ((top, "Horizontal"), (right, "Vertical"), (bottom, "Horizontal"))]
        # a click on the circle's top makes the side's end Tangent to it (on the circle, tangent there), which with
        # the side Horizontal puts the end at the top: Point on Curve with the circle or the Y axis is redundant
        tangent = {g for g in (top, bottom) if any(c.Type == "Tangent" and {c.First, c.Second} == {g, outer}
                                                    for c in sk.Constraints)}
        holds = [(g, p, t) for g, p in ((top, 1), (bottom, 2)) for t in (outer, -2) if g not in tangent]
        snapped = sum(self.ak_on(g, p, t) for g, p, t in holds) + 2 * len(tangent)
        added = sum(self.ak_put_on(g, p, t) for g, p, t in holds)
        d, where = self.sk_constrain(sk, "Distance", [self.ag_vertex(top, 2), "V_Axis"], L)
        dof, _, msg = self.sk_state(sk)
        missing, _ = self.ak_missing(ak_reference()[4:7])
        self.step("Profile: the rectangle's three sides from the top of the Ø3.50 circle to its bottom, 5.50 long",
                  f"Z key, 4 MB1 clicks, MB2; the ends + circle or Y axis + 'Point on Curve'; corner + Y axis + "
                  f"'{where} > Distance' 5.50",
                  SAME if all(hv) and d == 1 and dof == 0 and not missing else FAIL,
                  f"Horizontal/Vertical/Horizontal {hv}; {snapped} of 4 end holds made by the clicks "
                  f"({len(tangent)} as Tangent to the circle), {added} added; DoF {dof}{self.ak_red()}; the sides "
                  f"{'match' if not missing else f'differ: {missing}'}")

    def ak_slot(self):
        """Line (L), twice: the slot's sides from the Ø3.50 circle to the right side, 0.50 apart about the X axis."""
        sk = self._ag_sk
        outer, rect = self._ak_c.get("outer"), getattr(self, "_ak_rect", None)
        if outer is None or rect is None:
            self.step("Line: the 0.50 slot's two sides, from the circle to the right side", "-", FAIL, "no outline")
            self._ak_slot = None
            return
        import math
        r, h, L = AK_D["outer"] / 2, AK_SLOT / 2, AK_LEN
        a = math.sqrt(r * r - h * h)
        self.ak_frame()
        n0 = len(sk.Geometry)
        self.key("L")
        QtWidgets.QApplication.processEvents()
        for y in (h, -h):
            self.mb1_click(self.screen_point(sk, a, y))
            self.mb1_click(self.screen_point(sk, L, y))
        self.ak_end_tool()
        geo = [g for g in range(n0, len(sk.Geometry)) if self.ag_kind(g) == "line"]
        if len(geo) != 2:
            self._ak_slot = None
            self.step("Line: the 0.50 slot's two sides, from the circle to the right side", "L key, 4 MB1 clicks, MB2",
                      FAIL, f"{len(geo)} lines")
            return
        self._ak_slot = geo
        upper, lower = geo
        right = rect[1]
        horiz = [any(c.Type == "Horizontal" and c.First == g for c in sk.Constraints) for g in geo]
        for g in geo:
            if not any(c.Type == "Horizontal" and c.First == g for c in sk.Constraints):
                self.sk_constrain(sk, "Horizontal", [self.ag_edge(g)])
        snapped = sum(self.ak_on(g, p, t) for g in geo for p, t in ((1, outer), (2, right)))
        added = sum(self.ak_put_on(g, p, t) for g in geo for p, t in ((1, outer), (2, right)))
        d1, where = self.sk_constrain(sk, "Distance", [self.ag_vertex(upper, 1), self.ag_edge(lower)], AK_SLOT)
        d2, _ = self.sk_constrain(sk, "Distance", [self.ag_vertex(upper, 1), "H_Axis"], h)
        dof, _, msg = self.sk_state(sk)
        missing, _ = self.ak_missing(ak_reference()[7:9])
        self.step("Line: the 0.50 slot's two sides, from the circle to the right side", "L key, 4 MB1 clicks, MB2; "
                  f"'{where} > Distance' 0.50 between them and 0.25 from the X axis",
                  SAME if all(horiz) and d1 + d2 == 2 and dof == 0 and not missing else FAIL,
                  f"Horizontal as drawn {horiz}; {snapped} of 4 ends snapped to the circle or the side, {added} added; "
                  f"DoF {dof}; the sides {'match' if not missing else f'differ: {missing}'}")

    def ak_trim(self):
        """Quick Trim (T): the Ø3.50 circle between the slot's sides."""
        import math
        sk = self._ag_sk
        outer = self._ak_c.get("outer")
        if outer is None or getattr(self, "_ak_slot", None) is None:
            self.step("Quick Trim: the circle inside the slot", "-", FAIL, "no slot")
            self._ak_outer = None
            return
        r = AK_D["outer"] / 2
        self.ak_frame()
        n0 = len(sk.Geometry)

        def on_outer():
            return [f"{c.Type} {c.First}/{c.FirstPos} {c.Second}/{c.SecondPos}" for c in sk.Constraints
                    if outer in (c.First, c.Second)]
        before = on_outer()
        self.key("T")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        a = math.radians(4)                     # between the slot's sides, clear of the X axis
        self.mb1_click(self.screen_point(sk, r * math.cos(a), r * math.sin(a)))
        self.ak_end_tool()
        arcs = [g for g in range(len(sk.Geometry)) if "ArcOfCircle" in sk.Geometry[g].TypeId
                and abs(sk.Geometry[g].Radius - r) < 1e-6]
        circle_left = any("Circle" in g.TypeId and "Arc" not in g.TypeId and abs(g.Radius - r) < 1e-6
                          for g in sk.Geometry)
        self._ak_outer = arcs[0] if len(arcs) == 1 else None
        self.info["AK trim: the circle's constraints"] = {"before": before, "after": on_outer()}
        # Profile holds each side's end by Point on Curve plus Tangent, a partly redundant pair with the side
        # Horizontal; the trim sometimes drops one side's Tangent (3 of 4 runs), and that end would slide round the
        # arc. Tangent again (FreeCAD folds the pair into one end-point tangency: the count does not change)
        retangent = []
        rect = getattr(self, "_ak_rect", None)

        def tangent(g):
            return any(c.Type == "Tangent" and {c.First, c.Second} == {g, self._ak_outer} for c in sk.Constraints)
        if self._ak_outer is not None and rect:
            for g in (rect[0], rect[2]):
                if not tangent(g):
                    self.sk_constrain(sk, "Tangent", [self.ag_edge(g), self.ag_edge(self._ak_outer)])
                    retangent.append(f"{'top' if g == rect[0] else 'bottom'} side "
                                     f"({'tangent' if tangent(g) else 'not made'})")
        dof, _, msg = self.sk_state(sk)
        missing, _ = self.ak_missing(ak_reference()[3:4])
        held = 0
        if self._ak_outer is not None:
            g = self._ak_outer
            held = sum(1 for s in self._ak_slot if any(
                c.Type == "Coincident" and {(c.First, c.FirstPos), (c.Second, c.SecondPos)} & {(g, 1), (g, 2)}
                and {(c.First, c.FirstPos), (c.Second, c.SecondPos)} & {(s, 1)} for c in sk.Constraints))
        self.step("Quick Trim: the Ø3.50 circle between the slot's sides, MB2", "T key, MB1 on the circle inside the "
                  "slot, MB2" + ("; Tangent again where the trim dropped it" if retangent else ""),
                  (DIFFERS if retangent else SAME) if tool and self._ak_outer is not None and not circle_left
                  and not missing and held == 2 and dof == 0 and "not made" not in "".join(retangent) else FAIL,
                  f"{len(arcs)} arc R1.75, full circle left {circle_left}; its ends held to the slot's sides "
                  f"{held} of 2; DoF {dof} ('{msg}'){self.ak_red()}; geometry {n0} -> {len(sk.Geometry)}"
                  + (f"; FreeCAD's trim dropped a side's tangency, made Tangent again: {retangent}"
                     if retangent else "") + (f"; differs: {missing}" if missing else ""))

    # ------------------------------------------------------------- the cross
    def ak_arm(self):
        """Line (L), twice: one arm of the cross, from the Ø0.75 circle to the Ø2.76 circle, 0.25 wide about the
        X axis."""
        import math
        sk = self._ag_sk
        hole, ring = self._ak_c.get("hole"), self._ak_c.get("ring")
        w = AK_CROSS / 2
        b, c = math.sqrt((AK_D["hole"] / 2) ** 2 - w * w), math.sqrt((AK_D["ring"] / 2) ** 2 - w * w)
        self.ak_frame(0.85 * IN, 0, 2.2 * IN, 1.6 * IN)
        n0 = len(sk.Geometry)
        self.key("L")
        QtWidgets.QApplication.processEvents()
        for y in (w, -w):
            self.mb1_click(self.screen_point(sk, b, y))
            self.mb1_click(self.screen_point(sk, c, y))
        self.ak_end_tool()
        geo = [g for g in range(n0, len(sk.Geometry)) if self.ag_kind(g) == "line"]
        self._ak_arm = geo if len(geo) == 2 else None
        if self._ak_arm is None or hole is None or ring is None:
            self.step("Line: one arm of the cross, 0.25 wide, from the Ø0.75 circle to the Ø2.76 circle",
                      "L key, 4 MB1 clicks, MB2", FAIL, f"{len(geo)} lines")
            return
        upper, lower = geo
        for g in geo:
            if not any(cc.Type == "Horizontal" and cc.First == g for cc in sk.Constraints):
                self.sk_constrain(sk, "Horizontal", [self.ag_edge(g)])
        snapped = sum(self.ak_on(g, p, t) for g in geo for p, t in ((1, hole), (2, ring)))
        added = sum(self.ak_put_on(g, p, t) for g in geo for p, t in ((1, hole), (2, ring)))
        d1, where = self.sk_constrain(sk, "Distance", [self.ag_vertex(upper, 1), self.ag_edge(lower)], AK_CROSS)
        d2, _ = self.sk_constrain(sk, "Distance", [self.ag_vertex(upper, 1), "H_Axis"], w)
        dof, _, msg = self.sk_state(sk)
        missing, _ = self.ak_missing(ak_reference()[9:11])
        self.step("Line: one arm of the cross, 0.25 wide, from the Ø0.75 circle to the Ø2.76 circle",
                  f"L key, 4 MB1 clicks, MB2; '{where} > Distance' 0.25 between the lines and 0.125 from the X axis",
                  SAME if d1 + d2 == 2 and dof == 0 and not missing else FAIL,
                  f"{snapped} of 4 ends snapped to the circles, {added} added; DoF {dof}; the arm "
                  f"{'matches' if not missing else f'differs: {missing}'}")
        self.ak_shot("AK1_outline_and_arm.png")

    def ak_arm_rotate(self):
        arm = getattr(self, "_ak_arm", None)
        if arm is None:
            self.step("Rotate Curve: the arm, 3 copies 90° apart (NX: Pattern Curve, circular)", "-", FAIL, "no arm")
            return
        new, where, typed = self.ak_rotate(arm, 3, 90.0, "cross")
        err = self.ak_rotated_error(arm, new, 90.0) if len(new) == 6 else None
        dof, _, msg = self.sk_state(self._ag_sk)
        self.step("Rotate Curve: the arm, 3 copies 90° apart, about the origin (NX: Pattern Curve, circular)",
                  f"2 lines selected + ribbon '{where} > Rotate Curve', Copies 3, MB1 at the origin, 0° and 270° "
                  + ("typed in the on-view fields" if typed else "clicked"),
                  (SAME if typed else DIFFERS) if err is not None and err < 1e-3 else FAIL,
                  f"{len(new)} copies made; largest error {err if err is None else f'{err:.1e}'} mm; DoF {dof}")

    # ------------------------------------------------------------- the lugs
    def ak_lug_profile(self):
        """Profile (Z) for the lug at 180°: a side from the Ø3.50 circle, M three times for the tangent end
        arc, the other side (a tangent line) back to the circle; MB2."""
        from .tutorial import qtest
        sk = self._ag_sk
        p0, t0, t1, p1, cc = ak_lug(AK_LUGS[0])
        self.ak_frame(cc.x + 0.4 * IN, 0, 2.4 * IN, 1.8 * IN)
        n0 = len(sk.Geometry)
        self.key("Z")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        for i, p in enumerate((p0, t0, t1, p1)):
            if i == 2:
                for _ in range(self.AF_ARC_PRESSES):
                    self.key("M")
                    qtest().qWait(50)
            self.mb1_click(self.screen_point(sk, p.x, p.y))
        self.ak_end_tool()
        geo = list(range(n0, len(sk.Geometry)))
        kinds = [self.ag_kind(g) for g in geo]
        self._ak_lug = geo if kinds == ["line", "arc", "line"] else None
        tangents = sum(1 for c in sk.Constraints if c.Type == "Tangent" and {c.First, c.Second} <= set(geo))
        self.step("Profile: the lug at 180°, a side, the tangent end arc, the other side", "Z key, 4 MB1 clicks "
                  f"(M {self.AF_ARC_PRESSES}x before the arc's end), MB2",
                  SAME if tool and self._ak_lug is not None and tangents == 2 else FAIL,
                  f"curves {kinds}; tangent joints {tangents}")

    def ak_lug_constraints(self):
        """The end arc's centre on the bolt circle and the X axis, its radius 0.38, the sides' ends on the Ø3.50
        circle, 1.00 apart, and the sides equal."""
        sk = self._ag_sk
        lug, outer, bolt = getattr(self, "_ak_lug", None), getattr(self, "_ak_outer", None), getattr(self, "_ak_bolt", None)
        if lug is None or outer is None or bolt is None:
            self.step("The lug: centre on the bolt circle and the X axis, R0.38, sides 1.00 apart and equal", "-",
                      FAIL, "no lug, outer arc or bolt circle")
            return
        l1, arc, l2 = lug
        a1, a2 = self.ag_vertex(arc, 3), self.ag_edge(arc)
        made = []
        for name, label, subs, value, entry in (
                ("centre on the bolt circle", "Point on Curve", [a1, self.ag_edge(bolt)], None, None),
                ("centre on the X axis", "Point on Curve", [a1, "H_Axis"], None, None),
                ("R0.38", "Radius / Diameter", [a2], AK_LUG_R, self.ak_kind_entry("radius"))):
            d, where = self.sk_constrain(sk, label, subs, value, entry=entry)
            made.append(name + ("" if d == 1 else " (not made)"))
        snapped = sum(self.ak_on(g, p, outer) for g, p in ((l1, 1), (l2, 2)))
        added = sum(self.ak_put_on(g, p, outer) for g, p in ((l1, 1), (l2, 2)))
        for x, y in ((l1, arc), (arc, l2)):
            if not any(c.Type == "Tangent" and {c.First, c.Second} == {x, y} for c in sk.Constraints):
                d, _ = self.sk_constrain(sk, "Tangent", [self.ag_edge(x), self.ag_edge(y)])
                made.append("tangent added" + ("" if d == 1 else " (not made)"))
        d, where = self.sk_constrain(sk, "Distance", [self.ag_vertex(l1, 1), self.ag_vertex(l2, 2)], AK_LUG_W)
        made.append("1.00 between the sides' ends" + ("" if d == 1 else " (not made)"))
        d, _ = self.sk_constrain(sk, "Equal", [self.ag_edge(l1), self.ag_edge(l2)])
        made.append("sides Equal" + ("" if d == 1 else " (not made)"))
        dof, _, msg = self.sk_state(sk)
        ref = ak_reference()
        missing, _ = self.ak_missing(ref[17:20])
        self.step("The lug: centre on the bolt circle and the X axis, R0.38, the sides 1.00 apart and Equal",
                  "centre + bolt circle / X axis + 'Point on Curve', arc + 'Radius / Diameter' R0.38, the ends + "
                  f"'{where} > Distance' 1.00, the sides + 'Equal'",
                  SAME if "not made" not in "".join(made) and not missing else FAIL,
                  f"{'; '.join(made)}; {snapped} of 2 side ends snapped to the circle, {added} added; DoF {dof} "
                  f"('{msg}'); the lug {'matches' if not missing else f'differs: {missing}'}")

    def ak_lug_hole(self):
        """Circle (O): the Ø0.38 hole about the end arc's centre."""
        sk = self._ag_sk
        lug = getattr(self, "_ak_lug", None)
        if lug is None:
            self.step("Circle: the Ø0.38 hole about the lug's centre", "-", FAIL, "no lug")
            self._ak_hole = None
            return
        arc = lug[1]
        c = sk.Geometry[arc].Center
        r = AK_LUG_HOLE / 2
        self.ak_frame(c.x + 0.4 * IN, 0, 2.4 * IN, 1.8 * IN)
        n0 = len(sk.Geometry)
        self.key("O")
        QtWidgets.QApplication.processEvents()
        self.mb1_click(self.screen_point(sk, c.x, c.y))
        self.mb1_click(self.screen_point(sk, c.x - r * 0.7071, c.y + r * 0.7071))
        self.ak_end_tool()
        g = n0 if len(sk.Geometry) > n0 and "Circle" in sk.Geometry[n0].TypeId else None
        self._ak_hole = g
        if g is None:
            self.step("Circle: the Ø0.38 hole about the lug's centre", "O key, MB1 on the centre and the rim, MB2",
                      FAIL, "no circle made")
            return
        on = any(cc.Type == "Coincident" and {(cc.First, cc.FirstPos), (cc.Second, cc.SecondPos)} == {(g, 3), (arc, 3)}
                 for cc in sk.Constraints)
        if not on:
            self.sk_constrain(sk, "Coincident", [self.ag_vertex(g, 3), self.ag_vertex(arc, 3)])
        d, where = self.sk_constrain(sk, "Radius / Diameter", [self.ag_edge(g)], AK_LUG_HOLE,
                                     entry=self.ak_kind_entry("diameter"))
        geo = sk.Geometry[g]
        dof, _, msg = self.sk_state(sk)
        err = max((geo.Center - sk.Geometry[arc].Center).Length, abs(2 * geo.Radius - AK_LUG_HOLE))
        self.step("Circle: the Ø0.38 hole about the lug's centre", "O key, MB1 on the arc's centre and on the rim, MB2; "
                  "Diameter 0.38", (SAME if on else DIFFERS) if d == 1 and err < 1e-6 else FAIL,
                  f"centre {'snapped to' if on else 'held by Coincident on'} the arc's centre; error {err:.1e} mm; "
                  f"DoF {dof}")

    def ak_lug_rotate(self):
        lug, hole = getattr(self, "_ak_lug", None), getattr(self, "_ak_hole", None)
        if lug is None or hole is None:
            self.step("Rotate Curve: the lug and its hole, 2 copies 120° apart", "-", FAIL, "no lug")
            return
        geos = lug + [hole]
        new, where, typed = self.ak_rotate(geos, 2, 120.0, "lugs")
        err = self.ak_rotated_error(geos, new, 120.0) if len(new) == 8 else None
        dof, _, msg = self.sk_state(self._ag_sk)
        self.step("Rotate Curve: the lug and its hole, 2 copies 120° apart, about the origin (NX: Pattern Curve)",
                  f"4 curves selected + ribbon '{where} > Rotate Curve', Copies 2, MB1 at the origin, 0° and 240° "
                  + ("typed in the on-view fields" if typed else "clicked"),
                  (SAME if typed else DIFFERS) if err is not None and err < 1e-3 else FAIL,
                  f"{len(new)} copies made; largest error {err if err is None else f'{err:.1e}'} mm; DoF {dof}")

    def ak_check(self):
        sk = self._ag_sk
        ref = ak_reference()
        missing, n = self.ak_missing(ref)
        dof, _, msg = self.sk_state(sk)
        self.step(f"The sketch: {len(ref)} curves and the bolt circle", "compared with the book's figure",
                  SAME if n == len(ref) and not missing else FAIL,
                  f"{n} curves; {f'all {len(ref)} match the book' if not missing else f'missing {missing}'}; DoF {dof} "
                  f"('{msg}'){self.ak_red()}")
        self.ak_shot("AK2_holder_sketch.png")

    def ak_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1200

    def ak_save(self):
        left = self.edited_sketch() is None
        self.step("Finish Sketch", "Ctrl+Q", SAME if left else FAIL, f"sketch edit ended {left}")
        outcome, how, detail, path = self.save_ctrl_s("Holder.FCStd")
        self.step("Save the file", how, outcome, detail)
        self.wait = 300

    def ak_fit(self):
        self.fit()

    def ak_show(self):
        self.show("AK_holder")
