# SPDX-License-Identifier: LGPL-2.1-or-later
"""Replay NX textbook tutorials through the NX-style UI (``launch_nx.py --tutorial OUTDIR``).

Each step is done the way the book tells an NX user to do it: the same key,
the same ribbon button (found by its NX name), MB1 clicks in the graphics
window for sketch curves, MB2 to end a tool or accept a dialog. Where the
FreeCAD flow differs, the step says so. Typed dimension values are applied to
the sketch through FreeCAD's API (the equivalent of typing them into Rapid
Dimension), and every feature is checked by its volume.

Tutorial steps paraphrase two exercises found through the NX notebook:
  A  "The Adjuster"  - Shih, Parametric Modeling with Siemens NX, ch. 2
  B  "First part"    - hollow cylinder plus revolved cone (NX course exercise)
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

    def set_quantity(self, name_part, value):
        """Type a value into a task-panel quantity field (e.g. Length)."""
        for w in self.tasks_dock().findChildren(QtWidgets.QAbstractSpinBox):
            if name_part.lower() in w.objectName().lower():
                w.setProperty("rawValue", float(value))
                return w.objectName()
        return None

    def set_combo(self, name_part, option_part):
        for c in self.tasks_dock().findChildren(QtWidgets.QComboBox):
            if name_part.lower() in c.objectName().lower():
                for i in range(c.count()):
                    if option_part.lower() in c.itemText(i).lower():
                        c.setCurrentIndex(i)
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
        for fn in A + B:
            yield fn

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
        origin_shown = bool(body and body.Origin.ViewObject.Visibility)
        self.step("File > New (Ctrl+N), Model template", "Ctrl+N",
                  SAME if new and body and origin_shown else FAIL,
                  f"new document {sorted(new)}; Body with origin planes shown = {origin_shown}")
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
        # top face of the horizontal leg (normal +Y at y = 0.75 in)
        doc = App.ActiveDocument
        body = self.body()
        tip = body.Tip
        face = None
        for i, f in enumerate(tip.Shape.Faces, start=1):
            n = f.normalAt(0, 0)
            if abs(n.y - 1) < 1e-6 and abs(f.CenterOfMass.y - 0.75 * IN) < 1e-6:
                face = f"Face{i}"
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, body.Name, f"{tip.Name}.{face}")
        b, where = self.click_ribbon("Extrude (Subtract)")
        self.step("Extrude, pick the leg's face as sketch plane, Boolean Subtract",
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
        c1 = inv.multVec(App.Vector(1.25 * IN, 0.75 * IN, -0.2 * IN))
        c2 = inv.multVec(App.Vector(2.25 * IN, 0.75 * IN, 2.7 * IN))
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
        mode = self.set_combo("mode", "through")
        self.step("Reverse Direction into the solid", "-", DIFFERS,
                  "not needed: FreeCAD's subtracting extrude cuts into the solid by default")
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        App.ActiveDocument.recompute()
        base = (2.5 * 2.5 - 1.75 * 1.75) * 2.5
        want = (base - 1.0 * 0.75 * 2.5) * IN ** 3
        got = self.solid_volume()
        ok = abs(got - want) < 1e-3 * want and not Gui.Control.activeDialog()
        self.step("End = Through All, OK", f"'{mode}' chosen, MB2 = OK", SAME if ok else FAIL,
                  f"volume {got / IN**3:.4f} in^3, expected {want / IN**3:.4f}")
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
        self.info[f"camera {name}"] = str(self.view().getCamera())[:400]
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit()
        self.info[f"in edit {name}"] = vp.Object.Name if vp is not None else None
        try:
            from pivy import coin
            scene = self.view().getSceneGraph()
            found = {}
            for o in App.ActiveDocument.Objects:
                vo = getattr(o, "ViewObject", None)
                if vo is None or not vo.Visibility or o.TypeId.startswith("App::"):
                    continue
                sa = coin.SoSearchAction()
                sa.setNode(vo.RootNode)
                sa.apply(scene)
                found[o.Name] = sa.getPath() is not None
            self.info[f"in scene graph {name}"] = found
        except Exception as e:
            self.info[f"in scene graph {name}"] = str(e)
        self.shot(name + ".png")
        try:
            self.view().saveImage(os.path.join(OUT, name + "_3d.png"), 1200, 800, "Current")
            body = self.body()
            body.Origin.ViewObject.Visibility = False
            QtWidgets.QApplication.processEvents()
            self.view().saveImage(os.path.join(OUT, name + "_3d_no_origin.png"), 1200, 800, "Current")
            self.shot(name + "_no_origin.png")
            body.Origin.ViewObject.Visibility = True
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
        same_cam = f.view.getCameraNode() == self.view().getCameraNode()
        self.info["MB2 drag diag"] = {"filter events": getattr(f, "events", "n/a"), "same camera": same_cam,
                                      "filter view camera": str(f.view.getCamera())[:200],
                                      "active view camera": str(self.view().getCamera())[:200]}
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

    # ------------------------------------------------------------- runner
    def next(self):
        if not self.steps:
            self.finish()
            return
        fn = self.steps.pop(0)
        self.wait = 400
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

    def finish(self):
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
