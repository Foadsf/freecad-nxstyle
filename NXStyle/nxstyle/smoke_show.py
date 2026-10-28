# SPDX-License-Identifier: LGPL-2.1-or-later
"""Self-test of NX's Show (Ctrl+Shift+K) and its neighbours, called from smoke.py, through the real keys on a part
whose sketch FreeCAD hid after a Pad (tutorial AX's case) and a second, hidden body:

- the hidden sketch selected (by name, then through its Body), Ctrl+Shift+K at once: shown;
- the hidden body clicked in the Part Navigator, Ctrl+Shift+K at once with the focus still there: shown;
- nothing selected, Ctrl+Shift+K: the Show dialog lists the hidden objects; OK shows the picked one, one undo step;
- Ctrl+B at once after a pick hides it; Ctrl+Shift+U shows all; Ctrl+Shift+B inverts.

"At once" is before FreeCAD's command-state timer has seen the selection: each case first waits for that timer to
grey Std_ShowSelection for the empty selection and records that it was still greyed at the key, else the check
does not reach the race (AX's miss: NX-Style's Show action was greyed the same way, and Qt dropped the key)."""

import traceback

import FreeCAD as App
import FreeCADGui as Gui

from . import navigator_status, showhide
from .qt import QtWidgets, Qt
from .smoke_selection import qwait


def stale_wait():
    """Clear the selection and wait until FreeCAD's timer greys Std_ShowSelection for it."""
    Gui.Selection.clearSelection()
    acts = Gui.Command.get("Std_ShowSelection").getAction() or []
    for _ in range(40):
        if acts and not any(a.isEnabled() for a in acts):
            return
        qwait(100)


def freecad_show_enabled():
    """Whether FreeCAD's own Show Selection action is enabled now (False just after a pick: the race is reached)."""
    return [a.isEnabled() for a in Gui.Command.get("Std_ShowSelection").getAction() or []]


def key_on(widget, seq):
    from .smoke import decode
    from .tutorial import qtest
    app = QtWidgets.QApplication.instance()
    if app.activeWindow() is None and hasattr(app, "setActiveWindow"):
        app.setActiveWindow(Gui.getMainWindow())
    widget.setFocus()
    k, m = decode(seq)
    qtest().keyClick(widget, k, m)
    QtWidgets.QApplication.processEvents()


def click_tree(tree, doc, name):
    """Click the Part Navigator item of object `name` in document `doc` (column 2 holds the internal name), as a
    user does; False when there is no such item. The item is used at once: FreeCAD rebuilds its tree items."""
    from .tutorial import qtest
    it = QtWidgets.QTreeWidgetItemIterator(tree)
    in_doc = False                  # the walk is depth first: an item belongs to the last document item before it
    while it.value():
        v = it.value()
        if tree.indexOfTopLevelItem(v) >= 0:
            in_doc = v.text(0) == doc.Label
        elif in_doc and tree.columnCount() > 2 and v.text(2) == name:
            tree.scrollToItem(v)
            rect = tree.visualItemRect(v)
            center = rect.center()
            at = tree.itemAt(center)
            seen = {"hidden": v.isHidden(), "rect": (rect.x(), rect.y(), rect.width(), rect.height()),
                    "at": at.text(2) if at is not None else None}
            qtest().mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, center)
            QtWidgets.QApplication.processEvents()
            return seen
        it += 1
    return None


def build(doc):
    import Part
    body = doc.addObject("PartDesign::Body", "Body")
    sk = body.newObject("Sketcher::SketchObject", "Sketch")
    sk.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
    sk.MapMode = "FlatFace"
    p = [App.Vector(0, 0, 0), App.Vector(30, 0, 0), App.Vector(30, 20, 0), App.Vector(0, 20, 0)]
    for i in range(4):
        sk.addGeometry(Part.LineSegment(p[i], p[(i + 1) % 4]), False)
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sk
    pad.Length = 10
    other = doc.addObject("PartDesign::Body", "Body001")
    other.Label = "Second Body"
    box = other.newObject("PartDesign::AdditiveBox", "Box")
    box.Placement.Base = App.Vector(50, 0, 0)
    doc.recompute()
    sk.ViewObject.Visibility = False        # what FreeCAD's Pad command does to its sketch
    other.ViewObject.Visibility = False
    return body, sk, other


def run(smoke):
    before = App.ActiveDocument
    doc = App.newDocument("SmokeShow")
    doc.UndoMode = 1
    try:
        body, sk, other = build(doc)
        Gui.getDocument(doc.Name).ActiveView.setActiveObject("pdbody", body)
        qwait(300)

        # 1. the hidden sketch selected as tutorial AX does, by name and through its Body; the key in the 3D view
        got = {}
        for how, sub in (("by name", None), ("through its Body", f"{sk.Name}.")):
            sk.ViewObject.Visibility = False
            stale_wait()
            if sub is None:
                Gui.Selection.addSelection(doc.Name, sk.Name)
            else:
                Gui.Selection.addSelection(doc.Name, body.Name, sub)
            stale = freecad_show_enabled()
            smoke.press("Ctrl+Shift+K")
            QtWidgets.QApplication.processEvents()
            got[how] = {"shown": sk.ViewObject.Visibility, "Std_ShowSelection enabled at the key": stale}
        smoke.check("Show (Ctrl+Shift+K) right after selecting a hidden sketch shows it, by name and through its "
                    "Body (tutorial AX)", all(g["shown"] and g["Std_ShowSelection enabled at the key"] == [False]
                                              for g in got.values()),
                    f"{got} (the action must still be greyed at the key, [False], else this does not reach the race)")

        # 2. the hidden body clicked in the Part Navigator; the key with the focus still in the navigator
        smoke.shell.show_part_navigator()
        tree = navigator_status.model_tree()
        stale_wait()
        item = click_tree(tree, doc, other.Name) if tree is not None else None
        picked, stale = None, None
        if item:
            picked = sorted(s.ObjectName for s in Gui.Selection.getSelectionEx("", 0))
            stale = freecad_show_enabled()
            key_on(tree, "Ctrl+Shift+K")
        smoke.check("Show (Ctrl+Shift+K) right after picking a hidden body in the Part Navigator shows it",
                    item and picked == [other.Name] and other.ViewObject.Visibility and stale == [False],
                    f"tree item clicked {item}; selected {picked}; Std_ShowSelection enabled at the key {stale}; "
                    f"shown {other.ViewObject.Visibility}")

        # 3. nothing selected: the dialog lists the hidden objects; OK shows the picked one, one undo step
        sk.ViewObject.Visibility = False
        other.ViewObject.Visibility = False
        stale_wait()
        smoke.press("Ctrl+Shift+K")
        qwait(200)
        dlg = showhide._show
        listed, shown, after_undo = None, None, None
        if dlg is not None and dlg.isVisible():
            listed = [dlg.list.item(i).data(Qt.UserRole) for i in range(dlg.list.count())]
            target = next(dlg.list.item(i) for i in range(dlg.list.count())
                          if dlg.list.item(i).data(Qt.UserRole) == other.Name)
            target.setSelected(True)
            smoke.shot("show_dialog.png", dlg)
            dlg.ok.click()
            QtWidgets.QApplication.processEvents()
            shown = (other.ViewObject.Visibility, sk.ViewObject.Visibility)
            names = doc.UndoNames[:1]
            doc.undo()
            after_undo = (other.ViewObject.Visibility, names)
        smoke.check("Show (Ctrl+Shift+K) with nothing selected lists the hidden objects; OK shows the picked one, "
                    "as one undo step", listed == [other.Name, sk.Name] and shown == (True, False)
                    and after_undo == (False, ["Show"]) and not dlg.isVisible(),
                    f"dialog open {dlg is not None}; listed {listed}; (body, sketch) shown after OK {shown}; "
                    f"after undo (body shown, undo names) {after_undo}")

        # 4. Hide at once after a pick, Show All, Invert: still on their keys
        other.ViewObject.Visibility = True
        stale_wait()
        Gui.Selection.addSelection(doc.Name, other.Name)
        smoke.press("Ctrl+B")
        hidden = not other.ViewObject.Visibility
        stale_wait()
        smoke.press("Ctrl+Shift+U")
        qwait(100)
        all_shown = sk.ViewObject.Visibility and other.ViewObject.Visibility and body.ViewObject.Visibility
        smoke.press("Ctrl+Shift+B")
        inverted = not (other.ViewObject.Visibility or body.ViewObject.Visibility)
        smoke.press("Ctrl+Shift+B")
        back = other.ViewObject.Visibility and body.ViewObject.Visibility
        smoke.check("Hide (Ctrl+B) right after a pick, Show All (Ctrl+Shift+U) and Invert (Ctrl+Shift+B) by their "
                    "keys", hidden and all_shown and inverted and back,
                    f"hidden by Ctrl+B {hidden}; all shown by Ctrl+Shift+U {all_shown}; inverted {inverted}; "
                    f"inverted back {back}")
    except Exception:
        smoke.check("show scenario ran", False, traceback.format_exc().splitlines()[-1])
        smoke.info["traceback show"] = traceback.format_exc()
    finally:
        if showhide._show is not None:
            showhide._show.close()
        Gui.Selection.clearSelection()
        App.closeDocument(doc.Name)
        if before is not None and before.Name in App.listDocuments():
            App.setActiveDocument(before.Name)
