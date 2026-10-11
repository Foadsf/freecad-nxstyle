# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX default keyboard shortcuts mapped onto FreeCAD commands.

Sources: Siemens NX documentation and tutorials (Ctrl+F Fit, Ctrl+B Hide,
Ctrl+Shift+B Invert, Ctrl+Shift+U Show All, Ctrl+W Show and Hide, Ctrl+J
Object Display, Ctrl+T Move Object, X Extrude, Ctrl+M Modeling, Ctrl+Shift+D
Drafting, Home Trimetric, End Isometric, F8 Snap View) plus NX textbooks for
the rest. A key already used by another FreeCAD command is taken away from
it, because Qt ignores ambiguous shortcuts.
"""

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtGui

NX_SHORTCUTS = [
    # view
    ("Std_ViewFitAll", "Ctrl+F"),
    ("Std_ViewTrimetric", "Home"),
    ("Std_ViewIsometric", "End"),
    ("Std_ViewFront", "Ctrl+Alt+F"),
    ("Std_ViewTop", "Ctrl+Alt+T"),
    ("Std_ViewRight", "Ctrl+Alt+R"),
    ("Std_ViewLeft", "Ctrl+Alt+L"),
    ("NXStyle_SnapView", "F8"),
    ("Sketcher_ViewSketch", "Shift+F8"),
    ("Std_ViewBoxZoom", "F6"),
    ("Std_Refresh", "F5"),
    ("Std_MainFullscreen", "Alt+Return"),
    # visibility / display
    ("Std_HideSelection", "Ctrl+B"),
    ("NXStyle_InvertVisibility", "Ctrl+Shift+B"),
    ("Std_ShowSelection", "Ctrl+Shift+K"),
    ("Std_ShowObjects", "Ctrl+Shift+U"),
    ("NXStyle_ShowHide", "Ctrl+W"),
    ("Std_SetAppearance", "Ctrl+J"),
    ("Std_TransformManip", "Ctrl+T"),
    # modelling
    ("PartDesign_Pad", "X"),
    ("NXStyle_Expressions", "Ctrl+E"),
    ("NXStyle_RepeatCommand", "F4"),
    # sketch
    ("Sketcher_LeaveSketch", "Ctrl+Q"),
    ("Sketcher_CreatePolyline", "Z"),
    ("Sketcher_Dimension", "D"),
    # customization
    ("Std_DlgCustomize", "Ctrl+1"),
    ("Std_DlgPreferences", "Ctrl+2"),
    # applications (NXStyle_App_* commands carry Ctrl+M / Ctrl+Shift+D themselves)
    ("NXStyle_App_modeling", "Ctrl+M"),
    ("NXStyle_App_drafting", "Ctrl+Shift+D"),
]

# Freed keys get these replacements so nothing important is lost
RELOCATE = {
    "Std_Quit": "",                  # Ctrl+Q now finishes a sketch; Alt+F4 still quits
    "Std_CloseActiveWindow": "Ctrl+F4",
}


def _get(name):
    try:
        return Gui.Command.get(name)
    except Exception:
        return None


def _holders(seq):
    try:
        return list(Gui.Command.listByShortcut(seq))
    except Exception:
        return []


def apply():
    """Apply the NX map; returns {command: (requested, actual)} for checking."""
    known = set(Gui.listCommands())
    result = {}
    for name, seq in RELOCATE.items():
        cmd = _get(name) if name in known else None
        if cmd is not None:
            cmd.setShortcut(seq)
    for name, seq in NX_SHORTCUTS:
        if name not in known:
            continue
        for other in _holders(seq):
            if other != name:
                c = _get(other)
                if c is not None:
                    c.setShortcut("")
        cmd = _get(name)
        cmd.setShortcut(seq)
        got = _action_shortcut(cmd)
        if _norm(got) != _norm(seq):
            # Python-defined commands in FreeCAD 1.0 do not always pick up
            # setShortcut(); put the key on the QAction directly.
            for act in cmd.getAction() or []:
                act.setShortcut(QtGui.QKeySequence(seq))
                break
            got = _action_shortcut(cmd)
        result[name] = (seq, got)
    return result


def _norm(seq):
    return seq.replace(" ", "").lower()


def _action_shortcut(cmd):
    acts = cmd.getAction() or []
    if acts:
        return acts[0].shortcut().toString()
    return cmd.getShortcut()


def report(result):
    bad = {k: v for k, v in result.items() if _norm(v[0]) != _norm(v[1])}
    for k, (want, got) in bad.items():
        App.Console.PrintWarning(f"NXStyle: shortcut {want} for {k} ended up as '{got}'\n")
    return bad
