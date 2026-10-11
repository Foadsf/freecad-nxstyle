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
"""

import math
import time

import FreeCAD as App
import FreeCADGui as Gui

from . import commands, config, prefs
from .qt import QtCore, QtWidgets, Qt, global_pos, mouse_event, pos
from .radial import RadialMenu
from .ribbon import command_icon, is_enabled, known_commands, resolve, trigger

MOVE_THRESHOLD = 3


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
    ("Edit Parameters", "Std_Edit"),
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
        self.hold_timer = QtCore.QTimer(self)
        self.hold_timer.setSingleShot(True)
        self.hold_timer.timeout.connect(self._mb2_hold)
        self.radial_timer = QtCore.QTimer(self)
        self.radial_timer.setSingleShot(True)
        self.radial_timer.timeout.connect(self._open_radial)

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

    def _mb2_click(self):
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

    def eventFilter(self, obj, ev):
        t = ev.type()
        if self._replaying or t not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease,
                                        QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonDblClick):
            return False
        try:
            return self._handle(t, ev)
        except Exception as e:  # never break the 3D view because of us
            App.Console.PrintWarning(f"NXStyle navigation: {e}\n")
            return False

    def _handle(self, t, ev):
        own = prefs.uses_own_navigation(self.cfg)
        button = ev.button()
        p = pos(ev)
        if t == QtCore.QEvent.MouseButtonDblClick:
            return own and button == Qt.MiddleButton
        if t == QtCore.QEvent.MouseButtonPress:
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
                return False
            return False
        if t == QtCore.QEvent.MouseMove:
            if self.mb2:
                if not self.moved and (p - self.start).manhattanLength() > MOVE_THRESHOLD:
                    self.moved = True
                    self.hold_timer.stop()
                if self.moved:
                    dx, dy = p.x() - self.last.x(), p.y() - self.last.y()
                    mods = QtWidgets.QApplication.keyboardModifiers()
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
        return False

    def _release_pending_rmb(self, press_only):
        """A short MB3 click (or MB3 drag): hand it to FreeCAD unchanged."""
        self.radial_timer.stop()
        self.rmb_pending = False
        self.replay(QtCore.QEvent.MouseButtonPress, Qt.RightButton, self.rmb_pos)
        if not press_only:
            self.replay(QtCore.QEvent.MouseButtonRelease, Qt.RightButton, self.rmb_pos)


class NavigationManager(QtCore.QObject):
    """Attaches NxMouse to every 3D view, including ones opened later."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filters = {}
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
                widget.installEventFilter(f)
                widget.destroyed.connect(lambda _=None, k=key: self.filters.pop(k, None))
                self.filters[key] = f
        prefs.apply_navigation_to_open_views()

    def filter_for_active_view(self):
        try:
            widget = Gui.ActiveDocument.ActiveView.graphicsView().viewport()
        except Exception:
            return None
        self.scan()
        return self.filters.get(id(widget))
