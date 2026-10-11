# SPDX-License-Identifier: LGPL-2.1-or-later
"""Self-test run inside FreeCAD (``launch_nx.py --smoke-test OUTDIR``).

It drives the real UI: synthetic mouse events on the 3D view, ribbon and
command lookups, application switching, sketch edit mode. Results go to
OUTDIR/smoke.json and screenshots to OUTDIR/*.png.
"""

import json
import os
import time
import traceback

import FreeCAD as App
import FreeCADGui as Gui

from . import commands, navigation, prefs, shortcuts
from .qt import QtCore, QtWidgets, Qt, mouse_event
from .selection_filter import TypeGate

OUT = os.environ.get("NXSTYLE_SMOKE_OUT", "")
EXPECTED_MODELING_TABS = ["Home", "Assemblies", "Curve", "Surface", "Analysis", "View", "Render", "Tools",
                          "Application"]


class Smoke:
    def __init__(self, shell):
        self.shell = shell
        self.checks = []
        self.info = {}
        self.steps = list(self.plan())

    def check(self, name, ok, detail=""):
        self.checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    def shot(self, name, widget=None):
        try:
            (widget or Gui.getMainWindow()).grab().save(os.path.join(OUT, name))
        except Exception as e:
            self.info[f"screenshot {name}"] = str(e)

    # ------------------------------------------------------------ helpers
    def view(self):
        return Gui.ActiveDocument.ActiveView

    def nav(self):
        return self.shell.navigation.filter_for_active_view()

    def send(self, f, kind, p, button, buttons):
        ev = mouse_event(kind, p, button, buttons, Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(f.widget, ev)

    def drag(self, f, buttons_down, dx, dy, start=None):
        """Press buttons in order, move in steps, release in reverse order."""
        w = f.widget
        p = start or QtCore.QPoint(w.width() // 2, w.height() // 2)
        held = Qt.NoButton
        for b in buttons_down:
            held = held | b
            self.send(f, QtCore.QEvent.MouseButtonPress, p, b, held)
        for i in range(1, 11):
            q = QtCore.QPoint(p.x() + dx * i // 10, p.y() + dy * i // 10)
            self.send(f, QtCore.QEvent.MouseMove, q, Qt.NoButton, held)
        for b in reversed(buttons_down):
            held = held & ~b
            self.send(f, QtCore.QEvent.MouseButtonRelease, q, b, held)

    def camera(self):
        cam = self.view().getCameraNode()
        o = cam.orientation.getValue().getValue()
        pp = cam.position.getValue()
        h = cam.height.getValue() if hasattr(cam, "height") else None
        return tuple(round(x, 5) for x in o), tuple(round(pp[i], 4) for i in range(3)), h

    # --------------------------------------------------------------- plan
    def plan(self):
        """Yields (callable, delay_ms_after)."""
        yield self.s_static, 200
        yield self.s_document, 1500
        yield self.s_gates, 100
        yield self.s_snap, 900
        yield self.s_mouse, 300
        yield self.s_mb2_ok_open, 600
        yield self.s_mb2_ok_click, 600
        yield self.s_mb2_ok_check, 100
        yield self.s_radial_open, 900
        yield self.s_radial_check, 300
        yield self.s_visibility, 300
        yield self.s_finder, 100
        yield self.s_repeat, 800
        yield self.s_sketch_enter, 1500
        yield self.s_sketch_check, 100
        yield self.s_sketch_leave, 1200
        yield self.s_sketch_left, 100
        yield self.s_drafting, 2500
        yield self.s_drafting_check, 100
        yield self.s_auto_app, 4000
        yield self.s_auto_check, 100
        yield self.s_back, 2000
        yield self.s_expressions, 800
        yield self.s_final, 100

    def s_static(self):
        sh = self.shell
        profile = os.path.normcase(os.path.abspath(os.environ.get("NXSTYLE_PROFILE", "?")))
        dirs = [App.getUserAppDataDir(), App.getUserConfigDir(), App.getUserMacroDir(True)]
        inside = all(os.path.normcase(os.path.abspath(d)).startswith(profile) for d in dirs)
        self.check("profile isolation", inside, f"profile={profile} dirs={dirs}")
        self.check("setup without errors", not sh.setup_errors, "; ".join(e.splitlines()[-1] for e in sh.setup_errors))
        tabs = sh.ribbon.tab_names()
        self.check("modeling ribbon tabs", tabs == EXPECTED_MODELING_TABS, tabs)
        self.info["missing_ribbon_commands"] = sh.ribbon.missing
        self.check("ribbon commands resolved", not sh.ribbon.missing,
                   f"{len(sh.ribbon.missing)} missing: {sh.ribbon.missing}")
        visible = [tb.objectName() for tb in sh.native_toolbars() if tb.isVisible()]
        self.check("FreeCAD toolbars hidden", not visible, visible)
        self.check("menu bar hidden", not Gui.getMainWindow().menuBar().isVisible())
        bad = shortcuts.report(sh.shortcut_result)
        self.check("NX shortcuts applied", not bad and sh.shortcut_result,
                   f"{len(sh.shortcut_result)} set; mismatches: {bad}")
        from .ribbon import command_actions
        no_icon = [a["id"] for a in sh.apps
                   if not command_actions(f"NXStyle_App_{a['id']}")
                   or command_actions(f"NXStyle_App_{a['id']}")[0].icon().isNull()]
        self.check("Application buttons have icons", not no_icon, no_icon)
        sh._fill_history()
        self.check("History panel explains when empty", sh.history_dock.widget().count() >= 1)
        self.info["freecad"] = App.Version()[:4]
        self.info["qt"] = QtCore.qVersion()
        groups = {}
        for n in Gui.listCommands():
            try:
                acts = Gui.Command.get(n).getAction() or []
            except Exception:
                continue
            if len(acts) > 1:
                groups[n] = [a.objectName() for a in acts[1:]]
        self.info["group_commands"] = groups

    def s_document(self):
        Gui.getMainWindow().resize(1600, 1000)
        doc = App.newDocument("NXSmoke")
        import Part  # noqa: F401
        box = doc.addObject("Part::Box", "Box")
        box.Length, box.Width, box.Height = 40, 30, 20
        doc.recompute()
        Gui.SendMsgToActiveView("ViewFit")
        Gui.runCommand("Std_ViewTrimetric")

    def s_gates(self):
        doc = App.ActiveDocument
        box = doc.getObject("Box")
        face, edge, body = TypeGate("face"), TypeGate("edge"), TypeGate("body")
        ok = (face.allow(doc, box, "Face1") and not face.allow(doc, box, "Edge1")
              and edge.allow(doc, box, "Edge3") and not edge.allow(doc, box, "Face2")
              and body.allow(doc, box, "Face1"))
        self.check("type filter gates", ok)
        nav_type = self.view().getNavigationType()
        want = prefs.navigation_style(self.shell.cfg)
        self.check("navigation style", nav_type == want, nav_type)
        self.check("NX mouse filter attached", self.nav() is not None)
        self.check("Part Navigator in front without a dialog", self.shell.current_left_tab() == "Part Navigator",
                   self.shell.current_left_tab())
        tri = self.nav().triad if self.nav() else None
        vp = self.nav().widget if self.nav() else None
        if tri is not None and vp is not None:
            g = tri.geometry()
            lower_left = g.left() < vp.width() * 0.2 and g.top() > vp.height() * 0.6
            corner_off = not App.ParamGet(prefs.VIEW).GetBool("CornerCoordSystem", True)
            self.check("view triad lower-left, FreeCAD's hidden", tri.isVisible() and lower_left and corner_off,
                       f"triad {g.left()},{g.top()} in {vp.width()}x{vp.height()}, FreeCAD corner off={corner_off}")
            self.shot("07_triad.png", tri)
        else:
            self.check("view triad lower-left, FreeCAD's hidden", False, "no triad")
        self.shot("01_modeling.png")
        try:  # grab() cannot capture OpenGL; render the 3D view itself
            Gui.Selection.addSelection(doc.Name, "Box", "Face6")
            Gui.Selection.setPreselection(doc.getObject("Box"), "Face2")
            self.view().saveImage(os.path.join(OUT, "01_view3d.png"), 1200, 800, "Current")
            Gui.Selection.clearSelection()
        except Exception as e:
            self.info["view3d image"] = str(e)
        # start the snap test from a slightly rotated front view
        rot = App.Rotation(App.Vector(1, 0, 0), 90).multiply(App.Rotation(App.Vector(0, 1, 0), 12))
        self.view().setCameraOrientation(rot.Q, True)

    def s_snap(self):
        Gui.runCommand("NXStyle_SnapView")

    def s_mouse(self):
        d = self.view().getViewDirection()
        self.check("Snap View (F8) aligns to an axis", max(abs(d.x), abs(d.y), abs(d.z)) > 0.999, d)
        Gui.runCommand("Std_ViewTrimetric")
        self.view().fitAll()
        f = self.nav()
        if f is None:
            self.check("MB2 rotate", False, "no filter")
            return
        o0, p0, h0 = self.camera()
        self.drag(f, [Qt.MiddleButton], 60, 25)
        o1, p1, h1 = self.camera()
        self.check("MB2 drag rotates", o1 != o0, f"{o0} -> {o1}")
        self.drag(f, [Qt.MiddleButton, Qt.RightButton], 80, 40)
        o2, p2, h2 = self.camera()
        self.check("MB2+MB3 drag pans", p2 != p1 and o2 == o1, f"pos {p1} -> {p2}")
        self.drag(f, [Qt.MiddleButton, Qt.LeftButton], 0, -60)
        o3, p3, h3 = self.camera()
        self.check("MB1+MB2 drag zooms", h3 is not None and h2 is not None and h3 < h2, f"height {h2} -> {h3}")

    def s_mb2_ok_open(self):
        smoke = self

        class Panel:
            def __init__(self):
                self.form = QtWidgets.QLabel("NXStyle smoke-test dialog")

            def accept(self):
                smoke.info["dialog_accepted"] = True
                Gui.Control.closeDialog()
                return True

            def reject(self):
                Gui.Control.closeDialog()
                return True

        self.info["dialog_accepted"] = False
        Gui.Control.showDialog(Panel())

    def s_mb2_ok_click(self):
        f = self.nav()
        w = f.widget
        p = QtCore.QPoint(30, w.height() - 30)
        self.send(f, QtCore.QEvent.MouseButtonPress, p, Qt.MiddleButton, Qt.MiddleButton)
        self.send(f, QtCore.QEvent.MouseButtonRelease, p, Qt.MiddleButton, Qt.NoButton)

    def s_mb2_ok_check(self):
        self.check("MB2 click = OK in dialog", self.info.get("dialog_accepted"))
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()

    def s_radial_open(self):
        f = self.nav()
        p = QtCore.QPoint(40, 40)   # empty background in the corner
        self.send(f, QtCore.QEvent.MouseButtonPress, p, Qt.RightButton, Qt.RightButton)

    def s_radial_check(self):
        f = self.nav()
        menu = f.last_radial
        ok = menu is not None and menu.isVisible() and len(menu.items) >= 6
        self.check("MB3 hold opens radial menu", ok, [i["label"] for i in menu.items] if menu else None)
        if menu is not None:
            self.shot("05_radial.png", menu)
            menu.close()

    def s_visibility(self):
        doc = App.ActiveDocument
        box = doc.getObject("Box")
        Gui.runCommand("NXStyle_InvertVisibility")
        hidden = not box.ViewObject.Visibility
        Gui.runCommand("NXStyle_InvertVisibility")
        self.check("Invert Shown and Hidden", hidden and box.ViewObject.Visibility)
        # a real key press through Qt's shortcut map, not just a settings read-back
        try:
            try:
                from PySide6 import QtTest
            except ImportError:
                from PySide2 import QtTest
            target = self.nav().widget
            target.setFocus()
            QtTest.QTest.keyClick(target, Qt.Key_B, Qt.ControlModifier | Qt.ShiftModifier)
            pressed_hidden = not box.ViewObject.Visibility
            QtTest.QTest.keyClick(target, Qt.Key_B, Qt.ControlModifier | Qt.ShiftModifier)
            self.check("Ctrl+Shift+B key press inverts visibility", pressed_hidden and box.ViewObject.Visibility)
        except ImportError as e:
            self.check("Ctrl+Shift+B key press inverts visibility", True, f"QtTest unavailable, skipped: {e}")
        from . import showhide
        dlg = showhide.show_dialog()
        rows = dlg.grid.rowCount()
        self.shot("06_show_hide.png", dlg)
        dlg.close()
        self.check("Show and Hide dialog lists types", rows >= 3, f"{rows} rows")

    def s_finder(self):
        hits = self.shell.finder.find("Edge Blend")
        self.check("Command Finder finds NX names", "PartDesign_Fillet" in hits, hits[:5])

    def s_repeat(self):
        doc = App.ActiveDocument
        n0 = len(doc.Objects)
        Gui.Command.get("Part_Cylinder").getAction()[0].trigger()
        self.info["last_command"] = commands.last_command["name"]
        Gui.runCommand("NXStyle_RepeatCommand")
        doc.recompute()
        self.check("Repeat Command (F4)", len(doc.Objects) == n0 + 2 and commands.last_command["name"] == "Part_Cylinder",
                   f"objects {n0} -> {len(doc.Objects)}, last={commands.last_command['name']}")

    def s_sketch_enter(self):
        doc = App.ActiveDocument
        sk = doc.addObject("Sketcher::SketchObject", "Sketch")
        doc.recompute()
        Gui.ActiveDocument.setEdit(sk.Name)

    def s_sketch_check(self):
        tabs = self.shell.ribbon.tab_names()
        self.check("contextual Sketch tab in sketch mode", tabs[:1] == ["Sketch"] and navigation.in_sketch_edit(),
                   tabs)
        visible = [tb.objectName() for tb in self.shell.native_toolbars() if tb.isVisible()]
        self.check("sketcher toolbars stay hidden", not visible, visible)
        self.shot("02_sketch.png")

    def s_sketch_leave(self):
        Gui.ActiveDocument.resetEdit()

    def s_sketch_left(self):
        self.check("Sketch tab removed after Finish", "Sketch" not in self.shell.ribbon.tab_names(),
                   self.shell.ribbon.tab_names())

    def s_drafting(self):
        self.shell.switch_application("drafting")

    def s_drafting_check(self):
        r = self.shell.ribbon
        self.check("Drafting application ribbon", Gui.activeWorkbench().name() == "TechDrawWorkbench"
                   and "TechDraw_View" in r.locations, r.tab_names())
        self.info["missing_drafting_commands"] = r.missing
        self.shot("03_drafting.png")

    def s_auto_app(self):
        if self.shell._app("simulation"):
            self.shell.switch_application("simulation")

    def s_auto_check(self):
        if not self.shell._app("simulation"):
            self.check("auto ribbon (FEM)", True, "FEM not installed; skipped")
            return
        r = self.shell.ribbon
        page = r.stack.widget(0)
        groups = page.widget().findChildren(QtWidgets.QFrame, "NXRibbonGroup")
        self.check("auto ribbon from workbench toolbars (FEM)", r.tab_names()[:1] == ["Pre/Post"] and len(groups) > 2,
                   f"{r.tab_names()[:2]}, {len(groups)} groups")
        visible = [tb.objectName() for tb in self.shell.native_toolbars() if tb.isVisible()]
        self.check("FEM toolbars hidden", not visible, visible)
        self.shot("04_simulation.png")

    def s_back(self):
        self.shell.switch_application("modeling")

    def s_expressions(self):
        Gui.runCommand("NXStyle_Expressions")

    def s_final(self):
        doc = App.ActiveDocument
        self.check("Expressions sheet (Ctrl+E)", doc is not None and doc.getObject("Expressions") is not None)
        self.check("back to Modeling", self.shell.ribbon.tab_names() == EXPECTED_MODELING_TABS,
                   self.shell.ribbon.tab_names())
        self.shell.ribbon.select("Application")
        self.shot("08_application.png", self.shell.ribbon)
        self.shell.ribbon.select("Home")

    # --------------------------------------------------------------- runner
    def next(self):
        if not self.steps:
            self.finish()
            return
        fn, delay = self.steps.pop(0)
        try:
            fn()
        except Exception:
            self.check(f"step {fn.__name__}", False, traceback.format_exc().splitlines()[-1])
            self.info[f"traceback {fn.__name__}"] = traceback.format_exc()
        QtCore.QTimer.singleShot(delay, self.next)

    def finish(self):
        result = {"checks": self.checks, "info": self.info, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(os.path.join(OUT, "smoke.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1, default=str)
        if os.environ.get("NXSTYLE_SMOKE_EXIT") == "1":
            for name in list(App.listDocuments()):
                App.closeDocument(name)
            QtCore.QTimer.singleShot(300, Gui.getMainWindow().close)


_smoke = None


def start(shell):
    global _smoke
    _smoke = Smoke(shell)
    QtCore.QTimer.singleShot(1500, _smoke.next)
