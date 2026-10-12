# SPDX-License-Identifier: LGPL-2.1-or-later
"""Replay NX textbook tutorials through the NX-style UI (``launch_nx.py --tutorial OUTDIR``).

Each step is done the way the book tells an NX user to do it: the same key,
the same ribbon button (found by its NX name), MB1 clicks in the graphics
window for sketch curves, MB2 to end a tool or accept a dialog. Where the
FreeCAD flow differs, the step says so. Typed dimension values are applied to
the sketch through FreeCAD's API (the equivalent of typing them into Rapid
Dimension), and every feature is checked by its volume.

Tutorial steps paraphrase four exercises found through the NX notebook:
  A  "The Adjuster"  - Shih, Parametric Modeling with Siemens NX, ch. 2
  B  "First part"    - hollow cylinder plus revolved cone (NX course exercise)
  C  "Rod-Guide"     - Shih ch. 9: datum planes and a hole on a datum
  D  "Pulley"        - Shih ch. 11: revolve, mirror, circular pattern, drawing

Each step start is appended to OUTDIR/progress.log with the process's
committed memory, so a run stopped by the launcher's memory ceiling still
shows where it was.
"""

import json
import math
import os
import time
import traceback

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtCore, QtWidgets, Qt, mouse_event
from .ribbon import CommandButton

OUT = os.environ.get("NXSTYLE_TUTORIAL_OUT", "")
IN = 25.4
SAME, DIFFERS, MISSING, FAIL = "same", "differs", "missing", "FAILED"


def qtest():
    try:
        from PySide6 import QtTest
    except ImportError:
        from PySide2 import QtTest
    return QtTest.QTest


class ModalWatcher(QtCore.QObject):
    """Closes unexpected modal dialogs (and records them) so a replay never hangs."""

    def __init__(self):
        super().__init__()
        self.seen = []
        self.accept = False      # True: answer Yes/OK (e.g. a delete confirmation the step expects)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(150)

    def poll(self):
        w = QtWidgets.QApplication.activeModalWidget()
        if w is None:
            return
        text = w.windowTitle()
        if isinstance(w, QtWidgets.QMessageBox):
            text += ": " + w.text()
            if self.accept:
                for role in (QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.Ok):
                    b = w.button(role)
                    if b is not None:
                        self.seen.append(text + " -> accepted")
                        b.click()
                        return
        self.seen.append(text)
        try:
            w.reject()
        except Exception:
            w.close()


class Replay:
    def __init__(self, shell):
        self.shell = shell
        self.rows = []
        self.info = {}
        self.tutorial = ""
        self.modals = ModalWatcher()
        self.steps = list(self.plan())

    # ------------------------------------------------------------- report
    def step(self, nx, how, outcome, detail=""):
        self.rows.append({"tutorial": self.tutorial, "n": sum(1 for r in self.rows if r["tutorial"] == self.tutorial) + 1,
                          "nx": nx, "replay": how, "outcome": outcome, "detail": str(detail)})

    def shot(self, name):
        try:
            Gui.getMainWindow().grab().save(os.path.join(OUT, name))
        except Exception as e:
            self.info[name] = str(e)

    # ------------------------------------------------------------- UI helpers
    def nav(self):
        return self.shell.navigation.filter_for_active_view()

    def view(self):
        return Gui.ActiveDocument.ActiveView

    def key(self, seq):
        from .smoke import decode
        f = self.nav()
        app = QtWidgets.QApplication.instance()
        mw = Gui.getMainWindow()
        if app.activeWindow() is None and hasattr(app, "setActiveWindow"):
            app.setActiveWindow(mw)   # hidden desktop: no foreground window
        target = f.widget if f is not None else mw
        target.setFocus()
        k, m = decode(seq)
        qtest().keyClick(target, k, m)

    def ribbon_button(self, label):
        r = self.shell.ribbon
        for i in range(r.stack.count()):
            page = r.stack.widget(i)
            for b in page.findChildren(CommandButton):
                if b.nx_label == label:
                    return b, r.tabs.tabText(i), r.locations.get(b.command, "")
        return None, "", ""

    def click_ribbon(self, label):
        b, tab, where = self.ribbon_button(label)
        if b is None:
            return None, ""
        self.shell.ribbon.select(tab)
        QtWidgets.QApplication.processEvents()
        qtest().mouseClick(b, Qt.LeftButton)
        return b, where

    def send(self, kind, p, button, buttons):
        f = self.nav()
        QtWidgets.QApplication.sendEvent(f.widget, mouse_event(kind, p, button, buttons, Qt.NoModifier))

    def mb2_click(self, p=None):
        f = self.nav()
        p = p or QtCore.QPoint(f.widget.width() - 40, f.widget.height() - 40)
        self.send(QtCore.QEvent.MouseButtonPress, p, Qt.MiddleButton, Qt.MiddleButton)
        self.send(QtCore.QEvent.MouseButtonRelease, p, Qt.MiddleButton, Qt.NoButton)

    def mb1_click(self, p):
        self.send(QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton)
        QtWidgets.QApplication.processEvents()
        self.send(QtCore.QEvent.MouseButtonPress, p, Qt.LeftButton, Qt.LeftButton)
        self.send(QtCore.QEvent.MouseButtonRelease, p, Qt.LeftButton, Qt.NoButton)
        QtWidgets.QApplication.processEvents()

    def screen_point(self, sketch, x, y):
        """Sketch-plane coordinates -> widget pixel position."""
        g = sketch.getGlobalPlacement().multVec(App.Vector(x, y, 0))
        sx, sy = self.view().getPointOnViewport(g)
        w = self.nav().widget
        dpr = w.devicePixelRatioF() if hasattr(w, "devicePixelRatioF") else 1.0
        return QtCore.QPoint(int(round(sx / dpr)), int(round(w.height() - sy / dpr)))

    def frame_sketch(self, sketch, cx, cy, height):
        """Zoom the sketch view so the points to click are on screen."""
        from pivy import coin
        cam = self.view().getCameraNode()
        g = sketch.getGlobalPlacement().multVec(App.Vector(cx, cy, 0))
        d = cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
        fd = cam.focalDistance.getValue()
        cam.position.setValue(coin.SbVec3f(g.x, g.y, g.z) - d * fd)
        if hasattr(cam, "height"):
            cam.height.setValue(height)

    def tasks_dock(self):
        return Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Tasks")

    def pick_in_feature_list(self, text):
        """FreeCAD's 'select a plane' task: choose the list row, as a click in the list would."""
        dock = self.tasks_dock()
        for lst in dock.findChildren(QtWidgets.QListWidget):
            for i in range(lst.count()):
                if text.lower() in lst.item(i).text().lower().replace("-", "_"):
                    lst.setCurrentRow(i)
                    lst.item(i).setSelected(True)
                    return lst.item(i).text()
        return None

    def _field(self, cls, name_part):
        """Task-panel widget whose objectName equals name_part, else contains it."""
        widgets = [w for w in self.tasks_dock().findChildren(cls) if w.objectName()]
        exact = [w for w in widgets if w.objectName().lower() == name_part.lower()]
        return (exact or [w for w in widgets if name_part.lower() in w.objectName().lower()] or [None])[0]

    def set_quantity(self, name_part, value):
        """Type a value into a task-panel quantity field (e.g. Length)."""
        w = self._field(QtWidgets.QAbstractSpinBox, name_part)
        if w is None:
            return None
        w.setProperty("rawValue", float(value))
        return w.objectName()

    @staticmethod
    def _matches(part, text):
        """'x axis' matches 'Base X-axis' (1.1) as well as 'Base X axis'."""
        def norm(s):
            return s.lower().replace("-", " ")
        return norm(part) in norm(text)

    def set_combo(self, name_part, option_part):
        """Choose a list entry the way a user does: FreeCAD 1.1 dialogs react to 'activated'."""
        c = self._field(QtWidgets.QComboBox, name_part)
        if c is None:
            return None
        for i in range(c.count()):
            if self._matches(option_part, c.itemText(i)):
                c.setCurrentIndex(i)
                try:
                    c.activated.emit(i)
                except Exception:
                    try:
                        c.activated[int].emit(i)
                    except Exception:
                        pass
                QtWidgets.QApplication.processEvents()
                return c.itemText(i)
        return None

    def body(self):
        return next((o for o in App.ActiveDocument.Objects if o.isDerivedFrom("PartDesign::Body")), None)

    def solid_volume(self):
        b = self.body()
        try:
            return b.Shape.Volume if b is not None and not b.Shape.isNull() else 0.0
        except Exception:
            return 0.0

    def edited_sketch(self):
        return self.shell._edited_sketch()

    @staticmethod
    def rebuild(sketch, lines=(), circles=(), constraints=()):
        """Exact geometry with the dimensions the book types (Rapid Dimension values)."""
        import Part
        import Sketcher
        sketch.deleteAllGeometry()
        for (a, b) in lines:
            sketch.addGeometry(Part.LineSegment(App.Vector(*a, 0), App.Vector(*b, 0)), False)
        for (c, r) in circles:
            sketch.addGeometry(Part.Circle(App.Vector(*c, 0), App.Vector(0, 0, 1), r), False)
        n = len(lines)
        for i in range(n):   # close the profile
            sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % n, 1))
        for c in constraints:
            sketch.addConstraint(Sketcher.Constraint(*c))
        App.ActiveDocument.recompute()

    # ------------------------------------------------------------- plan
    def plan(self):
        A = [self.a_new, self.a_extrude, self.a_plane, self.a_profile_clicks, self.a_mb2_end,
             self.a_dimensions, self.a_finish, self.a_extrude_dialog, self.a_face_pick, self.a_rectangle,
             self.a_finish_cut, self.a_cut_dialog, self.a_fit, self.a_show, self.a_save]
        B = [self.b_new, self.b_extrude, self.b_plane, self.b_circles, self.b_finish, self.b_extrude_dialog,
             self.b_revolve, self.b_plane_yz, self.b_lines, self.b_finish_revolve, self.b_revolve_dialog,
             self.b_fit, self.b_show, self.b_inspect, self.b_snap]
        C = [self.c_new, self.c_extrude, self.c_plane, self.c_sketch, self.c_finish, self.c_extrude_dialog,
             self.c_datum_angle, self.c_datum_angle_ok, self.c_upper_feature, self.c_datum_offset,
             self.c_datum_offset_ok, self.c_hole, self.c_hole_sketch, self.c_finish_hole, self.c_hole_dialog,
             self.c_fit, self.c_show]
        D = [self.d_new, self.d_revolve, self.d_plane, self.d_profile, self.d_finish, self.d_revolve_dialog,
             self.d_mirror, self.d_mirror_dialog, self.d_leader, self.d_leader_sketch, self.d_finish_leader,
             self.d_leader_dialog, self.d_pattern, self.d_pattern_dialog, self.d_fit, self.d_show,
             self.d_drafting, self.d_sheet, self.d_base_view, self.d_base_view_check, self.d_extra_view,
             self.d_delete_view, self.d_section, self.d_section_dialog, self.d_section_check,
             self.d_section_edges, self.d_back]
        wanted = (os.environ.get("NXSTYLE_TUTORIALS") or "A,B,C,D").upper().split(",")
        for key, steps in (("A", A), ("B", B), ("C", C), ("D", D)):
            if key in wanted:
                yield from steps

    # ---------------------------------------------------------- tutorial A
    def a_new(self):
        self.tutorial = "A: The Adjuster (inches)"
        before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200
        self._docs_before = before

    def a_extrude(self):
        new = set(App.listDocuments()) - self._docs_before
        body = self.body()
        self.step("File > New (Ctrl+N), Model template", "Ctrl+N", SAME if new and body else FAIL,
                  f"new document {sorted(new)} with a Body; its datum planes appear when a plane is "
                  "picked (kept hidden otherwise: FreeCAD 1.1.4 hides the part when they stay on)")
        doc = App.ActiveDocument
        unit = getattr(doc, "UnitSystem", None)
        if unit is not None:
            options = doc.getEnumerationsOfProperty("UnitSystem") if hasattr(doc, "getEnumerationsOfProperty") else []
            pick = next((o for o in options if "Imperial" in o and "decimal" in o.lower()), None)
            if pick:
                doc.UnitSystem = pick
            self.step("Units: Inches in the New dialog", "Document > Unit system",
                      DIFFERS, f"set per document in FreeCAD ({doc.UnitSystem}), not in the New dialog")
        else:
            self.step("Units: Inches in the New dialog", "-", DIFFERS,
                      "FreeCAD sets units in Preferences > General > Units, not per new part")
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def a_plane(self):
        dialog = bool(Gui.Control.activeDialog())
        self.step("Extrude (X) with nothing selected", "X key", SAME if dialog else FAIL,
                  "FreeCAD asks for the sketch plane in the Dialog panel; NX asks in the graphics window"
                  if dialog else f"no dialog opened; modals: {self.modals.seen}")
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.wait = 1500
        self._picked = picked

    def a_profile_clicks(self):
        sk = self.edited_sketch()
        self.step("Pick the XY plane, accept with MB2", "plane row in the Dialog panel + MB2 click",
                  SAME if sk is not None else FAIL,
                  f"picked {self._picked}; sketch in edit: {sk.Label if sk else None}")
        if sk is None:
            raise RuntimeError("no sketch in edit; tutorial A cannot continue")
        self._sk = sk
        self.frame_sketch(sk, 1.25 * IN, 1.25 * IN, 4.5 * IN)
        QtWidgets.QApplication.processEvents()
        self.key("Z")
        QtWidgets.QApplication.processEvents()
        self._tool_on = self.nav().sketch_tool_active()
        pts = [(0, 0), (2.5, 0), (2.5, 0.75), (0.75, 0.75), (0.75, 2.5), (0, 2.5), (0, 0)]
        for (x, y) in pts:
            self.mb1_click(self.screen_point(sk, x * IN, y * IN))
        self.wait = 400

    def a_mb2_end(self):
        n = len(self._sk.Geometry)
        self.step("Profile (Z), six MB1 clicks for the L outline", "Z key + MB1 clicks in the graphics window",
                  SAME if self._tool_on and n >= 6 else FAIL, f"tool active {self._tool_on}; {n} curves drawn")
        self.mb2_click(self.screen_point(self._sk, 1.25 * IN, 1.25 * IN))
        self.wait = 400

    def a_dimensions(self):
        ended = not self.nav().sketch_tool_active()
        self.step("MB2 ends Profile", "MB2 click", SAME if ended else FAIL, f"tool ended = {ended}")
        self.key("D")
        QtWidgets.QApplication.processEvents()
        dim_tool = self.nav().sketch_tool_active()
        self.mb2_click(self.screen_point(self._sk, 1.25 * IN, 1.25 * IN))
        self.step("Rapid Dimension (D): 2.5 width, 2.5 height, 0.75 legs", "D key, values applied",
                  DIFFERS if dim_tool else FAIL,
                  "D starts FreeCAD's Dimension tool. FreeCAD does not show NX's dynamic dimensions on click, "
                  "and there is no 'scale the whole sketch to the first dimension?' prompt")
        L = [((0, 0), (2.5 * IN, 0)), ((2.5 * IN, 0), (2.5 * IN, 0.75 * IN)),
             ((2.5 * IN, 0.75 * IN), (0.75 * IN, 0.75 * IN)), ((0.75 * IN, 0.75 * IN), (0.75 * IN, 2.5 * IN)),
             ((0.75 * IN, 2.5 * IN), (0, 2.5 * IN)), ((0, 2.5 * IN), (0, 0))]
        self.rebuild(self._sk, lines=L, constraints=[
            ("Horizontal", 0), ("Vertical", 1), ("Horizontal", 2), ("Vertical", 3), ("Horizontal", 4),
            ("Vertical", 5), ("Coincident", 0, 1, -1, 1), ("DistanceX", 0, 1, 0, 2, 2.5 * IN),
            ("DistanceY", 5, 2, 5, 1, 2.5 * IN), ("DistanceY", 1, 1, 1, 2, 0.75 * IN),
            ("DistanceX", 4, 2, 4, 1, 0.75 * IN)])
        self.info["A sketch dof"] = self._sk.solve()
        self.wait = 300

    def a_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def a_extrude_dialog(self):
        pad = next((o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Pad"), None)
        open_ = bool(Gui.Control.activeDialog()) and pad is not None
        self.step("Finish Sketch (Ctrl+Q) returns to the Extrude dialog", "Ctrl+Q",
                  SAME if open_ else FAIL, f"Extrude dialog open = {open_}; modals {self.modals.seen}")
        field = self.set_quantity("length", 2.5 * IN)
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        time.sleep(0.2)
        App.ActiveDocument.recompute()
        want = (2.5 * 2.5 - 1.75 * 1.75) * 2.5 * IN ** 3
        got = self.solid_volume()
        ok = abs(got - want) < 1e-3 * want and not Gui.Control.activeDialog()
        self.step("Extrude: End = Value 2.5, Boolean None, OK", f"typed into '{field}', MB2 = OK",
                  SAME if ok else FAIL, f"volume {got / IN**3:.4f} in^3, expected {want / IN**3:.4f}")
        self.shot("A1_extrude.png")
        self.wait = 600

    def a_face_pick(self):
        # top face of the vertical leg (normal +Y at y = 2.5 in); the slot is cut down into it.
        # (NotebookLM's step list leaves the slot's place open; this keeps the part one solid.)
        doc = App.ActiveDocument
        body = self.body()
        tip = body.Tip
        face = None
        for i, f in enumerate(tip.Shape.Faces, start=1):
            n = f.normalAt(0, 0)
            if abs(n.y - 1) < 1e-6 and abs(f.CenterOfMass.y - 2.5 * IN) < 1e-6:
                face = f"Face{i}"
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, body.Name, f"{tip.Name}.{face}")
        b, where = self.click_ribbon("Extrude (Subtract)")
        self.step("Extrude, pick the top face as sketch plane, Boolean Subtract",
                  f"select face + ribbon '{where} > Extrude (Subtract)'",
                  DIFFERS if b is not None else MISSING,
                  "FreeCAD has no Boolean option in Extrude: the subtracting extrude is its own button "
                  "(Home > Feature > Extrude (Subtract))")
        self.wait = 1800

    def a_rectangle(self):
        sk = self.edited_sketch()
        if sk is None:
            self.step("Rectangle on the face", "-", FAIL, f"no sketch in edit; modals {self.modals.seen}")
            raise RuntimeError("tutorial A: no sketch on the face")
        self._sk2 = sk
        inv = sk.getGlobalPlacement().inverse()
        # 1.00 in wide (along Z, 0.75 in from the end), across the whole 0.75 in leg
        c1 = inv.multVec(App.Vector(-0.2 * IN, 2.5 * IN, 0.75 * IN))
        c2 = inv.multVec(App.Vector(0.95 * IN, 2.5 * IN, 1.75 * IN))
        self.frame_sketch(sk, (c1.x + c2.x) / 2, (c1.y + c2.y) / 2, 4.5 * IN)
        QtWidgets.QApplication.processEvents()
        self.key("R")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        self.mb1_click(self.screen_point(sk, c1.x, c1.y))
        self.mb1_click(self.screen_point(sk, c2.x, c2.y))
        drawn = len(sk.Geometry)
        self.mb2_click(self.screen_point(sk, (c1.x + c2.x) / 2, (c1.y + c2.y) / 2))
        self.step("Rectangle (R), two MB1 clicks, MB2", "R key + MB1 clicks + MB2",
                  SAME if tool and drawn >= 4 else FAIL, f"tool active {tool}; {drawn} curves")
        x0, x1, y0, y1 = min(c1.x, c2.x), max(c1.x, c2.x), min(c1.y, c2.y), max(c1.y, c2.y)
        L = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
        self.rebuild(sk, lines=L, constraints=[("Horizontal", 0), ("Vertical", 1), ("Horizontal", 2),
                                               ("Vertical", 3)])
        self.step("Rapid Dimension: 0.50 from edge, 1.00 wide, 0.75 deep", "values applied",
                  DIFFERS, "as in step 6: same tool, no NX dynamic dimensions")
        self.wait = 300

    def a_finish_cut(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def a_cut_dialog(self):
        pocket = next((o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Pocket"), None)
        open_ = bool(Gui.Control.activeDialog()) and pocket is not None
        self.step("Finish Sketch returns to the (subtract) Extrude dialog", "Ctrl+Q",
                  SAME if open_ else FAIL, f"dialog open = {open_}")
        field = self.set_quantity("length", 0.75 * IN)
        self.step("Reverse Direction into the solid", "-", DIFFERS,
                  "not needed: FreeCAD's subtracting extrude cuts into the solid by default")
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        App.ActiveDocument.recompute()
        base = (2.5 * 2.5 - 1.75 * 1.75) * 2.5
        want = (base - 0.75 * 1.0 * 0.75) * IN ** 3
        got = self.solid_volume()
        solids = len(self.body().Shape.Solids)
        ok = abs(got - want) < 1e-3 * want and solids == 1 and not Gui.Control.activeDialog()
        self.step("Slot depth 0.75, OK", f"'{field}' = 0.75 in, MB2 = OK", SAME if ok else FAIL,
                  f"volume {got / IN**3:.4f} in^3, expected {want / IN**3:.4f}; {solids} solid(s)")
        self.wait = 400

    def fit(self):
        Gui.Selection.clearSelection()
        Gui.runCommand("Std_ViewTrimetric")
        Gui.SendMsgToActiveView("ViewFit")
        self.wait = 2000   # animated view changes must finish before the next action

    def show(self, name):
        rows = []
        for o in App.ActiveDocument.Objects:
            vo = getattr(o, "ViewObject", None)
            if vo is None:
                continue
            row = {"name": o.Name, "type": o.TypeId, "visible": vo.Visibility}
            for prop in ("DisplayMode", "Transparency", "ShapeColor", "ShapeAppearance", "LineColor"):
                if hasattr(vo, prop):
                    try:
                        val = getattr(vo, prop)
                        row[prop] = str(val[0].DiffuseColor) if prop == "ShapeAppearance" else str(val)
                    except Exception as e:
                        row[prop] = f"? {e}"
            rows.append(row)
        self.info[f"display {name}"] = rows
        self.shot(name + ".png")
        try:
            self.view().saveImage(os.path.join(OUT, name + "_3d.png"), 1200, 800, "Current")
        except Exception as e:
            self.info[name] = str(e)
        self.wait = 300

    def a_fit(self):
        self.fit()

    def a_show(self):
        self.show("A_adjuster")

    def b_fit(self):
        self.fit()

    def b_show(self):
        self.show("B_first_part")

    @staticmethod
    def drawn_fraction(png):
        """Share of sampled pixels that are not the light background gradient."""
        from .qt import QtGui
        img = QtGui.QImage(png)
        if img.isNull():
            return 0.0
        hits = total = 0
        for y in range(0, img.height(), 6):
            for x in range(0, img.width(), 6):
                c = img.pixelColor(x, y)
                total += 1
                if min(c.red(), c.green(), c.blue()) < 165 or max(c.red(), c.green(), c.blue()) - \
                        min(c.red(), c.green(), c.blue()) > 60:
                    hits += 1
        return hits / max(total, 1)

    def check_drawn(self, label, name):
        png = os.path.join(OUT, name)
        self.view().saveImage(png, 900, 600, "Current")
        frac = self.drawn_fraction(png)
        self.step(label, "render of the graphics window", SAME if frac > 0.02 else FAIL,
                  f"{frac:.1%} of the view shows the part")

    def a_save(self):
        self.check_drawn("The finished part is shown in the graphics window", "A_live_check.png")
        path = os.path.join(OUT, "Adjuster.FCStd")
        doc = App.ActiveDocument
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        App.openDocument(path)
        QtWidgets.QApplication.processEvents()
        Gui.SendMsgToActiveView("ViewFit")
        QtWidgets.QApplication.processEvents()
        self.step("Save (Ctrl+S)", "Ctrl+S is bound to Save (tested by the self-test); file saved",
                  SAME, "saved as Adjuster.FCStd (FreeCAD format, not .prt)")
        self.check_drawn("Reopened part is shown", "A_reopened_check.png")
        self.wait = 300

    # ---------------------------------------------------------- tutorial B
    def b_new(self):
        self.tutorial = "B: First part, cylinder and cone (mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def b_extrude(self):
        new = set(App.listDocuments()) - self._docs_before
        self.step("File > New (Ctrl+N), Model template, mm", "Ctrl+N",
                  SAME if new and self.body() else FAIL, f"new document {sorted(new)}")
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def b_plane(self):
        dialog = bool(Gui.Control.activeDialog())
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.step("Extrude (X), pick the XC-YC plane", "X key, plane row + MB2", SAME if dialog else FAIL,
                  f"picked {picked}")
        self.wait = 1500

    def b_circles(self):
        sk = self.edited_sketch()
        if sk is None:
            self.step("Circle tool", "-", FAIL, "no sketch in edit")
            raise RuntimeError("tutorial B: no sketch")
        self._sk = sk
        self.frame_sketch(sk, 0, 0, 80)
        QtWidgets.QApplication.processEvents()
        self.key("O")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        for r in (25, 15):
            self.mb1_click(self.screen_point(sk, 0, 0))
            self.mb1_click(self.screen_point(sk, r, 0))
        n = len(sk.Geometry)
        self.mb2_click(self.screen_point(sk, 30, 30))
        ended = not self.nav().sketch_tool_active()
        self.step("Circle (O): two circles at the origin, MB2", "O key + MB1 clicks + MB2",
                  SAME if tool and n >= 2 and ended else FAIL, f"tool {tool}; {n} circles; ended {ended}")
        self.rebuild(sk, circles=[((0, 0), 25), ((0, 0), 15)],
                     constraints=[("Coincident", 0, 3, -1, 1), ("Coincident", 1, 3, -1, 1),
                                  ("Diameter", 0, 50), ("Diameter", 1, 30)])
        self.step("Rapid Dimension: diameters 50 and 30", "values applied", DIFFERS,
                  "same tool; values typed in FreeCAD's dimension field")
        self.wait = 300

    def b_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def b_extrude_dialog(self):
        open_ = bool(Gui.Control.activeDialog())
        field = self.set_quantity("length", 50)
        self.mb2_click()
        App.ActiveDocument.recompute()
        want = math.pi * (25 ** 2 - 15 ** 2) * 50
        got = self.solid_volume()
        ok = open_ and abs(got - want) < 1e-3 * want
        self.step("Finish Sketch, Extrude 0 to 50 mm, OK", f"Ctrl+Q, '{field}' = 50, MB2 = OK",
                  SAME if ok else FAIL, f"volume {got:.1f} mm^3, expected {want:.1f}")
        self.wait = 600

    def b_revolve(self):
        Gui.Selection.clearSelection()
        b, where = self.click_ribbon("Revolve")
        self.step("Revolve (ribbon)", f"ribbon '{where} > Revolve'", SAME if b is not None else MISSING,
                  "nothing selected: sketch first, as with Extrude")
        self.wait = 1500

    def b_plane_yz(self):
        picked = self.pick_in_feature_list("YZ")
        self.mb2_click()
        self.step("Pick the YC-ZC plane", "plane row + MB2", SAME if picked else FAIL, f"picked {picked}")
        self.wait = 1500

    def b_lines(self):
        sk = self.edited_sketch()
        if sk is None:
            self.step("Line tool", "-", FAIL, "no sketch in edit")
            raise RuntimeError("tutorial B: no revolve sketch")
        self._sk2 = sk
        self.frame_sketch(sk, 12, 75, 90)
        QtWidgets.QApplication.processEvents()
        self.key("L")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        for (a, b) in (((0, 50), (25, 50)), ((25, 50), (0, 100)), ((0, 100), (0, 50))):
            self.mb1_click(self.screen_point(sk, *a))
            self.mb1_click(self.screen_point(sk, *b))
        n = len(sk.Geometry)
        self.mb2_click(self.screen_point(sk, 40, 90))
        self.step("Line (L): right triangle on the axis, MB2", "L key + MB1 clicks + MB2",
                  SAME if tool and n >= 3 else FAIL, f"tool {tool}; {n} lines")
        self.rebuild(sk, lines=[((0, 50), (25, 50)), ((25, 50), (0, 100)), ((0, 100), (0, 50))],
                     constraints=[("Horizontal", 0), ("Vertical", 2), ("PointOnObject", 0, 1, -2),
                                  ("DistanceX", 0, 1, 0, 2, 25), ("DistanceY", 2, 2, 2, 1, 50),
                                  ("DistanceY", -1, 1, 0, 1, 50)])
        self.step("Rapid Dimension: height 50, radius 25", "values applied", DIFFERS, "same tool")
        self.wait = 300

    def b_finish_revolve(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def b_revolve_dialog(self):
        rev = next((o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Revolution"), None)
        open_ = bool(Gui.Control.activeDialog()) and rev is not None
        axis = rev.ReferenceAxis[1] if rev is not None and rev.ReferenceAxis else None
        self.step("Finish Sketch returns to Revolve; axis = Z, 0..360 deg", "Ctrl+Q",
                  SAME if open_ else FAIL, f"dialog open {open_}; default axis {axis} (sketch V axis = Z)")
        self.mb2_click()
        App.ActiveDocument.recompute()
        want = math.pi * (25 ** 2 - 15 ** 2) * 50 + math.pi * 25 ** 2 * 50 / 3
        got = self.solid_volume()
        ok = abs(got - want) < 1e-3 * want and not Gui.Control.activeDialog()
        self.step("Boolean Unite, OK", "MB2 = OK", SAME if ok else FAIL,
                  f"volume {got:.1f} mm^3, expected {want:.1f}; features in one Body unite automatically")
        self.wait = 400

    def b_inspect(self):
        f = self.nav()
        cam = self.view().getCameraNode()
        o0 = cam.orientation.getValue().getValue()
        p = QtCore.QPoint(f.widget.width() // 2, f.widget.height() // 2)
        self.send(QtCore.QEvent.MouseButtonPress, p, Qt.MiddleButton, Qt.MiddleButton)
        for i in range(1, 11):
            self.send(QtCore.QEvent.MouseMove, QtCore.QPoint(p.x() + 7 * i, p.y() + 3 * i), Qt.NoButton,
                      Qt.MiddleButton)
        self.send(QtCore.QEvent.MouseButtonRelease, QtCore.QPoint(p.x() + 70, p.y() + 30), Qt.MiddleButton,
                  Qt.NoButton)
        o1 = cam.orientation.getValue().getValue()
        self.step("Hold MB2 and drag to rotate", "MB2 drag", SAME if o1 != o0 else FAIL, "")
        self.key("F8")
        self.wait = 900

    def b_snap(self):
        d = self.view().getViewDirection()
        ok = max(abs(d.x), abs(d.y), abs(d.z)) > 0.999
        self.step("F8 snaps to the nearest standard view", "F8 key", SAME if ok else FAIL, f"view {d}")
        self.check_drawn("The finished part is shown in the graphics window", "B_live_check.png")
        App.ActiveDocument.saveAs(os.path.join(OUT, "FirstPart.FCStd"))
        self.step("Save (Ctrl+S)", "file saved", SAME, "FirstPart.FCStd")
        self.shot("B2_snapped.png")
        self.wait = 200

    # ------------------------------------------------------- more helpers
    def set_spin(self, name_part, value):
        """Type a value into an integer or quantity field in the task panel.

        Integer fields get the text typed and interpreted, as a user's typing is:
        FreeCAD's Gui::UIntSpinBox keeps unsigned values offset by 2^31 inside a
        QSpinBox, so QSpinBox.setValue(5) from Python stores 5 + 2^31 (clamped
        to INT_MAX). On a pattern's Occurrences that asked for ~19 GB."""
        for w in self.tasks_dock().findChildren(QtWidgets.QAbstractSpinBox):
            if name_part.lower() in w.objectName().lower():
                if isinstance(w, QtWidgets.QSpinBox):
                    w.lineEdit().setText(str(int(value)))
                    w.interpretText()
                else:
                    w.setProperty("rawValue", float(value))
                return w.objectName()   # no processEvents: callers check the value before a recompute
        return None

    def choose(self, option_part, name_part=""):
        """Pick a list entry in whichever task-panel combo offers it (names differ between versions)."""
        combos = [c for c in self.tasks_dock().findChildren(QtWidgets.QComboBox) if c.isVisible()]
        combos.sort(key=lambda c: name_part.lower() not in c.objectName().lower())
        for c in combos:
            if any(self._matches(option_part, c.itemText(i)) for i in range(c.count())):
                return self.set_combo(c.objectName(), option_part) if c.objectName() else None
        self.progress(f"choose '{option_part}': not offered; combos " + str(
            {c.objectName(): [c.itemText(i) for i in range(c.count())]
             for c in self.tasks_dock().findChildren(QtWidgets.QComboBox)}))
        return None

    def task_widgets(self):
        """objectName: class of everything in the Dialog panel (for the report)."""
        return sorted({f"{w.objectName()}:{type(w).__name__}" for w in self.tasks_dock().findChildren(QtWidgets.QWidget)
                       if w.objectName() and not w.objectName().startswith("qt_")})

    def click_dropdown(self, drop_label, item_label):
        from .ribbon import DropdownButton
        r = self.shell.ribbon
        for i in range(r.stack.count()):
            for b in r.stack.widget(i).findChildren(DropdownButton):
                if b.text() == drop_label:
                    for a in b.menu().actions():
                        if a.text() == item_label:
                            r.tabs.setCurrentIndex(i)
                            a.trigger()
                            return r.tabs.tabText(i)
        return None

    def newest(self, type_id):
        objs = [o for o in App.ActiveDocument.Objects if o.TypeId == type_id]
        return objs[-1] if objs else None

    def face_of(self, obj, test):
        for i, f in enumerate(obj.Shape.Faces, start=1):
            try:
                if test(f):
                    return f"Face{i}"
            except Exception:
                continue
        return None

    def select_sub(self, obj, sub):
        doc = App.ActiveDocument
        body = self.body()
        Gui.Selection.clearSelection()
        if obj.isDerivedFrom("PartDesign::Feature") or obj.isDerivedFrom("Part::Datum"):
            Gui.Selection.addSelection(doc.Name, body.Name, f"{obj.Name}.{sub}" if sub else f"{obj.Name}.")
        else:
            Gui.Selection.addSelection(doc.Name, obj.Name, sub or "")

    def draw_clicks(self, key, pts):
        """Start a sketch tool by key, click the given sketch points, end it with MB2."""
        sk = self.edited_sketch()
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        self.frame_sketch(sk, (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, span * 1.8)
        QtWidgets.QApplication.processEvents()
        self.key(key)
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        for (x, y) in pts:
            self.mb1_click(self.screen_point(sk, x, y))
        n = len(sk.Geometry)
        self.mb2_click(self.screen_point(sk, min(xs) - span * 0.6, max(ys) + span * 0.6))
        ended = not self.nav().sketch_tool_active()
        return sk, tool, n, ended

    @staticmethod
    def add_geometry(sketch, geos):
        sketch.deleteAllGeometry()
        for g in geos:
            sketch.addGeometry(g, False)
        App.ActiveDocument.recompute()

    def check_volume(self, label, how, want, extra=""):
        App.ActiveDocument.recompute()
        got = self.solid_volume()
        solids = len(self.body().Shape.Solids) if self.body() is not None else 0
        ok = abs(got - want) < 1e-3 * max(want, 1e-9) and solids == 1 and not Gui.Control.activeDialog()
        self.step(label, how, SAME if ok else FAIL,
                  f"volume {got / IN**3:.4f} in^3, expected {want / IN**3:.4f}; {solids} solid(s){extra}")
        return ok

    # ---------------------------------------------------------- tutorial C
    # Rod-Guide (Shih ch. 9). The book gives the block's size only in figures;
    # 3.00 x 2.00 in is NotebookLM's reading. The upper angled feature's profile
    # is figure-only and is not replayed.
    def c_new(self):
        self.tutorial = "C: Rod-Guide (inches)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def c_extrude(self):
        doc = App.ActiveDocument
        self.step("File > New (Ctrl+N), Model template, inches", "Ctrl+N",
                  SAME if set(App.listDocuments()) - self._docs_before and self.body() else FAIL, "")
        if hasattr(doc, "UnitSystem"):
            opts = doc.getEnumerationsOfProperty("UnitSystem")
            pick = next((o for o in opts if "Imperial" in o and "decimal" in o.lower()), None)
            if pick:
                doc.UnitSystem = pick
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def c_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.step("Extrude (X), pick the XY plane", "X key, plane row + MB2", SAME if picked else FAIL,
                  f"picked {picked}")
        self.wait = 1500

    def c_sketch(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch in edit")
        _, tool, n, ended = self.draw_clicks("R", [(-1.5 * IN, -1.0 * IN), (1.5 * IN, 1.0 * IN)])
        self.step("Rectangle (R) by 2 points around the origin", "R key + 2 MB1 clicks + MB2",
                  SAME if tool and n >= 4 and ended else FAIL, f"tool {tool}; {n} curves; ended {ended}")
        self.key("F")
        QtWidgets.QApplication.processEvents()
        fillet_tool = self.nav().sketch_tool_active()
        self.mb2_click(self.screen_point(sk, 2.5 * IN, 2.0 * IN))
        self.step("Sketch Fillet (F), R0.25 on the four corners", "F key; corners applied as values",
                  DIFFERS if fillet_tool else FAIL,
                  "F starts FreeCAD's sketch fillet; the radius is typed after picking, not before as in NX")
        self.key("O")
        QtWidgets.QApplication.processEvents()
        circle_tool = self.nav().sketch_tool_active()
        self.mb2_click(self.screen_point(sk, 2.5 * IN, 2.0 * IN))
        r, w, h = 0.25 * IN, 1.5 * IN, 1.0 * IN
        V = App.Vector
        Z = V(0, 0, 1)
        geos = [Part.LineSegment(V(-w + r, -h, 0), V(w - r, -h, 0)),
                Part.LineSegment(V(w, -h + r, 0), V(w, h - r, 0)),
                Part.LineSegment(V(w - r, h, 0), V(-w + r, h, 0)),
                Part.LineSegment(V(-w, h - r, 0), V(-w, -h + r, 0))]
        for (cx, cy, a0) in ((w - r, -h + r, -90), (w - r, h - r, 0), (-w + r, h - r, 90), (-w + r, -h + r, 180)):
            geos.append(Part.ArcOfCircle(Part.Circle(V(cx, cy, 0), Z, r), math.radians(a0), math.radians(a0 + 90)))
        for (cx, cy) in ((w - r, -h + r), (w - r, h - r), (-w + r, h - r), (-w + r, -h + r)):
            geos.append(Part.Circle(V(cx, cy, 0), Z, 0.125 * IN))
        self.add_geometry(sk, geos)
        import Sketcher
        for i in (9, 10, 11):
            sk.addConstraint(Sketcher.Constraint("Equal", 8, i))
        App.ActiveDocument.recompute()
        self.step("Circle (O): four Ø0.25 circles on the arc centres, Equal Radius", "O key; values applied",
                  SAME if circle_tool else FAIL, "Equal constraint exists in both")
        self.wait = 300

    def c_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def c_extrude_dialog(self):
        field = self.set_quantity("length", 0.75 * IN)
        self.mb2_click()
        r = 0.25
        area = 3.0 * 2.0 - 4 * (r * r - math.pi * r * r / 4) - 4 * math.pi * 0.125 ** 2
        self._c_base = area * 0.75 * IN ** 3
        self.check_volume("Finish Sketch, Extrude 0.75, OK", f"Ctrl+Q, '{field}' = 0.75 in, MB2 = OK", self._c_base)
        self.wait = 600

    def c_datum_angle(self):
        pad = self.body().Tip
        face = self.face_of(pad, lambda f: abs(f.normalAt(0, 0).y + 1) < 1e-6)
        self.select_sub(pad, face)
        where = self.click_dropdown("Datum", "Datum Plane")
        self._before_planes = len([o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Plane"])
        self.step("Datum Plane, At Angle: front face", f"select face + ribbon '{where} > Datum > Datum Plane'",
                  SAME if where and Gui.Control.activeDialog() else FAIL,
                  "the datum is attached to the face; FreeCAD's attachment dialog opens")
        self.wait = 1200

    def c_datum_angle_ok(self):
        plane = self.newest("PartDesign::Plane")
        used = None
        for axis in ("yaw", "pitch", "roll"):
            name = self.set_quantity(f"attachmentoffset{axis}", -30)
            QtWidgets.QApplication.processEvents()
            App.ActiveDocument.recompute()
            n = plane.Placement.Rotation.multVec(App.Vector(0, 0, 1))
            if name and abs(n.z) < 1e-6 and abs(abs(n.dot(App.Vector(0, -1, 0))) - math.cos(math.radians(30))) < 1e-4:
                used = name
                break
            if name:
                self.set_quantity(f"attachmentoffset{axis}", 0)
        self.mb2_click()
        App.ActiveDocument.recompute()
        n = plane.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        ang = math.degrees(math.acos(min(1.0, abs(n.dot(App.Vector(0, -1, 0))))))
        ok = used and abs(ang - 30) < 0.01 and not Gui.Control.activeDialog()
        self.step("Angle -30° about the vertical axis, OK", f"'{used}' = -30°, MB2 = OK",
                  DIFFERS if ok else FAIL,
                  f"plane at {ang:.2f}° to the face. NX picks the Z axis as hinge; FreeCAD rotates in the "
                  "attachment offset about the face's own axes")
        self.wait = 500

    def c_upper_feature(self):
        self.step("Extrude the angled upper block on the datum plane (Unite, Symmetric 1.0)", "-", "skipped",
                  "the profile's dimensions are only in the book's figures")

    def c_datum_offset(self):
        pad = next(o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Pad")
        face = self.face_of(pad, lambda f: abs(f.normalAt(0, 0).z - 1) < 1e-6 and abs(f.CenterOfMass.z - 0.75 * IN) < 1e-6)
        self.select_sub(pad, face)
        where = self.click_dropdown("Datum", "Datum Plane")
        self.step("Datum Plane, At Distance: top face", f"select face + ribbon '{where} > Datum > Datum Plane'",
                  SAME if where and Gui.Control.activeDialog() else FAIL, "")
        self.wait = 1200

    def c_datum_offset_ok(self):
        plane = self.newest("PartDesign::Plane")
        field = self.set_quantity("attachmentoffsetz", 0.75 * IN)
        self.mb2_click()
        App.ActiveDocument.recompute()
        z = plane.Placement.Base.z / IN
        self._c_plane = plane
        self.step("Distance 0.75, OK", f"'{field}' = 0.75 in, MB2 = OK",
                  SAME if abs(z - 1.5) < 1e-6 and not Gui.Control.activeDialog() else FAIL,
                  f"datum plane at z = {z:.4f} in (top face 0.75 + 0.75)")
        self.wait = 500

    def c_hole(self):
        self.select_sub(self._c_plane, "")
        b, where = self.click_ribbon("Hole")
        sk = None
        QtWidgets.QApplication.processEvents()
        self.step("Hole, placed on the offset datum plane", f"select plane + ribbon '{where} > Hole'",
                  DIFFERS if b is not None else MISSING,
                  "FreeCAD's Hole drills at circle centres in a sketch, so Hole starts a sketch on the plane "
                  "(NX picks the point directly)")
        self._sk = sk
        self.wait = 1500

    def c_hole_sketch(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError(f"no hole sketch in edit; modals {self.modals.seen}")
        _, tool, n, ended = self.draw_clicks("O", [(0, 0), (0.125 * IN, 0)])
        self.add_geometry(sk, [Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 0.125 * IN)])
        self.step("Place the hole centre at the WCS origin", "O key + MB1 at the origin + MB2",
                  SAME if tool and n >= 1 and ended else FAIL, f"tool {tool}; {n} curves; ended {ended}")
        self.wait = 300

    def c_finish_hole(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def c_hole_dialog(self):
        hole = self.newest("PartDesign::Hole")
        open_ = bool(Gui.Control.activeDialog()) and hole is not None
        dia = self.set_quantity("diameter", 0.25 * IN)
        depth = self.set_combo("depthtype", "through")
        self.info["C hole dialog widgets"] = self.task_widgets()
        self.mb2_click()
        want = self._c_base - math.pi * 0.125 ** 2 * 0.75 * IN ** 3
        ok = self.check_volume("Hole: Simple, Ø0.25, Through Body, OK",
                               f"dialog open {open_}; '{dia}' = 0.25 in, '{depth}', MB2 = OK", want)
        if not ok and hole is not None:
            self.info["C hole state"] = {"Diameter": str(hole.Diameter), "DepthType": hole.DepthType,
                                         "Reversed": getattr(hole, "Reversed", None)}
        self.wait = 500

    def c_fit(self):
        self.fit()

    def c_show(self):
        self.show("C_rod_guide")
        self.check_drawn("The finished part is shown in the graphics window", "C_live_check.png")
        App.ActiveDocument.saveAs(os.path.join(OUT, "Rod-Guide.FCStd"))

    # ---------------------------------------------------------- tutorial D
    # Pulley (Shih ch. 11). The book's profile dimensions are in figures; the
    # values below are NotebookLM's (Ø4.00, 1.00 wide, hub Ø1.50, bore Ø0.75,
    # web 0.25, 5 x Ø0.50 holes on a 2.50 pitch circle), halved for the half
    # model that Mirror Feature completes.
    HALF = [(0, 0.375), (0.5, 0.375), (0.5, 0.75), (0.125, 0.75), (0.125, 1.75), (0.5, 1.75), (0.5, 2.0), (0, 2.0)]

    def d_volume_half(self):
        rects = [(0.5, 0.375, 0.75), (0.125, 0.75, 1.75), (0.5, 1.75, 2.0)]   # (width, r0, r1)
        return sum(w * math.pi * (r1 ** 2 - r0 ** 2) for (w, r0, r1) in rects) * IN ** 3

    def d_new(self):
        self.tutorial = "D: Pulley with drawing (inches)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def d_revolve(self):
        self.step("File > New (Ctrl+N), Model template", "Ctrl+N",
                  SAME if set(App.listDocuments()) - self._docs_before and self.body() else FAIL, "")
        doc = App.ActiveDocument
        if hasattr(doc, "UnitSystem"):
            pick = next((o for o in doc.getEnumerationsOfProperty("UnitSystem") if "Imperial" in o
                         and "decimal" in o.lower()), None)
            if pick:
                doc.UnitSystem = pick
        Gui.Selection.clearSelection()
        b, where = self.click_ribbon("Revolve")
        self.step("Revolve, nothing selected", f"ribbon '{where} > Revolve'", SAME if b is not None else MISSING, "")
        self.wait = 1500

    def d_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.step("Pick the XY plane of the datum CSYS", "plane row + MB2", SAME if picked else FAIL, f"{picked}")
        self.wait = 1500

    def d_profile(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch in edit")
        pts = [(x * IN, y * IN) for (x, y) in self.HALF] + [(self.HALF[0][0] * IN, self.HALF[0][1] * IN)]
        _, tool, n, ended = self.draw_clicks("Z", pts)
        self.step("Profile (Z): closed half cross-section, MB2", "Z key + 9 MB1 clicks + MB2",
                  SAME if tool and n >= 8 and ended else FAIL, f"tool {tool}; {n} curves; ended {ended}")
        P = [App.Vector(x * IN, y * IN, 0) for (x, y) in self.HALF]
        self.add_geometry(sk, [Part.LineSegment(P[i], P[(i + 1) % len(P)]) for i in range(len(P))])
        self.step("Rapid Dimension: profile sizes", "values applied", DIFFERS, "same tool; no dynamic dimensions")
        self.wait = 300

    def d_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def d_revolve_dialog(self):
        rev = self.newest("PartDesign::Revolution")
        axis = self.set_combo("axis", "x axis") or self.set_combo("axis", "horizontal")
        self.mb2_click()
        self.check_volume("Specify Vector = X axis through the origin, 0..360°, OK",
                          f"axis '{axis}', MB2 = OK", self.d_volume_half(),
                          "; NX picks the axis in the graphics window, FreeCAD lists it in the dialog")
        self._d_rev = rev
        self.wait = 600

    def d_mirror(self):
        self.select_sub(self._d_rev, "")
        b, where = self.click_ribbon("Mirror Feature")
        self.step("Mirror Feature: select the revolved feature, MB2 to proceed",
                  f"feature selected + ribbon '{where} > Mirror Feature'",
                  DIFFERS if b is not None and Gui.Control.activeDialog() else FAIL,
                  "selecting first and then starting Mirror Feature replaces NX's 'select, then MB2'")
        self.wait = 1500

    def d_mirror_dialog(self):
        plane = self.set_combo("plane", "yz")
        self.info["D mirror dialog widgets"] = self.task_widgets()
        self.mb2_click()
        self.check_volume("Plane = the back face (on the YZ plane), OK; Unite",
                          f"plane '{plane}', MB2 = OK", 2 * self.d_volume_half(),
                          "; inside a Body the mirror unites by itself, so NX's separate Unite step is not needed")
        self.wait = 600

    def d_leader(self):
        tip = self.body().Tip
        face = self.face_of(tip, lambda f: abs(f.normalAt(0, 0).x - 1) < 1e-6
                            and abs(f.CenterOfMass.x - 0.125 * IN) < 1e-6)
        self.select_sub(tip, face)
        b, where = self.click_ribbon("Extrude (Subtract)")
        self.step("Pattern leader: Extrude on the front face of the web, Subtract",
                  f"select face + ribbon '{where} > Extrude (Subtract)'", DIFFERS if b is not None else MISSING,
                  "subtracting extrude is its own button in FreeCAD")
        self.wait = 1500

    def d_leader_sketch(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no leader sketch in edit")
        inv = sk.getGlobalPlacement().inverse()
        c = inv.multVec(App.Vector(0.125 * IN, 0, 1.25 * IN))
        e = inv.multVec(App.Vector(0.125 * IN, 0, 1.5 * IN))
        _, tool, n, ended = self.draw_clicks("O", [(c.x, c.y), (e.x, e.y)])
        self.add_geometry(sk, [Part.Circle(App.Vector(c.x, c.y, 0), App.Vector(0, 0, 1), 0.25 * IN)])
        self.step("Circle Ø0.50 on the 2.50 pitch circle", "O key + MB1 clicks + MB2; values applied",
                  SAME if tool and n >= 1 and ended else FAIL, f"tool {tool}; {n} curves")
        self.wait = 300

    def d_finish_leader(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def d_leader_dialog(self):
        mode = self.choose("through all", "mode")
        self.info["D leader dialog widgets"] = self.task_widgets()
        self.mb2_click()
        self._d_hole = math.pi * 0.25 ** 2 * 0.25 * IN ** 3
        self.check_volume("Reverse Direction, End = Through All, OK", f"'{mode}', MB2 = OK",
                          2 * self.d_volume_half() - self._d_hole, "; no Reverse needed in FreeCAD")
        self.wait = 600

    def d_pattern(self):
        pocket = self.newest("PartDesign::Pocket")
        self.select_sub(pocket, "")
        b, where = self.click_ribbon("Circular Pattern")
        self.step("Pattern Feature, Layout = Circular", f"leader selected + ribbon '{where} > Circular Pattern'",
                  DIFFERS if b is not None and Gui.Control.activeDialog() else FAIL,
                  "NX has one Pattern Feature with a Layout list; FreeCAD has separate linear and circular buttons")
        self.wait = 1500

    def pattern_state(self):
        pat = self.newest("PartDesign::PolarPattern")
        if pat is None:
            return "no PolarPattern"
        return {p: str(getattr(pat, p)) for p in pat.PropertiesList
                if p in ("Axis", "Angle", "Occurrences", "Offset", "Mode", "Originals", "Reversed")}

    def d_pattern_dialog(self):
        axis = self.choose("x axis", "axis") or self.choose("x axis", "direction")
        count = self.set_spin("occurrences", 5)
        state = self.pattern_state()
        self.progress(f"d_pattern_dialog: axis '{axis}', count '{count}' -> {state}")
        self.info["D pattern dialog widgets"] = self.task_widgets()
        pat = self.newest("PartDesign::PolarPattern")
        if pat is None or pat.Occurrences != 5:
            # never confirm (or let recompute) a pattern with a count nobody asked for
            if pat is not None:
                pat.Occurrences = 2
            Gui.Control.closeDialog()
            raise RuntimeError(f"pattern count not set: {state}")
        used = f"axis '{axis}'" if axis else f"default axis {pat.Axis[1]} of {pat.Axis[0].Label}"
        self.mb2_click()
        self.check_volume("Axis X, Count and Span: 5 over 360°, OK", f"{used}, '{count}' = 5, MB2 = OK",
                          2 * self.d_volume_half() - 5 * self._d_hole,
                          "" if axis else "; the leader sketch's normal is the pulley's X axis here")
        self.wait = 600

    def d_fit(self):
        self.fit()

    def d_show(self):
        self.show("D_pulley")
        self.check_drawn("The finished part is shown in the graphics window", "D_live_check.png")
        App.ActiveDocument.saveAs(os.path.join(OUT, "Pulley.FCStd"))
        self._d_doc = App.ActiveDocument.Name

    def d_drafting(self):
        self.key("Ctrl+Shift+D")
        self.wait = 2500

    def d_sheet(self):
        wb = Gui.activeWorkbench().name()
        self.step("File > Drafting (Ctrl+Shift+D)", "Ctrl+Shift+D",
                  SAME if wb == "TechDrawWorkbench" and self.shell.ribbon.has_tab("Home") else FAIL, wb)
        b, where = self.click_ribbon("New Sheet")
        QtWidgets.QApplication.processEvents()
        page = self.newest("TechDraw::DrawPage")
        tmpl = page.Template.Template if page is not None and page.Template else ""
        self.step("New sheet, A-size, 1:1", f"ribbon '{where} > New Sheet'", DIFFERS if page else FAIL,
                  f"FreeCAD's default template {os.path.basename(str(tmpl))}; an ANSI A sheet is one "
                  "template choice away (Sheet from Template)")
        self._page = page
        self.wait = 1200

    def d_base_view(self):
        doc = App.ActiveDocument
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, self.body().Name)
        b, where = self.click_ribbon("Base View")
        self.wait = 1500
        self._views_before = len(self._page.Views)
        self._base_where = where

    def d_base_view_check(self):
        views = [v for v in self._page.Views if v.isDerivedFrom("TechDraw::DrawViewPart")]
        dialog = bool(Gui.Control.activeDialog())
        base = views[-1] if views else None
        if base is not None:
            base.Direction = App.Vector(1, 0, 0)
            base.XDirection = App.Vector(0, -1, 0)
        if dialog:
            self.mb2_click_on_sheet()
        App.ActiveDocument.recompute()
        self._base = base
        self.step("Base View: Right view of the pulley", f"body selected + ribbon '{self._base_where} > Base View'"
                  f"{'; dialog closed with MB2' if dialog else ''}",
                  SAME if base is not None and not Gui.Control.activeDialog() else FAIL,
                  f"{len(views)} view(s) on the sheet; direction set to Right (+X)")
        self.wait = 800

    def mb2_click_on_sheet(self):
        """Middle click in the middle of the active drawing sheet (not a 3D view)."""
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        sub = mdi.activeSubWindow() if mdi else None
        views = sub.widget().findChildren(QtWidgets.QGraphicsView) if sub else []
        if not views:
            return False
        target = views[0].viewport()
        p = QtCore.QPoint(target.width() // 2, target.height() // 2)
        for kind, buttons in ((QtCore.QEvent.MouseButtonPress, Qt.MiddleButton),
                              (QtCore.QEvent.MouseButtonRelease, Qt.NoButton)):
            QtWidgets.QApplication.sendEvent(target, mouse_event(kind, p, Qt.MiddleButton, buttons, Qt.NoModifier))
        return True

    def d_extra_view(self):
        doc = App.ActiveDocument
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, self.body().Name)
        self.click_ribbon("Base View")
        self.wait = 1500

    def d_delete_view(self):
        views = [v for v in self._page.Views if v.isDerivedFrom("TechDraw::DrawViewPart")]
        if Gui.Control.activeDialog():
            from .navigation import accept_task_dialog
            accept_task_dialog()
        extra = views[-1] if len(views) > 1 else None
        n0 = len(views)
        if extra is not None:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(App.ActiveDocument.Name, extra.Name)
            self.modals.accept = True
            self.key("Delete")
            QtWidgets.QApplication.processEvents()
            self.modals.accept = False
        App.ActiveDocument.recompute()
        n1 = len([v for v in self._page.Views if v.isDerivedFrom("TechDraw::DrawViewPart")])
        self.step("Add a projected view, select it, Delete key", "Base View again + Delete key",
                  DIFFERS if extra is not None and n1 == n0 - 1 else FAIL,
                  f"views {n0} -> {n1}. NX drags projected views off the base view; FreeCAD's Projected View "
                  "is a projection group, so a second Base View stood in for it")
        self.wait = 800

    def d_section(self):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self._base.Name)
        b, where = self.click_ribbon("Section View")
        self._sec_where = where
        self.wait = 1500

    def d_section_dialog(self):
        dock = self.tasks_dock()
        pressed = None
        for btn in dock.findChildren(QtWidgets.QAbstractButton):
            if btn.objectName().lower() in ("pbright", "pbleft") and btn.isVisible():
                btn.click()
                pressed = btn.objectName()
                break
        self.info["D section dialog widgets"] = self.task_widgets()
        QtWidgets.QApplication.processEvents()
        buttons = [(b.text(), b.isVisible(), b.isEnabled()) for box in dock.findChildren(QtWidgets.QDialogButtonBox)
                   for b in box.buttons()]
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        sub = mdi.activeSubWindow() if mdi else None
        sent = self.mb2_click_on_sheet()
        self.progress(f"d_section_dialog: direction {pressed}; buttons {buttons}; "
                      f"active window '{sub.windowTitle() if sub else None}'; MB2 sent {sent}; "
                      f"filter: {self.shell.navigation.mb2_anywhere.trace}")
        self._sec_pressed = pressed
        self.wait = 1500

    def d_section_check(self):
        if Gui.Control.activeDialog():   # MB2 on the sheet did not close it
            self.step("Section View: OK with MB2 on the sheet", "MB2 click", FAIL, "dialog still open")
            from .navigation import accept_task_dialog
            accept_task_dialog()
        App.ActiveDocument.recompute()
        self.wait = 3000   # TechDraw computes hidden lines in a worker thread

    def d_section_edges(self):
        secs = [v for v in self._page.Views if v.TypeId == "TechDraw::DrawViewSection"]
        edges = len(secs[-1].getVisibleEdges()) if secs else 0
        if secs:
            s = secs[-1]
            self.progress(f"d_section_edges: {s.Name} normal {s.SectionNormal} origin {s.SectionOrigin} "
                          f"direction {s.Direction} base {s.BaseView.Name if s.BaseView else None} "
                          f"valid {s.isValid()}; at ({s.X}, {s.Y}), base at ({self._base.X}, {self._base.Y})")
        self.step("Section View through the centre of the base view",
                  f"base view selected + ribbon '{self._sec_where} > Section View', direction "
                  f"'{self._sec_pressed}', MB2 = OK", SAME if secs and edges > 0 else FAIL,
                  f"{len(secs)} section view(s), {edges} visible edges")
        if secs:
            # NX: drag the section off the base view and MB1 to place it. FreeCAD puts it
            # on top of the base view; a FreeCAD user drags it aside afterwards.
            s, base = secs[-1], self._base
            scale = float(base.getScale()) if hasattr(base, "getScale") else float(base.Scale)
            s.X = float(base.X) + 3.0 * IN * scale
            s.Y = float(base.Y)
            App.ActiveDocument.recompute()
            QtWidgets.QApplication.processEvents()
            self.step("Drag the section to the right of the base view, MB1 to place", "X/Y of the section set",
                      DIFFERS, "FreeCAD places the section on top of the base view; it is moved afterwards "
                      f"(placed at x = {float(s.X):.1f} mm, base at {float(base.X):.1f} mm)")
        self.shot("D_drawing.png")
        App.ActiveDocument.save()
        self.wait = 400

    def d_back(self):
        self.key("Ctrl+M")
        self.wait = 1500

    # ------------------------------------------------------------- runner
    def next(self):
        if not self.steps:
            self.finish()
            return
        fn = self.steps.pop(0)
        self.wait = 400
        self.progress(fn.__name__)
        try:
            fn()
        except Exception:
            tb = traceback.format_exc()
            self.info[f"traceback {fn.__name__}"] = tb
            self.step(fn.__name__, "-", FAIL, tb.splitlines()[-1])
            # skip the rest of this tutorial
            prefix = fn.__name__[:2]
            self.steps = [s for s in self.steps if not s.__name__.startswith(prefix)]
        QtCore.QTimer.singleShot(self.wait, self.next)

    @staticmethod
    def commit_mb():
        """This process's committed memory (Windows PrivateUsage), or -1 elsewhere."""
        if os.name != "nt":
            return -1
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                                               "PrivateUsage")]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return -1
        return c.PrivateUsage // 2 ** 20

    def progress(self, name):
        """One flushed line per step, so a run killed mid-step still says where it was."""
        try:
            mb = self.commit_mb()
        except Exception as e:
            mb = f"? {e}"
        try:
            last = self.rows[-1] if self.rows else {}
            with open(os.path.join(OUT, "progress.log"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {mb:>6} MB  start {name}"
                        f"  (last row: {last.get('tutorial', '')[:1]}{last.get('n', '')} {last.get('outcome', '')}"
                        f" {last.get('detail', '')[:200]})\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass

    def finish(self):
        self.progress("finish")
        self.info["unexpected modal dialogs"] = self.modals.seen
        self.info["FreeCAD"] = App.Version()[:4]
        with open(os.path.join(OUT, "tutorial.json"), "w", encoding="utf-8") as f:
            json.dump({"steps": self.rows, "info": self.info}, f, indent=1, default=str)
        if os.environ.get("NXSTYLE_SMOKE_EXIT", "1") == "1":
            for name in list(App.listDocuments()):
                App.closeDocument(name)
            QtCore.QTimer.singleShot(300, Gui.getMainWindow().close)


_replay = None


def start(shell):
    global _replay
    _replay = Replay(shell)
    QtCore.QTimer.singleShot(2000, _replay.next)
