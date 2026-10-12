# SPDX-License-Identifier: LGPL-2.1-or-later
"""Strata as NXStyle's data management (the role Teamcenter plays next to NX).

Strata (https://github.com/Foadsf/freecad-strata) is its own add-on: the launcher loads it next to
NXStyle (``vendor/freecad-strata``, or a copy installed in the NX profile), and this module only
places it in the NX layout once Strata has started:

- its "Versions and history" panel joins the navigators on the left, behind the Part Navigator;
- the resource bar gets a button for it (Strata's own command, so Strata keeps its toolbar hidden);
- the ribbon's PLM tab (``ribbons/common.json``) shows Strata's commands;
- Strata's colour tokens take NX's teal accent.

Strata's engine and UI stay upstream; nothing here copies or patches them.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config
from .qt import QtCore, QtWidgets, Qt
from .ribbon import command_actions

# NX accent (THEME_TOKENS in shell.py) for Strata's light tokens; dark keeps Strata's own
NX_TOKENS = {"accent": "#0B6E79", "accent_hover": "#095A63", "accent_soft": "#C7E3E7", "selected": "#C7E3E7"}
WAIT_MS, TRIES = 250, 80            # Strata installs itself from a zero timer; allow it 20 s
_state = {"tries": 0}


def enabled():
    return config.get().get("plm", "strata") == "strata"


def strata_panel():
    try:
        import strata.boot
    except ImportError:
        return None
    return strata.boot.panel()


def status():
    """For the smoke test and the Information panel."""
    p = strata_panel()
    return {"enabled": enabled(), "loaded": _loaded(), "panel": p is not None, "placed": _state.get("placed", False),
            "panel_area": _area(p), "resource_button": "action" in _state}


def _loaded():
    try:
        import strata  # noqa: F401
        return True
    except ImportError:
        return False


def _area(dock):
    if dock is None:
        return None
    a = Gui.getMainWindow().dockWidgetArea(dock)
    return {Qt.LeftDockWidgetArea: "left", Qt.RightDockWidgetArea: "right"}.get(a, str(a))


def attach(shell):
    """Called once NXStyle's shell is up; waits for Strata, then places it."""
    if not enabled() or not _loaded():
        return
    _state["shell"] = shell
    _poll()


def _poll():
    p = strata_panel()
    if p is None:
        _state["tries"] += 1
        if _state["tries"] < TRIES:
            QtCore.QTimer.singleShot(WAIT_MS, _poll)
        else:
            App.Console.PrintWarning("NXStyle: Strata is loaded but its panel never appeared\n")
        return
    try:
        _place(_state["shell"], p)
    except Exception:
        import traceback
        App.Console.PrintError(f"NXStyle: placing Strata failed\n{traceback.format_exc()}\n")


def _theme(panel):
    try:
        from strata.ui import theme
    except ImportError:
        return
    theme.LIGHT.update(NX_TOKENS)
    panel.setStyleSheet(theme.stylesheet())
    if hasattr(panel, "schedule_refresh"):
        panel.schedule_refresh()


def _resource_action(parent):
    from .qt import QAction, QtGui
    info = {}
    try:
        info = Gui.Command.get("Strata_Panel").getInfo()
    except Exception:
        pass
    acts = command_actions("Strata_Panel")
    if acts:
        icon = acts[0].icon()
    else:
        icon = QtGui.QIcon(info.get("pixmap", "")) if info.get("pixmap") else QtGui.QIcon()
    act = QAction(icon, info.get("menuText") or "Versions and history", parent)
    act.setObjectName("NXStrataPanel")
    act.setToolTip("Versions and history (Strata): every save, versions, workspaces, releases")
    act.triggered.connect(lambda *_: Gui.runCommand("Strata_Panel"))
    return act


def _place(shell, panel):
    mw = Gui.getMainWindow()
    # FreeCAD makes a command's QAction when the command first lands in a toolbar or menu; activating
    # Strata's own workbench once does that (the way NXStyle preloads other workbenches), so the
    # ribbon's PLM buttons and the resource bar have live actions to mirror
    if "StrataWorkbench" in Gui.listWorkbenches():
        shell.preload(["StrataWorkbench"])
    _theme(panel)
    # a navigator like the others: left tab strip, behind the Part Navigator (NX opens with that one)
    model = mw.findChild(QtWidgets.QDockWidget, "Model")
    if not panel.isFloating():
        if model is not None:
            mw.tabifyDockWidget(model, panel)       # moves it from Strata's right-hand area too
            model.raise_()
        else:
            mw.addDockWidget(Qt.LeftDockWidgetArea, panel)
        # the move can leave the right-hand area's tab strip on screen, empty, over the Top Border Bar
        QtCore.QTimer.singleShot(0, shell.hide_stray_tab_bars)
    # Strata's command on the resource bar. Strata keeps its fallback toolbar hidden while an action
    # with its command's text sits on a visible toolbar; without one, Strata shows that toolbar every
    # 2 s and NXStyle hides it again. FreeCAD makes a Python command's QAction only when the command
    # is first added to a menu or toolbar, so the button gets its own action that runs the command.
    if getattr(shell, "resource_bar", None) is not None:
        act = _resource_action(shell.resource_bar)
        shell.resource_bar.addAction(act)
        shell.resource_actions[act.text()] = act
        _state["action"] = act
    # the PLM ribbon tab needs Strata's commands, which did not exist when the ribbon was first built
    if getattr(shell, "current_app", None):
        shell.build_ribbon(shell.current_app)
    # Strata re-activates the workbench while installing, which restores FreeCAD's own shortcuts
    # and toolbars: take the NX keys back and hide what is not NX's
    shell._reclaim_keys()
    shell.enforce_ui()
    _state["placed"] = True
    App.Console.PrintLog("NXStyle: Strata placed as data management\n")
