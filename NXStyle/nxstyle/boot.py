# SPDX-License-Identifier: LGPL-2.1-or-later
"""Start-up hook: wait until FreeCAD's main window is shown, then build the shell."""

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtCore

START = "User parameter:BaseApp/Preferences/Mod/Start"


def _start(attempt=0):
    mw = Gui.getMainWindow()
    if (mw is None or not mw.isVisible()) and attempt < 50:
        QtCore.QTimer.singleShot(200, lambda: _start(attempt + 1))
        return
    try:
        from . import shell
        shell.start()
    except Exception:
        import traceback
        App.Console.PrintError("NXStyle failed to start:\n" + traceback.format_exc() + "\n")


OVERLAYS = "User parameter:BaseApp/MainWindow/DockWindows"
NX_DOCKED = {"Model", "Tasks", "NXHistory", "Selection view"}


def release_overlays():
    """FreeCAD 1.1 puts the Tasks panel in a right-hand overlay by default; NX
    keeps the dialog with the navigators, so take NX's panels out of overlays."""
    root = App.ParamGet(OVERLAYS)
    for side in ("OverlayLeft", "OverlayRight", "OverlayTop", "OverlayBottom"):
        grp = root.GetGroup(side)
        names = [n for n in grp.GetString("Widgets", "").split(",") if n]
        keep = [n for n in names if n not in NX_DOCKED]
        if keep != names:
            grp.SetString("Widgets", ",".join(keep) + ("," if keep else ""))


def schedule():
    # The NX profile is already configured; skip FreeCAD's first-run welcome panel
    App.ParamGet(START).SetBool("FirstStart2024", False)
    release_overlays()
    try:   # before Strata installs itself (from its own zero timer): NX layout settings for it
        from . import plm
        plm.prepare()
    except Exception:
        import traceback
        App.Console.PrintError("NXStyle: preparing Strata failed:\n" + traceback.format_exc() + "\n")
    try:   # before any LCInterlocking panel module is imported (its workbench, or a document that has one)
        from . import lcinterlocking
        lcinterlocking.install()
    except Exception:
        import traceback
        App.Console.PrintError("NXStyle: the LCInterlocking Qt 6 patch failed:\n" + traceback.format_exc() + "\n")
    QtCore.QTimer.singleShot(0, _start)
