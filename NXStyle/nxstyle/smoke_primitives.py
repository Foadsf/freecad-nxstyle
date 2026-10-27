# SPDX-License-Identifier: LGPL-2.1-or-later
"""Self-test of the primitive solids (called from smoke.py): Block, Cylinder, Cone and Sphere started from their
ribbon buttons, values typed into the dialog's fields, the vector choice, a point snapped at an arc centre by a
click in the graphics window, each Boolean (None, Unite, Subtract, Intersect), one undo step, Cancel and Esc,
Apply, and Edit Parameters. The book's chapter 4 parts give the numbers (inches typed as mm).

Each scenario builds its own document and closes it; one that raises is recorded as a failed check and the
others still run."""

import math
import traceback

import FreeCAD as App
import FreeCADGui as Gui

from . import primitive_ui
from .qt import Qt, QtWidgets
from .smoke_selection import click, qt_point, qwait, settle


class Scenario:
    def __init__(self, smoke, name):
        self.smoke, self.name = smoke, name
        self.before = App.ActiveDocument
        self.doc = None

    def __enter__(self):
        self.doc = App.newDocument(self.name)
        self.doc.UndoMode = 1
        body = self.doc.addObject("PartDesign::Body", "Body")      # what Ctrl+N gives: a part with a Body
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", body)
        return self

    def __exit__(self, kind, value, tb):
        if kind is not None:
            self.smoke.check(f"primitive scenario {self.name} ran", False, "".join(
                traceback.format_exception_only(kind, value)).strip())
            self.smoke.info[f"traceback {self.name}"] = "".join(traceback.format_exception(kind, value, tb))
        try:
            p = primitive_ui.current()
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
def ribbon_click(smoke, label):
    """Click the Home tab's button with this NX label; returns the panel it opened (or None)."""
    from .ribbon import CommandButton
    from .tutorial import qtest
    r = smoke.shell.ribbon
    button = None
    for i in range(r.stack.count()):
        button = next((b for b in r.stack.widget(i).findChildren(CommandButton) if b.nx_label == label), None)
        if button is not None:
            r.select(r.tabs.tabText(i))
            break
    if button is None:
        return None
    QtWidgets.QApplication.processEvents()
    for _ in range(20):                              # FreeCAD refreshes command states on a timer
        if button.isEnabled():
            break
        qwait(100)
    how, _via = r.reach(button)
    if how in ("group", "overflow"):
        act = r.menu_action(button)
        if act is not None:
            act.trigger()
    else:
        qtest().mouseClick(button, Qt.LeftButton)
    qwait(300)
    return primitive_ui.current()


def field(panel, name, cls=QtWidgets.QAbstractSpinBox):
    return next((w for w in panel.form.findChildren(cls) if w.objectName() == name), None)


def type_into(name_or_widget, text, panel=None):
    """Replace a field's text with what a user types, then Tab out."""
    from .smoke import decode
    from .tutorial import qtest
    w = field(panel, name_or_widget) if isinstance(name_or_widget, str) else name_or_widget
    app = QtWidgets.QApplication.instance()
    if app.activeWindow() is None and hasattr(app, "setActiveWindow"):
        app.setActiveWindow(Gui.getMainWindow())     # a hidden desktop has no foreground window
    w.setFocus()
    ed = w.lineEdit()
    ed.selectAll()
    qtest().keyClicks(ed, str(text).replace(".", w.locale().decimalPoint()))
    qtest().keyClick(ed, *decode("Tab"))
    QtWidgets.QApplication.processEvents()
    qwait(200)
    return w.property("rawValue")


def choose(panel, name, text):
    """Choose a list entry the way a user does (the dialog reacts to 'activated')."""
    c = field(panel, name, QtWidgets.QComboBox)
    i = c.findText(text)
    c.setCurrentIndex(i)
    c.activated.emit(i)
    QtWidgets.QApplication.processEvents()
    qwait(250)
    return c.currentText()


def ok(panel=None):
    """Press the dialog's OK button; False when it is unavailable (the panel's error state)."""
    b = primitive_ui._dialog_button(QtWidgets.QDialogButtonBox.Ok)
    if b is None or not b.isEnabled():
        return False
    b.click()
    QtWidgets.QApplication.processEvents()
    qwait(400)
    return True


def button(which):
    b = primitive_ui._dialog_button(which)
    if b is not None and b.isEnabled():
        b.click()
        QtWidgets.QApplication.processEvents()
        qwait(400)
        return True
    return False


def last():
    return dict(primitive_ui.HISTORY[-1]) if primitive_ui.HISTORY else {}


def of_type(doc, type_id):
    return [o for o in doc.Objects if o.TypeId == type_id]


def view_on(doc):
    av = Gui.getDocument(doc.Name).ActiveView
    av.viewIsometric()
    av.fitAll()
    settle(av, 600)
    return av


# ------------------------------------------------------------ scenarios
def block_typed(smoke):
    """Arborpress plate (book 4.2.1): Block, Origin and Edge Lengths, typed lengths into an empty part."""
    with Scenario(smoke, "SmokeBlock") as sc:
        doc = sc.doc
        p = ribbon_click(smoke, "Block")
        smoke.check("Block: the ribbon button opens the NX Block dialog (Type, Origin, Dimensions, Boolean)",
                    p is not None and p.command == "Block" and field(p, "nxType", QtWidgets.QComboBox) is not None
                    and field(p, "originXC") is not None and field(p, "nxBoolean", QtWidgets.QComboBox) is not None,
                    [w.objectName() for w in p.form.findChildren(QtWidgets.QWidget) if w.objectName()][:30]
                    if p is not None else "no panel")
        if p is None:
            return
        got = {n: type_into(n, v, p) for n, v in (("length", "65"), ("width", "0.75 in"), ("height", "20.125"),
                                                   ("originXC", "1.5"))}
        typed_ok = abs(got["height"] - 20.125) < 1e-9 and abs(got["width"] - 19.05) < 1e-9
        pressed = ok()
        rec = last()
        boxes = of_type(doc, "PartDesign::AdditiveBox")
        b = boxes[0] if boxes else None
        bb = b.Shape.BoundBox if b is not None else None
        smoke.check("Block: typed values keep their decimals (20.125), units convert (0.75 in = 19.05 mm), OK builds "
                    "it in the part's empty Body, one undo step named Block",
                    pressed and typed_ok and b is not None and b.getParentGeoFeatureGroup().Name == "Body"
                    and abs(b.Shape.Volume - 65 * 19.05 * 20.125) < 1e-6 and abs(bb.XMin - 1.5) < 1e-9
                    and rec.get("outcome") == "committed" and rec.get("mode") == "none"
                    and doc.UndoNames[:1] == ["Block"] and rec.get("undo_steps") == 1,
                    {"typed": got, "volume": b.Shape.Volume if b else None, "history": rec,
                     "undo": doc.UndoNames[:3]})
        doc.undo()
        doc.recompute()
        smoke.check("Block: one Undo takes the whole Block back", not of_type(doc, "PartDesign::AdditiveBox"),
                    [o.Name for o in doc.Objects])

        # Two Diagonal Points (L-bar's cut-out block, book 4.7.3), then Cancel leaves nothing
        p = ribbon_click(smoke, "Block")
        if p is None:
            return
        remembered = abs(primitive_ui.mm(field(p, "length")) - 65) < 1e-9
        choose(p, "nxType", "Two Diagonal Points")
        hidden = field(p, "length").isHidden() and not p.steps["point2"].isHidden()
        for n, v in (("originXC", "130"), ("originYC", "22.5"), ("originZC", "209.5"), ("point2XC", "190"),
                     ("point2YC", "42.5"), ("point2ZC", "275.5")):
            type_into(n, v, p)
        f = p.feature()
        dims = (f.Length.Value, f.Width.Value, f.Height.Value) if f is not None else None
        button(QtWidgets.QDialogButtonBox.Cancel)
        smoke.check("Block: the dialog keeps the last lengths (65); Two Diagonal Points shows the second point "
                    "and builds 60 x 20 x 66; Cancel leaves nothing and adds no undo step",
                    remembered and hidden and dims == (60.0, 20.0, 66.0) and not of_type(doc, "PartDesign::AdditiveBox")
                    and last().get("outcome") == "cancelled" and last().get("undo_steps") == 0,
                    {"dims": dims, "hidden": hidden, "remembered": remembered, "history": last()})


def shaft(smoke):
    """Impeller shaft (book 4.2.2): Cylinder on ZC at the origin, a Cone on its top face's centre (a click with
    Arc/Ellipse/Sphere Center), Unite; then Edit Parameters on the Cone."""
    with Scenario(smoke, "SmokeShaft") as sc:
        doc = sc.doc
        p = ribbon_click(smoke, "Cylinder")
        if p is None:
            smoke.check("Cylinder: the ribbon button opens its dialog", False, "no panel")
            return
        choose(p, "nxVector", "ZC")
        type_into("diameter", "101.6", p)
        type_into("height", "457.2", p)
        ok()
        cyl = of_type(doc, "PartDesign::AdditiveCylinder")
        smoke.check("Cylinder: vector ZC at the origin, diameter 101.6, height 457.2, Boolean None",
                    len(cyl) == 1 and abs(cyl[0].Shape.Volume - math.pi * 50.8 ** 2 * 457.2) < 1e-4
                    and abs(cyl[0].Shape.BoundBox.ZMax - 457.2) < 1e-9 and last().get("mode") == "none",
                    {"history": last(), "bb": str(cyl[0].Shape.BoundBox) if cyl else None})
        av = view_on(doc)

        p = ribbon_click(smoke, "Cone")
        if p is None:
            smoke.check("Cone: the ribbon button opens its dialog", False, "no panel")
            return
        for n, v in (("baseDiameter", "101.6"), ("topDiameter", "152.4"), ("height", "254")):
            type_into(n, v, p)
        choose(p, "originPointType", "Arc/Ellipse/Sphere Center")
        nav = smoke.nav()
        target = App.Vector(30, 0, 457.2)               # on the cylinder's top face, off its centre
        click(smoke, nav, qt_point(nav, av.getPointOnViewport(target)))
        qwait(400)
        snapped = p.steps["origin"].point()
        smoke.check("Point: Arc/Ellipse/Sphere Center and a click on the cylinder's top face give its centre "
                    "(0, 0, 457.2) in XC, YC, ZC",
                    snapped is not None and all(abs(a - b) < 1e-6 for a, b in zip(snapped, (0, 0, 457.2))),
                    {"point": snapped, "status": p.steps["origin"].status.text(), "warnings": p.warnings})
        choose(p, "nxBoolean", "Unite")
        body = p.steps["body"].chosen()
        pressed = ok()
        cone = of_type(doc, "PartDesign::AdditiveCone")
        frustum = math.pi * 254 / 3 * (50.8 ** 2 + 50.8 * 76.2 + 76.2 ** 2)
        b = doc.getObject("Body")
        smoke.check("Cone: Unite with the only body (chosen by itself); one solid, cylinder + frustum",
                    pressed and body == "Body" and len(cone) == 1 and cone[0].BaseFeature is not None
                    and len(b.Shape.Solids) == 1
                    and abs(b.Shape.Volume - (math.pi * 50.8 ** 2 * 457.2 + frustum)) < 1e-3
                    and last().get("mode") == "unite" and doc.UndoNames[:1] == ["Cone"],
                    {"history": last(), "volume": b.Shape.Volume, "undo": doc.UndoNames[:2]})

        # Edit Parameters: Cancel keeps the value, OK changes it in one 'Edit Cone' step
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, cone[0].Name)
        Gui.runCommand("NXStyle_EditParameters")
        qwait(300)
        p = primitive_ui.current()
        loaded = p is not None and p.edit and abs(primitive_ui.mm(field(p, "topDiameter")) - 152.4) < 1e-9 \
            and all(abs(a - b) < 1e-9 for a, b in zip(p.steps["origin"].point(), (0, 0, 457.2))) \
            and not field(p, "nxBoolean", QtWidgets.QComboBox).isEnabled()
        if p is not None:
            type_into("topDiameter", "120.65", p)
            button(QtWidgets.QDialogButtonBox.Cancel)
        kept = abs(cone[0].Radius2.Value - 76.2) < 1e-9
        Gui.Selection.addSelection(doc.Name, cone[0].Name)
        Gui.runCommand("NXStyle_EditParameters")
        qwait(300)
        p = primitive_ui.current()
        if p is not None:
            type_into("topDiameter", "120.65", p)
            ok()
        smoke.check("Edit Parameters on the Cone: its NX dialog with the values and the Boolean fixed; Cancel keeps "
                    "152.4, OK makes the top 120.65 in one step 'Edit Cone'",
                    loaded and kept and abs(cone[0].Radius2.Value - 60.325) < 1e-9
                    and doc.UndoNames[:1] == ["Edit Cone"] and last().get("undo_steps") == 1,
                    {"loaded": loaded, "kept": kept, "radius2": cone[0].Radius2.Value, "undo": doc.UndoNames[:3]})


def lbar(smoke):
    """L-bar (book 4.7.3): two Blocks as separate bodies, then a Cylinder on YC subtracted from the upper one
    (target picked), Apply for the next; a Unite that misses its target is refused (negative control)."""
    with Scenario(smoke, "SmokeLBar") as sc:
        doc = sc.doc
        for dims, z in (((65, 65, 285), 0), ((182, 65, 85), 200)):
            p = ribbon_click(smoke, "Block")
            if p is None:
                smoke.check("L-bar: Block opens", False, "no panel")
                return
            choose(p, "nxType", "Origin and Edge Lengths")
            for n, v in zip(("length", "width", "height", "originXC", "originYC", "originZC"), dims + (0, 0, z)):
                type_into(n, str(v), p)
            ok()
        bodies = [o for o in doc.Objects if o.isDerivedFrom("PartDesign::Body")]
        upper = bodies[-1] if len(bodies) == 2 else None
        smoke.check("Block with Boolean None in a part that has a solid makes a new body",
                    upper is not None and abs(upper.Shape.Volume - 182 * 65 * 85) < 1e-6,
                    [(b.Name, b.Shape.Volume) for b in bodies])
        if upper is None:
            return
        av = view_on(doc)

        before = upper.Shape.Volume                      # the preview cuts as soon as the target is known
        p = ribbon_click(smoke, "Cylinder")
        choose(p, "nxVector", "YC")
        for n, v in (("originXC", "130"), ("originYC", "-5"), ("originZC", "242"), ("diameter", "35"),
                     ("height", "100")):
            type_into(n, v, p)
        choose(p, "nxBoolean", "Subtract")
        asked = p.active == "body" and p.error is not None          # two bodies: NX asks for the target
        p.addSelection(doc.Name, upper.Name, f"{upper.Tip.Name}.Face1", (0, 0, 0))   # a pick on the upper block
        qwait(300)
        chosen = p.steps["body"].chosen()
        apply_button = primitive_ui._dialog_button(QtWidgets.QDialogButtonBox.Apply)
        apply_state = (apply_button is not None, apply_button.isEnabled() if apply_button else None, p.error)
        steps = len(doc.UndoNames)
        applied = button(QtWidgets.QDialogButtonBox.Apply) and last().get("command") == "Cylinder" \
            and last().get("outcome") == "committed" \
            and doc.UndoNames[:1] == ["Cylinder"] and len(doc.UndoNames) == steps + 1   # committed, not a preview
        cut = before - upper.Shape.Volume
        still = primitive_ui.current() is p and p.open
        type_into("originYC", "22.5", p)
        type_into("diameter", "66", p)
        type_into("height", "20", p)
        second = {"error": p.error, "warnings": list(p.warnings), "feature": p.feature_name, "built": p.built,
                  "values": p.values()}
        second["ok pressed"] = ok()
        second.update({"open after": p.open, "dialog after": bool(Gui.Control.activeDialog()),
                       "trace": list(primitive_ui.TRACE[-8:])})
        smoke.info["primitives second cylinder"] = second
        if p.open:
            p.cancel()
            qwait(300)
        cyls = of_type(doc, "PartDesign::SubtractiveCylinder")
        smoke.check("Cylinder on YC with Subtract: the target body is asked for and taken from a pick; Apply cuts "
                    "the 35 hole through the upper block only and keeps the dialog for a second cylinder",
                    asked and chosen == upper.Name and applied and still and abs(cut - math.pi * 17.5 ** 2 * 65) < 1e-3
                    and len(cyls) == 2 and all(c.getParentGeoFeatureGroup() is upper for c in cyls)
                    and abs(bodies[0].Shape.Volume - 65 * 65 * 285) < 1e-6,
                    {"asked": asked, "chosen": chosen, "cut": cut, "cyls": [c.Name for c in cyls],
                     "apply button (found, enabled, error)": apply_state, "applied": applied, "still open": still,
                     "history": primitive_ui.HISTORY[-2:]})

        # negative control: a Unite whose block misses the target is refused, OK stays unavailable
        p = ribbon_click(smoke, "Block")
        for n, v in zip(("length", "width", "height", "originXC", "originYC", "originZC"),
                        ("10", "10", "10", "500", "500", "500")):
            type_into(n, v, p)
        choose(p, "nxBoolean", "Unite")
        p.steps["body"].choose(upper.Name)
        qwait(400)
        refused = p.error is not None and "separate solid" in p.error and not ok()
        button(QtWidgets.QDialogButtonBox.Cancel)
        smoke.check("Unite whose block does not touch the target: refused with the reason, OK unavailable; Cancel "
                    "leaves the two bodies as they were (negative control)",
                    refused and len(of_type(doc, "PartDesign::AdditiveBox")) == 2
                    and len([o for o in doc.Objects if o.isDerivedFrom("PartDesign::Body")]) == 2,
                    {"error": last().get("error"), "boxes": [o.Name for o in of_type(doc, "PartDesign::AdditiveBox")]})

        # negative control: Existing Point refuses an edge pick and leaves XC, YC, ZC alone
        p = ribbon_click(smoke, "Sphere")
        choose(p, "originPointType", "Existing Point")
        p.addSelection(doc.Name, upper.Name, f"{upper.Tip.Name}.Edge1", (1, 2, 3))
        qwait(300)
        refused = p.steps["origin"].point() == (0.0, 0.0, 0.0) and any("Existing Point" in w for w in p.warnings)
        smoke.check("Point: Existing Point refuses an edge and says why (negative control)", refused,
                    {"point": p.steps["origin"].point(), "warnings": p.warnings})
        button(QtWidgets.QDialogButtonBox.Cancel)
        del av


def nut(smoke):
    """Hexagonal nut (book 4.7.2): a Sphere centred by typed XC, YC, ZC, Intersect with the nut body; Edit
    Parameters on the Intersect; Esc cancels; one Undo takes the Intersect back."""
    with Scenario(smoke, "SmokeNut") as sc:
        doc = sc.doc
        p = ribbon_click(smoke, "Block")
        for n, v in zip(("length", "width", "height", "originXC", "originYC", "originZC"),
                        ("14.5", "14.5", "3.175", "-7.25", "-7.25", "0")):
            type_into(n, v, p)
        ok()
        body = doc.getObject("Body")
        plate = body.Shape.Volume

        p = ribbon_click(smoke, "Sphere")
        for n, v in (("originZC", "3.175"), ("diameter", "14.478")):
            type_into(n, v, p)
        choose(p, "nxBoolean", "Intersect")
        pressed = ok()
        common = [o for o in of_type(doc, "PartDesign::Boolean") if o.Type == "Common"]
        spheres = of_type(doc, "PartDesign::AdditiveSphere")
        tool = spheres[0].getParentGeoFeatureGroup() if spheres else None
        import Part
        want = Part.makeBox(14.5, 14.5, 3.175, App.Vector(-7.25, -7.25, 0)).common(
            Part.makeSphere(7.239, App.Vector(0, 0, 3.175))).Volume
        smoke.check("Sphere with Intersect: a tool body with the sphere and a Boolean (Common) in the target; the "
                    "part is the plate inside the sphere; the tool body hidden; one step 'Sphere'",
                    pressed and len(common) == 1 and tool is not None and common[0].Group == [tool]
                    and body.Tip is common[0] and abs(body.Shape.Volume - want) < 1e-6 and body.Shape.Volume < plate
                    and not tool.Visibility and doc.UndoNames[:1] == ["Sphere"] and last().get("undo_steps") == 1,
                    {"history": last(), "volume": body.Shape.Volume, "want": want, "undo": doc.UndoNames[:2]})
        if not common:
            return
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, common[0].Name)
        Gui.runCommand("NXStyle_EditParameters")
        qwait(300)
        p = primitive_ui.current()
        opened = p is not None and p.command == "Sphere" and p.mode == "intersect" and p.target == body.Name
        smoke.press("Escape")
        qwait(400)
        smoke.check("Edit Parameters on the Intersect opens the Sphere's dialog (Boolean Intersect, target the "
                    "nut); Esc cancels it", opened and primitive_ui.current() is None
                    and not Gui.Control.activeDialog() and last().get("outcome") == "cancelled",
                    {"opened": opened, "history": last()})
        doc.undo()
        doc.recompute()
        smoke.check("One Undo takes the Intersect back: no Boolean, no tool body, the plate whole",
                    not of_type(doc, "PartDesign::Boolean") and not of_type(doc, "PartDesign::AdditiveSphere")
                    and abs(body.Shape.Volume - plate) < 1e-6,
                    [o.Name for o in doc.Objects])


def ribbon(smoke):
    """The four buttons in Home > Feature, with icons and NX names; FreeCAD names with labels: freecad."""
    from . import config
    from .ribbon import command_actions
    r = smoke.shell.ribbon
    where = {c: r.locations.get(f"NXStyle_{c}") for c in ("Block", "Cylinder", "Cone", "Sphere")}
    icons = {c: bool(command_actions(f"NXStyle_{c}")) and not command_actions(f"NXStyle_{c}")[0].icon().isNull()
             for c in where}
    cfg = config.get()
    before = cfg.get("labels")
    try:
        cfg["labels"] = "freecad"
        names = {c: primitive_ui.COMMANDS[f"NXStyle_{c}"].GetResources()["MenuText"] for c in where}
    finally:
        cfg["labels"] = before
    smoke.check("Block, Cylinder, Cone and Sphere are separate buttons in Home > Feature, with icons; labels: "
                "freecad names them Additive Box, Cylinder, Cone, Sphere",
                all(w == "Home › Feature" for w in where.values()) and all(icons.values())
                and names["Block"] == "Additive Box" and names["Sphere"] == "Additive Sphere",
                {"where": where, "icons": icons, "freecad names": names})


def run(smoke):
    for scenario in (ribbon, block_typed, shaft, lbar, nut):
        try:
            scenario(smoke)
        except Exception:
            smoke.check(f"primitive scenario {scenario.__name__} ran", False, traceback.format_exc().splitlines()[-1])
            smoke.info[f"traceback primitives {scenario.__name__}"] = traceback.format_exc()
        qwait(200)
    smoke.info["primitive history"] = primitive_ui.HISTORY[-12:]
