# SPDX-License-Identifier: LGPL-2.1-or-later
"""Self-test of NX's Move Object (called from smoke.py), started by its key (Ctrl+T) and driven through the panel:

- the book's L-bar (NX 12 for Engineering Design 4.7.3): two Blocks as separate bodies, the second moved 200 in
  along ZC (typed as 5080 mm) with Move Original; its placement, its bounding box, one undo step, Undo;
- 4.6.9: a cylinder picked in the graphics window and moved 5 in (127 mm) along XC;
- Copy Original, 2 copies: two new bodies, each the solid moved once and twice;
- Angle (with Apply) and Point to Point typed;
- Cancel and Esc leave nothing; negative controls: a wrong vector and a Distance of 0 fail the position check.

Each scenario builds its own document and closes it; one that raises is recorded as a failed check and the others
still run."""

import traceback

import FreeCAD as App
import FreeCADGui as Gui

from . import move_ui
from .qt import Qt, QtWidgets
from .smoke_primitives import button, choose, field, ok, type_into, view_on
from .smoke_selection import click, qt_point, qwait

IN = 25.4
TOL = 1e-6


class Scenario:
    def __init__(self, smoke, name):
        self.smoke, self.name = smoke, name
        self.before = App.ActiveDocument
        self.doc = None

    def __enter__(self):
        self.doc = App.newDocument(self.name)
        self.doc.UndoMode = 1
        return self

    def block(self, origin, size, label="Block"):
        """A Block as NX-Style's Block with Boolean None makes it: an AdditiveBox in its own Body."""
        body = self.doc.addObject("PartDesign::Body", "Body")
        box = body.newObject("PartDesign::AdditiveBox", label)
        box.Length, box.Width, box.Height = size
        box.Placement = App.Placement(App.Vector(*origin), App.Rotation())
        self.doc.recompute()
        return body

    def cylinder(self, radius, height):
        body = self.doc.addObject("PartDesign::Body", "Body")
        cyl = body.newObject("PartDesign::AdditiveCylinder", "Cylinder")
        cyl.Radius, cyl.Height = radius, height
        self.doc.recompute()
        return body

    def __exit__(self, kind, value, tb):
        if kind is not None:
            self.smoke.check(f"move scenario {self.name} ran", False, "".join(
                traceback.format_exception_only(kind, value)).strip())
            self.smoke.info[f"traceback {self.name}"] = "".join(traceback.format_exception(kind, value, tb))
        try:
            p = move_ui.current()
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
def ctrl_t(smoke, doc, motion=None, result=None):
    """Ctrl+T at once after the selection (the replay's case that FreeCAD's own Transform missed). The dialog
    remembers the last Motion and Result, as NX's does, so a scenario chooses the ones it needs."""
    view_on(doc)
    smoke.press("Ctrl+T")
    qwait(400)
    p = move_ui.current()
    if p is not None:
        if motion:
            choose(p, "nxMotion", motion)
        if result:
            choose(p, "nxResult", result)
    return p


def last():
    return dict(move_ui.HISTORY[-1]) if move_ui.HISTORY else {}


def box_of(obj):
    b = obj.Shape.BoundBox
    return (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)


def shifted(obj, box0, d, tol=TOL):
    """The position check: obj's bounding box is box0 moved by d."""
    want = tuple(c + d[i % 3] for i, c in enumerate(box0))
    return all(abs(a - b) <= tol for a, b in zip(box_of(obj), want))


def base(obj):
    return tuple(obj.Placement.Base)


def bodies(doc):
    return [o for o in doc.Objects if o.isDerivedFrom("PartDesign::Body")]


def objects(p):
    return [n for n, _ in p.objects] if p is not None else None


# ------------------------------------------------------------ scenarios
def book(smoke):
    """L-bar (4.7.3): the second block's body selected, Ctrl+T, Distance 200 in along ZC, Move Original, OK."""
    with Scenario(smoke, "SmokeMove") as sc:
        doc = sc.doc
        sc.block((0, 0, 0), (60 * IN, 15 * IN, 20 * IN))
        top = sc.block((0, 0, 0), (60 * IN, 15 * IN, 20 * IN))
        first = bodies(doc)[0]
        box0, first0 = box_of(top), box_of(first)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, top.Name)        # what a click in the Part Navigator selects
        p = ctrl_t(smoke, doc)
        smoke.check("Move Object: Ctrl+T right after selecting a body opens the NX dialog (Objects, Motion, Specify "
                    "Vector, Distance, Result) with the body as its object",
                    p is not None and objects(p) == [top.Name] and p.motion.currentText() == "Distance"
                    and field(p, "distance") is not None and p.result.currentText() == "Move Original",
                    {"objects": objects(p), "widgets": [w.objectName() for w in p.form.findChildren(QtWidgets.QWidget)
                                                        if w.objectName()][:40] if p is not None else "no panel"})
        if p is None:
            return
        choose(p, "nxVector", "ZC")
        type_into("distance", "5080", p)
        previewed = shifted(top, box0, (0, 0, 5080))
        pressed = ok()
        rec = last()
        lifted = (abs(top.Placement.Base.z - 5080) < TOL and abs(top.Placement.Base.x) < TOL
                  and abs(top.Placement.Base.y) < TOL and shifted(top, box0, (0, 0, 5080)))
        detail = {"placement": base(top), "box": box_of(top), "box before": box0, "history": rec,
                  "undo": doc.UndoNames[:3], "previewed": previewed}
        smoke.info["move book"] = detail
        smoke.shot("move_book.png")
        smoke.check("Move Object (book 4.7.3): Distance 200 in (5080 mm) along ZC, Move Original, OK: the body's "
                    "Placement is (0, 0, 5080) and its box is the old one lifted 5080; the other block unmoved; one "
                    "undo step 'Move Object'",
                    pressed and previewed and lifted and box_of(first) == first0 and rec.get("outcome") == "committed"
                    and rec.get("undo_steps") == 1 and doc.UndoNames[:1] == ["Move Object"]
                    and len(bodies(doc)) == 2, detail)
        doc.undo()
        doc.recompute()
        smoke.check("Undo puts the body back where it was (Placement and box)",
                    base(top) == (0, 0, 0) and shifted(top, box0, (0, 0, 0)), {"placement": base(top)})
        # negative control: the position check refuses the block where it was (as a Distance of 0 leaves it)
        smoke.check("Negative control: the position check fails on the unmoved block",
                    not shifted(top, box0, (0, 0, 5080)), box_of(top))

        # negative control through the dialog: a wrong vector (YC) moves it, but not where the book says
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, top.Name)
        p = ctrl_t(smoke, doc)
        if p is not None:
            remembered = abs(move_ui.mm(field(p, "distance")) - 5080) < TOL and p.vector.currentText() == "ZC"
            choose(p, "nxVector", "YC")
            ok()
            wrong = not shifted(top, box0, (0, 0, 5080)) and shifted(top, box0, (0, 5080, 0))
            smoke.check("Negative control: moved along YC instead of ZC, the position check for ZC fails (and the "
                        "YC one passes); the dialog remembered 5080 and ZC from the last time",
                        remembered and wrong, {"box": box_of(top), "remembered": remembered})
            doc.undo()
            doc.recompute()


def cylinder(smoke):
    """4.6.9: Ctrl+T with nothing selected, a click on the cylinder, 5 in along XC, OK."""
    with Scenario(smoke, "SmokeMoveCyl") as sc:
        doc = sc.doc
        body = sc.cylinder(1 * IN, 2 * IN)
        box0 = box_of(body)
        Gui.Selection.clearSelection()
        p = ctrl_t(smoke, doc, "Distance", "Move Original")
        if p is None:
            smoke.check("Move Object: Ctrl+T with nothing selected opens the dialog", False, "no panel")
            return
        waiting = p.active == "objects" and p.error is not None and not ok_enabled()
        av = view_on(doc)
        nav = smoke.nav()
        click(smoke, nav, qt_point(nav, av.getPointOnViewport(App.Vector(0, 0, 2 * IN))))     # the top face
        qwait(400)
        picked = objects(p)
        choose(p, "nxVector", "XC")
        type_into("distance", "127", p)
        pressed = ok()
        rec = last()
        moved = shifted(body, box0, (127, 0, 0)) and abs(body.Placement.Base.x - 127) < TOL
        smoke.check("Move Object (4.6.9): with nothing selected the dialog asks for objects (OK unavailable); a "
                    "click on the cylinder's face takes its body; 5 in (127 mm) along XC moves it; one undo step",
                    waiting and picked == [body.Name] and pressed and moved and rec.get("undo_steps") == 1,
                    {"waiting": waiting, "picked": picked, "box": box_of(body), "history": rec})


def ok_enabled():
    from .primitive_ui import _dialog_button
    b = _dialog_button(QtWidgets.QDialogButtonBox.Ok)
    return b is not None and b.isEnabled()


def copies(smoke):
    """Copy Original, Number of Copies 2, 50 mm along YC: two new bodies, the original where it was."""
    with Scenario(smoke, "SmokeMoveCopy") as sc:
        doc = sc.doc
        body = sc.block((0, 0, 0), (40, 10, 20))
        box0, vol0 = box_of(body), body.Shape.Volume
        names0 = {o.Name for o in doc.Objects}
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, body.Name)
        p = ctrl_t(smoke, doc, "Distance", "Copy Original")
        if p is None:
            smoke.check("Move Object: Ctrl+T opens the dialog", False, "no panel")
            return
        choose(p, "nxVector", "YC")
        type_into("distance", "50", p)
        type_into(field(p, "copies"), "2", p)
        pressed = ok()
        rec = last()
        made = [doc.getObject(n) for n in rec.get("copies", [])]
        new = [b for b in bodies(doc) if b is not body]
        good = (pressed and len(made) == 2 and len(new) == 2 and all(m is not None for m in made)
                and all(m.isDerivedFrom("PartDesign::Body") and len(m.Shape.Solids) == 1 and m.Shape.isValid()
                        and abs(m.Shape.Volume - vol0) < 1e-6 for m in made)
                and shifted(made[0], box0, (0, 50, 0)) and shifted(made[1], box0, (0, 100, 0))
                and shifted(body, box0, (0, 0, 0)) and rec.get("undo_steps") == 1
                and all(m.BaseFeature is not None and not m.BaseFeature.ViewObject.Visibility for m in made))
        detail = {"copies": [(m.Name, box_of(m), m.Shape.Volume) for m in made if m is not None],
                  "history": rec, "original": box_of(body)}
        smoke.info["move copies"] = detail
        view_on(doc)
        smoke.shot("move_copies.png")
        smoke.check("Move Object Copy Original, Number of Copies 2, 50 mm along YC: two new bodies, each one solid of "
                    "the original's volume, at +50 and +100 YC; the original where it was; the copied solid hidden; "
                    "one undo step", good, detail)
        doc.undo()
        doc.recompute()
        smoke.check("Undo removes both copies (no object left over)", {o.Name for o in doc.Objects} == names0,
                    sorted({o.Name for o in doc.Objects} - names0))


def angle_and_points(smoke):
    """Angle 90 about ZC through a typed point (Apply), then Point to Point typed (OK)."""
    with Scenario(smoke, "SmokeMoveAngle") as sc:
        doc = sc.doc
        body = sc.block((10, 0, 0), (20, 10, 5))
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, body.Name)
        p = ctrl_t(smoke, doc, "Angle", "Move Original")
        if p is None:
            smoke.check("Move Object: Ctrl+T opens the dialog", False, "no panel")
            return
        choose(p, "nxVector", "ZC")
        for axis, v in (("XC", "10"), ("YC", "0"), ("ZC", "0")):
            type_into(f"point{axis}", v, p)
        type_into("angle", "90", p)
        applied = button(QtWidgets.QDialogButtonBox.Apply)
        # Apply committed the body turned 90 deg about the vertical through (10, 0, 0): Placement (10, -10, 0) with
        # the quarter turn; the dialog then previews the next turn, as OK would make it (x -10..10, y -10..0)
        rec = last()
        base_q = rec.get("placements", {}).get(body.Name)
        s = 0.5 ** 0.5
        turned = base_q is not None and all(abs(a - w) < TOL for a, w in zip(base_q[0] + base_q[1],
                                                                                (10, -10, 0, 0, 0, s, s)))
        b = box_of(body)
        preview = all(abs(a - w) < TOL for a, w in zip(b, (-10, -10, 0, 10, 0, 5)))
        still = move_ui.current() is p and p.open
        steps_after_apply = rec.get("undo_steps")
        choose(p, "nxMotion", "Point to Point")
        for key, pt in (("from", (0, 0, 0)), ("to", (100, 0, 50))):
            for axis, c in zip(("XC", "YC", "ZC"), pt):
                type_into(f"{key}{axis}", str(c), p)
        pressed = ok()
        b2 = box_of(body)
        moved = all(abs(a - w) < TOL for a, w in zip(b2, (100, 0, 50, 110, 20, 55)))
        smoke.check("Move Object Angle 90 about ZC through (10, 0, 0), Apply: the block's body turns about that axis "
                    "(one step) and the dialog stays open previewing the next turn; then Point to Point (0, 0, 0) to "
                    "(100, 0, 50), OK, moves the turned block on (a second step)",
                    applied and turned and preview and still and steps_after_apply == 1 and pressed and moved
                    and doc.UndoNames[:2] == ["Move Object", "Move Object"],
                    {"applied placement": base_q, "preview box": b, "after point to point": b2,
                     "undo": doc.UndoNames[:3], "history": move_ui.HISTORY[-2:]})


def cancel(smoke):
    """The preview moves the body; Cancel, and Esc, leave it where it was with no undo step."""
    with Scenario(smoke, "SmokeMoveCancel") as sc:
        doc = sc.doc
        body = sc.block((0, 0, 0), (30, 30, 30))
        box0 = box_of(body)
        results = []
        for how in ("Cancel", "Esc"):
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(doc.Name, body.Name)
            steps0 = list(doc.UndoNames)
            p = ctrl_t(smoke, doc, "Distance", "Copy Original" if how == "Esc" else "Move Original")
            if p is None:
                results.append((how, "no panel"))
                continue
            choose(p, "nxVector", "ZC")
            type_into("distance", "100", p)
            previewed = (shifted(body, box0, (0, 0, 100)) if how == "Cancel"   # Number of Copies is remembered
                         else len(bodies(doc)) == 1 + p.count.value())
            if how == "Cancel":
                button(QtWidgets.QDialogButtonBox.Cancel)
            else:
                from .tutorial import qtest
                qtest().keyClick(field(p, "distance").lineEdit(), Qt.Key_Escape)
                qwait(400)
            rec = last()
            results.append((how, previewed, move_ui.current() is None, shifted(body, box0, (0, 0, 0)),
                            len(bodies(doc)), list(doc.UndoNames) == steps0, rec.get("outcome"),
                            rec.get("undo_steps")))
        smoke.check("Move Object: the preview moves the body (or makes the copy); Cancel and Esc close the dialog "
                    "and leave the body where it was, no copy, no undo step",
                    all(len(r) == 8 and r[1] and r[2] and r[3] and r[4] == 1 and r[5] and r[6] == "cancelled"
                        and r[7] == 0 for r in results), results)

        # negative control: a Distance of 0 warns that nothing moves, and the position check fails
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, body.Name)
        p = ctrl_t(smoke, doc, "Distance", "Move Original")
        if p is not None:
            type_into("distance", "0", p)
            warned = any("do not move" in w for w in p.warnings)
            ok()
            smoke.check("Negative control: Distance 0 warns 'the objects do not move', and the position check for "
                        "100 along ZC fails", warned and not shifted(body, box0, (0, 0, 100)),
                        {"warnings": last().get("warnings"), "box": box_of(body)})


def bindings(smoke):
    """Ctrl+T and the MB3 radial's Move Object run NXStyle_MoveObject; FreeCAD's name with labels: freecad."""
    from . import config, navigation, shortcuts
    inst = shortcuts.instance()
    act = inst.targets.get(shortcuts.norm("Ctrl+T")) if inst is not None else None
    cmd_acts = Gui.Command.get("NXStyle_MoveObject").getAction() or []
    known = navigation.known_commands()
    radial = {label: navigation.resolve(cmd, known) for label, cmd in navigation.OBJECT_RADIAL if cmd}
    cfg = config.get()
    before = cfg.get("labels")
    try:
        cfg["labels"] = "freecad"
        name = move_ui.COMMANDS["NXStyle_MoveObject"].GetResources()["MenuText"]
    finally:
        cfg["labels"] = before
    smoke.check("Ctrl+T is NXStyle_MoveObject's key (FreeCAD's Transform keeps no key of its own); the radial "
                "menu's Move Object runs it; labels: freecad calls it Transform",
                act is not None and cmd_acts and act is cmd_acts[0] and name == "Transform"
                and radial.get("Move Object") == "NXStyle_MoveObject",
                {"Ctrl+T action": act.objectName() or act.text() if act is not None else None,
                 "radial": radial, "freecad name": name})


def run(smoke):
    for scenario in (bindings, book, cylinder, copies, angle_and_points, cancel):
        try:
            scenario(smoke)
        except Exception:
            smoke.check(f"move scenario {scenario.__name__} ran", False, traceback.format_exc().splitlines()[-1])
            smoke.info[f"traceback move {scenario.__name__}"] = traceback.format_exc()
        qwait(200)
    smoke.info["move history"] = move_ui.HISTORY[-12:]
    smoke.info["move trace"] = move_ui.TRACE[-30:]
