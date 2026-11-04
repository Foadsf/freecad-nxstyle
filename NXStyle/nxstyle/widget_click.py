# SPDX-License-Identifier: LGPL-2.1-or-later
"""Where the replays click a widget as a user would (kept free of FreeCAD so a Qt test can check it)."""

from .qt import QtWidgets, Qt


def check_box_point(box):
    """The middle of a check box's indicator, where a user clicks it.

    A QCheckBox toggles only on its indicator and label (the style's SE_CheckBoxClickRect). In a task panel
    the box fills the row, so its centre can sit right of the label, and a click there does nothing. Tutorial
    I's "Add offset constraint": 306 px wide, label to x = 152, centre 152, toggled; #48's restyle made it
    308 px, centre 153, and the click stopped taking."""
    opt = QtWidgets.QStyleOptionButton()
    box.initStyleOption(opt)
    return box.style().subElementRect(QtWidgets.QStyle.SE_CheckBoxIndicator, opt, box).center()


def click_check_box(box, qtest):
    """MB1 on the box's indicator; returns whether the box is checked afterwards."""
    qtest.mouseClick(box, Qt.LeftButton, Qt.NoModifier, check_box_point(box))
    return box.isChecked()
