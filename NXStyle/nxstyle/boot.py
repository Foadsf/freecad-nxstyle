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


def schedule():
    # The NX profile is already configured; skip FreeCAD's first-run welcome panel
    App.ParamGet(START).SetBool("FirstStart2024", False)
    QtCore.QTimer.singleShot(0, _start)
