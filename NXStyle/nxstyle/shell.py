# SPDX-License-Identifier: LGPL-2.1-or-later
"""Builds the NX-style window around FreeCAD's main window.

Layout (top to bottom, left to right), following the NX textbooks:
    ribbon row     File button, Quick Access Toolbar, tabs, Command Finder
    ribbon page    groups of large / small buttons
    top border bar Menu button, Type Filter, Selection Scope, selection tools
    resource bar   vertical strip on the left: Part Navigator, History, ...
    graphics area  FreeCAD 3D view with NX colours and mouse behaviour
    status bar     cue line on the left
"""

import html
import os

import FreeCAD as App
import FreeCADGui as Gui

from . import (commands, config, navigation, navigator_status, nxt, prefs, ribbon_layout, selection_filter,
               shortcuts, theme)
from .finder import CommandFinder
from .qt import QtCore, QtGui, QtWidgets, Qt
from .ribbon import (CommandButton, Ribbon, command_action, command_actions, expand_tabs, known_commands,
                     provide_actions, resolve, spec_commands, spec_groups, sub_actions)
from .selection_filter import CurveRule, ScopeFilter, TypeFilter

OUR_TOOLBARS = {"NXRibbonBar", "NXTopBorderBar", "NXResourceBar"}
GLOBAL_TOOLBARS = {"File", "Edit", "Clipboard", "Workbench", "Macro", "View", "Individual views",
                   "Structure", "Help", "Navigation", "Selection"}
THEME_MARK = "/* NXStyle theme */"
LEFT_PANELS = ["Model", "Tasks", "NXHistory", "Selection view", "NxtModelPanel"]   # the last: --nxt
BOTTOM_PANELS = ["Report view", "Python console"]


class DockTitle(QtWidgets.QWidget):
    """Slim panel header: title on the left, close on the right."""

    def __init__(self, dock):
        super().__init__(dock)
        self.setObjectName("NXDockTitle")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 4, 2)
        self.label = QtWidgets.QLabel(dock.windowTitle())
        dock.windowTitleChanged.connect(self.label.setText)
        lay.addWidget(self.label, 1)
        close = QtWidgets.QToolButton(self)
        close.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_TitleBarCloseButton))
        close.setIconSize(QtCore.QSize(10, 10))
        close.setToolTip("Close")
        close.clicked.connect(dock.close)
        lay.addWidget(close)


class OverlayGuard(QtCore.QObject):
    """Hides an overlay frame as soon as it is shown if it only holds panels
    that NXStyle keeps docked on the left."""

    TITLES = {"Model", "Tasks", "NXHistory", "Selection view", "Part Navigator", "Dialog", "History",
              "Selection View"}

    def stale(self, tw):
        return all(tw.tabText(i) in self.TITLES for i in range(tw.count()))

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.Show and self.stale(obj):
            QtCore.QTimer.singleShot(0, obj.hide)
        return False


# Workbenches FreeCAD activates by itself when an object is edited
FOLLOWER_WORKBENCHES = {"SketcherWorkbench", "SpreadsheetWorkbench"}
DOCK_TITLES = {"Model": "Part Navigator", "Report view": "Information", "Python console": "Journal (Python)",
               "Tasks": "Dialog"}
QUICK_ACCESS = ["Std_New", "Std_Open", "Std_Save", "Std_Undo", "Std_Redo", "Std_Cut", "Std_Copy",
                "Std_Paste", "NXStyle_RepeatCommand"]
BORDER_TOOLS = [("Std_SelBack", "Previous Selection"), ("Std_SelForward", "Next Selection"),
                ("Std_BoxSelection", "Rectangle"), ("Std_BoxElementSelection", "Rectangle (Elements)"),
                ("Std_SelectAll", "Select All"), ("Std_TreeSelection", "Find in Navigator")]
CUE_IDLE = "Select objects and use MB3, or double-click an object"
CUE_IMMEDIATE_HIDE = "Immediate Hide: select objects to hide them. Esc = finish"
CUE_ROTATE = "Rotate: drag MB1 to rotate the view. Esc, MB2 or MB3 = finish"
CUE_DIALOG = "Set the dialog options. MB2 = OK, Esc = Cancel"
CUE_SKETCH = "Sketch: choose a curve or constraint tool, or select curves. Ctrl+Q = Finish Sketch"
LAYOUT_PARAM = "User parameter:BaseApp/Preferences/Mod/NXStyle"

_shell = None


def instance():
    return _shell


def switch_application(app_id):
    if _shell:
        _shell.switch_application(app_id)


def toggle_native_ui():
    if _shell:
        _shell.toggle_native_ui()


def load_apps():
    data = config.load_json("ribbons", "apps.json")
    available = set(Gui.listWorkbenches())
    groups, flat = [], []
    for g in data["groups"]:
        apps = [a for a in g["apps"] if a["workbench"] in available]
        if apps:
            groups.append((g["name"], apps))
            flat += apps
    return groups, flat


class Shell(QtCore.QObject):
    def __init__(self):
        super().__init__(Gui.getMainWindow())
        self.mw = Gui.getMainWindow()
        self.cfg = config.get()
        self.app_groups, self.apps = load_apps()
        self.current_app = None
        self.native_ui = False
        self._loading = False
        self._preloaded = set()
        self._tracked = set()
        self.ready = False
        self.shortcut_rows = []
        self.touch_mode = False
        self.setup_errors = []
        self._nav_state = None
        self._ticks = 0
        self._overlay_guard = OverlayGuard(self)
        self._last_sketch = None
        self._pending_idle = 0
        self._known_docs = set(App.listDocuments())
        self._waiting_docs = {}        # new empty documents not yet active: ticks waited
        self._guide_states = None      # last workflow step states shown on a guided ribbon

    # ================================================================ setup
    def setup(self):
        steps = [self._prefs, self._apply_theme, self._register_commands, self._build_ribbon_bar, self._build_border_bar,
                 self._build_resource_bar, self._arrange_docks, self._navigator_status, self._build_cue_line,
                 self._navigation, self._precise_input]
        for step in steps:
            try:
                step()
            except Exception:
                import traceback
                self.setup_errors.append(traceback.format_exc())
                App.Console.PrintError(f"NXStyle: {step.__name__} failed\n{traceback.format_exc()}\n")
        self.mw.workbenchActivated.connect(self._on_workbench)
        default = self.cfg.get("default_application", "modeling")
        self.switch_application(default if self._app(default) else self.apps[0]["id"])
        try:
            if self.cfg.get("nx_shortcuts", True):
                self.shortcut_rows = shortcuts.apply(self)
                shortcuts.report(self.shortcut_rows)
        except Exception:
            import traceback
            self.setup_errors.append(traceback.format_exc())
        self._track_commands()
        self._reclaim_keys()
        self.watch = QtCore.QTimer(self)
        self.watch.timeout.connect(self._tick)
        self.watch.start(300)
        self.enforce_ui()
        try:
            from . import plm
            plm.attach(self)
        except Exception:
            import traceback
            self.setup_errors.append(traceback.format_exc())
        self.ready = True
        App.Console.PrintLog("NXStyle: ready\n")

    def _prefs(self):
        prefs.apply(self.cfg)
        prefs.apply_navigation_to_open_views(self.cfg)

    def _register_commands(self):
        names = commands.register(self.apps)
        if not all(command_actions(n) for n in names):
            self.reactivate_workbench()        # so FreeCAD builds the global toolbar
        missing = [n for n in names if not command_actions(n)]
        if missing:
            App.Console.PrintWarning(f"NXStyle: no QAction for {missing}\n")
        # Application buttons get their workbench's icon (from Std_Workbench's entries)
        wb_actions = sub_actions()
        for app in self.apps:
            acts = command_actions(f"NXStyle_App_{app['id']}")
            src = wb_actions.get(app["workbench"])
            icon = src.icon() if src is not None else self._workbench_icon(app["workbench"])
            if acts and icon is not None and not icon.isNull():
                acts[0].setIcon(icon)

    def reactivate_workbench(self):
        """Activate the current workbench again: FreeCAD rebuilds its toolbars, the custom ones included, and makes
        the actions of the commands they hold. Not while a task dialog is open (sketch edit): FreeCAD then makes
        them at the next activation."""
        if Gui.Control.activeDialog():
            return
        # hidden first, as on every application switch: FreeCAD saves the toolbars' visibility when the workbench is
        # left (and restores it when that setting changes); otherwise FEM's toolbars came back after enforce_ui
        # (measured, with Workbench.reloadActive() as well)
        if not self.native_ui and self.cfg.get("hide_native_toolbars", True):
            for tb in self.native_toolbars():
                tb.hide()
        current = Gui.activeWorkbench().name()
        self._loading = True
        try:
            Gui.activateWorkbench("NoneWorkbench")
            Gui.activateWorkbench(current)
        finally:
            self._loading = False

    @staticmethod
    def _workbench_icon(name):
        """Icon file declared by the workbench (Assembly is missing from Std_Workbench in 1.0)."""
        wb = Gui.listWorkbenches().get(name)
        path = getattr(wb, "Icon", "") if wb is not None else ""
        if isinstance(path, str) and os.path.isfile(path):
            return QtGui.QIcon(path)
        return None

    def _app(self, app_id):
        return next((a for a in self.apps if a["id"] == app_id), None)

    # -------------------------------------------------------------- ribbon
    def _toolbar(self, name, title):
        tb = QtWidgets.QToolBar(title, self.mw)
        tb.setObjectName(name)
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.toggleViewAction().setVisible(False)
        return tb

    def _build_ribbon_bar(self):
        self.ribbon = Ribbon()
        self.ribbon.on_run = commands.remember
        self.ribbon.store = ribbon_layout.LayoutStore(config.profile_dir())
        if self.ribbon.store.error:
            App.Console.PrintWarning(f"NXStyle: {self.ribbon.store.error}\n")
        self.ribbon.set_collapsed(self.ribbon.store.minimized, save=False)
        self.mw.installEventFilter(self)
        tb = self._toolbar("NXRibbonBar", "Ribbon")
        tb.setStyleSheet("QToolBar { border: none; padding: 0px; margin: 0px; spacing: 0px; }")
        tb.addWidget(self.ribbon)
        self.ribbon.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.mw.addToolBar(Qt.TopToolBarArea, tb)
        self.mw.addToolBarBreak(Qt.TopToolBarArea)
        self.ribbon_bar = tb
        self.finder = CommandFinder(self.ribbon, on_run=commands.remember)
        self.ribbon.corner.addWidget(self.finder)
        self._file_menu = QtWidgets.QMenu(self.ribbon.file_button)
        self._file_menu.aboutToShow.connect(self._fill_file_menu)
        self.ribbon.file_button.setMenu(self._file_menu)
        known = known_commands()
        for name in QUICK_ACCESS:
            if name in known:
                self.ribbon.qat.addWidget(self._icon_button(name))

    # A main window less high than this (logical pixels, e.g. 1366x768 at 200 %) minimises the ribbon to
    # its tab row; a tab then drops its page down over the graphics window.
    AUTO_MINIMIZE_BELOW = 420

    def eventFilter(self, obj, ev):
        if obj is self.mw and ev.type() == QtCore.QEvent.Resize:
            # Font/theme spacing can lift Qt's expanded minimum above the usual
            # breakpoint. Collapse before that minimum traps a small window.
            # Retain it while collapsed so the lower minimum cannot cause oscillation.
            if not self.ribbon.is_collapsed():
                self._ribbon_auto_threshold = max(self.AUTO_MINIMIZE_BELOW,
                                                  self.mw.minimumSizeHint().height() + 24)
            threshold = getattr(self, "_ribbon_auto_threshold", self.AUTO_MINIMIZE_BELOW)
            self.ribbon.set_auto_minimized(self.mw.height() < threshold)
        return False

    # An add-on panel docked with the navigators (Strata's needs 383 px) sets the whole window's minimum
    # height, since tabbed panels share the tallest minimum: at 1366x768 and 125 % the window then no longer
    # fits the screen. Such a panel scrolls instead. Only panels NXStyle itself places among the navigators
    # and that never look their content up through the dock (Strata sets it once): FreeCAD's own panels and
    # Katydid's canvas are reached through dock.widget(), so they are left as they are.
    TALL_PANEL = 200
    SCROLL_PANELS = {"StrataPanel"}

    def scroll_tall_docks(self):
        """Put the content of a tall hosted panel in a scroll area; returns the panels wrapped now."""
        wrapped = []
        for d in self.mw.findChildren(QtWidgets.QDockWidget):
            w = d.widget()
            if (w is None or d.objectName() not in self.SCROLL_PANELS or isinstance(w, QtWidgets.QScrollArea)
                    or w.minimumSizeHint().height() <= self.TALL_PANEL):
                continue
            area = QtWidgets.QScrollArea(d)
            area.setObjectName("NXDockScroll")
            area.setWidgetResizable(True)
            area.setFrameShape(QtWidgets.QFrame.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            area.setWidget(w)
            d.setWidget(area)
            wrapped.append(d.objectName())
        return wrapped

    def _icon_button(self, name, label=None):
        b = CommandButton(name, label or name, "small", on_run=commands.remember)
        b.setToolButtonStyle(Qt.ToolButtonIconOnly)
        return b

    def _menubar_menus(self):
        for act in self.mw.menuBar().actions():
            if act.menu() is not None and act.text():
                yield act.menu()

    def _fill_file_menu(self):
        m = self._file_menu
        m.clear()
        menus = list(self._menubar_menus())
        if menus:
            m.addActions(menus[0].actions())
        m.addSeparator()
        for name in ("Std_DlgPreferences", "Std_DlgCustomize"):
            acts = command_actions(name)
            if acts:
                m.addAction(acts[0])

    def build_ribbon(self, app):
        r = self.ribbon
        r.clear()
        r.app_id = app.get("id", "")
        r.essential = set()
        known = known_commands()
        tabs = []
        if app.get("ribbon"):
            spec = config.load_json("ribbons", app["ribbon"])
            self.preload(spec.get("preload", []))
            known = known_commands()
            tabs = expand_tabs(spec)
            r.essential = {c for c in (resolve(e, known) for e in spec.get("essential", [])) if c}
        else:
            tabs = [{"name": app["title"], "groups": None}] + expand_tabs(
                {"tabs": [{"include": "common:View"}, {"include": "common:Tools"},
                          {"include": "common:Application"}]})
        pages = []
        for t in tabs:
            if t.get("requires") and not any(c in known for c in t["requires"]):
                continue                     # e.g. the PLM tab without the Strata add-on
            if t["name"] == "Application":
                groups = self._application_groups()
            elif t.get("groups") is None:
                groups = self._auto_groups()
            else:
                groups = spec_groups(t)
            pages.append((t["name"], groups))
        # once for the application, the Sketch tab included: the workbench is activated again, so not in sketch edit
        sketch = spec_groups(config.load_json("ribbons", "sketch.json")["tabs"][0])
        provide_actions([c for _name, groups in pages + [("Sketch", sketch)] for c in spec_commands(groups, known)],
                        self.reactivate_workbench)
        for name, groups in pages:
            r.add_tab(name, groups, known=known)
        if not r.select(app.get("first_tab", "")):
            r.tabs.setCurrentIndex(0)
        self._sketch_tab(navigation.in_sketch_edit(), force=True)
        self.finder.invalidate()
        self._guide_states = None
        self.update_guide()

    def update_guide(self):
        """Guided applications (Simulation): mark the workflow steps on the ribbon done or next."""
        if not (self.current_app or {}).get("guide") == "fem":
            return None
        from . import fem_guide
        states = fem_guide.states(fem_guide.active_members())
        if states != getattr(self, "_guide_states", None):
            self.ribbon.set_steps(states)
            self._guide_states = states
        return states

    def _application_groups(self):
        groups = []
        for gname, apps in self.app_groups:
            items = [{"cmd": f"NXStyle_App_{a['id']}", "label": a["title"], "size": "large"} for a in apps]
            groups.append((gname, items))
        groups.append(("User Interface", [{"cmd": "NXStyle_ToggleNativeUI", "label": "FreeCAD Menus and Toolbars"}]))
        return groups

    def _auto_groups(self):
        """Ribbon groups from the active workbench's own toolbars."""
        wb = Gui.activeWorkbench()
        groups = []
        try:
            items = wb.getToolbarItems()
        except Exception:
            items = {}
        for tbname, cmds in items.items():
            if tbname in GLOBAL_TOOLBARS:
                continue
            entries = []
            for i, c in enumerate([c for c in cmds if c and c != "Separator"]):
                entries.append({"cmd": c, "label": self._freecad_label(c), "size": "large" if i == 0 else "small"})
            if entries:
                groups.append((tbname, entries))
        return groups

    @staticmethod
    def _freecad_label(name):
        act = command_action(name)
        if act is not None:
            from .ribbon import clean_text
            return clean_text(act.text()) or name
        return name

    def preload(self, workbenches):
        """Activate workbenches once so their commands exist (NX has no workbenches)."""
        todo = [w for w in workbenches if w not in self._preloaded and w in Gui.listWorkbenches()]
        if not todo:
            return
        current = Gui.activeWorkbench().name()
        self._loading = True
        try:
            for w in todo:
                try:
                    Gui.activateWorkbench(w)
                except Exception as e:
                    App.Console.PrintWarning(f"NXStyle: could not load {w}: {e}\n")
                self._preloaded.add(w)
            Gui.activateWorkbench(current)
        finally:
            self._loading = False
        self._track_commands()
        self._reclaim_keys()

    # ------------------------------------------------------- applications
    def switch_application(self, app_id):
        app = self._app(app_id)
        if app is None:
            return
        # Switching rebuilds the ribbon, deleting the button that was clicked; the focus then lands
        # on another document's window and FreeCAD makes that part active (measured: Ctrl+N, then
        # Application > Modeling, went back to the previous part). Keep the part the user is in.
        mdi = self.mw.findChild(QtWidgets.QMdiArea)
        active = mdi.activeSubWindow() if mdi is not None else None
        try:
            self._switch_application(app)
        finally:
            if active is not None:
                def keep():
                    try:
                        if mdi.activeSubWindow() is not active and active in mdi.subWindowList():
                            mdi.setActiveSubWindow(active)
                    except RuntimeError:        # the window was closed meanwhile
                        pass
                keep()
                QtCore.QTimer.singleShot(0, keep)

    def _switch_application(self, app):
        self.current_app = app
        if Gui.activeWorkbench().name() != app["workbench"]:
            self._loading = True
            try:
                Gui.activateWorkbench(app["workbench"])
            finally:
                self._loading = False
        self._preloaded.add(app["workbench"])
        self.build_ribbon(app)
        self.enforce_ui()
        self._track_commands()
        self._reclaim_keys()
        self._navigator_after_switch()

    def _navigator_after_switch(self):
        """NX shows the Part Navigator after an application switch unless a dialog is open. _tick only
        raises it when (dialog, documents) changes, which a switch does not; forgetting the state makes
        the next tick check again, after FreeCAD has finished activating the workbench."""
        try:
            dialog = bool(Gui.Control.activeDialog())
        except Exception:
            dialog = False
        if not dialog:
            self.show_part_navigator()
        self._nav_state = None

    def _on_workbench(self, name):
        if self._loading:
            return
        QtCore.QTimer.singleShot(0, lambda: self._after_workbench(name))

    def _after_workbench(self, name):
        if name in FOLLOWER_WORKBENCHES and self.current_app is not None:
            # FreeCAD switched on its own (editing a sketch or a sheet); NX would
            # stay in the current application, and the ribbon commands still work.
            self.enforce_ui()
            return
        if self.current_app is None or self.current_app["workbench"] != name:
            app = next((a for a in self.apps if a["workbench"] == name), None)
            if app is None:
                app = {"id": name, "title": name.replace("Workbench", ""), "workbench": name, "ribbon": None}
            self.current_app = app
            self.build_ribbon(app)
        self.enforce_ui()
        self._track_commands()
        self._reclaim_keys()
        self._navigator_after_switch()

    # ---------------------------------------------------------- border bar
    def _build_border_bar(self):
        tb = self._toolbar("NXTopBorderBar", "Top Border Bar")
        tb.setIconSize(QtCore.QSize(16, 16))
        menu_button = QtWidgets.QToolButton(tb)
        menu_button.setObjectName("NXMenuButton")
        menu_button.setText("Menu")
        menu_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        menu_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu_button.setMinimumWidth(68)
        menu_button.setStyleSheet("QToolButton { padding: 2px 18px 2px 8px; }")
        self._menu = QtWidgets.QMenu(menu_button)
        self._menu.aboutToShow.connect(self._fill_menu)
        menu_button.setMenu(self._menu)
        tb.addWidget(menu_button)
        tb.addSeparator()
        self.type_filter = TypeFilter(tb)
        tb.addWidget(self.type_filter)
        self.scope_filter = ScopeFilter(tb)
        tb.addWidget(self.scope_filter)
        self.curve_rule = CurveRule(tb)
        tb.addWidget(self.curve_rule)
        tb.addSeparator()
        known = known_commands()
        for name, label in BORDER_TOOLS:
            if name in known:
                tb.addWidget(self._icon_button(name, label))
        clear = QtWidgets.QToolButton(tb)
        clear.setText("Deselect All")
        clear.setToolTip("Deselect All (Esc)")
        clear.setAutoRaise(True)
        clear.clicked.connect(lambda: Gui.Selection.clearSelection())
        tb.addWidget(clear)
        self.mw.addToolBar(Qt.TopToolBarArea, tb)
        self.border_bar = tb

    def _fill_menu(self):
        self._menu.clear()
        for m in self._menubar_menus():
            self._menu.addMenu(m)

    # -------------------------------------------------------- resource bar
    def _build_resource_bar(self):
        tb = self._toolbar("NXResourceBar", "Resource Bar")
        tb.setOrientation(Qt.Vertical)
        tb.setIconSize(QtCore.QSize(22, 22))
        self._build_history_dock()
        entries = [
            ("Part Navigator", "Model", "navigator"),
            ("History", "NXHistory", "history"),
            ("Information", "Report view", "information"),
            ("Journal (Python)", "Python console", "journal"),
            ("Selection", "Selection view", "selection"),
        ]
        self.resource_actions = {}
        for title, dock_name, icon_name in entries:
            dock = self.mw.findChild(QtWidgets.QDockWidget, dock_name)
            if dock is None:
                continue
            icon = QtGui.QIcon(config.resource("icons", f"{icon_name}.svg"))
            act = dock.toggleViewAction()
            act.setIcon(icon)
            act.setText(title)
            act.setToolTip(title)
            tb.addAction(act)
            self.resource_actions[title] = act
        self.mw.addToolBar(Qt.LeftToolBarArea, tb)
        self.resource_bar = tb

    def _build_history_dock(self):
        dock = QtWidgets.QDockWidget("History", self.mw)
        dock.setObjectName("NXHistory")
        lst = QtWidgets.QListWidget(dock)
        lst.setObjectName("NXHistoryList")
        lst.itemActivated.connect(self._open_history_item)
        dock.setWidget(lst)
        dock.visibilityChanged.connect(lambda vis: vis and self._fill_history())
        self.mw.addDockWidget(Qt.LeftDockWidgetArea, dock)
        dock.hide()
        self.history_dock = dock

    def _fill_history(self):
        lst = self.history_dock.widget()
        lst.clear()
        p = App.ParamGet("User parameter:BaseApp/Preferences/RecentFiles")
        for i in range(max(p.GetInt("RecentFiles", 4), 12)):
            path = p.GetString(f"MRU{i}")
            if path:
                item = QtWidgets.QListWidgetItem(os.path.basename(path))
                item.setToolTip(path)
                item.setData(Qt.UserRole, path)
                lst.addItem(item)
        if not lst.count():
            item = QtWidgets.QListWidgetItem("No recently opened parts yet.\nFiles you open appear here.")
            item.setFlags(Qt.NoItemFlags)
            lst.addItem(item)

    def _open_history_item(self, item):
        path = item.data(Qt.UserRole)
        if not path or not os.path.exists(path):
            return
        if path.lower().endswith(".fcstd"):
            App.openDocument(path)
        else:
            Gui.open(path)

    # --------------------------------------------------------------- docks
    def _arrange_docks(self):
        for dock in self.mw.findChildren(QtWidgets.QDockWidget):
            title = DOCK_TITLES.get(dock.objectName())
            if title:
                dock.setWindowTitle(title)
        p = App.ParamGet(LAYOUT_PARAM)
        if not p.GetBool("LayoutInitialized", False):
            # NX starts with only the navigator open; the rest is one click away
            for name in ("Report view", "Python console", "Selection view"):
                d = self.mw.findChild(QtWidgets.QDockWidget, name)
                if d is not None:
                    d.hide()
            model = self.mw.findChild(QtWidgets.QDockWidget, "Model")
            if model is not None:
                model.show()
                model.raise_()
            p.SetBool("LayoutInitialized", True)
        self._style_docks()
        tasks = self.mw.findChild(QtWidgets.QDockWidget, "Tasks")
        if tasks is not None and self.cfg.get("floating_task_panel"):
            tasks.setFloating(True)
            central = self.mw.centralWidget()
            origin = central.mapToGlobal(QtCore.QPoint(12, 12)) if central else QtCore.QPoint(80, 200)
            tasks.setGeometry(origin.x(), origin.y(), 340, 520)

    def _style_docks(self):
        """One tab strip for the left panels (the tabs are their headers, as in
        NX's navigators); a slim header for the bottom panels; document tabs
        above the graphics window."""
        find = lambda n: self.mw.findChild(QtWidgets.QDockWidget, n)  # noqa: E731
        model = find("Model")
        self.mw.setTabPosition(Qt.LeftDockWidgetArea, QtWidgets.QTabWidget.North)
        self.mw.setTabPosition(Qt.BottomDockWidgetArea, QtWidgets.QTabWidget.North)
        if model is not None:
            for name in LEFT_PANELS[1:]:
                d = find(name)
                if d is not None and not d.isFloating():
                    self.mw.tabifyDockWidget(model, d)
        self._blank_titles()
        for name in BOTTOM_PANELS:
            d = find(name)
            if d is not None and (d.titleBarWidget() is None or d.titleBarWidget().objectName() != "NXDockTitle"):
                d.setTitleBarWidget(DockTitle(d))
        mdi = self.mw.findChild(QtWidgets.QMdiArea)
        if mdi is not None:
            mdi.setTabPosition(QtWidgets.QTabWidget.North)
        self._hide_stale_overlays()
        self.show_part_navigator()

    def _hide_stale_overlays(self):
        """An overlay frame that only lists panels NXStyle docks itself is an
        empty box over the 3D view (FreeCAD 1.1 default layout). Hide it now
        and whenever FreeCAD shows it again (e.g. when a dialog opens)."""
        for tw in self.mw.findChildren(QtWidgets.QTabWidget):
            if not tw.objectName().startswith("Overlay"):
                continue
            if not tw.property("nxGuarded"):
                tw.installEventFilter(self._overlay_guard)
                tw.setProperty("nxGuarded", True)
            if tw.isVisible() and self._overlay_guard.stale(tw):
                tw.hide()

    def _blank_titles(self):
        for name in LEFT_PANELS:
            d = self.mw.findChild(QtWidgets.QDockWidget, name)
            if d is None or d.isFloating():
                continue
            tw = d.titleBarWidget()
            if tw is None or tw.objectName() != "NXNoTitle":
                blank = QtWidgets.QWidget(d)
                blank.setObjectName("NXNoTitle")
                blank.setFixedHeight(0)
                d.setTitleBarWidget(blank)

    # --------------------------------------------------------------- theme
    def _apply_theme(self):
        if self.cfg.get("theme", "nx") != "nx":
            return
        app = QtWidgets.QApplication.instance()
        dirs = [os.path.join(App.getUserAppDataDir(), "Gui", "Stylesheets"),
                os.path.join(App.getResourceDir(), "Gui", "Stylesheets")]
        QtCore.QDir.setSearchPaths("qss", [d for d in dirs if os.path.isdir(d)] + list(QtCore.QDir.searchPaths("qss")))
        base = app.styleSheet().split(THEME_MARK)[0]
        if len(base) < 1000:
            # FreeCAD has not applied its own theme yet (first start of a fresh
            # profile on 1.0): load the file ourselves. Once FreeCAD has loaded
            # it, it is already resolved (1.1 computes its values from YAML).
            name = prefs.base_stylesheet(self.cfg)
            for d in dirs:
                path = os.path.join(d, name) if name else ""
                if path and os.path.isfile(path):
                    with open(path, encoding="utf-8") as f:
                        base = f.read()
                    break
        # FreeCAD fills its placeholders when it loads a stylesheet itself; an
        # unfilled one makes Qt drop the rules around it. Use the NX accent tints.
        app.setStyleSheet(theme.fill_freecad(base) + "\n" + theme.stylesheet("nx_theme.qss"))

    def theme_active(self):
        return THEME_MARK in QtWidgets.QApplication.instance().styleSheet()

    # ------------------------------------------------------------ cue line
    def _build_cue_line(self):
        self.cue = QtWidgets.QLabel(CUE_IDLE)
        self.cue.setObjectName("NXCueLine")
        self.cue.setStyleSheet(f"QLabel#NXCueLine {{ color: {theme.color('accent')}; padding-left: 6px; }}")
        self.mw.statusBar().insertWidget(0, self.cue, 1)

    def _navigation(self):
        self.navigation = navigation.NavigationManager(self)

    def _precise_input(self):
        """Typed lengths keep their decimals in FreeCAD's quantity fields (nxstyle/precise_input.py)."""
        from . import precise_input
        self.precise_input = precise_input.install()

    def _navigator_status(self):
        """Work part, active body, suppressed and failed features above the Part Navigator's tree."""
        self.navigator_status = navigator_status.attach(self.mw)
        if self.navigator_status is None:
            raise RuntimeError("Part Navigator: FreeCAD's tree panel was not found, so no status strip")

    # ======================================================== periodic work
    def _edited_sketch(self):
        try:
            vp = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument else None
            obj = vp.Object if vp is not None else None
            return obj if obj is not None and obj.isDerivedFrom("Sketcher::SketchObject") else None
        except Exception:
            return None

    def _feature_flow(self):
        """Finish Sketch inside NX Extrude/Revolve carries on into the feature."""
        sk = self._edited_sketch()
        if sk is not None:
            self._last_sketch = sk
            if commands.pending_feature["command"]:
                commands.pending_feature["sketch"] = sk
            return
        if self._last_sketch is not None:
            done, self._last_sketch = self._last_sketch, None
            if commands.pending_feature["command"] and commands.pending_feature["sketch"] is done:
                QtCore.QTimer.singleShot(0, lambda: commands.continue_pending_feature(done))
                return
        # a pending feature whose sketch never started (plane pick cancelled)
        if commands.pending_feature["command"] and commands.pending_feature["sketch"] is None:
            try:
                busy = bool(Gui.Control.activeDialog())
            except Exception:
                busy = False
            self._pending_idle = 0 if busy else self._pending_idle + 1
            if self._pending_idle > 10:
                commands.pending_feature["command"] = None
                self._pending_idle = 0

    def _activate_document(self, doc):
        """Make doc the active document by activating its 3D window; True when it is active."""
        mdi = self.mw.findChild(QtWidgets.QMdiArea)
        gdoc = Gui.getDocument(doc.Name)
        for sub in mdi.subWindowList() if mdi is not None else []:
            title = sub.windowTitle()
            if title.split(" : ")[0].rstrip("*") in (doc.Label, doc.Name):
                mdi.setActiveSubWindow(sub)
                break
        QtWidgets.QApplication.processEvents()
        if App.ActiveDocument is not doc:
            App.setActiveDocument(doc.Name)
            try:
                Gui.ActiveDocument = gdoc
            except Exception:
                pass
        return App.ActiveDocument is doc and Gui.ActiveDocument is not None \
            and Gui.ActiveDocument.Document is doc

    def _new_part_template(self):
        """NX's Model template starts with a datum coordinate system; give a new
        empty document a Body ready to sketch on. In the Assemblies application
        the new document gets an empty Assembly instead (NX's Assembly template)."""
        names = set(App.listDocuments())
        new = names - self._known_docs
        if not self.cfg.get("new_part_datum", True) or not self.current_app \
                or self.current_app.get("id") not in ("modeling", "assemblies"):
            self._known_docs = names
            return
        for name in new:
            doc = App.getDocument(name)
            gdoc = Gui.getDocument(name)
            if doc.Objects or doc.FileName:
                self._known_docs.add(name)
                continue
            views = gdoc.mdiViewsOfType("Gui::View3DInventor") if gdoc else []
            if not views:
                continue          # view not ready yet: try again on the next tick
            if App.ActiveDocument is not doc:
                # File > New makes the new part the active one, but when other documents were just
                # opened by a script their deferred activation can take the focus back (measured,
                # FreeCAD 1.1.4: the new part stayed inactive behind the last opened one). After a
                # few ticks, bring the new part's window to the front as clicking its tab would.
                waited = self._waiting_docs.get(name, 0) + 1
                self._waiting_docs[name] = waited
                if waited < 3 or not self._activate_document(doc):
                    continue
            self._waiting_docs.pop(name, None)
            if self.current_app.get("id") == "assemblies":
                # NX's Assembly template: an empty assembly, ready for Add Component
                Gui.runCommand("Assembly_CreateAssembly")
            else:
                # The origin planes stay hidden: in FreeCAD 1.1.4 a visible Body origin
                # makes the whole Body vanish from the 3D view after a view fit (seen in
                # plain FreeCAD too). FreeCAD shows the planes while you pick a sketch plane.
                Gui.runCommand("PartDesign_Body")
            self._known_docs.add(name)
        self._known_docs &= names
        self._waiting_docs = {k: v for k, v in self._waiting_docs.items() if k in names}

    def _tick(self):
        self._feature_flow()
        self._new_part_template()
        sketch = navigation.in_sketch_edit()
        self._sketch_tab(sketch)
        try:
            dialog = bool(Gui.Control.activeDialog())
        except Exception:
            dialog = False
        gates = selection_filter.manager()
        try:
            gates.sync()
        except Exception as e:
            App.Console.PrintWarning(f"NXStyle selection: {e}\n")
        text = CUE_SKETCH if sketch else CUE_DIALOG if dialog else CUE_IDLE
        refused = gates.recent_rejection()
        if commands.immediate_hide.active:
            text = CUE_IMMEDIATE_HIDE
        elif getattr(self, "navigation", None) is not None and self.navigation.mode == "rotate":
            text = CUE_ROTATE
        elif refused:      # why the pick under the cursor (or the last one) was not taken
            text = f"<span style='color:#C62828'>{html.escape(refused)}</span>"
        if self.cue.text() != text:
            self.cue.setText(text)
        if nxt.expected():
            nxt.tick(self)             # FreeCAD-Nxt's toolbar hidden, its panel the Part Navigator, once they are up
        if getattr(self, "navigator_status", None) is not None:
            try:
                self.navigator_status.refresh()
            except Exception as e:
                App.Console.PrintWarning(f"NXStyle Part Navigator status: {e}\n")
        # NX keeps the Part Navigator in front; FreeCAD leaves its (often empty)
        # Tasks panel in front after start-up, new documents and closed dialogs.
        self._ticks += 1
        if self._ticks % 5 == 0:   # FreeCAD may re-apply its own stylesheet or dock headers
            try:
                self.update_guide()
                self.scroll_tall_docks()
            except Exception as e:
                App.Console.PrintLog(f"NXStyle: workflow guide / panels: {e}\n")
            if self.cfg.get("theme", "nx") == "nx" and not self.theme_active():
                self._apply_theme()
            self._blank_titles()
            self._hide_stale_overlays()
            self.hide_stray_tab_bars()
            self.label_navigation()
        state = (dialog, len(App.listDocuments()))
        if state != self._nav_state:
            if not dialog:
                self.show_part_navigator()
            self._nav_state = state

    NAV_LABEL = "NX (NXStyle)"

    def label_navigation(self):
        """FreeCAD's status bar names its navigation style, here Blender, the base NXStyle's own mouse
        handling sits on (MB2, the MB3 hold, MB2 = OK); it would tell the user the wrong mouse model. While
        NXStyle handles the mouse the button says so; its menu still switches FreeCAD's style. Returns the
        relabelled widgets (for tests)."""
        from . import prefs
        if not prefs.uses_own_navigation(self.cfg):
            return []
        base = prefs.NX_BASE_STYLE.split("::")[-1].replace("NavigationStyle", "")      # "Blender"
        out = []
        bar = self.mw.statusBar()
        for w in bar.findChildren(QtWidgets.QAbstractButton) + bar.findChildren(QtWidgets.QLabel):
            try:
                if w.text().strip() == base:          # FreeCAD pads the name with spaces
                    w.setText(self.NAV_LABEL)
                    w.setToolTip("Mouse: NXStyle's NX handling (MB2 rotates, MB2 click is OK, hold MB3 for the radial "
                                 f"menu) on top of FreeCAD's {base} navigation style, which supplies the rest")
                    out.append(w)
            except RuntimeError:
                continue
        return out

    def hide_stray_tab_bars(self):
        """A dock area's tab strip is only needed for two or more tabbed panels. When panels move
        (FreeCAD's Tasks/overlay handling, Strata's panel joining the navigators) Qt can leave an
        empty one painted over the Top Border Bar. Spare ones Qt parks off-screen are left alone."""
        hidden = []
        for tb in self.mw.findChildren(QtWidgets.QTabBar):
            if (tb.parentWidget() is self.mw and tb.isVisible() and tb.count() < 2
                    and tb.geometry().intersects(self.mw.rect())):
                hidden.append(tb.geometry().getRect())
                tb.hide()
        return hidden

    def show_part_navigator(self):
        model = nxt.navigator_dock() or self.mw.findChild(QtWidgets.QDockWidget, "Model")
        if model is not None and model.isVisible():
            model.raise_()

    def current_left_tab(self):
        """Title of the front tab among the left dock panels (for tests)."""
        for bar in self.mw.findChildren(QtWidgets.QTabBar):
            texts = [bar.tabText(i) for i in range(bar.count())]
            if "Part Navigator" in texts:
                return bar.tabText(bar.currentIndex())
        return None

    def _sketch_tab(self, active, force=False):
        has = self.ribbon.has_tab("Sketch")
        if active and (not has or force):
            if has:
                self.ribbon.remove_tab("Sketch")
            spec = config.load_json("ribbons", "sketch.json")["tabs"][0]
            self.ribbon.add_tab("Sketch", spec_groups(spec), index=0, contextual=True)
            self.ribbon.tabs.setCurrentIndex(0)
            self.finder.invalidate()
        elif not active and has:
            self.ribbon.remove_tab("Sketch")
            self.ribbon.select("Home")
            self.finder.invalidate()

    def _track_commands(self):
        """Remember the last command run from anywhere, for Repeat Command (F4)."""
        for name in Gui.listCommands():
            if name in self._tracked:
                continue
            act = command_action(name)
            if act is None:
                continue
            try:
                act.triggered.connect(lambda _=False, n=name: commands.remember(n))
            except RuntimeError:            # a stale Qt wrapper must not stop the shell's start; tried again later
                continue
            self._tracked.add(name)

    def _reclaim_keys(self):
        """Newly loaded workbenches bring their own shortcuts; take the NX keys back."""
        inst = shortcuts.instance()
        if inst is not None:
            inst.reapply()

    def set_touch_mode(self, on):
        """NX Touch Mode: bigger icons on the ribbon and the bars."""
        from . import ribbon
        self.touch_mode = on
        ribbon.LARGE, ribbon.SMALL = (44, 24) if on else (32, 16)
        bar_icon = QtCore.QSize(24 if on else 16, 24 if on else 16)
        for bar in (self.ribbon.qat, self.border_bar):
            bar.setIconSize(bar_icon)
            for b in bar.findChildren(QtWidgets.QToolButton):
                b.setIconSize(bar_icon)
        self.resource_bar.setIconSize(QtCore.QSize(32 if on else 22, 32 if on else 22))
        current = self.ribbon.tabs.tabText(self.ribbon.tabs.currentIndex())
        if self.current_app is not None:
            self.build_ribbon(self.current_app)
            self.ribbon.select(current)
        status = "on" if on else "off"
        self.mw.statusBar().showMessage(f"Touch Mode {status}", 2500)

    # ===================================================== native UI toggle
    def native_toolbars(self):
        for tb in self.mw.findChildren(QtWidgets.QToolBar):
            if tb.objectName() in OUR_TOOLBARS or tb.parentWidget() != self.mw:
                continue
            yield tb

    def enforce_ui(self):
        if self.native_ui:
            return
        if self.cfg.get("hide_menubar", True):
            self.mw.menuBar().hide()
        if self.cfg.get("hide_native_toolbars", True):
            for tb in self.native_toolbars():
                if not tb.property("nxHooked"):
                    tb.visibilityChanged.connect(self._toolbar_shown)
                    tb.setProperty("nxHooked", True)
                if tb.isVisible():
                    tb.hide()
        for tb in (self.ribbon_bar, self.border_bar, self.resource_bar):
            tb.show()

    def _toolbar_shown(self, visible):
        if visible and not self.native_ui:
            QtCore.QTimer.singleShot(0, self.enforce_ui)

    def toggle_native_ui(self):
        self.native_ui = not self.native_ui
        if self.native_ui:
            self.mw.menuBar().show()
            names = set(GLOBAL_TOOLBARS) - {"Workbench"}
            try:
                names |= set(Gui.activeWorkbench().getToolbarItems().keys())
            except Exception:
                pass
            for tb in self.native_toolbars():
                if tb.objectName() in names or tb.windowTitle() in names:
                    tb.show()
        else:
            self.enforce_ui()


def start():
    """Entry point called once FreeCAD's main window is up."""
    global _shell
    if _shell is not None:
        return _shell
    _shell = Shell()
    _shell.setup()
    if os.environ.get("NXSTYLE_SMOKE_OUT"):
        from . import smoke
        smoke.start(_shell)
    elif os.environ.get("NXSTYLE_TUTORIAL_OUT"):
        from . import tutorial
        tutorial.start(_shell)
    return _shell
