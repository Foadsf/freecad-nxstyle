# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real Qt keyboard controller interactions; only FreeCAD services are replaced."""
import importlib
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6 import QtCore, QtGui, QtWidgets, QtTest
except ImportError:
    if os.environ.get("NXSTYLE_REQUIRE_QT") == "1":
        raise
    QtCore = None

PACKAGE = Path(__file__).resolve().parents[1] / "NXStyle" / "nxstyle"


@unittest.skipIf(QtCore is None, "PySide6 required for keyboard controller checks")
class KeyboardUiQt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.old_font, cls.font_id = cls.app.font(), -1
        if not QtGui.QFontDatabase.families() and os.environ.get("WINDIR"):
            cls.font_id = QtGui.QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / "segoeui.ttf"))
            families = QtGui.QFontDatabase.applicationFontFamilies(cls.font_id)
            if families:
                cls.app.setFont(QtGui.QFont(families[0], 10))
        cls.package_name = "_nxstyle_keyboard_ui_qt"
        package = types.ModuleType(cls.package_name)
        package.__path__ = [str(PACKAGE)]
        wrapper = types.ModuleType("PySide")
        wrapper.QtCore, wrapper.QtGui, wrapper.QtWidgets = QtCore, QtGui, QtWidgets
        cls.gui = types.ModuleType("FreeCADGui")
        cls.gui.listCommands = lambda: []
        cls.gui.Command = types.SimpleNamespace(get=lambda _: None)
        cls.host = patch.dict(sys.modules, {cls.package_name: package, "PySide": wrapper,
                                          "FreeCAD": types.ModuleType("FreeCAD"), "FreeCADGui": cls.gui})
        cls.host.start()
        cls.config = importlib.import_module(cls.package_name + ".config")
        cls.config._cfg = dict(cls.config.DEFAULTS)
        cls.module = importlib.import_module(cls.package_name + ".keyboard_ui")
        cls.ribbon_module = importlib.import_module(cls.package_name + ".ribbon")
        cls.finder_module = importlib.import_module(cls.package_name + ".finder")

    @classmethod
    def tearDownClass(cls):
        cls.app.setFont(cls.old_font)
        if cls.font_id >= 0:
            QtGui.QFontDatabase.removeApplicationFont(cls.font_id)
        cls.host.stop()
        for name in list(sys.modules):
            if name.startswith(cls.package_name + "."):
                del sys.modules[name]

    def setUp(self):
        self.mw = QtWidgets.QMainWindow()
        central = QtWidgets.QWidget()
        self.mw.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        self.ribbon = self.ribbon_module.Ribbon()
        layout.addWidget(self.ribbon)
        self.finder = self.finder_module.CommandFinder(self.ribbon, self.ribbon.header)
        self.ribbon.corner.addWidget(self.finder)
        self.clicked, self.camera, self.mouse = [], [], []
        self.pages = []
        for title in ("Home", "View"):
            page = QtWidgets.QWidget()
            row = QtWidgets.QHBoxLayout(page)
            buttons = []
            for label in ("First", "Disabled", "Hidden", "Menu", "Last"):
                button = QtWidgets.QToolButton(page)
                button.setText(title + " " + label)
                button.clicked.connect(lambda _=False, text=button.text(): self.clicked.append(text))
                row.addWidget(button)
                buttons.append(button)
            buttons[1].setEnabled(False)
            buttons[2].hide()
            menu = QtWidgets.QMenu(buttons[3])
            disabled = menu.addAction("Unavailable")
            disabled.setEnabled(False)
            menu.addSeparator()
            active = menu.addAction("Enabled action")
            active.triggered.connect(lambda _=False, title=title: self.clicked.append(title + " action"))
            buttons[3].setMenu(menu)
            buttons[3].setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
            self.ribbon.tabs.addTab(title)
            self.ribbon.stack.addWidget(page)
            self.pages.append(buttons)
        self.resource, self.border = QtWidgets.QWidget(), QtWidgets.QWidget()
        for area, text in ((self.resource, "Resource"), (self.border, "Selection")):
            row = QtWidgets.QHBoxLayout(area)
            button = QtWidgets.QToolButton(area)
            button.setText(text)
            button.clicked.connect(lambda _=False, text=text: self.clicked.append(text))
            row.addWidget(button)
            layout.addWidget(area)
        self.editor = QtWidgets.QLineEdit()
        layout.addWidget(self.editor)
        # FreeCAD's View3DInventor: the viewer and, as its siblings, Sketcher's on-view fields
        self.view_host = QtWidgets.QWidget()
        QtWidgets.QVBoxLayout(self.view_host)
        self.graphics = QtWidgets.QGraphicsView()
        self.graphics.setScene(QtWidgets.QGraphicsScene(self.graphics))
        self.graphics.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.view_host.layout().addWidget(self.graphics)
        layout.addWidget(self.view_host, 1)
        self.nav = types.SimpleNamespace(
            widget=self.graphics.viewport(), view=types.SimpleNamespace(graphicsView=lambda: self.graphics),
            rotate=lambda dx, dy: self.camera.append(("rotate", dx, dy)),
            pan=lambda dx, dy: self.camera.append(("pan", dx, dy)),
            zoom=lambda delta: self.camera.append(("zoom", delta)))
        self.active_nav = self.nav
        self.gui.ActiveDocument = types.SimpleNamespace(ActiveView=self.nav.view)
        shell = types.SimpleNamespace(mw=self.mw, ribbon=self.ribbon, finder=self.finder,
                                      resource_bar=self.resource, border_bar=self.border,
                                      navigation=types.SimpleNamespace(filter_for_active_view=lambda: self.active_nav))
        self.access = self.module.KeyboardAccess(shell)

        test = self
        class MouseRecorder(QtCore.QObject):
            def eventFilter(self, obj, event):
                if event.type() in (QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
                    test.mouse.append((event.type(), event.button(), event.buttons(), event.position().toPoint()))
                return False
        self.recorder = MouseRecorder(self.mw)
        self.nav.widget.installEventFilter(self.recorder)
        self.mw.resize(900, 650)
        self.mw.show()
        self.mw.activateWindow()
        self.graphics.setFocus()
        self.app.processEvents()
        self.camera.clear()
        self.mouse.clear()

    def tearDown(self):
        self.app.removeEventFilter(self.access)
        self.access.stop_pointer()
        for buttons in self.pages:
            buttons[3].menu().hide()
        self.ribbon.hide_popup()
        self.mw.close()
        self.mw.deleteLater()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def key(self, widget, key, mods=QtCore.Qt.NoModifier if QtCore is not None else None):
        QtTest.QTest.keyClick(widget, key, mods)
        self.app.processEvents()

    def start_pointer(self):
        self.graphics.setFocus()
        self.access.toggle_pointer()
        self.app.processEvents()
        self.assertIs(self.access.pointer_view, self.nav)
        self.assertTrue(self.access.mark.isVisible())
        self.mouse.clear()

    def test_access_shortcut_escapes_text_fields_shortcut_override(self):
        shortcuts = importlib.import_module(self.package_name + ".shortcuts")
        action = QtGui.QAction("Focus tasks", self.mw)
        action.setShortcut(QtGui.QKeySequence("Alt+2"))
        self.mw.addAction(action)
        hits = []
        action.triggered.connect(lambda: hits.append(True))
        entry = shortcuts.Entry("Tasks", "Alt+2", "NXStyle_FocusTasks", "global", resolved="NXStyle_FocusTasks")
        manager = types.SimpleNamespace(entries=[entry], targets={"Alt+2": action})

        class GreedyField(QtCore.QObject):
            def eventFilter(self, obj, event):
                if event.type() == QtCore.QEvent.ShortcutOverride:
                    event.accept()
                    return True
                return False
        greedy = GreedyField(self.editor)
        self.editor.installEventFilter(greedy)
        self.editor.setFocus()
        with patch.object(shortcuts, "instance", return_value=manager):
            self.key(self.editor, QtCore.Qt.Key_2, QtCore.Qt.AltModifier)
            self.assertEqual(hits, [True])
            # Same field swallows the action without our override protection.
            self.app.removeEventFilter(self.access)
            try:
                self.key(self.editor, QtCore.Qt.Key_2, QtCore.Qt.AltModifier)
                self.assertEqual(hits, [True])
            finally:
                self.app.installEventFilter(self.access)

    def test_task_tab_traverses_real_fields_once_and_wraps_inside_panel(self):
        dock = QtWidgets.QDockWidget("Tasks", self.mw)
        dock.setObjectName("Tasks")
        scroll = QtWidgets.QScrollArea()
        form = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(form)
        combo, spin, button = QtWidgets.QComboBox(), QtWidgets.QDoubleSpinBox(), QtWidgets.QPushButton("OK")
        combo.addItems(["Block", "Cylinder"])
        for widget in (combo, spin, button):
            layout.addWidget(widget)
        scroll.setWidget(form)
        scroll.setWidgetResizable(True)
        dock.setWidget(scroll)
        self.mw.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
        dock.show()
        self.app.processEvents()
        self.access.focus_dock("Tasks")
        self.app.processEvents()
        self.assertIs(self.app.focusWidget(), combo)
        self.key(combo, QtCore.Qt.Key_Tab)
        self.assertIn(self.app.focusWidget(), (spin, spin.lineEdit()))
        self.key(self.app.focusWidget(), QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QtTest.QTest.keyClicks(self.app.focusWidget(), "17")
        self.key(self.app.focusWidget(), QtCore.Qt.Key_Tab)
        self.assertIs(self.app.focusWidget(), button)
        self.assertEqual(spin.value(), 17)
        self.key(button, QtCore.Qt.Key_Tab)
        self.assertIs(self.app.focusWidget(), combo)
        self.key(combo, QtCore.Qt.Key_Backtab)
        self.assertIs(self.app.focusWidget(), button)

    def test_ribbon_focus_tab_enter_escape_and_native_tab_arrows(self):
        self.access.focus_ribbon()
        self.assertIs(self.app.focusWidget(), self.ribbon.tabs)
        self.key(self.ribbon.tabs, QtCore.Qt.Key_Right)
        self.assertEqual(self.ribbon.tabs.currentIndex(), 1)
        self.key(self.ribbon.tabs, QtCore.Qt.Key_Down)
        first, _, _, menu, last = self.pages[1]
        self.assertIs(self.app.focusWidget(), first)
        self.key(first, QtCore.Qt.Key_Tab)
        self.assertIs(self.app.focusWidget(), menu)
        self.key(menu, QtCore.Qt.Key_Backtab)
        self.assertIs(self.app.focusWidget(), first)
        self.key(first, QtCore.Qt.Key_Return)
        self.assertEqual(self.clicked, ["View First"])
        self.key(first, QtCore.Qt.Key_Escape)
        self.assertIs(self.app.focusWidget(), self.graphics)
        self.assertEqual(self.camera, [])

    def test_ribbon_menu_down_focuses_first_enabled_action_and_enter_dispatches_once(self):
        self.access.focus_ribbon()
        self.key(self.ribbon.tabs, QtCore.Qt.Key_Down)
        button = self.pages[0][3]
        button.setFocus()
        self.key(button, QtCore.Qt.Key_Down)
        menu = button.menu()
        self.assertTrue(menu.isVisible())
        self.assertEqual(menu.activeAction().text(), "Enabled action")
        self.key(menu, QtCore.Qt.Key_Return)
        self.assertEqual(self.clicked, ["Home action"])
        self.assertFalse(menu.isVisible())

    def test_nested_escape_closes_menu_then_restores_previous_area(self):
        self.access.focus_ribbon()
        self.key(self.ribbon.tabs, QtCore.Qt.Key_Down)
        button = self.pages[0][3]
        button.setFocus()
        self.key(button, QtCore.Qt.Key_Down)
        menu = button.menu()
        self.assertTrue(menu.isVisible())
        self.key(menu, QtCore.Qt.Key_Escape)
        self.assertFalse(menu.isVisible())
        self.assertIs(self.app.focusWidget(), button)
        self.key(button, QtCore.Qt.Key_Escape)
        self.assertIs(self.app.focusWidget(), self.graphics)
        self.assertEqual(self.clicked, [])

    def test_collapsed_ribbon_opens_for_keyboard_and_escape_returns_to_view(self):
        self.ribbon.set_collapsed(True, save=False)
        self.access.focus_ribbon()
        self.key(self.ribbon.tabs, QtCore.Qt.Key_Return)
        self.assertTrue(self.ribbon._popup.isVisible())
        first = self.pages[0][0]
        self.assertIs(self.app.focusWidget(), first)
        self.key(first, QtCore.Qt.Key_Escape)
        self.assertFalse(self.ribbon._popup.isVisible())
        self.assertIs(self.app.focusWidget(), self.graphics)

    def test_alt_arrows_rotate_in_view_and_leave_text_fields_untouched(self):
        self.key(self.graphics, QtCore.Qt.Key_Left, QtCore.Qt.AltModifier)
        self.key(self.graphics.viewport(), QtCore.Qt.Key_Up, QtCore.Qt.AltModifier)
        self.assertEqual(self.camera, [("rotate", -10, 0), ("rotate", 0, -10)])
        self.editor.setFocus()
        self.editor.setText("coordinate")
        self.editor.setCursorPosition(3)
        self.key(self.editor, QtCore.Qt.Key_Left, QtCore.Qt.AltModifier)
        self.assertEqual(self.camera, [("rotate", -10, 0), ("rotate", 0, -10)])

    def test_freecad_view_keys_keep_their_meaning(self):
        # FreeCAD 1.1.4 pans with the arrows and zooms with PageUp/PageDown (measured with this override off);
        # Shift+Left / Shift+Right are Std_ViewRotateLeft / Right, Ctrl+arrows Std_DockOverlayToggle*
        seen = []

        class Native(QtCore.QObject):
            def eventFilter(self, obj, event):
                if event.type() == QtCore.QEvent.KeyPress:
                    seen.append((event.key(), event.modifiers()))
                return False
        native = Native(self.graphics)
        self.graphics.installEventFilter(native)
        turns = []
        for seq in ("Shift+Left", "Shift+Right", "Ctrl+Left"):
            action = QtGui.QAction(seq, self.mw)
            action.setShortcut(QtGui.QKeySequence(seq))
            action.triggered.connect(lambda _=False, s=seq: turns.append(s))
            self.mw.addAction(action)
        self.graphics.setFocus()
        for key in (QtCore.Qt.Key_Left, QtCore.Qt.Key_Down, QtCore.Qt.Key_PageUp, QtCore.Qt.Key_Plus):
            self.key(self.graphics, key)
        self.key(self.graphics, QtCore.Qt.Key_Left, QtCore.Qt.ShiftModifier)
        self.key(self.graphics, QtCore.Qt.Key_Right, QtCore.Qt.ShiftModifier)
        self.key(self.graphics, QtCore.Qt.Key_Left, QtCore.Qt.ControlModifier)
        modifiers = (QtCore.Qt.Key_Shift, QtCore.Qt.Key_Control)    # QTest presses those too
        self.assertEqual([k for k, _ in seen if k not in modifiers],
                         [QtCore.Qt.Key_Left, QtCore.Qt.Key_Down, QtCore.Qt.Key_PageUp, QtCore.Qt.Key_Plus])
        self.assertEqual(turns, ["Shift+Left", "Shift+Right", "Ctrl+Left"])
        self.assertEqual(self.camera, [])

    def test_rotate_override_claims_alt_arrow_before_conflicting_global_qaction(self):
        invoked = []
        conflict = QtGui.QAction("Conflicting Alt+Left action", self.mw)
        conflict.setShortcut(QtGui.QKeySequence("Alt+Left"))
        conflict.triggered.connect(lambda: invoked.append("left action"))
        self.mw.addAction(conflict)
        self.key(self.graphics, QtCore.Qt.Key_Left, QtCore.Qt.AltModifier)
        self.assertEqual(self.camera, [("rotate", -10, 0)])
        self.assertEqual(invoked, [])
        # Unclaimed keys still reach their normal QAction shortcut target.
        conflict.setShortcut(QtGui.QKeySequence("Ctrl+K"))
        self.key(self.graphics, QtCore.Qt.Key_K, QtCore.Qt.ControlModifier)
        self.assertEqual(invoked, ["left action"])

    def test_finder_selects_existing_text_and_escape_restores_view(self):
        self.finder.setText("existing query")
        self.access.focus_finder()
        self.assertIs(self.app.focusWidget(), self.finder)
        self.assertEqual(self.finder.selectedText(), "existing query")
        self.key(self.finder, QtCore.Qt.Key_Escape)
        self.assertEqual(self.finder.text(), "")
        self.assertIs(self.app.focusWidget(), self.graphics)

    def test_toolbar_buttons_activate_with_enter_without_camera_events(self):
        for area, label in ((self.resource, "Resource"), (self.border, "Selection")):
            self.access.focus_bar(area)
            button = area.findChild(QtWidgets.QToolButton)
            self.assertIs(self.app.focusWidget(), button)
            self.key(button, QtCore.Qt.Key_Return)
            self.assertEqual(self.clicked[-1], label)
            # reachable by Tab, but a mouse click must not take the focus from the graphics view
            self.assertEqual(button.focusPolicy(), QtCore.Qt.TabFocus)
        self.assertEqual(self.camera, [])

    def test_pointer_moves_with_modifiers_clamps_and_leaves_camera_unchanged(self):
        self.start_pointer()
        start = QtCore.QPoint(self.access.point)
        self.key(self.graphics, QtCore.Qt.Key_Right)
        self.key(self.graphics, QtCore.Qt.Key_Down, QtCore.Qt.ShiftModifier)
        self.key(self.graphics, QtCore.Qt.Key_Left, QtCore.Qt.ControlModifier)
        self.assertEqual(self.access.point, start + QtCore.QPoint(-20, 1))
        self.access.move_pointer(-100000, -100000)
        self.assertEqual(self.access.point, QtCore.QPoint(0, 0))
        self.access.move_pointer(100000, 100000)
        self.assertEqual(self.access.point, self.nav.widget.rect().bottomRight())
        self.assertTrue(all(event[0] == QtCore.QEvent.MouseMove for event in self.mouse))
        self.assertEqual(self.camera, [])

    def test_pointer_left_middle_right_clicks_are_normal_balanced_mouse_events(self):
        self.start_pointer()
        for key, button in ((QtCore.Qt.Key_Return, QtCore.Qt.LeftButton),
                            (QtCore.Qt.Key_Space, QtCore.Qt.MiddleButton),
                            (QtCore.Qt.Key_Menu, QtCore.Qt.RightButton)):
            self.key(self.graphics, key)
            press, release = self.mouse[-2:]
            self.assertEqual(press[:3], (QtCore.QEvent.MouseButtonPress, button, button))
            self.assertEqual(release[:3], (QtCore.QEvent.MouseButtonRelease, button, QtCore.Qt.NoButton))
            self.assertEqual(press[3], self.access.point)
            self.assertEqual(release[3], self.access.point)
        self.assertEqual(len(self.mouse), 6)
        self.key(self.graphics, QtCore.Qt.Key_F10, QtCore.Qt.ShiftModifier)
        self.assertEqual(self.mouse[-2][1], QtCore.Qt.RightButton)
        self.assertEqual(self.mouse[-1][0], QtCore.QEvent.MouseButtonRelease)
        self.assertEqual(self.camera, [])

    def test_drag_moves_with_left_button_and_focus_loss_releases_once(self):
        self.start_pointer()
        self.key(self.graphics, QtCore.Qt.Key_Return, QtCore.Qt.ControlModifier)
        self.assertTrue(self.access.dragging)
        self.key(self.graphics, QtCore.Qt.Key_Right)
        self.assertEqual(self.mouse[-1][2], QtCore.Qt.LeftButton)
        self.editor.setFocus()
        self.app.processEvents()
        self.assertFalse(self.access.dragging)
        releases = [event for event in self.mouse if event[0] == QtCore.QEvent.MouseButtonRelease]
        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0][1], QtCore.Qt.LeftButton)
        self.access.stop_pointer()
        self.assertEqual(len([e for e in self.mouse if e[0] == QtCore.QEvent.MouseButtonRelease]), 1)

    def test_ctrl_enter_finishes_drag_and_unmodified_click_finishes_existing_drag(self):
        self.start_pointer()
        for finish_mods in (QtCore.Qt.ControlModifier, QtCore.Qt.NoModifier):
            self.mouse.clear()
            self.key(self.graphics, QtCore.Qt.Key_Return, QtCore.Qt.ControlModifier)
            self.assertTrue(self.access.dragging)
            self.key(self.graphics, QtCore.Qt.Key_Return, finish_mods)
            self.assertFalse(self.access.dragging)
            self.assertEqual([event[0] for event in self.mouse],
                             [QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease])

    def test_escape_deactivation_and_view_hide_stop_pointer_and_balance_drag(self):
        for stop in ("escape", "deactivate", "hide"):
            with self.subTest(stop=stop):
                self.graphics.show()
                self.start_pointer()
                self.key(self.graphics, QtCore.Qt.Key_Return, QtCore.Qt.ControlModifier)
                if stop == "escape":
                    self.key(self.graphics, QtCore.Qt.Key_Escape)
                elif stop == "deactivate":
                    self.app.sendEvent(self.mw, QtCore.QEvent(QtCore.QEvent.ApplicationDeactivate))
                else:
                    self.nav.widget.hide()
                    self.app.processEvents()
                self.assertIsNone(self.access.pointer_view)
                self.assertFalse(self.access.dragging)
                self.assertIsNone(self.access.mark)
                self.assertEqual(len([e for e in self.mouse if e[0] == QtCore.QEvent.MouseButtonRelease]), 1)
                self.nav.widget.show()

    def test_nonview_keys_and_autorepeated_click_do_not_generate_pointer_events(self):
        self.start_pointer()
        self.editor.setFocus()
        self.key(self.editor, QtCore.Qt.Key_Return)
        self.key(self.editor, QtCore.Qt.Key_Left)
        self.assertEqual(self.mouse, [])
        self.graphics.setFocus()
        repeat = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier, "", True, 2)
        self.app.sendEvent(self.graphics, repeat)
        self.assertEqual(self.mouse, [])
        self.key(self.graphics, QtCore.Qt.Key_Return)
        self.assertEqual(len(self.mouse), 2)

    def on_view_field(self):
        """A field where Sketcher puts one (EditableDatumLabel: a child of the viewer's parent, ClickFocus)."""
        field = QtWidgets.QDoubleSpinBox(self.view_host)
        field.setFocusPolicy(QtCore.Qt.ClickFocus)
        field.setRange(-1000, 1000)
        field.show()
        return field

    def test_pointer_keys_reach_pointer_from_on_view_field_and_digits_stay_typed(self):
        field = self.on_view_field()
        self.start_pointer()
        field.setFocus()           # what FreeCAD does on each pointer move of a sketch tool,
        field.selectAll()          # with its number selected (EditableDatumLabel::setFocusToSpinbox)
        released = []              # Sketcher's DrawSketchKeyboardManager filters releases on the field too

        class Releases(QtCore.QObject):
            def eventFilter(self, obj, event):
                if event.type() == QtCore.QEvent.KeyRelease:
                    released.append(event.key())
                return False
        watcher = Releases(field)
        field.installEventFilter(watcher)
        start = QtCore.QPoint(self.access.point)
        QtTest.QTest.keyClicks(field, "25")
        self.key(field, QtCore.Qt.Key_Right)
        self.key(field, QtCore.Qt.Key_Return)
        self.assertEqual(field.value(), 25)          # digits are the typed dimension
        self.assertEqual(released, [QtCore.Qt.Key_2, QtCore.Qt.Key_5])   # not the pointer's Right and Return
        self.assertEqual(self.access.point.x(), start.x() + 10)
        self.assertEqual([e[0] for e in self.mouse[-2:]],
                         [QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease])
        self.key(field, QtCore.Qt.Key_Escape)
        self.assertIsNone(self.access.pointer_view)
        # pointer off: the field's own keys again
        self.mouse.clear()
        self.key(field, QtCore.Qt.Key_Up)
        self.assertEqual(field.value(), 26)
        self.assertEqual(self.mouse, [])

    def test_fields_outside_pointer_view_keep_their_keys(self):
        self.start_pointer()
        self.editor.setFocus()
        self.editor.setText("123")
        self.editor.setCursorPosition(1)
        self.key(self.editor, QtCore.Qt.Key_Right)
        self.key(self.editor, QtCore.Qt.Key_Return)
        self.assertEqual(self.editor.cursorPosition(), 2)
        self.assertEqual(self.mouse, [])

    def test_drag_survives_focus_moving_to_on_view_field(self):
        field = self.on_view_field()
        self.start_pointer()
        self.key(self.graphics, QtCore.Qt.Key_Return, QtCore.Qt.ControlModifier)
        field.setFocus()
        self.app.processEvents()
        self.assertTrue(self.access.dragging)
        self.key(field, QtCore.Qt.Key_Right)
        self.assertEqual(self.mouse[-1][:3], (QtCore.QEvent.MouseMove, QtCore.Qt.NoButton, QtCore.Qt.LeftButton))
        self.editor.setFocus()     # leaving the view ends it, once
        self.app.processEvents()
        self.assertFalse(self.access.dragging)
        self.assertEqual(len([e for e in self.mouse if e[0] == QtCore.QEvent.MouseButtonRelease]), 1)


if __name__ == "__main__":
    unittest.main()
