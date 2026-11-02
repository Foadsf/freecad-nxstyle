# SPDX-License-Identifier: LGPL-2.1-or-later
"""The user's own macro commands on the Tools › Macros ribbon group (no FreeCAD needed here).

A macro becomes a command in FreeCAD's Tools › Customize › Macros: FreeCAD names it ``Std_Macro_<n>``
(``Std_Macro_0``, ``Std_Macro_1``, ...; DlgCustomActionsImp::newActionName) and keeps it in the profile's
``BaseApp/Macro/Macros`` parameters, with the menu text the user gave it. The built-in debugger commands
(``Std_MacroStartDebug``, ``Std_MacroStepInto``, ...) have no underscore after ``Macro`` and so never match.
"""

import re

PREFIX = "Std_Macro_"
_NUMBERED = re.compile(r"^Std_Macro_(\d+)$")


def _order(name):
    """Std_Macro_2 before Std_Macro_10: the order the user made them in."""
    m = _NUMBERED.match(name)
    return (0, int(m.group(1)), "") if m else (1, 0, name)


def user_commands(known):
    """The user's own macro command names from the known FreeCAD commands (any iterable), oldest first."""
    return sorted((n for n in known if n.startswith(PREFIX)), key=_order)


def label(name, text=None):
    """The button label for a macro command: the menu text the user gave it, else what follows the prefix."""
    text = (text or "").replace("&", "").strip()
    if text:
        return text
    return name[len(PREFIX):] if name.startswith(PREFIX) else name


def items_for(known, text=lambda name: None):
    """The ribbon items of the user's own macros, one small button each. ``text(name)`` gives a command's
    menu text (FreeCAD's Gui.Command.get(name).getInfo()["menuText"]); None or "" falls back to the name."""
    return [{"cmd": name, "label": label(name, text(name)), "size": "small"} for name in user_commands(known)]
