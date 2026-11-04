# SPDX-License-Identifier: LGPL-2.1-or-later
"""The replays' check-box click, in real Qt without FreeCAD. CI runs these with PySide6.

Tutorial I's "Add offset constraint" fills the task panel's row; a click on the widget's centre falls right of
its label once the row is wide enough, and Qt ignores it (#48's restyle widened it from 306 to 308 px)."""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6 import QtCore, QtTest, QtWidgets
except ImportError:
    if os.environ.get("NXSTYLE_REQUIRE_QT") == "1":
        raise  # dedicated CI must fail, not skip, if Qt or its runtime libraries are missing
    QtCore = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "NXStyle"))


@unittest.skipIf(QtCore is None, "PySide6 required; exercised by the qt-icons CI job")
class CheckBoxClickQt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.modules = patch.dict(sys.modules, {
            "nxstyle.qt": types.SimpleNamespace(QtCore=QtCore, QtWidgets=QtWidgets, Qt=QtCore.Qt)})
        self.modules.start()
        sys.modules.pop("nxstyle.widget_click", None)
        from nxstyle import widget_click
        self.wc = widget_click
        self.box = QtWidgets.QCheckBox("Add offset constraint")
        self.box.show()
        self.app.processEvents()

    def tearDown(self):
        self.box.close()
        self.box.deleteLater()
        sys.modules.pop("nxstyle.widget_click", None)
        self.modules.stop()

    def click_rect(self):
        opt = QtWidgets.QStyleOptionButton()
        self.box.initStyleOption(opt)
        return self.box.style().subElementRect(QtWidgets.QStyle.SE_CheckBoxClickRect, opt, self.box)

    def widen(self, extra):
        """Make the box as wide as a task panel's row: its centre `extra` px right of the label's end."""
        right = self.click_rect().right()
        self.box.resize(2 * (right + extra) + 1, self.box.sizeHint().height())
        self.app.processEvents()
        self.assertEqual(self.box.rect().center().x(), right + extra)

    def test_centre_click_right_of_the_label_is_ignored(self):
        # the trap the helper avoids: the widget's centre one pixel past the label (tutorial I after #48)
        self.widen(1)
        self.assertFalse(self.click_rect().contains(self.box.rect().center()))
        QtTest.QTest.mouseClick(self.box, QtCore.Qt.LeftButton)
        self.assertFalse(self.box.isChecked())

    def test_indicator_click_toggles_a_wide_box(self):
        for extra in (1, 200):
            with self.subTest(extra=extra):
                self.widen(extra)
                self.box.setChecked(False)
                self.assertTrue(self.click_rect().contains(self.wc.check_box_point(self.box)))
                self.assertTrue(self.wc.click_check_box(self.box, QtTest.QTest))
                self.assertFalse(self.wc.click_check_box(self.box, QtTest.QTest))

    def test_indicator_click_toggles_a_box_at_its_size_hint(self):
        self.box.resize(self.box.sizeHint())
        self.app.processEvents()
        self.assertTrue(self.wc.click_check_box(self.box, QtTest.QTest))


if __name__ == "__main__":
    unittest.main()
