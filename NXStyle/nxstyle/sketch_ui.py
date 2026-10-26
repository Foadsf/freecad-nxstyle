# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX sketch constraints FreeCAD lacks: Collinear, and the Geometric Constraints gallery (NX: C).

Collinear: FreeCAD has no such constraint. Both ends of one line are put on the line through the other
(point on object), and each is kept only if the solver does not call it redundant: when both lines are already
horizontal (or vertical, or parallel by constraint) one end is enough.

Geometric Constraints: NX opens one dialog for all geometric constraints; here C opens NX's gallery as a
menu, and the choice runs FreeCAD's tool on the current selection (or starts it to pick, as FreeCAD does).
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config, sketch_core as core
from .qt import QtGui, QtWidgets


def edited_sketch():
    try:
        vp = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument else None
    except Exception:
        return None
    obj = getattr(vp, "Object", None)
    return obj if obj is not None and obj.isDerivedFrom("Sketcher::SketchObject") else None


def _status(text, ms=5000):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, ms)
    except Exception:
        pass


def is_line(sk, geo):
    if geo in (core.H_AXIS, core.V_AXIS):
        return True
    try:
        g = sk.Geometry[geo] if geo >= 0 else sk.ExternalGeo[-geo - 1]
    except Exception:
        return False
    return g.TypeId == "Part::GeomLineSegment"


def picked_curves(sk):
    """[(GeoId, is_line)] of the curves picked in the sketch, in pick order; points are left out."""
    out = []
    for s in Gui.Selection.getSelectionEx():
        if s.Object != sk:
            continue
        for sub in s.SubElementNames:
            g = core.geo_id(sub)
            if g is not None:
                out.append((g, is_line(sk, g)))
    return out


def _redundant(sk):
    """The solver's redundant constraints (1-based), fully or partly, after a solve."""
    sk.solve()
    return set(sk.RedundantConstraints) | set(getattr(sk, "PartiallyRedundantConstraints", []))


def make_collinear(sk, moving, target):
    """Put the line `moving` on the line through `target`. Returns the indices of the constraints kept."""
    import Sketcher
    doc = sk.Document
    kept = []
    doc.openTransaction("Collinear")
    try:
        for pos in (1, 2):
            before = _redundant(sk)
            i = sk.addConstraint(Sketcher.Constraint("PointOnObject", moving, pos, target))
            if _redundant(sk) - before:      # the solver may name another one of the redundant set
                sk.delConstraint(i)          # redundant: the directions were tied already
                sk.solve()
            else:
                kept.append(i)
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    doc.recompute()
    return kept


class Collinear:
    """NX's Collinear: two lines on one straight line."""

    def GetResources(self):
        return {"MenuText": "Collinear",
                "ToolTip": "Put two lines on one straight line: select the line to move, then the line to "
                           "align it with, then Collinear",
                "Pixmap": config.resource("icons", "collinear.svg"), "CmdType": "ForEdit"}

    def IsActive(self):
        return edited_sketch() is not None

    def Activated(self):
        sk = edited_sketch()
        if sk is None:
            return
        try:
            moving, target = core.collinear_roles(picked_curves(sk))
        except core.NotCollinear as e:
            _status(f"{e}. Select two lines, then Collinear")
            return
        kept = make_collinear(sk, moving, target)
        Gui.Selection.clearSelection()
        name = {core.H_AXIS: "the X axis", core.V_AXIS: "the Y axis"}.get(target, f"Edge{target + 1}")
        if kept:
            _status(f"Collinear: Edge{moving + 1} on the line through {name} "
                    f"({len(kept)} point-on-curve constraint{'s' if len(kept) > 1 else ''})")
        else:
            _status(f"Edge{moving + 1} and {name} are collinear already: nothing added")


last_gallery = None        # the menu C opened last, for tests


class GeometricConstraints:
    """NX's Geometric Constraints (C): NX's gallery of constraint types, each running FreeCAD's tool."""

    def GetResources(self):
        return {"MenuText": "Geometric Constraints",
                "ToolTip": "Choose a geometric constraint (NX's gallery); it applies to what is selected, "
                           "or starts FreeCAD's tool to pick (NX: C)",
                # FreeCAD greys out every command not made for edit mode while a sketch is in edit
                "Pixmap": config.resource("icons", "geometric_constraints.svg"), "CmdType": "ForEdit"}

    def IsActive(self):
        return edited_sketch() is not None

    def Activated(self):
        global last_gallery
        from .ribbon import command_actions, command_icon, is_enabled, known_commands, resolve
        menu = QtWidgets.QMenu("Geometric Constraints", Gui.getMainWindow())
        menu.setObjectName("NXGeometricConstraints")
        menu.setToolTipsVisible(True)
        known = known_commands()
        for label, spec, pick in core.GALLERY:
            name = resolve(spec, known)
            if not name:
                continue
            act = menu.addAction(command_icon(name), label)
            act.setToolTip(f"{label}: pick {pick}")
            act.setData(name)
            # FreeCAD 1.1 makes no action for a command in none of its toolbars (Point on Object)
            act.setEnabled(is_enabled(name) if command_actions(name) else Gui.Command.get(name).isActive())
            act.triggered.connect(lambda _=False, n=name: _run(n))
        last_gallery = menu
        menu.popup(QtGui.QCursor.pos())


def _run(name):
    from . import commands
    from .ribbon import trigger
    commands.remember(name)
    trigger(name)


COMMANDS = {
    "NXStyle_SketchCollinear": Collinear(),
    "NXStyle_GeometricConstraints": GeometricConstraints(),
}


def collinear_report(sk, a, b):
    """For tests: the largest distance of line b's ends from the line through a, and the angle between
    the two (degrees)."""
    ga, gb = sk.Geometry[a], sk.Geometry[b]
    d = ga.EndPoint - ga.StartPoint
    n = App.Vector(-d.y, d.x, 0).normalize()
    off = max(abs((p - ga.StartPoint).dot(n)) for p in (gb.StartPoint, gb.EndPoint))
    angle = abs(d.getAngle(gb.EndPoint - gb.StartPoint)) * 180 / 3.141592653589793
    return off, min(angle, 180 - angle)
