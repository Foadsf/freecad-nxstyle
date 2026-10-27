# SPDX-License-Identifier: LGPL-2.1-or-later
"""Self-test run inside FreeCAD (``launch_nx.py --smoke-test OUTDIR``).

It drives the real UI: synthetic mouse events on the 3D view, ribbon and
command lookups, application switching, sketch edit mode. Results go to
OUTDIR/smoke.json and screenshots to OUTDIR/*.png.
"""

import os
import time
import traceback

import FreeCAD as App
import FreeCADGui as Gui

from . import commands, navigation, prefs, shortcuts
from .qt import QAction, QtCore, QtWidgets, Qt, mouse_event


def pixel_luminance(argb):
    """Rec. 601 luminance (0..255) of a QImage.pixel() value."""
    r, g, b = (argb >> 16) & 0xFF, (argb >> 8) & 0xFF, argb & 0xFF
    return 0.299 * r + 0.587 * g + 0.114 * b
from .selection_filter import TypeGate

OUT = os.environ.get("NXSTYLE_SMOKE_OUT", "")
EXPECTED_MODELING_TABS = ["Home", "Assemblies", "Curve", "Surface", "Analysis", "PMI", "View", "Render", "Tools",
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
        only = [s for s in os.environ.get("NXSTYLE_SMOKE_ONLY", "").split(",") if s]
        if only:                         # a developer's quick run: Strata's wait, then only the named steps
            self.steps = [(fn, d) for fn, d in self.steps if fn.__name__ == "s_wait_strata" or fn.__name__ in only]
            self.steps += [(getattr(self, s), 300) for s in only if s not in [fn.__name__ for fn, _ in self.steps]
                           and hasattr(self, s)]
        self.planned = [fn.__name__ for fn, _ in self.steps]
        self.ran = []

    def check(self, name, ok, detail=""):
        self.checks.append({"name": name, "ok": bool(ok), "status": "pass" if ok else "fail", "detail": str(detail)})

    def skip(self, name, detail):
        """A check this FreeCAD cannot run (the capability is absent): counted as skipped, not as passed."""
        self.checks.append({"name": name, "ok": True, "status": "skipped", "detail": str(detail)})

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
        yield self.s_layout_matrix, 300
        yield self.s_layout_controls, 300
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
        yield self.s_finder, 300
        yield self.s_finder_check, 100
        yield self.s_finder_click, 300
        yield self.s_finder_check, 100
        yield self.s_repeat, 800
        yield self.s_sketch_enter, 1500
        yield self.s_sketch_check, 100
        yield self.s_profile, 300
        yield self.s_sketch_trim, 300             # before Point on Curve: MB2 must not leave the trim's gate up
        yield self.s_sketch_constraints, 300
        yield self.s_sketch_point_typed, 300
        yield self.s_sketch_linear_dimension, 300
        yield self.s_sketch_hide, 300
        yield self.s_sketch_datum, 300
        yield self.s_sketch_arc, 600              # FreeCAD refreshes the command states on a timer
        yield self.s_sketch_radius, 400
        yield self.s_sketch_radius_check, 100
        yield self.s_sketch_leave, 1200
        yield self.s_sketch_left, 100
        yield self.s_drafting, 2500
        yield self.s_drafting_check, 100
        yield self.s_switch_dialog_open, 1500
        yield self.s_switch_dialog_check, 1500
        yield self.s_switch_nav, 1500
        yield self.s_switch_nav_check, 100
        yield self.s_auto_app, 4000
        yield self.s_auto_check, 100
        yield self.s_katydid, 3000
        yield self.s_katydid_check, 2500
        yield self.s_katydid_shot, 100
        yield self.s_back, 2000
        yield self.s_katydid_after, 100
        yield self.s_laser_cut, 2500
        yield self.s_laser_cut_check, 300
        yield self.s_laser_cut_join, 1500
        yield self.s_laser_cut_result, 300
        yield self.s_laser_cut_back, 2000
        yield self.s_laser_cut_after, 100
        yield self.s_dfm, 1500
        yield self.s_dfm_check, 300
        yield self.s_dfm_run_notched, 500
        yield self.s_dfm_result_notched, 300
        yield self.s_dfm_run_clean, 500
        yield self.s_dfm_result_clean, 300
        yield self.s_dfm_after, 100
        yield self.s_layout_persist, 2500          # switches applications: after the other switching steps
        yield self.s_layout_persist_check, 300
        yield self.s_ap242, 300
        yield self.s_model_views, 300
        yield self.s_assembly_links, 200
        yield self.s_selection, 300
        yield self.s_extrude_key, 1500
        yield self.s_extrude_key_check, 300
        yield self.s_section, 300
        yield self.s_primitives, 300
        yield self.s_thread, 300
        yield self.s_move, 300
        yield self.s_geometry_oracle, 100
        yield self.s_validity, 300
        yield self.s_inspection, 300
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
        self.info["Strata PanelVisible after placement"] = App.ParamGet(
            "User parameter:BaseApp/Preferences/Mod/Strata").GetBool("PanelVisible", True)
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
        bars = [[b.tabText(i) for i in range(b.count())] for b in mw.findChildren(QtWidgets.QTabBar)
                if b.isVisible()]
        left = next((t for t in bars if "Part Navigator" in t), [])
        self.check("Versions and history tab in the left strip (also on a second start)",
                   "Versions and history" in left, left)
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
        if hasattr(sb, "activate_commands"):          # Strata 0.2.1+: it has keys of its own
            owners = {k: sorted(Gui.Command.listByShortcut(k)) for k in ("Ctrl+Shift+D", "Ctrl+Shift+Y",
                                                                      "Ctrl+Shift+H")}
            # NXStyle's key pass would take D/Y back anyway (measured: same owners with Strata's defaults);
            # what plm.STRATA_SHORTCUTS changes is Strata's own view, which its Tools menu shows
            eff = sb.effective_shortcuts() if hasattr(sb, "effective_shortcuts") else {}
            self.check("Strata's keys leave NX's Ctrl+Shift+D/Y alone (Ctrl+Shift+H still Strata's)",
                       owners["Ctrl+Shift+D"] == ["NXStyle_App_drafting"]
                       and owners["Ctrl+Shift+Y"] == ["NXStyle_App_draft"]
                       and owners["Ctrl+Shift+H"] == ["Strata_Panel"]
                       and not eff.get("Strata_Compare") and not eff.get("Strata_Sync"),
                       {"owners": owners, "Strata's own": eff})
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
            if not lab.isVisibleTo(page):           # a collapsed or overflowed group shows no label
                continue
            bottom = lab.mapTo(vp, QtCore.QPoint(0, lab.height())).y()
            if bottom > vp.height():
                bad.append(f"{lab.text()} ({bottom}>{vp.height()})")
        return bad

    # ----------------------------------------------------- responsive ribbon
    SMOKE_WINDOW = (1600, 1000)

    def layout_matrix(self, app):
        """Window-size matrix (ribbon_layout.matrix_cells) for the current application, measured from widget
        geometry; one check per application, the cells' details in info."""
        from . import layout_check
        results = layout_check.run_matrix(self.shell)
        Gui.getMainWindow().resize(*self.SMOKE_WINDOW)
        layout_check.settle()
        failed = [f"{c['cell']}: {c['problems'][:4]}" for c in results if not c["ok"]]
        self.info[f"layout matrix {app}"] = results
        self.check(f"{app} ribbon at 1366x768 and 1920x1080, 100-200 % scale: nothing clipped, every command "
                   "and the essential ones reachable", len(results) == 8 and not failed,
                   failed[:3] or [f"{c['cell']}: {c['reach']}" for c in results])
        return results

    def s_layout_matrix(self):
        from . import layout_check
        screen = QtWidgets.QApplication.primaryScreen()
        self.info["screen"] = {"logical": [screen.size().width(), screen.size().height()],
                               "device_pixel_ratio": screen.devicePixelRatio()}
        results = self.layout_matrix("Modeling")
        # the narrowest cell must actually exercise collapse and overflow, or the matrix proves nothing
        narrow = min(results, key=lambda c: c["window"][0])
        stages = {s for tab in narrow["tabs"].values() for s in tab.values()}
        self.check("narrow window collapses ribbon groups (positive control of the reduction)",
                   {"collapsed"} & stages and narrow["reach"]["group"] + narrow["reach"]["overflow"] > 0,
                   f"{narrow['cell']}: {narrow['tabs'].get('Home')}")
        short = {c["cell"]: c.get("ribbon") for c in results}
        self.check("a window too short for the ribbon minimises it, a tab drops its page down, and it comes "
                   "back when the window is taller", short.get("1366x768@200%") == "minimised automatically"
                   and short.get("1366x768@100%") == "expanded" and not self.shell.ribbon.is_collapsed(), short)
        wide = max(results, key=lambda c: c["window"][0])
        home = layout_check.measure_page(self.shell.ribbon.stack.widget(0), "Home")
        self.check("Modeling essentials one click away at 1920x1080 100 %",
                   all(v == "direct" for v in wide["essential"].values()), wide["essential"])
        self.info["home stages at smoke size"] = home["stages"]

    def s_layout_controls(self):
        """Negative controls: the checks must catch a ribbon that clips (reduction switched off) and a
        collapsed group whose menu lost a command."""
        from . import layout_check, ribbon_layout
        r = self.shell.ribbon
        cell = ribbon_layout.matrix_cells()[2]                   # 1366x768 at 150 %: ribbon expanded, narrow
        Gui.getMainWindow().resize(*cell["window"])
        r.select("Home")
        layout_check.settle()
        page = r.stack.currentWidget()
        page.layout_enabled = False
        page.refit()
        layout_check.settle()
        off = layout_check.measure_page(page, "Home")
        page.layout_enabled = True
        page.refit()
        layout_check.settle()
        on = layout_check.measure_page(page, "Home")
        self.check("layout check catches a ribbon that does not reduce (negative control)",
                   (off["clipped"] or off["scroll"] > 0 or off["unreachable"]) and not on["clipped"]
                   and on["scroll"] == 0 and not on["unreachable"],
                   f"reduction off: scroll {off['scroll']}px, {len(off['clipped'])} clipped, "
                   f"{len(off['unreachable'])} unreachable; on: scroll {on['scroll']}px, {len(on['clipped'])} clipped")
        group = next((g for g in page.groups if g.stage == ribbon_layout.COLLAPSED and len(g.entries()) > 1), None)
        if group is None:
            self.check("layout check catches a command missing from a collapsed group's menu (negative control)",
                       False, f"no collapsed group on Home at {cell['name']}: {on['stages']}")
        else:
            real = group.populate

            def lossy(menu):
                real(menu)
                menu.removeAction(menu.actions()[-1])
            group.populate = lossy
            broken = layout_check.measure_page(page, "Home")
            del group.populate
            fixed = layout_check.measure_page(page, "Home")
            self.check("layout check catches a command missing from a collapsed group's menu (negative control)",
                       broken["unreachable"] and not fixed["unreachable"], broken["unreachable"])
        Gui.getMainWindow().resize(*self.SMOKE_WINDOW)
        layout_check.settle()

    def s_layout_persist(self):
        """Always Collapsed (the group's right-click menu) is saved with the profile and survives rebuilding
        the ribbon; the collapsed group's menu entry runs the command as the button does."""
        from . import layout_check, ribbon_layout
        if (self.shell.current_app or {}).get("id") != "modeling":
            self.shell.switch_application("modeling")
        r = self.shell.ribbon
        r.select("View")
        layout_check.settle()
        group = next(g for _t, g in r.groups("View") if g.title == "Orientation")
        r.set_group_preference("View", group, ribbon_layout.COLLAPSED)
        layout_check.settle()
        self._persist = {"path": r.store.path, "collapsed_now": group.stage == ribbon_layout.COLLAPSED}
        ran, prev = [], r.on_run
        r.on_run = ran.append
        menu = QtWidgets.QMenu()
        group.populate(menu)
        act = next((a for a in menu.actions() if a.data() == "Std_ViewFitAll"), None)
        if act is not None:
            act.trigger()
        r.on_run = prev
        menu.deleteLater()
        self.check("a collapsed group's menu entry runs its command (Orientation › Fit)",
                   act is not None and ran == ["Std_ViewFitAll"], ran)
        r.set_collapsed(True)
        self._persist["minimized_saved"] = r.store.minimized
        r.set_collapsed(False)
        self.shell.switch_application("drafting")
        self.shell.switch_application("modeling")

    def s_layout_persist_check(self):
        from . import layout_check, ribbon_layout
        r = self.shell.ribbon
        r.select("View")                           # a page fits its width once it is shown
        layout_check.settle()
        group = next(g for _t, g in r.groups("View") if g.title == "Orientation")
        reread = ribbon_layout.LayoutStore(os.path.dirname(self._persist["path"]))
        rebuilt = (group.preference, group.stage)
        ok = (self._persist["collapsed_now"] and self._persist["minimized_saved"]
              and rebuilt == (ribbon_layout.COLLAPSED, ribbon_layout.COLLAPSED)
              and reread.preference("modeling", "View", "Orientation") == ribbon_layout.COLLAPSED
              and not reread.minimized and not reread.error)
        r.set_group_preference("View", group, ribbon_layout.AUTO)
        layout_check.settle()
        cleared = ribbon_layout.LayoutStore(os.path.dirname(self._persist["path"]))
        after = group.stage
        r.select("Home")
        self.check("ribbon group layout saved in the profile and kept after the ribbon is rebuilt",
                   ok and cleared.preference("modeling", "View", "Orientation") == ribbon_layout.AUTO
                   and after == ribbon_layout.FULL,
                   f"{self._persist}, after rebuild: {rebuilt}, file: {reread.data}, back to Automatic: {after}")

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
        from . import config
        if self.shell.cfg.get("theme", "nx") == "nx":
            self.check("NX theme applied over FreeCAD's light theme", self.shell.theme_active() and len(base) > 10000,
                       f"base {len(base)} chars")
        else:      # a run with "theme": "none" in config/nxstyle.json: proves the settings file is read
            self.check("theme off as set in nxstyle.json", not self.shell.theme_active(), config.user_file())
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

    def s_navigation_label(self):
        """The status bar names the mouse handling in use, not only FreeCAD's base style under it."""
        from . import prefs
        self.shell.label_navigation()
        bar = Gui.getMainWindow().statusBar()
        texts = [w.text().strip() for w in bar.findChildren(QtWidgets.QAbstractButton) +
                 bar.findChildren(QtWidgets.QLabel) if w.isVisible()]
        if prefs.uses_own_navigation(self.shell.cfg):
            self.check("status bar names NXStyle's mouse handling, not just FreeCAD's base style",
                       self.shell.NAV_LABEL in texts and "Blender" not in texts, texts)

    def s_mouse(self):
        self.s_navigation_label()
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
            self.skip("Ctrl+Shift+B key press inverts visibility", f"QtTest unavailable: {e}")
        from . import showhide
        dlg = showhide.show_dialog()
        rows = dlg.grid.rowCount()
        self.shot("06_show_hide.png", dlg)
        dlg.close()
        self.check("Show and Hide dialog lists types", rows >= 3, f"{rows} rows")

    def s_finder(self):
        hits = self.shell.finder.find("Edge Blend")
        self.check("Command Finder finds NX names", "NXStyle_EdgeBlend" in hits, hits[:5])
        self.finder_type("Enter")
        from .tutorial import qtest
        qtest().keyClick(self.shell.finder, Qt.Key_Return)
        self._finder_popup_after = self.shell.finder.completer.popup().isVisible()

    def finder_type(self, how):
        """Type a harmless command's name into the Command Finder so its completer popup opens, and count
        the commands it runs."""
        from .tutorial import qtest
        from .finder import ROLE_CMD
        cf = self.shell.finder
        title = next((cf.model.item(r).text().split("  —  ")[0] for r in range(cf.model.rowCount())
                      if cf.model.item(r).data(ROLE_CMD) == "Std_ViewFitAll"), "Fit all")
        self._finder_runs = []
        self._finder_on_run = cf.on_run
        cf.on_run = self._finder_runs.append
        cf.setFocus()
        cf.clear()
        qtest().keyClicks(cf, title)
        QtWidgets.QApplication.processEvents()
        self._finder_how = how
        self._finder_popup_before = cf.completer.popup().isVisible()

    def s_finder_check(self):
        cf = self.shell.finder
        cf.on_run = self._finder_on_run
        p = QtWidgets.QApplication.activePopupWidget()
        # Enter: also right after the key, before the command's timers ran
        after = cf.completer.popup().isVisible() or (self._finder_how == "Enter" and self._finder_popup_after)
        self.nav().widget.setFocus()
        self.check(f"Command Finder: {self._finder_how} runs the command once and closes the popup",
                   self._finder_popup_before and not after and len(self._finder_runs) == 1,
                   f"popup before {self._finder_popup_before}, after {after}; ran {self._finder_runs}; "
                   f"active popup {type(p).__name__ if p is not None else None}")

    def s_finder_click(self):
        from .tutorial import qtest
        self.finder_type("click")
        popup = self.shell.finder.completer.popup()
        rect = popup.visualRect(popup.model().index(0, 0))
        qtest().mouseClick(popup.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())

    def s_repeat(self):
        doc = App.ActiveDocument
        n0 = len(doc.Objects)
        Gui.Command.get("Part_Cylinder").getAction()[0].trigger()
        self.info["last_command"] = commands.last_command["name"]
        Gui.runCommand("NXStyle_RepeatCommand")
        doc.recompute()
        self.check("Repeat Command (Quick Access Toolbar; F4 is Touch Mode, as in NXtips)", len(doc.Objects) == n0 + 2 and commands.last_command["name"] == "Part_Cylinder",
                   f"objects {n0} -> {len(doc.Objects)}, last={commands.last_command['name']}")

    def s_sketch_enter(self):
        self.ribbon_follows_commands("Modeling")
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
        rows = self.tab_buttons("Sketch")
        self.info["Sketch tab buttons (label, command, enabled, active, actions)"] = rows
        greyed = [(label, cmd, n) for label, cmd, on, active, n in rows if active and not on]
        self.check("every Sketch-tab button whose FreeCAD command is active is enabled (group commands too)",
                   rows and not greyed, greyed)
        tested, bad = self.press_keys("sketch")
        self.check(f"sketch key presses reach their commands through Qt's shortcut dispatch ({tested} keys; "
                   "dispatch only)", tested and not bad, bad)

    def s_profile(self):
        """Profile (Z) with real key and mouse events: a click on the first point closes the outline, and one
        MB2 ends the tool, also when the profile was left open (FreeCAD's Esc needs two presses then)."""
        from pivy import coin
        from . import sketch_ui
        from .tutorial import qtest, settle_view
        sk = sketch_ui.edited_sketch()
        if sk is None:
            self.check("Profile: the last click on the first point closes it", False, "no sketch in edit")
            return
        view, f = self.view(), self.nav()
        w = f.widget
        settled = settle_view(view)            # FreeCAD turns the view to the sketch with an animation
        cam = view.getCameraNode()
        d = cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
        g = sk.getGlobalPlacement().multVec(App.Vector(40, 10, 0))
        cam.position.setValue(coin.SbVec3f(g.x, g.y, g.z) - d * cam.focalDistance.getValue())
        if hasattr(cam, "height"):
            cam.height.setValue(160)
        QtWidgets.QApplication.processEvents()
        dpr = w.devicePixelRatioF() if hasattr(w, "devicePixelRatioF") else 1.0

        def at(x, y):
            sx, sy = view.getPointOnViewport(sk.getGlobalPlacement().multVec(App.Vector(x, y, 0)))
            return QtCore.QPoint(int(round(sx / dpr)), int(round(w.height() - sy / dpr)))

        def click(p, button=Qt.LeftButton):
            self.send(f, QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton)
            QtWidgets.QApplication.processEvents()
            self.send(f, QtCore.QEvent.MouseButtonPress, p, button, button)
            self.send(f, QtCore.QEvent.MouseButtonRelease, p, button, Qt.NoButton)
            QtWidgets.QApplication.processEvents()

        def running(p):
            self.send(f, QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton)
            QtWidgets.QApplication.processEvents()
            return f.sketch_tool_active()

        def profile(pts):
            mw = Gui.getMainWindow()
            app = QtWidgets.QApplication.instance()
            if app.activeWindow() is None and hasattr(app, "setActiveWindow"):
                app.setActiveWindow(mw)
            w.setFocus()
            g0, c0 = len(sk.Geometry), len(sk.Constraints)
            qtest().keyClick(w, Qt.Key_Z)
            QtWidgets.QApplication.processEvents()
            started = f.sketch_tool_active()
            for x, y in pts:
                click(at(x, y))
            away = at(-25, 60)
            click(away, Qt.MiddleButton)
            return started, not running(away), g0, sk.Constraints[c0:]

        # clear of the axes: a line from the origin along the X axis gets no Horizontal, FreeCAD finds it redundant
        started, ended, g0, new = profile([(5, 5), (45, 5), (45, 35), (5, 35), (5, 5)])
        closing = [c for c in new if c.Type == "Coincident" and {(c.First, c.FirstPos), (c.Second, c.SecondPos)}
                   == {(g0 + 3, 2), (g0, 1)}]
        first_h = any(c.Type == "Horizontal" and c.First == g0 for c in new)
        self.check("Profile: the last click on the first point closes it; the first line gets Horizontal; MB2 "
                   "ends the tool", started and ended and len(sk.Geometry) == g0 + 4 and closing and first_h,
                   f"started {started}, ended {ended}, {len(sk.Geometry) - g0} lines, closed {bool(closing)}, first "
                   f"Horizontal {first_h}; view settled after {settled} s")
        started, ended, g0, new = profile([(60, 0), (90, 0), (90, 25)])
        self.check("Profile left open: one MB2 still ends the tool", started and ended and len(sk.Geometry) == g0 + 2,
                   f"started {started}, ended {ended}, {len(sk.Geometry) - g0} lines")
        sk.deleteAllGeometry()
        App.ActiveDocument.recompute()

    def s_sketch_trim(self):
        """Quick Trim (T) keeps a line tangent where it ends on the trimmed circle. Tutorial AK's outline, smaller:
        a circle with a side held as Profile holds it (end on the circle plus Tangent) and one held as Tangent
        holds it (the end tangent there), trimmed between two lines. FreeCAD's trim alone drops such tangencies by
        a rounding error's sign (the control, NX-Style's guard off); with the guard, all stay, one Undo."""
        import math
        import Part
        import Sketcher
        from pivy import coin
        from . import sketch_ui
        from .tutorial import qtest, settle_view
        name = "Quick Trim keeps the sides tangent to the trimmed circle; one Undo takes the trim back"
        sk = sketch_ui.edited_sketch()
        if sk is None:
            self.check(name, False, "no sketch in edit")
            return
        doc, V = sk.Document, App.Vector
        r, length, h = 20.0, 60.0, 3.0
        view, f = self.view(), self.nav()
        w = f.widget
        settle_view(view)
        cam = view.getCameraNode()
        d = cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
        g = sk.getGlobalPlacement().multVec(V(20, 0, 0))
        cam.position.setValue(coin.SbVec3f(g.x, g.y, g.z) - d * cam.focalDistance.getValue())
        if hasattr(cam, "height"):
            cam.height.setValue(110)
        QtWidgets.QApplication.processEvents()
        dpr = w.devicePixelRatioF() if hasattr(w, "devicePixelRatioF") else 1.0

        def at(x, y):
            sx, sy = view.getPointOnViewport(sk.getGlobalPlacement().multVec(V(x, y, 0)))
            return QtCore.QPoint(int(round(sx / dpr)), int(round(w.height() - sy / dpr)))

        def click(p, button=Qt.LeftButton):
            self.send(f, QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton)
            QtWidgets.QApplication.processEvents()
            self.send(f, QtCore.QEvent.MouseButtonPress, p, button, button)
            self.send(f, QtCore.QEvent.MouseButtonRelease, p, button, Qt.NoButton)
            QtWidgets.QApplication.processEvents()

        def running(p):
            self.send(f, QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton)
            QtWidgets.QApplication.processEvents()
            return f.sketch_tool_active()

        def outline():
            """Curves 0 circle, 1 top, 2 right, 3 bottom, 4 and 5 the slot; the ends start right of the contact."""
            sk.deleteAllGeometry()
            c = sk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), r + 0.3), False)
            top = sk.addGeometry(Part.LineSegment(V(0.3, r + 0.2, 0), V(length, r, 0)), False)
            right = sk.addGeometry(Part.LineSegment(V(length, r, 0), V(length, -r, 0)), False)
            bot = sk.addGeometry(Part.LineSegment(V(length, -r, 0), V(0.3, -r - 0.2, 0)), False)
            a = math.sqrt(r * r - h * h)
            slot = [sk.addGeometry(Part.LineSegment(V(a, y, 0), V(length, y, 0)), False) for y in (h, -h)]
            k = [("Coincident", c, 3, -1, 1), ("Diameter", c, 2 * r), ("Coincident", top, 2, right, 1),
                 ("Coincident", right, 2, bot, 1), ("Horizontal", top), ("Vertical", right), ("Horizontal", bot),
                 ("PointOnObject", top, 1, c), ("Tangent", top, c),        # as Profile's clicks hold it
                 ("Tangent", bot, 2, c),                                   # as Tangent folds that pair
                 ("DistanceX", -1, 1, top, 2, length)]
            for s, y in zip(slot, (h, -h)):
                k += [("Horizontal", s), ("PointOnObject", s, 1, c), ("PointOnObject", s, 2, right),
                      ("DistanceY", -1, 1, s, 1, y)]
            for args in k:
                sk.addConstraint(Sketcher.Constraint(*args))
            doc.recompute()
            return c, top, bot

        def tangent(g):
            return any(k.Type == "Tangent" and g in (k.First, k.Second) for k in sk.Constraints)

        def point_pickable():
            """FreeCAD's trim gate takes edges only: a sketch point is refused until the tool has ended."""
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(doc.Name, sk.Name, "Vertex1")
            ok = any("Vertex1" in s.SubElementNames for s in Gui.Selection.getSelectionEx(doc.Name))
            Gui.Selection.clearSelection()
            return ok

        def trim(guarded, cut=True):
            sketch_ui.trim_guard.enabled = guarded
            sketch_ui.trim_guard.last = None
            c, top, bot = outline()
            n0 = len(sk.Constraints)
            w.setFocus()
            qtest().keyClick(w, Qt.Key_T)
            QtWidgets.QApplication.processEvents()
            if cut:
                a = math.radians(4)
                click(at(r * math.cos(a), r * math.sin(a)))
                qtest().qWait(100)                  # the guard runs once FreeCAD's tool has committed
            away = at(-15, 30)
            click(away, Qt.MiddleButton)            # the hover before it puts FreeCAD's cursor in place of the tool's
            point = point_pickable()
            ended = not running(away)
            for _ in range(3):                      # leave no tool running for the next checks
                if not running(away):
                    break
                qtest().keyClick(w, Qt.Key_Escape)
                QtWidgets.QApplication.processEvents()
            Gui.Selection.clearSelection()
            arcs = [i for i, x in enumerate(sk.Geometry) if "ArcOfCircle" in x.TypeId]
            solved = sk.solve() == 0 and not list(getattr(sk, "MalformedConstraints", []))
            return {"arcs": len(arcs), "top": tangent(top), "bottom": tangent(bot), "n0": n0, "ended": ended,
                    "point": point, "dof": getattr(sk, "DoF", None), "solved": solved,
                    "guard": sketch_ui.trim_guard.last}

        try:
            idle = trim(True, cut=False)
            control = trim(False)
            got = trim(True)
            after = len(sk.Constraints)
            doc.undo()
            undone = (len(sk.Constraints), any("ArcOfCircle" in x.TypeId for x in sk.Geometry))
            doc.redo()
            redone = (len(sk.Constraints), tangent(1), tangent(3))
        finally:
            sketch_ui.trim_guard.enabled = True
            sk.deleteAllGeometry()
            doc.recompute()
        dropped = (not control["top"]) + (not control["bottom"])
        self.info["Quick Trim, FreeCAD alone (control)"] = control
        self.info["Quick Trim, NX-Style"] = got
        ok = got["arcs"] == 1 and got["top"] and got["bottom"] and got["solved"] and str(got["dof"]) == "0" \
            and undone == (got["n0"], False) and redone == (after, True, True)
        self.check(name, ok, f"NX-Style: MB2 ended the tool {got['ended']} (control {control['ended']}); tangent top "
                   f"{got['top']}, bottom {got['bottom']}, DoF {got['dof']}, put back "
                   f"{(got['guard'] or {}).get('put back')}; undo {undone} (constraints, arc left), redo {redone}; "
                   f"control, FreeCAD alone: {dropped} of 2 tangencies dropped"
                   + ("" if dropped else " (the control did not reach the defect: FreeCAD may have fixed its trim)"))
        runs = {"no trim": idle, "trim, guard off": control, "trim": got}
        self.check("MB2 ends Quick Trim and its edges-only selection gate: a sketch point can be picked after it",
                   all(x["ended"] and x["point"] for x in runs.values()),
                   "; ".join(f"{k}: ended {x['ended']}, point pickable {x['point']}" for k, x in runs.items()))

    def s_sketch_constraints(self):
        """Point on Curve, Collinear and NX's Geometric Constraints gallery (C), run from the Sketch tab."""
        import Part
        import Sketcher
        from . import sketch_ui
        from .ribbon import CommandButton, command_actions, is_enabled, trigger
        from .tutorial import qtest
        sk = sketch_ui.edited_sketch()
        if sk is None:
            self.check("Sketch tab: Point on Curve, Collinear, Geometric Constraints", False, "no sketch in edit")
            return
        doc, V = sk.Document, App.Vector
        buttons = {b.nx_label: b.command for b in self.shell.ribbon.findChildren(CommandButton)}
        want = {"Point on Curve": "Sketcher_ConstrainPointOnObject", "Collinear": "NXStyle_SketchCollinear",
                "Geometric Constraints": "NXStyle_GeometricConstraints"}
        self.check("Sketch tab: Point on Curve, Collinear, Geometric Constraints buttons",
                   all(buttons.get(k) == v for k, v in want.items()), {k: buttons.get(k) for k in want})
        base = len(sk.Geometry)
        sk.addGeometry([Part.LineSegment(V(0, 0, 0), V(20, 0, 0)), Part.LineSegment(V(30, 3, 0), V(50, 3, 0)),
                        Part.LineSegment(V(0, 10, 0), V(20, 14, 0)), Part.LineSegment(V(30, 20, 0), V(50, 30, 0)),
                        Part.LineSegment(V(0, 40, 0), V(10, 45, 0))], False)
        for i in (0, 1):
            sk.addConstraint(Sketcher.Constraint("Horizontal", base + i))
        doc.recompute()

        def vertex(geo, pos):
            for i in range(4 * len(sk.Geometry)):
                try:
                    if sk.getGeoVertexIndex(i) == (geo, pos):
                        return f"Vertex{i + 1}"
                except Exception:
                    break
            return None

        def run(cmd, subs):
            n = len(sk.Constraints)
            Gui.Selection.clearSelection()
            for s in subs:
                Gui.Selection.addSelection(doc.Name, sk.Name, s)
            QtWidgets.QApplication.processEvents()
            for _ in range(20):           # FreeCAD refreshes the actions' state on a timer, as a user waits
                if not command_actions(cmd) or is_enabled(cmd):
                    break
                qtest().qWait(100)
            trigger(cmd)
            QtWidgets.QApplication.processEvents()
            doc.recompute()
            return sk.Constraints[n:]

        new = run("Sketcher_ConstrainPointOnObject", [vertex(base + 4, 1), f"Edge{base + 3}"])
        g4 = sk.Geometry[base + 4].StartPoint
        on = sk.Geometry[base + 2].toShape().distToShape(Part.Vertex(g4))[0]
        self.check("Point on Curve puts a point on a curve", [c.Type for c in new] == ["PointOnObject"] and on < 1e-6,
                   f"{[c.Type for c in new]}; {on:.2e} mm off")
        new = run("NXStyle_SketchCollinear", [f"Edge{base + 2}", f"Edge{base + 1}"])
        off, ang = sketch_ui.collinear_report(sk, base, base + 1)
        self.check("Collinear on two horizontal lines: one point on the other line, nothing redundant",
                   len(new) == 1 and sk.solve() == 0 and off < 1e-6, f"{[c.Type for c in new]}; {off:.2e} mm apart")
        new = run("NXStyle_SketchCollinear", [f"Edge{base + 4}", f"Edge{base + 3}"])
        off, ang = sketch_ui.collinear_report(sk, base + 2, base + 3)
        added = len(new)
        doc.undo()
        undone = sum(1 for c in sk.Constraints if c.First == base + 3 and c.Type == "PointOnObject")
        doc.redo()
        again = run("NXStyle_SketchCollinear", [f"Edge{base + 4}", f"Edge{base + 3}"])
        self.check("Collinear on two free lines: both ends on the other line, one undo step, nothing added twice",
                   added == 2 and sk.solve() == 0 and off < 1e-6 and ang < 1e-6 and undone == 0 and not again,
                   f"added {added}, {off:.2e} mm apart, {ang:.2e} deg; after undo {undone} left; again {len(again)}")
        Gui.Selection.clearSelection()
        mw = Gui.getMainWindow()
        app = QtWidgets.QApplication.instance()
        if app.activeWindow() is None and hasattr(app, "setActiveWindow"):
            app.setActiveWindow(mw)
        self.nav().widget.setFocus()
        sketch_ui.last_gallery = None
        for _ in range(20):
            if is_enabled("NXStyle_GeometricConstraints"):
                break
            qtest().qWait(100)
        qtest().keyClick(self.nav().widget, Qt.Key_C)
        QtWidgets.QApplication.processEvents()
        menu = sketch_ui.last_gallery
        labels = [a.text() for a in menu.actions()] if menu is not None else []
        shown = menu is not None and menu.isVisible()
        if menu is not None:
            menu.close()
        self.check("C opens NX's Geometric Constraints gallery", shown and labels[:3] == ["Coincident", "Point on Curve",
                   "Tangent"] and "Collinear" in labels, labels)
        cf = self.shell.finder
        cf.rebuild()
        hits = cf.find("Collinear") + cf.find("Point on Curve")
        self.check("Command Finder finds Collinear and Point on Curve",
                   {"NXStyle_SketchCollinear", "Sketcher_ConstrainPointOnObject"} <= set(hits), hits[:6])
        sk.deleteAllGeometry()
        doc.recompute()

    def s_sketch_point_typed(self):
        """NX's sketch Point takes typed XC/YC: NX-Style's profile turns on FreeCAD's positional on-view fields, so
        typing 298.45 and 152.4 makes a point at exactly (298.45, 152.4) mm (AH's point at 11.75, 6 in)."""
        from . import prefs, sketch_ui
        from .ribbon import trigger
        from .tutorial import qtest
        sk = sketch_ui.edited_sketch()
        ovp = App.ParamGet(prefs.SKETCHER_TOOLS).GetInt("OnViewParameterVisibility", 1)
        if sk is None:
            self.check("sketch Point at typed XC, YC", False, "no sketch in edit")
            return
        f = self.nav()
        w = f.widget
        n0 = len(sk.Geometry)
        Gui.Selection.clearSelection()
        w.setFocus()
        trigger("Sketcher_CreatePoint")
        QtWidgets.QApplication.processEvents()
        p = QtCore.QPoint(w.width() // 2 + 37, w.height() // 2 - 23)
        self.send(f, QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton)
        qtest().qWait(200)
        texts = [x.text() for x in sketch_ui.on_view_fields(w)]
        fields = sketch_ui.xy_fields(sk, w, p) or []          # FreeCAD lists the fields in no fixed order
        cursor = tuple(round(c, 2) for c in sketch_ui.cursor_on_sketch(sk, w, p))
        want = (298.45, 152.4)
        for x, v in zip(fields, want):
            x.setFocus()
            x.lineEdit().selectAll()
            qtest().keyClicks(x.lineEdit(), f"{v:.6g}".replace(".", x.locale().decimalPoint()))
            qtest().keyClick(x.lineEdit(), Qt.Key_Return)
            qtest().qWait(150)
        if len(sk.Geometry) == n0 and len(fields) >= 2:      # the typed values are locked: a click confirms them
            self.send(f, QtCore.QEvent.MouseButtonPress, p, Qt.LeftButton, Qt.LeftButton)
            self.send(f, QtCore.QEvent.MouseButtonRelease, p, Qt.LeftButton, Qt.NoButton)
            QtWidgets.QApplication.processEvents()
        self.send(f, QtCore.QEvent.MouseButtonPress, p, Qt.MiddleButton, Qt.MiddleButton)    # MB2 ends the tool
        self.send(f, QtCore.QEvent.MouseButtonRelease, p, Qt.MiddleButton, Qt.NoButton)
        QtWidgets.QApplication.processEvents()
        sk.Document.recompute()
        made = [g for g in range(n0, len(sk.Geometry)) if "Point" in sk.Geometry[g].TypeId]
        q = sk.getPoint(made[0], 1) if made else None
        exact = q is not None and abs(q.x - want[0]) < 1e-9 and abs(q.y - want[1]) < 1e-9
        # FreeCAD keeps typed coordinates as distances from the axes
        held = sorted((c.Type, round(c.Value, 6)) for c in sk.Constraints if made and c.First == made[0])
        self.check("sketch Point at typed XC, YC: positional on-view fields on (NX's input boxes), 298.45 and 152.4 "
                   "typed make the point exactly there", ovp == 2 and len(fields) >= 2 and len(made) == 1 and exact,
                   f"OnViewParameterVisibility {ovp}; fields {texts} with the pointer at {cursor}; points made "
                   f"{len(made)}; at "
                   f"{(q.x, q.y) if q is not None else None}; constraints on it {held}")
        sk.deleteAllGeometry()
        sk.Document.recompute()

    def s_sketch_linear_dimension(self):
        """NX's Linear Dimension (Sketch tab, Constraints): Horizontal and Vertical between the origin and a point
        make FreeCAD's horizontal and vertical distances."""
        import Part
        from . import sketch_ui
        from .ribbon import DropdownButton, clean_text
        from .tutorial import qtest
        sk = sketch_ui.edited_sketch()
        drop = next((b for b in self.shell.ribbon.findChildren(DropdownButton) if b.text() == "Linear Dimension"),
                    None)
        entries = {clean_text(a.text()): a for a in drop.menu().actions()} if drop is not None else {}
        if sk is None or drop is None:
            self.check("Linear Dimension > Horizontal / Vertical on the Sketch tab", False,
                       f"sketch {sk is not None}, drop-down entries {list(entries)}")
            return
        doc = sk.Document
        g = sk.addGeometry(Part.Point(App.Vector(298.45, 152.4, 0)))      # a free point
        doc.recompute()
        p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Sketcher")
        dialog = p.GetBool("ShowDialogOnDistanceConstraint", True)
        p.SetBool("ShowDialogOnDistanceConstraint", False)      # no modal datum dialog: the value is the distance
        vertex = next(f"Vertex{i + 1}" for i in range(4 * len(sk.Geometry)) if sk.getGeoVertexIndex(i) == (g, 1))
        made = {}
        try:
            for label in ("Horizontal", "Vertical"):
                n = len(sk.Constraints)
                Gui.Selection.clearSelection()
                for s in ("RootPoint", vertex):
                    Gui.Selection.addSelection(doc.Name, sk.Name, s)
                QtWidgets.QApplication.processEvents()
                act = entries.get(label)
                for _ in range(20):            # FreeCAD refreshes the actions' state on a timer
                    if act is None or act.isEnabled():
                        break
                    qtest().qWait(100)
                if act is not None:
                    act.trigger()
                QtWidgets.QApplication.processEvents()
                doc.recompute()
                made[label] = [(c.Type, round(c.Value, 6)) for c in sk.Constraints[n:]]
        finally:
            p.SetBool("ShowDialogOnDistanceConstraint", dialog)
        Gui.Selection.clearSelection()
        self._linear_dims = [i for i, c in enumerate(sk.Constraints) if c.Type in ("DistanceX", "DistanceY")]
        self.check("Linear Dimension > Horizontal / Vertical (Sketch tab) make FreeCAD's horizontal and vertical "
                   "distances", list(entries) == ["Horizontal", "Vertical", "Point-to-Point"]
                   and made == {"Horizontal": [("DistanceX", 298.45)], "Vertical": [("DistanceY", 152.4)]},
                   f"entries {list(entries)}; made {made}")

    def s_sketch_hide(self):
        """NX's Hide for sketch dimensions: Ctrl+B, and MB3 > Hide (FreeCAD's sketch MB3 menu), move the picked
        dimensions to FreeCAD's virtual space; Show All (Ctrl+Shift+U) brings them back; the sketch stays shown."""
        from . import sketch_ui
        from .tutorial import qtest
        sk = sketch_ui.edited_sketch()
        dims = getattr(self, "_linear_dims", [])
        if sk is None or len(dims) < 2:
            self.check("Hide (Ctrl+B) on sketch dimensions", False, f"dimensions {dims}")
            return
        doc, f = sk.Document, self.nav()
        w = f.widget

        def pick(ids):
            Gui.Selection.clearSelection()
            for i in ids:
                Gui.Selection.addSelection(doc.Name, sk.Name, f"Constraint{i + 1}")
            QtWidgets.QApplication.processEvents()

        def key(k, mods=Qt.NoModifier):
            app = QtWidgets.QApplication.instance()
            if app.activeWindow() is None and hasattr(app, "setActiveWindow"):
                app.setActiveWindow(Gui.getMainWindow())
            w.setFocus()
            for _ in range(10):                # wait for FreeCAD's command state refresh, as a user would
                qtest().qWait(100)
            qtest().keyClick(w, k, mods)
            QtWidgets.QApplication.processEvents()

        # FreeCAD hides the edited sketch object itself (its visibility automation): Hide must leave that alone
        before = sk.ViewObject.Visibility
        pick(dims[:1])
        key(Qt.Key_B, Qt.ControlModifier)
        by_key = [bool(sk.getVirtualSpace(i)) for i in dims]
        after_key = sk.ViewObject.Visibility
        # MB3 on empty space with the other dimension picked: FreeCAD's sketch menu, with NX-Style's Hide
        pick(dims[1:2])
        seen = {}

        def read_menu():
            m = QtWidgets.QApplication.activePopupWidget()
            if isinstance(m, QtWidgets.QMenu):
                seen["items"] = [a.text().replace("&", "") for a in m.actions() if a.text()]
                hide = next((a for a in m.actions() if a.text().replace("&", "") == "Hide"), None)
                seen["hide"] = hide is not None
                if hide is not None:
                    m.close()
                    hide.trigger()
                    seen["Hide changed"] = sketch_ui.COMMANDS["NXStyle_Hide"].last
                    return
                m.close()
            elif seen.setdefault("tries", 0) < 20:
                seen["tries"] += 1
                QtCore.QTimer.singleShot(100, read_menu)
        QtCore.QTimer.singleShot(150, read_menu)
        corner = QtCore.QPoint(25, w.height() - 25)
        self.send(f, QtCore.QEvent.MouseMove, corner, Qt.NoButton, Qt.NoButton)
        self.send(f, QtCore.QEvent.MouseButtonPress, corner, Qt.RightButton, Qt.RightButton)
        self.send(f, QtCore.QEvent.MouseButtonRelease, corner, Qt.RightButton, Qt.NoButton)
        for _ in range(30):
            if "items" in seen:
                break
            qtest().qWait(100)
        QtWidgets.QApplication.processEvents()
        by_menu = [bool(sk.getVirtualSpace(i)) for i in dims]
        vis = (before, after_key, sk.ViewObject.Visibility)
        self.check("Hide on sketch dimensions: Ctrl+B and MB3 > Hide put them in FreeCAD's virtual space; the sketch "
                   "object's own visibility is untouched", by_key == [True, False] and by_menu == [True, True]
                   and len(set(vis)) == 1 and seen.get("Hide changed", {}).get("others") == [],
                   f"after Ctrl+B {by_key}; MB3 menu {seen.get('items')}; after MB3 > Hide {by_menu}; sketch "
                   f"visibility before / after Ctrl+B / after MB3 {vis}; last Hide {seen.get('Hide changed')}")
        doc.undo()
        undone = [bool(sk.getVirtualSpace(i)) for i in dims]
        key(Qt.Key_U, Qt.ControlModifier | Qt.ShiftModifier)
        back = [bool(sk.getVirtualSpace(i)) for i in dims]
        self.check("Undo takes one Hide back; Show All (Ctrl+Shift+U) shows the sketch's hidden dimensions",
                   undone == [True, False] and back == [False, False], f"after undo {undone}; after Show All {back}")
        sk.deleteAllGeometry()
        doc.recompute()

    def s_sketch_datum(self):
        """A dimension typed as 28.095 in FreeCAD's Insert Length dialog is stored as 28.095, not cut to the
        display decimals (NX keeps what you type); opened again and OK'd, it stays 28.095."""
        import Part
        from . import sketch_ui
        sk = sketch_ui.edited_sketch()
        if sk is None:
            self.check("a sketch dimension typed as 28.095 is stored as 28.095", False, "no sketch in edit")
            return
        doc = sk.Document
        # 20 mm long: the new dimension's field starts at 20, so the typed 28.095 itself must widen it
        geo = sk.addGeometry(Part.LineSegment(App.Vector(0, 70, 0), App.Vector(20, 70, 0)), False)
        doc.recompute()
        n = len(sk.Constraints)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, sk.Name, f"Edge{geo + 1}")
        QtWidgets.QApplication.processEvents()
        for cmd, typed in (("Sketcher_ConstrainDistance", "28.095"), ("Sketcher_ChangeDimensionConstraint", None)):
            seen = self.datum_dialog_answer(cmd, typed)
            doc.recompute()
            made = [i for i, c in enumerate(sk.Constraints) if i >= n and c.Type == "Distance"]
            stored = sk.Constraints[made[0]].Value if made else None
            length = sk.Geometry[geo].length()
            self.check(f"a sketch dimension {'typed as 28.095 in' if typed else 'of 28.095 opened again in'} the "
                       f"Insert Length dialog (focus in the field, then OK) is stored as 28.095",
                       seen.get("focus") is True and stored is not None
                       and abs(stored - 28.095) < 1e-9 and abs(length - 28.095) < 1e-9,
                       f"dialog {seen.get('title')!r}, field focused {seen.get('focus')}, showed {seen.get('field')!r} "
                       f"(field value {seen.get('raw')}); stored {stored!r}; line {length!r} mm")
            if not made:
                break
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(doc.Name, sk.Name, f"Constraint{made[0] + 1}")
            QtWidgets.QApplication.processEvents()
        self.info["precise input (nxstyle/precise_input.py)"] = getattr(self.shell, "precise_input", None) and \
            self.shell.precise_input.trace
        sk.deleteAllGeometry()
        doc.recompute()
        Gui.Selection.clearSelection()

    def datum_dialog_answer(self, cmd, typed):
        """Run a sketcher command that opens the Insert Length dialog; type into its field (if typed), OK."""
        from .ribbon import is_enabled, trigger
        from .tutorial import qtest
        seen = {}

        def answer():
            dlg = QtWidgets.QApplication.activeModalWidget()
            if dlg is None:
                if seen.setdefault("polls", 0) < 50:
                    seen["polls"] += 1
                    QtCore.QTimer.singleShot(100, answer)
                return
            spins = dlg.findChildren(QtWidgets.QAbstractSpinBox)
            if not spins:
                dlg.reject()
                return
            ed = spins[0].lineEdit()
            # FreeCAD rounds the value when the field loses focus: without focus the check would prove nothing
            dlg.activateWindow()
            app = QtWidgets.QApplication.instance()
            if hasattr(app, "setActiveWindow"):
                app.setActiveWindow(dlg)
            spins[0].setFocus()
            QtWidgets.QApplication.processEvents()
            if typed is not None:
                ed.selectAll()
                qtest().keyClicks(ed, typed.replace(".", spins[0].locale().decimalPoint()))
                QtWidgets.QApplication.processEvents()
            seen.update(title=dlg.windowTitle(), focus=spins[0].hasFocus(), field=ed.text(),
                        raw=spins[0].property("rawValue"))
            for box in dlg.findChildren(QtWidgets.QDialogButtonBox):
                b = box.button(QtWidgets.QDialogButtonBox.Ok)
                if b is not None:
                    b.click()
                    return
            dlg.reject()

        for _ in range(20):
            if is_enabled(cmd):
                break
            qtest().qWait(100)
        QtCore.QTimer.singleShot(100, answer)
        trigger(cmd)
        QtWidgets.QApplication.processEvents()
        return seen

    def tab_buttons(self, tab=None):
        """(label, command, enabled, FreeCAD isActive, number of QActions) of a ribbon tab's (or every tab's) command
        buttons; add-on actions (ribbon.HOST_ACTIONS) keep their own state and are left out."""
        from .ribbon import HOST_ACTIONS, CommandButton, command_actions
        r = self.shell.ribbon
        rows = []
        for i in range(r.stack.count()):
            if tab is not None and r.tabs.tabText(i) != tab:
                continue
            for b in r.stack.widget(i).findChildren(CommandButton):
                if b.command in HOST_ACTIONS:
                    continue
                try:
                    active = bool(Gui.Command.get(b.command).isActive())
                except Exception:          # a group's sub-action named directly: no command of its own
                    active = None
                rows.append((b.nx_label, b.command, b.isEnabled(), active, len(command_actions(b.command))))
        return rows

    def ribbon_follows_commands(self, app):
        """Every button of the application's ribbon is enabled when its FreeCAD command is active (no task dialog
        open: FreeCAD then disables document commands on its own)."""
        rows = self.tab_buttons()
        greyed = [(label, cmd, n) for label, cmd, on, active, n in rows if active and not on]
        self.check(f"{app} ribbon: every button whose FreeCAD command is active is enabled ({len(rows)} buttons)",
                   rows and not greyed and not Gui.Control.activeDialog(), greyed)

    def s_sketch_arc(self):
        """An arc in the sketch, selected, for the Radius / Diameter button (a FreeCAD group command)."""
        import Part
        from . import sketch_ui
        sk = sketch_ui.edited_sketch()
        self._radius_sketch = sk
        geo = sk.addGeometry(Part.ArcOfCircle(Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 20), 0.0, 2.0))
        App.ActiveDocument.recompute()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, f"Edge{geo + 1}")

    def s_sketch_radius(self):
        from .ribbon import CommandButton
        from .tutorial import qtest
        sk = self._radius_sketch
        self._radius_before = len(sk.Constraints)
        p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Sketcher")
        self._radius_dialog = p.GetBool("ShowDialogOnDistanceConstraint", True)
        p.SetBool("ShowDialogOnDistanceConstraint", False)     # no modal datum dialog in the self-test
        r = self.shell.ribbon
        r.select("Sketch")
        b = next((w for w in r.stack.currentWidget().findChildren(CommandButton) if w.nx_label == "Radius / Diameter"),
                 None)
        self._radius_button = (b.command, b.isEnabled(), b.menu() is not None) if b is not None else None
        if b is None:
            return
        how, _via = r.reach(b)
        if how in ("group", "overflow"):         # a narrow window collapses the group: its menu runs the button
            act = r.menu_action(b)
            if act is not None:
                act.trigger()
        else:
            qtest().mouseClick(b, Qt.LeftButton)
        self._radius_how = how

    def s_sketch_radius_check(self):
        sk = self._radius_sketch
        App.ParamGet("User parameter:BaseApp/Preferences/Mod/Sketcher").SetBool(
            "ShowDialogOnDistanceConstraint", self._radius_dialog)
        App.ActiveDocument.recompute()
        made = [c.Type for c in sk.Constraints[self._radius_before:]]
        self.check("Radius / Diameter clicked on a selected arc makes a Radius constraint (group command button)",
                   made == ["Radius"], f"button (command, enabled, drop-down) {self._radius_button}; "
                   f"reached {getattr(self, '_radius_how', None)}; made {made}")
        Gui.Selection.clearSelection()

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
        self.ribbon_follows_commands("Drafting")
        self.shot("03_drafting.png")
        self.layout_matrix("Drafting")

    def tasks_to_front(self):
        """Put FreeCAD's Tasks panel (the Dialog tab) in front, as FreeCAD itself may do; returns the front tab."""
        Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Tasks").raise_()
        QtWidgets.QApplication.processEvents()
        return self.shell.current_left_tab()

    def s_switch_dialog_open(self):
        """Negative control: with a feature dialog open, switching applications leaves the Dialog tab in front."""
        class Panel:
            def __init__(self):
                self.form = QtWidgets.QLabel("NXStyle smoke-test dialog")

            def reject(self):
                Gui.Control.closeDialog()
                return True

        Gui.Control.showDialog(Panel())
        self.info["front tab before switching, dialog open"] = self.tasks_to_front()
        self.shell.switch_application("modeling")

    def s_switch_dialog_check(self):
        tab = self.shell.current_left_tab()
        self.check("Dialog stays in front over an application switch while a dialog is open",
                   bool(Gui.Control.activeDialog()) and tab == "Dialog",
                   {"before": self.info.get("front tab before switching, dialog open"), "after": tab})
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()

    def s_switch_nav(self):
        """No dialog, the Dialog tab in front (closing the dialog above already let the shell's tick settle):
        switching applications must bring the Part Navigator back, though the tick sees no change."""
        self.info["front tab before switching, no dialog"] = self.tasks_to_front()
        self.shell.switch_application("drafting")

    def s_switch_nav_check(self):
        before, tab = self.info.get("front tab before switching, no dialog"), self.shell.current_left_tab()
        self.check("Part Navigator in front after an application switch",
                   before == "Dialog" and tab == "Part Navigator" and not Gui.Control.activeDialog(),
                   {"before": before, "after": tab})

    def s_auto_app(self):
        if self.shell._app("simulation"):
            self.shell.switch_application("simulation")

    def s_auto_check(self):
        if not self.shell._app("simulation"):
            self.skip("guided Simulation ribbon (FEM)", "FEM not installed")
            return
        r = self.shell.ribbon
        steps = [(g.title, g.step) for _t, g in r.groups("Home")]
        self.info["missing_simulation_commands"] = r.missing
        self.check("guided Simulation ribbon: Home tab is the analysis workflow in order, every command found",
                   r.tab_names()[:4] == ["Home", "Loads", "Mesh and Solve", "Results"]
                   and [s for _t, s in steps] == ["analysis", "material", "loads", "mesh", "solve", "results"]
                   and not r.missing, f"{r.tab_names()}, {steps}, missing {r.missing}")
        visible = [tb.objectName() for tb in self.shell.native_toolbars() if tb.isVisible()]
        self.check("FEM toolbars hidden", not visible, visible)
        self.fem_guide()
        self.layout_matrix("Simulation")
        self.shot("04_simulation.png")

    def fem_guide(self):
        """The guide follows the analysis: nothing -> step 1 next; analysis, material and a fixed support ->
        steps 1-3 ticked and the mesh next. Checked through the ribbon's labels, on a document of its own."""
        from . import fem_guide
        before = App.ActiveDocument
        doc = App.newDocument("NXFemGuide")
        try:
            r = self.shell.ribbon
            empty = self.shell.update_guide()
            labels_empty = {g.step: g.label.text() for _t, g in r.groups("Home")}
            import ObjectsFem
            import Part  # noqa: F401
            box = doc.addObject("Part::Box", "Block")
            doc.recompute()
            analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
            analysis.addObject(ObjectsFem.makeMaterialSolid(doc, "Steel"))
            fixed = ObjectsFem.makeConstraintFixed(doc, "Fixed")
            fixed.References = [(box, "Face1")]
            analysis.addObject(fixed)
            doc.recompute()
            states = self.shell.update_guide()
            labels = {g.step: (g.label.text(), g.property("nxstep")) for _t, g in r.groups("Home")}
            self.info["fem guide"] = {"empty": empty, "set up": states, "labels": labels,
                                      "members": fem_guide.active_members(doc)}
            self.check("Simulation guide: an empty document's next step is the analysis; with analysis, material "
                       "and a fixed support the mesh is next and steps 1-3 are ticked",
                       empty is not None and empty["analysis"] == "next" and "✓" not in "".join(labels_empty.values())
                       and states == {"analysis": "done", "material": "done", "loads": "done", "mesh": "next",
                                      "solve": "", "results": ""}
                       and labels["loads"][0].endswith("✓") and labels["mesh"][1] == "next",
                       f"empty {empty}; set up {states}; labels {labels}")
        finally:
            App.closeDocument(doc.Name)
            if before is not None and before.Name in App.listDocuments():
                App.setActiveDocument(before.Name)
            self.shell.update_guide()

    def s_katydid(self):
        """Katydid (github.com/Foadsf/Katydid), on by default: NX's Algorithmic Modeling application."""
        if self.shell._app("algorithmic_modeling"):
            # Katydid a0a9e8a+ registers its commands at start-up: Canvas is on every Tools tab before its
            # workbench (which opens the canvas when it starts) has ever been activated
            mw = Gui.getMainWindow()
            self.info["katydid canvas before"] = {
                "command on Tools tab": "Katydid_Canvas" in self.shell.ribbon.locations,
                "where": self.shell.ribbon.locations.get("Katydid_Canvas"),
                "workbench": Gui.activeWorkbench().name(),
                "canvas exists": mw.findChild(QtWidgets.QDockWidget, "KatydidDock") is not None}
            self.shell.switch_application("algorithmic_modeling")

    def s_katydid_check(self):
        want = os.environ.get("NXSTYLE_KATYDID_EXPECTED", "1") == "1"
        app = self.shell._app("algorithmic_modeling")
        if not want:
            self.check("Katydid off as asked", app is None and "KatydidWorkbench" not in Gui.listWorkbenches(), app)
            return
        self.check("Algorithmic Modeling application (Katydid) offered", app is not None,
                   sorted(Gui.listWorkbenches()))
        if app is None:
            return
        before = self.info.get("katydid canvas before", {})
        self.check("Katydid's Canvas on the Tools tab before its workbench has started",
                   before.get("command on Tools tab") and str(before.get("where", "")).startswith("Tools")
                   and before.get("workbench") != "KatydidWorkbench" and not before.get("canvas exists"), before)
        r, mw = self.shell.ribbon, Gui.getMainWindow()
        cmds = {c: c in r.locations for c in ("Katydid_Canvas", "Katydid_Bake")}
        self.check("Algorithmic Modeling ribbon with Katydid's Canvas and Bake, and the Application tab",
                   Gui.activeWorkbench().name() == "KatydidWorkbench" and all(cmds.values())
                   and not [m for m in r.missing if "Katydid" in str(m)] and "Application" in r.tab_names(),
                   {"commands": cmds, "tabs": r.tab_names()})
        dock = mw.findChild(QtWidgets.QDockWidget, "KatydidDock")
        model = mw.findChild(QtWidgets.QDockWidget, "Model")
        tabbed = dock is not None and model is not None and dock in mw.tabifiedDockWidgets(model)
        self.check("Katydid canvas opens floating, outside the navigator strip",
                   dock is not None and dock.isVisible() and dock.isFloating() and not tabbed,
                   None if dock is None else {"visible": dock.isVisible(), "floating": dock.isFloating(),
                                              "tabbed": tabbed})
        visible = [tb.objectName() for tb in self.shell.native_toolbars() if tb.isVisible()]
        self.check("Katydid's own toolbar hidden under the ribbon", not visible, visible)
        contrast = self.katydid_tab_contrast(dock)
        # under the NX theme the selected category tab once drew as a black box with no label (Katydid 2a3759b)
        self.check("Katydid's selected category tab has a readable label", contrast is not None and contrast > 0.3,
                   contrast)
        panel = dock.widget() if dock is not None else None
        if hasattr(panel, "load_example"):              # Katydid's own example, for the screenshot
            panel.load_example("attractor")
        elif hasattr(panel, "load_attractor_demo"):
            panel.load_attractor_demo()

    @staticmethod
    def katydid_tab_contrast(dock):
        """Luminance range (0..1) inside the selected tab of Katydid's category ribbon: ~0 = one flat colour.
        Measured on Katydid 2a3759b (the black box): 0.784 with the tab's border included, which is why the
        border is excluded."""
        tabs = getattr(dock.widget(), "ribbon", None) if dock is not None else None
        bar = tabs.tabBar() if tabs is not None else None
        if bar is None:
            return None
        img = bar.grab(bar.tabRect(bar.currentIndex())).toImage()
        img.save(os.path.join(OUT, "05_katydid_selected_tab.png"))
        m = 4          # inside the tab only: its border alone would give a range on a flat black box
        lum = [pixel_luminance(img.pixel(x, y)) for x in range(m, img.width() - m)
               for y in range(m, img.height() - m)]
        return round((max(lum) - min(lum)) / 255, 3) if lum else None

    def s_katydid_shot(self):
        """The floating canvas is its own window, so the main-window grab misses it: paint both."""
        mw = Gui.getMainWindow()
        dock = mw.findChild(QtWidgets.QDockWidget, "KatydidDock")
        if dock is None or not self.shell._app("algorithmic_modeling"):
            return
        if hasattr(dock.widget(), "view"):
            dock.widget().view.fit_all()
        QtWidgets.QApplication.processEvents()
        try:
            from .qt import QtGui
            img = mw.grab()
            canvas = dock.grab()
            at = mw.mapFromGlobal(dock.mapToGlobal(QtCore.QPoint(0, 0)))
            p = QtGui.QPainter(img)
            p.drawPixmap(at, canvas)
            p.end()
            img.save(os.path.join(OUT, "05_algorithmic_modeling.png"))
            self.shot("05_katydid_canvas.png", dock)
        except Exception as e:
            self.info["screenshot 05"] = str(e)

    def s_back(self):
        self.shell.switch_application("modeling")

    def s_katydid_after(self):
        if not self.shell._app("algorithmic_modeling"):
            return
        r = self.shell.ribbon
        self.check("back in Modeling after Algorithmic Modeling",
                   Gui.activeWorkbench().name() == "PartDesignWorkbench" and "NXStyle_Extrude" in r.locations,
                   r.tab_names())
        dock = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "KatydidDock")
        self.check("Katydid canvas stays open after leaving Algorithmic Modeling (as documented)",
                   dock is not None and dock.isVisible(), None if dock is None else dock.isVisible())

    # ---------------------------------------------------------------- Laser Cut (LCInterlocking)
    LC_COMMANDS = ("make_box_command", "make_rounded_box_command", "multiple_tabs_command", "crosspiece",
                   "livinghinge", "export_command")
    LC_T = 3.0          # panel thickness, mm
    LC_TABS = 3
    LC_TAB_WIDTH = 10.0

    def s_laser_cut(self):
        """Laser Cut on LCInterlocking (github.com/execuc/LCInterlocking), on by default: two 3 mm panels,
        a base and a wall standing on it, as Part solids (the add-on ignores a PartDesign Body's placement)."""
        if not self.shell._app("laser_cut"):
            return
        doc = App.newDocument("SmokeLaserCut")
        base = doc.addObject("Part::Box", "Base")
        base.Length, base.Width, base.Height = 100, 60, self.LC_T
        wall = doc.addObject("Part::Box", "Wall")
        wall.Length, wall.Width, wall.Height = 100, self.LC_T, 40
        wall.Placement.Base = App.Vector(0, 0, self.LC_T)
        doc.recompute()
        self.shell.switch_application("laser_cut")

    def lc_button(self, cmd):
        return next((b for b in self.shell.ribbon.findChildren(QtWidgets.QToolButton, "NXRibbonButton")
                     if getattr(b, "command", None) == cmd), None)

    def s_laser_cut_check(self):
        want = os.environ.get("NXSTYLE_LCINTERLOCKING_EXPECTED", "1") == "1"
        app = self.shell._app("laser_cut")
        if not want:
            self.check("LCInterlocking off as asked", app is None and
                       "LCInterlockingWorkbench" not in Gui.listWorkbenches(), app)
            return
        self.check("Laser Cut application (LCInterlocking) offered", app is not None, sorted(Gui.listWorkbenches()))
        if app is None:
            return
        r = self.shell.ribbon
        cmds = {c: c in r.locations for c in self.LC_COMMANDS}
        missing = [m for m in r.missing if str(m[-1]).startswith(("Part_", "Sketcher_")) or
                   m[-1] in self.LC_COMMANDS]
        self.check("Laser Cut ribbon with LCInterlocking's commands, and the Application tab",
                   Gui.activeWorkbench().name() == "LCInterlockingWorkbench" and all(cmds.values()) and not missing
                   and r.tab_names()[:1] == ["Home"] and "Application" in r.tab_names(),
                   {"workbench": Gui.activeWorkbench().name(), "commands": cmds, "missing": missing,
                    "tabs": r.tab_names()})
        b = self.lc_button("multiple_tabs_command")
        tip = b.toolTip() if b is not None else ""
        self.check("Laser Cut buttons carry NX names, the add-on's own name in the tooltip",
                   b is not None and b.text().replace("\n", " ") == "Tabs and Slots" and "FreeCAD: Slots" in tip, tip)
        visible = [tb.objectName() for tb in self.shell.native_toolbars() if tb.isVisible()]
        self.check("LCInterlocking's own toolbars hidden under the ribbon", not visible, visible)

    def s_laser_cut_join(self):
        """Tabs and Slots from the ribbon, then the add-on's own task panel: parts, the wall's bottom face as
        a Tab joint, OK. Driven through the panel's methods, as its buttons call them."""
        doc = App.getDocument("SmokeLaserCut") if "SmokeLaserCut" in App.listDocuments() else None
        b = self.lc_button("multiple_tabs_command")
        if doc is None or b is None:
            return
        App.setActiveDocument(doc.Name)
        n0 = len(doc.Objects)
        b.click()
        join = next((o for o in doc.Objects[n0:] if o.Name.startswith("MultiJoin")), None)
        self.info["laser cut dialog opened by the ribbon"] = bool(Gui.Control.activeDialog())
        if join is None:
            return
        Gui.Control.closeDialog()
        from panel.multiplejoins import MultipleJoins           # the add-on's own task panel
        panel = MultipleJoins(join)
        self.lc_qt6(panel)
        base, wall = doc.getObject("Base"), doc.getObject("Wall")
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(base)
        Gui.Selection.addSelection(wall)
        panel.add_parts()
        face = next(f"Face{i + 1}" for i, f in enumerate(wall.Shape.Faces)
                    if abs(f.CenterOfMass.z - self.LC_T) < 1e-6 and f.normalAt(0, 0).z < -0.9)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, wall.Name, face)
        panel.add_tabs()
        panel.selection_model.clearSelection()      # saves the tab's widget, so the values below stay
        for t in panel.tabsList.faces:
            t.tabs_number, t.tabs_width = self.LC_TABS, self.LC_TAB_WIDTH
        self.info["laser cut panel"] = {"parts": [p.name for p in panel.partsList.part_list],
                                        "tabs": [t.tab_name for t in panel.tabsList.faces]}
        panel.accept()
        self.info["laser cut join"] = join.Name

    def lc_qt6(self, panel):
        """The two calls that fail on PySide6 in upstream LCInterlocking: fixed in the bundled fork, patched
        by nxstyle.lcinterlocking in an upstream copy."""
        import inspect
        from . import lcinterlocking
        mod = inspect.getmodule(type(panel).__mro__[1])
        src = inspect.getsourcefile(mod) or ""
        try:
            buttons = panel.getStandardButtons()
        except Exception as e:
            buttons = repr(e)
        try:
            panel.force_selection(None)
            none = "ok"
        except Exception as e:
            none = repr(e)
        self.info["laser cut qt6"] = {"buttons": buttons, "add with nothing selected": none,
                                      "patched by NXStyle": bool(getattr(mod.TreePanel, lcinterlocking.MARK, False)),
                                      "fixed in the add-on": "if index is None" in open(src, encoding="utf-8").read(),
                                      "from": src}

    def report_text(self):
        report = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Report view")
        return "\n".join(w.toPlainText() for w in (report.findChildren(QtWidgets.QTextEdit) +
                                                   report.findChildren(QtWidgets.QPlainTextEdit))) if report else ""

    def s_laser_cut_result(self):
        if not self.shell._app("laser_cut"):
            return
        doc = App.listDocuments().get("SmokeLaserCut")
        join = doc.getObject(self.info.get("laser cut join", "")) if doc else None
        parts = {o.Name: o.Shape for o in (join.generatedParts if join else [])}
        base, wall = parts.get("Base_tab"), parts.get("Wall_tab")
        t, slot = self.LC_T, self.LC_TABS * self.LC_TAB_WIDTH * self.LC_T * self.LC_T
        detail = {n: {"valid": sh.isValid(), "solids": len(sh.Solids), "volume": round(sh.Volume, 2),
                      "zmin": round(sh.BoundBox.ZMin, 3)} for n, sh in parts.items()}
        ok = (base is not None and wall is not None and all(sh.isValid() and len(sh.Solids) == 1
                                                             for sh in (base, wall)))
        if ok:
            removed = 100 * 60 * t - base.Volume
            added = wall.Volume - 100 * t * 40
            overlap = base.common(wall).Volume
            detail.update({"slots removed": round(removed, 2), "tabs added": round(added, 2),
                           "overlap": round(overlap, 2), "expected": slot})
            # LCInterlocking widens each tab by the laser kerf (thickness/15 by default): a press fit
            ok = (abs(removed - slot) < 0.01 * slot and slot <= added < 1.05 * slot and
                  abs(wall.BoundBox.ZMin) < 1e-6 and overlap < 0.1 * slot)
        q = self.info.get("laser cut qt6", {})
        errors = [ln for ln in self.report_text().splitlines() if "StandardButton" in ln or "NoneType, SelectionFlag" in ln]
        self.check("LCInterlocking's task panel on Qt 6: OK and Cancel, Add with nothing selected, no TypeError "
                   "(fixed in the bundled fork, patched in an upstream copy)",
                   q.get("buttons") == 0x400400 and q.get("add with nothing selected") == "ok" and not errors,
                   {**q, "report errors": errors[:3]})
        self.check(f"Laser Cut: two panels joined with {self.LC_TABS} tabs (one solid each, slots cut, "
                   f"tabs through the base)", ok, detail)
        if doc is not None:
            v = Gui.getDocument(doc.Name).ActiveView
            v.viewIsometric()
            v.fitAll()
            QtWidgets.QApplication.processEvents()
            self.shot("10_laser_cut.png")

    def s_laser_cut_back(self):
        if self.shell._app("laser_cut"):
            self.shell.switch_application("modeling")

    def s_laser_cut_after(self):
        if not self.shell._app("laser_cut"):
            return
        r = self.shell.ribbon
        self.check("back in Modeling after Laser Cut",
                   Gui.activeWorkbench().name() == "PartDesignWorkbench" and "NXStyle_Extrude" in r.locations,
                   r.tab_names())
        if "SmokeLaserCut" in App.listDocuments():
            App.closeDocument("SmokeLaserCut")

    # ------------------------------------------------- Molded Part Validation (DFM add-on)
    DFM_BUTTONS = {"DFM_SetupAnalysis": "Moldability Validation", "DFM_ThicknessAnalysis": "Check Wall Thickness",
                   "DFM_DraftAnalysis": "Draft Analysis", "DFM_ProcessLibrary": "Process Library"}
    DFM_RULE = "Sharp Internal Corners"

    def dfm_want(self):
        return os.environ.get("NXSTYLE_DFM_EXPECTED", "1") == "1"

    def s_dfm(self):
        """DFM (github.com/ryankembrey/FreeCAD-DFM-Workbench), on by default once its OCP is installed: two
        30 x 20 x 10 blocks with a 15 x 5 step, one with the step's inside edge sharp (a known Sharp
        Internal Corner), one with it filleted R2 (none)."""
        if not self.dfm_want():
            return
        import Part
        doc = App.newDocument("SmokeDFM")
        notched = Part.makeBox(30, 20, 10).cut(Part.makeBox(15, 20, 5, App.Vector(15, 0, 5)))
        inner = [i for i, e in enumerate(notched.Edges)
                 if all(abs(v.X - 15) < 1e-6 and abs(v.Z - 5) < 1e-6 for v in e.Vertexes)]
        clean = notched.makeFillet(2.0, [notched.Edges[i] for i in inner])
        a = doc.addObject("Part::Feature", "Notched")
        a.Shape = notched
        b = doc.addObject("Part::Feature", "Filleted")
        b.Shape = clean
        b.Placement.Base = App.Vector(0, 40, 0)
        doc.recompute()
        self.info["dfm sharp edge"] = [f"Edge{i + 1}" for i in inner]
        self.shell.switch_application("modeling")
        self.shell.ribbon.select("Analysis")

    def s_dfm_check(self):
        cmds = Gui.listCommands()
        if not self.dfm_want():
            self.check("DFM off as asked: no Molded Part Validation group",
                       not any(c in cmds for c in self.DFM_BUTTONS)
                       and not any(c in self.shell.ribbon.locations for c in self.DFM_BUTTONS),
                       [c for c in self.DFM_BUTTONS if c in cmds])
            return
        r = self.shell.ribbon
        where = {c: r.locations.get(c) for c in self.DFM_BUTTONS}
        buttons = {c: self.lc_button(c) for c in self.DFM_BUTTONS}
        state = {c: None if b is None else (b.text().replace("\n", " "), b.isEnabled()) for c, b in buttons.items()}
        self.check("DFM add-on loaded: its commands in Analysis > Molded Part Validation, buttons enabled",
                   all(c in cmds for c in self.DFM_BUTTONS)
                   and all(w == "Analysis › Molded Part Validation" for w in where.values())
                   and all(s is not None and s[1] for s in state.values()), {"where": where, "buttons": state})
        tip = buttons["DFM_SetupAnalysis"].toolTip() if buttons["DFM_SetupAnalysis"] else ""
        self.check("Molded Part Validation buttons carry NX names, the add-on's own name in the tooltip",
                   all(s is not None and s[0] == self.DFM_BUTTONS[c] for c, s in state.items())
                   and "FreeCAD: DFM Analysis" in tip, tip)
        found = {t: self.shell.finder.find(t) for t in ("Moldability Validation", "Check Wall Thickness")}
        self.check("Command Finder finds Moldability Validation and Check Wall Thickness",
                   "DFM_SetupAnalysis" in found["Moldability Validation"]
                   and "DFM_ThicknessAnalysis" in found["Check Wall Thickness"], found)
        report = [ln for ln in self.report_text().splitlines()
                  if ("DFM" in ln or "OCP" in ln) and ("Error" in ln or "Traceback" in ln or "failed" in ln)]
        self.check("DFM loaded without errors in the Report view", not report, report[:5])

    def dfm_widget(self, kind, name):
        """The add-on's live task-panel widget of that name (an earlier panel's may wait for deletion)."""
        found = [w for w in Gui.getMainWindow().findChildren(kind, name) if w.isVisible()]
        return found[-1] if found else None

    def dfm_run(self, target):
        """Select the part, Moldability Validation on the ribbon, then the add-on's own panel: material
        Default (category and process are its only ones and fill themselves), Run Analysis."""
        doc = App.listDocuments().get("SmokeDFM")
        b = self.lc_button("DFM_SetupAnalysis")
        if doc is None or b is None:
            return
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        App.setActiveDocument(doc.Name)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.getObject(target))
        b.click()
        QtWidgets.QApplication.processEvents()
        target_box = self.dfm_widget(QtWidgets.QLineEdit, "leSelectModel")
        material = self.dfm_widget(QtWidgets.QComboBox, "cbMaterial")
        run = self.dfm_widget(QtWidgets.QPushButton, "pbRunAnalysis")
        state = {"dialog": bool(Gui.Control.activeDialog()), "target": target_box.text() if target_box else None}
        if material is not None:
            material.setCurrentIndex(material.findText("Default"))
            state["material"] = material.currentText()
        if run is not None:
            state["run enabled"] = run.isEnabled()
            run.click()                 # the add-on analyses in the click, then opens its results panel
        self.info[f"dfm run {target}"] = state

    def dfm_findings(self):
        """What the results panel shows: {rule: [geometry of each finding]} and the rules listed as Passed."""
        tree = self.dfm_widget(QtWidgets.QTreeView, "tvResults")
        if tree is None:
            return None, None
        model, kind, label = tree.model(), Qt.UserRole + 1, Qt.UserRole + 2
        findings, passed = {}, []

        def walk(parent, under):
            for row in range(model.rowCount(parent)):
                i = model.index(row, 0, parent)
                what, name = i.data(kind), i.data(label)
                if what == "finding":
                    findings.setdefault(under, []).append(name)
                elif under == "Passed" and what == "rule":
                    passed.append(name)
                walk(i, "Passed" if name == "Passed" else name if what == "rule" else under)
        walk(QtCore.QModelIndex(), None)
        return findings, passed

    def dfm_close(self):
        """The results panel's Close button, as a user would (the add-on restores the part's colours)."""
        close = next((bt for bt in Gui.getMainWindow().findChildren(QtWidgets.QPushButton)
                      if bt.isVisible() and bt.text().replace("&", "") == "Close"), None)
        if close is not None:
            close.click()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()

    def s_dfm_run_notched(self):
        if self.dfm_want():
            self.dfm_run("Notched")

    def s_dfm_result_notched(self):
        if not self.dfm_want():
            return
        findings, passed = self.dfm_findings()
        self.info["dfm notched"] = {"findings": findings, "passed": passed, "run": self.info.get("dfm run Notched")}
        sharp = (findings or {}).get(self.DFM_RULE, [])
        self.check("Moldability Validation from the ribbon flags the sharp inside edge of a stepped block "
                   "(Sharp Internal Corners, that edge only)",
                   findings is not None and sharp == self.info.get("dfm sharp edge"),
                   {"expected": self.info.get("dfm sharp edge"), "findings": findings})
        if findings is not None:
            self.shot("11_dfm_moldability.png")
        self.dfm_close()

    def s_dfm_run_clean(self):
        if self.dfm_want():
            self.dfm_run("Filleted")

    def s_dfm_result_clean(self):
        if not self.dfm_want():
            return
        findings, passed = self.dfm_findings()
        self.info["dfm filleted"] = {"findings": findings, "passed": passed, "run": self.info.get("dfm run Filleted")}
        self.check("negative control: the same block with that edge filleted R2 has no Sharp Internal Corner "
                   "(the rule listed as Passed)",
                   findings is not None and self.DFM_RULE not in findings and self.DFM_RULE in passed,
                   {"findings": findings, "passed": passed})
        self.dfm_close()

    def s_dfm_after(self):
        if "SmokeDFM" in App.listDocuments():
            App.closeDocument("SmokeDFM")
        self.shell.ribbon.select("Home")

    def s_expressions(self):
        Gui.runCommand("NXStyle_Expressions")

    def s_final(self):
        self.info["Strata PanelVisible at the end"] = App.ParamGet(
            "User parameter:BaseApp/Preferences/Mod/Strata").GetBool("PanelVisible", True)
        # FreeCAD reports a command icon it cannot resolve in the Report view ("Cannot find icon: X")
        report = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Report view")
        texts = [w.toPlainText() for w in (report.findChildren(QtWidgets.QTextEdit) +
                                          report.findChildren(QtWidgets.QPlainTextEdit))] if report else []
        missing_icons = sorted({ln.strip() for t in texts for ln in t.splitlines() if "Cannot find icon" in ln})
        self.check("every command icon found (Report view has no 'Cannot find icon')",
                   bool(texts) and not missing_icons, missing_icons if texts else "no Report view text")
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
    def s_keys_in_text_field(self):
        """A single-letter NX key typed into a text field is text: X in the Command Finder must not reach
        Extrude (a shortcut that fires while the user types would run commands by accident)."""
        try:
            from PySide6 import QtTest
        except ImportError:
            from PySide2 import QtTest
        inst = shortcuts.instance()
        act = inst.targets.get(shortcuts.norm("X"))
        field = self.shell.finder
        if act is None or field is None:
            self.check("an NX letter key typed into a text field stays text", False, "no X action or no finder")
            return
        app = QtWidgets.QApplication.instance()
        probe = ShortcutProbe()
        app.installEventFilter(probe)
        try:
            field.setFocus()
            field.clear()
            QtTest.QTest.keyClick(field, Qt.Key_X)
            reached = [h for h in probe.hits if h[0] == cpp(act)]
            text = field.text()
        finally:
            app.removeEventFilter(probe)
            field.clear()
            self.nav().widget.setFocus()
        self.check("an NX letter key typed into a text field stays text (X in the Command Finder)",
                   not reached and text.lower() == "x", f"typed {text!r}; reached Extrude: {bool(reached)}")

    def press_keys(self, context):
        """Press every key of one context and check which action Qt's shortcut dispatch picks; the probe
        eats the shortcut event, so this tests dispatch, not that the command then works."""
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
        self.check(f"real key presses reach their commands through Qt's shortcut dispatch ({tested} keys; "
                   "dispatch only: the probe stops the command from running)", tested and not bad, bad)
        self.s_keys_in_text_field()
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

    def s_ap242(self):
        """STEP with PMI: a plate with a hole and a pin, PMI on both, written and read back."""
        import Part
        from . import ap242, pmi_ui
        if not ap242.available():
            self.skip("STEP AP242 with semantic PMI (written, ISO 286 grades right, read back by OCCT)",
                      "this FreeCAD has no pythonocc")
            return
        before = App.ActiveDocument
        doc = App.newDocument("SmokeAP242")
        try:
            shape = Part.makeBox(80, 50, 12).cut(Part.makeCylinder(8, 12, App.Vector(25, 25, 0)))
            shape = shape.fuse(Part.makeCylinder(5, 15, App.Vector(60, 25, 12))).removeSplitter()
            plate = doc.addObject("Part::Feature", "Plate")
            plate.Shape = shape
            doc.recompute()

            def face(pred):
                return "Face%d" % next(i for i, f in enumerate(plate.Shape.Faces, 1) if pred(f))

            def kind(f):
                return f.Surface.__class__.__name__

            bottom = face(lambda f: kind(f) == "Plane" and abs(f.CenterOfMass.z) < 1e-6)
            hole = face(lambda f: kind(f) == "Cylinder" and abs(f.Surface.Radius - 8) < 1e-6)
            pin = face(lambda f: kind(f) == "Cylinder" and abs(f.Surface.Radius - 5) < 1e-6)
            pmi_ui.create("Datum Feature", [(plate, bottom)], doc, Letter="A")
            pmi_ui.create("Datum Feature", [(plate, hole)], doc, Letter="B")
            pmi_ui.create("Dimension", [(plate, hole)], doc, DimensionType="Diameter", Fit="H7")
            pmi_ui.create("Dimension", [(plate, pin)], doc, DimensionType="Diameter", Fit="g6")
            pmi_ui.create("Feature Control Frame", [(plate, pin)], doc, Characteristic="Position", Tolerance=0.02,
                          ZoneDiameter=True, MaterialCondition="MMC", DatumReferences=["A", "B(M)"])
            pmi_ui.create("Feature Control Frame", [(plate, bottom)], doc, Characteristic="Flatness",
                          Tolerance=0.01)
            path = os.path.join(OUT, "smoke_pmi.step")
            text = pmi_ui.export_step(doc, path)
            s = ap242.summary(open(path, encoding="latin-1").read())
            back = pmi_ui.last.get("read_back") or {}
            ok = (s["schema"].startswith("AP242") and s["datums"] == ["A", "B"] and s["fits"] == ["H7", "g6"]
                  and s["tolerances"] == {"POSITION_TOLERANCE": 1, "FLATNESS_TOLERANCE": 1}
                  and s["material_requirements"] == 1 and back.get("dimensions") == 2
                  and back.get("geometric_tolerances") == 2)
            self.check("STEP AP242 with semantic PMI (written, ISO 286 grades right, read back by OCCT)", ok,
                       text.splitlines()[1:])
            # the MBD round trip: the file's PMI imported into a new part as NXStyle PMI on its faces
            back_doc = App.newDocument("SmokeAP242Import")
            try:
                parts, made, problems = pmi_ui.import_step(path, back_doc)
                written = sorted(p.Callout for p in pmi_ui.all_pmi(doc))
                imported = sorted(p.Callout for p in made)
                self.check("Import STEP with PMI: the same PMI on the same kind of faces", written == imported and
                           not problems and [p.Label for p in parts] == ["Plate"],
                           f"written {written}; imported {imported}; problems {problems}")
            finally:
                App.closeDocument(back_doc.Name)
        finally:
            App.closeDocument(doc.Name)
            if before is not None and before.Name in App.listDocuments():
                App.setActiveDocument(before.Name)
                Gui.getDocument(before.Name)

    def s_inspection(self):
        """Composite position evaluated from measured data, a gauge study, and a title block on a sheet."""
        import Part
        from . import msa_ui, pmi_ui, position_ui, titleblock_ui
        before = App.ActiveDocument
        doc = App.newDocument("SmokeInspection")
        try:
            shape = Part.makeBox(80, 80, 10)
            centres = [(20.0, 20.0), (20.0, 60.0), (60.0, 60.0), (60.0, 20.0)]
            for x, y in centres:
                shape = shape.cut(Part.makeCylinder(2.5, 10, App.Vector(x, y, 0)))
            plate = doc.addObject("Part::Feature", "Plate")
            plate.Shape = shape
            doc.recompute()

            def face(pred):
                return "Face%d" % next(i for i, f in enumerate(plate.Shape.Faces, 1) if pred(f))

            def plane(axis):
                return face(lambda f: f.Surface.__class__.__name__ == "Plane"
                            and abs(getattr(f.CenterOfMass, axis)) < 1e-6)
            holes = [face(lambda f, x=x, y=y: f.Surface.__class__.__name__ == "Cylinder"
                          and abs(f.Surface.Center.x - x) < 1e-6 and abs(f.Surface.Center.y - y) < 1e-6)
                     for x, y in centres]
            for letter, axis in (("A", "z"), ("B", "x"), ("C", "y")):
                pmi_ui.create("Datum Feature", [(plate, plane(axis))], doc, Letter=letter)
            size = pmi_ui.create("Dimension", [(plate, h) for h in holes], doc, DimensionType="Diameter",
                                 UpperDeviation=0.2, Quantity=4)
            frame = pmi_ui.create("Feature Control Frame", [(plate, h) for h in holes], doc, Characteristic="Position",
                                  Tolerance=0.2, ZoneDiameter=True, MaterialCondition="MMC",
                                  DatumReferences=["A", "B", "C"], FrameStyle="Composite Frame", LowerTolerance=0.04,
                                  LowerMaterialCondition="MMC", LowerDatumReferences=["A"])
            ev = position_ui.create(frame, doc, Measured=["19.94 20.06 5.12", "20.08 60.08 5.16", "60.12 59.96 5.20",
                                                          "60.04 19.96 5.08"])
            svg, _, h = pmi_ui.label_svg(frame)
            self.check("composite position: callout, two-row label, evaluation from measured data",
                       frame.Callout == "position | Ø0.200 (M) | A | B | C / Ø0.040 (M) | A" and abs(h - 14) < 1e-9
                       and ev.Verdict == "ACCEPT" and abs(ev.LowerUsed - 71.5) < 0.2 and ev.Size == size
                       and ev.Basic == ["20.0000 20.0000", "20.0000 60.0000", "60.0000 60.0000", "60.0000 20.0000"],
                       f"{frame.Callout}; {ev.Verdict}, PLTZF {ev.UpperUsed:.1f} %, FRTZF {ev.LowerUsed:.1f} %; "
                       f"basic {list(ev.Basic)}")
            study = msa_ui.create(size, doc, Readings=["5.10 5.14", "5.08 5.12", "5.15 5.19"],
                                  Spread="6 sigma (AIAG MSA)")
            self.check("gauge study on a PMI size", abs(study.Tolerance - 0.2) < 1e-9 and study.Percent > 30
                       and study.Verdict.startswith("unacceptable"), f"{study.Percent:.1f} %: {study.Verdict}")
            page = doc.addObject("TechDraw::DrawPage", "Sheet")
            tmpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
            tmpl.Template = os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates",
                                         "Default_Template_A4_Landscape.svg")
            page.Template = tmpl
            doc.recompute()
            doc.Meta = {"DB_PART_NO": "PLT-300", "DB_PART_REV": "C", "DB_PART_NAME": "PLATE, COVER"}
            had = titleblock_ui.has_title_block(page)
            values = {k: v for k, v in titleblock_ui.titleblock.values(titleblock_ui.info(page)).items()}
            titleblock_ui.apply(page, values, titleblock_ui.iso_template(page), [("C", "First release", "", "")])
            t = dict(page.Template.EditableTexts)
            block = [v for v in page.Views if getattr(v, "NX_Kind", "") == "revision block"]
            self.check("Populate Title Block: ISO 7200 fields from the part's attributes, a revision block",
                       not had and t.get("drawing_number") == "PLT-300" and t.get("revision_index") == "C"
                       and t.get("title") == "PLATE, COVER" and t.get("general_tolerances") == "ISO 8015"
                       and t.get("supplementary_title_2") == "" and t.get("responsible_department") == ""
                       and len(block) == 1, f"template had a title block: {had}; {t}")
        finally:
            App.closeDocument(doc.Name)
            if before is not None and before.Name in App.listDocuments():
                App.setActiveDocument(before.Name)
                Gui.getDocument(before.Name)

    def s_validity(self):
        """Broken references make PMI, stack-ups and clearance results say so, instead of keeping their last
        good values: a diameter whose face became a plane, a stack-up whose PMI was deleted, a clearance
        result after a part moved, a pair rule naming a label two parts share."""
        import Part
        from . import ap242, clearance, pmi, pmi_ui, stackup_ui
        before = App.ActiveDocument
        doc = App.newDocument("SmokeValidity")
        try:
            plate = doc.addObject("Part::Feature", "Plate")
            plate.Shape = Part.makeBox(60, 40, 10).cut(Part.makeCylinder(5, 10, App.Vector(30, 20, 0)))
            doc.recompute()
            hole = "Face%d" % next(i for i, f in enumerate(plate.Shape.Faces, 1)
                                   if f.Surface.__class__.__name__ == "Cylinder")
            top = "Face%d" % next(i for i, f in enumerate(plate.Shape.Faces, 1)
                                  if f.Surface.__class__.__name__ == "Plane" and abs(f.CenterOfMass.z - 10) < 1e-6)
            dia = pmi_ui.create("Dimension", [(plate, hole)], doc, DimensionType="Diameter", Fit="H7")
            good = (dia.Valid, dia.Callout)
            dia.References = [(plate, top)]                  # the face it measured is now a plane
            doc.recompute()
            bad = (dia.Valid, dia.Callout)
            anns = [pmi_ui.semantic(o) for o in pmi_ui.all_pmi(doc)]
            in_plan = any(r["id"] == dia.Name for r in pmi.inspection_plan(pmi.number(anns)))
            flagged = any(s == "error" and i == dia.Name for s, i, _ in pmi.check(anns))
            refused = False
            try:
                pmi_ui.stack_values(dia)
            except ValueError:
                refused = True
            written = [r["id"] for r in ap242.plan([a for a in anns if pmi.is_valid(a)])]
            dia.References = [(plate, hole)]
            doc.recompute()
            back = (dia.Valid, dia.Callout)
            self.check("an invalid PMI says why and is not used: model, plan, checks, stack-up, export",
                       good[0] and not bad[0] and bad[1].startswith("error:") and "Ø10" not in bad[1]
                       and not in_plan and flagged and refused and dia.Name not in written
                       and back == good, f"valid {good}; face became a plane {bad}; in plan {in_plan}, "
                       f"flagged {flagged}, stack-up refused {refused}; repaired {back}")

            # a stack-up row following a PMI that is then deleted
            s = stackup_ui.create(doc)
            stackup_ui.set_rows(s, [{"name": "bore", "pmi": dia.Name, "nominal": 10, "plus": 0, "minus": 0}], [])
            doc.recompute()
            ok_before = s.Valid and abs(s.WorstCaseMax - s.Nominal) > 0
            doc.removeObject(dia.Name)
            s.touch()
            doc.recompute()
            self.check("a stack-up whose PMI was deleted gives no result, not the old one",
                       ok_before and not s.Valid and s.Verdict.startswith("INVALID") and s.WorstCaseMax == 0.0
                       and stackup_ui.csv_rows(s)[1][0].startswith("INVALID"), s.Verdict)

            # clearance: out of date after a part moves; a rule naming a shared label is not applied
            a = doc.addObject("Part::Box", "BlockA")
            b = doc.addObject("Part::Box", "BlockB")
            c = doc.addObject("Part::Box", "BlockC")
            # FreeCAD makes labels unique unless duplicates are allowed (Preferences > Document); with them, and
            # across linked documents, two parts can share a label
            pd = App.ParamGet("User parameter:BaseApp/Preferences/Document")
            dup = pd.GetBool("DuplicateLabels", False)
            pd.SetBool("DuplicateLabels", True)
            a.Label = "Block"
            c.Label = "Block"
            pd.SetBool("DuplicateLabels", dup)
            b.Placement.Base = App.Vector(5, 0, 0)
            doc.recompute()
            cset = clearance.create(doc, [a, b, c])
            cset.PairRules = ["Block|BlockB=exclude"]
            clearance.perform(cset)
            fresh = not clearance.is_stale(cset)
            b.Placement.Base = App.Vector(50, 0, 0)
            doc.recompute()
            stale = clearance.is_stale(cset) and cset.Stale and "OUT OF DATE" in clearance.report(cset)
            self.check("clearance results are marked out of date after a part moves; an ambiguous pair rule is "
                       "reported, not applied", fresh and stale and any("names 2 objects" in p for p in cset.RuleProblems),
                       f"fresh {fresh}, stale {stale}, labels {a.Label}/{c.Label}, rule problems "
                       f"{list(cset.RuleProblems)}")
        finally:
            App.closeDocument(doc.Name)
            if before is not None and before.Name in App.listDocuments():
                App.setActiveDocument(before.Name)
                Gui.getDocument(before.Name)

    def s_geometry_oracle(self):
        """The tutorials' geometry comparison tells solids of equal volume apart (a negative control), and
        accepts the same solid built another way (a positive one)."""
        import Part
        from . import geomcheck
        ref = Part.makeBox(20, 10, 10)
        same = Part.makeBox(10, 10, 10).fuse(Part.makeBox(10, 10, 10, App.Vector(10, 0, 0)))
        other = Part.makeBox(10, 10, 20)                      # the same 2000 mm³, a different block
        moved = Part.makeBox(20, 10, 10, App.Vector(0.5, 0, 0))
        ok_same, d_same = geomcheck.compare(same, ref)
        ok_other, d_other = geomcheck.compare(other, ref)
        ok_moved, d_moved = geomcheck.compare(moved, ref)
        # a curved solid with a display mesh attached, as the 3D view leaves it: its BoundBox is the mesh's
        disc = Part.Face(Part.Wire(Part.makeCircle(60))).extrude(App.Vector(0, 0, 20))
        disc.tessellate(0.5)
        meshed = disc.BoundBox.YMax
        ok_disc, d_disc = geomcheck.compare(disc, Part.makeCylinder(60, 20))
        self.check("geometry comparison: the same solid passes, also a meshed curved one; an equal-volume "
                   "different or moved one fails",
                   ok_same and ok_disc and not ok_other and not ok_moved and abs(other.Volume - ref.Volume) < 1e-9,
                   f"same: {d_same} | meshed disc (BoundBox Y max {meshed:.4f}): {d_disc} | other: {d_other} | "
                   f"moved: {d_moved}")

    def s_assembly_links(self):
        """Volume claims and clearance see a linked part where its assembly puts it, and not its hidden source."""
        from . import claims, clearance
        before = App.ActiveDocument
        doc = App.newDocument("SmokeLinks")
        try:
            block = doc.addObject("Part::Box", "Block")
            block.Length = block.Width = block.Height = 10
            asm = doc.addObject("App::Part", "Assembly")
            asm.Placement.Base = App.Vector(100, 0, 0)
            link = doc.addObject("App::Link", "BlockLink")
            link.LinkedObject = block
            link.Placement.Base = App.Vector(0, 50, 0)
            asm.addObject(link)
            block.Visibility = False
            wall = doc.addObject("Part::Box", "Wall")           # touches the link only where it really is
            wall.Length = wall.Width = wall.Height = 5
            wall.Placement.Base = App.Vector(105, 55, 0)
            doc.recompute()
            got = [(o.Name, round(s.BoundBox.XMin, 3), round(s.BoundBox.YMin, 3)) for o, s in claims.parts(doc)]
            row = clearance.analyse_pair(link, wall, clearance.solid_of(link), clearance.solid_of(wall), 0.0)
            vol = row[0]["volume"] if row else 0.0
            self.check("linked part in a moved assembly: claims and clearance use its global position",
                       got == [("BlockLink", 100.0, 50.0), ("Wall", 105.0, 55.0)] and abs(vol - 125) < 1e-6,
                       f"parts {got}; overlap with the wall {vol:.1f} mm³ (want 125)")
        finally:
            App.closeDocument(doc.Name)
            if before is not None and before.Name in App.listDocuments():
                App.setActiveDocument(before.Name)
                Gui.getDocument(before.Name)

    def s_selection(self):
        """Selection scope and look-alike occurrences, QuickPick, select-through, gate layers, collectors in
        both orders, curve chains and the Part Navigator's marks (smoke_selection.py)."""
        from . import smoke_selection
        smoke_selection.run(self)

    def s_section(self):
        """Extrude and Revolve on picked curves of the impeller casing sketch: the wall revolved, the edge extruded
        -Z, the flange revolved, then Cancel (smoke_section.py)."""
        from . import smoke_section
        smoke_section.run(self)

    def s_primitives(self):
        """Block, Cylinder, Cone and Sphere from their ribbon buttons: typed values, the vector, a point snapped at
        an arc centre, each Boolean, one undo step, Apply, Cancel and Esc, Edit Parameters (smoke_primitives.py)."""
        from . import smoke_primitives
        smoke_primitives.run(self)

    def s_thread(self):
        """Thread from its ribbon button and a click on the book's 0.25 in shank: Detailed against a Part API build
        of the same helix, the hand, one undo step, Edit Parameters, Cancel, Symbolic (smoke_thread.py)."""
        from . import smoke_thread
        smoke_thread.run(self)

    def s_move(self):
        """Move Object by Ctrl+T on the book's L-bar (4.7.3) and cylinder (4.6.9): Distance, Angle with Apply, Point
        to Point, Copy Original with 2 copies, Cancel and Esc, one undo step, negative controls (smoke_move.py)."""
        from . import smoke_move
        smoke_move.run(self)

    def press(self, seq):
        """A key press through Qt's shortcut map, on the graphics window, as a user types it."""
        from .tutorial import qtest
        mw = Gui.getMainWindow()
        app = QtWidgets.QApplication.instance()
        if app.activeWindow() is None and hasattr(app, "setActiveWindow"):
            app.setActiveWindow(mw)                   # a hidden desktop has no foreground window
        target = self.nav().widget
        target.setFocus()
        k, m = decode(seq)
        qtest().keyClick(target, k, m)

    def s_extrude_key(self):
        """Extrude started by its key with a sketch selected and a Type Filter set (the shortcut checks above
        test dispatch only; this one tests that the command then runs)."""
        import Part
        self._extrude_before = App.ActiveDocument
        doc = App.newDocument("SmokeExtrude")
        body = doc.addObject("PartDesign::Body", "Body")
        sk = body.newObject("Sketcher::SketchObject", "Sketch")
        sk.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
        sk.MapMode = "FlatFace"
        p = [App.Vector(0, 0, 0), App.Vector(30, 0, 0), App.Vector(30, 20, 0), App.Vector(0, 20, 0)]
        for i in range(4):
            sk.addGeometry(Part.LineSegment(p[i], p[(i + 1) % 4]), False)
        doc.recompute()
        Gui.getDocument(doc.Name).ActiveView.setActiveObject("pdbody", body)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, body.Name, f"{sk.Name}.")
        tf = self.shell.type_filter
        tf.setCurrentIndex(tf.findData("edge"))      # after the pick: an Edge filter would refuse the sketch
        self._extrude_doc = doc.Name
        self.press("X")

    def s_extrude_key_check(self):
        from . import controller, selection_filter
        from .smoke_selection import qwait
        ctl = controller.CONTROLLER
        m = selection_filter.manager()
        tf = self.shell.type_filter
        doc = App.getDocument(self._extrude_doc)

        def opened(timeout_ms=4000):
            t0 = time.monotonic()
            while (time.monotonic() - t0) * 1000 < timeout_ms:
                s = ctl.session
                if s is not None and s.stage == "parameterize" and controller._alive(s.box):
                    return True
                qwait(100)
            return False

        def state():
            s = ctl.session
            return {"busy": ctl.busy(), "stage": s.stage if s is not None else None,
                    "dialog": bool(Gui.Control.activeDialog()), "filter": m.global_kind,
                    "filter enabled": tf.isEnabled(), "last": ctl.history[-1:], "trace": ctl.trace[-4:]}

        def pick_sketch():
            """The sketch selected, then the Type Filter on Edge (which would refuse the sketch itself)."""
            tf.setCurrentIndex(0)
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(doc.Name, "Body", "Sketch.")
            tf.setCurrentIndex(tf.findData("edge"))

        try:
            up = opened()
            during = state()
            self.check("Extrude by its key (X) with a sketch selected and the Type Filter on Edge: the panel "
                       "opens, the filter is lifted and greyed out while it runs",
                       up and during["filter"] is None and during["filter enabled"] is False
                       and controller.CONTROLLER.session.sketch is not None
                       and controller.CONTROLLER.session.sketch.Name == "Sketch", during)
            ctl.cancel()
            qwait(500)
            after = state()
            pads = [o.Name for o in doc.Objects if o.TypeId == "PartDesign::Pad"]
            self.check("Extrude cancelled: the command ends, nothing is left, and the Type Filter (Edge) is back",
                       not after["busy"] and after["last"] and after["last"][0]["outcome"] == "cancelled"
                       and not pads and after["filter"] == "edge" and after["filter enabled"], after)

            # negative control: a start that fails ends the command; Extrude is not dead afterwards
            a = controller.ADAPTERS["Extrude"]

            def broken():
                raise RuntimeError("smoke: planted failure")

            pick_sketch()
            a.preselected_section = broken
            try:
                self.press("X")
                qwait(300)
            finally:
                del a.preselected_section
            failed = state()
            last = failed["last"][0] if failed["last"] else {}
            self.check("Extrude whose start fails: the command ends as failed with the reason, not left busy, "
                       "and the Type Filter is back",
                       not failed["busy"] and last.get("outcome") == "failed" and "planted failure" in
                       (last.get("note") or "") and failed["filter"] == "edge" and failed["filter enabled"], failed)
            pick_sketch()
            self.press("X")
            again = opened()
            ctl.cancel()
            qwait(500)
            self.check("Extrude runs again after a failed start", again and not ctl.busy(), state())

            # a build that lets the event loop run, as FreeCAD's recompute does through its progress bar: the
            # controller's poll fires meanwhile and must not end the command as having no section (tutorial AJ
            # step 7 ended 'cancelled ... no section' about one run in five)
            slow_build = a.build

            def slow(s, plan):
                qwait(450)                               # three poll intervals
                return slow_build(s, plan)

            pick_sketch()
            ended = len(ctl.history)
            a.build = slow
            try:
                self.press("X")
                built = opened()
            finally:
                del a.build
            raced = state()
            raced["ended meanwhile"] = ctl.history[ended:]
            self.check("Extrude whose build lets the event loop run: the poll does not end it, the panel opens",
                       built and not raced["ended meanwhile"], raced)
            if ctl.busy():
                ctl.cancel()
                qwait(500)
            elif Gui.Control.activeDialog():             # the race: a panel left open by an ended command
                if App.getActiveTransaction():
                    App.closeActiveTransaction(True)
                Gui.getDocument(doc.Name).resetEdit()
                Gui.Control.closeDialog()
                qwait(300)
        finally:
            if ctl.busy():
                ctl.cancel()
                qwait(300)
            tf.setCurrentIndex(0)
            Gui.Selection.clearSelection()
            App.closeDocument(doc.Name)
            before = self._extrude_before
            if before is not None and before.Name in App.listDocuments():
                App.setActiveDocument(before.Name)
                Gui.getDocument(before.Name)

    def s_model_views(self):
        """PMI model views: the eight look as FreeCAD's standard views do, and the work view filters PMI."""
        import Part
        from . import pmi_ui, pmi_views
        before = App.ActiveDocument
        doc = App.newDocument("SmokeViews")
        try:
            box = doc.addObject("Part::Feature", "Plate")
            box.Shape = Part.makeBox(80, 60, 10)
            doc.recompute()
            av = Gui.getDocument(doc.Name).ActiveView
            methods = {"Front": "viewFront", "Top": "viewTop", "Right": "viewRight", "Back": "viewRear",
                       "Bottom": "viewBottom", "Left": "viewLeft", "Isometric": "viewIsometric",
                       "Trimetric": "viewTrimetric"}
            off = []
            from .tutorial import qtest
            # a new 3D view sets its default orientation a moment after it opens, and that can undo the
            # first turn made at once (measured: Front read as Top in two runs): let it settle first
            same, last, t0 = 0, None, time.monotonic()
            while same < 5 and time.monotonic() - t0 < 4:
                qtest().qWait(100)
                q = tuple(round(c, 9) for c in av.getCameraOrientation().Q)
                same = same + 1 if q == last else 0
                last = q
            for name, method in methods.items():
                start = tuple(round(c, 9) for c in av.getCameraOrientation().Q)
                getattr(av, method)()
                last, t0 = None, time.monotonic()
                while time.monotonic() - t0 < 3:          # FreeCAD animates the turn: wait until it rests
                    qtest().qWait(100)
                    q = tuple(round(c, 9) for c in av.getCameraOrientation().Q)
                    # the turn may start a moment late: resting where it started is not resting yet
                    # (measured: Front read as the Top it came from), unless it was already there
                    if q == last and (q != start or time.monotonic() - t0 > 1.0):
                        break
                    last = q
                rot = av.getCameraOrientation()
                d, u = rot.multVec(App.Vector(0, 0, -1)), rot.multVec(App.Vector(0, 1, 0))
                want_d, want_u = pmi_views.STANDARD[name]
                _, up, _ = pmi_views.frame(want_d, want_u)
                if (d - App.Vector(*pmi_views._unit(want_d))).Length > 1e-4 or (u - App.Vector(*up)).Length > 1e-4:
                    off.append(f"{name}: FreeCAD dir {tuple(round(c, 6) for c in d)} up "
                               f"{tuple(round(c, 6) for c in u)}")
            self.check("the eight PMI model views look as FreeCAD's standard views do", not off, off)

            def face(pred):
                return "Face%d" % next(i for i, f in enumerate(box.Shape.Faces, 1) if pred(f))
            top = face(lambda f: abs(f.CenterOfMass.z - 10) < 1e-6)
            bottom = face(lambda f: abs(f.CenterOfMass.z) < 1e-6)
            left = face(lambda f: abs(f.CenterOfMass.x) < 1e-6)
            right = face(lambda f: abs(f.CenterOfMass.x - 80) < 1e-6)
            pmi_ui.folder(doc)
            views = {v.Label: v for v in pmi_ui.model_views(doc)}
            pmi_ui.activate(views["Top"])
            width = pmi_ui.create("Dimension", [(box, left), (box, right)], doc, DimensionType="Distance")
            pmi_ui.activate(views["Front"])
            datum = pmi_ui.create("Datum Feature", [(box, bottom)], doc, Letter="A")
            flat = pmi_ui.create("Feature Control Frame", [(box, top)], doc, Characteristic="Flatness",
                                 Tolerance=0.05)
            in_front = set(pmi_ui.activate(views["Front"]))
            last, t0 = None, time.monotonic()
            while time.monotonic() - t0 < 3:              # the turn is animated: wait until it rests
                qtest().qWait(100)
                q = tuple(round(c, 9) for c in av.getCameraOrientation().Q)
                if q == last:
                    break
                last = q
            rot = av.getCameraOrientation()
            camera_ok = (rot.multVec(App.Vector(0, 0, -1)) - App.Vector(0, 1, 0)).Length < 1e-6
            in_top = set(pmi_ui.activate(views["Top"]))
            pmi_ui.display_in_views([datum], [views["Top"], views["Front"]])
            in_top2 = set(pmi_ui.activate(views["Top"]))
            everything = set(pmi_ui.show_all(doc))
            ok = (len(views) == 8 and in_front == {datum.Name, flat.Name} and in_top == {width.Name}
                  and in_top2 == {width.Name, datum.Name} and everything == {width.Name, datum.Name, flat.Name}
                  and camera_ok and width.Views == [views["Top"]])
            self.check("model views: a PMI goes into the work view; switching hides the others; Display in Views",
                       ok, f"Front {sorted(in_front)}, Top {sorted(in_top)}, Top after copy {sorted(in_top2)}, "
                       f"all {sorted(everything)}, camera {camera_ok}")
        finally:
            App.closeDocument(doc.Name)
            if before is not None and before.Name in App.listDocuments():
                App.setActiveDocument(before.Name)
                Gui.getDocument(before.Name)

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
        self.ran.append(fn.__name__)
        QtCore.QTimer.singleShot(delay, self.next)

    def finish(self):
        from . import harness_result
        result = {"checks": self.checks, "info": self.info, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
        harness_result.write(os.path.join(OUT, "smoke.json"), "smoke", result, self.planned, self.ran)
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
