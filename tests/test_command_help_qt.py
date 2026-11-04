# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real Qt keyboard-help surfaces with bounded FreeCAD host services."""
import importlib
import unittest
from unittest.mock import patch

import test_finder_qt as fixture

QtCore = fixture.QtCore
QtGui, QtWidgets = getattr(fixture, "QtGui", None), getattr(fixture, "QtWidgets", None)


@unittest.skipIf(QtCore is None, "PySide6 required for keyboard-help interaction checks")
class CommandHelpQt(unittest.TestCase):
    setUpClass = classmethod(fixture.FinderQt.setUpClass.__func__)
    tearDownClass = classmethod(fixture.FinderQt.tearDownClass.__func__)

    def setUp(self):
        fixture.FinderQt.setUp(self)
        self.ribbon_module = importlib.import_module(self.package_name + ".ribbon")
        self.help = importlib.import_module(self.package_name + ".command_help")
        self.shortcuts = importlib.import_module(self.package_name + ".shortcuts")
        self.widgets = []
        self.alias = QtGui.QAction("Pad alias")
        self.alias.setShortcuts([QtGui.QKeySequence("F7"), QtGui.QKeySequence("Ctrl+F7")])
        window = QtWidgets.QWidget()
        self.widgets.append(window)
        with patch.object(self.gui, "getMainWindow", return_value=window, create=True):
            self.manager = self.shortcuts.Shortcuts(None)
        self.manager.entries = [self.shortcuts.Entry("Pad alias", "F7", "Test_Pad", alias=True, resolved="Test_Pad")]
        self.manager.targets = {"F7": self.alias}
        self.manager_patch = patch.object(self.shortcuts, "instance", return_value=self.manager)
        self.manager_patch.start()
        self.finder.invalidate()
        self.finder.rebuild()

    def tearDown(self):
        self.manager_patch.stop()
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.alias.deleteLater()
        fixture.FinderQt.tearDown(self)

    def button(self, name="Test_Pad", label="Extrude"):
        button = self.ribbon_module.CommandButton(name, label, "large")
        self.widgets.append(button)
        return button

    def test_access_keys_record_what_they_displace_and_stay_unique(self):
        window = QtWidgets.QMainWindow()
        self.widgets.append(window)
        finder_key = next(e.keys for e in self.shortcuts.TABLE if e.cmd == "NXStyle_CommandFinder")
        native = QtGui.QAction("Native", window)
        native.setShortcut(QtGui.QKeySequence(finder_key))
        for entry in self.shortcuts.TABLE:
            if entry.context != "global":
                continue
            action = QtGui.QAction(entry.nx)
            window.addAction(action)
            self.actions[entry.cmd] = action
            self.commands[entry.cmd] = type("Command", (), {
                "getAction": lambda _, a=action: [a],
                "setShortcut": lambda _, key, a=action: a.setShortcut(QtGui.QKeySequence(key)),
            })()
        with patch.object(self.gui, "getMainWindow", return_value=window, create=True):
            manager = self.shortcuts.Shortcuts(None)
            manager.entries = [e for e in self.shortcuts.TABLE if e.context == "global"]
            try:
                rows = manager.apply()
                self.assertEqual(len(rows), 10)
                # the key was taken from the native action, and the record says so
                self.assertEqual(native.shortcuts(), [])
                self.assertEqual(manager.displaced, {finder_key: {("Native", finder_key)}})
                self.assertEqual(manager.shortcuts_for("NXStyle_CommandFinder"), [finder_key])
                # a native group copying the key back loses it again
                native.setShortcuts([QtGui.QKeySequence(finder_key), QtGui.QKeySequence("Ctrl+Q")])
                self.assertEqual([s.toString() for s in native.shortcuts()], ["Ctrl+Q"])
                self.assertEqual(manager.shortcuts_for("NXStyle_CommandFinder"), [finder_key])
                with patch.object(manager, "guard_action"):
                    native.setShortcut(QtGui.QKeySequence(finder_key))
                    self.assertEqual(native.shortcut().toString(), finder_key)
            finally:
                self.app.removeEventFilter(manager.gate)
                manager.disconnect_guards()

    def hover(self, button):
        event = QtGui.QHelpEvent(QtCore.QEvent.ToolTip, QtCore.QPoint(2, 2), QtCore.QPoint(2, 2))
        self.app.sendEvent(button, event)

    def test_all_native_and_alias_sequences_refresh_at_hover(self):
        native = self.actions["Test_Pad"]
        native.setShortcuts([QtGui.QKeySequence("Ctrl+E"), QtGui.QKeySequence("Alt+E")])
        button = self.button()
        for key in ("Ctrl+E", "Alt+E", "F7", "Ctrl+F7"):
            self.assertIn(key, button.toolTip())
        self.alias.setShortcuts([QtGui.QKeySequence("F8")])
        self.hover(button)
        self.assertIn("F8", button.toolTip())
        self.assertNotIn("F7", button.toolTip())
        native.setShortcuts([])
        self.alias.setShortcuts([])
        self.hover(button)
        self.assertIn("No direct shortcut assigned", button.toolTip())
        self.assertNotIn("Ctrl+E", button.toolTip())

    def test_unbound_command_names_live_finder_route_and_escapes_markup(self):
        action = QtGui.QAction("Finder")
        action.setShortcut(QtGui.QKeySequence("Ctrl+Space"))
        self.actions[self.help.FINDER_COMMAND] = action
        self.commands[self.help.FINDER_COMMAND] = type("Command", (), {"getAction": lambda _: [action]})()
        self.actions["Test_Pocket"].setShortcuts([])
        self.actions["Test_Pocket"].setToolTip("Use <b>unsafe & text</b>")
        button = self.button("Test_Pocket", "<Remove>")
        self.assertIn("Command Finder (Ctrl+Space)", button.toolTip())
        self.assertIn("&lt;Remove&gt;", button.toolTip())
        # a native tooltip's markup is read as markup, then its text is escaped: no live tags, no literal tags
        self.assertIn("Use unsafe &amp; text", button.toolTip())
        self.assertNotIn("<b>unsafe", button.toolTip())
        self.assertNotIn("&lt;b&gt;", button.toolTip())
        action.setShortcut(QtGui.QKeySequence("Alt+Space"))
        self.hover(button)
        self.assertIn("Command Finder (Alt+Space)", button.toolTip())
        self.assertNotIn("Ctrl+Space", button.toolTip())

    def test_freecad_html_tooltip_reads_as_text_not_tags(self):
        """FreeCAD 1.1's command tooltips are HTML; they used to show as literal <p style=...> text."""
        self.actions["Test_Pocket"].setText("Polyline")
        self.actions["Test_Pocket"].setToolTip(
            "<p style='white-space:pre; margin-bottom:0.5em;'><b>Polyline</b> (Z)</p>"
            "<p style='white-space:pre; margin:0;'>Creates a continuous polyline. Press the 'M' key to switch "
            "segment modes</p><p style='white-space:pre; margin-top:0.5em;'><i>Sketcher_CreatePolyline</i></p>")
        tip = self.button("Test_Pocket", "Profile").toolTip()
        self.assertIn("FreeCAD: Polyline", tip)
        self.assertIn("Creates a continuous polyline. Press the &#x27;M&#x27; key", tip)
        self.assertIn("Sketcher_CreatePolyline", tip)
        for raw in ("<p", "&lt;p", "style=", "white-space", "&lt;i&gt;", "Polyline</b> (Z)"):
            self.assertNotIn(raw, tip)
        doc = QtGui.QTextDocument()
        doc.setHtml(tip)
        self.assertNotIn("<", doc.toPlainText())

    def test_raw_action_and_dropdown_show_aliases_without_registering_proxies(self):
        raw = self.ribbon_module.ActionButton(self.actions["Test_Pad"], "small")
        dropdown = self.ribbon_module.DropdownButton("Features", [("Test_Pad", "Extrude")], "small")
        self.widgets += [raw, dropdown]
        self.assertIn("F7", raw.toolTip())
        self.assertIn("F7", dropdown.toolTip())
        proxy = dropdown.menu().actions()[0]
        self.assertIn("F7", proxy.text())
        self.assertEqual(proxy.shortcuts(), [])
        # entries are still found by their label (the smoke and tutorial replays pick them so)
        self.assertEqual(self.ribbon_module.clean_text(proxy.text()), "Extrude")
        self.assertEqual(dropdown.accessibleName(), "Features")
        self.assertTrue(dropdown.menu().accessibleName())
        self.alias.setShortcut(QtGui.QKeySequence("F9"))
        dropdown.menu().aboutToShow.emit()
        self.hover(raw)
        self.assertIn("F9", proxy.text())
        self.assertNotIn("F7", proxy.text())
        self.assertEqual(proxy.shortcuts(), [])       # the refresh shows the new key, it does not register it
        self.assertIn("F9", raw.toolTip())
        calls = []
        self.actions["Test_Pad"].triggered.connect(lambda: calls.append("native"))
        proxy.trigger()
        self.assertEqual(calls, ["native"])

    def test_group_default_tracks_remembered_entry_without_mutating_native_labels(self):
        owner = QtCore.QObject()
        group = QtGui.QActionGroup(owner)
        own = QtGui.QAction("Group", owner)
        own.setObjectName("Test_Group")
        own.setShortcut(QtGui.QKeySequence("G"))
        entries = [self.actions["Test_Pad"], self.actions["Test_Pocket"]]
        for action in entries:
            group.addAction(action)
        owner.setProperty("defaultAction", 0)
        self.commands["Test_Group"] = type("Command", (), {"getAction": lambda _: entries})()
        button = self.button("Test_Group", "Features")
        self.assertIn("Current command: Pad", button.toolTip())
        self.assertIn("F7", button.toolTip())
        owner.setProperty("defaultAction", 1)
        self.hover(button)
        self.assertIn("Current command: Pocket (Ctrl+P)", button.toolTip())
        self.assertNotIn("F7", button.toolTip())
        self.assertEqual([a.text() for a in button.menu().actions()], ["&Pad", "Pocket"])
        # Keep the native owner alive until after widgets; actual FreeCAD owns it.
        self.widgets.remove(button)
        button.deleteLater()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def test_finder_search_badges_and_tooltips_follow_alias_reassignment(self):
        self.assertIn("Test_Pad", self.finder.find("F7"))
        row = next(self.finder.model.item(i) for i in range(self.finder.model.rowCount())
                   if self.finder.model.item(i).data(self.finder_module.ROLE_CMD) == "Test_Pad")
        self.assertIn("F7", row.data(self.finder_module.ROLE_SHORTCUT))
        self.alias.setShortcut(QtGui.QKeySequence("F10"))
        self.assertIn("Test_Pad", self.finder.find("F10"))
        self.assertEqual(self.finder.find("F7"), [])
        self.assertIn("F10", row.toolTip())
        self.assertNotIn("F7", row.data(QtCore.Qt.AccessibleTextRole))

    def test_native_menu_hover_uses_live_help_without_rewriting_its_label(self):
        menu = QtWidgets.QMenu()
        self.widgets.append(menu)
        action = self.actions["Test_Pad"]
        menu.addAction(action)
        self.help.bind_menu_help(menu, "Native features")
        menu.ensurePolished()
        event = QtGui.QHelpEvent(QtCore.QEvent.ToolTip, menu.actionGeometry(action).center(), QtCore.QPoint(2, 2))
        with patch.object(QtWidgets.QToolTip, "showText") as show:
            self.app.sendEvent(menu, event)
        self.assertIn("F7", show.call_args.args[1])
        self.assertEqual(action.text(), "&Pad")
        self.assertEqual(action.shortcut().toString(), "Ctrl+E")

    def test_negative_control_rejects_hidden_alias(self):
        button = self.button()
        with patch.object(self.manager, "shortcuts_for", return_value=[]):
            self.hover(button)
            with self.assertRaisesRegex(AssertionError, "F7"):
                self.assertIn("F7", button.toolTip())


if __name__ == "__main__":
    unittest.main()
