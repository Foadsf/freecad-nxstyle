# SPDX-License-Identifier: LGPL-2.1-or-later
"""Self-test of typed sketch points that meet (called from smoke.py; the repair is sketch_typed.py).

Two arcs (A) and a line (L) in the sketch in edit, every value typed in FreeCAD's on-view fields beside the
pointer, each typed point on the end of the curve before: one closed wire, a Coincident at each join, no gap above
1e-7 mm, no redundant constraint, and one Undo takes back the last curve. The same input with NX-Style's guard off
(FreeCAD 1.1.4 alone) is the negative control and must fail. Each run records what was typed, the constraints
FreeCAD wrote, its report-view messages and what the guard did (smoke.json info 'typed join ...')."""

import math
import traceback

import FreeCAD as App
import FreeCADGui as Gui

from .qt import Qt, QtCore, QtWidgets

ARC1 = ((0.0, 0.0), 63.5, 90.0, 90.0)          # centre, radius, start, sweep: (0, 63.5) to (-63.5, 0)
ARC2 = ((-50.8, 0.0), 12.7, 180.0, 180.0)      # from (-63.5, 0) under the X axis to (-38.1, 0)


def qwait(ms):
    from .tutorial import qtest
    qtest().qWait(ms)


def report_text():
    for t in Gui.getMainWindow().findChildren(QtWidgets.QTextEdit):
        p = t
        while p is not None and "Report" not in (p.objectName() or ""):
            p = p.parentWidget()
        if p is not None:
            return t.toPlainText()
    return ""


def rows(sk, n0=0):
    return [(i, c.Type, c.First, int(c.FirstPos), c.Second, int(c.SecondPos), repr(c.Value))
            for i, c in enumerate(sk.Constraints) if i >= n0]


class Drive:
    def __init__(self, smoke, sk):
        self.smoke, self.sk = smoke, sk
        self.f = smoke.nav()
        self.w = self.f.widget
        self.view = smoke.view()
        self.log = []

    def at(self, x, y):
        w = self.w
        dpr = w.devicePixelRatioF() if hasattr(w, "devicePixelRatioF") else 1.0
        sx, sy = self.view.getPointOnViewport(self.sk.getGlobalPlacement().multVec(App.Vector(x, y, 0)))
        return QtCore.QPoint(int(round(sx / dpr)), int(round(w.height() - sy / dpr)))

    def move(self, p, ms=150):
        self.smoke.send(self.f, QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton)
        qwait(ms)

    def key(self, k):
        from .tutorial import qtest
        mw = Gui.getMainWindow()
        app = QtWidgets.QApplication.instance()
        if app.activeWindow() is None and hasattr(app, "setActiveWindow"):
            app.setActiveWindow(mw)
        self.w.setFocus()
        qtest().keyClick(self.w, k)
        QtWidgets.QApplication.processEvents()

    def type_in(self, field, v):
        from .tutorial import qtest
        field.setFocus()
        field.lineEdit().selectAll()
        qtest().keyClicks(field.lineEdit(), f"{round(float(v), 9):.12g}".replace(".", field.locale().decimalPoint()))
        raw = field.property("rawValue")
        qtest().keyClick(field.lineEdit(), Qt.Key_Return)
        qwait(150)
        return raw

    def fields(self):
        from . import sketch_ui
        return sketch_ui.on_view_fields(self.w)

    def pre(self):
        """What FreeCAD preselects now (it looks for autoconstraints at the typed position through it)."""
        try:
            p = Gui.Selection.getPreselection()
            return f"{p.ObjectName}.{p.SubElementNames}" if p.ObjectName else None
        except Exception as e:
            return f"? {e}"

    def end_tool(self, p):
        self.smoke.send(self.f, QtCore.QEvent.MouseButtonPress, p, Qt.MiddleButton, Qt.MiddleButton)
        self.smoke.send(self.f, QtCore.QEvent.MouseButtonRelease, p, Qt.MiddleButton, Qt.NoButton)
        QtWidgets.QApplication.processEvents()
        qwait(150)

    def arc(self, c, r, a0, sweep, pointer_off=0.0):
        from . import sketch_ui
        pt = lambda deg: (c[0] + r * math.cos(math.radians(deg)), c[1] + r * math.sin(math.radians(deg)))  # noqa
        n0, k0 = len(self.sk.Geometry), len(self.sk.Constraints)
        rec = {"want": (c, r, a0, sweep)}
        r0 = len(report_text())
        self.key(Qt.Key_A)
        near = self.at(c[0] + r * 0.2, c[1] + r * 0.3)
        self.move(near)
        xy = sketch_ui.xy_fields(self.sk, self.w, near)
        rec["centre fields"] = bool(xy)
        if xy:
            rec["centre raw"] = [self.type_in(fw, v) for fw, v in zip(xy, c)]
        s = pt(a0)
        sp = self.at(s[0] + pointer_off, s[1] + pointer_off)
        self.move(sp)
        rec["pre at start pointer"] = self.pre()
        second = self.fields()[:2]
        rec["start shown"] = [sketch_ui.field_value(x) for x in second]
        if len(second) == 2:
            length = min(second, key=lambda x: abs(sketch_ui.field_value(x) - r))
            angle = next(x for x in second if x is not length)
            rec["start raw"] = [self.type_in(length, r), self.type_in(angle, a0)]
        rec["pre after start typed"] = self.pre()
        for k in range(1, 9):
            q = pt(a0 + sweep * k / 9)
            self.move(self.at(q[0] + pointer_off, q[1] + pointer_off), 20)
        e = pt(a0 + sweep)
        self.move(self.at(e[0] + pointer_off, e[1] + pointer_off))
        third = self.fields()
        rec["end shown"] = [sketch_ui.field_value(x) for x in third]
        if third:
            sw = min(third, key=lambda x: abs(sketch_ui.field_value(x) - sweep))
            rec["sweep raw"] = self.type_in(sw, sweep)
        self.end_tool(self.at(c[0] - r * 1.3, c[1] + r * 1.3))
        App.ActiveDocument.recompute()
        rec["report"] = report_text()[r0:][-600:]
        rec["made"] = list(range(n0, len(self.sk.Geometry)))
        rec["constraints"] = rows(self.sk, k0)
        self.log.append(rec)
        return rec["made"]

    def line(self, p1, p2, pointer_off=0.0):
        from . import sketch_ui
        n0, k0 = len(self.sk.Geometry), len(self.sk.Constraints)
        rec = {"want": (p1, p2)}
        r0 = len(report_text())
        self.key(Qt.Key_L)
        near = self.at(p1[0] + 3 + pointer_off, p1[1] + 4 + pointer_off)
        self.move(near)
        xy = sketch_ui.xy_fields(self.sk, self.w, near)
        rec["p1 fields"] = bool(xy)
        if xy:
            rec["p1 raw"] = [self.type_in(fw, v) for fw, v in zip(xy, p1)]
        rec["pre after p1"] = self.pre()
        at2 = self.at(p2[0] + pointer_off, p2[1] + pointer_off)
        self.move(at2)
        shown_w = self.fields()[:2]
        shown = [sketch_ui.field_value(x) for x in shown_w]
        polar = (math.hypot(p2[0] - p1[0], p2[1] - p1[1]), math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0])))
        best = None
        for pair in (p2, polar):
            for order in ((0, 1), (1, 0)):
                if len(shown) == 2:
                    err = sum(abs(shown[order[k]] - pair[k]) for k in range(2))
                    if best is None or err < best[0]:
                        best = (err, order, pair)
        rec["p2 shown"], rec["p2 typed"] = shown, best[2] if best else None
        if best:
            rec["p2 raw"] = [self.type_in(shown_w[best[1][k]], best[2][k]) for k in range(2)]
        rec["pre after p2"] = self.pre()
        self.end_tool(self.at(p1[0] - 30, p1[1] + 80))
        App.ActiveDocument.recompute()
        rec["report"] = report_text()[r0:][-600:]
        rec["made"] = list(range(n0, len(self.sk.Geometry)))
        rec["constraints"] = rows(self.sk, k0)
        self.log.append(rec)
        return rec["made"]


def ends(sk, g):
    return [sk.getPoint(g, 1), sk.getPoint(g, 2)]


def gaps(sk, curves):
    """Each curve end's distance to the nearest end of another curve."""
    out = []
    for g in curves:
        for p in ends(sk, g):
            out.append(min((p - q).Length for h in curves if h != g for q in ends(sk, h)))
    return out


def scenario(smoke, label, guarded, pointer_off=0.0):
    import Part
    from . import sketch_typed, sketch_ui
    from .tutorial import settle_view
    from pivy import coin
    sk = sketch_ui.edited_sketch()
    guard = sketch_typed.install()
    guard.enabled, guard.last, guard.typed = guarded, None, []
    d = Drive(smoke, sk)
    settle_view(d.view)
    cam = d.view.getCameraNode()
    dirn = cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
    g = sk.getGlobalPlacement().multVec(App.Vector(-25, 20, 0))
    cam.position.setValue(coin.SbVec3f(g.x, g.y, g.z) - dirn * cam.focalDistance.getValue())
    if hasattr(cam, "height"):
        cam.height.setValue(150)
    QtWidgets.QApplication.processEvents()
    qwait(200)
    repairs = []
    a1 = d.arc(*ARC1, pointer_off=pointer_off)
    repairs.append(guard.last)
    a2 = d.arc(*ARC2, pointer_off=pointer_off)
    repairs.append(guard.last)
    before_line = (len(sk.Geometry), [r[1:] for r in rows(sk)])
    ln = d.line((-38.1, 0.0), (0.0, 63.5), pointer_off=pointer_off)
    repairs.append(guard.last)
    curves = a1 + a2 + ln
    gp = gaps(sk, curves)
    try:
        wires = Part.__sortEdges__([sk.Geometry[c].toShape() for c in curves])
        wire = Part.Wire(wires)
        closed = wire.isClosed()
    except Exception as e:
        closed = f"no wire: {e}"
    sk.solve()
    bad = list(sk.RedundantConstraints) + list(sk.ConflictingConstraints)
    pairs = {frozenset(((c.First, int(c.FirstPos)), (c.Second, int(c.SecondPos))))
             for c in sk.Constraints if c.Type == "Coincident"}
    want = [((a1[0], 2), (a2[0], 1)), ((a2[0], 2), (ln[0], 1)), ((ln[0], 2), (a1[0], 1))] \
        if len(a1) == len(a2) == len(ln) == 1 else []
    joined = [frozenset(w) in pairs for w in want]
    sweep = next((c.Value for c in sk.Constraints if c.Type == "Angle" and a1 and c.First == a1[0]
                  and c.Second == -2000), None)
    ok = len(curves) == 3 and closed is True and max(gp or [1]) < 1e-7 and all(joined) and joined and not bad
    smoke.info[f"typed join {label}"] = {
        "log": d.log, "repairs": repairs, "gaps": [f"{x:.3e}" for x in gp], "closed": closed,
        "geometry": [(c, sk.Geometry[c].TypeId, [tuple(round(v, 12) for v in p) for p in ends(sk, c)])
                     for c in curves],
        "constraints": rows(sk), "redundant or conflicting": bad, "arc 1 sweep": repr(sweep)}
    detail = (f"{len(curves)} curves, closed {closed}, largest end gap {max(gp or [0]):.2e} mm, Coincident at "
              f"the three joins {joined}, redundant/conflicting {bad}, arc 1's sweep {sweep!r} rad")
    # one Undo takes back the line with its joins: the repair adds no undo step
    doc = sk.Document
    doc.undo()
    doc.recompute()
    undone = (len(sk.Geometry), [r[1:] for r in rows(sk)]) == before_line
    smoke.info[f"typed join {label}"]["after one Undo"] = {"geometry": len(sk.Geometry), "constraints": rows(sk),
                                                           "as before the line": undone}
    if guarded:
        ok = ok and undone
        detail += f"; one Undo leaves the sketch as before the line {undone}"
    sk.deleteAllGeometry()
    App.ActiveDocument.recompute()
    guard.enabled = True
    return ok, detail


def run(smoke):
    """The two arcs and the line of the AV rocker arm's kind, every value typed in the fields beside the pointer
    (A: centre, radius and start angle, sweep; L: first point, then length and angle): each typed point lands on
    the end of the curve before, and the line closes the loop on the first arc's start. With NX-Style's guard off
    (the control: FreeCAD 1.1.4 alone) the ends miss by up to 2e-5 mm and carry no Coincident."""
    results = {}
    for label, guarded in (("FreeCAD alone (control)", False), ("NX-Style", True)):
        try:
            results[label] = scenario(smoke, label, guarded)
        except Exception as e:
            results[label] = (None, repr(e))
            smoke.info[f"traceback typed join {label}"] = traceback.format_exc()
    ok, detail = results["NX-Style"]
    smoke.check("typed points join: two arcs (A) and a line (L), every point typed onto the end before, make one "
                "closed wire with no gap above 1e-7 mm, a Coincident at each join and no redundant constraint",
                ok is True, detail)
    ok, detail = results["FreeCAD alone (control)"]
    smoke.check("typed points join, control: the same input with NX-Style's guard off fails that check (FreeCAD "
                "1.1.4 alone)", ok is False, detail)
