# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Part Navigator's status strip: work part, active body, suppressed and failed features, and the
occurrence the selection is on.

FreeCAD's tree shows a failed feature with a small overlay and a suppressed one not at all (FreeCAD
1.1.4). NX's navigator makes both plain, and names the work part. The strip sits above the tree; the
tree items of suppressed features are struck through and those of failed ones are red, with the error
as their tooltip. Clicking a count selects those features.
"""

import html

import FreeCAD as App
import FreeCADGui as Gui

from . import selection_filter as sf
from .qt import QtCore, QtGui, QtWidgets, Qt

RED = "#C62828"
GREY = "#8A9199"


def is_suppressed(o):
    return "Suppressed" in o.PropertiesList and bool(getattr(o, "Suppressed", False))


def has_error(o):
    try:
        return "Invalid" in o.State or "Error" in o.State
    except Exception:
        return False


def state(doc=None):
    """What the strip shows, as plain data (for tests too)."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return {"doc": None, "work": "", "body": "", "suppressed": [], "errors": [], "selected": ""}
    body = None
    try:
        body = Gui.getDocument(doc.Name).ActiveView.getActiveObject("pdbody")
    except Exception:
        pass
    selected = ""
    sel = Gui.Selection.getSelectionEx(doc.Name, 0)
    if sel:
        s = sel[0]
        try:
            selected = sf.Resolved(doc.Name, s.ObjectName, (s.SubElementNames or [""])[0]).label
        except Exception:
            selected = s.Object.Label
        more = sum(max(len(x.SubElementNames), 1) for x in sel) - 1
        if more:
            selected += f" (+{more})"
    errors = []
    for o in doc.Objects:
        if has_error(o):
            try:
                msg = o.getStatusString()
            except Exception:
                msg = ""
            errors.append((o.Name, o.Label, msg))
    return {"doc": doc.Name, "work": sf.work_part_text() or doc.Label, "body": body.Label if body else "",
            "body_name": body.Name if body else "",
            "suppressed": [(o.Name, o.Label) for o in doc.Objects if is_suppressed(o)],
            "errors": errors, "selected": selected}


def model_tree():
    dock = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Model")
    if dock is None:
        return None
    trees = [t for t in dock.findChildren(QtWidgets.QTreeWidget) if t.metaObject().className() == "Gui::TreeWidget"]
    return trees[0] if trees else None


class NavigatorStatus(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NXNavigatorStatus")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(1)
        self.labels = {}
        for key in ("work", "body", "suppressed", "errors", "selected"):
            lab = QtWidgets.QLabel()
            lab.setObjectName(f"NXNav_{key}")
            lab.setTextFormat(Qt.RichText)
            lab.linkActivated.connect(self._select)
            lab.setWordWrap(True)
            lay.addWidget(lab)
            self.labels[key] = lab
        self.last = None
        self.decorated = {}          # (doc, name) -> 'suppressed' | 'error'
        self.ticks = 0

    def minimumSizeHint(self):
        # Wrapped labels in a narrow Part Navigator would set the whole window's minimum height (the docks
        # share it), so a short window could not fit 1366x768 at 200 %. Even one line is too much there, so
        # the strip may fold away; the tree items keep their suppressed and error marks.
        return QtCore.QSize(super().minimumSizeHint().width(), 0)

    def text(self):
        """The strip as plain text (for tests)."""
        return " | ".join(QtGui.QTextDocumentFragment.fromHtml(lab.text()).toPlainText()
                          for lab in self.labels.values() if lab.isVisibleTo(self))

    def _select(self, which):
        st = self.last or {}
        doc = st.get("doc")
        names = [n for n, _ in st.get("suppressed", [])] if which == "suppressed" else \
            [n for n, _, _ in st.get("errors", [])]
        if not doc or not names:
            return
        Gui.Selection.clearSelection()
        for n in names:
            Gui.Selection.addSelection(doc, n)

    def refresh(self, force=False):
        st = state()
        self.ticks += 1
        if st == self.last and not force and self.ticks % 7:
            return st
        L = self.labels
        e = html.escape
        L["work"].setText(f"Work part: <b>{e(st['work'])}</b>" if st["doc"] else "No part open")
        L["body"].setText(f"Active body: <b>{e(st['body'])}</b>" if st["body"] else "Active body: none")
        L["body"].setVisible(bool(st["doc"]))
        sup = st["suppressed"]
        L["suppressed"].setText(f"<a href='suppressed' style='color:{GREY}'>Suppressed: {len(sup)}</a> "
                                + e(", ".join(lb for _, lb in sup)))
        L["suppressed"].setVisible(bool(sup))
        err = st["errors"]
        L["errors"].setText(f"<a href='errors' style='color:{RED}'>Errors: {len(err)}</a> "
                            + e(", ".join(f"{lb}" for _, lb, _ in err)))
        L["errors"].setToolTip("\n".join(f"{lb}: {msg}" for _, lb, msg in err))
        L["errors"].setVisible(bool(err))
        L["selected"].setText(f"Selected: {e(st['selected'])}")
        L["selected"].setVisible(bool(st["selected"]))
        self.last = st
        self.decorate(st)
        return st

    def decorate(self, st):
        """Strike suppressed features through and colour failed ones in FreeCAD's tree."""
        tree = model_tree()
        if tree is None or not st["doc"]:
            return
        doc = App.getDocument(st["doc"])
        want = {(doc.Name, n): "suppressed" for n, _ in st["suppressed"]}
        tips = {}
        for n, _, msg in st["errors"]:
            want[(doc.Name, n)] = "error"
            tips[n] = msg
        top = None
        for i in range(tree.topLevelItemCount()):
            it = tree.topLevelItem(i)
            if it.text(0) in (doc.Label, doc.Name):
                top = it
                break
        if top is None:
            return
        stack = [top.child(i) for i in range(top.childCount())]
        done = set()
        while stack:
            it = stack.pop()
            stack += [it.child(i) for i in range(it.childCount())]
            name = it.text(2) if tree.columnCount() > 2 else ""
            key = (doc.Name, name)
            kind = want.get(key)
            f = it.font(0)
            if kind:
                f.setStrikeOut(kind == "suppressed")
                it.setFont(0, f)
                it.setForeground(0, QtGui.QBrush(QtGui.QColor(GREY if kind == "suppressed" else RED)))
                it.setToolTip(0, "Suppressed (Suppress again to switch it back on)" if kind == "suppressed"
                              else f"Error: {tips.get(name) or 'the feature failed to update'}")
                done.add(key)
            elif key in self.decorated:
                f.setStrikeOut(False)
                it.setFont(0, f)
                it.setData(0, Qt.ForegroundRole, None)
                it.setToolTip(0, "")
        self.decorated = {k: want[k] for k in done}

    def item_looks(self, name):
        """{'strike', 'color', 'tip'} of the tree items for an object (for tests)."""
        tree = model_tree()
        out = []
        if tree is None:
            return out
        it = QtWidgets.QTreeWidgetItemIterator(tree)
        while it.value():
            v = it.value()
            if tree.columnCount() > 2 and v.text(2) == name:
                out.append({"strike": v.font(0).strikeOut(), "color": v.foreground(0).color().name(),
                            "tip": v.toolTip(0)})
            it += 1
        return out


def attach(mw):
    """Put the strip above the tree in the Part Navigator; returns it (None when the tree is not found)."""
    dock = mw.findChild(QtWidgets.QDockWidget, "Model")
    if dock is None:
        return None
    panel = next((w for w in dock.findChildren(QtWidgets.QWidget)
                  if w.metaObject().className() == "Gui::TreePanel"), None)
    if panel is None or panel.layout() is None:
        return None
    old = panel.findChild(QtWidgets.QFrame, "NXNavigatorStatus")
    if old is not None:
        return old
    strip = NavigatorStatus(panel)
    panel.layout().insertWidget(0, strip)
    return strip
