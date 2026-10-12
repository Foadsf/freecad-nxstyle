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
from .qt import QAction, QtCore, QtWidgets, Qt, mouse_event
from .selection_filter import TypeGate

OUT = os.environ.get("NXSTYLE_SMOKE_OUT", "")
EXPECTED_MODELING_TABS = ["Home", "Assemblies", "Curve", "Surface", "Analysis", "View", "Render", "Tools",
                          "Application"]


def expected_tabs():
    """With Strata placed, the PLM tab follows Tools."""
    from . import plm
    tabs = list(EXPECTED_MODELING_TABS)
    if plm.status()["placed"]:
        tabs.insert(tabs.index("Tools") + 1, "PLM")
    return tabs


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
        yield self.s_wait_strata, 200
        yield self.s_static, 200
        yield self.s_document, 1500
        yield self.s_gates, 100
        yield self.s_snap, 900
        yield self.s_strata, 2500
        yield self.s_mouse, 300
        yield self.s_mb2_ok_open, 600
        yield self.s_mb2_ok_click, 600
        yield self.s_mb2_ok_check, 100
        yield self.s_radial_open, 900
        yield self.s_radial_check, 300
        yield self.s_visibility, 300
        yield self.s_keys_doc, 300
        yield self.s_new_commands, 500
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

    def s_wait_strata(self):
        """Strata starts from its own timer; the UI checks begin once NXStyle has placed it."""
        from . import plm
        from .tutorial import qtest
        t0 = time.monotonic()
        if os.environ.get("NXSTYLE_STRATA_EXPECTED", "1") == "1":
            while not plm.status()["placed"] and time.monotonic() - t0 < 20:
                qtest().qWait(100)
        self.info["strata placed after s"] = round(time.monotonic() - t0, 2)

    def s_strata(self):
        """Strata, on by default: started by FreeCAD (not by this test), placed in the NX layout."""
        from . import plm
        st = plm.status()
        self.info["strata"] = st
        want = os.environ.get("NXSTYLE_STRATA_EXPECTED", "1") == "1"
        if not want:
            self.check("Strata off as asked", not st["panel"], st)
            return
        self.check("Strata starts with NXStyle (data management)", st["loaded"] and st["panel"], st)
        mw = Gui.getMainWindow()
        p, model = plm.strata_panel(), mw.findChild(QtWidgets.QDockWidget, "Model")
        tabbed = p is not None and model is not None and p in mw.tabifiedDockWidgets(model)
        self.check("Strata panel among the left navigators", st["placed"] and st["panel_area"] == "left" and tabbed,
                   f"area {st['panel_area']}, tabbed with the Part Navigator {tabbed}")
        self.check("Part Navigator stays in front", self.shell.current_left_tab() == "Part Navigator",
                   self.shell.current_left_tab())
        stray = [(t.count(), t.geometry().getRect()) for t in mw.findChildren(QtWidgets.QTabBar)
                 if t.parentWidget() is mw and t.isVisible() and t.count() < 2
                 and t.geometry().intersects(mw.rect())]       # Qt parks spare tab bars off-screen
        self.check("no empty dock tab strip left on screen (moving the panel)", not stray, stray)
        self.check("resource bar button for Versions and history", st["resource_button"]
                   and "Versions and history" in self.shell.resource_actions, list(self.shell.resource_actions))
        import strata.boot as sb
        self.check("Strata set up for NX before it started: no toolbar of its own, panel made on the left",
                   st["configured_before_start"] and mw.findChild(QtWidgets.QToolBar, "StrataTools") is None
                   and sb.host_provides_toolbar(), st)
        from .ribbon import CommandButton
        acts = sb.actions()
        plm_buttons = {b.command: (b.action is acts.get(b.command), b.isEnabled()) for b in
                       self.shell.ribbon.findChildren(CommandButton) if b.command.startswith("Strata_")}
        self.check("PLM ribbon tab with Strata's commands, live and enabled", self.shell.ribbon.has_tab("PLM")
                   and len(plm_buttons) == 5 and all(a for a, _ in plm_buttons.values())
                   and plm_buttons.get("Strata_Panel", (0, 0))[1], plm_buttons)
        try:
            from strata.ui import theme
            accent = theme.LIGHT["accent"]
        except ImportError:
            accent = None
        self.check("Strata takes NX's accent colour", accent == plm.NX_TOKENS["accent"], accent)
        if p is not None and model is not None:      # pictures for the README: panel in front, PLM tab
            p.raise_()
            self.shell.ribbon.select("PLM")
            QtWidgets.QApplication.processEvents()
            self.shot("09_strata_plm.png")
            model.raise_()
            self.shell.ribbon.select("Home")

    def s_static(self):
        sh = self.shell
        profile = os.path.normcase(os.path.abspath(os.environ.get("NXSTYLE_PROFILE", "?")))
        dirs = [App.getUserAppDataDir(), App.getUserConfigDir(), App.getUserMacroDir(True)]
        inside = all(os.path.normcase(os.path.abspath(d)).startswith(profile) for d in dirs)
        self.check("profile isolation", inside, f"profile={profile} dirs={dirs}")
        self.check("setup without errors", not sh.setup_errors, "; ".join(e.splitlines()[-1] for e in sh.setup_errors))
        tabs = sh.ribbon.tab_names()
        # PLM joins once Strata has started (checked in s_strata)
        self.check("modeling ribbon tabs", [t for t in tabs if t != "PLM"] == EXPECTED_MODELING_TABS, tabs)
        self.info["missing_ribbon_commands"] = sh.ribbon.missing
        self.check("ribbon commands resolved", not sh.ribbon.missing,
                   f"{len(sh.ribbon.missing)} missing: {sh.ribbon.missing}")
        visible = [tb.objectName() for tb in sh.native_toolbars() if tb.isVisible()]
        self.check("FreeCAD toolbars hidden", not visible, visible)
        self.check("menu bar hidden", not Gui.getMainWindow().menuBar().isVisible())
        missing = shortcuts.report(sh.shortcut_rows)
        self.check("every NXtips shortcut has a FreeCAD target", sh.shortcut_rows and not missing,
                   f"{len(sh.shortcut_rows)} rows; missing: {[r['nx'] for r in missing]}")
        self.info["shortcut_rows"] = sh.shortcut_rows
        from .ribbon import command_actions
        no_icon = [a["id"] for a in sh.apps
                   if not command_actions(f"NXStyle_App_{a['id']}")
                   or command_actions(f"NXStyle_App_{a['id']}")[0].icon().isNull()]
        self.check("Application buttons have icons", not no_icon, no_icon)
        bars = [[b.tabText(i) for i in range(b.count())] for b in Gui.getMainWindow().findChildren(QtWidgets.QTabBar)]
        left = next((t for t in bars if "Part Navigator" in t), [])
        self.check("left panels share one tab strip", "Dialog" in left, left)
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        self.check("document tabs above the graphics window",
                   mdi is not None and mdi.tabPosition() == QtWidgets.QTabWidget.North)
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

    def labels_clipped(self):
        """Ribbon group labels on the current page that fall outside the visible area."""
        page = self.shell.ribbon.stack.currentWidget()
        vp = page.viewport()
        bad = []
        for lab in page.widget().findChildren(QtWidgets.QLabel, "NXRibbonGroupLabel"):
            bottom = lab.mapTo(vp, QtCore.QPoint(0, lab.height())).y()
            if bottom > vp.height():
                bad.append(f"{lab.text()} ({bottom}>{vp.height()})")
        return bad

    def check_units(self):
        """Metric by default, and an imperial schema left in the profile is switched back."""
        from . import prefs
        names = prefs.unit_schemas()
        p = App.ParamGet(prefs.UNITS)
        at_start = names[p.GetInt("UserSchema", 0)] if names else "?"
        imperial = next((i for i, n in enumerate(names) if prefs.is_imperial(n)), None)
        planted = "?"
        if imperial is not None:                      # negative control: plant imperial, then re-apply
            p.SetInt("UserSchema", imperial)
            App.Units.setSchema(imperial)
            planted = App.Units.Quantity("25.4 mm").UserString
        after = prefs.apply_units()
        q = App.Units.Quantity("25.4 mm").UserString
        std = names[prefs.standard_schema(names)] if names else "?"
        self.check("units are metric (mm) by default", at_start == std and after == std and imperial is not None
                   and "mm" not in planted and "mm" in q and p.GetInt("UserSchema", -1) == prefs.standard_schema(names),
                   f"at start '{at_start}'; planted '{names[imperial] if imperial is not None else None}' "
                   f"(25.4 mm shown as '{planted}'); NXStyle set '{after}' (25.4 mm shown as '{q}')")

    def s_gates(self):
        # checked a few seconds in: FreeCAD 1.1 may reload its own stylesheet after start-up
        css = QtWidgets.QApplication.instance().styleSheet()
        base = css.split("/* NXStyle theme */")[0]
        self.check("NX theme applied over FreeCAD's light theme", self.shell.theme_active() and len(base) > 10000,
                   f"base {len(base)} chars")
        self.check("no unfilled stylesheet placeholders", "@Theme" not in css)
        self.check_units()
        clipped = self.labels_clipped()
        self.check("ribbon group labels not clipped", not clipped, clipped)
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
        # what occupies the right part of the graphics area (diagnostics)
        mw = Gui.getMainWindow()
        chain = []
        w = mw.childAt(QtCore.QPoint(int(mw.width() * 0.88), int(mw.height() * 0.6)))
        while w is not None and w is not mw and len(chain) < 12:
            chain.append(f"{type(w).__name__}#{w.objectName()}")
            w = w.parentWidget()
        self.info["widget at right of view"] = chain
        self.info["docks"] = [(d.objectName(), d.isVisible(), d.isFloating(), str(mw.dockWidgetArea(d)))
                              for d in mw.findChildren(QtWidgets.QDockWidget)]
        self.info["overlays"] = [(t.objectName(), t.isVisible(), t.count(), [t.tabText(i) for i in range(t.count())])
                                 for t in mw.findChildren(QtWidgets.QTabWidget) if t.objectName().startswith("Overlay")]
        boxes = [o[0] for o in self.info["overlays"] if o[1]]
        self.check("no overlay box over the graphics window", not boxes, boxes)
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
        boxes = [t.objectName() for t in Gui.getMainWindow().findChildren(QtWidgets.QTabWidget)
                 if t.objectName().startswith("Overlay") and t.isVisible()]
        self.check("no overlay box over the view in sketch mode", not boxes, boxes)
        self.shot("02_sketch.png")
        tested, bad = self.press_keys("sketch")
        self.check(f"sketch key presses reach their commands ({tested} keys)", tested and not bad, bad)

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
        # sample across Strata's 2 s toolbar timer: hidden at one instant is not "stays hidden"
        from .tutorial import qtest
        shown = 0
        for _ in range(30):
            fallback = Gui.getMainWindow().findChild(QtWidgets.QToolBar, "StrataTools")
            shown += bool(fallback is not None and fallback.isVisible())
            qtest().qWait(100)
        self.check("Strata's own toolbar stays hidden (no fight with NXStyle)", shown == 0,
                   f"seen visible in {shown} of 30 samples over 3 s")
        doc = App.ActiveDocument
        self.check("Expressions sheet (Ctrl+E)", doc is not None and doc.getObject("Expressions") is not None)
        self.check("back to Modeling", self.shell.ribbon.tab_names() == expected_tabs(),
                   self.shell.ribbon.tab_names())
        self.shell.ribbon.select("Application")
        self.shot("08_application.png", self.shell.ribbon)
        self.shell.ribbon.select("Home")

    # ------------------------------------------------------ keyboard tests
    def press_keys(self, context):
        """Press every key of one context; the probe eats the shortcut event so nothing runs."""
        try:
            from PySide6 import QtTest
        except ImportError:
            from PySide2 import QtTest
        inst = shortcuts.instance()
        target = self.nav().widget
        mw = Gui.getMainWindow()
        mw.activateWindow()
        app = QtWidgets.QApplication.instance()
        if app.activeWindow() is None and hasattr(app, "setActiveWindow"):
            # a hidden desktop has no foreground window; window shortcuts need one
            app.setActiveWindow(mw)
        self.info[f"active window ({context})"] = type(app.activeWindow()).__name__ if app.activeWindow() else None
        target.setFocus()
        results = []
        probe = ShortcutProbe()
        app.installEventFilter(probe)
        try:
            # positive control: a key proven to work by the real-execution test above
            control = inst.targets.get(shortcuts.norm("Ctrl+Shift+B"))
            was = control.isEnabled()
            control.setEnabled(True)
            QtTest.QTest.keyClick(target, Qt.Key_B, Qt.ControlModifier | Qt.ShiftModifier)
            control.setEnabled(was)
            if cpp(control) not in [h[0] for h in probe.hits]:
                return 0, [("probe", "Ctrl+Shift+B", f"instrument failed: control key not seen ({probe.hits})")]
            tested = 0
            for row in self.shell.shortcut_rows:
                if row["context"] != context:
                    continue
                tested += 1
                key = row["keys"]
                act = inst.targets.get(key)
                if act is None:
                    results.append((row["nx"], key, "no action"))
                    continue
                was = act.isEnabled()
                act.setEnabled(True)
                probe.hits = []
                k, m = decode(key)
                QtTest.QTest.keyClick(target, k, m)
                act.setEnabled(was)
                got = [h for h in probe.hits if h[0] == cpp(act)]
                if not got:
                    others = [h[1] for h in probe.hits]
                    results.append((row["nx"], key, f"did not reach its command; went to {others}"))
                elif any(h[2] for h in got):
                    results.append((row["nx"], key, "ambiguous"))
            if context == "doc":
                # a FreeCAD default outside the NX table must survive the hidden toolbars too
                acts = Gui.Command.get("Std_ToggleVisibility").getAction()
                key = acts[0].shortcut().toString() if acts else ""
                if key:
                    probe.hits = []
                    was = acts[0].isEnabled()
                    acts[0].setEnabled(True)
                    k, m = decode(key)
                    QtTest.QTest.keyClick(target, k, m)
                    acts[0].setEnabled(was)
                    self.info["Space spy"] = [h[1] for h in probe.hits]
                    if cpp(acts[0]) not in [h[0] for h in probe.hits]:
                        results.append(("FreeCAD default Std_ToggleVisibility", key, "did not reach its command"))
                    tested += 1
        finally:
            app.removeEventFilter(probe)
        self.info[f"key failures ({context})"] = results
        return tested, results

    def s_keys_doc(self):
        doc = App.ActiveDocument
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, "Box")
        tested, bad = self.press_keys("doc")
        self.check(f"real key presses reach their commands ({tested} keys)", tested and not bad, bad)
        # independent of Qt's dispatch: no other action holds an NX key or a chord starting with it
        inst = shortcuts.instance()
        ours = {id(a) for a in inst.targets.values()}
        clashes = []
        for act in Gui.getMainWindow().findChildren(QAction):
            if id(act) in ours:
                continue
            for s in act.shortcuts():
                txt = s.toString()
                if txt and (shortcuts.norm(txt) in inst.targets or shortcuts.first_chord(txt) in inst.targets):
                    clashes.append(f"{act.objectName() or act.text()}={txt}")
        self.check("no other action shares an NX key", not clashes, clashes[:10])

    def s_new_commands(self):
        doc = App.ActiveDocument
        box = doc.getObject("Box")
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, "Box", "Face1")
        text = commands.object_information()
        self.check("Object Information (Ctrl+I) reports volume and face area",
                   "Volume" in text and "Face1" in text and "area" in text, text.splitlines()[:3])
        Gui.Selection.clearSelection()
        Gui.runCommand("NXStyle_ImmediateHide")
        on = commands.immediate_hide.active
        Gui.Selection.addSelection(doc.Name, "Box", "Face2")
        QtWidgets.QApplication.processEvents()
        hidden = not box.ViewObject.Visibility
        commands.stop_immediate_hide()
        box.ViewObject.Visibility = True
        self.check("Immediate Hide (Ctrl+Shift+I) hides what you pick", on and hidden)
        # F7 rotate mode: MB1 drag rotates, Esc ends
        nav = self.shell.navigation
        f = self.nav()
        nav.set_mode("rotate")
        o0 = self.camera()[0]
        self.drag(f, [Qt.LeftButton], 50, 20)
        o1 = self.camera()[0]
        try:
            from PySide6 import QtTest
        except ImportError:
            from PySide2 import QtTest
        QtTest.QTest.keyClick(self.view().graphicsView(), Qt.Key_Escape)
        self.check("Rotate mode (F7): MB1 drag rotates, Esc ends", o1 != o0 and nav.mode is None,
                   f"rotated={o1 != o0}, mode after Esc={nav.mode}")
        def page_sizes():
            page = self.shell.ribbon.stack.currentWidget()
            return {b.iconSize().width() for b in page.findChildren(QtWidgets.QToolButton, "NXRibbonButton")}
        Gui.runCommand("NXStyle_TouchMode")
        sizes = page_sizes()
        big = 44 in sizes
        Gui.runCommand("NXStyle_TouchMode")
        sizes_after = page_sizes()
        self.check("Touch Mode (F4) enlarges ribbon icons and back", big and 44 not in sizes_after,
                   f"on {sorted(sizes)}, off {sorted(sizes_after)}")
        Gui.runCommand("NXStyle_Refresh")
        lazy = [e for e in shortcuts.TABLE if e.workbench]
        for e in lazy:
            self.shell.preload([e.workbench])
        absent = [f"{e.nx}: {e.cmd}" for e in lazy if shortcuts.resolve(e, set(Gui.listCommands())) == ""]
        self.check("lazily loaded shortcut targets exist after their workbench loads", not absent, absent)

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


def _shiboken():
    try:
        import shiboken6 as shiboken
    except ImportError:
        import shiboken2 as shiboken
    return shiboken


def cpp(obj):
    """C++ address of a Qt object (Python wrappers of one object can differ)."""
    return _shiboken().getCppPointer(obj)[0]


class ShortcutProbe(QtCore.QObject):
    """Application-wide filter: records which action Qt sends each QShortcutEvent
    to, and consumes it so the command never runs during the test."""

    def __init__(self):
        super().__init__()
        self.hits = []      # (receiver address, receiver name, ambiguous)

    def eventFilter(self, obj, ev):
        if ev.type() != QtCore.QEvent.Shortcut:
            return False
        ambiguous = False
        try:   # PySide may hand over a plain QEvent; cast to read the flag
            from PySide import QtGui
            sb = _shiboken()
            ambiguous = bool(sb.wrapInstance(sb.getCppPointer(ev)[0], QtGui.QShortcutEvent).isAmbiguous())
        except Exception:
            pass
        self.hits.append((cpp(obj), obj.objectName(), ambiguous))
        return True


def decode(key):
    """'Ctrl+Shift+B' -> (Qt.Key, Qt.KeyboardModifiers) for QTest."""
    from PySide import QtGui
    c = QtGui.QKeySequence(key)[0]
    if hasattr(c, "key"):          # Qt 6: QKeyCombination
        return c.key(), c.keyboardModifiers()
    mask = int(Qt.KeyboardModifierMask)
    return Qt.Key(c & ~mask), Qt.KeyboardModifiers(c & mask)


_smoke = None


def start(shell):
    global _smoke
    _smoke = Smoke(shell)
    QtCore.QTimer.singleShot(1500, _smoke.next)
