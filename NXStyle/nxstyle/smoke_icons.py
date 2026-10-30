# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native FreeCAD icon integration checks, called by the normal smoke harness."""
from . import config, icon_theme
from .qt import QtGui, QtWidgets
from .ribbon import CommandButton, command_action, command_actions


def run(smoke):
    cfg = config.get()
    before = cfg.get("icon_theme", "nx")
    actions = []
    for name in icon_theme.catalogue():
        action = command_action(name)
        if action is not None:
            actions.append((name, action))
    smoke.check("icon theme: mapped commands materialize", len(actions) > 30, len(actions))
    # Snapshot nonvisual properties and an independent unknown-command fallback.
    def state(a):
        return (a.isEnabled(), a.isCheckable(), a.isChecked(), a.text(), a.toolTip(), a.shortcut().toString())
    states = [(a, state(a)) for _, a in actions]
    native = {}
    try:
        cfg["icon_theme"] = "freecad"
        for name, a in actions:
            command_action(name)
            native[name] = a.icon().cacheKey()
        cfg["icon_theme"] = "nx"
        for name, _ in actions:
            command_action(name)
        smoke.check("icon theme: artwork replaces native icons",
                    all(a.icon().cacheKey() != native[n] for n, a in actions),
                    [n for n, a in actions if a.icon().cacheKey() == native[n]])
        smoke.check("icon theme: commands keep state, label, tooltip and shortcut",
                    all(state(a) == original for a, original in states))
        fallback = QtGui.QIcon()
        smoke.check("icon theme: unknown command retains native fallback",
                    icon_theme.icon("NXStyle_NoSuchIcon", fallback) is fallback)
        buttons = smoke.shell.ribbon.findChildren(CommandButton)
        mapped = [b for b in buttons if b.command in icon_theme.catalogue() and b.action is not None]
        smoke.check("icon theme: ribbon follows shared actions", bool(mapped) and
                    all(b.icon().cacheKey() == b.action.icon().cacheKey() for b in mapped), len(mapped))
        smoke.shell.finder.rebuild()
        from .finder import ROLE_CMD
        model = smoke.shell.finder.model
        found = [model.item(i) for i in range(model.rowCount())
                 if model.item(i).data(ROLE_CMD) == "PartDesign_Pad"]
        pad = command_action("PartDesign_Pad")
        smoke.check("icon theme: finder shares Extrude action icon", bool(found) and pad is not None and
                    found[0].icon().cacheKey() == pad.icon().cacheKey())
        group = command_action("Sketcher_CompCreateBSpline")
        entries = command_actions("Sketcher_CompCreateBSpline")
        owner = entries[0].actionGroup().parent() if entries else None
        index = owner.property("defaultAction") if owner is not None else None
        smoke.check("icon theme: grouped tool shows remembered entry", group is not None and
                    isinstance(index, int) and 0 <= index < len(entries) and
                    group.icon().cacheKey() == entries[index].icon().cacheKey(), index)
        cfg["icon_theme"] = "freecad"
        for name, _ in actions:
            command_action(name)
        smoke.check("icon theme: native icons restored", all(a.icon().cacheKey() == native[n] for n, a in actions))
    finally:
        cfg["icon_theme"] = before
        for name, _ in actions:
            command_action(name)
        # Refresh groups after their child icons have been restored.
        command_action("Sketcher_CompCreateBSpline")
        smoke.shell.finder.invalidate()
    # A native widget capture is also useful when a command is disabled.
    for widget in smoke.shell.ribbon.findChildren(QtWidgets.QToolButton):
        widget.update()
