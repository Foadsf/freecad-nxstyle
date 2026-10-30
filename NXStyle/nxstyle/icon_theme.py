# SPDX-License-Identifier: LGPL-2.1-or-later
"""Original NX-inspired artwork on the existing command actions, never new commands.

The catalogue is Qt/FreeCAD-independent. Rendering and action bindings are lazy,
so catalogue checks also run in ordinary Python. Each binding belongs to its
QAction and follows native icon changes without touching dispatch or state.
"""

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "resources"
_icons = {}
_binding_class = None


@lru_cache(maxsize=1)
def catalogue():
    """Command name -> artwork stem; one source for aliases and coverage."""
    with (ROOT / "icon-theme.json").open(encoding="utf-8") as f:
        groups = json.load(f)
    return {command: stem for stem, commands in groups.items() for command in commands}


def asset_path(command):
    stem = catalogue().get(command)
    if stem is None:
        return None
    path = ROOT / "icons" / "nx" / (stem + ".svg")
    return path if path.is_file() else None


def enabled():
    from . import config
    return config.get().get("icon_theme", "nx") == "nx"


def icon(command, fallback):
    """Keep the exact native fallback for unmapped, absent or unrenderable assets."""
    if not enabled():
        return fallback
    path = asset_path(command)
    if path is None:
        return fallback
    key = str(path)
    if key not in _icons:
        from .qt import QtGui
        candidate = QtGui.QIcon(key)
        # QIcon.isNull alone can be false for a malformed SVG on some Qt builds.
        _icons[key] = candidate if not candidate.pixmap(16, 16).isNull() else None
    return _icons[key] if _icons[key] is not None else fallback


def _type():
    global _binding_class
    if _binding_class is not None:
        return _binding_class
    from .qt import QtCore

    class Binding(QtCore.QObject):
        def __init__(self, action, command, entries, owner):
            super().__init__(action)
            self.setObjectName("NXStyleIconBinding")
            self.action, self.command = action, command
            self.entries, self.owner = entries, owner
            self.native = action.icon()
            self.last = self.native.cacheKey()
            self.busy = False
            action.changed.connect(self.sync)

        def sync(self):
            if self.busy:
                return
            self.busy = True
            try:
                current = self.action.icon()
                if current.cacheKey() != self.last:
                    self.native = current      # host changed the icon, not just enabled/checked
                if self.entries is not None:
                    # Group buttons must show the remembered entry, even when it has
                    # no artwork. Never label another command with the first entry's icon.
                    index = self.owner.property("defaultAction")
                    if isinstance(index, int) and 0 <= index < len(self.entries):
                        wanted = self.entries[index].icon()
                    else:
                        wanted = self.native
                else:
                    wanted = icon(self.command, self.native)
                self.last = wanted.cacheKey()
                if current.cacheKey() != self.last:
                    self.action.setIcon(wanted)
            finally:
                self.busy = False

    _binding_class = Binding
    return Binding


def bind(action, command, entries=None, owner=None):
    """Decorate a materialized action once; late workbench actions use the same path."""
    if action is None:
        return action
    # Unmapped commands are untouched. A group is bound only if at least one of
    # its entries is mapped; its own icon follows the current entry thereafter.
    if entries is None and command not in catalogue():
        return action
    if entries is not None and not any(a.objectName() in catalogue() for a in entries):
        return action
    from .qt import QtCore
    binding = action.findChild(QtCore.QObject, "NXStyleIconBinding")
    if binding is None:
        binding = _type()(action, command, entries, owner)
    else:
        binding.entries, binding.owner = entries, owner
    binding.sync()
    return action
