# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX mouse behaviour in FreeCAD's 3D views.

An event filter on each 3D viewport takes over the middle button (MB2) and
the right-button hold; everything else falls through to FreeCAD's Blender
navigation style (MB1 select, wheel zoom, MB3 click context menu).

    MB2 drag                    rotate (about the view centre)
    press-and-hold MB2, drag    rotate about the point under the cursor
    Shift+MB2 or MB2+MB3 drag   pan
    Ctrl+MB2 or MB1+MB2 drag    zoom
    MB2 click                   OK in the open feature dialog
    hold MB3                    radial menu (view, or object under cursor)
    rest the pointer, MB1 click QuickPick (NX 2212): the cursor shows three dots over overlapping
                                objects; the click opens the list of everything under it
    hold MB1 still              QuickPick too
    MB1 click                   selects through what the selection filter refuses

An MB1 press is held back until the button is released, the mouse moves or the hold time passes, and
then handed to FreeCAD unchanged; only the hold and the select-through click are NXStyle's own.
"""

import math
import time

import FreeCAD as App
import FreeCADGui as Gui

from . import commands, config, prefs
from .qt import QtCore, QtGui, QtWidgets, Qt, global_pos, mouse_event, pos
from .radial import RadialMenu
from .ribbon import command_icon, is_enabled, known_commands, resolve, trigger

MOVE_THRESHOLD = 3
# A click answers the QuickPick dots only if it comes this long after they appeared: a press already
# queued while FreeCAD was busy (the rest timer fired late) is an ordinary click
REACT_S = 0.15


def _coin():
    from pivy import coin
    return coin


def in_sketch_edit():
    try:
        gdoc = Gui.ActiveDocument
        obj = gdoc.getInEdit() if gdoc else None
        return bool(obj and obj.Object.isDerivedFrom("Sketcher::SketchObject"))
    except Exception:
        return False


def accept_task_dialog():
    """Press OK in the open task dialog, like NX's MB2 = OK. Returns True on success."""
    try:
        if not Gui.Control.activeDialog() or in_sketch_edit():
            return False
    except Exception:
        return False
    mw = Gui.getMainWindow()
    boxes = []
    for dock in mw.findChildren(QtWidgets.QDockWidget):
        if dock.objectName() in ("Tasks", "Combo View", "ComboView") or "task" in dock.objectName().lower():
            boxes += dock.findChildren(QtWidgets.QDialogButtonBox)
    for box in boxes:
        ok = box.button(QtWidgets.QDialogButtonBox.Ok)
        if ok is not None and ok.isVisible() and ok.isEnabled():
            ok.click()
            return True
    return False


def status(text, ms=2500):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, ms)
    except Exception:
        pass


def run_command(name):
    commands.remember(name)
    trigger(name)


_qp_cursor = None


def quickpick_cursor():
    """An arrow with three dots: NX's sign that the pointer rests over several objects."""
    global _qp_cursor
    if _qp_cursor is None:
        pix = QtGui.QPixmap(32, 32)
        pix.fill(Qt.transparent)
        p = QtGui.QPainter(pix)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        arrow = QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in
                                 ((1, 1), (1, 17), (5, 13), (8, 20), (10, 19), (7, 12), (12, 12))])
        p.setPen(QtGui.QPen(Qt.white, 1.5))
        p.setBrush(Qt.black)
        p.drawPolygon(arrow)
        p.setPen(QtGui.QPen(Qt.white, 1))
        for i in range(3):
            p.drawEllipse(QtCore.QPointF(15 + 5 * i, 23), 2, 2)
        p.end()
        _qp_cursor = QtGui.QCursor(pix, 1, 1)
    return _qp_cursor


VIEW_RADIAL = [
    ("Fit", "Std_ViewFitAll"),
    ("Shaded with Edges", "Std_DrawStyleFlatLines"),
    ("Shaded", "Std_DrawStyleShaded"),
    ("Wireframe with Hidden Edges", "Std_DrawStyleHidden"),
    ("Static Wireframe", "Std_DrawStyleWireframe"),
    ("Isometric", "Std_ViewIsometric"),
    ("Trimetric", "Std_ViewTrimetric"),
    ("Snap View", "NXStyle_SnapView"),
]

OBJECT_RADIAL = [
    ("Edit Parameters", ["NXStyle_EditParameters", "Std_Edit"]),
    ("Edit Object Display", ["Std_SetAppearance", "Std_DlgDisplayProperties"]),
    ("Hide", "Std_HideSelection"),
    ("Delete", "Std_Delete"),
    ("Fit Selection", "Std_ViewFitSelection"),
    ("Measure", ["Std_Measure", "Part_Measure_Linear"]),
    ("Move Object", "Std_TransformManip"),
    ("Show Only", None),
]


def show_only_selected():
    doc = App.ActiveDocument
    if doc is None:
        return
    keep = {s.Object.Name for s in Gui.Selection.getSelectionEx("", 0)}
    doc.openTransaction("Show Only")
    for o in commands.display_objects(doc):
        o.ViewObject.Visibility = o.Name in keep
    for name in keep:
        o = doc.getObject(name)
        if o is not None and o.ViewObject is not None:
            o.ViewObject.Visibility = True
    doc.commitTransaction()


def radial_items(spec):
    known = known_commands()
    items = []
    for label, cmd in spec:
        if cmd is None:
            items.append({"label": label, "icon": command_icon("Std_ShowSelection"),
                          "run": show_only_selected, "enabled": bool(Gui.Selection.getSelection())})
            continue
        name = resolve(cmd, known)
        if not name:
            continue
        enabled = is_enabled(name)
        items.append({"label": label, "icon": command_icon(name),
                      "run": (lambda n=name: run_command(n)), "enabled": enabled})
    return items


class NxMouse(QtCore.QObject):
    """Event filter for one 3D view's viewport widget."""

    def __init__(self, view, widget):
        super().__init__(widget)
        self.view = view
        self.widget = widget
        self.cfg = config.get()
        self._replaying = False
        self.mb2 = False
        self.extra_rmb = False   # MB3 pressed during an MB2 gesture (pan)
        self.extra_lmb = False   # MB1 pressed during an MB2 gesture (zoom)
        self.moved = False
        self.pivot = None
        self.hold_used = False
        self.rmb_pending = False
        self.last_radial = None
        self.triad = None
        self.mode = None
        self.lmb_rotate = False
        self.swallow_release = None
        self.manager = None
        self.hold_timer = QtCore.QTimer(self)
        self.hold_timer.setSingleShot(True)
        self.hold_timer.timeout.connect(self._mb2_hold)
        self.radial_timer = QtCore.QTimer(self)
        self.radial_timer.setSingleShot(True)
        self.radial_timer.timeout.connect(self._open_radial)
        self.lmb_pending = False
        self.last_pick = None        # what the last MB1 click or hold did, for tests
        self.lmb_timer = QtCore.QTimer(self)
        self.lmb_timer.setSingleShot(True)
        self.lmb_timer.timeout.connect(self._lmb_hold)
        self.armed = None            # where the pointer rested over overlapping objects (QuickPick cursor)
        self.armed_at = 0.0
        self.hover_pos = None
        self.hover_timer = QtCore.QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.timeout.connect(self._hover_rest)

    # ------------------------------------------------------------ helpers
    def coin_xy(self, p):
        dpr = self.widget.devicePixelRatioF() if hasattr(self.widget, "devicePixelRatioF") else 1.0
        return int(p.x() * dpr), int((self.widget.height() - p.y()) * dpr)

    def pick(self, p):
        try:
            return self.view.getObjectInfo(self.coin_xy(p))
        except Exception:
            return None

    def replay(self, kind, button, p):
        ev = mouse_event(kind, p, button, button if kind == QtCore.QEvent.MouseButtonPress else Qt.NoButton,
                         Qt.NoModifier)
        self._replaying = True
        try:
            QtWidgets.QApplication.sendEvent(self.widget, ev)
        finally:
            self._replaying = False

    # ------------------------------------------------------------ camera ops
    def _camera(self):
        cam = self.view.getCameraNode()
        kind = cam.getTypeId().getName()
        return cam, str(kind)

    def rotate(self, dx, dy):
        coin = _coin()
        cam, _ = self._camera()
        k = math.radians(float(self.cfg.get("rotate_degrees_per_pixel", 0.4)))
        orient = cam.orientation.getValue()
        up = orient.multVec(coin.SbVec3f(0, 1, 0))
        right = orient.multVec(coin.SbVec3f(1, 0, 0))
        r = coin.SbRotation(up, -dx * k) * coin.SbRotation(right, -dy * k)
        position = cam.position.getValue()
        if self.pivot is not None:
            pivot = coin.SbVec3f(self.pivot.x, self.pivot.y, self.pivot.z)
        else:
            direction = orient.multVec(coin.SbVec3f(0, 0, -1))
            pivot = position + direction * cam.focalDistance.getValue()
        rel = r.multVec(position - pivot)
        cam.orientation.setValue(orient * r)
        cam.position.setValue(pivot + rel)

    def pan(self, dx, dy):
        coin = _coin()
        cam, kind = self._camera()
        h = max(self.widget.height(), 1)
        if "Orthographic" in kind:
            units = cam.height.getValue() / h
        else:
            units = 2.0 * cam.focalDistance.getValue() * math.tan(cam.heightAngle.getValue() / 2.0) / h
        orient = cam.orientation.getValue()
        up = orient.multVec(coin.SbVec3f(0, 1, 0))
        right = orient.multVec(coin.SbVec3f(1, 0, 0))
        delta = right * (-dx * units) + up * (dy * units)
        cam.position.setValue(cam.position.getValue() + delta)

    def zoom(self, dy):
        coin = _coin()
        cam, kind = self._camera()
        sign = 1.0 if self.cfg.get("zoom_drag_up_zooms_in", True) else -1.0
        factor = math.exp(sign * dy * 0.01)
        if "Orthographic" in kind:
            cam.height.setValue(max(cam.height.getValue() * factor, 1e-6))
        else:
            fd = cam.focalDistance.getValue()
            new_fd = max(fd * factor, 1e-6)
            direction = cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
            cam.position.setValue(cam.position.getValue() + direction * (fd - new_fd))
            cam.focalDistance.setValue(new_fd)

    # ------------------------------------------------------------ MB2 / MB3
    def _mb2_hold(self):
        if not self.mb2 or self.moved:
            return
        info = self.pick(self.start)
        if info and all(k in info for k in ("x", "y", "z")):
            self.pivot = App.Vector(info["x"], info["y"], info["z"])
            self.hold_used = True
            self.widget.setCursor(Qt.CrossCursor)
            status("Rotation point set; drag MB2 to rotate about it")

    def sketch_tool_active(self):
        """FreeCAD's sketcher tools set a custom (bitmap) cursor on the view."""
        try:
            return self.widget.cursor().shape() == Qt.BitmapCursor
        except Exception:
            return False

    def _mb2_click(self):
        if in_sketch_edit():
            # NX: MB2 ends the current curve tool; Esc does that in FreeCAD
            if self.sketch_tool_active():
                gv = self.view.graphicsView()
                for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                    QtWidgets.QApplication.sendEvent(gv, QtGui.QKeyEvent(kind, Qt.Key_Escape, Qt.NoModifier))
                status("Tool ended (MB2)")
            return
        if self.cfg.get("mb2_click_is_ok", True) and accept_task_dialog():
            status("OK (MB2)")

    def _open_radial(self):
        if not self.rmb_pending:
            return
        self.rmb_pending = False
        info = self.pick(self.rmb_pos)
        spec = VIEW_RADIAL
        if info and info.get("Object"):
            doc = info.get("Document") or App.ActiveDocument.Name
            obj = info.get("ParentObject") or info["Object"]
            sub = info.get("SubName") if info.get("ParentObject") else info.get("Component", "")
            if not Gui.Selection.isSelected(App.getDocument(doc).getObject(obj), sub or ""):
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(doc, obj, sub or "")
            spec = OBJECT_RADIAL
        menu = RadialMenu(radial_items(spec), Gui.getMainWindow())
        self.last_radial = menu
        menu.popup_at(self.rmb_global)

    # ------------------------------------------------------------ MB1: QuickPick
    def _defer_lmb(self, ev):
        """Hold an MB1 press back (for QuickPick and select-through)? Not in sketches, dialogs that edit
        an object in the view (draggers), with a modifier or with QuickPick switched off."""
        if self.cfg.get("quickpick_hold_ms", 500) <= 0 or ev.modifiers() != Qt.NoModifier or self.mode:
            return False
        try:
            gdoc = Gui.ActiveDocument
            if gdoc is None or gdoc.getInEdit() is not None:
                return False
        except Exception:
            return False
        return True

    def _hover(self, ev, p):
        """The pointer moved with no button down: rearm the rest timer; leaving the rest spot disarms."""
        if self.armed is not None and (p - self.armed).manhattanLength() > MOVE_THRESHOLD:
            self._disarm()
        if self.armed is None and self._defer_lmb(ev):
            self.hover_pos = p
            self.hover_timer.start(int(self.cfg.get("quickpick_hold_ms", 500)))

    def _hover_rest(self):
        """The pointer rested: over two or more things the cursor shows NX's three dots, and the next MB1
        click there opens QuickPick."""
        from . import selection_filter as sf
        if self.hover_pos is None or self.lmb_pending or self.mb2 or self.mode:
            return
        rows = sf.rows_at(self.view, self.coin_xy(self.hover_pos))
        allowed = sum(1 for r in rows if r["ok"])      # what the filter refuses is no choice
        if allowed < 2:
            return
        self.armed = self.hover_pos
        self.armed_at = time.monotonic()
        self.widget.setCursor(quickpick_cursor())
        status(f"QuickPick: {allowed} selectable objects under the cursor; click to choose one")

    def _disarm(self):
        if self.armed is not None:
            self.armed = None
            self.widget.unsetCursor()

    def _quickpick_at(self, p, gpos):
        from . import quickpick
        menu = quickpick.open_at(self.view, self.coin_xy(p), gpos)
        if menu is not None:
            self.last_pick = ("quickpick", len(menu.rows))
            status("QuickPick: choose one; greyed rows are refused (hover for the reason)")
        return menu

    def _flush_lmb(self):
        """Hand the held-back MB1 press to FreeCAD."""
        if self.lmb_pending:
            self.lmb_timer.stop()
            self.lmb_pending = False
            self.replay(QtCore.QEvent.MouseButtonPress, Qt.LeftButton, self.lmb_pos)

    def _lmb_hold(self):
        if not self.lmb_pending:
            return
        self.lmb_pending = False
        menu = self._quickpick_at(self.lmb_pos, self.lmb_global)
        if menu is not None:
            self.swallow_release = Qt.LeftButton
        else:
            self.last_pick = ("hold", None)
            self.replay(QtCore.QEvent.MouseButtonPress, Qt.LeftButton, self.lmb_pos)

    def _lmb_click(self):
        """A short MB1 click: select through a refused nearest hit, else let FreeCAD select."""
        from . import selection_core, selection_filter as sf
        self.lmb_timer.stop()
        self.lmb_pending = False
        m = sf.manager()
        through = None
        if m.installed and not sf.foreign_dialog():
            rows = sf.rows_at(self.view, self.coin_xy(self.lmb_pos))
            through = selection_core.select_through(rows)
        if through is not None:
            sf.select_row(through)
            self.last_pick = ("through", through["label"])
            status(f"Selected through to {through['label']}; {rows[0]['label']} is refused: {rows[0]['reason']}",
                   5000)
            return True
        self.last_pick = ("click", None)
        self.replay(QtCore.QEvent.MouseButtonPress, Qt.LeftButton, self.lmb_pos)
        return False

    def set_mode(self, mode):
        """None, or 'rotate' (NX F7: MB1 drag rotates until Esc / MB2 / MB3)."""
        self.mode = mode
        self.lmb_rotate = False
        if mode == "rotate":
            self.widget.setCursor(Qt.OpenHandCursor)
        else:
            self.widget.unsetCursor()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QtCore.QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            if self.mode:
                self.manager.set_mode(None)
                return True
            if commands.immediate_hide.active:
                commands.stop_immediate_hide()
                status("Immediate Hide finished")
                return True
            return False
        if obj is not self.widget:   # the graphics view itself: only keys matter
            return False
        if self._replaying or t not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease,
                                        QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonDblClick):
            return False
        try:
            return self._handle(t, ev)
        except Exception as e:  # never break the 3D view because of us
            App.Console.PrintWarning(f"NXStyle navigation: {e}\n")
            return False

    def _rotate_mode(self, t, ev, p):
        """Mouse handling while F7 Rotate is on. Returns True if consumed."""
        button = ev.button()
        if t == QtCore.QEvent.MouseButtonPress:
            if button == Qt.LeftButton:
                self.lmb_rotate = True
                self.last = p
                self.widget.setCursor(Qt.ClosedHandCursor)
                return True
            if button in (Qt.RightButton, Qt.MiddleButton):
                self.manager.set_mode(None)
                self.swallow_release = button
                return True
        if t == QtCore.QEvent.MouseMove and self.lmb_rotate:
            self.rotate(p.x() - self.last.x(), p.y() - self.last.y())
            self.last = p
            return True
        if t == QtCore.QEvent.MouseButtonRelease and button == Qt.LeftButton and self.lmb_rotate:
            self.lmb_rotate = False
            self.widget.setCursor(Qt.OpenHandCursor)
            return True
        return False

    def _handle(self, t, ev):
        own = prefs.uses_own_navigation(self.cfg)
        button = ev.button()
        p = pos(ev)
        if self.swallow_release is not None and t == QtCore.QEvent.MouseButtonRelease \
                and button == self.swallow_release:
            self.swallow_release = None
            return True
        if self.mode == "rotate" and self._rotate_mode(t, ev, p):
            return True
        if t == QtCore.QEvent.MouseButtonDblClick:
            return own and button == Qt.MiddleButton
        if t == QtCore.QEvent.MouseButtonPress:
            self.hover_timer.stop()
            if (button == Qt.LeftButton and self.armed is not None and ev.modifiers() == Qt.NoModifier
                    and (p - self.armed).manhattanLength() <= MOVE_THRESHOLD
                    and time.monotonic() - self.armed_at >= REACT_S):
                self._disarm()
                if self._quickpick_at(p, global_pos(ev)) is not None:
                    self.swallow_release = Qt.LeftButton
                    return True
            self._disarm()
            if self.lmb_pending and button != Qt.LeftButton:
                if button == Qt.MiddleButton and own:
                    # MB1 then MB2: the zoom chord, as with MB2 first; FreeCAD never sees this MB1
                    self.lmb_timer.stop()
                    self.lmb_pending = False
                    self.extra_lmb = True
                else:
                    self._flush_lmb()
            if button == Qt.MiddleButton and own:
                self.mb2 = True
                self.start = self.last = p
                self.moved = False
                self.hold_used = False
                self.pivot = None
                self.t0 = time.monotonic()
                self.hold_timer.start(int(self.cfg.get("mb2_hold_sets_rotation_point_ms", 450)))
                return True
            if button == Qt.RightButton:
                if self.mb2:
                    self.extra_rmb = True
                    return True
                if ev.modifiers() == Qt.NoModifier and self.cfg.get("mb3_hold_radial_menu_ms", 350) > 0:
                    self.rmb_pending = True
                    self.rmb_pos = p
                    self.rmb_global = global_pos(ev)
                    self.radial_timer.start(int(self.cfg.get("mb3_hold_radial_menu_ms", 350)))
                    return True
                return False
            if button == Qt.LeftButton:
                if self.mb2:
                    self.extra_lmb = True
                    return True
                if self.rmb_pending:
                    self._release_pending_rmb(press_only=True)
                if own and self._defer_lmb(ev):
                    self.lmb_pending = True
                    self.lmb_pos = p
                    self.lmb_global = global_pos(ev)
                    self.lmb_timer.start(int(self.cfg.get("quickpick_hold_ms", 500)))
                    return True
                return False
            return False
        if t == QtCore.QEvent.MouseMove and self.lmb_pending:
            if (p - self.lmb_pos).manhattanLength() > MOVE_THRESHOLD:
                self._flush_lmb()          # a drag: FreeCAD gets the press where it happened, then the moves
                return False
            return True
        if t == QtCore.QEvent.MouseMove:
            if self.mb2:
                if not self.moved and (p - self.start).manhattanLength() > MOVE_THRESHOLD:
                    self.moved = True
                    self.hold_timer.stop()
                if self.moved:
                    dx, dy = p.x() - self.last.x(), p.y() - self.last.y()
                    mods = ev.modifiers()   # this event's state, not a possibly stale global one
                    if self.extra_rmb or mods & Qt.ShiftModifier:
                        self.pan(dx, dy)
                    elif self.extra_lmb or mods & Qt.ControlModifier:
                        self.zoom(dy)
                    else:
                        self.rotate(dx, dy)
                    self.last = p
                return True
            if self.rmb_pending:
                if (p - self.rmb_pos).manhattanLength() > 6:
                    self._release_pending_rmb(press_only=True)
                    return False
                return True
            if own and ev.buttons() == Qt.NoButton:
                self._hover(ev, p)
            return False
        if t == QtCore.QEvent.MouseButtonRelease:
            if button == Qt.MiddleButton and self.mb2:
                self.mb2 = False
                self.hold_timer.stop()
                if not self.moved and not self.hold_used and time.monotonic() - self.t0 < 0.6:
                    self._mb2_click()
                self.widget.unsetCursor()
                self.pivot = None
                return True
            if button == Qt.RightButton:
                if self.extra_rmb:
                    self.extra_rmb = False
                    return True
                if self.rmb_pending:
                    self._release_pending_rmb(press_only=False)
                    return True
                return False
            if button == Qt.LeftButton and self.extra_lmb:
                self.extra_lmb = False
                return True
            if button == Qt.LeftButton and self.lmb_pending:
                return self._lmb_click()
        return False

    def _release_pending_rmb(self, press_only):
        """A short MB3 click (or MB3 drag): hand it to FreeCAD unchanged."""
        self.radial_timer.stop()
        self.rmb_pending = False
        self.replay(QtCore.QEvent.MouseButtonPress, Qt.RightButton, self.rmb_pos)
        if not press_only:
            self.replay(QtCore.QEvent.MouseButtonRelease, Qt.RightButton, self.rmb_pos)


class Mb2OkAnywhere(QtCore.QObject):
    """MB2 click = OK in views that are not 3D views (e.g. TechDraw sheets).

    3D views have their own NxMouse filter; this one only watches for a still
    middle click inside the document area while a task dialog is open, and
    never consumes the event, so MB2 drag-to-pan in drawings keeps working.
    """

    def __init__(self, manager):
        super().__init__(manager)
        self.manager = manager
        self.press = None
        self.trace = ""

    def _in_document_area(self, w):
        while w is not None:
            if isinstance(w, QtWidgets.QMdiArea):
                return True
            w = w.parentWidget()
        return False

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
            return False
        try:
            if ev.button() != Qt.MiddleButton or not isinstance(obj, QtWidgets.QWidget):
                return False
            if id(obj) in self.manager.filters or not self._in_document_area(obj):
                return False
            if t == QtCore.QEvent.MouseButtonPress:
                # an ignored press propagates to the parents and passes this filter again
                self.press = (obj, global_pos(ev), time.monotonic())
                self.trace = f"press on {obj.metaObject().className()}"
                return False
            if self.press and self._related(self.press[0], obj):
                moved = (global_pos(ev) - self.press[1]).manhattanLength()
                quick = time.monotonic() - self.press[2] < 0.6
                self.press = None
                if moved <= MOVE_THRESHOLD and quick and config.get().get("mb2_click_is_ok", True):
                    ok = accept_task_dialog()
                    self.trace = f"click on {obj.metaObject().className()}: OK pressed {ok}"
                    if ok:
                        status("OK (MB2)")
                else:
                    self.trace = f"not a click: moved {moved}, quick {quick}"
        except Exception as e:
            self.trace = f"error {e}"
        return False

    @staticmethod
    def _related(a, b):
        try:
            return a is b or a.isAncestorOf(b) or b.isAncestorOf(a)
        except RuntimeError:   # widget already deleted
            return False


class NavigationManager(QtCore.QObject):
    """Attaches NxMouse to every 3D view, including ones opened later."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filters = {}
        self.mode = None
        self.mb2_anywhere = Mb2OkAnywhere(self)
        QtWidgets.QApplication.instance().installEventFilter(self.mb2_anywhere)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.scan)
        self.timer.start(800)

    def scan(self):
        for name in App.listDocuments():
            gdoc = Gui.getDocument(name)
            if gdoc is None:
                continue
            for view in gdoc.mdiViewsOfType("Gui::View3DInventor"):
                try:
                    widget = view.graphicsView().viewport()
                except Exception:
                    continue
                key = id(widget)
                if key in self.filters:
                    continue
                f = NxMouse(view, widget)
                f.manager = self
                if self.mode:
                    f.set_mode(self.mode)
                widget.installEventFilter(f)
                view.graphicsView().installEventFilter(f)   # keyboard focus sits on the view, not the viewport
                widget.destroyed.connect(lambda _=None, k=key: self.filters.pop(k, None))
                self.filters[key] = f
                if config.get().get("view_triad", "nx") == "nx":
                    try:
                        from .triad import ViewTriad
                        f.triad = ViewTriad(view, view.graphicsView())
                    except Exception as e:
                        App.Console.PrintWarning(f"NXStyle: view triad unavailable: {e}\n")
        prefs.apply_navigation_to_open_views()

    def set_mode(self, mode):
        self.mode = mode
        for f in list(self.filters.values()):
            try:
                f.set_mode(mode)
            except RuntimeError:   # view closed
                pass
        status("Rotate: drag MB1 to rotate; Esc, MB2 or MB3 to finish" if mode == "rotate" else "", 4000)

    def filter_for_active_view(self):
        try:
            widget = Gui.ActiveDocument.ActiveView.graphicsView().viewport()
        except Exception:
            return None
        self.scan()
        return self.filters.get(id(widget))
