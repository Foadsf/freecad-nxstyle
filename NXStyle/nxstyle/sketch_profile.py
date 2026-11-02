# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX's on-screen input for Profile (Z): X and Y for the first point, then the length and angle of each line (the
radius and sweep of an arc), typed in fields beside the pointer, as FreeCAD's Line offers them.

FreeCAD 1.1.4's Polyline (DrawSketchHandlerLineSet) is the one curve tool still on the old sketch handler: it has
no on-view fields, so a point can only be clicked. While it runs, NX-Style shows fields like FreeCAD's own
(Gui::QuantitySpinBox over the 3D view; OnViewParameterVisibility decides, as for FreeCAD's tools: X and Y only
with 'position and dimensions'). They follow the pointer; a value typed and confirmed with Enter (or Tab) is
locked. Once a point's values are locked, or the user clicks with one of them locked (the pointer gives the
other), NX-Style clicks the tool at the point they give, with the sketch's autoconstraints off for that click (a
curve within the pick radius of the point would get an inferred constraint that fights the typed values).

When FreeCAD has added the segment ('Add line to sketch polyline', 'Add arc to sketch polyline'), the values typed
hold it, as FreeCAD's Line holds its typed values (sketch_core.profile_constraints), each with the number typed: a
Coincident first where a typed point lies on a point of another curve or on the origin (within sketch_typed's
1e-4 mm), then the typed values, each kept only if the solved sketch takes it without redundancy. A point typed
onto the profile's first point closes it as a click there does (FreeCAD's Coincident then holds the end, and the
typed length and angle go). Like FreeCAD's own repair steps this adds no undo step.

The Polyline's segment mode (free, tangent or perpendicular line, the arcs: M) is not visible from Python;
ProfileInput follows it as the handler switches it (sketch_core.profile_mode_after, profile_mode_switch). The tool
is known to run from its command's action (Z, the ribbon, FreeCAD's toolbar), and to end with FreeCAD's input
hints, another sketch command or Esc; Gui.runCommand('Sketcher_CreatePolyline') from a macro gets no fields.
"""

import math
import time

import FreeCAD as App
import FreeCADGui as Gui

from . import sketch_core as core
from .qt import Qt, QtCore, QtWidgets, mouse_event

POLYLINE = "Sketcher_CreatePolyline"
SEGMENT = ("Add line to sketch polyline", "Add arc to sketch polyline")
FIELD = "nxProfileField"          # dynamic property: which value an NX-Style Profile field holds
ANGLES = ("angle", "direction", "sweep")
TIPS = {"x": "X", "y": "Y", "length": "Length", "angle": "Angle (degrees from the X axis)",
        "direction": "Angle: held by the curve before (M switches the mode)", "radius": "Radius",
        "sweep": "Sweep angle (degrees, counter-clockwise positive)"}
CONFIRM = (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab)
TYPING = "0123456789.,-+"


def edited_sketch():
    from .sketch_ui import edited_sketch as edited
    return edited()


def visibility():
    from . import prefs
    return App.ParamGet(prefs.SKETCHER_TOOLS).GetInt("OnViewParameterVisibility", 1)


def _same(a, b):
    try:
        return a is not None and b is not None and (a is b or a == b)
    except RuntimeError:
        return False


class ProfileInput(QtCore.QObject):
    """Application event filter (it consumes only the keys and clicks meant for its fields) and document
    observer for FreeCAD's Polyline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = True
        self.stage = None              # None (Polyline not running), 'first' or 'next' point
        self.sk = self.view = self.widget = None
        self.kinds = ()
        self.visibility = 2
        self.fields = {}               # kind -> field widget
        self.locked = {}               # kind -> value typed
        self.start = None              # where the next segment starts (sketch mm)
        self.prev = None               # (GeoId, PointPos) the next segment continues from, as the handler keeps it
        self.prev_arc = False
        self.segment, self.transition = core.LINE, core.FREE
        self.chain_first = None        # (GeoId, PointPos) of the profile's first point, once its first segment is in
        self.first_typed = {}          # the first point's typed values, held once its segment is in
        self.first_target = None
        self.pending = None            # the typed values of the segment FreeCAD is adding
        self.pointer = None            # the pointer in the view (widget pixels)
        self.placing = False
        self.swallow_release = False
        self.open_name = None
        self.hooked = set()
        self.actions = []               # the hooked actions, kept so their wrappers live
        self.scanned = 0.0
        self.log = []                  # what each typed point did, for tests and the tutorials
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.check_alive)

    # ------------------------------------------------------------ the tool starts and ends
    def hook_actions(self):
        """Connect to the actions of the sketch commands: Polyline's starts the fields, any other ends them (FreeCAD
        replaces the running tool). Actions FreeCAD makes later are picked up by the next scan."""
        self.scanned = time.monotonic()
        for name in Gui.listCommands():
            if not name.startswith(("Sketcher_", "NXStyle_")):
                continue
            try:
                acts = Gui.Command.get(name).getAction() or []
            except Exception:
                continue
            for a in acts:
                self.hook_action(a, name)
        self.hook_polyline()

    def hook_action(self, a, name=None):
        """Connect one command's action to the guard. The command's own name is the action's objectName: a group
        command's list holds its entries (FreeCAD's Sketcher 'Line' group holds the Polyline), so the Polyline is
        caught under its own name whichever list it is found in. The action is kept, so the connection lives."""
        try:
            key = a.objectName() or name or ""
        except RuntimeError:
            return
        if not key or key in self.hooked:
            return
        try:
            a.triggered.connect(lambda _=False, n=key: self.on_command(n))
            self.hooked.add(key)
            self.actions.append(a)
        except Exception:
            pass

    def hook_polyline(self):
        """Hook the Polyline's action now: the scan may not have run yet when the key comes (the Sketcher's commands
        get their actions only once the workbench is loaded)."""
        try:
            acts = Gui.Command.get(POLYLINE).getAction() or []
        except Exception:
            return
        for a in acts:
            self.hook_action(a, POLYLINE)

    def on_command(self, name):
        if not self.enabled:
            return
        if name == POLYLINE:
            QtCore.QTimer.singleShot(0, self.begin)        # after FreeCAD's own slot has started the tool
        elif self.stage is not None:
            self.end()

    def begin(self):
        sk = edited_sketch()
        if sk is None or not self.enabled:
            return
        self.end()
        try:
            self.view = Gui.ActiveDocument.ActiveView
            self.widget = self.view.graphicsView().viewport()
        except Exception:
            return
        self.sk = sk
        self.visibility = visibility()
        self.reset_chain()
        self.timer.start()
        from .qt import QtGui
        p = self.pointer if self.pointer is not None else self.widget.mapFromGlobal(QtGui.QCursor.pos())
        self.follow(p)

    def reset_chain(self):
        self.stage = "first"
        self.start = self.prev = self.chain_first = self.first_target = self.pending = None
        self.prev_arc = False
        self.first_typed = {}
        self.segment, self.transition = core.LINE, core.FREE
        self.rebuild()

    def end(self):
        self.stage = None
        self.timer.stop()
        self.locked = {}
        self.kinds = ()
        for w in self.fields.values():
            try:
                w.hide()
                w.deleteLater()
            except RuntimeError:
                pass
        self.fields = {}

    def check_alive(self):
        from .navigation import in_sketch_edit, tool_hints_shown
        if self.placing:
            return
        sk = edited_sketch()
        try:
            same = sk is not None and sk.Name == self.sk.Name and sk.Document == self.sk.Document
        except Exception:
            same = False
        if not in_sketch_edit() or not same or not tool_hints_shown():
            self.end()

    # ------------------------------------------------------------ the fields
    def host(self):
        return self.view.graphicsView().parentWidget()      # FreeCAD's own on-view fields sit on the MDI view

    def make_field(self, kind):
        host = self.host()
        w = None
        try:
            w = Gui.UiLoader().createWidget("Gui::QuantitySpinBox", host)
            w.setProperty("unit", "deg" if kind in ANGLES else "mm")
            w.setProperty("autoNormalize", False)
            w.setProperty("minimum", -1e12)
            w.setProperty("maximum", 1e12)
        except Exception:
            w = None
        if w is None:
            w = QtWidgets.QDoubleSpinBox(host)
            w.setRange(-1e12, 1e12)
            w.setDecimals(6)
            w.setSuffix(" °" if kind in ANGLES else " mm")
        w.setProperty(FIELD, kind)
        w.setToolTip(TIPS.get(kind, kind))
        w.setFocusPolicy(Qt.ClickFocus)
        w.setMinimumWidth(110)
        if kind == "direction":
            w.setReadOnly(True)
        w.show()
        return w

    def rebuild(self):
        kinds = core.profile_fields(self.stage, self.segment, self.transition, self.visibility)
        self.locked = {}
        if kinds == self.kinds and all(self.alive(w) for w in self.fields.values()):
            for w in self.fields.values():
                w.setStyleSheet("")
            return
        for w in self.fields.values():
            try:
                w.hide()
                w.deleteLater()
            except RuntimeError:
                pass
        self.kinds = kinds
        self.fields = {k: self.make_field(k) for k in kinds}

    @staticmethod
    def alive(w):
        try:
            w.objectName()
            return True
        except RuntimeError:
            return False

    @staticmethod
    def show_value(w, kind, v):
        if isinstance(w, QtWidgets.QDoubleSpinBox):
            w.setValue(v)
        else:
            w.setProperty("value", App.Units.Quantity(v, App.Units.Angle if kind in ANGLES else App.Units.Length))

    @staticmethod
    def typed_value(w):
        """The number the field's text says (mm or degrees), or None."""
        if isinstance(w, QtWidgets.QDoubleSpinBox):
            w.interpretText()
            return w.value()
        from .precise_input import typed_quantity
        current = w.property("value")
        if current is None or not hasattr(current, "Value"):
            return None
        q = typed_quantity(w, current)
        return (q if q is not None else current).Value

    def direction(self):
        """The direction the next segment leaves in (tangent or square to the curve before), or None."""
        if self.prev is None or self.segment == core.LINE and self.transition == core.FREE:
            return None
        sk, (g, pos) = self.sk, self.prev
        try:
            geo = sk.Geometry[g]
        except Exception:
            return None
        kind = core.ARC if "ArcOfCircle" in geo.TypeId else core.LINE
        pt = lambda p: (sk.getPoint(g, p).x, sk.getPoint(g, p).y)     # noqa: E731
        d = core.end_direction(kind, pt(1), pt(2), pt(3) if kind == core.ARC else None, pos)
        return core.transition_direction(self.transition, d)

    def compute(self, cursor):
        either = self.transition in (core.PERP_L, core.PERP_R) and self.segment == core.LINE
        return core.profile_point(self.kinds, {k: v for k, v in self.locked.items() if k != "direction"}, cursor,
                                  self.start, self.direction(), either)

    def cursor(self, p):
        from .sketch_ui import cursor_on_sketch
        return cursor_on_sketch(self.sk, self.widget, p)

    def follow(self, p):
        """The pointer moved to p: unlocked fields show its values, and the fields go beside it."""
        self.pointer = QtCore.QPoint(p)
        if not self.fields:
            return
        try:
            shown, _target = self.compute(self.cursor(p))
        except Exception:
            return
        focus = QtWidgets.QApplication.focusWidget()
        host = self.host()
        at = host.mapFrom(self.widget, p)
        for i, (kind, w) in enumerate(self.fields.items()):
            if not self.alive(w):
                continue
            if kind not in self.locked and not (_same(focus, w) or _same(focus, w.lineEdit())):
                self.show_value(w, kind, shown.get(kind, 0.0))
            x = max(0, min(at.x() + 18, max(0, host.width() - w.width())))
            y = max(0, min(at.y() + 18 + i * (w.height() + 4), max(0, host.height() - w.height())))
            w.move(x, y)

    def field_of(self, obj):
        for w in self.fields.values():
            try:
                if _same(obj, w) or _same(obj, w.lineEdit()):
                    return w
            except RuntimeError:
                continue
        return None

    def focus_field(self, w):
        w.setFocus()
        w.lineEdit().selectAll()

    def focus_view(self):
        try:
            self.view.graphicsView().setFocus()
        except Exception:
            pass

    def needed(self):
        return [k for k in self.kinds if k != "direction"]

    def confirm(self, w):
        """Enter (or Tab) in a field: its value is locked; with every value the point needs locked, the point goes
        in. Otherwise the next field takes the keys."""
        kind = w.property(FIELD)
        v = self.typed_value(w)
        if v is None or kind == "direction":
            return
        self.locked[kind] = v
        w.setStyleSheet("font-weight: bold;")
        rest = [k for k in self.needed() if k not in self.locked]
        if rest:
            self.focus_field(self.fields[rest[0]])
        else:
            self.place()

    # ------------------------------------------------------------ a typed point goes in
    def pixel(self, xy):
        g = self.sk.getGlobalPlacement().multVec(App.Vector(xy[0], xy[1], 0))
        sx, sy = self.view.getPointOnViewport(g)
        w = self.widget
        dpr = w.devicePixelRatioF() if hasattr(w, "devicePixelRatioF") else 1.0
        return QtCore.QPoint(int(round(sx / dpr)), int(round(w.height() - sy / dpr)))

    def place(self, cursor=None):
        """Click the tool where the locked values (the pointer for the others) put the point."""
        if cursor is None:
            cursor = self.cursor(self.pointer) if self.pointer is not None else (0.0, 0.0)
        values = {k: v for k, v in self.locked.items() if k != "direction"}
        _shown, target = self.compute(cursor)
        rec = {"stage": self.stage, "fields": self.kinds, "typed": dict(values), "target": target,
               "mode": (self.segment, self.transition)}
        p = self.pixel(target)
        rec["pixel"] = (p.x(), p.y())
        if self.stage == "first":
            self.first_typed, self.first_target = values, target if len(values) == 2 else None
        else:
            self.pending = {"fields": self.kinds, "values": values,
                            "target": target if len(values) == len(self.needed()) else None, "rec": rec}
        stage = self.stage
        vo = self.sk.ViewObject
        auto = getattr(vo, "Autoconstraints", None)
        self.placing = True
        try:
            if auto is not None:
                vo.Autoconstraints = False
            for kind, button, buttons in ((QtCore.QEvent.MouseMove, Qt.NoButton, Qt.NoButton),
                                          (QtCore.QEvent.MouseButtonPress, Qt.LeftButton, Qt.LeftButton),
                                          (QtCore.QEvent.MouseButtonRelease, Qt.LeftButton, Qt.NoButton)):
                QtWidgets.QApplication.sendEvent(self.widget, mouse_event(kind, p, button, buttons, Qt.NoModifier))
        finally:
            if auto is not None:
                vo.Autoconstraints = auto
            self.placing = False
        self.log = (self.log + [rec])[-40:]
        if stage == "first" and self.stage == "first":
            self.stage, self.start = "next", tuple(target)
            self.rebuild()
        else:
            self.locked = {}
            for w in self.fields.values():
                w.setStyleSheet("")
        self.focus_view()
        if self.pointer is not None:
            self.follow(self.pointer)

    def clicked(self, p):
        """A click of the user's own (no value locked): the tool takes the point; follow it."""
        if self.stage != "first":
            return
        cursor = self.cursor(p)
        self.start, self.prev, self.prev_arc = tuple(cursor), None, False
        self.segment, self.transition = core.LINE, core.FREE
        vo = self.sk.ViewObject
        if getattr(vo, "Autoconstraints", True):
            # FreeCAD continues from the end of a line or arc clicked on (DrawSketchHandlerLineSet::pressButton)
            try:
                pre = Gui.Selection.getPreselection()
                subs = pre.SubElementNames if pre.ObjectName == self.sk.Name else []
            except Exception:
                subs = []
            for sub in subs:
                if sub.startswith("Vertex"):
                    g, pos = self.sk.getGeoVertexIndex(int(sub[6:]) - 1)
                    pos = int(pos)
                    geo = self.sk.Geometry[g] if 0 <= g < len(self.sk.Geometry) else None
                    if geo is not None and pos in (1, 2) and geo.TypeId in ("Part::GeomLineSegment",
                                                                            "Part::GeomArcOfCircle"):
                        self.prev, self.prev_arc = (g, pos), "Arc" in geo.TypeId
                        q = self.sk.getPoint(g, pos)
                        self.start = (q.x, q.y)
                        if self.prev_arc:
                            self.transition = core.TANGENT
        self.first_typed, self.first_target = {}, None
        self.stage = "next"
        self.rebuild()

    # ------------------------------------------------------------ FreeCAD added the segment
    def slotOpenTransaction(self, doc, name):
        self.open_name = name

    def slotAbortTransaction(self, doc):
        self.open_name = None

    def slotCommitTransaction(self, doc):
        name, self.open_name = self.open_name, None
        if self.stage is None or name not in SEGMENT or self.sk is None:
            return
        try:
            if self.sk.Document != doc:
                return
        except Exception:
            return
        pend, self.pending = self.pending, None
        QtCore.QTimer.singleShot(0, lambda: self.segment_added(name, pend))   # after the tool's releaseButton

    def segment_added(self, name, pend):
        sk = self.sk
        try:
            g = len(sk.Geometry) - 1
        except Exception:
            return
        is_arc = "arc" in name
        ends = {pos: (sk.getPoint(g, pos).x, sk.getPoint(g, pos).y) for pos in (1, 2)}
        s = self.start or ends[1]
        start_pos = 1 if not is_arc else min((1, 2), key=lambda q: math.hypot(ends[q][0] - s[0], ends[q][1] - s[1]))
        end_pos = 3 - start_pos
        first = self.chain_first is None
        if first:
            self.chain_first = (g, start_pos)
        closed = not first and any(
            c.Type == "Coincident" and {(c.First, int(c.FirstPos)), (c.Second, int(c.SecondPos))}
            == {(g, end_pos), self.chain_first} for c in sk.Constraints)
        specs, overrides = [], {}
        if first and self.first_typed:
            specs += core.profile_constraints(("x", "y"), self.first_typed, g, start_pos, end_pos)
            if self.first_target is not None:
                overrides[(g, start_pos)] = self.first_target
        if pend:
            specs += core.profile_constraints(pend["fields"], pend["values"], g, start_pos, end_pos)
            if pend["target"] is not None:
                overrides[(g, end_pos)] = pend["target"]
        held = self.hold(sk, g, specs, overrides) if specs else None
        if pend:
            pend["rec"]["held"] = held
        elif held is not None:
            self.log = (self.log + [{"stage": "first", "held": held}])[-40:]
        self.first_typed, self.first_target = {}, None
        if closed:
            self.reset_chain()
        else:
            q = sk.getPoint(g, end_pos)
            self.start, self.prev, self.prev_arc = (q.x, q.y), (g, end_pos), is_arc
            self.segment, self.transition = core.profile_mode_after(is_arc)
            self.rebuild()
        if self.pointer is not None:
            self.follow(self.pointer)

    def hold(self, sk, g, specs, overrides):
        """The typed values hold the segment: joins first, then each value, each only if the solved sketch takes
        it without redundancy."""
        import Sketcher
        from .sketch_typed import JOIN_TOL, links, redundant, vertices
        rec = {"geo": g, "joined": [], "kept": [], "dropped": []}
        if redundant(sk):
            rec["skipped"] = "the sketch had redundant or conflicting constraints before this segment"
            return rec
        pts = vertices(sk)
        pts.update(overrides)
        joins = [j for j in core.missing_joins(pts, {g}, links(sk), JOIN_TOL) if j[0] in overrides]

        def keep(args):
            k = sk.addConstraint(Sketcher.Constraint(*args))
            if redundant(sk):
                sk.delConstraint(k)
                return False
            return True

        for (g1, p1), (g2, p2) in joins:
            args = ("Coincident", g1, p1, g2, p2)
            rec["joined" if keep(args) else "dropped"].append(args)
        for args in specs:
            rec["kept" if keep(args) else "dropped"].append(args)
        sk.solve()
        sk.Document.recompute()
        return rec

    # ------------------------------------------------------------ events
    def in_view(self, obj):
        """Is the event's widget the 3D view's? (Also before the tool starts: the pointer may move before the
        fields are made.)"""
        try:
            w = self.widget or self.view_widget()
            return _same(obj, w) or _same(obj, self.view.graphicsView() if self.view is not None else None)
        except RuntimeError:
            return False

    @staticmethod
    def view_widget():
        """The 3D view's viewport, or None."""
        try:
            return Gui.ActiveDocument.ActiveView.graphicsView().viewport()
        except Exception:
            return None

    def eventFilter(self, obj, ev):
        t = ev.type()
        if self.enabled and t in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.MouseButtonPress):
            try:
                if time.monotonic() - self.scanned > 1.0:
                    self.hook_actions()
                elif t == QtCore.QEvent.ShortcutOverride:
                    self.hook_polyline()        # the key may come before the next scan
            except Exception:
                pass
        if self.stage is None:
            if t == QtCore.QEvent.MouseMove and self.enabled and self.in_view(obj):
                # the pointer moves before the tool starts (the key and the first move can come in one go):
                # remember it, so the fields that appear show the pointer's values
                self.pointer = QtCore.QPoint(ev.pos())
            return False
        if self.placing or not self.enabled:
            return False
        try:
            return self._event(obj, ev, t)
        except Exception as e:           # never in the way of FreeCAD's tool
            App.Console.PrintWarning(f"NX-Style Profile fields: {e}\n")
            return False

    def _event(self, obj, ev, t):
        w = self.field_of(obj) if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride) else None
        if w is not None:
            if t == QtCore.QEvent.ShortcutOverride:
                ev.accept()               # the field takes its keys: no sketch shortcut (M, digits) while typing
                return False
            if ev.key() in CONFIRM:
                self.confirm(w)
                return True
            if ev.key() == Qt.Key_Escape:
                self.locked = {}
                for f in self.fields.values():
                    f.setStyleSheet("")
                self.focus_view()
                return True
            return False
        if not self.in_view(obj):
            return False
        if t == QtCore.QEvent.KeyPress:
            focus = QtWidgets.QApplication.focusWidget()
            if focus is None:
                # no focus widget: the viewport's own event is the press, the graphics view gets Qt's copy of it
                if not _same(obj, self.widget):
                    return False
            elif obj is not focus:
                # Qt propagates a key the focus widget ignored up to its parent: the same press, already handled
                return False
        if t == QtCore.QEvent.MouseMove:
            self.follow(ev.pos())
        elif t == QtCore.QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            self.pointer = QtCore.QPoint(ev.pos())
            if {k for k in self.locked if k != "direction"}:
                self.swallow_release = True
                self.place(self.cursor(ev.pos()))
                return True
            self.clicked(ev.pos())
        elif t == QtCore.QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton and self.swallow_release:
            self.swallow_release = False
            return True
        elif t == QtCore.QEvent.KeyPress:
            k = ev.key()
            if k == Qt.Key_Escape:
                # FreeCAD's quit(): an open profile ends and the tool stays; with no segment drawn the tool ends
                if self.stage == "next" and self.chain_first is not None:
                    self.reset_chain()
                else:
                    self.end()
            elif k == Qt.Key_M and not ev.modifiers():
                if self.stage == "next" and self.prev is not None:
                    self.segment, self.transition = core.profile_mode_switch(self.segment, self.transition,
                                                                             self.prev_arc)
                    self.rebuild()
                    if self.pointer is not None:
                        QtCore.QTimer.singleShot(0, lambda: self.follow(self.pointer))
            elif self.fields and (k == Qt.Key_Tab or ev.text() and ev.text() in TYPING):
                rest = [f for f in self.needed() if f not in self.locked]
                if rest:
                    f = self.fields[rest[0]]
                    self.focus_field(f)
                    if k != Qt.Key_Tab:
                        f.lineEdit().insert(ev.text())
                    return True
        return False


guard = None


def install():
    global guard
    if guard is None:
        guard = ProfileInput(QtWidgets.QApplication.instance())
        QtWidgets.QApplication.instance().installEventFilter(guard)
        App.addDocumentObserver(guard)
        try:
            guard.hook_actions()
        except Exception:
            pass
    return guard
