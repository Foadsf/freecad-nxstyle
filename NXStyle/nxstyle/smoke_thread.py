# SPDX-License-Identifier: LGPL-2.1-or-later
"""Self-test of NX's Thread (called from smoke.py): the book's hexagonal screw (4.7.1), a 0.25 in shank threaded
Detailed with the defaults, started from the ribbon and a click on the shank in the graphics window. The volume is
checked against an independent Part API build of the same helix (a long helix swept by Part's pipe shell, then a
Boolean cut) and against the analytic volume of a helical sweep; one solid, the hand, one undo step, Cancel leaving
nothing, Symbolic leaving the volume as it was, Edit Parameters, and two negative controls.

Each scenario builds its own document and closes it; one that raises is recorded as a failed check and the
others still run."""

import math
import traceback

import FreeCAD as App
import FreeCADGui as Gui

from . import thread_core as core, thread_feature as tf, thread_ui
from .qt import Qt, QtCore, QtWidgets
from .smoke_primitives import button, choose, of_type, ok, ribbon_click, type_into, view_on
from .smoke_selection import click, qt_point, qwait

SHANK = (3.175, 38.1)            # radius, length: the book's 0.25 in x 1.5 in shank, typed in mm
REL = 1e-4                       # volume agreement with the reference builds


class Scenario:
    def __init__(self, smoke, name, radius, height):
        self.smoke, self.name, self.radius, self.height = smoke, name, radius, height
        self.before = App.ActiveDocument
        self.doc = None

    def __enter__(self):
        self.doc = App.newDocument(self.name)
        self.doc.UndoMode = 1
        body = self.doc.addObject("PartDesign::Body", "Body")
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", body)
        cyl = body.newObject("PartDesign::AdditiveCylinder", "Shank")
        cyl.Radius, cyl.Height = self.radius, self.height
        self.doc.recompute()
        self.body = body
        self.cylinder_volume = body.Shape.Volume
        return self

    def __exit__(self, kind, value, tb):
        if kind is not None:
            self.smoke.check(f"thread scenario {self.name} ran", False, "".join(
                traceback.format_exception_only(kind, value)).strip())
            self.smoke.info[f"traceback {self.name}"] = "".join(traceback.format_exception(kind, value, tb))
        try:
            p = thread_ui.current()
            if p is not None:
                p.reject()
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
            Gui.Selection.clearSelection()
            App.closeDocument(self.doc.Name)
            if self.before is not None and self.before.Name in App.listDocuments():
                App.setActiveDocument(self.before.Name)
                Gui.getDocument(self.before.Name)
        except Exception:
            self.smoke.info[f"cleanup {self.name}"] = traceback.format_exc()
        return True


# ------------------------------------------------------------ driving the dialog as a user does
def open_thread(smoke):
    ribbon_click(smoke, "Thread")
    return thread_ui.current()


def click_shank(smoke, sc, z):
    """A real click on the shank's side, where it faces the camera, at height z. Returns what FreeCAD had
    preselected under the pointer just before the click (the face the click takes)."""
    av = view_on(sc.doc)
    d = av.getViewDirection()
    toward = App.Vector(-d.x, -d.y, 0)
    toward = toward.normalize() if toward.Length > 1e-9 else App.Vector(1, 0, 0)
    target = toward * (sc.radius * 0.999) + App.Vector(0, 0, z)
    nav = smoke.nav()
    p = qt_point(nav, av.getPointOnViewport(target))
    smoke.send(nav, QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton)
    QtWidgets.QApplication.processEvents()
    qwait(150)
    pre = Gui.Selection.getPreselection()
    pre = (pre.ObjectName, pre.SubElementNames) if pre is not None and pre.ObjectName else None
    click(smoke, nav, p)
    qwait(500)
    return pre


def last():
    return dict(thread_ui.HISTORY[-1]) if thread_ui.HISTORY else {}


# ------------------------------------------------------------ the references
def reference_volume(radius, height, thread, length):
    """The book shank threaded by Part's own tools: a long helix (Part.makeLongHelix) swept with the profile by a
    Frenet pipe shell, cut from a Part cylinder. Starts at the top (z = height) and runs down, as the click near
    the top asks; a rotation about the axis does not change the volume, so the helix's start angle is free."""
    import Part
    pts = core.profile(thread.major, thread.minor, thread.pitch, thread.angle, False, radius)
    hs = core.half_span(pts)
    h = core.helix(length, thread.pitch, pts)
    bottom = height - (length - hs)                 # the profile centre's last position
    helix = Part.makeLongHelix(thread.pitch, h["height"], thread.major / 2, 0, False)
    helix.translate(App.Vector(0, 0, bottom))
    first = helix.Edges[0].valueAt(helix.Edges[0].FirstParameter)
    ang = math.atan2(first.y, first.x)
    prof = [App.Vector(r * math.cos(ang), r * math.sin(ang), bottom + a) for r, a in pts]
    tool = Part.Wire(helix).makePipeShell([Part.makePolygon(prof + [prof[0]])], True, True)
    if tool.Volume < 0:
        tool.reverse()
    result = Part.makeCylinder(radius, height).cut(tool)
    return result.Volume, len(result.Solids), result.isValid()


def threaded(doc, body, cylinder_volume, want):
    """(ok, detail): the Body's solid is the cylinder with a Detailed thread of the reference volume."""
    helices = of_type(doc, "PartDesign::SubtractiveHelix")
    s = body.Shape
    vol = s.Volume
    good = (len(helices) == 1 and helices[0].isValid() and len(s.Solids) == 1 and s.isValid()
            and abs(vol - want) <= REL * want and vol < cylinder_volume - 1.0)
    return good, {"volume": vol, "want": want, "helices": [h.Name for h in helices], "solids": len(s.Solids)}


# ------------------------------------------------------------ scenarios
def detailed(smoke):
    """Hex screw (book 4.7.1): Thread, Detailed, a click on the 0.25 in shank, defaults, OK."""
    with Scenario(smoke, "SmokeThread", *SHANK) as sc:
        doc, body = sc.doc, sc.body
        p = open_thread(smoke)
        smoke.check("Thread: the ribbon button opens the NX Thread dialog (Thread Type, Select Cylinder, Major and "
                    "Minor Diameter, Pitch, Angle, Length, Rotation, Start)",
                    p is not None and all(w is not None for w in
                                          [p.type, p.fields.get("majorDiameter"), p.fields.get("minorDiameter"),
                                           p.fields.get("pitch"), p.fields.get("angle"), p.fields.get("length"),
                                           p.rotation, p.reverse, p.steps.get("cylinder"), p.steps.get("start")]),
                    [w.objectName() for w in p.form.findChildren(QtWidgets.QWidget) if w.objectName()][:30]
                    if p is not None else "no panel")
        if p is None:
            return
        choose(p, "threadType", "Detailed")
        pre = click_shank(smoke, sc, 30.0)
        v = p.values()
        t = core.find("1/4-20 UNC")
        filled = (p.cyl is not None and abs(v["major"] - 6.35) < 1e-9 and abs(v["pitch"] - 1.27) < 1e-9
                  and abs(v["minor"] - t.minor) < 1e-6 and abs(v["angle"] - 60) < 1e-9
                  and abs(v["length"] - 38.1) < 1e-9 and v["rotation"] == "Right Hand"
                  and p.table.currentText() == "1/4-20 UNC")
        smoke.check("Thread: a click on the 0.25 in shank fills 1/4-20 UNC: Major 6.35, Minor 4.975, Pitch 1.27, "
                    "Angle 60, Length 38.1 (the shank), Right Hand",
                    filled, {"values": v, "table": p.table.currentText(), "preselected": pre,
                             "status": p.status.text(), "warnings": p.warnings})
        pressed = ok()
        rec = last()
        want, ref_solids, ref_valid = reference_volume(*SHANK, t, 38.1)
        analytic = sc.cylinder_volume - core.removed_volume(
            core.profile(t.major, t.minor, t.pitch, 60, False, SHANK[0]), 38.1, t.pitch, SHANK[0])
        good, detail = threaded(doc, body, sc.cylinder_volume, want)
        helix = (of_type(doc, "PartDesign::SubtractiveHelix") or [None])[0]
        hand = core.handedness(tf.helix_points(helix), (0, 0, 0), (0, 0, 1)) if helix is not None else None
        detail.update(analytic=analytic, reference=(want, ref_solids, ref_valid), hand=hand, history=rec,
                      undo=doc.UndoNames[:3])
        smoke.info["thread detailed"] = detail
        view_on(doc)
        smoke.shot("thread_detailed.png")
        smoke.check("Thread Detailed: OK builds one solid whose volume matches an independent Part API build of "
                    "the same helix (and the analytic helical sweep) within 1e-4; right hand; one undo step "
                    "named Thread",
                    pressed and good and ref_solids == 1 and ref_valid and abs(analytic - want) <= REL * want
                    and hand == "Right Hand" and rec.get("outcome") == "committed"
                    and doc.UndoNames[:1] == ["Thread"] and rec.get("undo_steps") == 1
                    and helix is not None and helix.NX_Callout == "1/4-20 UNC", detail)

        # Edit Parameters: Left Hand in one 'Edit Thread' step
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, helix.Name)
        Gui.runCommand("NXStyle_EditParameters")
        qwait(300)
        p = thread_ui.current()
        loaded = p is not None and p.edit and not p.type.isEnabled() and p.table.currentText() == "1/4-20 UNC"
        if p is not None:
            choose(p, "rotation", "Left Hand")
            ok()
        hand = core.handedness(tf.helix_points(helix), (0, 0, 0), (0, 0, 1))
        smoke.check("Edit Parameters on the thread reopens its dialog with the values; Left Hand turns the helix "
                    "the other way in one step 'Edit Thread', the volume unchanged",
                    loaded and hand == "Left Hand" and doc.UndoNames[:1] == ["Edit Thread"]
                    and last().get("undo_steps") == 1 and abs(body.Shape.Volume - want) <= REL * want,
                    {"loaded": loaded, "hand": hand, "undo": doc.UndoNames[:3], "volume": body.Shape.Volume})
        doc.undo()
        doc.undo()
        doc.recompute()
        smoke.check("Undo takes the thread back: no helix, no profile sketch, the plain shank",
                    not of_type(doc, "PartDesign::SubtractiveHelix") and not of_type(doc, "Sketcher::SketchObject")
                    and abs(body.Shape.Volume - sc.cylinder_volume) < 1e-6,
                    [o.Name for o in doc.Objects])

        # negative control: the reference check fails on a shank with no thread
        bare, _detail = threaded(doc, body, sc.cylinder_volume, want)
        smoke.check("Negative control: the thread check fails on the bare shank (no thread built)", not bare,
                    _detail)


def cancel_and_refuse(smoke):
    """Cancel leaves nothing; flanks that meet are refused with OK unavailable (negative control)."""
    with Scenario(smoke, "SmokeThreadCancel", *SHANK) as sc:
        doc, body = sc.doc, sc.body
        p = open_thread(smoke)
        if p is None:
            smoke.check("Thread: the ribbon button opens its dialog", False, "no panel")
            return
        choose(p, "threadType", "Detailed")
        click_shank(smoke, sc, 20.0)
        previewed = bool(of_type(doc, "PartDesign::SubtractiveHelix")) and body.Shape.Volume < sc.cylinder_volume
        type_into("minorDiameter", "2", p)
        refused = p.error is not None and "flanks meet" in p.error and not ok()
        button(QtWidgets.QDialogButtonBox.Cancel)
        smoke.check("Thread: a Minor Diameter the flanks cannot reach is refused with the reason, OK unavailable "
                    "(negative control)", refused, {"error": p.error})
        smoke.check("Thread: the preview cuts the thread; Cancel leaves nothing (no helix, no sketch, the shank's "
                    "volume) and adds no undo step",
                    previewed and not of_type(doc, "PartDesign::SubtractiveHelix")
                    and not of_type(doc, "Sketcher::SketchObject")
                    and abs(body.Shape.Volume - sc.cylinder_volume) < 1e-6
                    and last().get("outcome") == "cancelled" and last().get("undo_steps") == 0,
                    {"previewed": previewed, "history": last(), "objects": [o.Name for o in doc.Objects]})


def symbolic(smoke):
    """Symbolic on a metric 6 mm shank: M6 x 1 filled in, the solid unchanged, the thread recorded."""
    with Scenario(smoke, "SmokeThreadSym", 3.0, 20.0) as sc:
        doc, body = sc.doc, sc.body
        p = open_thread(smoke)
        if p is None:
            smoke.check("Thread: the ribbon button opens its dialog", False, "no panel")
            return
        choose(p, "threadType", "Symbolic")
        click_shank(smoke, sc, 10.0)
        callout = p.table.currentText()
        pressed = ok()
        sym = of_type(doc, "PartDesign::FeaturePython")
        f = sym[0] if sym else None
        smoke.check("Thread Symbolic on a 6 mm shank: M6 x 1 from the ISO table; the solid's volume unchanged; a "
                    "SymbolicThread feature at the Body's tip records the callout, pitch and length; no helix; one "
                    "undo step",
                    pressed and callout == "M6 x 1" and f is not None and body.Tip is f
                    and abs(body.Shape.Volume - sc.cylinder_volume) < 1e-9 and len(body.Shape.Solids) == 1
                    and f.NX_Callout == "M6 x 1" and abs(f.NX_Pitch.Value - 1.0) < 1e-12
                    and abs(f.NX_Length.Value - 20.0) < 1e-9 and f.NX_ThreadType == "Symbolic"
                    and not of_type(doc, "PartDesign::SubtractiveHelix")
                    and doc.UndoNames[:1] == ["Thread"] and last().get("undo_steps") == 1,
                    {"callout": callout, "history": last(), "volume": body.Shape.Volume,
                     "tip": body.Tip.Name if body.Tip else None})


def ribbon(smoke):
    """The Thread button in Home > Feature, with an icon; FreeCAD's name with labels: freecad."""
    from . import config
    from .ribbon import command_actions
    where = smoke.shell.ribbon.locations.get("NXStyle_Thread")
    acts = command_actions("NXStyle_Thread")
    cfg = config.get()
    before = cfg.get("labels")
    try:
        cfg["labels"] = "freecad"
        name = thread_ui.COMMANDS["NXStyle_Thread"].GetResources()["MenuText"]
    finally:
        cfg["labels"] = before
    smoke.check("Thread is a button in Home > Feature with an icon; labels: freecad names it after the helix",
                where == "Home › Feature" and bool(acts) and not acts[0].icon().isNull()
                and name == core.FREECAD_NAME, {"where": where, "freecad name": name})


def run(smoke):
    for scenario in (ribbon, detailed, cancel_and_refuse, symbolic):
        try:
            scenario(smoke)
        except Exception:
            smoke.check(f"thread scenario {scenario.__name__} ran", False, traceback.format_exc().splitlines()[-1])
            smoke.info[f"traceback thread {scenario.__name__}"] = traceback.format_exc()
        qwait(200)
    smoke.info["thread history"] = thread_ui.HISTORY[-8:]
    smoke.info["thread trace"] = thread_ui.TRACE[-20:]
