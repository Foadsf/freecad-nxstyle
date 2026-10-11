# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX "Type Filter": restrict picking to one kind of object via a selection gate."""

import FreeCADGui as Gui

from .qt import QtWidgets

# (label, key) in NX's order; only kinds FreeCAD can tell apart are offered
TYPES = [
    ("No Selection Filter", None),
    ("Curve", "curve"),
    ("Datums", "datum"),
    ("Edge", "edge"),
    ("Face", "face"),
    ("Feature", "feature"),
    ("Point", "vertex"),
    ("Sketch", "sketch"),
    ("Solid Body", "body"),
]


def _leaf(obj, sub):
    """Resolve 'Body' + 'Pad.Face3' to (Pad, 'Face3')."""
    element = sub.split(".")[-1] if sub else ""
    leaf = obj
    if sub and "." in sub:
        try:
            found = obj.getSubObject(sub, 1)
            if found is not None:
                leaf = found
        except Exception:
            pass
    return leaf, element


def _is_datum(o):
    return (o.isDerivedFrom("Part::Datum") or o.TypeId in ("App::Plane", "App::Line", "App::Point", "App::Origin"))


class TypeGate:
    def __init__(self, kind):
        self.kind = kind

    def allow(self, doc, obj, sub):
        leaf, element = _leaf(obj, sub or "")
        k = self.kind
        if k == "face":
            return element.startswith("Face")
        if k == "edge":
            return element.startswith("Edge")
        if k == "vertex":
            return element.startswith("Vertex") or leaf.TypeId == "PartDesign::Point"
        if k == "curve":
            if element.startswith("Edge"):
                return True
            shape = getattr(leaf, "Shape", None)
            return bool(shape is not None and not shape.isNull() and shape.Edges and not shape.Faces)
        if k == "sketch":
            return leaf.isDerivedFrom("Sketcher::SketchObject") or obj.isDerivedFrom("Sketcher::SketchObject")
        if k == "datum":
            return _is_datum(leaf) or _is_datum(obj)
        if k == "feature":
            return leaf.isDerivedFrom("PartDesign::Feature") or leaf.isDerivedFrom("Part::Feature")
        if k == "body":
            if obj.isDerivedFrom("PartDesign::Body") or leaf.isDerivedFrom("PartDesign::Body"):
                return True
            shape = getattr(leaf, "Shape", None)
            return bool(shape is not None and not shape.isNull() and shape.Solids)
        return True


class TypeFilter(QtWidgets.QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NXTypeFilter")
        self.setToolTip("Type Filter: limit what can be selected")
        for label, key in TYPES:
            self.addItem(label, key)
        self.setMinimumContentsLength(16)
        self.currentIndexChanged.connect(self._changed)
        self.gate = None

    def _changed(self, index):
        self.apply(self.itemData(index))

    def apply(self, kind):
        try:
            Gui.Selection.removeSelectionGate()
        except Exception:
            pass
        self.gate = None
        if kind:
            self.gate = TypeGate(kind)
            Gui.Selection.addSelectionGate(self.gate)

    def reset(self):
        self.setCurrentIndex(0)
