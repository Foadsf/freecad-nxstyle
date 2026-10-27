# SPDX-License-Identifier: LGPL-2.1-or-later
"""Typed values keep their precision in FreeCAD's quantity fields, as in NX.

FreeCAD's Gui::QuantitySpinBox (the sketch's Insert Length dialog, task panels) shows its value with the
Units 'Decimals' preference (2 by default) and parses its own text back as the value whenever it rewrites
it: on focus-out (normalize) and on every setValue. (The sketcher's on-view fields do not normalize, and
keep what is typed.) So a typed 28.095 becomes 28.09 when the focus leaves
the field, e.g. on a click on OK (the double 28.094999... rounds down), and a dimension of 28.095 opened
again shows and holds 28.09, which OK then writes back. Raising the preference only moves the cut and pads
every value in FreeCAD with zeros (20.0000 mm).

The field's display format travels with its value (Qt property 'value', a Quantity). This filter gives a
field the decimals its value needs: after the user typed in it, just before FreeCAD normalizes it on
focus-out; and when FreeCAD shows a field bound to a property (its 'binding'), from that property's value,
if that value has at most RESTORE_DECIMALS decimals (a value somebody typed, not a drawn length)."""

import re

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtCore, QtWidgets
from .quantity_core import decimals_needed

UNITS = "User parameter:BaseApp/Preferences/Units"
CLASS = "Gui::QuantitySpinBox"
RESTORE_DECIMALS = 6          # 1 nm in mm; 1/64 in = 0.396875 mm


def preference_decimals():
    return App.ParamGet(UNITS).GetInt("Decimals", 2)


def displayed(q):
    """The number as the field shows it: in the unit FreeCAD's schema picks (mm, m, °, in, ...)."""
    try:
        _text, factor, _unit = q.getUserPreferred()
        return q.Value / factor if factor else q.Value
    except Exception:
        return q.Value


def shown_decimals(q):
    p = dict(q.Format).get("Precision", -1)
    return preference_decimals() if p is None or p < 0 else p


def field_of(obj):
    """The quantity field an event concerns: the field itself or its line edit; None for the sketcher's on-view
    fields, which sit in the 3D view and keep what is typed (positional and dimensional)."""
    try:
        w = obj if obj.inherits(CLASS) else None
        if w is None and isinstance(obj, QtWidgets.QLineEdit):
            p = obj.parent()
            w = p if p is not None and p.inherits(CLASS) else None
        if w is not None and in_3d_view(w):
            return None
        return w
    except RuntimeError:          # deleted widget
        return None


def in_3d_view(w):
    p = w.parentWidget()
    while p is not None:
        if p.inherits("Gui::View3DInventor"):
            return True
        p = p.parentWidget()
    return False


def show_with(w, q, decimals):
    """Set the field to q, shown with the given decimals (FreeCAD parses the text it shows as the value)."""
    fmt = dict(q.Format)
    fmt["Precision"] = decimals
    fmt["NumberFormat"] = "f"
    q.Format = fmt
    w.setProperty("value", q)


TYPED = "nxTyped"             # dynamic property: the user pressed a key in the field since it last lost focus


def typed_quantity(w, current):
    """The quantity the field's text says, read with FreeCAD's quantity parser in the field's unit, or None.

    A field with keyboard tracking off (the Pad's Length) takes its text only on focus-out, so its value
    property still holds the old value here. Text the parser cannot read (an expression naming an object)
    gives None."""
    try:
        loc = w.locale()
        text = w.lineEdit().text().replace(loc.groupSeparator(), "")
        if loc.decimalPoint() != ".":
            text = text.replace(loc.decimalPoint(), ".")
        q = App.Units.Quantity(text.strip())
        if q.Unit != current.Unit:
            q = q * App.Units.Quantity("1 " + w.property("unit")) if q.Unit == App.Units.Quantity(1).Unit else None
        return q if q is not None and q.Unit == current.Unit else None
    except Exception:
        return None


def keep_typed(w):
    """After the user typed in the field: widen its format to the decimals of what was typed. True when it did.

    QLineEdit.isModified() cannot tell: a task panel that recomputes on every key rewrites the text."""
    if not w.property(TYPED):
        return False
    w.setProperty(TYPED, False)
    if not w.property("autoNormalize"):
        return False               # FreeCAD leaves its text alone (the sketcher's on-view fields): nothing is cut
    current = w.property("value")
    if current is None or not hasattr(current, "Format"):
        return False
    q = typed_quantity(w, current)
    if q is None:
        if not w.keyboardTracking():
            return False           # the value property is not what was typed, and the text cannot be read here
        q = current
    need = decimals_needed(displayed(q))
    if need <= shown_decimals(current):
        return False
    q.Format = dict(current.Format)
    show_with(w, q, need)
    return True


def edited_object():
    try:
        vp = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument else None
        return vp.Object if vp is not None else None
    except Exception:
        return None


def bound_value(obj, path):
    """The value of the property a field is bound to (a path relative to the object in edit), or None.

    A sketch dimension's field is bound to 'Constraints[i]' (or 'Constraints.Name'): its datum, as a Quantity."""
    m = re.fullmatch(r"\.?Constraints(?:\[(\d+)\]|\.(\w+))", path)
    try:
        if m and obj.isDerivedFrom("Sketcher::SketchObject"):
            return obj.getDatum(int(m.group(1)) if m.group(1) is not None else m.group(2))
        return obj.evalExpression(path)
    except Exception:
        return None


def restore_bound(w):
    """A field FreeCAD filled from a property cut the property's decimals: give them back. True when it did."""
    path = w.property("binding")
    if not path or w.property("expression"):
        return False
    obj = edited_object()
    q = w.property("value")
    if obj is None or q is None or not hasattr(q, "Format"):
        return False
    true = bound_value(obj, path)
    if not hasattr(true, "Value") or not hasattr(true, "Unit") or true.Unit != q.Unit:
        return False
    shown = shown_decimals(q)
    tv, fv = displayed(true), displayed(q)
    need = decimals_needed(tv)
    # the field holds the property's value cut to its decimals: anything else is not this property's value
    if need <= shown or need > RESTORE_DECIMALS or abs(tv - fv) > 0.5 * 10 ** -shown + 1e-12 * max(1.0, abs(tv)):
        return False
    show_with(w, true, need)
    return True


class PreciseInput(QtCore.QObject):
    """Application event filter for FreeCAD's quantity fields. Never consumes an event."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.widened = 0
        self.restored = 0
        self.trace = []                # the last few actions, for the self-test and bug reports

    def note(self, text):
        self.trace = (self.trace + [text])[-8:]

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t != QtCore.QEvent.FocusOut and t != QtCore.QEvent.Show and t != QtCore.QEvent.KeyPress:
            return False
        w = field_of(obj)              # the field or its line edit: what follows does nothing the second time
        if w is None:
            return False
        try:
            name = w.objectName() or CLASS
            if t == QtCore.QEvent.KeyPress:
                if ev.text() and ev.text().isprintable() or ev.key() in (QtCore.Qt.Key_Backspace, QtCore.Qt.Key_Delete):
                    w.setProperty(TYPED, True)
            elif t == QtCore.QEvent.FocusOut:
                typed, before = w.property(TYPED), w.property("rawValue")
                if keep_typed(w):
                    self.widened += 1
                    self.note(f"typed: {name} = {w.property('rawValue')!r}")
                elif typed:
                    self.note(f"typed, kept as is: {name} = {before!r}")
            elif t == QtCore.QEvent.Show and restore_bound(w):
                self.restored += 1
                self.note(f"restored: {name} {w.property('binding')} = {w.property('rawValue')!r}")
        except Exception as e:
            self.note(f"error {e}")
        return False


_filter = None


def install():
    global _filter
    if _filter is None:
        _filter = PreciseInput(QtWidgets.QApplication.instance())
        QtWidgets.QApplication.instance().installEventFilter(_filter)
    return _filter
