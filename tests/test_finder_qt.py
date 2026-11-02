# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real offscreen Qt finder interactions; only FreeCAD's host services are mocked."""
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


@unittest.skipIf(QtCore is None, "PySide6 required for real finder interaction checks")
class FinderQt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.old_font = cls.app.font()
        cls.font_id = -1
        # Windows' offscreen plugin has no system font database. Load a local
        # system font for meaningful row rendering without packaging any font.
        if not QtGui.QFontDatabase.families() and os.environ.get("WINDIR"):
            font = Path(os.environ["WINDIR"]) / "Fonts" / "segoeui.ttf"
            cls.font_id = QtGui.QFontDatabase.addApplicationFont(str(font))
            families = QtGui.QFontDatabase.applicationFontFamilies(cls.font_id)
            if families:
                cls.app.setFont(QtGui.QFont(families[0], 10))
        # Load the actual shim, ribbon/action adapter and finder under an isolated
        # package name, so pure-Python tests' Qt stubs cannot contaminate this suite.
        cls.package_name = "_nxstyle_finder_qt"
        package = types.ModuleType(cls.package_name)
        package.__path__ = [str(PACKAGE)]
        wrapper = types.ModuleType("PySide")
        wrapper.QtCore, wrapper.QtGui, wrapper.QtWidgets = QtCore, QtGui, QtWidgets
        cls.gui = types.ModuleType("FreeCADGui")
        cls.host = patch.dict(sys.modules, {
            cls.package_name: package, "PySide": wrapper,
            "FreeCAD": types.ModuleType("FreeCAD"), "FreeCADGui": cls.gui,
        })
        cls.host.start()
        cls.config = importlib.import_module(cls.package_name + ".config")
        cls.config._cfg = dict(cls.config.DEFAULTS)
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
        self.runs, self.remembered, self.actions = [], [], {}
        for name, label, shortcut in (
            ("Test_Pad", "&Pad", "Ctrl+E"),
            ("Test_PadOther", "Additive feature", "Ctrl+Shift+E"),
            ("Test_Pocket", "Pocket", "Ctrl+P"),
        ):
            action = QtGui.QAction(label)
            action.setObjectName(name)
            action.setShortcut(QtGui.QKeySequence(shortcut))
            action.setToolTip("Native " + label)
            pixmap = QtGui.QPixmap(20, 20)
            pixmap.fill(QtGui.QColor("magenta"))
            action.setIcon(QtGui.QIcon(pixmap))
            self.actions[name] = action
        self.commands = {
            name: types.SimpleNamespace(
                getAction=lambda action=action: [action],
                isActive=lambda action=action: action.isEnabled())
            for name, action in self.actions.items()
        }
        self.gui.listCommands = lambda: list(self.commands)
        self.gui.Command = types.SimpleNamespace(get=lambda name: self.commands[name])
        self.gui.runCommand = self.runs.append
        self.gui.getIcon = lambda _: QtGui.QIcon()
        ribbon = types.SimpleNamespace(
            labels={"Test_Pad": "Extrude", "Test_PadOther": "Extrude alternative", "Test_Pocket": "Subtract"},
            locations={"Test_Pad": "Home / Design Feature", "Test_PadOther": "Home / Design Feature",
                       "Test_Pocket": "Home / Remove"})
        self.finder = self.finder_module.CommandFinder(ribbon, on_run=self.remembered.append)
        self.finder.resize(280, 36)
        self.finder.show()
        self.finder.setFocus()
        self.app.processEvents()

    def tearDown(self):
        QtTest.QTest.qWait(60)  # finish queued dispatch/busy reset before deleting widgets
        self.finder.completer.popup().hide()
        self.finder.close()
        self.finder.deleteLater()
        for action in self.actions.values():
            action.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def search(self, query):
        self.finder.clear()
        QtTest.QTest.keyClicks(self.finder, query)
        self.finder.completer.setCompletionPrefix(query)
        self.finder.completer.complete()
        self.app.processEvents()
        return self.finder.completer.popup()

    def test_find_and_standard_completer_match_every_search_field(self):
        for query in ("extrude", "pad", "Test_Pad", "design feature", "Ctrl+E"):
            with self.subTest(query=query):
                self.assertIn("Test_Pad", self.finder.find(query))
                self.finder.completer.setCompletionPrefix(query)
                model = self.finder.completer.completionModel()
                names = [model.index(row, 0).data(self.finder_module.ROLE_CMD)
                         for row in range(model.rowCount())]
                self.assertIn("Test_Pad", names)
        self.assertEqual(self.finder.find("not a real command"), [])

    def test_keyboard_selected_result_runs_exactly_once(self):
        popup = self.search("extrude")
        popup.setCurrentIndex(QtCore.QModelIndex())
        QtTest.QTest.keyClick(popup, QtCore.Qt.Key_Down)
        QtTest.QTest.keyClick(popup, QtCore.Qt.Key_Down)
        self.assertEqual(popup.currentIndex().data(self.finder_module.ROLE_CMD), "Test_PadOther")
        QtTest.QTest.keyClick(popup, QtCore.Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.runs, ["Test_PadOther"])
        self.assertEqual(self.remembered, ["Test_PadOther"])
        self.assertEqual(self.finder.text(), "")
        self.assertFalse(popup.isVisible())

    def test_line_edit_return_runs_first_match_once(self):
        self.finder.setText("Ctrl+E")
        QtTest.QTest.keyClick(self.finder, QtCore.Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.runs, ["Test_Pad"])
        QtTest.QTest.keyClick(self.finder, QtCore.Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.runs, ["Test_Pad"])

    def test_mouse_result_dispatches_once(self):
        popup = self.search("pocket")
        index = popup.model().index(0, 0)
        QtTest.QTest.mouseClick(popup.viewport(), QtCore.Qt.LeftButton,
                               pos=popup.visualRect(index).center())
        self.app.processEvents()
        self.assertEqual(self.runs, ["Test_Pocket"])
        self.assertEqual(self.finder.text(), "")
        self.assertFalse(popup.isVisible())

    def test_disabled_command_cannot_dispatch(self):
        self.actions["Test_Pad"].setEnabled(False)
        self.finder.rebuild()
        self.assertFalse(self.finder.model.item(0).isEnabled())
        self.finder.setText("Ctrl+E")
        QtTest.QTest.keyClick(self.finder, QtCore.Qt.Key_Return)
        self.finder._activated(self.finder.model.index(0, 0))
        self.app.processEvents()
        self.assertEqual(self.runs, [])
        self.assertEqual(self.remembered, [])

    def test_command_disabled_after_popup_opens_cannot_dispatch(self):
        popup = self.search("Ctrl+E")
        popup.setCurrentIndex(popup.model().index(0, 0))
        self.actions["Test_Pad"].setEnabled(False)
        QtTest.QTest.keyClick(popup, QtCore.Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.runs, [])

    def test_no_stale_result_dispatch_for_unknown_text(self):
        popup = self.search("extrude")
        popup.setCurrentIndex(popup.model().index(0, 0))
        self.finder.setText("not-a-real-command")
        QtTest.QTest.keyClick(self.finder, QtCore.Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.runs, [])

    def test_native_command_without_action_uses_is_active(self):
        self.actions["Test_PadOther"].setEnabled(False)
        self.commands["Test_Pad"] = types.SimpleNamespace(
            getAction=lambda: [], isActive=lambda: False,
            getInfo=lambda: {"menuText": "Pad", "toolTip": "Extrude profile"})
        self.finder.rebuild()
        self.finder.setText("Test_Pad")
        QtTest.QTest.keyClick(self.finder, QtCore.Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.runs, [])
        self.commands["Test_Pad"].isActive = lambda: True
        self.finder.setText("Test_Pad")
        QtTest.QTest.keyClick(self.finder, QtCore.Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.runs, ["Test_Pad"])

    def test_unknown_and_empty_search_do_not_dispatch(self):
        for query in ("not-a-real-command", ""):
            self.finder.setText(query)
            QtTest.QTest.keyClick(self.finder, QtCore.Qt.Key_Return)
            self.app.processEvents()
        self.assertEqual(self.runs, [])
        self.assertEqual(self.remembered, [])

    def test_escape_clears_search_and_closes_popup(self):
        popup = self.search("extrude")
        self.assertTrue(popup.isVisible())
        QtTest.QTest.keyClick(popup, QtCore.Qt.Key_Escape)
        self.app.processEvents()
        self.assertEqual(self.finder.text(), "")
        self.assertFalse(popup.isVisible())
        self.assertEqual(self.runs, [])

    def test_rows_render_and_popup_width_tracks_available_screen(self):
        popup = self.search("extrude")
        index = popup.model().index(0, 0)
        self.assertEqual(index.data(self.finder_module.ROLE_TITLE), "Extrude")
        self.assertIn("Home / Design Feature", index.data(self.finder_module.ROLE_DETAIL))
        self.assertIn("Pad", index.data(self.finder_module.ROLE_DETAIL))
        self.assertEqual(index.data(self.finder_module.ROLE_SHORTCUT), "Ctrl+E")
        self.assertEqual(popup.iconSize(), QtCore.QSize(20, 20))
        self.assertGreaterEqual(popup.visualRect(index).height(), 58)
        normal = popup.grab().toImage()
        self.assertFalse(normal.isNull())
        popup.setCurrentIndex(index)
        self.app.processEvents()
        selected = popup.grab().toImage()
        self.assertNotEqual(normal, selected)
        self.assertGreaterEqual(popup.width(), 440)
        self.finder.resize(600, 36)
        self.app.processEvents()
        available = self.app.primaryScreen().availableGeometry().width() - 24
        self.assertEqual(popup.width(), min(600, available))
        output = os.environ.get("NXSTYLE_FINDER_SCREENSHOT")
        if output:
            self.assertTrue(selected.save(output))


if __name__ == "__main__":
    unittest.main()
