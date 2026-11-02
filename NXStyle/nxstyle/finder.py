# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX-style Command Finder: type a name, see where the command lives, run it."""

import FreeCADGui as Gui

from .qt import QtCore, QtGui, QtWidgets, Qt
from . import icon_theme
from .ribbon import clean_text, command_action

ROLE_CMD = Qt.UserRole + 1


class CommandFinder(QtWidgets.QLineEdit):
    def __init__(self, ribbon, parent=None, on_run=None):
        super().__init__(parent)
        self.ribbon = ribbon
        self.on_run = on_run
        self.setObjectName("NXCommandFinder")
        self.setPlaceholderText("Command Finder")
        self.setClearButtonEnabled(True)
        self.model = QtGui.QStandardItemModel(self)
        self.completer = QtWidgets.QCompleter(self.model, self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.completer.setCompletionRole(Qt.DisplayRole)
        self.completer.setMaxVisibleItems(14)
        self.completer.popup().setIconSize(QtCore.QSize(16, 16))
        self.setCompleter(self.completer)
        self.completer.activated[QtCore.QModelIndex].connect(self._activated)
        self.returnPressed.connect(self._return)
        self._dirty = True
        self._busy = False

    def invalidate(self):
        self._dirty = True

    def focusInEvent(self, ev):
        if self._dirty:
            self.rebuild()
        super().focusInEvent(ev)

    def rebuild(self):
        self.model.clear()
        locations = self.ribbon.locations
        labels = self.ribbon.labels
        for name in sorted(Gui.listCommands()):
            act = command_action(name)
            if act is not None:
                icon, fc_text = act.icon(), clean_text(act.text())
                shortcut, tip = act.shortcut().toString(), clean_text(act.toolTip() or "")
            elif name in labels:
                # on the ribbon, but FreeCAD made no action for it (it sits in none of FreeCAD's toolbars,
                # e.g. Sketcher_ConstrainPointOnObject in 1.1): the command's own text and icon
                info = Gui.Command.get(name).getInfo()
                icon = icon_theme.icon(name, Gui.getIcon(info.get("pixmap") or "") or QtGui.QIcon())
                fc_text, shortcut, tip = clean_text(info.get("menuText", "")), "", clean_text(info.get("toolTip", ""))
            else:
                continue
            if not fc_text:
                continue
            nx = labels.get(name)
            where = locations.get(name, "Menu")
            title = nx or fc_text
            extra = f" ({fc_text})" if nx and nx != fc_text else ""
            text = f"{title}{extra}  —  {where}" + (f"  [{shortcut}]" if shortcut else "")
            item = QtGui.QStandardItem(icon, text)
            item.setData(name, ROLE_CMD)
            item.setToolTip(tip)
            self.model.appendRow(item)
        self._dirty = False

    def find(self, text):
        """Command names whose entry contains text (used by tests and Enter)."""
        if self._dirty:
            self.rebuild()
        text = text.lower()
        out = []
        for row in range(self.model.rowCount()):
            item = self.model.item(row)
            if text in item.text().lower():
                out.append(item.data(ROLE_CMD))
        return out

    def _run(self, name):
        if not name or self._busy:
            return
        # Choosing from the popup with Enter fires both activated and returnPressed
        self._busy = True
        QtCore.QTimer.singleShot(50, lambda: setattr(self, "_busy", False))
        # Enter reaches returnPressed before the completer hides its popup; a popup left open stays the
        # active popup and takes keys (Esc) meant for the command that starts now.
        self.completer.popup().hide()
        if self.on_run:
            self.on_run(name)
        QtCore.QTimer.singleShot(0, lambda: Gui.runCommand(name))
        QtCore.QTimer.singleShot(0, self.clear)

    def _activated(self, index):
        # The popup model is a proxy; map the text back to our item.
        text = index.data(Qt.DisplayRole)
        for row in range(self.model.rowCount()):
            item = self.model.item(row)
            if item.text() == text:
                self._run(item.data(ROLE_CMD))
                return

    def _return(self):
        hits = self.find(self.text())
        if hits:
            self._run(hits[0])
