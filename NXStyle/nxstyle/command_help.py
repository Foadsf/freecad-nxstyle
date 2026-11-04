# SPDX-License-Identifier: LGPL-2.1-or-later
"""Live keyboard help for native commands and their NXStyle aliases.

Import action/shortcut adapters lazily: ribbon and shortcuts both use this
module, and neither a static key table nor a menu proxy owns a binding.
"""

from html import escape

from .qt import QtCore, QtWidgets

FINDER_COMMAND = "NXStyle_CommandFinder"


def plain(text):
    return str(text or "").split("\t", 1)[0].replace("&&", "\0").replace("&", "").replace("\0", "&").replace("...", "").strip()


def action_shortcuts(action):
    """All sequences actually assigned to an action, without empty entries."""
    try:
        return [seq.toString() for seq in action.shortcuts() if not seq.isEmpty()]
    except (AttributeError, RuntimeError):
        return []


def shortcut_text(name, action=None):
    """Native sequences plus active manager aliases, deduplicated in order."""
    if action is None and name:
        from .ribbon import command_action
        action = command_action(name)
    keys = action_shortcuts(action)
    try:
        from . import shortcuts
        manager = shortcuts.instance()
        if manager is not None:
            keys += list(manager.shortcuts_for(name))
    except (ImportError, AttributeError, RuntimeError):
        pass
    return ", ".join(dict.fromkeys(key for key in keys if key))


def finder_route():
    keys = shortcut_text(FINDER_COMMAND)
    return f"Command Finder ({keys})" if keys else "Command Finder (no keyboard shortcut assigned)"


def _current_entry(name, action):
    from .ribbon import command_actions
    entries = command_actions(name) if name else []
    if not entries or action is entries[0]:
        return None
    group = entries[0].actionGroup()
    owner = group.parent() if group is not None else None
    try:
        index = owner.property("defaultAction") if owner is not None else None
        return entries[index] if isinstance(index, int) and 0 <= index < len(entries) else None
    except RuntimeError:
        return None


def command_tooltip(name, label, action=None, description=""):
    """Escaped rich text, including current group entry and reachable keys."""
    if action is None and name:
        from .ribbon import command_action
        action = command_action(name)
    native = plain(action.text()) if action is not None else ""
    tip = str((action.toolTip() if action is not None else description) or "").strip()
    lines = [f"<b>{escape(str(label))}</b>"]
    if native and native != label:
        lines.append("FreeCAD: " + escape(native))
    keys = shortcut_text(name, action)
    lines.append("Shortcut: " + escape(keys) if keys else "No direct shortcut assigned")
    current = _current_entry(name, action)
    if current is not None:
        current_keys = shortcut_text(current.objectName(), current)
        detail = plain(current.text())
        if current_keys:
            detail += f" ({current_keys})"
        lines.append("Current command: " + escape(detail))
    if not keys:
        lines.append("Keyboard: " + escape(finder_route()) + "; type the command name")
    if tip and tip != native:
        lines.append(escape(tip).replace("\n", "<br>"))
    return "<br>".join(lines)


def proxy_help(action, name, label, source=None):
    """Show keys as menu text; do not register a duplicate QAction shortcut."""
    keys = shortcut_text(name, source)
    action.setText(label + ("\t" + keys if keys else ""))
    action.setToolTip(command_tooltip(name, label, source))
    action.setProperty("nxHelpCommand", name)
    action.setProperty("nxHelpLabel", label)


class _MenuHelp(QtCore.QObject):
    def refresh(self):
        menu = self.parent()
        for action in menu.actions():
            name, label = action.property("nxHelpCommand"), action.property("nxHelpLabel")
            if name and label:
                proxy_help(action, name, label)
            if action.menu() is not None:
                bind_menu_help(action.menu(), plain(action.text()))

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.ToolTip:
            action = watched.actionAt(event.pos())
            if action is not None and not action.isSeparator():
                name = action.property("nxHelpCommand") or action.objectName()
                label = action.property("nxHelpLabel") or plain(action.text())
                tip = command_tooltip(name, label, None if action.property("nxHelpCommand") else action)
                QtWidgets.QToolTip.showText(event.globalPos(), tip, watched)
                return True
        return super().eventFilter(watched, event)


def bind_menu_help(menu, label="Commands"):
    """Keep native menu actions/labels intact and resolve their help on hover."""
    if not menu.accessibleName():
        menu.setAccessibleName(label)
    if not hasattr(menu, "_nx_command_help"):
        helper = _MenuHelp(menu)
        menu._nx_command_help = helper
        menu.installEventFilter(helper)
        menu.aboutToShow.connect(helper.refresh)
        helper.refresh()
