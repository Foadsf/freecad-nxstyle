# SPDX-License-Identifier: LGPL-2.1-or-later
"""Builds the NX-style window around FreeCAD's main window.

Layout (top to bottom, left to right), following the NX textbooks:
    ribbon row     File button, Quick Access Toolbar, tabs, Command Finder
    ribbon page    groups of large / small buttons
    top border bar Menu button, Type Filter, selection tools
    resource bar   vertical strip on the left: Part Navigator, History, ...
    graphics area  FreeCAD 3D view with NX colours and mouse behaviour
    status bar     cue line on the left
"""

import os

import FreeCAD as App
import FreeCADGui as Gui

from . import commands, config, navigation, prefs, shortcuts
from .finder import CommandFinder
from .qt import QtCore, QtGui, QtWidgets, Qt
from .ribbon import (CommandButton, Ribbon, command_actions, expand_tabs, known_commands,
                     spec_groups, sub_actions)
from .selection_filter import TypeFilter

OUR_TOOLBARS = {"NXRibbonBar", "NXTopBorderBar", "NXResourceBar"}
GLOBAL_TOOLBARS = {"File", "Edit", "Clipboard", "Workbench", "Macro", "View", "Individual views",
                   "Structure", "Help", "Navigation", "Selection"}
THEME_MARK = "/* NXStyle theme */"
THEME_TOKENS = {"@ThemeAccentColor1": "#0B6E79", "@ThemeAccentColor2": "#8CC5CC", "@ThemeAccentColor3": "#C7E3E7"}
LEFT_PANELS = ["Model", "Tasks", "NXHistory", "Selection view"]
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
        self.shortcut_result = {}
        self.setup_errors = []
        self._nav_state = None
        self._ticks = 0

    # ================================================================ setup
    def setup(self):
        steps = [self._prefs, self._apply_theme, self._register_commands, self._build_ribbon_bar, self._build_border_bar,
                 self._build_resource_bar, self._arrange_docks, self._build_cue_line, self._navigation]
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
                self.shortcut_result = shortcuts.apply()
                shortcuts.report(self.shortcut_result)
        except Exception:
            import traceback
            self.setup_errors.append(traceback.format_exc())
        self._track_commands()
        self.watch = QtCore.QTimer(self)
        self.watch.timeout.connect(self._tick)
        self.watch.start(300)
        self.enforce_ui()
        self.ready = True
        App.Console.PrintLog("NXStyle: ready\n")

    def _prefs(self):
        prefs.apply(self.cfg)
        prefs.apply_navigation_to_open_views(self.cfg)

    def _register_commands(self):
        names = commands.register(self.apps)
        if not all(command_actions(n) for n in names):
            # Re-activate the workbench so FreeCAD builds the global toolbar
            current = Gui.activeWorkbench().name()
            self._loading = True
            try:
                Gui.activateWorkbench("NoneWorkbench")
                Gui.activateWorkbench(current)
            finally:
                self._loading = False
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
        known = known_commands()
        tabs = []
        if app.get("ribbon"):
            spec = config.load_json("ribbons", app["ribbon"])
            self.preload(spec.get("preload", []))
            known = known_commands()
            tabs = expand_tabs(spec)
        else:
            tabs = [{"name": app["title"], "groups": None}] + expand_tabs(
                {"tabs": [{"include": "common:View"}, {"include": "common:Tools"},
                          {"include": "common:Application"}]})
        for t in tabs:
            if t["name"] == "Application":
                groups = self._application_groups()
            elif t.get("groups") is None:
                groups = self._auto_groups()
            else:
                groups = spec_groups(t)
            r.add_tab(t["name"], groups, known=known)
        if not r.select(app.get("first_tab", "")):
            r.tabs.setCurrentIndex(0)
        self._sketch_tab(navigation.in_sketch_edit(), force=True)
        self.finder.invalidate()

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
        acts = command_actions(name)
        if acts:
            from .ribbon import clean_text
            return clean_text(acts[0].text()) or name
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

    # ------------------------------------------------------- applications
    def switch_application(self, app_id):
        app = self._app(app_id)
        if app is None:
            return
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
        self.show_part_navigator()

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
        current = app.styleSheet()
        base = current.split(THEME_MARK)[0]
        name = self.cfg.get("stylesheet", "")
        for d in dirs:
            path = os.path.join(d, name) if name else ""
            if path and os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    base = f.read()
                break
        # FreeCAD fills these placeholders when it loads a stylesheet itself; an
        # unfilled one makes Qt drop the rules around it. Use the NX accent tints.
        for token, value in THEME_TOKENS.items():
            base = base.replace(token, value)
        with open(config.resource("nx_theme.qss"), encoding="utf-8") as f:
            theme = f.read()
        app.setStyleSheet(base + "\n" + theme)

    def theme_active(self):
        return THEME_MARK in QtWidgets.QApplication.instance().styleSheet()

    # ------------------------------------------------------------ cue line
    def _build_cue_line(self):
        self.cue = QtWidgets.QLabel(CUE_IDLE)
        self.cue.setObjectName("NXCueLine")
        self.cue.setStyleSheet("QLabel#NXCueLine { color: #0B6E79; padding-left: 6px; }")
        self.mw.statusBar().insertWidget(0, self.cue, 1)

    def _navigation(self):
        self.navigation = navigation.NavigationManager(self)

    # ======================================================== periodic work
    def _tick(self):
        sketch = navigation.in_sketch_edit()
        self._sketch_tab(sketch)
        try:
            dialog = bool(Gui.Control.activeDialog())
        except Exception:
            dialog = False
        text = CUE_SKETCH if sketch else CUE_DIALOG if dialog else CUE_IDLE
        if self.cue.text() != text:
            self.cue.setText(text)
        # NX keeps the Part Navigator in front; FreeCAD leaves its (often empty)
        # Tasks panel in front after start-up, new documents and closed dialogs.
        self._ticks += 1
        if self._ticks % 20 == 0:   # FreeCAD may re-apply its own stylesheet or dock headers
            if self.cfg.get("theme", "nx") == "nx" and not self.theme_active():
                self._apply_theme()
            self._blank_titles()
        state = (dialog, len(App.listDocuments()))
        if state != self._nav_state:
            if not dialog:
                self.show_part_navigator()
            self._nav_state = state

    def show_part_navigator(self):
        model = self.mw.findChild(QtWidgets.QDockWidget, "Model")
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
            acts = command_actions(name)
            if not acts:
                continue
            acts[0].triggered.connect(lambda _=False, n=name: commands.remember(n))
            self._tracked.add(name)

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
    return _shell
