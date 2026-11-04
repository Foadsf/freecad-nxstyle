# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real Qt rendering/action controls, without FreeCAD. CI runs these with PySide6."""
import gc
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6 import QtCore, QtGui, QtWidgets, QtSvg
except ImportError:
    if os.environ.get("NXSTYLE_REQUIRE_QT") == "1":
        raise  # dedicated CI must fail, not skip, if Qt or its runtime libraries are missing
    QtCore = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "NXStyle"))
from nxstyle import icon_theme


@unittest.skipIf(QtCore is None, "PySide6 required; exercised by the qt-icons CI job")
class IconsQt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.settings = {"icon_theme": "nx"}
        self.modules = patch.dict(sys.modules, {
            "nxstyle.qt": types.SimpleNamespace(QtCore=QtCore, QtGui=QtGui),
            "nxstyle.config": types.SimpleNamespace(get=lambda: self.settings),
        })
        self.modules.start()
        # 'from . import config' can use a cached package attribute from other tests.
        import nxstyle
        self.config = patch.object(nxstyle, "config", sys.modules["nxstyle.config"], create=True)
        self.config.start()
        self.actions = []

    def tearDown(self):
        for action in self.actions:
            action.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.config.stop()
        self.modules.stop()

    def native_icon(self, color="magenta"):
        p = QtGui.QPixmap(16, 16)
        p.fill(QtGui.QColor(color))
        return QtGui.QIcon(p)

    def action(self, name):
        a = QtGui.QAction(name)
        a.setObjectName(name)
        a.setIcon(self.native_icon())
        self.actions.append(a)
        return a

    def test_renders_every_asset_and_state_and_rejects_invalid_svg(self):
        paths = set(icon_theme.asset_path(c) for c in icon_theme.catalogue())
        self.assertNotIn(None, paths)
        for path in paths:
            with self.subTest(asset=path.name):
                self.assertTrue(QtSvg.QSvgRenderer(str(path)).isValid())
                icon = QtGui.QIcon(str(path))
                for size in (16, 24, 32, 44):
                    for mode in (QtGui.QIcon.Normal, QtGui.QIcon.Disabled, QtGui.QIcon.Active, QtGui.QIcon.Selected):
                        image = icon.pixmap(size, size, mode).toImage()
                        self.assertFalse(image.isNull())
                        opaque = sum(image.pixelColor(x, y).alpha() > 0 for x in range(image.width())
                                     for y in range(image.height()))
                        self.assertGreater(opaque, size, (path.name, size, mode))
        self.assertFalse(QtSvg.QSvgRenderer(b"<broken/>").isValid())

    def test_binding_changes_only_icon_and_is_idempotent(self):
        a = self.action("PartDesign_Pad")
        native = a.icon().cacheKey()
        a.setCheckable(True)
        a.setChecked(True)
        a.setShortcut(QtGui.QKeySequence("Ctrl+E"))
        a.setData("keep-model-command")
        hits = []
        a.triggered.connect(lambda checked: hits.append(checked))
        icon_theme.bind(a, a.objectName())
        themed = a.icon().cacheKey()
        self.assertNotEqual(native, themed)
        binding = icon_theme.binding_of(a)
        for _ in range(3):
            icon_theme.bind(a, a.objectName())
        self.assertIs(icon_theme.binding_of(a), binding)       # one binding, however often the action is bound
        self.assertEqual(a.receivers(QtCore.SIGNAL("changed()")), 1)
        self.assertEqual(a.shortcut().toString(), "Ctrl+E")
        self.assertEqual(a.data(), "keep-model-command")
        a.setEnabled(False)
        self.assertFalse(a.isEnabled())
        self.assertTrue(a.isChecked())
        self.assertEqual(a.icon().cacheKey(), themed)
        a.setEnabled(True)
        a.trigger()
        self.assertEqual(hits, [False])
        self.settings["icon_theme"] = "freecad"
        icon_theme.bind(a, a.objectName())
        self.assertEqual(a.icon().cacheKey(), native)

    def test_host_icon_update_is_remembered_without_overriding_state(self):
        a = self.action("PartDesign_Pad")
        icon_theme.bind(a, a.objectName())
        newer = self.native_icon("cyan")
        a.setIcon(newer)
        self.assertNotEqual(a.icon().cacheKey(), newer.cacheKey())
        self.settings["icon_theme"] = "freecad"
        icon_theme.bind(a, a.objectName())
        self.assertEqual(a.icon().cacheKey(), newer.cacheKey())

    @staticmethod
    def lose_wrapper_state(action):
        """What FreeCAD 26.3 (PySide6 6.11) showed in issue #53: an object Qt hands back for the action's child is
        of the Python class but carries none of its Python attributes ('Binding' object has no attribute 'busy')."""
        for child in action.findChildren(QtCore.QObject):
            vars(child).clear()
        gc.collect()

    def test_binding_survives_python_wrappers_losing_their_attributes(self):
        a = self.action("PartDesign_Pad")
        native = a.icon().cacheKey()
        icon_theme.bind(a, a.objectName())
        themed = a.icon().cacheKey()
        self.lose_wrapper_state(a)
        icon_theme.bind(a, a.objectName())                    # issue #53 raised AttributeError here
        a.setEnabled(False)                                   # and in the slot on every changed()
        a.setEnabled(True)
        self.assertEqual(a.icon().cacheKey(), themed)
        self.settings["icon_theme"] = "freecad"
        icon_theme.bind(a, a.objectName())
        self.assertEqual(a.icon().cacheKey(), native)         # the native icon is still known

    def test_group_binding_survives_python_wrappers_losing_their_attributes(self):
        """The issue #53 traceback's path: ribbon.command_action binding a group's own action with its entries."""
        owner = QtCore.QObject()
        own = self.action("Sketcher_CompLine")
        entries = [self.action("Sketcher_CreateLine"), self.action("UnmappedVariant")]
        for e in entries:
            icon_theme.bind(e, e.objectName())
        owner.setProperty("defaultAction", 0)
        icon_theme.bind(own, own.objectName(), entries, owner)
        self.lose_wrapper_state(own)
        icon_theme.bind(own, own.objectName(), entries, owner)
        self.assertEqual(own.icon().cacheKey(), entries[0].icon().cacheKey())

    def test_binding_is_dropped_with_its_action(self):
        a = QtGui.QAction("PartDesign_Pad")
        a.setObjectName("PartDesign_Pad")
        a.setIcon(self.native_icon())
        icon_theme.bind(a, a.objectName())
        key = a.property(icon_theme.BINDING_KEY)
        self.assertIn(key, icon_theme._bindings)
        a.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.assertNotIn(key, icon_theme._bindings)

    def test_unmapped_missing_invalid_and_off_keep_native(self):
        native = self.native_icon()
        self.assertIs(icon_theme.icon("NoSuchCommand", native), native)
        with patch.object(icon_theme, "asset_path", return_value=None):
            self.assertIs(icon_theme.icon("PartDesign_Pad", native), native)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.svg"
            path.write_text("<broken/>", encoding="utf-8")
            with patch.object(icon_theme, "asset_path", return_value=path):
                self.assertIs(icon_theme.icon("PartDesign_Pad", native), native)
        self.settings["icon_theme"] = "freecad"
        self.assertIs(icon_theme.icon("PartDesign_Pad", native), native)

    def test_group_follows_mapped_and_unmapped_remembered_entries(self):
        owner = QtCore.QObject()
        own = self.action("Sketcher_CompLine")
        entries = [self.action("Sketcher_CreateLine"), self.action("UnmappedVariant")]
        for a in entries:
            icon_theme.bind(a, a.objectName())
        owner.setProperty("defaultAction", 0)
        icon_theme.bind(own, own.objectName(), entries, owner)
        self.assertEqual(own.icon().cacheKey(), entries[0].icon().cacheKey())
        owner.setProperty("defaultAction", 1)
        own.setIcon(entries[1].icon())     # the host switches its group's remembered entry
        self.assertEqual(own.icon().cacheKey(), entries[1].icon().cacheKey())
        owner.setProperty("defaultAction", 0)
        own.setIcon(entries[0].icon())
        self.assertEqual(own.icon().cacheKey(), entries[0].icon().cacheKey())
        self.settings["icon_theme"] = "freecad"
        for a in entries:
            icon_theme.bind(a, a.objectName())
        icon_theme.bind(own, own.objectName(), entries, owner)
        self.assertEqual(own.icon().cacheKey(), entries[0].icon().cacheKey())


if __name__ == "__main__":
    unittest.main()
