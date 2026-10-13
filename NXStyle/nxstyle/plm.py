# SPDX-License-Identifier: LGPL-2.1-or-later
"""Strata as NXStyle's data management (the role Teamcenter plays next to NX).

Strata (https://github.com/Foadsf/freecad-strata) is its own add-on: the launcher loads it next to
NXStyle (``vendor/freecad-strata``, or a copy installed in the NX profile). NXStyle uses Strata's
embedding API (freecad-strata 1f71005 and later) and places it in the NX layout:

- before Strata starts (from NXStyle's InitGui): NXStyle provides the buttons, the panel goes left;
- once Strata is up (``on_ready``): its panel joins the navigators behind the Part Navigator, the
  resource bar and the PLM ribbon tab (``ribbons/common.json``) use Strata's own QActions, and
  Strata's colour tokens take NX's teal.

Strata's engine and UI stay upstream; nothing here copies or patches them.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config
from .qt import QtCore, QtWidgets, Qt

# NX accent (THEME_TOKENS in shell.py) for Strata's light tokens; dark keeps Strata's own
NX_TOKENS = {"accent": "#0B6E79", "accent_hover": "#095A63", "accent_soft": "#C7E3E7", "selected": "#C7E3E7"}
_state = {}


def enabled():
    return config.get().get("plm", "strata") == "strata"


def _boot():
    try:
        import strata.boot
        return strata.boot
    except ImportError:
        return None


def _embeddable(sb):
    return sb is not None and all(hasattr(sb, f) for f in ("configure", "on_ready", "actions"))


def strata_panel():
    sb = _boot()
    return sb.panel() if sb is not None else None


def status():
    """For the smoke test."""
    sb = _boot()
    p = strata_panel()
    return {"enabled": enabled(), "loaded": sb is not None, "embedding_api": _embeddable(sb),
            "configured_before_start": _state.get("configured_early", False), "panel": p is not None,
            "placed": _state.get("placed", False), "panel_area": _area(p), "resource_button": "action" in _state}


def _area(dock):
    if dock is None:
        return None
    a = Gui.getMainWindow().dockWidgetArea(dock)
    return {Qt.LeftDockWidgetArea: "left", Qt.RightDockWidgetArea: "right"}.get(a, str(a))


# Strata 0.2.0+ binds Ctrl+Shift+D (Compare) and Ctrl+Shift+Y (Sync), NX's Drafting and Layout keys;
# two owners and Qt fires neither. Since freecad-strata 37db86f the host chooses: these two go unbound.
STRATA_SHORTCUTS = {"Strata_Compare": None, "Strata_Sync": None}


def _configure(sb):
    try:
        sb.configure(host_toolbar=True, panel_area="left", shortcuts=STRATA_SHORTCUTS)
    except TypeError:                         # a Strata before 37db86f has no shortcuts= (and no keys)
        sb.configure(host_toolbar=True, panel_area="left")


def prepare():
    """From NXStyle's InitGui, before Strata installs itself (it waits for a zero timer): NXStyle
    provides Strata's buttons, so Strata makes no toolbar of its own and leaves the workbench alone,
    and its panel is created on the left, where the navigators are."""
    sb = _boot()
    if enabled() and _embeddable(sb):
        _configure(sb)
        _state["configured_early"] = not sb.is_ready()


def attach(shell):
    """Called once NXStyle's shell is up."""
    sb = _boot()
    if not enabled() or sb is None:
        return
    if not _embeddable(sb):
        App.Console.PrintWarning("NXStyle: this Strata has no embedding API (freecad-strata 1f71005 or later); "
                                 "it runs, but outside the NX layout\n")
        return
    if not _state.get("configured_early"):
        _configure(sb)                       # applies live when Strata started first
    sb.on_ready(lambda: _safe_place(shell, sb))


def _safe_place(shell, sb):
    try:
        _place(shell, sb)
    except Exception:
        import traceback
        App.Console.PrintError(f"NXStyle: placing Strata failed\n{traceback.format_exc()}\n")


def _place(shell, sb):
    from . import ribbon
    from strata.ui import theme
    mw = Gui.getMainWindow()
    panel = sb.panel()
    theme.set_overrides(light=NX_TOKENS, lanes_light=[NX_TOKENS["accent"]] + list(theme.LANES_LIGHT[1:]))
    # a navigator like the others: in the left tab strip, behind the Part Navigator (NX opens with that)
    model = mw.findChild(QtWidgets.QDockWidget, "Model")
    if model is not None and not panel.isFloating():
        mw.tabifyDockWidget(model, panel)
        # the tab stays in the strip, like the other navigators. Strata before 392952b saved its panel
        # as hidden when another tab was raised or FreeCAD closed, so profiles from then start it
        # hidden; show() repairs that and (since 392952b) does not change Strata's saved choice
        panel.show()
        model.raise_()
    # Strata's own QActions (enabled with the active project) on the resource bar and the PLM tab
    acts = sb.actions()
    ribbon.HOST_ACTIONS.update(acts)
    act = acts.get("Strata_Panel")
    if act is not None and getattr(shell, "resource_bar", None) is not None:
        shell.resource_bar.addAction(act)
        shell.resource_actions[act.text()] = act
        _state["action"] = act
    if getattr(shell, "current_app", None):
        shell.build_ribbon(shell.current_app)   # the PLM buttons now have actions to mirror
    # FreeCAD's view commands get their default keys (Home, End, Ctrl+Alt+F ...) back while Strata
    # starts, even with Strata in host mode (measured 2026-10-12; which step does it is not known):
    # take the NX keys back, as NXStyle does after any late-loading workbench. Strata 0.2.0+ binds its
    # own keys only once its Tools-menu entries exist, which in host mode is activate_commands()
    if hasattr(sb, "activate_commands"):
        sb.activate_commands()
    shell._reclaim_keys()
    if not _state.get("configured_early"):
        # Strata started before NXStyle could configure it: its toolbar and the moved panel
        shell.enforce_ui()
        QtCore.QTimer.singleShot(0, shell.hide_stray_tab_bars)
    _state["placed"] = True
    App.Console.PrintLog("NXStyle: Strata placed as data management\n")
