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
    smoke.check("Part Navigator stays the front left tab with Nxt on", smoke.shell.current_left_tab()
                == "Part Navigator", smoke.shell.current_left_tab())
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
    # with the focus in Nxt's tree it claims Home and End (NxtTree.qml Keys.onShortcutOverride)
    views = [w for w in (panel.findChildren(QtWidgets.QWidget) if panel is not None else [])
             if "QQuickWidget" in w.metaObject().className()]
    if views:
        for key, name in ((QtCore.Qt.Key_Home, "Home"), (QtCore.Qt.Key_End, "End")):
            Gui.SendMsgToActiveView("ViewFront")
            front = _settled()
            _key(views[0], key)
            info[f"{name} in Nxt's tree turns the view"] = _settled() != front
    # Space in the 3D view on a picked face of the Pad: FreeCAD's Std_ToggleVisibility, or Nxt's SpaceInView
    sketch = pad.Profile[0] if isinstance(pad.Profile, tuple) else pad.Profile
    body = doc.getObject("Body")
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, "Body", "Pad.Face6")
    vis0 = (body.ViewObject.Visibility, pad.ViewObject.Visibility, sketch.ViewObject.Visibility)
    _key(gl, QtCore.Qt.Key_Space)
    vis1 = (body.ViewObject.Visibility, pad.ViewObject.Visibility, sketch.ViewObject.Visibility)
    info["Space on a picked Pad face: (Body, Pad, Sketch) shown"] = {"before": vis0, "after": vis1}
    body.ViewObject.Visibility, pad.ViewObject.Visibility, sketch.ViewObject.Visibility = vis0
    Gui.Selection.clearSelection()
    # F2 in the Part Navigator (FreeCAD's tree) opens the name editor, as tutorial.rename does
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


def _features(smoke, info, doc, pad, box):
    from freecad.nxt.app import services
    from freecad.nxt.core import settings
    res = info.setdefault("features", {})
    body = doc.getObject("Body")
    # its commands in NX-Style's Menu (the hidden menu bar's View menu)
    view_menu = next((a.menu() for a in Gui.getMainWindow().menuBar().actions()
                      if a.menu() is not None and a.text().replace("&", "") == "View"), None)
    res["menu"] = {"View > FreeCAD-Nxt": view_menu is not None and any(
        "FreeCAD-Nxt" in a.text() for a in view_menu.actions())}
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
