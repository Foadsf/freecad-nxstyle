# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX-style "Show and Hide" dialog: one row per object type with + / - buttons."""

import FreeCAD as App
import FreeCADGui as Gui

from .commands import CATEGORIES, category, display_objects
from .qt import QtWidgets, Qt

_dialog = None


def _set(cat, visible):
    doc = App.ActiveDocument
    if doc is None:
        return
    doc.openTransaction(("Show " if visible else "Hide ") + (cat or "All"))
    for o in display_objects(doc):
        if cat is None or category(o) == cat:
            o.ViewObject.Visibility = visible
    doc.commitTransaction()
    _refresh()


def _counts():
    doc = App.ActiveDocument
    counts = {c: [0, 0] for c in CATEGORIES}
    if doc is None:
        return counts
    for o in display_objects(doc):
        c = counts[category(o)]
        c[0] += 1
        c[1] += 1 if o.ViewObject.Visibility else 0
    return counts


class ShowHideDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Show and Hide")
        self.setObjectName("NXShowHide")
        lay = QtWidgets.QVBoxLayout(self)
        self.grid = QtWidgets.QGridLayout()
        lay.addLayout(self.grid)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        lay.addWidget(buttons)
        self.rebuild()

    def rebuild(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for col, text in enumerate(("Type", "Show", "Hide", "Shown")):
            h = QtWidgets.QLabel(f"<b>{text}</b>")
            self.grid.addWidget(h, 0, col, Qt.AlignCenter if col else Qt.AlignLeft)
        counts = _counts()
        rows = [("All", None)] + [(c, c) for c in CATEGORIES if counts[c][0]]
        for r, (label, cat) in enumerate(rows, start=1):
            self.grid.addWidget(QtWidgets.QLabel(label), r, 0)
            show = QtWidgets.QPushButton("+")
            hide = QtWidgets.QPushButton("−")
            for b in (show, hide):
                b.setFixedWidth(36)
            show.clicked.connect(lambda _=False, c=cat: _set(c, True))
            hide.clicked.connect(lambda _=False, c=cat: _set(c, False))
            self.grid.addWidget(show, r, 1, Qt.AlignCenter)
            self.grid.addWidget(hide, r, 2, Qt.AlignCenter)
            if cat:
                total, shown = counts[cat]
                self.grid.addWidget(QtWidgets.QLabel(f"{shown}/{total}"), r, 3, Qt.AlignCenter)


def _refresh():
    if _dialog is not None and _dialog.isVisible():
        _dialog.rebuild()


def show_dialog():
    global _dialog
    if _dialog is None:
        _dialog = ShowHideDialog(Gui.getMainWindow())
    _dialog.rebuild()
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    return _dialog
