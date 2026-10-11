# SPDX-License-Identifier: LGPL-2.1-or-later
"""Qt shims so the same code runs on FreeCAD 1.0 (PySide2) and 1.1+ (PySide6)."""

from PySide import QtCore, QtGui  # FreeCAD's own PySide wrapper

try:
    from PySide import QtWidgets
except ImportError:  # very old wrappers put widgets in QtGui
    QtWidgets = QtGui

QAction = getattr(QtGui, "QAction", None) or QtWidgets.QAction
Qt = QtCore.Qt


def pos(ev):
    """Widget-local mouse position as QPoint (PySide6 deprecates ev.pos())."""
    if hasattr(ev, "position"):
        return ev.position().toPoint()
    return ev.pos()


def global_pos(ev):
    if hasattr(ev, "globalPosition"):
        return ev.globalPosition().toPoint()
    return ev.globalPos()


def exec_menu(menu, at):
    run = getattr(menu, "exec", None) or getattr(menu, "exec_")
    return run(at)


def exec_dialog(dlg):
    run = getattr(dlg, "exec", None) or getattr(dlg, "exec_")
    return run()


def mouse_event(kind, local, button, buttons, modifiers):
    """Build a QMouseEvent that works with both Qt5 and Qt6 constructors."""
    localf = QtCore.QPointF(local)
    try:
        return QtGui.QMouseEvent(kind, localf, localf, button, buttons, modifiers)
    except TypeError:
        return QtGui.QMouseEvent(kind, local, button, buttons, modifiers)


def color(hexstr):
    return QtGui.QColor(hexstr)
