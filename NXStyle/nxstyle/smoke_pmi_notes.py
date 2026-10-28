# SPDX-License-Identifier: LGPL-2.1-or-later
"""Self-test of the PMI tab's Linear, Radial, Note and Centerline (called from smoke.py), and Inherit PMI bringing
them onto a drawing, on a shaft Ø20 x 40 along X with a Ø6 bore 15 deep into its right end:

- Linear on the two end faces is 40 and Radial on the shaft is Ø20, or R10 with the Radius method; the values are
  the Part API's (the shape's box and its cylinder);
- Centerline on the bore runs along its axis past both its ends; Note keeps the lines typed;
- negative controls: a Note with no text is refused, a Centerline on a plane is not valid;
- Inherit PMI on a front view gives the 40 and the 20 as dimensions, the note as a note and the centerline as a
  dash-dot line whose ends are the bore's axis seen in that view, worked out here from the view's own placement;
  on a view along the axis the centerline is left out, with the reason."""

import traceback

import FreeCAD as App
import FreeCADGui as Gui

from . import pmi_ui
from .qt import QtWidgets
from .smoke_primitives import ok, ribbon_click
from .smoke_selection import qwait

R, L, BORE, DEPTH = 10.0, 40.0, 3.0, 15.0


def build(doc):
    import Part
    x = App.Vector(1, 0, 0)
    shaft = Part.makeCylinder(R, L, App.Vector(0, 0, 0), x).cut(
        Part.makeCylinder(BORE, DEPTH, App.Vector(L - DEPTH, 0, 0), x))
    part = doc.addObject("Part::Feature", "Shaft")
    part.Shape = shaft
    doc.recompute()
    return part


def face(part, test):
    return next(f"Face{i}" for i, f in enumerate(part.Shape.Faces, 1) if test(f))


def faces(part):
    def plane_at(x):
        return lambda f: f.Surface.__class__.__name__ == "Plane" and abs(f.CenterOfMass.x - x) < 1e-6 and f.Area > 200

    def cyl(r):
        return lambda f: f.Surface.__class__.__name__ == "Cylinder" and abs(f.Surface.Radius - r) < 1e-6
    return {"left": face(part, plane_at(0)), "right": face(part, plane_at(L)), "shaft": face(part, cyl(R)),
            "bore": face(part, cyl(BORE)), "bottom": face(part, lambda f: f.Surface.__class__.__name__ == "Plane"
                                                         and abs(f.CenterOfMass.x - (L - DEPTH)) < 1e-6)}


def widget(cls, name):
    dock = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Tasks")
    return next((w for w in dock.findChildren(cls) if w.objectName() == name), None) if dock else None


def pmi_command(smoke, part, subs, label, fill=None):
    """Select the faces, click the PMI tab's button, fill the dialog, OK; the new PMI (or None) and whether OK closed
    the dialog (a refused OK leaves it open)."""
    doc = part.Document
    before = {o.Name for o in pmi_ui.all_pmi(doc)}
    Gui.Selection.clearSelection()
    for s in subs:
        Gui.Selection.addSelection(doc.Name, part.Name, s)
    qwait(150)
    ribbon_click(smoke, label)
    qwait(200)
    if fill is not None:
        fill()
    ok()
    pressed = not Gui.Control.activeDialog()          # OK took it: the dialog closed
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    doc.recompute()
    new = [o for o in pmi_ui.all_pmi(doc) if o.Name not in before]
    return (new[-1] if new else None), pressed


def type_note(text):
    from .tutorial import qtest
    from .smoke import decode
    ed = widget(QtWidgets.QPlainTextEdit, "noteText")
    if ed is None:
        return False
    ed.setFocus()
    for i, line in enumerate(text.split("\n")):
        if i:
            qtest().keyClick(ed, *decode("Return"))
        qtest().keyClicks(ed, line)
    return True


def choose_method(text):
    c = widget(QtWidgets.QComboBox, "dimensionType")
    i = c.findText(text) if c is not None else -1
    if i >= 0:
        c.setCurrentIndex(i)
        c.activated.emit(i)
    return [c.itemText(k) for k in range(c.count())] if c is not None else None


def run(smoke):
    before = App.ActiveDocument
    doc = App.newDocument("SmokePMINotes")
    try:
        smoke.shell.switch_application("modeling")
        part = build(doc)
        f = faces(part)
        Gui.getDocument(doc.Name).ActiveView.viewIsometric()

        # 1. Linear and Radial, against the Part API
        lin, _ = pmi_command(smoke, part, [f["left"], f["right"]], "Linear")
        dia, _ = pmi_command(smoke, part, [f["shaft"]], "Radial")
        methods = {}
        rad, _ = pmi_command(smoke, part, [f["shaft"]], "Radial",
                             lambda: methods.setdefault("radial", choose_method("Radius")))
        bb = part.Shape.BoundBox
        cyl = part.Shape.getElement(f["shaft"]).Surface.Radius
        got = {k: (o.DimensionType, round(o.Nominal, 6)) if o is not None else None
               for k, o in (("linear", lin), ("radial", dia), ("radius", rad))}
        smoke.check("PMI Linear on the two end faces and Radial on the shaft (Diameter, or the Radius method) measure "
                    "what the Part API gives", got == {"linear": ("Distance", bb.XLength), "radial": ("Diameter",
                                                                                                       2 * cyl),
                                                      "radius": ("Radius", cyl)}
                    and methods.get("radial") == ["Diameter", "Radius"], {"PMI": got, "Radial methods": methods,
                                                                          "Part API": (bb.XLength, cyl)})

        # 2. Centerline on the bore; Note with two lines
        axis, _ = pmi_command(smoke, part, [f["bore"]], "Centerline")
        lo, hi = L - DEPTH, L
        over = DEPTH * pmi_ui.CENTERLINE_OVERRUN
        ends = (tuple(round(c, 6) for c in axis.Anchor), tuple(round(c, 6) for c in axis.Anchor2)) if axis else None
        smoke.check("PMI Centerline on the bore: along its axis, past both its ends", axis is not None and axis.Valid
                    and ends == ((lo - over, 0, 0), (hi + over, 0, 0)), {"ends": ends,
                                                                         "expected": ((lo - over, 0, 0), (hi + over, 0, 0))})
        note, _ = pmi_command(smoke, part, [f["shaft"]], "Note", lambda: type_note("Hardened\nHRC 58-62"))
        smoke.check("PMI Note keeps the lines typed, with a leader to the face", note is not None and list(note.Text)
                    == ["Hardened", "HRC 58-62"] and note.Callout == "Hardened\nHRC 58-62" and
                    note.LabelOffset.Length > 0, {"text": list(note.Text) if note else None})

        # 3. negative controls
        empty, pressed = pmi_command(smoke, part, [f["shaft"]], "Note")
        flat, _ = pmi_command(smoke, part, [f["left"]], "Centerline")
        smoke.check("Negative controls: a Note with no text is refused; a Centerline on a plane is not valid",
                    empty is None and not pressed and flat is not None and not flat.Valid,
                    {"empty note made": empty is not None, "OK took it": pressed,
                     "centerline on a plane": flat.Callout if flat else None})
        for o in (flat, rad):          # the radius would come out as a second 20 across the side lines
            if o is not None:
                doc.removeObject(o.Name)

        # 4. Inherit PMI on a front view, Aligned to Drawing (the PMI lie in the Front plane: no work view)
        page = doc.addObject("TechDraw::DrawPage", "Sheet")
        tmpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        from .smoke_drafting import template
        tmpl.Template = template("A3_Landscape_blank.svg") or template("ANSIB_Landscape.svg")
        page.Template = tmpl
        front = doc.addObject("TechDraw::DrawViewPart", "Front")
        page.addView(front)
        front.Source = [part]
        front.Direction, front.XDirection = App.Vector(0, -1, 0), App.Vector(1, 0, 0)
        front.ScaleType, front.Scale = "Custom", 2.0
        front.X, front.Y = 150.0, 150.0
        doc.recompute()
        for _ in range(150):
            if front.getVisibleEdges():
                break
            qwait(100)
        pmi_ui.inherit_mode(front)
        front.NX_InheritPMI = "Aligned to Drawing (Entire Part)"
        objs, how = pmi_ui.pmi_for_view(front)
        made, skipped = pmi_ui.inherit(front, objs)
        dims = sorted(round(float(d.getRawValue()), 4) for d in made if d.isDerivedFrom("TechDraw::DrawViewDimension"))
        notes = [list(n.Text) for n in made if getattr(n, "NX_Pmi", "") == note.Name]
        line = next((s for s in made if getattr(s, "NX_Pmi", "") == axis.Name), None)
        s = float(front.Scale)
        # independent: TechDraw centres the view on the part's box; paper x is model X, paper y model Z
        cx, cz = (bb.XMin + bb.XMax) / 2, (bb.ZMin + bb.ZMax) / 2
        want = ((float(front.X) + (lo - over - cx) * s + float(front.X) + (hi + over - cx) * s) / 2,
                float(front.Y) + (0 - cz) * s)
        placed = (round(float(line.X), 4), round(float(line.Y), 4), round(float(line.Rotation), 4)) if line else None
        smoke.check("Inherit PMI on a front view: the 40 and the Ø20 as dimensions, the note, and the centerline on "
                    "the bore's axis as the view shows it", dims == [2 * R, L] and notes == [["Hardened", "HRC 58-62"]]
                    and placed is not None and abs(placed[0] - want[0]) < 1e-3 and abs(placed[1] - want[1]) < 1e-3
                    and abs(placed[2]) < 1e-6, {"dimensions": dims, "notes": notes, "centerline at": placed,
                                                "expected": want, "ends": getattr(line, "NX_Ends", None),
                                                "skipped": skipped, "how": how})
        smoke.shot("pmi_notes_drawing.png")

        # 5. a view along the axis: the centerline is left out, with the reason
        page2 = doc.addObject("TechDraw::DrawPage", "Sheet2")
        tmpl2 = doc.addObject("TechDraw::DrawSVGTemplate", "Template2")
        tmpl2.Template = tmpl.Template
        page2.Template = tmpl2
        end = doc.addObject("TechDraw::DrawViewPart", "End")
        page2.addView(end)
        end.Source = [part]
        end.Direction, end.XDirection = App.Vector(1, 0, 0), App.Vector(0, 1, 0)
        doc.recompute()
        for _ in range(150):
            if end.getVisibleEdges():
                break
            qwait(100)
        made2, skipped2 = pmi_ui.inherit(end, [axis])
        smoke.check("Inherit PMI on a view along the axis leaves the centerline out and says why",
                    all(getattr(m, "NX_Pmi", "") != axis.Name for m in made2)
                    and any(lab == axis.Label and "points at the viewer" in why for lab, why in skipped2),
                    {"skipped": skipped2})
        # 6. the bore seen from the shaft's closed end is hidden: a view drawing hidden lines dimensions it, one that
        # does not leaves it out (the negative control)
        bore_dia, _ = pmi_command(smoke, part, [f["bore"]], "Radial")
        back = doc.addObject("TechDraw::DrawViewPart", "Back")
        page2.addView(back)
        back.Source = [part]
        back.Direction, back.XDirection = App.Vector(-1, 0, 0), App.Vector(0, -1, 0)
        back.X, back.Y = 300.0, 150.0
        results = {}
        for hard in (False, True):
            back.HardHidden = hard
            back.recompute()
            doc.recompute()
            for _ in range(150):
                if back.getVisibleEdges() and (not hard or back.getHiddenEdges()):
                    break
                qwait(100)
            for d in [v for v in page2.Views if getattr(v, "NX_Pmi", "") == getattr(bore_dia, "Name", "")]:
                doc.removeObject(d.Name)
            doc.recompute()
            made3, skipped3 = pmi_ui.inherit(back, [bore_dia] if bore_dia else [])
            dim = next((m for m in made3 if m.isDerivedFrom("TechDraw::DrawViewDimension")), None)
            n_vis = len(back.getVisibleEdges())
            sub = dim.References2D[0][1] if dim is not None else None
            sub = sub[0] if isinstance(sub, (tuple, list)) else sub
            edge = int(sub[4:]) if sub else None
            results[hard] = {"value": round(float(dim.getRawValue()), 4) if dim else None, "edge": edge,
                             "visible edges": n_vis, "skipped": skipped3}
        smoke.check("Inherit PMI dimensions a hidden circle on a view that draws hidden lines (dashed), and only there",
                    results[True]["value"] == 2 * BORE and results[True]["edge"] is not None
                    and results[True]["edge"] >= results[True]["visible edges"] and results[False]["value"] is None,
                    results)
    except Exception:
        smoke.check("PMI note and centerline scenario ran", False, traceback.format_exc().splitlines()[-1])
        smoke.info["traceback pmi notes"] = traceback.format_exc()
    finally:
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        Gui.Selection.clearSelection()
        App.closeDocument(doc.Name)
        if before is not None and before.Name in App.listDocuments():
            App.setActiveDocument(before.Name)
