# SPDX-License-Identifier: LGPL-2.1-or-later
"""LCInterlocking's task panels on Qt 6 (FreeCAD 1.1), for an upstream copy of the add-on.

NXStyle bundles a fork (github.com/Foadsf/LCInterlocking) that has these two fixes. An upstream
LCInterlocking (github.com/execuc/LCInterlocking), such as one the Addon Manager installed into the NX
profile, which the launcher then uses instead of the bundled fork, still has them broken on PySide6:

* TreePanel.getStandardButtons returns int(Ok | Cancel); PySide6 flags are enums, so int() raises a
  TypeError each time the Tabs and Slots or Cross Halving panel opens (upstream issue 78);
* TreePanel.force_selection(None), after Add parts or Add faces with nothing selected, raises a TypeError
  (upstream issue 75).

install() wraps both methods when LCInterlocking's panel.treepanel module is imported, or at once if it
already is. The wrappers call the add-on's own method first, so a fixed copy is left as it is.
No FreeCAD import here: the tests run it on a stand-in module.
"""

import importlib.abc
import os
import sys

MODULE = "panel.treepanel"          # LCInterlocking's own top-level package names
MARK = "_nxstyle_qt6"


def is_lcinterlocking(mod):
    """panel.treepanel is a generic name: only LCInterlocking's has lasercut/join.py beside its package."""
    path = getattr(mod, "__file__", None) or ""
    root = os.path.dirname(os.path.dirname(os.path.abspath(path))) if path else ""
    return bool(root) and os.path.isfile(os.path.join(root, "lasercut", "join.py"))


def patch(mod):
    """Wrap TreePanel's two methods in LCInterlocking's panel.treepanel. True when patched (now or before)."""
    cls = getattr(mod, "TreePanel", None)
    if cls is None or not is_lcinterlocking(mod) or not all(
            hasattr(cls, m) for m in ("getStandardButtons", "force_selection")):
        return False
    if getattr(cls, MARK, False):
        return True
    buttons, select = cls.getStandardButtons, cls.force_selection

    def getStandardButtons(self):
        try:
            return buttons(self)
        except TypeError:           # int() of a PySide6 enum flag
            box = mod.QtGui.QDialogButtonBox
            flags = box.Ok | box.Cancel
            return int(getattr(flags, "value", flags))

    def force_selection(self, index):
        try:
            return select(self, index)
        except TypeError:
            if index is None:       # nothing was added; PySide6 refuses None
                return None
            raise

    cls.getStandardButtons = getStandardButtons
    cls.force_selection = force_selection
    setattr(cls, MARK, True)
    return True


class _Loader(importlib.abc.Loader):
    """The module's own loader, then the patch."""

    def __init__(self, inner):
        self.inner = inner

    def create_module(self, spec):
        return self.inner.create_module(spec)

    def exec_module(self, module):
        self.inner.exec_module(module)
        patch(module)


class _Finder(importlib.abc.MetaPathFinder):
    """Finds panel.treepanel the usual way and hands it to _Loader."""

    def find_spec(self, fullname, path, target=None):
        if fullname != MODULE:
            return None
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(fullname, path, target)
            if spec is not None:
                if spec.loader is not None and hasattr(spec.loader, "exec_module"):
                    spec.loader = _Loader(spec.loader)
                return spec
        return None


def install():
    """Patch LCInterlocking's task panels now if loaded, else when they are first imported. Idempotent."""
    if MODULE in sys.modules:
        patch(sys.modules[MODULE])
    if not any(isinstance(f, _Finder) for f in sys.meta_path):
        sys.meta_path.insert(0, _Finder())


def uninstall():
    """Remove the import hook (the tests' clean-up); patched classes stay patched."""
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, _Finder)]
