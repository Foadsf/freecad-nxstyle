# SPDX-License-Identifier: LGPL-2.1-or-later
"""Keyboard access to visible B-rep geometry, through the existing selection gates.

Only the current object's current page is expanded. Rows retain the document and
object identities and a native shape hash; topology is rechecked before selection.
Opening, browsing, refreshing and cancelling never change the native selection.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import selection_filter as sf
from .qt import QtCore, QtWidgets

PAGE_SIZE = 200
ROLE = QtCore.Qt.UserRole
_dialog = None


def _eligible(obj):
    try:
        view = obj.ViewObject
        if not view.Visibility or not getattr(view, "Selectable", True):
            return False, "hidden or not selectable"
        parent = getattr(obj, "getParentGeoFeatureGroup", lambda: None)()
        seen = [obj]
        while parent is not None:
            if parent in seen or len(seen) >= 64:
                return False, "unsupported cyclic containment"
            seen.append(parent)
            if not parent.ViewObject.Visibility:
                return False, "hidden by a containing part or body"
            parent = getattr(parent, "getParentGeoFeatureGroup", lambda: None)()
        shape = obj.Shape
        if shape is None or shape.isNull():
            return False, "no B-rep shape"
        if not shape.isValid():
            return False, "invalid B-rep shape"
        shape.hashCode()  # fail closed when topology cannot be checked
        return True, ""
    except Exception:
        return False, "unsupported shape or unavailable object"


def _stamp(obj):
    shape = obj.Shape
    return (shape.hashCode(), len(shape.Faces), len(shape.Edges), len(shape.Vertexes),
            str(getattr(obj, "Placement", "")))


def _address(obj):
    """Retain the containing occurrence, so a work-part scope sees the full path."""
    chain = [obj]
    parent = getattr(obj, "getParentGeoFeatureGroup", lambda: None)()
    while parent is not None:
        if parent in chain or len(chain) >= 64:
            raise ValueError("cyclic object containment")
        chain.insert(0, parent)
        parent = getattr(parent, "getParentGeoFeatureGroup", lambda: None)()
    return chain[0].Name, "".join(o.Name + "." for o in chain[1:])


def _xyz(point):
    return "({:.6g}, {:.6g}, {:.6g}) mm".format(point.x, point.y, point.z)


def _summary(shape, kind):
    if kind == "Face":
        return "area {:.6g} mm²; centre {}".format(shape.Area, _xyz(shape.CenterOfMass))
    if kind == "Edge":
        return "length {:.6g} mm".format(shape.Length)
    if kind == "Vertex":
        return "XYZ " + _xyz(shape.Point)
    return "{} faces; {} edges; {} vertices".format(
        len(shape.Faces), len(shape.Edges), len(shape.Vertexes))


def _selected():
    """Read unresolved names, including occurrences, rather than resolved leaf names."""
    return {(s.DocumentName, s.ObjectName, sub)
            for s in Gui.Selection.getSelectionEx("", 0)
            for sub in (s.SubElementNames or [""])}


class GeometrySelectionDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NXKeyboardGeometrySelection")
        self.setWindowTitle("Select Geometry - Keyboard")
        self.resize(780, 600)
        self.doc = None
        self.obj = None
        self.stamp = None
        self.address = None
        self.page = 0
        layout = QtWidgets.QVBoxLayout(self)
        help_text = QtWidgets.QLabel(
            "Choose an object and geometry type. Use arrows, Space, Ctrl and Shift in the geometry list. "
            "Enter selects; Escape closes. Add to current selection for picks across objects or pages. "
            "Active command collectors always add; selection filters still apply.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.search = QtWidgets.QLineEdit()
        self.search.setAccessibleName("Find objects by label or internal name")
        self._field(layout, "&Find objects:", self.search)
        self.objects = QtWidgets.QListWidget()
        self.objects.setAccessibleName("Visible selectable objects")
        self._field(layout, "&Objects:", self.objects)
        self.kind = QtWidgets.QComboBox()
        self.kind.addItems(["Object", "Face", "Edge", "Vertex"])
        self._field(layout, "Geometry &type:", self.kind)
        self.elements = QtWidgets.QListWidget()
        self.elements.setAccessibleName("Geometry; Space toggles, Shift extends selection")
        self.elements.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._field(layout, "&Geometry:", self.elements)
        pages = QtWidgets.QHBoxLayout()
        self.previous = QtWidgets.QPushButton("&Previous page")
        self.next = QtWidgets.QPushButton("&Next page")
        self.page_label = QtWidgets.QLabel()
        pages.addWidget(self.previous)
        pages.addWidget(self.page_label, 1)
        pages.addWidget(self.next)
        layout.addLayout(pages)
        self.add_to_selection = QtWidgets.QCheckBox("&Add to current selection")
        self.add_to_selection.setToolTip("Keep previous picks while adding objects or geometry from another page. Command collectors always add.")
        layout.addWidget(self.add_to_selection)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Selection status")
        self.status.setTextInteractionFlags(QtCore.Qt.TextSelectableByKeyboard)
        layout.addWidget(self.status)
        buttons = QtWidgets.QHBoxLayout()
        self.refresh_button = QtWidgets.QPushButton("&Refresh")
        self.select_button = QtWidgets.QPushButton("&Select")
        self.close_button = QtWidgets.QPushButton("&Close")
        for button in (self.previous, self.next, self.refresh_button, self.select_button, self.close_button):
            button.setAutoDefault(False)
        self.select_button.setDefault(True)
        buttons.addWidget(self.refresh_button)
        buttons.addStretch()
        buttons.addWidget(self.select_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.search.textChanged.connect(self._filter_objects)
        self.objects.currentItemChanged.connect(self._object_changed)
        self.kind.currentIndexChanged.connect(self._type_changed)
        self.previous.clicked.connect(lambda: self._move_page(-1))
        self.next.clicked.connect(lambda: self._move_page(1))
        self.refresh_button.clicked.connect(self.refresh)
        self.select_button.clicked.connect(self.apply_selection)
        self.close_button.clicked.connect(self.reject)
        self.elements.itemActivated.connect(lambda _: self.apply_selection())
        # QListWidget consumes Return on some Qt versions. Handle it exactly once.
        for child in self.findChildren(QtWidgets.QWidget):
            child.installEventFilter(self)
        QtWidgets.QWidget.setTabOrder(self.search, self.objects)
        QtWidgets.QWidget.setTabOrder(self.objects, self.kind)
        QtWidgets.QWidget.setTabOrder(self.kind, self.elements)
        QtWidgets.QWidget.setTabOrder(self.elements, self.previous)
        QtWidgets.QWidget.setTabOrder(self.previous, self.next)
        QtWidgets.QWidget.setTabOrder(self.next, self.add_to_selection)
        QtWidgets.QWidget.setTabOrder(self.add_to_selection, self.refresh_button)
        QtWidgets.QWidget.setTabOrder(self.refresh_button, self.select_button)
        QtWidgets.QWidget.setTabOrder(self.select_button, self.close_button)
        self.refresh()
        self.search.setFocus()

    @staticmethod
    def _field(layout, text, widget):
        label = QtWidgets.QLabel(text)
        label.setBuddy(widget)
        layout.addWidget(label)
        layout.addWidget(widget)

    def event(self, event):
        if self._mnemonic(event):
            return True
        return super().event(event)

    def _mnemonic(self, event):
        # FreeCAD's hidden menu accelerators also claim Alt+F/Alt+T. A local
        # dialog mnemonic must win while this dialog (or one of its fields) has
        # focus; accepting ShortcutOverride prevents an ambiguous global match.
        if event.type() in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress):
            if event.modifiers() == QtCore.Qt.AltModifier and hasattr(self, "close_button"):
                targets = {QtCore.Qt.Key_F: self.search, QtCore.Qt.Key_O: self.objects,
                           QtCore.Qt.Key_T: self.kind, QtCore.Qt.Key_G: self.elements,
                           QtCore.Qt.Key_P: self.previous, QtCore.Qt.Key_N: self.next,
                           QtCore.Qt.Key_A: self.add_to_selection, QtCore.Qt.Key_R: self.refresh_button,
                           QtCore.Qt.Key_S: self.select_button, QtCore.Qt.Key_C: self.close_button}
                target = targets.get(event.key())
                if target is not None:
                    event.accept()
                    if event.type() == QtCore.QEvent.KeyPress and target.isEnabled():
                        if isinstance(target, QtWidgets.QAbstractButton):
                            target.animateClick()
                        else:
                            target.setFocus(QtCore.Qt.ShortcutFocusReason)
                    return True
        return False

    def eventFilter(self, watched, event):
        if self._mnemonic(event):
            return True
        if watched is self.elements and event.type() == QtCore.QEvent.KeyPress:
            if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                self.apply_selection()
                return True
            if event.key() == QtCore.Qt.Key_Space and event.modifiers() == QtCore.Qt.NoModifier:
                item = self.elements.currentItem()
                if item is not None:
                    item.setSelected(not item.isSelected())
                return True
        return super().eventFilter(watched, event)

    def refresh(self):
        self.doc = App.ActiveDocument
        self.objects.clear()
        self.obj, self.stamp, self.address = None, None, None
        excluded = 0
        if self.doc is not None:
            for obj in self.doc.Objects:
                ok, _ = _eligible(obj)
                if not ok:
                    excluded += 1
                    continue
                row = QtWidgets.QListWidgetItem("{} [{}]".format(obj.Label, obj.Name))
                row.setData(ROLE, obj)
                self.objects.addItem(row)
        self._filter_objects()
        self.status.setText(
            "{} available objects; {} excluded (hidden, non-selectable, null, invalid or unsupported B-rep). "
            "Meshes, datums and shapeless containers are unsupported here. Refresh after document changes."
            .format(self.objects.count(), excluded) if self.doc is not None else "No active document. Open a model and Refresh.")

    def _filter_objects(self, *_):
        query = self.search.text().casefold().strip()
        first = None
        for i in range(self.objects.count()):
            item = self.objects.item(i)
            item.setHidden(query not in item.text().casefold())
            if first is None and not item.isHidden():
                first = item
        current = self.objects.currentItem()
        if current is None or current.isHidden():
            self.objects.setCurrentItem(first)
        if first is None:
            self.obj, self.stamp = None, None
            self._type_changed()

    def _object_changed(self, current, _previous=None):
        self.obj = current.data(ROLE) if current is not None else None
        try:
            self.stamp = _stamp(self.obj) if self.obj is not None else None
            self.address = _address(self.obj) if self.obj is not None else None
        except Exception:
            self.stamp, self.address = None, None
        self._type_changed()

    def _type_changed(self, *_):
        self.page = 0
        self._load_elements()

    def _move_page(self, delta):
        self.page += delta
        self._load_elements()

    def _valid(self):
        try:
            if (self.doc is None or App.ActiveDocument is not self.doc or
                    App.getDocument(self.doc.Name) is not self.doc):
                return False, "The active document changed or closed. Refresh before selecting."
            if self.obj is None or self.doc.getObject(self.obj.Name) is not self.obj:
                return False, "The object was removed or replaced. Refresh before selecting."
            ok, why = _eligible(self.obj)
            if not ok:
                return False, "Object is {}. Refresh before selecting.".format(why)
            if _stamp(self.obj) != self.stamp or _address(self.obj) != self.address:
                return False, "Geometry or containment changed. Refresh before selecting."
            return True, ""
        except Exception:
            return False, "Object or geometry is unavailable. Refresh before selecting."

    def _load_elements(self):
        self.elements.clear()
        self.select_button.setEnabled(False)
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.page_label.setText("No geometry")
        if self.obj is None:
            return
        ok, why = self._valid()
        if not ok:
            self.status.setText(why)
            return
        kind = self.kind.currentText()
        shape = self.obj.Shape
        items = [shape] if kind == "Object" else getattr(shape, {"Face": "Faces", "Edge": "Edges", "Vertex": "Vertexes"}[kind])
        count = len(items)
        self.page = max(0, min(self.page, max(0, (count - 1) // PAGE_SIZE)))
        start = self.page * PAGE_SIZE
        for i in range(start, min(start + PAGE_SIZE, count)):
            sub = "" if kind == "Object" else kind + str(i + 1)
            row = QtWidgets.QListWidgetItem("{} - {}".format(sub or self.obj.Name, _summary(items[i], kind)))
            row.setData(ROLE, sub)
            self.elements.addItem(row)
        if self.elements.count():
            self.elements.setCurrentRow(0)
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(start + PAGE_SIZE < count)
        self.select_button.setEnabled(bool(count))
        self.page_label.setText("{}-{} of {} (selection applies to this page)".format(start + 1 if count else 0, min(start + PAGE_SIZE, count), count))

    def apply_selection(self):
        ok, why = self._valid()
        if not ok:
            self.status.setText(why)
            return False
        rows = self.elements.selectedItems()
        if not rows:
            self.status.setText("Choose geometry with arrows and Space before selecting.")
            return False
        top, prefix = self.address
        requested = [(self.doc.Name, top, prefix + row.data(ROLE)) for row in rows]
        manager = sf.manager()
        try:
            for doc, name, sub in requested:
                allowed, reason, _ = manager.verdict(doc, name, sub)
                if not allowed:
                    self.status.setText("Cannot select: " + reason)
                    return False
            before = _selected()
        except Exception:
            self.status.setText("Cannot verify the current selection policy or selection. No selection changed.")
            return False
        added = []
        try:
            # Keep existing picks until the native gate has accepted every request.
            for key in requested:
                valid, reason = self._valid()
                if not valid:
                    raise RuntimeError(reason)
                allowed, reason, _ = manager.verdict(*key)
                if not allowed:
                    raise RuntimeError(reason)
                if key in before:
                    continue
                Gui.Selection.addSelection(*key)
                if key not in _selected():
                    raise RuntimeError("The active native selection gate or collector refused the geometry.")
                added.append(key)
            collecting = self.add_to_selection.isChecked() or bool(manager.tasks) or bool(Gui.Control.activeDialog())
            if not collecting:
                for key in before - set(requested):
                    Gui.Selection.removeSelection(*key)
                # Removing a whole object can also remove its newly added faces.
                # Re-add those exact names through the gate after pruning the old picks.
                for key in set(requested) - _selected():
                    valid, reason = self._valid()
                    if not valid:
                        raise RuntimeError(reason)
                    allowed, reason, _ = manager.verdict(*key)
                    if not allowed:
                        raise RuntimeError(reason)
                    Gui.Selection.addSelection(*key)
            if not set(requested).issubset(_selected()):
                raise RuntimeError("The native selection changed while selecting. Refresh and try again.")
        except Exception as error:
            for key in added:
                try:
                    Gui.Selection.removeSelection(*key)
                except Exception:
                    pass
            # A native observer can alter selection while it is being pruned.
            # Restore prior names only through the current gate; never bypass it.
            try:
                for key in before - _selected():
                    Gui.Selection.addSelection(*key)
                restored = before.issubset(_selected())
            except Exception:
                restored = False
            self.status.setText("Cannot select: {}".format(error))
            if not restored:
                self.status.setText(self.status.text() + " The current gate prevented restoring some previous picks.")
            return False
        self.status.setText("Selected {} geometry item(s) through the active selection policy.".format(len(requested)))
        return True


def show():
    """Show one modeless keyboard dialog without taking over a task panel or gate."""
    global _dialog
    if _dialog is None:
        _dialog = GeometrySelectionDialog(Gui.getMainWindow())
    elif not _dialog.isVisible():
        _dialog.refresh()
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    _dialog.search.setFocus()
    return _dialog
