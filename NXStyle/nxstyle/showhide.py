# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX-style "Show and Hide" dialog: one row per object type with + / - buttons; and NX's Show with nothing
selected: the hidden objects in a list, the picked ones shown."""

import FreeCAD as App
import FreeCADGui as Gui

from .commands import CATEGORIES, category, display_objects, hidden_objects
from .qt import QtWidgets, Qt

_dialog = None
_show = None


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


class ShowDialog(QtWidgets.QDialog):
    """NX's Show (Ctrl+Shift+K) with nothing selected. NX shows the hidden objects in the graphics window to be
    picked; FreeCAD cannot pick a hidden object, so they are listed. OK shows the picked ones, as one undo step."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Show")
        self.setObjectName("NXShow")
        self.last = None                 # names the last OK showed, for tests
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Select the hidden objects to show"))
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("nxHidden")
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self._enable)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        lay.addWidget(self.list)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        lay.addWidget(buttons)
        self.rebuild()

    def rebuild(self):
        self.list.clear()
        doc = App.ActiveDocument
        for o in hidden_objects(doc) if doc is not None else []:
            item = QtWidgets.QListWidgetItem(f"{o.Label}   ({category(o)})")
            item.setData(Qt.UserRole, o.Name)
            self.list.addItem(item)
        if not self.list.count():
            item = QtWidgets.QListWidgetItem("Nothing is hidden")
            item.setFlags(Qt.NoItemFlags)
            self.list.addItem(item)
        self._enable()

    def _enable(self):
        self.ok.setEnabled(bool(self.picked()))

    def picked(self):
        return [i.data(Qt.UserRole) for i in self.list.selectedItems() if i.data(Qt.UserRole)]

    def accept(self):
        doc, names = App.ActiveDocument, self.picked()
        if doc is not None and names:
            doc.openTransaction("Show")
            for name in names:
                o = doc.getObject(name)
                if o is not None:
                    o.ViewObject.Visibility = True
            doc.commitTransaction()
        self.last = names
        _refresh()
        super().accept()


def show_hidden_dialog():
    global _show
    if _show is None:
        _show = ShowDialog(Gui.getMainWindow())
    _show.rebuild()
    _show.show()
    _show.raise_()
    _show.activateWindow()
    return _show
