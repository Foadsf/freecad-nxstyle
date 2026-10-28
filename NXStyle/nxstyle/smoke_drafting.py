# SPDX-License-Identifier: LGPL-2.1-or-later
"""Self-test of NX Drafting's Projected View and Display Borders (called from smoke.py), on a bar 60 x 25 x 20 with a
Ø8 hole along its length, the arbor press rack's shape in small:

- Projected View is a Home › View button; with the front view selected, Above and Right place two views;
- each view's projected edges, read back from TechDraw, span what the Part API gives for that direction (the top
  60 x 25, the right side 25 x 20 with the hole seen as a circle); same scale, lined up, clear of the parent;
- one undo step removes both; Close (Esc) keeps a view placed, as NX's Close does;
- on a first angle sheet the view placed to the right shows the left side;
- negative control: the same edge check on a plain second Base View placed above (still a front view) fails;
- Display Borders, a Home › Drawing button, turns the sheet's view borders off and on."""

import traceback

import FreeCAD as App
import FreeCADGui as Gui

from . import drafting_core as core, drafting_ui
from .qt import QtWidgets
from .smoke_primitives import ribbon_click
from .smoke_selection import qwait

BAR = (60.0, 25.0, 20.0)
HOLE = 4.0


def template(name):
    """A TechDraw template by file name, wherever this FreeCAD keeps it (Templates/ASME/... in 1.1)."""
    import glob
    import os
    hits = glob.glob(os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates", "**", name), recursive=True)
    return hits[0] if hits else None


def build(doc):
    import Part
    bar = Part.makeBox(*BAR).cut(Part.makeCylinder(HOLE, 20, App.Vector(BAR[0] - 20, BAR[1] / 2, BAR[2] / 2),
                                                   App.Vector(1, 0, 0)))
    part = doc.addObject("Part::Feature", "Bar")
    part.Shape = bar
    page = doc.addObject("TechDraw::DrawPage", "Sheet")
    tmpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
    tmpl.Template = template("ANSIB_Landscape.svg") or template("A3_Landscape_blank.svg")
    page.Template = tmpl
    page.ProjectionType = "Third angle"
    front = doc.addObject("TechDraw::DrawViewPart", "Front")
    page.addView(front)
    front.Source = [part]
    front.Direction, front.XDirection = App.Vector(0, -1, 0), App.Vector(1, 0, 0)
    front.ScaleType = "Custom"
    front.Scale = 2.0
    front.X, front.Y = 120.0, 100.0
    doc.recompute()
    return part, page, front


def edges_ready(view, timeout_ms=15000):
    """Wait for TechDraw's hidden-line worker; the view's visible edges (unscaled, centred)."""
    for _ in range(timeout_ms // 100):
        try:
            if view.getVisibleEdges():
                return view.getVisibleEdges()
        except Exception:
            pass
        qwait(100)
    return []


def spans(view):
    """(width, height, circle radii) of a view's visible edges."""
    es = edges_ready(view)
    if not es:
        return None
    bb = es[0].BoundBox
    for e in es[1:]:
        bb.add(e.BoundBox)
    radii = sorted({round(e.Curve.Radius, 4) for e in es if hasattr(e.Curve, "Radius")})
    return round(bb.XLength, 4), round(bb.YLength, 4), radii


def oracle(part, view):
    """What the Part API says the view must span: the part's corners seen along the view's direction."""
    bb = part.Shape.BoundBox
    corners = [(x, y, z) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax) for z in (bb.ZMin, bb.ZMax)]
    w, h, _, _ = core.extent(corners, tuple(view.Direction), tuple(view.XDirection))
    return round(w, 4), round(h, 4)


def matches(part, view, circle):
    got = spans(view)
    want = oracle(part, view)
    ok = got is not None and abs(got[0] - want[0]) < 1e-3 and abs(got[1] - want[1]) < 1e-3 \
        and ((HOLE in got[2]) == circle)
    return ok, {"edges span": got, "Part API": want, "hole as a circle expected": circle}


def mb2_on_sheet():
    """A middle click in the middle of the active sheet, as NX's MB2 = OK."""
    from .qt import QtCore, Qt, mouse_event
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    sub = mdi.activeSubWindow() if mdi else None
    views = sub.widget().findChildren(QtWidgets.QGraphicsView) if sub else []
    if not views:
        return False
    target = views[0].viewport()
    p = QtCore.QPoint(target.width() // 2, target.height() // 2)
    for kind, buttons in ((QtCore.QEvent.MouseButtonPress, Qt.MiddleButton),
                          (QtCore.QEvent.MouseButtonRelease, Qt.NoButton)):
        QtWidgets.QApplication.sendEvent(target, mouse_event(kind, p, Qt.MiddleButton, buttons, Qt.NoModifier))
    return True


def note_fill(lines, height_field, height):
    """Type the note's lines in the open Note dialog, the first ending in Ø from the Symbols button; set the height."""
    from .smoke import decode
    from .tutorial import qtest
    dock = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Tasks")
    ed = dock.findChild(QtWidgets.QPlainTextEdit, "noteText") if dock else None
    sym = dock.findChild(QtWidgets.QPushButton, "symbol_diameter") if dock else None
    hf = dock.findChild(QtWidgets.QDoubleSpinBox, height_field) if dock else None
    if ed is None or sym is None or hf is None:
        return False
    ed.setFocus()
    qtest().keyClicks(ed, lines[0])
    sym.click()
    for line in lines[1:]:
        qtest().keyClick(ed, *decode("Return"))
        qtest().keyClicks(ed, line)
    hf.setValue(height)
    QtWidgets.QApplication.processEvents()
    return True


def drafting_ui_panel_ok():
    """Press OK in the open dialog; False when it refused (the dialog stays open)."""
    from .navigation import accept_task_dialog
    if not Gui.Control.activeDialog():
        return None
    accept_task_dialog()
    QtWidgets.QApplication.processEvents()
    qwait(300)
    return not bool(Gui.Control.activeDialog())


def projected(smoke, front, sides):
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(front.Document.Name, front.Name)
    qwait(200)
    ribbon_click(smoke, "Projected View")
    p = drafting_ui.current()
    made = []
    if p is not None:
        for s in sides:
            b = next((w for w in p.form.findChildren(QtWidgets.QPushButton) if w.objectName() == f"projected{s}"), None)
            if b is not None:
                b.click()
                QtWidgets.QApplication.processEvents()
                made.append(p.made[-1] if p.made else None)
    return p, made


def run(smoke):
    before = App.ActiveDocument
    doc = App.newDocument("SmokeDrafting")
    doc.UndoMode = 1
    try:
        smoke.shell.switch_application("drafting")
        qwait(500)
        part, page, front = build(doc)
        page.ViewObject.show()
        qwait(500)

        where = smoke.shell.ribbon.locations.get("NXStyle_ProjectedView")
        smoke.check("Projected View is NX-Style's, a Home › View button; FreeCAD's projection group is beside it",
                    where == "Home › View" and smoke.shell.ribbon.locations.get("TechDraw_ProjectionGroup") == where,
                    {"Projected View": where,
                     "Projection Group": smoke.shell.ribbon.locations.get("TechDraw_ProjectionGroup")})

        # 1. Above and Right off the front view, MB2 = OK
        n0 = len(doc.UndoNames)
        p, (top, right) = projected(smoke, front, ("Above", "Right"))
        mb2 = mb2_on_sheet()
        qwait(300)
        mb2_ok = p is not None and drafting_ui.current() is None and drafting_ui.HISTORY[-1]["outcome"] == "ok"
        if drafting_ui.current() is not None:
            drafting_ui.current().accept()
        qwait(300)
        doc.recompute()
        ok_top, d_top = matches(part, top, circle=False) if top else (False, "no view")
        ok_right, d_right = matches(part, right, circle=True) if right else (False, "no view")
        dirs = {v.Label: (tuple(round(c, 6) for c in v.Direction), tuple(round(c, 6) for c in v.XDirection))
                for v in (top, right) if v is not None}
        smoke.check("Projected View: Above shows the top (60 x 25), Right the right side (25 x 20, the hole as a "
                    "circle); edges read back from TechDraw against the Part API", ok_top and ok_right
                    and tuple(top.Direction) == (0, 0, 1) and tuple(right.Direction) == (1, 0, 0) and mb2_ok,
                    {"top": d_top, "right": d_right, "directions": dirs, "MB2 on the sheet sent": mb2,
                     "MB2 = OK": mb2_ok})
        s = float(front.Scale)
        fw, fh = drafting_ui.paper_size(front, front.Direction, front.XDirection)
        aligned = top is not None and right is not None and abs(float(top.X) - float(front.X)) < 1e-6 \
            and abs(float(right.Y) - float(front.Y)) < 1e-6 and float(top.Scale) == s == float(right.Scale) \
            and float(top.Y) - BAR[1] / 2 * s > float(front.Y) + fh / 2 * s \
            and float(right.X) - BAR[1] / 2 * s > float(front.X) + fw / 2 * s
        smoke.check("Projected views keep the parent's scale, line up with it and stand clear of it", aligned,
                    {v.Label: (float(v.X), float(v.Y), float(v.Scale)) for v in (front, top, right) if v is not None})
        undo = doc.UndoNames[:1]
        doc.undo()
        doc.recompute()
        gone = all(doc.getObject(v.Name) is None for v in (top, right) if v is not None)
        smoke.check("Projected View is one undo step; undo removes the views it placed",
                    undo == ["Projected View"] and gone and len(doc.UndoNames) >= n0,
                    {"undo names": undo, "views gone": gone})

        # 2. Close (Esc) keeps what was placed, as NX's Close does
        p, (left,) = projected(smoke, front, ("Left",))
        if p is not None:
            p.reject()
        qwait(200)
        kept = left is not None and doc.getObject(left.Name) is not None
        smoke.check("Projected View: Close (Esc) keeps the view placed", kept and drafting_ui.HISTORY[-1]["outcome"]
                    == "closed" and tuple(left.Direction) == (-1, 0, 0), drafting_ui.HISTORY[-1])

        # 3. first angle: the view placed to the right shows the left side
        page.ProjectionType = "First angle"
        doc.recompute()
        p, (first,) = projected(smoke, front, ("Right",))
        if p is not None:
            p.accept()
        smoke.check("On a first angle sheet the view placed to the right shows the left side",
                    first is not None and tuple(first.Direction) == (-1, 0, 0) and float(first.X) > float(front.X),
                    {"direction": tuple(first.Direction) if first else None})

        # 4. negative control: a second Base View above the front is still a front view; the edge check refuses it
        imposter = doc.addObject("TechDraw::DrawViewPart", "Imposter")
        page.addView(imposter)
        imposter.Source = [part]
        imposter.Direction, imposter.XDirection = App.Vector(0, -1, 0), App.Vector(1, 0, 0)
        imposter.ScaleType, imposter.Scale = "Custom", s
        doc.recompute()
        bad, d_bad = matches(part, imposter, circle=False)
        d_bad["Part API"] = (BAR[0], BAR[1])             # what a top view must span
        got = d_bad["edges span"]
        refused = got is not None and abs(got[1] - BAR[1]) > 1e-3
        smoke.check("Negative control: a front view standing in for the top fails the edge check (spans 60 x 20, "
                    "not 60 x 25)", refused, d_bad)

        # 5. Note with a leader to the front view's top edge: Ø from the Symbols button, lettering height typed
        page.ProjectionType = "Third angle"
        doc.recompute()
        top_edge = next((f"Edge{i}" for i, e in enumerate(edges_ready(front)) if not hasattr(e.Curve, "Radius")
                         and abs(e.BoundBox.YMin - BAR[2] / 2) < 1e-6 and e.BoundBox.YLength < 1e-6
                         and abs(e.BoundBox.XLength - BAR[0]) < 1e-6), None)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, front.Name, top_edge or "")
        qwait(200)
        ribbon_click(smoke, "Note")
        qwait(200)
        typed = note_fill(["Right Hand ", "8 x 1.25"], "letteringHeight", 5.0)
        mb2_on_sheet()
        qwait(300)
        rec = drafting_ui.NOTES[-1] if drafting_ui.NOTES else {}
        note = doc.getObject(rec.get("note", "")) if rec else None
        lead = doc.getObject(rec.get("leader", "") or "") if rec else None
        # independent: the top edge's middle is the bar's (30, 20) in the front view, centred on the bar's box
        want = (float(front.X) + 0.0 * s, float(front.Y) + (BAR[2] - BAR[2] / 2) * s)
        tip = None
        if lead is not None:
            import re
            m = re.search(r'Z" fill="black"', lead.Symbol) and re.findall(r'<path d="M ([\d.]+) ([\d.]+) L', lead.Symbol)
            w = float(re.search(r'width="([\d.]+)mm"', lead.Symbol).group(1)) if 'mm"' in lead.Symbol else None
            h = float(re.search(r'height="([\d.]+)mm"', lead.Symbol).group(1)) if 'mm"' in lead.Symbol else None
            if m and w and h:
                tip = core.arrow_tip((float(lead.X), float(lead.Y)), w, h, (float(m[1][0]), float(m[1][1])))
        smoke.check("Note: the lines typed with Ø from the Symbols button, the lettering height, and a leader whose "
                    "arrow ends on the selected edge's middle", typed and note is not None
                    and list(note.Text) == ["Right Hand Ø", "8 x 1.25"] and abs(float(note.TextSize) - 5.0) < 1e-9
                    and tip is not None and abs(tip[0] - want[0]) < 1e-2 and abs(tip[1] - want[1]) < 1e-2,
                    {"edge": top_edge, "text": list(note.Text) if note else None, "arrow tip": tip, "expected": want,
                     "record": rec})
        n_notes = len(drafting_ui.NOTES)
        ribbon_click(smoke, "Note")
        qwait(200)
        refused = drafting_ui_panel_ok() is False
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        smoke.check("Negative control: a Note with no text is refused", refused and len(drafting_ui.NOTES) == n_notes,
                    {"notes before, after": (n_notes, len(drafting_ui.NOTES))})

        # 6. Display Borders: the sheet's view frames off and on
        vo = page.ViewObject
        was = bool(vo.ShowFrames)
        Gui.Selection.clearSelection()
        ribbon_click(smoke, "Display Borders")
        off = bool(vo.ShowFrames)
        ribbon_click(smoke, "Display Borders")
        on = bool(vo.ShowFrames)
        smoke.check("Display Borders (Home › Drawing) turns the view borders off and on (NX: Drafting Preferences › "
                    "View › Display Borders)", was and not off and on,
                    {"before": was, "after one click": off, "after two": on,
                     "where": smoke.shell.ribbon.locations.get("TechDraw_ToggleFrame")})
    except Exception:
        smoke.check("drafting scenario ran", False, traceback.format_exc().splitlines()[-1])
        smoke.info["traceback drafting"] = traceback.format_exc()
    finally:
        p = drafting_ui.current()
        if p is not None:
            p.reject()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        Gui.Selection.clearSelection()
        App.closeDocument(doc.Name)
        smoke.shell.switch_application("modeling")
        if before is not None and before.Name in App.listDocuments():
            App.setActiveDocument(before.Name)
