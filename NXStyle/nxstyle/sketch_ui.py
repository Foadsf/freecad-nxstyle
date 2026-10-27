# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX sketch constraints FreeCAD lacks: Collinear, the Geometric Constraints gallery (NX: C), and Hide / Show /
Show All that reach sketch dimensions (FreeCAD's virtual space; see sketch_core).

Collinear: FreeCAD has no such constraint. Both ends of one line are put on the line through the other
(point on object), and each is kept only if the solver does not call it redundant: when both lines are already
horizontal (or vertical, or parallel by constraint) one end is enough.

Geometric Constraints: NX opens one dialog for all geometric constraints; here C opens NX's gallery as a
menu, and the choice runs FreeCAD's tool on the current selection (or starts it to pick, as FreeCAD does).

Quick Trim: FreeCAD's trim tool, with the tangencies FreeCAD's trim drops put back (TrimGuard).
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


# ------------------------------------------------------------------ typed coordinates (NX's XC / YC boxes)
def on_view_fields(widget):
    """FreeCAD's on-view parameter fields shown over the 3D view widget (not the task panel's)."""
    from .qt import QtCore
    area = QtCore.QRect(widget.mapToGlobal(QtCore.QPoint(0, 0)), widget.size())

    def docked(w):
        while w is not None:
            if isinstance(w, QtWidgets.QDockWidget):
                return True
            w = w.parentWidget()
        return False
    return [w for w in Gui.getMainWindow().findChildren(QtWidgets.QAbstractSpinBox) if w.isVisible()
            and not docked(w) and area.contains(w.mapToGlobal(w.rect().center()))]


def field_value(w):
    v = w.property("rawValue")
    if isinstance(v, (int, float)):
        return float(v)
    import re
    m = re.search(r"-?\d+(?:[.,]\d+)?", w.text())
    return float(m.group(0).replace(",", ".")) if m else 0.0


def cursor_on_sketch(sk, widget, p):
    """The sketch's (x, y) under the widget position p."""
    view = Gui.ActiveDocument.ActiveView
    dpr = widget.devicePixelRatioF() if hasattr(widget, "devicePixelRatioF") else 1.0
    xy = (int(p.x() * dpr), int((widget.height() - p.y()) * dpr))
    get = getattr(view, "getPointOnFocalPlane", None) or view.getPoint
    g = sk.getGlobalPlacement().inverse().multVec(get(*xy))
    return g.x, g.y


def xy_fields(sk, widget, p):
    """(X field, Y field) of the running tool's positional on-view fields with the pointer at p, or None."""
    fields = on_view_fields(widget)
    pick = core.xy_fields([field_value(w) for w in fields], cursor_on_sketch(sk, widget, p))
    return (fields[pick[0]], fields[pick[1]]) if pick else None


def type_spline_point(sk, widget, p, point, prev=None):
    """Type one point of a running Studio Spline (FreeCAD's B-spline tool, either type) with the pointer at p.

    The first point (prev None) takes X and Y. FreeCAD 1.1.4 places it as soon as either field gets Enter, the
    other at the pointer's value, so X is typed without Enter and Enter goes to Y. A later point takes the length
    and angle from prev (FreeCAD has no X and Y there): Enter in each. Returns the values typed, or None when
    the two fields are not there."""
    from .qt import Qt
    from .tutorial import qtest
    fields = on_view_fields(widget)
    cursor = cursor_on_sketch(sk, widget, p)
    want = tuple(point) if prev is None else core.spline_step(prev, point)
    pick = (core.xy_fields if prev is None else core.spline_step_fields)(
        [field_value(w) for w in fields], cursor, *(() if prev is None else (prev,)))
    if not pick:
        return None
    for i, (k, v) in enumerate(zip(pick, want)):
        x = fields[k]
        x.setFocus()
        x.lineEdit().selectAll()
        qtest().keyClicks(x.lineEdit(), f"{v:.15g}".replace(".", x.locale().decimalPoint()))
        if prev is not None or i == 1:
            qtest().keyClick(x.lineEdit(), Qt.Key_Return)
        qtest().qWait(150)
    return want


# ------------------------------------------------------------------ Hide, Show, Show All (Ctrl+B, Ctrl+Shift+K/U)
def picked_constraints(sk):
    """(indices of the constraints of sk that are selected, other objects selected, other elements of sk)."""
    ids, others, elements = [], [], []
    for s in Gui.Selection.getSelectionEx():
        if s.Object != sk:
            others.append(s.Object)
            continue
        for sub in s.SubElementNames:
            i = core.constraint_id(sub)
            if i is None:
                elements.append(sub)
            else:
                ids.append(i)
    return ids, others, elements


def hidden_flags(sk):
    return [bool(sk.getVirtualSpace(i)) for i in range(len(sk.Constraints))]


def set_constraints_hidden(sk, ids, hidden, title):
    """Move constraints to FreeCAD's virtual space (hidden) or back, as one undo step."""
    doc = sk.Document
    doc.openTransaction(title)
    try:
        try:
            sk.setVirtualSpace(list(ids), hidden)
        except TypeError:                     # a FreeCAD that takes one index at a time
            for i in ids:
                sk.setVirtualSpace(i, hidden)
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise


class Visibility:
    """NX's Hide, Show and Show All, which also reach sketch dimensions and constraints: FreeCAD's own
    commands work on objects only (Std_HideSelection does not hide a picked dimension)."""

    FREECAD = {"hide": "Std_HideSelection", "show": "Std_ShowSelection", "show_all": "Std_ShowObjects"}
    TEXT = {"hide": ("Hide", "Hide the selected objects; in a sketch, the selected dimensions and constraints "
                             "(NX: Ctrl+B)"),
            "show": ("Show", "Show the selected objects; in a sketch, the selected hidden dimensions and "
                             "constraints, picked in the constraint list (NX: Ctrl+Shift+K)"),
            "show_all": ("Show All", "Show every object; in a sketch, every hidden dimension and constraint too "
                                     "(NX: Ctrl+Shift+U)")}

    def __init__(self, kind):
        self.kind = kind
        self.last = None                 # what the last run in a sketch changed, for tests

    def GetResources(self):
        from .commands import _pixmap
        text, tip = self.TEXT[self.kind]
        return {"MenuText": text, "ToolTip": tip, "Pixmap": _pixmap(self.FREECAD[self.kind]), "CmdType": "ForEdit"}

    def IsActive(self):
        if App.ActiveDocument is None:
            return False
        return self.kind == "show_all" or bool(Gui.Selection.getSelectionEx())

    def Activated(self):
        sk = edited_sketch()
        if sk is None:
            Gui.runCommand(self.FREECAD[self.kind])
            return
        ids, others, elements = picked_constraints(sk)
        change, hide = core.visibility_change(self.kind, ids, hidden_flags(sk))
        self.last = {"constraints": change, "others": [o.Name for o in others], "elements": elements}
        if change:
            set_constraints_hidden(sk, change, hide, self.TEXT[self.kind][0])
        if self.kind == "show_all":
            Gui.runCommand("Std_ShowObjects")
        else:
            for o in others:                  # objects picked outside the sketch, as FreeCAD's command does
                if getattr(o, "ViewObject", None) is not None:
                    o.ViewObject.Visibility = not hide
        Gui.Selection.clearSelection()         # hidden constraints cannot stay selected
        word = "hidden" if hide else "shown"
        note = f"; {len(elements)} curve or point pick(s) left alone: Hide in a sketch is for dimensions and " \
               "constraints" if elements else ""
        _status(f"{len(change)} sketch constraint{'s' if len(change) != 1 else ''} {word}{note}")


class SketchMenu:
    """MB3 menu in a sketch: Hide (or Show) for picked dimensions and constraints, beside FreeCAD's Delete."""

    def modifyContextMenu(self, recipient):
        if recipient != "Sketch":
            return []
        sk = edited_sketch()
        if sk is None:
            return []
        try:
            ids = picked_constraints(sk)[0]
            flags = hidden_flags(sk)
        except Exception:
            return []
        out = []
        if core.visibility_change("hide", ids, flags)[0]:
            out.append({"insert": "NXStyle_Hide", "menuItem": "Std_Delete"})
        if core.visibility_change("show", ids, flags)[0]:
            out.append({"insert": "NXStyle_Show", "menuItem": "Std_Delete"})
        # FreeCAD enables command actions on a timer after a selection change (Gui.updateCommands() only schedules
        # it): MB3 right after picking would show these entries greyed, and a click on them does nothing. Enable
        # them for the selection the menu is built for.
        for entry in out:
            try:
                cmd = Gui.Command.get(entry["insert"])
                active = cmd.isActive()
                for a in cmd.getAction():
                    a.setEnabled(active)
            except Exception:
                pass
        return out


_menu = None


def install_context_menu():
    global _menu
    if _menu is None and hasattr(Gui, "addWorkbenchManipulator"):
        _menu = SketchMenu()
        Gui.addWorkbenchManipulator(_menu)


# ------------------------------------------------------------------ Quick Trim keeps tangencies (NX: T)
TRIM = "Trim edge"          # the transaction FreeCAD's trim tool opens for each trim


def constraint_rows(sk):
    return [(c.Type, c.First, c.FirstPos, c.Second, c.SecondPos, c.Third) for c in sk.Constraints]


def touches(sk, other, pos, piece, tol=1e-6):
    """Whether curve `other` (its point `pos`, when pos) touches curve `piece`. FreeCAD asks OCC's extrema for
    an intersection, which miss a contact at the very end of a line; the distance between the shapes does not."""
    import Part
    if pos:
        target = Part.Vertex(sk.getPoint(other, pos))
    else:
        target = (sk.Geometry[other] if other >= 0 else sk.ExternalGeo[-other - 1]).toShape()
    return sk.Geometry[piece].toShape().distToShape(target)[0] < tol


class TrimGuard:
    """Puts back the Tangent and Perpendicular constraints FreeCAD's trim drops (see sketch_core.trim_losses):
    NX's Quick Trim keeps a line tangent to what is left of the arc. The constraints before the trim are read
    when FreeCAD opens its transaction; after it commits, each lost one goes on the piece the other curve still
    touches. Like FreeCAD's own solve after the trim, this adds no undo step: one Undo takes back the trim."""

    def __init__(self):
        self.pending = None
        self.enabled = True
        self.last = None             # what the last trim lost and got back, for tests and the tutorials

    def slotOpenTransaction(self, doc, name):
        sk = edited_sketch() if self.enabled and name == TRIM else None
        if sk is not None and sk.Document == doc:
            self.pending = (sk, constraint_rows(sk), [g.Tag for g in sk.Geometry])

    def slotAbortTransaction(self, doc):
        self.pending = None

    def slotCommitTransaction(self, doc):
        snap, self.pending = self.pending, None
        if snap is not None and snap[0].Document == doc:
            from .qt import QtCore
            QtCore.QTimer.singleShot(0, lambda: self.restore(*snap))   # after FreeCAD's tool is done with it

    def restore(self, sk, before, tags):
        import Sketcher
        try:
            now = [g.Tag for g in sk.Geometry]
        except Exception:                    # the sketch is gone
            return
        old, index = set(tags), {t: i for i, t in enumerate(now)}
        gone = [i for i, t in enumerate(tags) if t not in index]
        if len(gone) != 1:                   # not one curve trimmed: leave it to FreeCAD
            return
        pieces = [i for i, t in enumerate(now) if t not in old]
        renumber = {i: index.get(t) for i, t in enumerate(tags)}
        lost = core.trim_losses(before, constraint_rows(sk), gone[0], pieces, renumber)
        back = []
        for kind, other, pos in lost:
            piece = next((p for p in pieces if touches(sk, other, pos, p)), None)
            if piece is not None:
                sk.addConstraint(Sketcher.Constraint(*core.moved_constraint(kind, other, pos, piece)))
                back.append((kind, other, pos, piece))
        self.last = {"lost": lost, "put back": back}
        if back:
            sk.solve()
            App.Console.PrintLog(f"NX-Style Quick Trim: {len(back)} constraint(s) FreeCAD's trim dropped put back: "
                                 f"{back}\n")


trim_guard = TrimGuard()
_trim_watched = False


def install_trim_guard():
    global _trim_watched
    if not _trim_watched:
        App.addDocumentObserver(trim_guard)
        _trim_watched = True


COMMANDS = {
    "NXStyle_SketchCollinear": Collinear(),
    "NXStyle_GeometricConstraints": GeometricConstraints(),
    "NXStyle_Hide": Visibility("hide"),
    "NXStyle_Show": Visibility("show"),
    "NXStyle_ShowAll": Visibility("show_all"),
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
