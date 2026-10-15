# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Qt 6 patch for an upstream LCInterlocking, on a stand-in add-on (no FreeCAD, no Qt)."""

import importlib
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import lcinterlocking as lc  # noqa: E402

# PySide6 flags are enum.Flag members: int() of them raises TypeError, .value is the int
FAKE_QT = """
import enum

class StandardButton(enum.Flag):
    Ok = 0x400
    Cancel = 0x400000

class QDialogButtonBox:
    Ok = StandardButton.Ok
    Cancel = StandardButton.Cancel

class QtGui:
    QDialogButtonBox = QDialogButtonBox
"""

# the two methods as upstream LCInterlocking 1.5.1 has them (panel/treepanel.py)
UPSTREAM = """
from fakeqt import QtGui

class TreePanel(object):
    def __init__(self):
        self.selected = []

    def getStandardButtons(self):
        return int(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel)

    def force_selection(self, index):
        if not isinstance(index, int):
            raise TypeError("select() called with wrong argument types: NoneType")
        self.selected.append(index)
"""

# as the bundled fork has them
FORK = UPSTREAM.replace(
    "return int(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel)",
    'buttons = QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel\n'
    '        return int(getattr(buttons, "value", buttons)) + 0').replace(
    "    def force_selection(self, index):\n",
    "    def force_selection(self, index):\n        if index is None:\n            return 'fork'\n")


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "fakeqt.py").write_text(textwrap.dedent(FAKE_QT))
        sys.path.insert(0, str(self.root))
        self._forget()

    def tearDown(self):
        lc.uninstall()
        self._forget()
        sys.path.remove(str(self.root))
        self.tmp.cleanup()

    @staticmethod
    def _forget():
        for name in ("panel", "panel.treepanel", "fakeqt"):
            sys.modules.pop(name, None)
        importlib.invalidate_caches()

    def addon(self, source, lasercut=True):
        (self.root / "panel").mkdir()
        (self.root / "panel" / "__init__.py").write_text("")
        (self.root / "panel" / "treepanel.py").write_text(textwrap.dedent(source))
        if lasercut:
            (self.root / "lasercut").mkdir()
            (self.root / "lasercut" / "join.py").write_text("")

    def test_the_stand_in_fails_as_upstream_does_on_pyside6(self):
        self.addon(UPSTREAM)
        panel = importlib.import_module("panel.treepanel").TreePanel()
        self.assertRaises(TypeError, panel.getStandardButtons)
        self.assertRaises(TypeError, panel.force_selection, None)

    def test_upstream_patched_when_first_imported(self):
        self.addon(UPSTREAM)
        lc.install()
        mod = importlib.import_module("panel.treepanel")
        panel = mod.TreePanel()
        self.assertEqual(panel.getStandardButtons(), 0x400400)
        self.assertIsNone(panel.force_selection(None))
        panel.force_selection(3)
        self.assertEqual(panel.selected, [3])
        self.assertTrue(getattr(mod.TreePanel, lc.MARK))

    def test_upstream_already_imported_is_patched_at_install(self):
        self.addon(UPSTREAM)
        mod = importlib.import_module("panel.treepanel")
        lc.install()
        self.assertEqual(mod.TreePanel().getStandardButtons(), 0x400400)

    def test_fork_keeps_its_own_methods(self):
        self.addon(FORK)
        lc.install()
        panel = importlib.import_module("panel.treepanel").TreePanel()
        self.assertEqual(panel.getStandardButtons(), 0x400400)
        self.assertEqual(panel.force_selection(None), "fork")      # the fork's own method answered

    def test_another_add_ons_panel_package_is_left_alone(self):
        self.addon(UPSTREAM, lasercut=False)
        lc.install()
        mod = importlib.import_module("panel.treepanel")
        self.assertFalse(hasattr(mod.TreePanel, lc.MARK))
        self.assertRaises(TypeError, mod.TreePanel().getStandardButtons)

    def test_install_twice_patches_once(self):
        self.addon(UPSTREAM)
        lc.install()
        lc.install()
        self.assertEqual(sum(isinstance(f, lc._Finder) for f in sys.meta_path), 1)
        mod = importlib.import_module("panel.treepanel")
        self.assertTrue(lc.patch(mod))
        self.assertEqual(mod.TreePanel().getStandardButtons(), 0x400400)


class BundledForkTests(unittest.TestCase):
    """The submodule is the fork with the fix (skipped where it is not checked out)."""

    def test_bundled_copy_has_the_fix(self):
        src = Path(__file__).resolve().parents[1] / "vendor" / "LCInterlocking" / "panel" / "treepanel.py"
        if not src.is_file():
            self.skipTest("vendor/LCInterlocking not checked out (git submodule update --init)")
        text = src.read_text(encoding="utf-8")
        self.assertNotIn("return int(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel)", text)
        self.assertIn("if index is None", text)


if __name__ == "__main__":
    unittest.main()
