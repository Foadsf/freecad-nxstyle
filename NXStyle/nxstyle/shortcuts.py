# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX keyboard shortcuts mapped onto FreeCAD.

The table follows https://github.com/Foadsf/NXtips (the NX default bindings
with their NX command IDs), plus a few NX defaults from the NX textbooks
(Ctrl+T Move Object, Ctrl+Q Finish Sketch). Each row names the FreeCAD
command that does the same job, or the closest one; rows without an
equivalent show an explanation instead of doing nothing.

Qt ignores a key that two enabled actions share, and a single key such as
"S" never fires while any shortcut chord starts with it ("S, B"). So every
key used here is first taken away from every other action in the window.
"""

from dataclasses import dataclass, field

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QAction, QtGui, QtWidgets, Qt


@dataclass
class Entry:
    nx: str                       # NX command name
    keys: str                     # NX key binding
    cmd: object = None            # FreeCAD command name or list of candidates
    context: str = "doc"          # where it is meaningful: doc | sketch
    note: str = ""                # how the FreeCAD behaviour differs, if it does
    alias: bool = False           # keep the command's own key, add this one beside it
    workbench: str = ""           # workbench to load first (command not registered yet)
    message: str = ""             # no FreeCAD equivalent: explain instead
    nx_id: str = ""
    resolved: str = field(default="", repr=False)


TABLE = [
    # ---- File
    Entry("New", "Ctrl+N", "Std_New", nx_id="UG_FILE_NEW"),
    Entry("Open", "Ctrl+O", "Std_Open", nx_id="UG_FILE_OPEN"),
    Entry("Save", "Ctrl+S", "Std_Save", nx_id="UG_FILE_SAVE_PART"),
    Entry("Save As", "Ctrl+Shift+A", "Std_SaveAs", nx_id="UG_FILE_SAVE_AS"),
    Entry("Save as New Item Type", "Ctrl+Alt+Shift+I", "Std_SaveCopy", nx_id="UI_FILE_SAVE_AS_NEW_ITEM_TYPE",
          note="Teamcenter item types do not exist in FreeCAD; saves a copy under a new name"),
    Entry("Save as Non-Master Parts", "Ctrl+Alt+Shift+N", nx_id="UI_FILE_SAVE_AS_NON_MASTER_PARTS",
          message="Non-master parts are a Teamcenter/NX concept with no FreeCAD equivalent. "
                  "Use File > Save a Copy, or link the part into a new document (Std_LinkMake)."),
    Entry("Plot", "Ctrl+P", "Std_Print", nx_id="UG_FILE_PLOT"),
    Entry("Execute NXOpen", "Ctrl+U", "Std_DlgMacroExecute", nx_id="UG_FILE_RUN_UFUN",
          note="runs a FreeCAD Python macro"),
    Entry("Execute GRIP", "Ctrl+G", "Std_DlgMacroExecute", alias=True, nx_id="UG_FILE_RUN_GRIP",
          note="GRIP does not exist in FreeCAD; opens the macro (Python) runner"),
    Entry("Execute Debug GRIP", "Ctrl+Shift+G", "Std_MacroStartDebug", nx_id="UG_FILE_RUN_GRIP_DEBUG",
          note="debugs the macro open in FreeCAD's macro editor"),
    # ---- Edit
    Entry("Undo", "Ctrl+Z", "Std_Undo", nx_id="UG_EDIT_UNDO"),
    Entry("Redo", "Ctrl+Y", "Std_Redo", nx_id="UG_EDIT_REDO"),
    Entry("Cut", "Ctrl+X", "Std_Cut", nx_id="UG_EDIT_CUT"),
    Entry("Copy", "Ctrl+C", "Std_Copy", nx_id="UG_EDIT_COPY"),
    Entry("Paste", "Ctrl+V", "Std_Paste", nx_id="UG_EDIT_PASTE"),
    Entry("Paste Special", "Ctrl+Alt+V", "Std_DuplicateSelection", nx_id="UG_EDIT_PASTE_SPECIAL",
          note="FreeCAD's Duplicate Selection (copy with dependency options)"),
    Entry("Delete", "Ctrl+D", "Std_Delete", alias=True, nx_id="UG_EDIT_DELETE", note="the Delete key still works"),
    # ---- View
    Entry("Front View", "Ctrl+Alt+F", "Std_ViewFront", nx_id="UG_VIEW_POPUP_ORIENT_FRONT"),
    Entry("Top View", "Ctrl+Alt+T", "Std_ViewTop", nx_id="UG_VIEW_POPUP_ORIENT_TOP"),
    Entry("Left View", "Ctrl+Alt+L", "Std_ViewLeft", nx_id="UG_VIEW_POPUP_ORIENT_LEFT"),
    Entry("Right View", "Ctrl+Alt+R", "Std_ViewRight", nx_id="UG_VIEW_POPUP_ORIENT_RIGHT"),
    Entry("Trimetric View", "Home", "Std_ViewTrimetric", nx_id="UG_VIEW_POPUP_ORIENT_TFRTRI"),
    Entry("Isometric View", "End", "Std_ViewIsometric", nx_id="UG_VIEW_POPUP_ORIENT_TFRISO"),
    Entry("Orient to Active Sketch", "Shift+F8", "Sketcher_ViewSketch", "sketch",
          nx_id="UG_SKETCH_ORIENT_VIEW_TO_SKETCH"),
    Entry("Snap to Closest Standard View", "F8", "NXStyle_SnapView", nx_id="UG_VIEW_POPUP_SNAP_VIEW"),
    Entry("Fit", "Ctrl+F", "Std_ViewFitAll", nx_id="UG_VIEW_FIT"),
    Entry("Zoom", "F6", "Std_ViewBoxZoom", nx_id="UG_VIEW_POPUP_ZOOM", note="drag a rectangle to zoom"),
    Entry("Rotate", "F7", "NXStyle_RotateMode", nx_id="UG_VIEW_POPUP_ROTATE",
          note="MB1 drag rotates until Esc, MB2 or MB3"),
    Entry("Refresh", "F5", "NXStyle_Refresh", nx_id="UG_VIEW_POPUP_REFRESH",
          note="redraws the view; recompute stays on FreeCAD's Ctrl+R"),
    Entry("Toggle WCS Display", "W", "Std_AxisCross", nx_id="UG_WCS_DISPLAY",
          note="FreeCAD's axis cross at the origin; FreeCAD has no movable WCS"),
    Entry("Edit Section", "Ctrl+H", ["Part_SectionCut", "Std_ToggleClipPlane"], nx_id="UG_VIEW_SECTIONING"),
    Entry("Toggle Full Screen", "Alt+Return", "Std_MainFullscreen", nx_id="UG_VIEW_FULL_SCREEN_MODE"),
    # ---- Modeling
    Entry("Extrude", "X", ["NXStyle_Extrude", "PartDesign_Pad"], nx_id="UG_MODELING_EXTRUDED_FEATURE",
          note="with nothing selected: sketch first, Finish Sketch continues into the Extrude dialog"),
    Entry("Move Object", "Ctrl+T", "Std_TransformManip"),
    # ---- Sketch (sketch edit mode)
    Entry("Profile", "Z", "Sketcher_CreatePolyline", "sketch", nx_id="UG_SKETCH_PROFILE"),
    Entry("Rectangle", "R", "Sketcher_CreateRectangle", "sketch", nx_id="UG_SKETCH_RECTANGLE"),
    Entry("Line", "L", "Sketcher_CreateLine", "sketch", nx_id="UG_SKETCH_LINE"),
    Entry("Arc", "A", "Sketcher_CreateArc", "sketch", nx_id="UG_SKETCH_ARC"),
    Entry("Circle", "O", "Sketcher_CreateCircle", "sketch", nx_id="UG_SKETCH_CIRCLE"),
    Entry("Polygon", "P", ["Sketcher_CreateRegularPolygon", "Sketcher_CreateHexagon"], "sketch"),
    Entry("Studio Spline", "S", "Sketcher_CreateBSpline", "sketch"),
    Entry("Quick Trim", "T", "Sketcher_Trimming", "sketch"),
    Entry("Quick Extend", "E", "Sketcher_Extend", "sketch"),
    Entry("Fillet", "F", "Sketcher_CreateFillet", "sketch"),
    Entry("Rapid Dimension", "D", ["Sketcher_Dimension", "Sketcher_ConstrainDistance"], "sketch"),
    Entry("Geometric Constraints", "C", ["Sketcher_ConstrainCoincidentUnified", "Sketcher_ConstrainCoincident"],
          "sketch", note="FreeCAD applies one constraint per tool; C starts Coincident"),
    Entry("Finish Sketch", "Ctrl+Q", "Sketcher_LeaveSketch", "sketch", nx_id="UG_DIRECT_SKETCH_FINISH"),
    # ---- Selection, show and hide
    Entry("Hide", "Ctrl+B", "Std_HideSelection"),
    Entry("Show and Hide Panel", "Ctrl+W", "NXStyle_ShowHide"),
    Entry("Immediate Hide", "Ctrl+Shift+I", "NXStyle_ImmediateHide", note="pick objects to hide them; Esc to finish"),
    Entry("Show Panel", "Ctrl+Shift+K", "Std_ShowSelection",
          note="select the hidden objects in the Part Navigator first"),
    Entry("Show All", "Ctrl+Shift+U", "Std_ShowObjects"),
    Entry("Invert Show/Hidden", "Ctrl+Shift+B", "NXStyle_InvertVisibility"),
    Entry("Edit Display", "Ctrl+J", ["Std_SetAppearance", "Std_DlgDisplayProperties"]),
    Entry("Object Information", "Ctrl+I", "NXStyle_ObjectInfo"),
    # ---- Applications
    Entry("Modeling", "Ctrl+M", "NXStyle_App_modeling"),
    Entry("Sheet Metal", "Ctrl+Shift+M", "NXStyle_App_sheet_metal",
          message="Sheet Metal needs FreeCAD's SheetMetal add-on. Install it in this NX profile with "
                  "Tools > Add-on Manager, restart, and Ctrl+Shift+M will open it."),
    Entry("Drafting", "Ctrl+Shift+D", "NXStyle_App_drafting"),
    Entry("Layout", "Ctrl+Shift+Y", "NXStyle_App_draft", note="FreeCAD's Draft 2D workbench"),
    Entry("Shape Studio", "Ctrl+Alt+S", "NXStyle_App_shape_studio", note="FreeCAD's Surface workbench"),
    # ---- Other
    Entry("Customize", "Ctrl+1", "Std_DlgCustomize"),
    Entry("User Interface Preferences", "Ctrl+2", "Std_DlgPreferences"),
    Entry("Layer Settings", "Ctrl+L", "Draft_LayerManager", workbench="DraftWorkbench",
          note="FreeCAD's Draft layer manager"),
    Entry("Expressions", "Ctrl+E", "NXStyle_Expressions", note="a spreadsheet named Expressions"),
    Entry("Touch Mode", "F4", "NXStyle_TouchMode", note="larger ribbon and bar icons"),
]

# Keys FreeCAD's own commands get instead, so nothing important is lost
RELOCATE = {
    "Std_Quit": "",                  # Ctrl+Q finishes a sketch; Alt+F4 still quits
    "Std_CloseActiveWindow": "Ctrl+F4",
}


def norm(seq):
    return QtGui.QKeySequence(seq).toString()


def first_chord(seq):
    return norm(seq).split(",")[0].strip()


def _known():
    return set(Gui.listCommands())


def resolve(entry, known):
    for name in ([entry.cmd] if isinstance(entry.cmd, str) else (entry.cmd or [])):
        if name in known:
            return name
    return ""


def _cmd_actions():
    """id(QAction) -> command name, for actions that belong to a FreeCAD command."""
    out = {}
    for n in Gui.listCommands():
        try:
            for a in Gui.Command.get(n).getAction() or []:
                out[id(a)] = n
        except Exception:
            continue
    return out


class Shortcuts:
    """Applies TABLE; alias keys and fallbacks live on extra QActions in the main window."""

    def __init__(self, shell):
        self.shell = shell
        self.mw = Gui.getMainWindow()
        self.aliases = {}       # key -> QAction
        self.targets = {}       # key -> QAction that should fire
        self.rows = []          # report rows

    # ---------------------------------------------------------------- apply
    def apply(self):
        known = _known()
        for name, seq in RELOCATE.items():
            if name in known:
                Gui.Command.get(name).setShortcut(seq)
        primaries = {}
        wanted = []             # (key, entry, command or "")
        for e in TABLE:
            e.resolved = resolve(e, known)
            wanted.append((norm(e.keys), e))
        ours = set()
        for key, e in wanted:
            act = self._target_action(key, e, primaries)
            if act is not None:
                ours.add(id(act))
                self.targets[key] = act
        self._free_keys([k for k, _ in wanted], ours)
        # assign after freeing, so freeing cannot remove our own keys
        for key, e in wanted:
            act = self.targets.get(key)
            if act is None:
                continue
            if act in self.aliases.values():
                act.setShortcut(QtGui.QKeySequence(key))
            else:
                cmd = Gui.Command.get(e.resolved)
                cmd.setShortcut(key)
                if norm(act.shortcut().toString()) != key:
                    act.setShortcut(QtGui.QKeySequence(key))
        self.attach_to_window()
        self.rows = [self._row(k, e) for k, e in wanted]
        return self.rows

    def attach_to_window(self):
        """Qt only fires a window shortcut if its action sits on a *visible* widget.
        NXStyle hides FreeCAD's menu bar and toolbars, so every action with a key
        is also added to the main window itself (which shows nothing)."""
        attached = set(id(a) for a in self.mw.actions())
        for act in self.mw.findChildren(QAction):
            if id(act) in attached:
                continue
            if any(not s.isEmpty() for s in act.shortcuts()):
                self.mw.addAction(act)

    def _target_action(self, key, e, primaries):
        cmd_act = None
        if e.resolved:
            acts = Gui.Command.get(e.resolved).getAction() or []
            cmd_act = acts[0] if acts else None
        needs_alias = (e.alias or e.workbench or e.message and not e.resolved
                       or cmd_act is None or e.resolved in primaries)
        if not needs_alias:
            primaries[e.resolved] = key
            return cmd_act
        act = self.aliases.get(key)
        if act is None:
            act = QAction(e.nx, self.mw)
            act.setObjectName(f"NXShortcut_{e.nx.replace(' ', '')}")
            act.setShortcutContext(Qt.WindowShortcut)
            act.triggered.connect(lambda _=False, entry=e: self._run_alias(entry))
            self.mw.addAction(act)
            self.aliases[key] = act
        return act

    def _run_alias(self, e):
        from . import commands
        from .ribbon import trigger
        if e.workbench and not e.resolved:
            self.shell.preload([e.workbench])
            e.resolved = resolve(e, _known())
        if e.resolved:
            commands.remember(e.resolved)
            trigger(e.resolved)
        elif e.message:
            QtWidgets.QMessageBox.information(self.mw, e.nx, e.message)

    def _free_keys(self, keys, ours):
        """Take each key away from every other action, including chords that start with it."""
        singles = set(keys)
        by_cmd = _cmd_actions()
        cleared = set()
        for act in self.mw.findChildren(QAction):
            if id(act) in ours:
                continue
            seqs = [s.toString() for s in act.shortcuts()] or [act.shortcut().toString()]
            hit = False
            for s in seqs:
                if not s:
                    continue
                if norm(s) in singles or first_chord(s) in singles:
                    hit = True
            if not hit:
                continue
            name = by_cmd.get(id(act))
            if name and name not in cleared:
                try:
                    Gui.Command.get(name).setShortcut("")
                except Exception:
                    pass
                cleared.add(name)
            act.setShortcut(QtGui.QKeySequence())
        self.cleared = sorted(cleared)

    def reapply(self):
        """After a workbench loads new commands, take our keys back from them."""
        if not self.targets:
            return
        self._free_keys(list(self.targets), {id(a) for a in self.targets.values()})
        for key, act in self.targets.items():
            if norm(act.shortcut().toString()) != key:
                act.setShortcut(QtGui.QKeySequence(key))
        self.attach_to_window()

    def _row(self, key, e):
        act = self.targets.get(key)
        how = "alias" if act in self.aliases.values() else "command"
        status = "mapped" if (e.resolved or e.message or e.workbench) else "missing"
        return {"nx": e.nx, "keys": key, "freecad": e.resolved or (e.cmd if e.workbench else ""),
                "context": e.context, "via": how, "status": status, "note": e.note or e.message}


_instance = None


def apply(shell):
    global _instance
    _instance = Shortcuts(shell)
    return _instance.apply()


def instance():
    return _instance


def report(rows):
    bad = [r for r in rows if r["status"] == "missing"]
    for r in bad:
        App.Console.PrintWarning(f"NXStyle: no FreeCAD command for {r['nx']} ({r['keys']})\n")
    return bad
