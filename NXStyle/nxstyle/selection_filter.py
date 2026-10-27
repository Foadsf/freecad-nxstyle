# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX selection: the Type Filter, the Selection Scope, and the gates commands put up while they collect.

FreeCAD has one selection gate at a time, and whoever installs one replaces the last. The gate manager
keeps NX's layers instead: the global filter (Type Filter and Selection Scope) underneath, the gates of
running commands on top. Only the top layer is in force; when a command ends its layer is popped and the
one underneath comes back. Changing the Type Filter while a command collects changes the global layer
only, and while one of FreeCAD's own dialogs is open (they put up gates of their own, which NXStyle
cannot read) the change waits until the dialog closes. Every refusal says why: the reason goes to the
cue line and to the collector of the command that asked.
"""

import time

import FreeCAD as App
import FreeCADGui as Gui

from . import selection_core as core
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
TYPE_LABELS = {key: label for label, key in TYPES}


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


def type_ok(kind, obj, sub):
    """Does the pick obj + sub match one Type Filter kind?"""
    leaf, element = _leaf(obj, sub or "")
    k = kind
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


class TypeGate:
    """A plain FreeCAD gate for one Type Filter kind (or several)."""

    def __init__(self, kind):
        self.kinds = (kind,) if isinstance(kind, str) or kind is None else tuple(kind)

    def allow(self, doc, obj, sub):
        return any(k is None or type_ok(k, obj, sub) for k in self.kinds)


# ------------------------------------------------------------------ picks
def _obj(doc, obj):
    if isinstance(obj, str):
        d = App.getDocument(doc) if isinstance(doc, str) else doc
        return d.getObject(obj)
    return obj


def is_component(o):
    """A component occurrence in NX terms: a part container, or a link to anything."""
    return o is not None and (o.isDerivedFrom("App::Part") or o.isDerivedFrom("App::Link"))


def element_kind(leaf, element):
    if element.startswith("Face"):
        return "face"
    if element.startswith("Edge"):
        return "edge"
    if element.startswith("Vertex"):
        return "vertex"
    if leaf is None:
        return "object"
    if leaf.isDerivedFrom("Sketcher::SketchObject"):
        return "sketch"
    if _is_datum(leaf):
        return "datum"
    if leaf.isDerivedFrom("PartDesign::Body"):
        return "body"
    if leaf.isDerivedFrom("PartDesign::Feature") or leaf.isDerivedFrom("Part::Feature"):
        return "feature"
    return "object"


def body_of(o):
    """The PartDesign Body o is (in), or None."""
    if o is None:
        return None
    if o.isDerivedFrom("PartDesign::Body"):
        return o
    try:
        p = o.getParentGeoFeatureGroup()
    except Exception:
        return None
    return p if p is not None and p.isDerivedFrom("PartDesign::Body") else None


class Resolved(core.Pick):
    """A Pick with the FreeCAD objects behind it."""

    def __init__(self, doc, obj, sub):
        top = _obj(doc, obj)
        docname = doc if isinstance(doc, str) else doc.Name
        sub = core.plain(sub)
        path, element = core.split(top.Name, sub)
        objs = [top]
        for i in range(1, len(path)):
            try:
                objs.append(top.getSubObject(".".join(path[1:i + 1]) + ".", 1))
            except Exception:
                objs.append(None)
        self.objects = objs
        self.components = tuple(is_component(o) for o in objs)
        self.labels = {n: (o.Label if o is not None else n) for n, o in zip(path, objs)}
        self.leaf, _ = _leaf(top, sub or "")
        self.body = body_of(self.leaf)
        kind = element_kind(self.leaf, element)
        where = core.path_text(path, self.labels)
        super().__init__(docname, top.Name, sub, kind, self.body.Name if self.body is not None else "",
                         f"{element} of {where}" if element else where)
        self.top_obj = top
        self.through_link = next((o for o in objs[1:-1] if o is not None and o.isDerivedFrom("App::Link")), None)


def work_part():
    """The work part's occurrence path (FreeCAD's active part, wherever it was activated), or None."""
    try:
        raw = Gui.ActiveDocument.ActiveView.getActiveObject("part", False)
    except Exception:
        return None
    if not raw:
        return None
    obj, parent, sub = raw if isinstance(raw, tuple) else (raw, None, "")
    if obj is None:
        return None
    if parent is not None and sub:
        return core.split(parent.Name, sub)[0]
    chain = [obj]
    p = obj.getParentGeoFeatureGroup()
    while p is not None and len(chain) < 64:
        chain.insert(0, p)
        p = p.getParentGeoFeatureGroup()
    return tuple(o.Name for o in chain)


def work_part_text():
    path = work_part()
    if not path:
        return ""
    try:
        doc = App.ActiveDocument
        top = doc.getObject(path[0])
        labels = {path[0]: top.Label}
        for i in range(1, len(path)):
            o = top.getSubObject(".".join(path[1:i + 1]) + ".", 1)
            labels[path[i]] = o.Label if o is not None else path[i]
        return core.path_text(path, labels)
    except Exception:
        return core.path_text(path)


def foreign_dialog():
    """A task dialog is open that is not one of NXStyle's collectors (FreeCAD's own may hold a gate)."""
    try:
        return bool(Gui.Control.activeDialog()) and not manager().tasks
    except Exception:
        return False


# ------------------------------------------------------------- the manager
class Layer:
    def __init__(self, owner, verdict=None, kinds=None, alive=None):
        self.owner, self.kinds, self.alive = owner, kinds, alive
        self._verdict = verdict

    def verdict(self, pick):
        if self._verdict is not None:
            return self._verdict(pick)
        if self.kinds and pick.kind not in self.kinds:
            return False, f"{self.owner} takes {' or '.join(core.NOUNS.get(k, k) for k in self.kinds)}"
        return True, ""


class NxGate:
    """The one gate NXStyle installs; it asks the manager."""

    def allow(self, doc, obj, sub):
        try:
            ok, reason, pick = manager().verdict(doc, obj, sub)
        except Exception as e:      # never block selection because of a bug here
            App.Console.PrintWarning(f"NXStyle selection gate: {e}\n")
            return True
        if not ok:
            manager().note_rejection(pick, reason)
        return ok


class GateManager:
    REASON_SHOWN_S = 4.0

    def __init__(self):
        self.global_kind = None             # Type Filter key, None = no filter
        self.scope = "assembly"             # Selection Scope key
        self.curve_rule = "inferred"        # Curve Rule key (selection_core.SECTION_RULES) for sections
        self.rule_listeners = []            # f(rule) when the curve rule changes
        self.tasks = []                     # [(token, Layer)], top last
        self.gate = NxGate()
        self.installed = False
        self.deferred = False               # a global change waits for a FreeCAD dialog to close
        self._dialog = False
        self._next = 1
        self.rejections = []                # (time, pick label, reason, key), latest last
        self.listeners = []                 # f(pick, reason) for each new refusal
        self.history = []                   # what install() did, for tests: "task:Edge Blend", "global", "none"

    # -------------------------------------------------------------- verdicts
    def top(self):
        return self.tasks[-1][1] if self.tasks else None

    def needed(self):
        return bool(self.tasks) or self.global_kind is not None or self.scope != "assembly"

    def verdict(self, doc, obj, sub, layer="top"):
        """(ok, reason, pick) under the layer in force (or the given one: None = the global layer)."""
        pick = Resolved(doc, obj, sub)
        ok, why = core.scope_verdict(pick.path, pick.components, work_part(), self.scope, pick.labels)
        if not ok:
            return False, why, pick
        layer = self.top() if layer == "top" else layer
        if layer is not None:
            ok, why = layer.verdict(pick)
            return ok, why, pick
        if self.global_kind is not None and not type_ok(self.global_kind, pick.top_obj, pick.sub):
            return False, (f"the Type Filter is {TYPE_LABELS[self.global_kind]}, and {pick.label} is "
                           f"{core.NOUNS.get(pick.kind, pick.kind)}"), pick
        return True, "", pick

    def note_rejection(self, pick, reason):
        now = time.monotonic()
        last = self.rejections[-1] if self.rejections else None
        if last is not None and last[3] == pick.key and now - last[0] < 2.0:
            return          # the gate is asked again while the cursor rests on the same thing
        self.rejections.append((now, pick.label, reason, pick.key))
        del self.rejections[:-50]
        for f in list(self.listeners):
            try:
                f(pick, reason)
            except Exception:
                pass

    def recent_rejection(self):
        """'Cannot select Face6 of Asm › UnitB: ...' while it is fresh, else ''."""
        if self.rejections and time.monotonic() - self.rejections[-1][0] < self.REASON_SHOWN_S:
            _, label, reason, _ = self.rejections[-1]
            return f"Cannot select {label}: {reason}"
        return ""

    # -------------------------------------------------------------- the gate
    def install(self, closing_own=False):
        if not closing_own and foreign_dialog():
            # FreeCAD's dialog may have a gate of its own up: leave it alone until the dialog closes
            self.deferred = True
            self.history.append("deferred")
            return
        if self.needed():
            # unresolved: the gate gets the top object and the whole occurrence path ('Asm', 'UnitB.Box.Face6');
            # resolved, FreeCAD hands over the leaf ('Box', 'Face6') and the two look-alike links are one
            no_resolve = getattr(getattr(Gui.Selection, "ResolveMode", None), "NoResolve", 0)
            Gui.Selection.addSelectionGate(self.gate, no_resolve)
            self.installed = True
            self.history.append(f"task:{self.top().owner}" if self.tasks else "global")
        else:
            if self.installed:
                Gui.Selection.removeSelectionGate()
            self.installed = False
            self.history.append("none")
        del self.history[:-50]

    def set_global(self, kind=..., scope=...):
        """Change the Type Filter or the Selection Scope. A command's own selection rules stay in force:
        a new Type Filter reaches the gate when the command ends. The scope says where picks may come
        from, for the command too, so it applies at once."""
        if kind is not ...:
            self.global_kind = kind
        if scope is not ...:
            self.scope = scope
        if self.tasks:
            return "after the command" if kind is not ... else "now"
        self.deferred = False
        self.install()
        return "after the dialog" if self.deferred else "now"

    def set_curve_rule(self, rule):
        """The curve rule a section collector applies to a picked curve (it does not gate the selection)."""
        if rule not in {k for _, k in core.SECTION_RULES} or rule == self.curve_rule:
            return
        self.curve_rule = rule
        for f in list(self.rule_listeners):
            try:
                f(rule)
            except Exception:
                pass

    def push(self, layer):
        token = self._next
        self._next += 1
        self.tasks.append((token, layer))
        self.deferred = False
        self.install()
        return token

    def pop(self, token):
        """End a command's gate; the one underneath (the global filter) is back in force."""
        before = len(self.tasks)
        self.tasks = [(t, la) for t, la in self.tasks if t != token]
        if len(self.tasks) != before:
            self.install(closing_own=True)     # the dialog still open is the command's own, closing

    def sync(self):
        """Called by the shell's timer: drop the gates of commands whose dialogs are gone, and put the
        global gate back after one of FreeCAD's own dialogs (which removes whatever gate is up when it
        closes) has closed."""
        for token, layer in list(self.tasks):
            if layer.alive is not None and not layer.alive():
                self.pop(token)
        try:
            dialog = bool(Gui.Control.activeDialog())
        except Exception:
            dialog = False
        if self._dialog and not dialog and not self.tasks:
            self.deferred = False
            self.install()
        self._dialog = dialog


_manager = None


def manager():
    global _manager
    if _manager is None:
        _manager = GateManager()
    return _manager


# --------------------------------------------------------- ray hits / rows
def rows_at(view, xy, layer="top"):
    """Everything under the point xy (Coin pixel coordinates), nearest first, one row per pick, each
    with the verdict of the layer in force: {'doc','top','sub','label','ok','reason','pick'}."""
    try:
        hits = view.getObjectsInfo(tuple(int(c) for c in xy)) or []
    except Exception:
        hits = []
    raw = []
    for h in hits:
        parent = h.get("ParentObject")
        top = parent.Name if parent is not None and hasattr(parent, "Name") else h.get("Object")
        sub = h.get("SubName") if parent is not None else h.get("Component", "")
        if top:
            raw.append({"doc": h.get("Document") or App.ActiveDocument.Name, "top": top, "sub": sub or ""})
    rows = []
    m = manager()
    for r in core.dedupe(raw):
        try:
            ok, reason, pick = m.verdict(r["doc"], r["top"], r["sub"], layer)
        except Exception:
            continue
        rows.append(dict(r, label=pick.label, ok=ok, reason=reason, pick=pick))
    return rows


def select_row(row, clear=None):
    """Select a row the way a click would: replace the selection unless a dialog is collecting."""
    if clear is None:
        try:
            clear = not Gui.Control.activeDialog()
        except Exception:
            clear = True
    if clear:
        Gui.Selection.clearSelection()
    Gui.Selection.addSelection(row["doc"], row["top"], row["sub"])
    return Gui.Selection.isSelected(App.getDocument(row["doc"]).getObject(row["top"]), row["sub"])


# --------------------------------------------------------------- widgets
class TypeFilter(QtWidgets.QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NXTypeFilter")
        self.setToolTip("Type Filter: limit what can be selected")
        for label, key in TYPES:
            self.addItem(label, key)
        self.setMinimumContentsLength(16)
        self.currentIndexChanged.connect(self._changed)

    def _changed(self, index):
        self.apply(self.itemData(index))

    def apply(self, kind):
        when = manager().set_global(kind=kind)
        _say_when("Type Filter", when)

    def reset(self):
        self.setCurrentIndex(0)


class ScopeFilter(QtWidgets.QComboBox):
    """NX's Selection Scope; the work part is FreeCAD's active part (double-click a part or a component
    in the Part Navigator)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NXSelectionScope")
        self.setToolTip("Selection Scope: the whole assembly, or only the work part (FreeCAD's active part; "
                        "double-click a part or component in the Part Navigator to make it the work part)")
        for label, key in core.SCOPES:
            self.addItem(label, key)
        self.setMinimumContentsLength(14)
        self.currentIndexChanged.connect(lambda i: _say_when("Selection Scope",
                                                             manager().set_global(scope=self.itemData(i))))

    def select(self, key):
        i = self.findData(key)
        if i >= 0:
            self.setCurrentIndex(i)


class CurveRule(QtWidgets.QComboBox):
    """NX's Curve Rule on the Selection bar: how a section collector (Extrude, Revolve) takes a picked sketch
    curve. Inferred Curves takes the whole sketch; Single, Tangent and Connected Curves take that curve or its
    chain."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NXCurveRule")
        self.setToolTip("Curve Rule: what one pick adds to a section (Extrude, Revolve). Inferred Curves takes the "
                        "whole sketch; Single Curve the picked curve")
        for label, key in core.SECTION_RULES:
            self.addItem(label, key)
        self.setMinimumContentsLength(12)
        self.select(manager().curve_rule)
        self.currentIndexChanged.connect(lambda i: manager().set_curve_rule(self.itemData(i)))
        manager().rule_listeners.append(self.select)

    def select(self, key):
        i = self.findData(key)
        if i >= 0 and i != self.currentIndex():
            self.setCurrentIndex(i)


def _say_when(what, when):
    if when == "now":
        return
    msg = (f"{what}: applies when the command ends (its own selection rules are in force)" if when ==
           "after the command" else f"{what}: applies when FreeCAD's dialog closes")
    try:
        Gui.getMainWindow().statusBar().showMessage(msg, 4000)
    except Exception:
        pass
