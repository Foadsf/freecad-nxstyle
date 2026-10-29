# SPDX-License-Identifier: LGPL-2.1-or-later
"""Smoke checks for FreeCAD-Nxt next to NXStyle (launch_nx.py --nxt): what of Nxt works on this FreeCAD, and
where it meets NX's keys and layout. The key checks run with Nxt off too (the default), as their control.

Kept apart from smoke.py: these steps drive Nxt's commands on a document of their own.
"""

import os
import sys

import FreeCAD as App
import FreeCADGui as Gui

from . import nxt
from .nxt_navigator import FREECAD_TREE
from .qt import QtCore, QtWidgets

GIZMOS = "User parameter:BaseApp/Preferences/Gui/Gizmos"
DOC = "NxtProbe"


def _wait(ms):
    from .tutorial import qtest
    qtest().qWait(ms)


def _key(widget, key):
    from .tutorial import qtest
    widget.setFocus(QtCore.Qt.OtherFocusReason)
    _wait(50)
    qtest().keyClick(widget, key)
    _wait(150)


def _probe_doc():
    """A Body with a padded 20 x 10 rectangle (sketch on XY), and a lone Part box beside it."""
    import Part
    import Sketcher
    doc = App.newDocument(DOC)
    body = doc.addObject("PartDesign::Body", "Body")
    sk = body.newObject("Sketcher::SketchObject", "Sketch")
    pts = [App.Vector(0, 0, 0), App.Vector(20, 0, 0), App.Vector(20, 10, 0), App.Vector(0, 10, 0)]
    for i in range(4):
        sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sk
    pad.Length = 10
    box = doc.addObject("Part::Box", "Box")
    box.Placement.Base = App.Vector(40, 0, 0)
    doc.recompute()
    Gui.SendMsgToActiveView("ViewFit")
    return doc, pad, box


def _orientation():
    cam = Gui.ActiveDocument.ActiveView.getCameraNode()
    return tuple(round(x, 3) for x in cam.orientation.getValue().getValue())


def _settled(ms=1500):
    """The camera's orientation once a view animation has ended."""
    last, waited = _orientation(), 0
    while waited < ms:
        _wait(100)
        waited += 100
        now = _orientation()
        if now == last:
            return now
        last = now
    return last


def _scene_has(type_name):
    """How many nodes of a Coin type the active view's scene holds (0 when the type is unknown)."""
    from pivy import coin
    t = coin.SoType.fromName(type_name)
    if t.isBad():
        return 0
    search = coin.SoSearchAction()
    search.setType(t)
    search.setInterest(coin.SoSearchAction.ALL)
    search.setSearchingAll(True)
    search.apply(Gui.ActiveDocument.ActiveView.getSceneGraph())
    return search.getPaths().getLength()


def run(smoke):
    """s_nxt: the NX keys Nxt also handles, on and off; with Nxt on, its set-up and each feature tried once."""
    on = nxt.expected()
    info = smoke.info.setdefault("nxt", {"on": on})
    panel = None
    if on:
        panel = _setup(smoke, info)
    else:
        smoke.check("Nxt off as asked (the default)", not nxt.loaded(),
                    sorted(m for m in sys.modules if m.startswith("freecad.nxt"))[:5])
    before = App.ActiveDocument
    doc, pad, box = _probe_doc()
    try:
        _keys(smoke, info, doc, pad, panel)
        _double_click(smoke, info, doc, pad)
        _open_profile(info, doc)
        if on:
            _navigator_panels(smoke, info, doc, pad)
            _features(smoke, info, doc, pad, box)
    finally:
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        _wait(200)
        App.closeDocument(doc.Name)
        if before is not None and before.Name in App.listDocuments():
            App.setActiveDocument(before.Name)


def _setup(smoke, info):
    """Nxt loaded, its update check off, the preferences it set, its panel and its colours."""
    from freecad.nxt import __version__
    from freecad.nxt.app import services, update_check
    from freecad.nxt.core import settings
    from freecad.nxt.ui import theme as nxt_theme
    from . import theme as nx_theme
    info["version"] = __version__
    smoke.check("Nxt loaded with its services", nxt.loaded() and services.instance() is not None, __version__)
    smoke.check("Nxt's addon update check is off in the NX profile",
                settings.get("CheckAddonUpdates") is False and update_check._check is None,
                {"CheckAddonUpdates": settings.get("CheckAddonUpdates"), "running": update_check._check is not None})
    g = App.ParamGet(GIZMOS)
    info["gizmo prefs"] = {"FineSnapModifier": g.GetInt("FineSnapModifier", -1),
                           "DefaultCoarseDragBehavior": g.GetInt("DefaultCoarseDragBehavior", -1),
                           "Nxt ledger": settings.get("ForeignOriginals")}
    info["sketch repair on"] = settings.get("RepairProfiles")
    info["double-click edits"] = settings.get("EditOnDoubleClick")
    # Nxt tabs its panel beside FreeCAD's Model dock (the Part Navigator) on its first run, and raises it
    mw = Gui.getMainWindow()
    panel = mw.findChild(QtWidgets.QDockWidget, "NxtModelPanel")
    model = mw.findChild(QtWidgets.QDockWidget, "Model")
    info["panel"] = None if panel is None else {
        "visible": panel.isVisible(), "floating": panel.isFloating(),
        "tabbed with Model": model is not None and panel in mw.tabifiedDockWidgets(model),
        "front left tab": smoke.shell.current_left_tab()}
    smoke.check("Nxt's model panel opens", panel is not None and panel.isVisible(), info["panel"])
    # step 2: Nxt's panel is the Part Navigator, FreeCAD's tree a tab behind it (nxt_navigator.py)
    nav = nxt.navigator()
    tb = mw.findChild(QtWidgets.QToolBar, nxt.TOOLBAR)
    _wait(300)                              # the shell hides a shown toolbar on the next turn of the event loop
    act = smoke.shell.resource_actions.get("Part Navigator")
    strips = [[b.tabText(i) for i in range(b.count())] for b in mw.findChildren(QtWidgets.QTabBar)]
    left = next((t for t in strips if "Part Navigator" in t), [])
    info["navigator"] = {
        "left tabs": left,
        "Nxt dock": None if panel is None else panel.windowTitle(),
        "FreeCAD's tree": None if model is None else model.windowTitle(),
        "front left tab": smoke.shell.current_left_tab(),
        "Resource Bar button opens": None if act is None else act.parent().objectName(),
        "status strip in it": nav is not None and nav.isAncestorOf(smoke.shell.navigator_status),
        "Nxt toolbar shown": tb is not None and tb.isVisible(),
        "Nxt toolbar": None if tb is None else {"hooked": tb.property("nxHooked"), "parent": type(
            tb.parentWidget()).__name__, "native ui": smoke.shell.native_ui},
        "problems": list(nxt.problems)}
    smoke.check("Nxt's panel is the Part Navigator, in front; FreeCAD's tree is the FreeCAD Tree tab behind it",
                nav is not None and panel.windowTitle() == "Part Navigator" and model.windowTitle() == "FreeCAD Tree"
                and smoke.shell.current_left_tab() == "Part Navigator" and nav.isAncestorOf(nav.tree)
                and left[:1] == ["Part Navigator"] and FREECAD_TREE in left
                and info["navigator"]["status strip in it"], info["navigator"])
    smoke.check("the Resource Bar's Part Navigator button opens Nxt's panel",
                act is not None and act is panel.toggleViewAction(), info["navigator"]["Resource Bar button opens"])
    smoke.check("Nxt's Fillet/Chamfer toolbar stays hidden, like FreeCAD's toolbars", not (tb and tb.isVisible()),
                info["navigator"]["Nxt toolbar shown"])
    th = services.theme()
    if th is not None:
        info["theme"] = {"nxt accent": th.accent.name(), "nx accent": nx_theme.color("accent"),
                         "nxt background": th.background.name(), "nxt text": th.text.name(), "dark": th.dark,
                         "reference widget": type(nxt_theme.find_reference_widget(mw)).__name__}
    return panel


def _keys(smoke, info, doc, pad, panel):
    gl = smoke.nav().widget
    # Home in the 3D view is NX's Trimetric (Std_ViewTrimetric), End its Isometric
    for key, cmd, name in ((QtCore.Qt.Key_Home, "Std_ViewTrimetric", "Home"),
                           (QtCore.Qt.Key_End, "Std_ViewIsometric", "End")):
        Gui.SendMsgToActiveView("ViewFront")
        _settled()
        _key(gl, key)
        got = _settled()
        Gui.SendMsgToActiveView("ViewFront")
        _settled()
        Gui.runCommand(cmd)
        want = _settled()
        smoke.check(f"{name} in the 3D view runs {cmd}", got == want, {"got": got, "want": want})
    # with the focus in Nxt's tree: Nxt claims Home and End in its ShortcutOverride, NXStyle gives them back
    views = [w for w in (panel.findChildren(QtWidgets.QWidget) if panel is not None else [])
             if "QQuickWidget" in w.metaObject().className()]
    if views:
        for key, cmd, name in ((QtCore.Qt.Key_Home, "Std_ViewTrimetric", "Home"),
                               (QtCore.Qt.Key_End, "Std_ViewIsometric", "End")):
            Gui.runCommand(cmd)
            want = _settled()
            Gui.SendMsgToActiveView("ViewFront")
            front = _settled()
            _key(views[0], key)
            got = _settled()
            info[f"{name} in Nxt's tree turns the view"] = got != front
            smoke.check(f"{name} with the focus in Nxt's tree is still NX's {cmd[8:]} view", got == want,
                        {"got": got, "want": want, "front": front})
        # F2 in Nxt's tree: its name editor (a Qt Quick text field) takes the focus. Which FreeCAD command has F2:
        try:
            info["F2 is the shortcut of"] = sorted(
                c for c in Gui.listCommands() if Gui.Command.get(c).getShortcut().replace(" ", "") == "F2")
        except Exception as e:
            info["F2 is the shortcut of"] = repr(e)
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(doc.Name, pad.Name)
            _wait(300)
            _key(views[0], QtCore.Qt.Key_F2)
            _wait(300)
            item = views[0].quickWindow().activeFocusItem()
            editor = item.metaObject().className() if item is not None else None
            from .tutorial import qtest
            qtest().keyClick(views[0], QtCore.Qt.Key_Escape)
            _wait(200)
        except Exception as e:
            editor = repr(e)
        info["F2 in Nxt's tree: focus on"] = editor
        smoke.check("F2 in Nxt's tree opens its name editor", "Text" in str(editor), editor)
        Gui.Selection.clearSelection()
    # Space in the 3D view on a picked face of the Pad: FreeCAD's Std_ToggleVisibility with Nxt on or off. FreeCAD
    # enables the command's action a moment after the pick, so the key waits as a user's would.
    sketch = pad.Profile[0] if isinstance(pad.Profile, tuple) else pad.Profile
    body = doc.getObject("Body")

    def shown():
        return body.ViewObject.Visibility, pad.ViewObject.Visibility, sketch.ViewObject.Visibility

    vis0 = shown()
    after = {}
    for how in ("Space", "Std_ToggleVisibility"):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, "Body", "Pad.Face6")
        _wait(800)
        if how == "Space":
            _key(gl, QtCore.Qt.Key_Space)
        else:
            Gui.runCommand(how)
            _wait(150)
        after[how] = shown()
        body.ViewObject.Visibility, pad.ViewObject.Visibility, sketch.ViewObject.Visibility = vis0
    nxt_space = None
    if nxt.expected():
        from freecad.nxt.app import services
        nxt_space = type(getattr(services.instance(), "_space", None)).__name__
    info["Space on a picked Pad face: (Body, Pad, Sketch) shown"] = {"before": vis0, **after,
                                                                     "Nxt's Space handler": nxt_space}
    smoke.check("Space in the graphics window is FreeCAD's Show/Hide (Std_ToggleVisibility); Nxt's own is out",
                after["Space"] == after["Std_ToggleVisibility"] != vis0 and nxt_space in (None, "NoneType"),
                info["Space on a picked Pad face: (Body, Pad, Sketch) shown"])
    Gui.Selection.clearSelection()
    # F2 in FreeCAD's tree (the Part Navigator with Nxt off, the FreeCAD Tree tab with it on) opens the name editor,
    # as tutorial.rename does
    from .tutorial import qtest
    tree = next((t for t in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget)
                 if t.isVisible() and t.findItems("Box", QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive)), None)
    if tree is None:
        smoke.check("F2 in the Part Navigator opens the name editor", False, "no visible tree shows Box")
        return
    item = tree.findItems("Box", QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive)[0]
    tree.setCurrentItem(item)
    tree.setFocus()
    _wait(100)
    qtest().keyClick(tree, QtCore.Qt.Key_F2)
    editors = []
    for _ in range(10):
        _wait(100)
        editors = [e for e in tree.findChildren(QtWidgets.QLineEdit) if e.isVisible()]
        if editors:
            break
    smoke.check("F2 in the Part Navigator opens the name editor", editors,
                type(QtWidgets.QApplication.focusWidget()).__name__)
    if editors:
        qtest().keyClick(editors[0], QtCore.Qt.Key_Escape)
    Gui.Selection.clearSelection()


def _close_edit(doc):
    if Gui.Control.activeDialog():
        doc.abortTransaction()
        Gui.Control.closeDialog()
    if Gui.ActiveDocument.getInEdit() is not None:
        Gui.ActiveDocument.resetEdit()
    _wait(300)


def _double_click(smoke, info, doc, pad):
    """A double-click on the Pad's top face in the graphics window: what opens (Nxt edits the feature behind it)."""
    from .qt import Qt
    view = Gui.ActiveDocument.ActiveView
    Gui.SendMsgToActiveView("ViewIsometric")
    Gui.SendMsgToActiveView("ViewFit")
    _settled()
    x, y = view.getPointOnViewport(App.Vector(10, 5, 10))
    hit = view.getObjectInfo((x, y))
    f = smoke.nav()
    dpr = f.widget.devicePixelRatioF()
    p = QtCore.QPoint(round(x / dpr), round((view.getSize()[1] - y) / dpr))
    Gui.Selection.clearSelection()
    for kind in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick,
                 QtCore.QEvent.MouseButtonRelease):
        held = Qt.LeftButton if kind in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick) \
            else Qt.NoButton
        smoke.send(f, kind, p, Qt.LeftButton, held)
        _wait(30)
    _wait(1500)
    editing = Gui.ActiveDocument.getInEdit()
    info["double-click on the Pad's top face"] = {
        "hit": (hit or {}).get("Component") or (hit or {}).get("Object"), "sub": (hit or {}).get("SubName"),
        "in edit": getattr(getattr(editing, "Object", None), "Name", None),
        "dialog": bool(Gui.Control.activeDialog())}
    _close_edit(doc)
    Gui.Selection.clearSelection()


def _open_profile(info, doc):
    """A Pad on a rectangle with a 0.01 mm gap at one corner: FreeCAD fails it; Nxt's sketch repair closes it."""
    import Part
    body = doc.addObject("PartDesign::Body", "GapBody")
    sk = body.newObject("Sketcher::SketchObject", "GapSketch")
    pts = [App.Vector(0, 30, 0), App.Vector(20, 30, 0), App.Vector(20, 40, 0), App.Vector(0, 40, 0)]
    for i in range(4):
        end = pts[(i + 1) % 4] + (App.Vector(0.01, 0, 0) if i == 3 else App.Vector())
        sk.addGeometry(Part.LineSegment(pts[i], end))
    pad = body.newObject("PartDesign::Pad", "GapPad")
    pad.Profile = sk
    pad.Length = 5
    n0 = len(sk.Constraints)
    doc.recompute()
    before = pad.isValid()
    _wait(1500)
    doc.recompute()
    info["open profile (0.01 mm gap)"] = {"Pad valid at first": before, "Pad valid after 1.5 s": pad.isValid(),
                                         "constraints added": [c.Type for c in sk.Constraints[n0:]]}


def _navigator_panels(smoke, info, doc, pad):
    """Step 2: Dependencies and Details under Nxt's tree, Make Current Feature and its rollback bar, NX's names in
    Nxt's menu."""
    from freecad.nxt.core import settings
    from freecad.nxt.tree import menu_actions, panel as nxt_panel
    from .nxt_navigator import PARAM
    nav, bridge = nxt.navigator(), nxt_panel.bridge()
    if nav is None or bridge is None:
        smoke.check("Part Navigator panels (Dependencies, Details)", False, "Nxt's panel was not adopted")
        return
    res = info.setdefault("navigator panels", {})
    was = (nav.dep_section.is_open(), nav.det_section.is_open())
    sketch = pad.Profile[0] if isinstance(pad.Profile, tuple) else pad.Profile
    # the status strip grows by its Selected line on a pick; Nxt's view must keep its size (when it did not, making
    # and picking 25 boxes took 100 s against 4 s; nxt_navigator.Navigator._status_holder)
    strip = smoke.shell.navigator_status
    Gui.Selection.clearSelection()
    strip.refresh(force=True)
    _wait(200)
    sizes = [nav.tree.size().toTuple()]
    Gui.Selection.addSelection(doc.Name, pad.Name)
    strip.refresh(force=True)
    _wait(200)
    sizes.append(nav.tree.size().toTuple())
    res["Nxt's view size, no pick then a pick"] = sizes
    smoke.check("The status strip's Selected line does not resize Nxt's tree", sizes[0] == sizes[1]
                and "Selected" in strip.text(), {"sizes": sizes, "strip": strip.text()})
    try:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, pad.Name)
        nav.dep_section.set_open(True)
        nav.det_section.set_open(True)
        _wait(600)
        nav.refresh()
        deps = nav.rows(nav.deps)
        res["Dependencies of the Pad"] = deps
        res["Nxt's arrows"] = {"DependencyArrows": settings.get("DependencyArrows"), "links": bridge.linkArrows}
        parents = [r for r, d in deps if d == 2]
        smoke.check("Dependencies: the Pad's parent is its Sketch (Geometry), and Nxt draws its arrows while the "
                    "panel is open", [sketch.Label, "Geometry"] in parents and settings.get("DependencyArrows")
                    and bridge.linkArrows.get("source", -1) >= 0, res["Dependencies of the Pad"])
        det = nav.rows(nav.details)
        res["Details of the Pad"] = det
        smoke.shot("nxt_navigator.png")
        length = next((nav.details.topLevelItem(i) for i in range(nav.details.topLevelItemCount())
                       if nav.details.topLevelItem(i).text(0) == "Length"), None)
        undo0 = doc.UndoCount
        if length is not None:
            length.setText(1, "12 mm")
            _wait(400)
        res["Length typed 12 mm in Details"] = {"Pad.Length": pad.Length.Value, "undo steps": doc.UndoCount - undo0}
        smoke.check("Details: the Pad's Length, Type and Reversed; a Length typed there sets the Pad, one undo step",
                    [r[0][0] for r in det][:3] == ["Length", "Type", "Reversed"] and abs(pad.Length.Value - 12) < 1e-9
                    and doc.UndoCount - undo0 == 1, {"rows": det, **res["Length typed 12 mm in Details"]})
        if doc.UndoCount - undo0 == 1:
            doc.undo()
            doc.recompute()
        nav.dep_section.set_open(False)
        _wait(300)
        smoke.check("Nxt's dependency arrows go with the Dependencies panel", not settings.get("DependencyArrows"),
                    settings.get("DependencyArrows"))
        # Make Current Feature (the ribbon's PartDesign_MoveTip) moves Nxt's rollback bar: rolled back to the Sketch
        # with Nxt's bar, then the Pad made current from the ribbon's command
        body = doc.getObject("Body")
        bridge.setTip(body.Name, sketch.Name)
        _wait(500)
        rolled = getattr(body.Tip, "Name", None)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, pad.Name)
        Gui.runCommand("PartDesign_MoveTip")
        _wait(800)
        bar = next((x for x in bridge.tipBars if x["body"] == body.Name), {})
        res["Make Current Feature on the Pad"] = {"rolled back to": rolled, "tip": getattr(body.Tip, "Name", None),
                                                  "bar": bar, "Pad row": bridge.treeModel.row_of(pad.Name)}
        smoke.check("Make Current Feature moves Nxt's rollback bar to the feature",
                    rolled == sketch.Name and getattr(body.Tip, "Name", None) == pad.Name
                    and bar.get("pos") == bridge.treeModel.row_of(pad.Name), res["Make Current Feature on the Pad"])
        menu = menu_actions.build(bridge, [pad.Name])
        items = [(i["command"], i["label"]) for s in menu.get("sections", []) for i in s["items"]]
        res["Nxt's menu on the Pad"] = {"lead": (menu.get("lead") or {}).get("label"), "items": items}
        names = {"dock": nxt_panel.instance().windowTitle(),
                 "Roll back to here": App.Qt.translate("NxtMenu", "Roll back to here"),
                 "Roll forward to here": App.Qt.translate("NxtMenu", "Roll forward to here"),
                 "toast": App.Qt.translate("Nxt", "Tip of %s moved to %s")}
        res["NX names for Nxt's words"] = names
        smoke.check("Nxt's menu has NX's Edit Parameters on a feature, and its Roll back/forward is Make Current "
                    "Feature", ("NXStyle_EditParameters", "Edit Parameters") in items
                    and names["Roll back to here"] == names["Roll forward to here"] == "Make Current Feature"
                    and names["dock"] == "Part Navigator", {**res["Nxt's menu on the Pad"], **names})
    except Exception as e:
        import traceback
        smoke.check("Part Navigator panels (Dependencies, Details)", False, traceback.format_exc()[-600:] or repr(e))
    finally:
        nav.dep_section.set_open(was[0])
        nav.det_section.set_open(was[1])
        App.ParamGet(PARAM).SetBool("Dependencies", was[0])
        App.ParamGet(PARAM).SetBool("Details", was[1])
        Gui.Selection.clearSelection()


def _features(smoke, info, doc, pad, box):
    from freecad.nxt.app import services
    from freecad.nxt.core import settings
    res = info.setdefault("features", {})
    body = doc.getObject("Body")
    # its commands in NX-Style's Menu (the hidden menu bar's View menu). FreeCAD rebuilds its menus, so a menu
    # found here may be deleted a moment later: its entries are read at once, and a deleted one is retried
    found = None
    for _ in range(3):
        try:
            found = any("FreeCAD-Nxt" in b.text() for a in Gui.getMainWindow().menuBar().actions()
                        if a.menu() is not None and a.text().replace("&", "") == "View" for b in a.menu().actions())
            break
        except RuntimeError:
            _wait(200)
    res["menu"] = {"View > FreeCAD-Nxt": found}
    # the rollback bar: move the Body's tip back to the Sketch and forward again
    from freecad.nxt.tree import panel as nxt_panel
    bridge = nxt_panel.bridge()
    try:
        _wait(500)
        bridge.setTip("Body", "Sketch")
        _wait(500)
        back = getattr(body.Tip, "Name", None)
        bridge.setTip("Body", "Pad")
        _wait(500)
        res["rollback"] = {"tip after rolling back": back, "tip after rolling forward": getattr(body.Tip, "Name", None)}
    except Exception as e:
        res["rollback"] = {"error": repr(e)}
    # Isolate (NX's Show Only)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, "Box")
    Gui.runCommand("Nxt_Isolate")
    _wait(300)
    iso = services.isolation()
    res["isolate"] = {"active": bool(iso and iso.active()),
                      "body hidden": not body.ViewObject.Visibility or not pad.ViewObject.Visibility}
    if iso is not None and iso.active():
        iso.exit()
        _wait(200)
    res["isolate"]["exited, body shown"] = bool(body.ViewObject.Visibility and pad.ViewObject.Visibility)
    Gui.Selection.clearSelection()
    # Section view with filled cut faces
    from freecad.nxt.tools import section_view
    try:
        Gui.runCommand("Nxt_SectionView")
        _wait(800)
        sec = section_view.current()
        res["section view"] = {"open": sec is not None,
                               "objects": [o.TypeId for o in doc.Objects if "ection" in o.Name][:3]}
        if sec is not None:
            if os.environ.get("NXSTYLE_SMOKE_OUT"):
                smoke.shot("nxt_section.png")
            section_view.end(sec)
            _wait(300)
    except Exception as e:
        res["section view"] = {"error": repr(e)}
    # Property Inspector
    from freecad.nxt.inspector import host
    Gui.Selection.addSelection(doc.Name, "Body", "Pad.")
    try:
        Gui.runCommand("Nxt_PropertyInspector")
        _wait(500)
        res["property inspector"] = {"open": host.is_open()}
        if host.is_open():
            host.toggle()
            _wait(200)
    except Exception as e:
        res["property inspector"] = {"error": repr(e)}
    Gui.Selection.clearSelection()
    # Quick Mass
    try:
        settings.put("QuickMass", True)
        services.instance().quick_mass_changed()
        _wait(300)
        res["quick mass"] = {"shown": services.instance()._mass_bar is not None}
    except Exception as e:
        res["quick mass"] = {"error": repr(e)}
    finally:
        settings.put("QuickMass", False)
        services.instance().quick_mass_changed()
    # Drag handles (FreeCAD's gizmos) and Nxt's floating value boxes on a Pad in edit
    try:
        Gui.ActiveDocument.setEdit(pad.Name)
        _wait(1200)
        floating = services.instance()._floating
        shown = [n for n, b in (floating._boxes.items() if floating else [])
                 if b.widget is not None and b.widget.isVisible()]
        res["pad gizmos"] = {"linear handles": _scene_has("SoLinearDraggerContainer"),
                             "rotation handles": _scene_has("SoRotationDraggerContainer"),
                             "EnableGizmos": App.ParamGet(GIZMOS).GetBool("EnableGizmos", True),
                             "floating value boxes": shown}
        smoke.shot("nxt_pad_gizmos.png")
    except Exception as e:
        res["pad gizmos"] = {"error": repr(e)}
    finally:
        if Gui.Control.activeDialog():
            doc.abortTransaction()
            Gui.Control.closeDialog()
        Gui.ActiveDocument.resetEdit()
        _wait(300)
    # Nxt's fillet (a blend built by booleans), on one edge of the pad
    try:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, "Body", "Pad.Edge1")
        n0 = len(doc.Objects)
        Gui.runCommand("Nxt_BlendFillet")
        _wait(1500)
        made = list(doc.Objects[n0:])
        res["fillet"] = {"task open": bool(Gui.Control.activeDialog()),
                         "made": [(o.Name, o.TypeId, type(getattr(o, "Proxy", None)).__name__) for o in made],
                         "valid": [o.isValid() for o in made]}
        smoke.shot("nxt_fillet.png")
    except Exception as e:
        res["fillet"] = {"error": repr(e)}
    finally:
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        _wait(300)
    Gui.Selection.clearSelection()
    smoke.check("Nxt's features tried (see info.nxt.features)", True, res)
