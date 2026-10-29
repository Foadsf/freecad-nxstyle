# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD-Nxt (github.com/obelisk79/FreeCAD-Nxt, LGPL-2.1) next to NXStyle: off by default, on with --nxt or
"nxt": true. Nxt stays unforked: NXStyle sets Nxt's own preferences in the NX profile, gives its words NX's
names through a Qt translator, adds to its menu through its menus.register(), and arranges its panel.

FreeCAD runs the classic Mod InitGui.py files (NXStyle's) before the freecad.* namespace packages (Nxt's
freecad.nxt.init_gui), so what prepare() writes and installs is in place when Nxt starts. Once Nxt's panel is
up, tick() makes it the Part Navigator (nxt_navigator.py) and settles the keys both handle:

- Home and End are NX's Trimetric and Isometric views, also while Nxt's tree has the focus (Nxt keeps them
  there to move its selection to the first or last row). F2 in Nxt's tree renames there.
- Space in the graphics window stays FreeCAD's Show/Hide (Std_ToggleVisibility), as with Nxt off; Nxt's own
  Space there (tools/visibility.SpaceInView) is taken out. In Nxt's tree Space still toggles the row's eye.
- Nxt's Fillet/Chamfer toolbar stays hidden like FreeCAD's toolbars; its commands are in Menu > View >
  FreeCAD-Nxt.
"""

import os

import FreeCAD as App

from . import config
from .qt import QtCore, QtWidgets, Qt

GROUP = "User parameter:BaseApp/Preferences/Mod/Nxt"   # Nxt's core/settings.py GROUP
TOOLBAR = "NxtTesting"                                  # Nxt's app/test_toolbar.py NAME
NAMES = config.resource("nxt", "nx_names.qm")
MENU = config.resource("nxt", "nx_menu.toml")
NX_VIEW_KEYS = (Qt.Key_Home, Qt.Key_End)

_translator = None
_navigator = None
_keys = None
_toolbar_hooked = False


def expected():
    """The launcher loads Nxt (bundled, or a copy in the NX profile) when this is set."""
    return os.environ.get("NXSTYLE_NXT_EXPECTED", "0") == "1"


def loaded():
    import sys
    return "freecad.nxt" in sys.modules


def prepare():
    """Before Nxt starts. Its addon update check (app/update_check.py) looks for updates of every installed add-on
    and opens the Addon Manager's Update All dialog; in the NX profile the bundled add-ons are pinned submodules,
    so the check is switched off with Nxt's own CheckAddonUpdates. NX's names for Nxt's words are installed now,
    so Nxt's panel takes its title (Part Navigator) when it is made."""
    if not expected():
        return
    App.ParamGet(GROUP).SetBool("CheckAddonUpdates", False)
    install_names()


def install_names():
    global _translator
    if _translator is not None:
        return True
    tr = QtCore.QTranslator(QtWidgets.QApplication.instance())
    if not tr.load(NAMES):
        App.Console.PrintWarning(f"NXStyle: could not load {NAMES}; Nxt keeps its own names\n")
        return False
    QtCore.QCoreApplication.installTranslator(tr)
    _translator = tr
    return True


def navigator():
    """The Part Navigator built on Nxt's panel (nxt_navigator.Navigator), or None while Nxt is off or not up."""
    return _navigator


def navigator_dock():
    return _navigator.dock if _navigator is not None else None


def tick(shell):
    """From the shell's tick: hide Nxt's toolbar as soon as Nxt has made it; once Nxt's panel exists, make it the
    Part Navigator and settle the keys."""
    global _navigator, _toolbar_hooked
    if not expected() or not loaded():
        return _navigator
    if not _toolbar_hooked:
        try:
            _toolbar_hooked = _hide_toolbar(shell)
        except Exception as e:
            _toolbar_hooked = True
            problems.append(repr(e))
    if _navigator is not None:
        return _navigator
    from . import nxt_navigator
    try:
        nav = nxt_navigator.adopt(shell)
    except Exception as e:
        App.Console.PrintWarning(f"NXStyle: Nxt's panel as the Part Navigator: {e}\n")
        nav = None
    if nav is None:
        return None
    _navigator = nav
    for step in (_register_menu, lambda: _settle_keys(nav)):
        try:
            step()
        except Exception as e:
            problems.append(repr(e))
            App.Console.PrintWarning(f"NXStyle: Nxt: {e}\n")
    return nav


problems = []           # what failed while arranging Nxt (for the self-test)


def _register_menu():
    from freecad.nxt import menus
    menus.register(MENU)


class _NxKeys(QtCore.QObject):
    """Keys in Nxt's tree, decided before Qt's shortcuts see them (ShortcutOverride):
    - Home and End: Nxt's QML claims them; keeping the event from it lets NX's Std_ViewTrimetric and
      Std_ViewIsometric run, as everywhere else.
    - F2: Nxt's QML renames on it but does not claim it, and without the claim the key never reached it (measured:
      the focus stayed on the row); claiming it hands the key to Nxt's tree."""

    def eventFilter(self, obj, ev):
        if ev.type() != QtCore.QEvent.ShortcutOverride or ev.modifiers() & (
                Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if ev.key() in NX_VIEW_KEYS:
            ev.ignore()
            return True
        if ev.key() == Qt.Key_F2:
            ev.accept()
            return True
        return False


def _settle_keys(nav):
    global _keys
    _keys = _NxKeys(nav)
    nav.tree.installEventFilter(_keys)
    from freecad.nxt.app import services
    live = services.instance()
    space = getattr(live, "_space", None)
    if space is not None:
        space.remove()
        live._space = None


def _hide_toolbar(shell):
    """Nxt makes and shows its toolbar from a timer after each workbench switch, after the shell has hidden
    FreeCAD's; making it now (Nxt's own test_toolbar._toolbar) lets the shell hook it like FreeCAD's: hidden
    whenever Nxt shows it. True once hooked."""
    from freecad.nxt.app import test_toolbar
    if test_toolbar._toolbar() is None:
        return False
    shell.enforce_ui()
    return True
