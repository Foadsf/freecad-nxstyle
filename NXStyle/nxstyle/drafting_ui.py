# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX Drafting's Projected View for TechDraw (the geometry is drafting_core.py).

NX makes the other orthographic views one by one off a parent view: start Projected View, move the pointer to a
side of the parent and click; each click places a view, Close (or Esc) ends. FreeCAD's own Projected View is a
projection group made from the part, with its own anchor view. Here the parent is the selected drawing view (else
the sheet's newest base view); each side button places one view of the part turned that way for the sheet's
projection angle, at the parent's scale and with its view style, lined up with it.

FreeCAD 1.1's Base View makes a DrawProjGroupItem that belongs to no group (measured); it is a parent like a plain
view. The projected view is a view of its own: it stays where it is placed when the parent is dragged later (in NX it
follows the parent).
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config, drafting_core as core
from .qt import QtWidgets

HISTORY = []                 # one dict per dialog: parent, the views made, how it ended
_current = {"panel": None}
STYLE = ("ScaleType", "Scale", "HardHidden", "SmoothVisible", "SeamVisible", "IsoVisible",
         "SmoothHidden", "SeamHidden", "IsoHidden", "CoarseView")
VIEW_STYLE = ("LineWidth", "HiddenWidth", "IsoWidth", "ExtraWidth", "Color", "HiddenColor")


def is_part_view(o):
    """A view of the part that can be a parent: a plain view or a projection group's view, not a section or detail."""
    return o is not None and o.TypeId in ("TechDraw::DrawViewPart", "TechDraw::DrawProjGroupItem")


def group_of(view):
    """The projection group a DrawProjGroupItem belongs to, else None."""
    if view is None or view.TypeId != "TechDraw::DrawProjGroupItem":
        return None
    return next((g for g in view.InList if g.isDerivedFrom("TechDraw::DrawProjGroup")), None)


def sheet_xy(view):
    """Where a view's centre is on the sheet: a group's view is placed relative to its group."""
    from .gdt_ui import view_origin
    return view_origin(view)[:2]


def scale_of(view):
    from .gdt_ui import view_origin
    return view_origin(view)[2]


def parent_view():
    """The selected drawing view, else the active sheet's newest view that is not a section or detail."""
    for o in Gui.Selection.getSelection():
        if is_part_view(o):
            return o
    from . import gdt_ui
    page = gdt_ui.active_page()
    views = []
    for v in page.Views if page is not None else []:
        if v.isDerivedFrom("TechDraw::DrawProjGroup") and v.Anchor is not None:
            views.append(v.Anchor)
        elif is_part_view(v):
            views.append(v)
    return views[-1] if views else None


def paper_size(view, direction, xdirection):
    """(width, height) of the view's source seen along direction, unscaled: from the exact bounding box of the
    source turned into the view's paper axes (a plain BoundBox is padded around curved faces)."""
    import Part
    x, y, d = core.paper_axes(tuple(direction), tuple(xdirection))
    m = App.Matrix(*x, 0, *y, 0, *d, 0, 0, 0, 0, 1)
    shape = Part.makeCompound([s.Shape for s in view.Source if hasattr(s, "Shape")]).copy()
    shape.transformShape(m)
    try:
        bb = shape.optimalBoundingBox(False, False)
    except Exception:
        bb = shape.BoundBox
    return bb.XLength, bb.YLength


def projection_of(page):
    return str(getattr(page, "ProjectionType", "Third angle") or "Third angle")


def make_projected(parent, side):
    """A view of the parent's part projected onto one side of it, at its scale and style, lined up with it."""
    from . import gdt_ui
    doc = parent.Document
    page = gdt_ui.owning_page(parent)
    direction, xdir = core.projected(tuple(parent.Direction), tuple(parent.XDirection), side, projection_of(page))
    v = doc.addObject("TechDraw::DrawViewPart", "ProjectedView")
    page.addView(v)
    v.Source = list(parent.Source)
    if "XSource" in parent.PropertiesList:
        v.XSource = list(parent.XSource)
    v.Direction, v.XDirection = App.Vector(*direction), App.Vector(*xdir)
    for p in STYLE:
        if p in parent.PropertiesList and p in v.PropertiesList:
            setattr(v, p, getattr(parent, p))
    try:
        for p in VIEW_STYLE:
            if p in parent.ViewObject.PropertiesList and p in v.ViewObject.PropertiesList:
                setattr(v.ViewObject, p, getattr(parent.ViewObject, p))
    except Exception:
        pass
    if v.ScaleType == "Page" and group_of(parent) is not None:     # a group's scale is the group's
        v.ScaleType, v.Scale = "Custom", scale_of(parent)
    s = scale_of(parent)
    x, y = core.place(sheet_xy(parent), paper_size(parent, parent.Direction, parent.XDirection),
                      paper_size(v, direction, xdir), side, s)
    v.X, v.Y = x, y
    for name, kind, value, tip in (("NX_ParentView", "App::PropertyLink", parent, "The view it was projected from"),
                                   ("NX_Side", "App::PropertyString", side, "Which side of its parent it is on")):
        v.addProperty(kind, name, "NX", tip)
        setattr(v, name, value)
    v.Label = f"Projected View ({side})"
    doc.recompute()
    return v


class ProjectedViewPanel:
    """One button per side; each press places a view, as NX's click beside the parent does. OK, MB2, Close or Esc
    ends the command and keeps the views (NX's Close); one undo step removes them all."""

    def __init__(self, parent):
        from . import gdt_ui
        self.parent = parent
        self.doc = parent.Document
        self.made = []
        self.record = {"parent": parent.Name, "made": [], "outcome": "open"}
        HISTORY.append(self.record)
        _current["panel"] = self
        self.doc.openTransaction("Projected View")
        page = gdt_ui.owning_page(parent)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Projected View")
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.addWidget(QtWidgets.QLabel(f"Parent view: {parent.Label}"))
        lay.addWidget(QtWidgets.QLabel(f"Projection: {projection_of(page)} (the sheet's)"))
        grid = QtWidgets.QGridLayout()
        for side, (r, c) in zip(core.SIDES, ((0, 1), (1, 2), (2, 1), (1, 0))):
            b = QtWidgets.QPushButton(side)
            b.setObjectName(f"projected{side}")
            b.setToolTip(f"Place a projected view {side.lower() if side in ('Above', 'Below') else 'to the ' + side.lower()} "
                         "of the parent view")
            b.clicked.connect(lambda _=False, s=side: self.place(s))
            grid.addWidget(b, r, c)
        mid = QtWidgets.QLabel(parent.Label)
        mid.setObjectName("parentView")
        grid.addWidget(mid, 1, 1)
        lay.addLayout(grid)
        self.status = QtWidgets.QLabel("Click a side to place a view there; OK or MB2 when done.")
        self.status.setObjectName("projectedStatus")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

    def place(self, side):
        try:
            v = make_projected(self.parent, side)
        except Exception as e:
            self.status.setText(f"Not placed: {e}")
            return None
        self.made.append(v)
        self.record["made"].append({"name": v.Name, "side": side, "direction": tuple(v.Direction),
                                    "xdirection": tuple(v.XDirection)})
        self.status.setText(f"{len(self.made)} view(s) placed: {', '.join(m.Label for m in self.made)}")
        return v

    def getStandardButtons(self):
        return int(QtWidgets.QDialogButtonBox.Ok)

    def _end(self, how):
        self.doc.commitTransaction()
        self.record["outcome"] = how
        if _current["panel"] is self:
            _current["panel"] = None
        Gui.Control.closeDialog()
        return True

    def accept(self):
        return self._end("ok")

    def reject(self):
        return self._end("closed")           # NX's Close and Esc keep the views placed


class ProjectedView:
    def GetResources(self):
        return {"MenuText": "Projected View",
                "ToolTip": "NX Drafting: orthographic views off a parent view, one per side clicked, lined up with "
                           "it at its scale (select the parent view first, else the newest base view)",
                "Pixmap": config.resource("icons", "projected_view.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog() and parent_view() is not None

    def Activated(self):
        Gui.Control.showDialog(ProjectedViewPanel(parent_view()))


def current():
    """The open Projected View panel, or None."""
    return _current["panel"]


# ------------------------------------------------------------------ Note with a leader
NOTES = []                   # one dict per note made: its text, the arrow's tip, the leader and the note objects
SYMBOLS = (("diameter", "Ø"), ("degree", "°"), ("plusMinus", "±"))


def terminating_point():
    """(view, sheet point) of the selected view edge's middle: where NX's leader ends (Select Terminating Object)."""
    from . import gdt_ui
    for s in Gui.Selection.getSelectionEx():
        o = s.Object
        if is_part_view(o):
            for sub in s.SubElementNames:
                if sub.startswith("Edge"):
                    try:
                        (x, y), _, _ = gdt_ui.edge_on_sheet(o, o.getEdgeByIndex(int(sub[4:])))
                        return o, (x, y), sub
                    except Exception:
                        continue
    return None, None, None


def make_note(page, lines, height=3.5, tip=None, offset=(20.0, 12.0), stub=6.35):
    """A note on the sheet; with tip, a leader from it: up to the knee at tip + offset, a stub, then the text."""
    from . import gdt, gdt_ui
    doc = page.Document
    note = doc.addObject("TechDraw::DrawViewAnnotation", "Note")
    page.addView(note)
    if "ScaleType" in note.PropertiesList:
        note.ScaleType, note.Scale = "Custom", 1.0
    note.Text = list(lines)
    note.TextSize = height
    width = max(gdt.text_width(t, height) for t in lines)
    leader = None
    if tip is not None:
        knee = (tip[0] + offset[0], tip[1] + offset[1])
        s = stub if offset[0] >= 0 else -stub
        body, w, h, centre, end = core.leader(tip, knee, s)
        leader = gdt_ui.add_symbol(page, "Leader", gdt._svg(w, h, body), *centre)
        if "ScaleType" in leader.PropertiesList:
            leader.ScaleType, leader.Scale = "Custom", 1.0
        gdt_ui.tag(leader, kind="leader", tip=f"({tip[0]:.4f}, {tip[1]:.4f})")
        gap = 1.0 + width / 2
        note.X, note.Y = end[0] + (gap if s >= 0 else -gap), end[1]
    else:
        from .gdt_ui import page_centre
        note.X, note.Y = page_centre(page)
    doc.recompute()
    return note, leader


class NotePanel:
    """NX Drafting's Note: the text (Ø and ° from the Symbols buttons), its lettering height, and a leader to the
    selected view edge with a stub of the length given. MB2 or OK places it."""

    def __init__(self):
        from . import gdt_ui
        self.view, self.tip, self.sub = terminating_point()
        self.page = gdt_ui.owning_page(self.view) if self.view is not None else gdt_ui.active_page()
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Note")
        lay = QtWidgets.QFormLayout(self.form)
        where = (f"Leader to {self.view.Label} {self.sub}" if self.view is not None else
                 "No terminating object: select a view edge first for a leader")
        lay.addRow(QtWidgets.QLabel(where))
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setObjectName("noteText")
        lay.addRow("Text", self.text)
        row = QtWidgets.QHBoxLayout()
        for name, ch in SYMBOLS:
            b = QtWidgets.QPushButton(ch)
            b.setObjectName(f"symbol_{name}")
            b.setToolTip(f"Insert {ch}")
            b.clicked.connect(lambda _=False, c=ch: self.text.insertPlainText(c))
            row.addWidget(b)
        lay.addRow("Symbols", row)
        self.height = self._spin("letteringHeight", 3.5, 1.0, 50.0)
        self.stub = self._spin("stubLength", 6.35, 0.0, 100.0)
        lay.addRow("Lettering height", self.height)
        lay.addRow("Stub length", self.stub)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("noteStatus")
        self.status.setWordWrap(True)
        lay.addRow(self.status)

    @staticmethod
    def _spin(name, value, lo, hi):
        s = QtWidgets.QDoubleSpinBox()
        s.setObjectName(name)
        s.setRange(lo, hi)
        s.setDecimals(3)
        s.setSuffix(" mm")
        s.setValue(value)
        return s

    def lines(self):
        out = [t.rstrip() for t in self.text.toPlainText().split("\n")]
        while out and not out[-1]:
            out.pop()
        return out

    def accept(self):
        lines = self.lines()
        if not "".join(lines).strip() or self.page is None:
            self.status.setText("Type the note's text first." if self.page else "There is no drawing sheet.")
            return False
        doc = self.page.Document
        doc.openTransaction("Note")
        note, leader = make_note(self.page, lines, self.height.value(), self.tip, stub=self.stub.value())
        doc.commitTransaction()
        NOTES.append({"text": lines, "tip": self.tip, "view": self.view.Name if self.view else None,
                      "edge": self.sub, "note": note.Name, "leader": leader.Name if leader else None})
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


class Note:
    def GetResources(self):
        return {"MenuText": "Note",
                "ToolTip": "NX Drafting: a note, with a leader to the selected view edge (select it first); Ø and ° "
                           "on the Symbols buttons",
                "Pixmap": config.resource("icons", "pmi_note.svg")}

    def IsActive(self):
        from . import gdt_ui
        return App.ActiveDocument is not None and not Gui.Control.activeDialog() and gdt_ui.active_page() is not None

    def Activated(self):
        Gui.Control.showDialog(NotePanel())


COMMANDS = {"NXStyle_ProjectedView": ProjectedView(), "NXStyle_DraftingNote": Note()}
