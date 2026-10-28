# SPDX-License-Identifier: LGPL-2.1-or-later
"""Typed sketch points keep the values typed and join the end points they land on, as in NX.

In NX 2212 a point typed onto an existing end point is that point: NX infers the coincidence. FreeCAD 1.1.4's
sketch tools (DrawSketchDefaultHandler::finish) do this when a tool ends:

1. executeCommands: the geometry, exactly where the typed values put it ('Add sketch arc', 'Add sketch line').
2. beforeCreateAutoConstraints: the on-view fields' controller adds a constraint for each value typed
   (DistanceX/DistanceY, Radius, Angle, Distance), outside any transaction, each written through C's '%f':
   6 decimals in mm, and in radians for an angle typed in degrees. A typed 90 deg sweep is kept as 1.570796 rad,
   and the solver moves the end of an R63.5 arc 2e-5 mm off the point typed (sketch_core.exact_datum).
3. generateAutoConstraints: the Coincident FreeCAD found at the typed position (it preselects what lies there)
   is checked against the sketch, which by now holds step 2's constraints. They fix the typed point already,
   so the Coincident is redundant: removeRedundantAutoConstraints says "Autoconstraints cause redundancy.
   Removing them", and when the solver names one of step 2's constraints instead (it does for these arcs and
   lines) it throws "Redundant constraint is not an autoconstraint. No autoconstraints or additional constraints
   were added. Please report!". The controller's branch that adds a typed constraint only where the point keeps
   a degree of freedom (its "valid diagnosis") never runs: the autoconstraints are made after it.
4. createAutoConstraints, in 'Add Auto-Constraints' (FreeCAD signals a transaction only once it changes
   something: none when no autoconstraint is left, or after step 3 threw).

   Step 3 checks on the geometry before it solves: an autoconstraint it keeps can still make the solved sketch
   redundant (two arcs that meet tangentially are exactly tangent once solved), and the sketch then fails to
   solve from that curve on.

TypedGuard notes the tool's geometry transaction and, once the tool's finish() is over (a zero timer from the
geometry's commit), takes back the constraints the tool added (steps 2 and 4) and puts them back in NX's order:

* a Coincident for each of the tool's points that lies on a point of another curve or on the origin, within
  Validate Sketch's default tolerance for missing coincidences (sketch_core.missing_joins);
* FreeCAD's autoconstraints, then the typed values, each with the value typed (from the on-view fields as they
  were typed), each kept only if the solved sketch takes it without redundancy: what step 2's "valid
  diagnosis" branch does.

Like FreeCAD's own steps 2 and 3 and Quick Trim's guard, this adds no undo step.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import sketch_core as core
from .qt import QtCore, QtWidgets

GEOMETRY = "Add sketch "                  # the tools' geometry transactions: 'Add sketch arc', 'Add sketch line'
AUTO = "Add Auto-Constraints"
JOIN_TOL = 1e-4                           # mm: Validate Sketch's default for missing coincidences
QSB = "Gui::QuantitySpinBox"


def edited_sketch():
    from .sketch_ui import edited_sketch as edited
    return edited()


def on_view_field(obj):
    """The sketcher on-view field an event concerns (the field or its line edit), or None."""
    from .precise_input import in_3d_view
    try:
        w = obj if obj.inherits(QSB) else None
        if w is None and isinstance(obj, QtWidgets.QLineEdit):
            p = obj.parent()
            w = p if p is not None and p.inherits(QSB) else None
        return w if w is not None and in_3d_view(w) else None
    except RuntimeError:                  # deleted widget
        return None


def field_number(w):
    """(the field's value in FreeCAD's internal units, mm or degrees, True for an angle), or None."""
    q = w.property("value")
    if q is None or not hasattr(q, "Unit"):
        return None
    return q.Value, q.Unit == App.Units.Quantity(1, App.Units.Angle).Unit


def shown_numbers():
    """field_number of every on-view field the 3D views hold now (a value confirmed by a click, not Enter)."""
    from .precise_input import in_3d_view
    out = []
    for w in Gui.getMainWindow().findChildren(QtWidgets.QAbstractSpinBox):
        try:
            if w.inherits(QSB) and in_3d_view(w):
                n = field_number(w)
                if n is not None:
                    out.append(n)
        except RuntimeError:
            pass
    return out


POINTS = {"Part::GeomLineSegment": (1, 2), "Part::GeomArcOfCircle": (1, 2, 3), "Part::GeomArcOfEllipse": (1, 2, 3),
          "Part::GeomArcOfHyperbola": (1, 2, 3), "Part::GeomArcOfParabola": (1, 2, 3), "Part::GeomCircle": (3,),
          "Part::GeomEllipse": (3,), "Part::GeomPoint": (1,), "Part::GeomBSplineCurve": (1, 2)}


def vertices(sk):
    """{(GeoId, PointPos): (x, y)} of the sketch's own curves (start 1, end 2, centre 3), and its origin (-1, 1): a
    point held on the origin is joined to every other point held there."""
    out = {(-1, 1): (0.0, 0.0)}
    for g, geo in enumerate(sk.Geometry):
        for pos in POINTS.get(geo.TypeId, ()):
            p = sk.getPoint(g, pos)
            out[(g, pos)] = (p.x, p.y)
    return out


def links(sk):
    return [((c.First, int(c.FirstPos)), (c.Second, int(c.SecondPos))) for c in sk.Constraints
            if c.Type in core.JOINING and int(c.FirstPos) and int(c.SecondPos)]


def redundant(sk):
    sk.solve()
    return bool(sk.RedundantConstraints) or bool(sk.ConflictingConstraints)


class TypedGuard(QtCore.QObject):
    """Document observer for the sketch tools' transactions, and application event filter for the on-view
    fields (it records what is typed; it never consumes an event)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = True
        self.typed = []               # (value, is_angle) typed since the last tool finished
        self.open_name = None
        self.pending = None
        self.last = None              # what the last repair did, for tests and the tutorials

    # ------------------------------------------------------------ what is typed
    KEYS = (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Tab)     # what confirms an on-view field

    def eventFilter(self, obj, ev):
        if self.enabled and ev.type() == QtCore.QEvent.KeyPress and ev.key() in self.KEYS:
            w = on_view_field(obj)
            if w is not None:
                try:
                    n = field_number(w)
                    if n is not None:
                        self.typed.append(n)
                except Exception:
                    pass
        return False

    # ------------------------------------------------------------ the tool's transactions
    def slotOpenTransaction(self, doc, name):
        self.open_name = name
        sk = edited_sketch() if self.enabled else None
        if sk is None or sk.Document != doc:
            return
        if name.startswith(GEOMETRY):
            self.pending = {"sk": sk, "name": name, "geo0": len(sk.Geometry),
                            "typed": list(self.typed) + shown_numbers()}
        elif name == AUTO and self.pending is not None and "typed0" in self.pending and "typed1" not in self.pending:
            self.pending["typed1"] = len(sk.Constraints)      # FreeCAD signals it before its first change

    def slotAbortTransaction(self, doc):
        if self.open_name is not None and self.open_name.startswith(GEOMETRY):
            self.pending = None
        self.open_name = None

    def slotCommitTransaction(self, doc):
        name, self.open_name = self.open_name, None
        p = self.pending
        if p is not None and p["sk"].Document == doc and name == p["name"] and "typed0" not in p:
            p["typed0"] = len(p["sk"].Constraints)
            # the tool's finish() goes on in the same call: its typed constraints, then its autoconstraints (no
            # 'Add Auto-Constraints' transaction when there are none, or when the redundancy check threw)
            QtCore.QTimer.singleShot(0, lambda: self.repair(p))

    # ------------------------------------------------------------ the repair
    def repair(self, p):
        if self.pending is p:
            self.pending = None
        self.typed = []
        try:
            p["sk"].Constraints
        except Exception:                 # the sketch is gone
            return
        try:
            self._repair(p)
        except Exception as e:            # never in the way of FreeCAD's tool: what it made stays as it is
            self.last = {"tool": p["name"], "error": repr(e)}
            App.Console.PrintWarning(f"NX-Style typed points: repair skipped: {e}\n")

    def _repair(self, p):
        """The tool's constraints are taken back and put back: the joins first, then FreeCAD's autoconstraints,
        then the typed values (exact), each kept only if the solved sketch takes it without redundancy.

        FreeCAD checks its autoconstraints for redundancy on the geometry before it solves; solved, two arcs that
        meet tangentially (AV's R0.50 end between its R1.50 and R2.50 bands) are exactly tangent, and a Coincident
        there with the typed radius and centre is redundant. The sketch then does not solve at all ('Solving the
        sketch failed'), and setDatum fails too (its error codes come from the solve)."""
        import Sketcher
        sk = p["sk"]
        n = len(sk.Constraints)
        t0, t1 = p["typed0"], min(p.get("typed1", n), n)
        new = set(range(p["geo0"], len(sk.Geometry)))
        typed = [sk.Constraints[i] for i in range(t0, t1)]
        auto = [sk.Constraints[i] for i in range(t1, n)]
        values = [core.exact_datum(c.Value, p["typed"]) if c.Type in core.TYPED_DATUMS else None for c in typed]
        exact = [(c.Type, c.First, c.Value, v) for c, v in zip(typed, values) if v is not None]
        self.last = {"tool": p["name"], "typed": p["typed"], "exact": exact, "missing": [], "joined": [],
                     "refused": [], "dropped": []}
        was_sound = not redundant(sk)
        missing = core.missing_joins(vertices(sk), new, links(sk), JOIN_TOL) if new else []
        if was_sound and not missing and not exact:
            return
        for i in reversed(range(t0, n)):
            sk.delConstraint(i)
        if redundant(sk):                 # not sound before this tool: put back what FreeCAD made, as it was
            for c in typed + auto:
                sk.addConstraint(c)
            self.last["skipped"] = "the sketch had redundant constraints before this tool"
            return
        # after the tool's constraints are gone, a point FreeCAD joined is free again: look again
        missing = core.missing_joins(vertices(sk), new, links(sk), JOIN_TOL) if new else []
        joins, refused, dropped = self.last["joined"], self.last["refused"], self.last["dropped"]
        self.last["missing"] = missing

        def keep(c, value=None):
            k = sk.addConstraint(c)
            if value is not None:
                try:
                    sk.setDatum(k, value)
                except Exception:
                    pass                  # the redundancy check below decides
            if redundant(sk):
                sk.delConstraint(k)
                return False
            return True

        for (g1, p1), (g2, p2) in missing:
            (joins if keep(Sketcher.Constraint("Coincident", g1, p1, g2, p2)) else refused).append(
                ((g1, p1), (g2, p2)))
        for c, v in [(c, None) for c in auto] + list(zip(typed, values)):
            if not keep(c, v):            # the joins hold what it held
                dropped.append((c.Type, c.First, int(c.FirstPos), c.Value))
        sk.solve()
        if exact or joins:
            App.Console.PrintLog(f"NX-Style typed points: {len(exact)} typed value(s) kept exactly, {len(joins)} "
                                 f"end point(s) joined, {len(dropped)} typed constraint(s) the joins replace: "
                                 f"{self.last}\n")
            sk.Document.recompute()


guard = None


def install():
    global guard
    if guard is None:
        guard = TypedGuard(QtWidgets.QApplication.instance())
        QtWidgets.QApplication.instance().installEventFilter(guard)
        App.addDocumentObserver(guard)
    return guard
