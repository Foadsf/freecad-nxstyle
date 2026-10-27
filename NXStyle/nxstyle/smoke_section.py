# SPDX-License-Identifier: LGPL-2.1-or-later
"""Self-test of sections (called from smoke.py): Extrude and Revolve on curves picked from a sketch.

The sketch is the impeller lower casing of NX 12 for Engineering Design (3.5.2, built in tutorial AG): 19 curves,
in which the casing wall, its edge and the flange are three closed loops that share curves, and two flange lines
overlap Line 2 of the wall and of the edge. As a whole it is no profile. Book 4.4 revolves the wall 180° about XC,
extrudes the edge 0.5 in along -ZC and revolves the flange, each with the Curve Rule on Single Curve.

The commands start from the ribbon and the X key, curves are picked in the graphics window (a click where the
curve is the nearest thing under the cursor, QuickPick's row where a solid's face or edge lies on it), and the NX
box and FreeCAD's panel are set as a user sets them; OK and Esc end them."""

import math
import time
import traceback

import FreeCAD as App
import FreeCADGui as Gui

from . import selection_filter as sf
from .qt import Qt, QtCore, QtWidgets
from .smoke_selection import click, qt_point, qwait, settle

IN = 25.4
WALL = list(range(0, 8)) + [12, 13]           # geometry indices: the inner and upper chains, the two wall ends
LIP = list(range(0, 4)) + list(range(8, 12)) + [14, 15]
FLANGE = [15, 16, 17, 18]
OVERLAPPED = {3: 0.25, 11: 0.25}               # Line 2 of the wall and of the edge: picked clear of the flange


def _geometry(kind, p, q, c, r):
    import Part
    if kind == "line":
        return Part.LineSegment(p, q)
    a0, a1 = math.atan2(p.y - c.y, p.x - c.x), math.atan2(q.y - c.y, q.x - c.x)
    if (a1 - a0) % (2 * math.pi) > math.pi:
        a0, a1 = a1, a0
    if a1 < a0:
        a1 += 2 * math.pi
    return Part.ArcOfCircle(Part.Circle(c, App.Vector(0, 0, 1), r), a0, a1)


def casing(doc):
    """A Body with the casing sketch on XY (the book's 19 curves, unconstrained)."""
    from .tutorial_mst import ag_reference
    body = doc.addObject("PartDesign::Body", "Body")
    sk = body.newObject("Sketcher::SketchObject", "Sketch")
    sk.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
    sk.MapMode = "FlatFace"
    for g in ag_reference(-8 * IN):
        sk.addGeometry(_geometry(*g), False)
    doc.recompute()
    return body, sk


def edge_names(sk):
    """{geometry index: 'EdgeN'} outside sketch edit (the shape's order), through command_core.match_edges."""
    from . import command_core as core

    def rec(e):
        a, b = e.FirstParameter, e.LastParameter
        return tuple(tuple(e.valueAt(t)) for t in (a, b, (a + b) / 2))
    geo = {i: rec(g.toShape()) for i, g in enumerate(sk.Geometry)}
    return core.match_edges(geo, {f"Edge{i}": rec(e) for i, e in enumerate(sk.Shape.Edges, 1)})


class Expected:
    def __init__(self, volume, why=""):
        self.Volume, self.why = volume, why


def expected(sk, geos, how):
    """The solid the Part API makes of the same curves: 'revolve' 180° about X, or 'extrude' 0.5 in along -Z."""
    import Part
    try:
        edges = Part.__sortEdges__([sk.Geometry[i].toShape() for i in geos])
        face = Part.Face(Part.Wire(edges))
        solid = face.revolve(App.Vector(0, 0, 0), App.Vector(1, 0, 0), 180) if how == "revolve" else \
            face.extrude(App.Vector(0, 0, -0.5 * IN))
        return Expected(solid.Volume)
    except Exception as e:
        return Expected(float("nan"), f"the Part API could not make it: {e}")


def volume(o):
    try:
        return o.Shape.Volume if o is not None and not o.Shape.isNull() else 0.0
    except Exception:
        return 0.0


def zbox(o):
    """(ZMin, ZMax) of o's exact box, or None."""
    try:
        b = o.Shape.optimalBoundingBox(False, False)
        return (b.ZMin, b.ZMax)
    except Exception:
        return None


def solids(o):
    try:
        return len(o.Shape.Solids)
    except Exception:
        return 0


def wait(cond, ms=4000):
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        try:
            if cond():
                return True
        except Exception:
            pass
        qwait(50)
    return False


def box_widget(cls, name):
    dock = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Tasks")
    return dock.findChild(cls, name) if dock is not None else None


class Run:
    def __init__(self, smoke, doc, body, sk):
        from . import controller
        self.smoke, self.doc, self.body, self.sk = smoke, doc, body, sk
        self.ctl = controller.CONTROLLER
        self.names = edge_names(sk)
        self.routes = []

    # ------------------------------------------------------------ inputs
    def rule(self, key):
        w = getattr(self.smoke.shell, "curve_rule", None)       # the Selection bar's Curve Rule
        if w is not None:
            w.setCurrentIndex(w.findData(key))
        return w is not None and sf.manager().curve_rule == key

    def ribbon(self, cmd):
        from .ribbon import CommandButton
        r = self.smoke.shell.ribbon
        for i in range(r.stack.count()):
            for b in r.stack.widget(i).findChildren(CommandButton):
                if b.command == cmd:
                    r.select(r.tabs.tabText(i))
                    wait(b.isEnabled, 2000)
                    b.click()
                    return True
        return False

    def point_on(self, g, frac=0.5):
        e = self.sk.Geometry[g].toShape()
        return self.sk.getGlobalPlacement().multVec(e.valueAt(e.FirstParameter + frac * (e.LastParameter - e.FirstParameter)))

    def pick(self, g, clear=False):
        """Pick curve g as a user does: a click where it is the nearest thing under the cursor, else its QuickPick
        row (a solid's face or edge on the sketch plane lies in front of it). clear: a plain click's new selection."""
        view = Gui.ActiveDocument.ActiveView
        f = self.smoke.nav()
        coin = view.getPointOnViewport(self.point_on(g, OVERLAPPED.get(g, 0.5)))
        rows = sf.rows_at(view, coin)
        want = next((r for r in rows if r["pick"].leaf is self.sk and r["pick"].element == self.names[g]), None)
        # what a click there takes is what FreeCAD preselects under the pointer, which is not always the ray's first
        # hit (measured: a solid's face on the sketch plane, Pad.Face11; Line 2 six pixels from the wall's end line)
        p = qt_point(f, coin)
        self.smoke.send(f, QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton)
        QtWidgets.QApplication.processEvents()
        qwait(40)
        alone = want is not None and self.preselected() == (self.sk, self.names[g])
        if alone and not Gui.Control.activeDialog() and not clear:
            route = "row"                     # preselection adds to the selection (a plain click would replace it)
            sf.select_row(want, clear=False)
        elif alone:
            route = "click"
            click(self.smoke, f, qt_point(f, coin))
        elif want is not None:
            route = "quickpick"
            sf.select_row(want, clear=False)
        else:
            route = f"missing ({[r['label'] for r in rows[:3]]})"
        self.routes.append((g, route))
        # clicks farther apart than a double click: FreeCAD selects the whole object on one
        qwait(QtWidgets.QApplication.doubleClickInterval() + 80)
        return want is not None

    @staticmethod
    def preselected():
        """(sketch, 'EdgeN') FreeCAD preselects under the pointer, or None."""
        from . import controller
        try:
            p = Gui.Selection.getPreselection()
            subs = list(p.SubElementNames) if p is not None else []
            return controller.sketch_pick(p.DocumentName, p.ObjectName, subs[0]) if subs else None
        except Exception:
            return None

    def ctrl_click(self, g):
        """Ctrl+MB1 on curve g: FreeCAD deselects a selected curve."""
        from .qt import Qt, QtCore, mouse_event
        view = Gui.ActiveDocument.ActiveView
        f = self.smoke.nav()
        p = qt_point(f, view.getPointOnViewport(self.point_on(g, OVERLAPPED.get(g, 0.5))))
        for kind, button, buttons in ((QtCore.QEvent.MouseMove, Qt.NoButton, Qt.NoButton),
                                      (QtCore.QEvent.MouseButtonPress, Qt.LeftButton, Qt.LeftButton),
                                      (QtCore.QEvent.MouseButtonRelease, Qt.LeftButton, Qt.NoButton)):
            QtWidgets.QApplication.sendEvent(f.widget, mouse_event(kind, p, button, buttons, Qt.ControlModifier))
            QtWidgets.QApplication.processEvents()
        qwait(QtWidgets.QApplication.doubleClickInterval() + 80)

    def session(self):
        return self.ctl.session

    def opened(self, n=None, ms=6000):
        """The NX box is up (with n curves in the section)."""
        def up():
            s = self.ctl.session
            from . import controller
            return s is not None and s.stage == "parameterize" and controller._alive(s.box) and \
                (n is None or (s.edges is not None and len(s.edges) == n))
        return wait(up, ms)

    def vector(self, key):
        c = box_widget(QtWidgets.QComboBox, "nxSpecifyVector")
        if c is None:
            return False
        i = c.findData(key)
        c.setCurrentIndex(i)
        c.activated.emit(i)
        qwait(100)
        return wait(lambda: self.ctl.session is not None and self.ctl.session.axis["vector"] == key and self.opened(ms=50))

    def point(self, xyz):
        fields = [box_widget(QtWidgets.QDoubleSpinBox, f"nxPoint{c}") for c in "XYZ"]
        if None in fields:
            return False
        for w, v in zip(fields, xyz):
            w.setValue(v)
        fields[-1].editingFinished.emit()
        qwait(100)
        return wait(lambda: self.opened(ms=50) and tuple(self.ctl.session.axis["point"]) == tuple(xyz))

    def limits(self, start, end):
        a, b = box_widget(QtWidgets.QDoubleSpinBox, "nxLimitStart"), box_widget(QtWidgets.QDoubleSpinBox, "nxLimitEnd")
        if a is None or b is None:
            return False
        a.setValue(start)
        b.setValue(end)
        b.editingFinished.emit()
        qwait(200)
        return True

    def boolean(self, key):
        c = box_widget(QtWidgets.QComboBox, "nxBoolean")
        if c is None:
            return False
        i = c.findData(key)
        c.setCurrentIndex(i)
        c.activated.emit(i)
        qwait(100)
        return wait(lambda: self.ctl.session is not None and self.ctl.session.mode == key and self.opened(ms=50))

    def ok(self):
        b = self.ctl._ok_button()
        enabled = b is not None and b.isEnabled()
        if b is not None:
            b.click()
        wait(lambda: not self.ctl.busy() and not Gui.Control.activeDialog(), 6000)
        qwait(200)
        return enabled

    def state(self):
        s = self.ctl.session
        return {"busy": self.ctl.busy(), "stage": s.stage if s else None, "edges": list(s.edges or []) if s else None,
                "error": s.error if s else None, "axis": s.axis if s else None, "limits": s.limits if s else None,
                "last": self.ctl.history[-1:], "trace": self.ctl.trace[-30:], "routes": self.routes[-12:],
                "dialog": bool(Gui.Control.activeDialog())}

    def subs(self, geos):
        return sorted((self.names[g] for g in geos), key=lambda e: int(e[4:]))


class Recorder:
    """A stand-in for the self-test that keeps the checks of a planted run to itself."""

    def __init__(self, smoke):
        self.smoke, self.checks = smoke, []

    def check(self, name, ok, detail=""):
        self.checks.append((name, bool(ok), str(detail)[:600]))

    def shot(self, *_args):
        pass

    def __getattr__(self, name):
        return getattr(self.smoke, name)


def reset(run):
    if run.ctl.busy():
        run.ctl.cancel()
        wait(lambda: not run.ctl.busy(), 2000)
    if Gui.Control.activeDialog():
        from .smoke_selection import cancel_task_dialog
        cancel_task_dialog()
        wait(lambda: not Gui.Control.activeDialog(), 2000)
    Gui.Selection.clearSelection()
    qwait(200)


def scenario(smoke, name="SmokeSection"):
    """The three loops of the casing, then Cancel."""
    before = App.ActiveDocument
    doc = App.newDocument(name)
    try:
        body, sk = casing(doc)
        gdoc = Gui.getDocument(doc.Name)
        gdoc.ActiveView.setActiveObject("pdbody", body)
        gdoc.ActiveView.viewTop()
        gdoc.ActiveView.fitAll()
        settle(gdoc.ActiveView, 400)
        run = Run(smoke, doc, body, sk)
        smoke.info["section: casing edges"] = {str(k): v for k, v in sorted(run.names.items())}
        try:
            for part in (revolve_wall, extrude_lip, revolve_flange, cancel):
                reset(run)
                try:
                    part(smoke, run)
                except Exception:
                    smoke.check(f"sections: {part.__name__} ran", False, traceback.format_exc().splitlines()[-1])
                    smoke.info[f"traceback {name} {part.__name__}"] = traceback.format_exc()
        finally:
            if run.ctl.busy():
                run.ctl.cancel()
                qwait(300)
            run.rule("inferred")
    finally:
        try:
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
            Gui.Selection.clearSelection()
            App.closeDocument(doc.Name)
            if before is not None and before.Name in App.listDocuments():
                App.setActiveDocument(before.Name)
                Gui.getDocument(before.Name)
        except Exception:
            smoke.info["section: cleanup"] = traceback.format_exc()


def revolve_wall(smoke, run):
    """Revolve first, nothing selected (FreeCAD asks for a sketch plane); the 10 wall curves picked with Single
    Curve; Specify Vector XC through (0, 0, 0); End 180; OK."""
    Gui.Selection.clearSelection()
    ruled = run.rule("single")
    undo0 = list(run.doc.UndoNames)      # before: FreeCAD's plane pick holds a 'New Sketch' step until it closes
    started = run.ribbon("NXStyle_Revolve")
    asked = wait(lambda: Gui.Control.activeDialog(), 3000)
    run.pick(WALL[0], clear=True)
    first = run.opened(1)                            # the plane pick closes and the dialog opens with the curve
    for g in WALL[1:-1]:
        run.pick(g, clear=True)
    nine = run.opened(len(WALL) - 1)
    okb = run.ctl._ok_button()
    gap = (run.state()["error"], okb is not None and okb.isEnabled())
    run.ctrl_click(WALL[-2])                         # deselect the last one picked
    eight = run.opened(len(WALL) - 2) and run.names[WALL[-2]] not in run.ctl.session.edges
    run.pick(WALL[-2], clear=True)
    run.pick(WALL[-1], clear=True)
    up = run.opened(len(WALL))
    picked = run.state()
    picked.update({"first": first, "nine": nine, "open section": gap, "Ctrl+click took one out": eight})
    axis = run.vector("XC") and run.point((0.0, 0.0, 0.0))
    run.limits(0.0, 180.0)
    rev = next((o for o in run.doc.Objects if o.TypeId == "PartDesign::Revolution"), None)
    panel = box_widget(QtWidgets.QAbstractSpinBox, "revolveAngle")
    shown = (panel.property("rawValue") if panel is not None else None,
             rev.Angle.Value if rev is not None else None,
             rev.ReferenceAxis[0].Name if rev is not None and rev.ReferenceAxis else None)
    smoke.shot("12_section_revolve.png")
    ok = run.ok()
    rev = next((o for o in run.doc.Objects if o.TypeId == "PartDesign::Revolution"), None)
    want = expected(run.sk, WALL, "revolve")
    got = volume(rev)
    last = run.ctl.history[-1] if run.ctl.history else {}
    prof = list(rev.Profile[1]) if rev is not None else None
    box = zbox(rev)
    report(run.smoke, "Revolve with nothing selected, Curve Rule Single Curve: the 10 wall curves of the casing sketch "
           "(shared and overlapping curves in it) picked in the graphics window become the section; XC through the "
           "origin, End 180, OK: one undo step, the Profile is those curves, the solid is the Part API's; with 9 "
           "picked the box says the section is open and OK is unavailable, and Ctrl+click takes a curve out",
           {"curve rule": ruled, "ribbon": started, "plane asked": asked, "first curve opens the dialog": first,
            "9 picked": nine, "open section said": bool(gap[0]) and "open" in gap[0], "OK unavailable": not gap[1],
            "Ctrl+click took one out": eight, "10 picked": up, "XC through the origin": axis, "OK enabled": ok,
            "committed Revolve": last.get("outcome") == "committed" and last.get("command") == "Revolve",
            "one undo step": last.get("undo_steps") == 1 and core_undo(undo0, run.doc.UndoNames) == ["Revolve"],
            "Profile is the curves": prof == run.subs(WALL), "End 180 in FreeCAD's panel": shown[1] == 180.0,
            "volume": abs(got - want.Volume) < 1e-6 * want.Volume, "below the sketch plane": bool(box) and box[1] < 1e-6},
           {"undo": list(run.doc.UndoNames)[:4], "undo before": undo0[:3], "picked": picked,
            "panel/feature/axis while open": shown, "profile": prof,
                     "want": run.subs(WALL), "volume": got, "expected": want.Volume, "last": last,
                     "box z": box, "routes": run.routes})


def report(smoke, name, conds, detail):
    """One check of named conditions; the detail names the ones that failed."""
    smoke.check(name, all(conds.values()), dict({"failed": [k for k, v in conds.items() if not v]}, **detail))


def core_undo(before, after):
    from . import command_core as core
    n = core.undo_steps_added(before, after)
    return list(after[:n]) if n else []


def extrude_lip(smoke, run):
    """The edge (lip): its 10 curves preselected, then X; Boolean None (it touches the wall along a line only, so
    it is its own body, as in the book); FreeCAD's panel: 0.5 in, Reversed (-ZC); OK."""
    from . import precise_input
    run.rule("single")
    Gui.Selection.clearSelection()
    for g in LIP:
        run.pick(g)
    pre = sorted(e for _o, e in ((s.ObjectName, sub.split(".")[-1]) for s in Gui.Selection.getSelectionEx("", 0)
                                 for sub in s.SubElementNames))
    undo0 = list(run.doc.UndoNames)
    n_bodies = len([o for o in run.doc.Objects if o.isDerivedFrom("PartDesign::Body")])
    run.smoke.press("X")
    up = run.opened(len(LIP))
    picked = run.state()
    none = run.boolean("new_body")
    length = box_widget(QtWidgets.QAbstractSpinBox, "lengthEdit")
    rev = box_widget(QtWidgets.QCheckBox, "checkBoxReversed")
    if length is not None and rev is not None:
        precise_input.show_with(length, App.Units.Quantity("12.7 mm"), 1)
        rev.setChecked(True)
        qwait(300)
    smoke.shot("13_section_extrude.png")
    ok = run.ok()
    pads = [o for o in run.doc.Objects if o.TypeId == "PartDesign::Pad"]
    pad = pads[-1] if pads else None
    binder = pad.Profile[0] if pad is not None else None
    support = sorted((sub.split(".")[-1] for _o, subs in (binder.Support if binder is not None and
                                                           binder.TypeId == "PartDesign::SubShapeBinder" else [])
                      for sub in subs), key=lambda e: int(e[4:]))
    want = expected(run.sk, LIP, "extrude")
    got = volume(pad)
    box = zbox(pad)
    last = run.ctl.history[-1] if run.ctl.history else {}
    bodies = len([o for o in run.doc.Objects if o.isDerivedFrom("PartDesign::Body")])
    report(run.smoke, "the 10 edge (lip) curves preselected with Single Curve, then X: they are the section; Boolean "
           "None, 0.5 in Reversed (-ZC), OK: a new Body whose binder holds only those curves, extruded down 0.5 in, "
           "one undo step",
           {"preselected": sorted(pre, key=lambda e: int(e[4:])) == run.subs(LIP), "section": up, "None": none,
            "FreeCAD's length field": length is not None, "OK enabled": ok,
            "committed None": last.get("outcome") == "committed" and last.get("mode") == "new_body",
            "one undo step": last.get("undo_steps") == 1, "a new Body": bodies == n_bodies + 1,
            "binder holds the curves": support == run.subs(LIP), "volume": abs(got - want.Volume) < 1e-6 * want.Volume,
            "0.5 in down": bool(box) and abs(box[0] + 0.5 * IN) < 1e-6 and box[1] < 1e-6},
           {"preselected": pre, "picked": picked, "binder support": support, "want": run.subs(LIP),
                     "volume": got, "expected": want.Volume, "box z": box,
                     "last": last, "undo": run.doc.UndoNames[:3], "undo before": undo0[:2], "routes": run.routes[-10:]})


def revolve_flange(smoke, run):
    """The flange: Revolve first; Connected Curves takes three of its sides with one pick (the fourth side, the
    edge's right end, meets three other curves), Single Curve the fourth; XC, End 180, OK: united with the wall."""
    Gui.Selection.clearSelection()
    rule = run.rule("connected")
    run.ribbon("NXStyle_Revolve")
    wait(lambda: Gui.Control.activeDialog(), 3000)
    tip = run.body.Tip
    v0, n0 = volume(tip), solids(tip)
    run.pick(16, clear=True)
    three = run.opened(3)                            # the plane pick closed, the dialog opened with the chain
    chain = run.state()
    run.rule("single")
    run.pick(15, clear=True)
    four = run.opened(4)
    axis = run.vector("XC")
    run.limits(0.0, 180.0)
    ok = run.ok()
    tip = run.body.Tip
    want = expected(run.sk, FLANGE, "revolve")
    added = volume(tip) - v0
    last = run.ctl.history[-1] if run.ctl.history else {}
    prof = list(tip.Profile[1]) if tip.TypeId == "PartDesign::Revolution" else None
    report(run.smoke, "a 4-curve section (the flange): Connected Curves takes 3 sides with one pick, Single Curve the "
           "fourth; XC, End 180, OK: Unite onto the wall, one solid, the flange's volume added, one undo step",
           {"curve rule": rule, "Connected Curves took 3": three, "Single Curve the 4th": four, "XC": axis,
            "OK enabled": ok, "committed Unite": last.get("outcome") == "committed" and last.get("mode") == "unite",
            "one undo step": last.get("undo_steps") == 1, "Profile is the curves": prof == run.subs(FLANGE),
            "one solid": solids(tip) == n0 == 1, "volume added": abs(added - want.Volume) < 1e-6 * want.Volume},
           {"after the connected pick": chain, "profile": prof, "want": run.subs(FLANGE), "added": added,
                     "expected": want.Volume, "last": last, "routes": run.routes[-4:]})


def cancel(smoke, run):
    """Cancel leaves nothing: Revolve with the flange curves preselected and an axis off the origin (a datum line
    made for it), then Esc; Extrude first, three curves picked, then Esc."""
    from . import controller
    names0 = sorted(o.Name for o in run.doc.Objects)
    undo0 = list(run.doc.UndoNames)
    shown0 = run.sk.ViewObject.Visibility
    run.rule("single")
    Gui.Selection.clearSelection()
    for g in FLANGE:
        run.pick(g)
    Gui.runCommand("NXStyle_Revolve")
    up = run.opened(len(FLANGE))
    run.vector("XC")
    off = run.point((0.0, 10.0, 0.0))
    datum = [o.Name for o in run.doc.Objects if o.TypeId == "PartDesign::Line"]
    run.smoke.press("Escape")
    wait(lambda: not run.ctl.busy(), 3000)
    qwait(300)
    after_revolve = (sorted(o.Name for o in run.doc.Objects), list(run.doc.UndoNames), run.ctl.history[-1:])
    Gui.Selection.clearSelection()
    run.smoke.press("X")
    wait(lambda: Gui.Control.activeDialog(), 3000)
    run.pick(4, clear=True)
    run.opened(1)
    for g in (5, 6):
        run.pick(g, clear=True)
    three = run.opened(3)
    during = run.state()
    run.smoke.press("Escape")
    wait(lambda: not run.ctl.busy(), 3000)
    qwait(300)
    names, undo = sorted(o.Name for o in run.doc.Objects), list(run.doc.UndoNames)
    last = run.ctl.history[-1] if run.ctl.history else {}
    report(run.smoke, "Cancel (Esc) leaves nothing: a Revolve of 4 preselected curves about a vector through "
           "(0, 10, 0) (its datum line made, then gone) and an Extrude of 3 picked curves end cancelled with the same "
           "objects and undo list as before, the sketch shown as it was",
           {"Revolve section": up, "point (0, 10, 0)": off, "a datum line while open": len(datum) == 1,
            "Revolve: objects as before": after_revolve[0] == names0, "Revolve: undo as before": after_revolve[1] == undo0,
            "Revolve cancelled": bool(after_revolve[2]) and after_revolve[2][0]["outcome"] == "cancelled",
            "Extrude section of 3": three,
            "Extrude cancelled": last.get("outcome") == "cancelled" and last.get("command") == "Extrude",
            "objects as before": names == names0, "undo as before": undo == undo0,
            "sketch shown as before": run.sk.ViewObject.Visibility == shown0, "not busy": not controller.CONTROLLER.busy()},
           {"datum while open": datum, "after revolve": after_revolve[2], "during extrude": during,
                     "objects added": sorted(set(names) - set(names0)), "undo": undo[:3], "undo before": undo0[:3],
                     "last": last, "routes": run.routes[-7:]})


def negative_control(smoke):
    """The same run with every pick taken as its whole sketch, as before sections (the casing is then no profile):
    each of the four checks must fail."""
    from . import controller
    rec = Recorder(smoke)
    real = controller.expand
    controller.expand = lambda sketch, element, rule: None
    try:
        scenario(rec, "SmokeSectionPlanted")
    finally:
        controller.expand = real
    failed = [name.split(":")[0][:60] for name, ok, _ in rec.checks if not ok]
    smoke.check("negative control: with each pick taken as its whole sketch (as before sections), all four section "
                "checks fail", len(rec.checks) == 4 and len(failed) == 4,
                {"failed": failed, "passed": [n[:60] for n, ok, _ in rec.checks if ok]})


def run(smoke):
    for part in (scenario, negative_control):
        try:
            part(smoke)
        except Exception:
            smoke.check(f"sections: {part.__name__} ran", False, traceback.format_exc().splitlines()[-1])
            smoke.info[f"traceback sections {part.__name__}"] = traceback.format_exc()
