# SPDX-License-Identifier: LGPL-2.1-or-later
"""Selection collectors in a command panel, and NX Edge Blend built on one.

A collector shows how many items it holds and whether that is enough, takes only what its command can
use, and says why it refused a pick (in the panel and on the cue line). Its curve rule adds a whole
chain from one pick: Single Curve, Tangent Curves or Connected Curves (``selection_core.chain``).

Edge Blend collects the edges of one body. With valid edges already selected it hands them straight to
FreeCAD's Fillet, as before; with nothing selected, or with something it cannot use among the
selection, it opens its collector first and hands the collected edges on with OK.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import selection_core as core, selection_filter as sf
from .qt import QtCore, QtWidgets

_last = {"route": None, "panel": None}


def last_route():
    """How the last Edge Blend started: 'direct' (FreeCAD's Fillet at once) or 'collector'."""
    return _last["route"]


def last_panel():
    return _last["panel"]


# ------------------------------------------------------------------ chains
def _key(p):
    return (round(p.x, 6), round(p.y, 6), round(p.z, 6))


def edge_records(shape):
    """{'EdgeN': (v0, v1, out0, out1)} for selection_core.chain: the end points, and the unit tangents
    there pointing into the edge (from the curve's parameters, so a reversed edge is no trouble)."""
    out = {}
    for i, e in enumerate(shape.Edges, 1):
        try:
            if e.Length < 1e-9:
                continue
            a, b = e.FirstParameter, e.LastParameter
            t0, t1 = e.tangentAt(a), e.tangentAt(b)
            t0.normalize()
            t1.normalize()
            out[f"Edge{i}"] = (_key(e.valueAt(a)), _key(e.valueAt(b)), (t0.x, t0.y, t0.z), (-t1.x, -t1.y, -t1.z))
        except Exception:
            continue      # a curve without tangents (degenerate): it can only be picked on its own
    return out


def chain_subs(pick, rule):
    """Sub-names of the edges the rule adds from an edge pick (the pick included)."""
    if rule == "single" or pick.kind != "edge":
        return [pick.sub]
    shape = getattr(pick.leaf, "Shape", None)
    if shape is None or shape.isNull():
        return [pick.sub]
    names = core.chain(edge_records(shape), pick.element, rule)
    prefix = pick.sub[:len(pick.sub) - len(pick.element)]
    return [prefix + n for n in names] or [pick.sub]


# ----------------------------------------------------------------- widget
class CollectorWidget(QtWidgets.QFrame):
    """One collector: '✱ Select Edge (0)' until it has enough, the curve rule, the collected items and
    the latest refusal."""

    def __init__(self, collector, rules=True, parent=None):
        super().__init__(parent)
        self.collector = collector
        self.setObjectName("NXCollector")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        row = QtWidgets.QHBoxLayout()
        self.mark = QtWidgets.QLabel()
        self.mark.setObjectName("NXCollectorMark")
        self.status = QtWidgets.QLabel()
        self.status.setObjectName("NXCollectorStatus")
        self.status.setAccessibleName("Selection collector")
        row.addWidget(self.mark)
        row.addWidget(self.status, 1)
        self.rule = QtWidgets.QComboBox()
        self.rule.setObjectName("NXCollectorRule")
        self.rule.setAccessibleName("Curve rule")
        for label, key in core.RULES:
            self.rule.addItem(label, key)
        self.rule.setVisible(rules)
        row.addWidget(self.rule)
        lay.addLayout(row)
        self.items = QtWidgets.QListWidget()
        self.items.setObjectName("NXCollectorItems")
        self.items.setMaximumHeight(110)
        lay.addWidget(self.items)
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("NXCollectorMessage")
        self.message.setWordWrap(True)
        lay.addWidget(self.message)
        self.refresh()

    def rule_key(self):
        return self.rule.currentData() or "single"

    def set_rule(self, key):
        i = self.rule.findData(key)
        if i >= 0:
            self.rule.setCurrentIndex(i)

    def refresh(self):
        c = self.collector
        self.status.setText(c.status())
        if c.valid:
            self.mark.setText("✔")
            self.mark.setStyleSheet("color: #1B7F3A; font-weight: bold;")
            self.mark.setToolTip("Enough selected")
        else:
            self.mark.setText("✱")
            self.mark.setStyleSheet("color: #C62828; font-weight: bold;")
            self.mark.setToolTip(c.problem())
        self.items.clear()
        for p in c.items:
            self.items.addItem(p.label)
        if c.rejected:
            label, reason = c.rejected[-1]
            self.message.setText(f"Refused {label}: {reason}")
            self.message.setStyleSheet("color: #C62828;")
            self.message.setToolTip("\n".join(f"{lb}: {r}" for lb, r in c.rejected))
        else:
            self.message.setText(c.problem().capitalize() if c.problem() else "")
            self.message.setStyleSheet("color: #5F6B76;")


# ------------------------------------------------------------- Edge Blend
def _unselect(doc, obj, sub):
    try:
        Gui.Selection.removeSelection(App.getDocument(doc).getObject(obj), sub)
    except Exception:
        pass


def _selection():
    out = []
    for s in Gui.Selection.getSelectionEx("", 0):
        for sub in (s.SubElementNames or [""]):
            out.append((s.DocumentName, s.ObjectName, sub))
    return out


class EdgeBlendPanel:
    """The collector stage of Edge Blend: the command's own gate is up while it is open."""

    def __init__(self, collector, before):
        self.collector = collector
        self.before = before
        self.open = True
        self.busy = False
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("NXEdgeBlendPanel")
        self.form.setWindowTitle("Edge Blend")
        lay = QtWidgets.QVBoxLayout(self.form)
        head = QtWidgets.QLabel("Edge to Blend")
        head.setStyleSheet("font-weight: bold;")
        lay.addWidget(head)
        self.widget = CollectorWidget(collector, rules=True)
        self.widget.set_rule("tangent")          # NX's default for Edge Blend
        lay.addWidget(self.widget)
        hint = QtWidgets.QLabel("OK hands the edges to FreeCAD's Fillet for the radius. "
                                "Hold MB1 over overlapping edges for QuickPick.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5F6B76;")
        lay.addWidget(hint)
        lay.addStretch(1)
        self.layer = sf.Layer("Edge Blend", verdict=self.verdict,
                              alive=lambda: self.open and bool(Gui.Control.activeDialog()))
        self.token = None

    # --- rules
    def verdict(self, pick):
        if pick.kind in self.collector.accepts:
            if pick.body is None:
                return False, (f"Edge Blend rounds the edges of a body; {pick.label} is not in one "
                               "(a Part workbench solid: use Part > Fillet)")
            if pick.through_link is not None:
                return False, (f"Edge Blend changes the part itself; {pick.label} is seen through the component "
                               f"{pick.through_link.Label}: open that part to blend it")
        return self.collector.verdict(pick)

    # --- life cycle
    def start(self):
        self.token = sf.manager().push(self.layer)
        sf.manager().listeners.append(self._refused)
        Gui.Selection.addObserver(self)
        self.widget.refresh()

    def finish(self):
        if not self.open:
            return
        self.open = False
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        m = sf.manager()
        if self._refused in m.listeners:
            m.listeners.remove(self._refused)
        m.pop(self.token)

    def _refused(self, pick, reason):
        self.collector.reject(pick.label, reason)
        self.widget.refresh()

    # --- selection observer
    def addSelection(self, doc, obj, sub, _pnt=None):
        if self.busy or not self.open:
            return
        try:
            pick = sf.Resolved(doc, obj, sub)
        except Exception:
            return
        ok, why = self.verdict(pick)
        if not ok:              # came past the gate (e.g. the gate was replaced): undo and say why
            self.collector.reject(pick.label, why)
            QtCore.QTimer.singleShot(0, lambda: _unselect(doc, obj, sub))
            self.widget.refresh()
            return
        self.busy = True
        try:
            for s in chain_subs(pick, self.widget.rule_key()):
                p = pick if s == pick.sub else sf.Resolved(doc, obj, s)
                if s != pick.sub and not self.verdict(p)[0]:
                    continue
                self.collector.offer(p)
                if s != pick.sub:
                    Gui.Selection.addSelection(doc, obj, s)
        finally:
            self.busy = False
        self.widget.refresh()

    def removeSelection(self, doc, obj, sub):
        if self.busy:
            return
        self.collector.remove((doc, obj, core.plain(sub)))
        self.widget.refresh()

    def clearSelection(self, doc):
        if self.busy:
            return
        self.collector.clear()
        self.widget.refresh()

    # --- task panel
    def getStandardButtons(self):
        return int(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)

    def accept(self):
        if not self.collector.valid:
            self.collector.reject("OK", self.collector.problem())
            self.widget.refresh()
            return False
        picks = list(self.collector.items)
        self.busy = True
        Gui.Selection.clearSelection()
        for p in picks:                       # still under the command's own gate
            Gui.Selection.addSelection(p.doc, p.top, p.sub)
        self.finish()
        Gui.Control.closeDialog()
        QtCore.QTimer.singleShot(0, lambda: Gui.runCommand("PartDesign_Fillet"))
        return True

    def reject(self):
        self.busy = True
        Gui.Selection.clearSelection()
        self.finish()                         # the previous gate is back before the old selection returns
        for doc, obj, sub in self.before:
            try:
                Gui.Selection.addSelection(doc, obj, sub)
            except Exception:
                pass
        Gui.Control.closeDialog()
        return True


class EdgeBlend:
    def GetResources(self):
        try:
            pix = Gui.Command.get("PartDesign_Fillet").getInfo().get("pixmap", "")
        except Exception:
            pix = ""
        return {"MenuText": "Edge Blend", "Pixmap": pix,
                "ToolTip": "Round the edges of a body. Selected edges go straight to the Fillet; otherwise "
                           "collect them first (Tangent Curves adds a smooth chain from one pick)"}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        before = _selection()
        collector = core.Collector("Select Edge", ["edge"], minimum=1, one_owner=True, command="Edge Blend")
        panel = EdgeBlendPanel(collector, before)
        refused = []
        for doc, obj, sub in before:
            try:
                pick = sf.Resolved(doc, obj, sub)
            except Exception:
                continue
            ok, why = panel.verdict(pick)
            if ok:
                collector.offer(pick)
            else:
                collector.reject(pick.label, why)
                refused.append((doc, obj, sub))
        _last["panel"] = panel
        if before and not refused and collector.valid:
            _last["route"] = "direct"
            Gui.runCommand("PartDesign_Fillet")
            return
        _last["route"] = "collector"
        for doc, obj, sub in refused:          # the selection shows what the collector holds
            _unselect(doc, obj, sub)
        panel.start()
        Gui.Control.showDialog(panel)
        panel.widget.refresh()


COMMANDS = {"NXStyle_EdgeBlend": EdgeBlend()}
