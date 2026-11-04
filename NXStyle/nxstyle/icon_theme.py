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


# A binding's state lives in plain Python objects held here, never as attributes of a Qt object found again through
# Qt. Issue #53: on FreeCAD 26.3 (PySide6 6.11) the QObject child that used to hold it came back from findChild() as
# a 'Binding' without its Python attributes ('no attribute busy'): the wrapper PySide hands out for a Qt object is
# not guaranteed to be the one whose attributes were set. Qt keeps only the key, a dynamic property of the action.
BINDING_KEY = "nxstyleIconBinding"
_bindings = {}
_next_key = [0]


class _Binding:
    """The native icon of one action and what it shows instead; plain Python, so nothing Qt or PySide does to a
    wrapper can take this state away. All fields are set before the action's signal is connected."""

    def __init__(self, key, action, command, entries, owner):
        self.key, self.action, self.command = key, action, command
        self.entries, self.owner = entries, owner
        self.native = action.icon()
        self.last = self.native.cacheKey()
        self.busy = False
        action.changed.connect(self.sync)
        action.destroyed.connect(lambda *_args, key=key: _bindings.pop(key, None))

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
        except RuntimeError:               # the action was deleted by FreeCAD (a workbench reload)
            _bindings.pop(self.key, None)
        finally:
            self.busy = False


def binding_of(action):
    """The binding of an action, or None; found through the key Qt keeps on the action."""
    key = action.property(BINDING_KEY)
    return _bindings.get(key) if isinstance(key, int) else None


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
    binding = binding_of(action)
    if binding is None:
        _next_key[0] += 1
        key = _next_key[0]
        action.setProperty(BINDING_KEY, key)
        binding = _bindings[key] = _Binding(key, action, command, entries, owner)
    else:
        binding.entries, binding.owner = entries, owner
    binding.sync()
    return action
